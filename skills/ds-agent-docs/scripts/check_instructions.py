#!/usr/bin/env python3
"""Check, audit, stage, gate and apply instruction-file edits for one repository.

Commands (all accept --json and print one JSON object):

  check --repo R                    read-only survey: delivery state, budget, imports,
                                    references, Backpass leads
  audit --repo R [--scope P]        read-only cross-agent prompt-audit: inventory, context
                                    load, imports, references, structure, docs coverage
  stage --repo R --out S            copy the memory surface into an editable stage
  gate  --stage S --evidence E --claims C
                                    validate claims and evidence, write S/gate.json
  apply --stage S                   write the staged edit in place, or emit S/staged.patch

Exit codes: 0 ok, 1 blocked, 2 invalid or unsafe input. Only `apply` writes to a
repository. Stdlib only, Python 3.9+.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
GIT_STRIP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
EXIT_OK, EXIT_BLOCKED, EXIT_INVALID = 0, 1, 2
DEFAULT_SKILLS_DIR = ".agents/skills"
BRANCH_NAME = re.compile(r"\A[A-Za-z0-9._/-]+\Z")


def valid_branch(name):
    return (isinstance(name, str) and bool(name) and bool(BRANCH_NAME.match(name))
            and not name.startswith("-") and ".." not in name and "//" not in name)


def _load_collector():
    spec = importlib.util.spec_from_file_location(
        "collect_sessions_shared", str(HERE / "collect_sessions.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COLLECT = _load_collector()
redact = COLLECT.redact
fold = COLLECT.fold
is_correction = COLLECT.is_correction


def run_git(args, cwd):
    env = {key: value for key, value in os.environ.items() if key not in GIT_STRIP}
    try:
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True,
                              text=True, env=env)
    except (OSError, ValueError):
        return None


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest_file(path):
    try:
        return digest_bytes(Path(path).read_bytes())
    except OSError:
        return None


def tree_digest(directory):
    directory = Path(directory)
    items = []
    if directory.is_dir():
        for dirpath, dirnames, filenames in os.walk(str(directory)):
            dirnames.sort()
            for name in sorted(filenames):
                path = Path(dirpath) / name
                rel = os.path.relpath(str(path), str(directory))
                if os.path.islink(str(path)):
                    items.append(rel + "\0link:" + os.readlink(str(path)))
                else:
                    items.append(rel + "\0" + (digest_file(path) or ""))
    return digest_bytes("\n".join(sorted(items)).encode("utf-8"))


def _inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (OSError, ValueError):
        return False


def _path_escapes_root(root, rel, include_leaf=False):
    """True when rel is absolute, climbs out, or any ancestor is a symlink or escapes root."""
    rel = normalize_rel(rel)
    parts = Path(rel).parts
    if not parts or os.path.isabs(rel) or ".." in parts:
        return True
    root_real = os.path.realpath(str(root))
    current = Path(root)
    checked = parts if include_leaf else parts[:-1]
    for part in checked:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except (OSError, ValueError):
            return True
    target = Path(root) / rel
    try:
        Path(os.path.realpath(str(target))).relative_to(root_real)
    except (OSError, ValueError):
        return True
    return False


def outside_worktree(path):
    """True when path (and its real parent) is outside every git worktree."""
    parent = Path(path).parent
    try:
        parent = Path(os.path.realpath(str(parent)))
    except OSError:
        return False
    if not parent.is_dir():
        return False
    probe = parent
    while True:
        if probe.name == ".git":
            return False
        try:
            if (probe / ".git").exists():
                return False
        except OSError:
            pass
        if probe.parent == probe:
            break
        probe = probe.parent
    proc = run_git(["rev-parse", "--show-toplevel"], parent)
    return not (proc is not None and proc.returncode == 0 and proc.stdout.strip())


def skills_dir(root):
    config = Path(root) / ".backpassrc.json"
    value = None
    if config.is_file():
        try:
            data = json.loads(config.read_text("utf-8", "replace"))
        except ValueError:
            data = {}
        if isinstance(data, dict):
            value = data.get("skillsDir")
    if isinstance(value, str) and value.strip():
        candidate = value.strip().rstrip("/")
        if not os.path.isabs(candidate) and ".." not in Path(candidate).parts:
            try:
                if _inside(Path(root) / candidate, root) and \
                        not _path_escapes_root(root, candidate, include_leaf=True):
                    return candidate
            except OSError:
                pass
    return DEFAULT_SKILLS_DIR


def is_surface_path(rel, root):
    rel = normalize_rel(rel)
    parts = Path(rel).parts
    if ".git" in parts or ".backpass" in parts or ".worktrees" in parts:
        return False
    for index in range(len(parts) - 1):
        if parts[index] == ".claude" and parts[index + 1] == "worktrees":
            return False
    if rel in ("AGENTS.md", "CLAUDE.md"):
        return True
    if rel.endswith("/AGENTS.md") or rel.endswith("/CLAUDE.md"):
        return not _path_escapes_root(root, rel)
    prefix = skills_dir(root).rstrip("/") + "/"
    if rel.startswith(prefix):
        if _path_escapes_root(root, prefix.rstrip("/"), include_leaf=True) or \
                _path_escapes_root(root, rel):
            return False
        rest = rel[len(prefix):]
        return rest.count("/") == 1 and rest.endswith("/SKILL.md")
    return False


def surface_paths(root):
    root = Path(root)
    found = set()
    pruned_dirs = (".git", "node_modules", "__pycache__", ".venv", "graft",
                   ".mypy_cache", ".pytest_cache")
    for dirpath, dirnames, filenames in os.walk(str(root)):
        here = Path(dirpath)
        kept = []
        for name in sorted(dirnames):
            if name in pruned_dirs or name in (".backpass", ".worktrees"):
                continue
            if name == "worktrees" and here.name == ".claude":
                continue
            child = here / name
            try:
                if child.is_symlink():
                    continue
                if (child / ".git").exists() or (child / ".git").is_symlink():
                    continue
            except OSError:
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in ("AGENTS.md", "CLAUDE.md"):
            if name in filenames:
                found.add(os.path.relpath(os.path.join(dirpath, name), str(root)))
    skills_rel = skills_dir(root)
    skills = root / skills_rel
    if skills.is_dir() and not _path_escapes_root(root, skills_rel, include_leaf=True):
        try:
            children = sorted(skills.iterdir())
        except OSError:
            children = []
        for child in children:
            try:
                if child.is_symlink() or not _inside(child, root):
                    continue
            except OSError:
                continue
            if child.is_dir() and (child / "SKILL.md").is_file() and \
                    not (child / "SKILL.md").is_symlink():
                found.add(os.path.relpath(str(child / "SKILL.md"), str(root)))
    return sorted(found)


def surface_entries(root):
    root = Path(root)
    entries = []
    for rel in surface_paths(root):
        path = root / rel
        item = {"path": rel.replace(os.sep, "/")}
        if path.is_symlink():
            item["link"] = os.readlink(str(path))
        else:
            try:
                info = path.stat()
            except OSError:
                continue
            item["mode"] = stat.S_IMODE(info.st_mode)
            item["sha256"] = digest_file(path)
        entries.append(item)
    return entries


class Repo:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.is_git = False
        self.common = None
        self.worktrees = []
        self.head = ""
        self.current = ""
        self.default_branch = None
        if not self.root.is_dir():
            raise ValueError("repository path is not a directory")
        common = self._common_dir(self.root)
        if common is not None:
            self.is_git = True
            self.common = common
            proc = run_git(["rev-parse", "HEAD"], self.root)
            if proc is not None and proc.returncode == 0:
                self.head = proc.stdout.strip()
            proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"], self.root)
            if proc is not None and proc.returncode == 0:
                self.current = proc.stdout.strip()
            self.default_branch = self._default_branch()
            self.worktrees = self._worktrees()
        basis = self.common if self.common is not None else str(self.root)
        self.id = digest_bytes(basis.encode("utf-8", "replace"))

    @staticmethod
    def _common_dir(path):
        proc = run_git(["rev-parse", "--git-common-dir"], path)
        if proc is None or proc.returncode != 0 or not proc.stdout.strip():
            return None
        common = Path(proc.stdout.strip())
        if not common.is_absolute():
            common = Path(path) / common
        try:
            return str(common.resolve())
        except OSError:
            return os.path.abspath(str(common))

    def _default_branch(self):
        proc = run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], self.root)
        if proc is not None and proc.returncode == 0 and proc.stdout.strip():
            name = proc.stdout.strip().split("/", 1)[-1]
            if valid_branch(name):
                return name
        for name in ("main", "master"):
            proc = run_git(["show-ref", "--verify", "--quiet", "refs/heads/" + name], self.root)
            if proc is not None and proc.returncode == 0:
                return name
        proc = run_git(["config", "--get", "init.defaultBranch"], self.root)
        if proc is not None and proc.returncode == 0 and proc.stdout.strip():
            name = proc.stdout.strip()
            if valid_branch(name):
                proc = run_git(["show-ref", "--verify", "--quiet", "refs/heads/" + name],
                               self.root)
                if proc is not None and proc.returncode == 0:
                    return name
        return None

    def _worktrees(self):
        proc = run_git(["worktree", "list", "--porcelain"], self.root)
        if proc is None or proc.returncode != 0:
            return []
        found = []
        for line in proc.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            try:
                found.append(str(Path(line[len("worktree "):].strip()).resolve()))
            except OSError:
                found.append(line[len("worktree "):].strip())
        return found

    def main_checkout(self):
        return Path(self.worktrees[0]) if self.worktrees else self.root


def status_paths(root):
    proc = run_git(["status", "--porcelain"], root)
    if proc is None or proc.returncode != 0:
        return set()
    dirty = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty.add(path.strip().strip('"'))
    return dirty


PR_REQUIRE = re.compile(
    r"(?i)(\bmust\b|\brequires?\b|\brequired\b|\balways\b|\bonly\b|\buse\b|\bthrough\b|"
    r"\bvia\b|\bopen\b|\bgo through\b).{0,60}\b(pull request|PR)\b")
PR_FORBID = re.compile(
    r"(?i)(\bno\b|\bnever\b|\bnot\b|\bdon'?t\b|\bdo not\b|\bforbid\w*\b|\bmust not\b)"
    r".{0,60}\b(direct(?:ly)?\s+)?(push|commit)")


def has_pr_rule(root):
    for name in ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md"):
        path = Path(root) / name
        if not path.is_file():
            continue
        try:
            text = path.read_text("utf-8", "replace")
        except OSError:
            continue
        for line in text.splitlines():
            if PR_REQUIRE.search(line) or PR_FORBID.search(line):
                return True
    return False


def delivery_state(repo, entries):
    dirty = bool(status_paths(repo.root) & {entry["path"] for entry in entries})
    if dirty:
        return {"action": "patch_only", "reason": "dirty memory file", "dirty": True,
                "commands": []}
    if not repo.is_git:
        return {"action": "in_place", "reason": "not a git repository", "dirty": False,
                "commands": []}
    if repo.default_branch is None:
        return {"action": "patch_only", "reason": "unknown default branch", "dirty": False,
                "commands": []}
    if repo.current == "HEAD":
        return {"action": "worktree", "reason": "detached HEAD", "dirty": False,
                "commands": worktree_commands(repo)}
    if repo.current != repo.default_branch:
        return {"action": "in_place", "reason": "task branch", "dirty": False, "commands": []}
    if has_pr_rule(repo.root):
        return {"action": "worktree", "reason": "default branch with a written PR rule",
                "dirty": False, "commands": worktree_commands(repo)}
    return {"action": "in_place", "reason": "default branch without a written PR rule",
            "dirty": False, "commands": []}


def worktree_commands(repo):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = re.sub(r"[^A-Za-z0-9._-]", "-", repo.root.name) or "repo"
    branch = "docs/ds-sync-%s" % stamp
    if not valid_branch(repo.default_branch):
        return []
    location = ('"$HOME"' + shlex.quote(
        "/.local/state/ds-agent-docs/worktrees/%s-%s" % (name, stamp)))
    return [
        "git fetch origin -- %s" % shlex.quote(repo.default_branch),
        "git worktree add -b %s -- %s %s" % (
            shlex.quote(branch), location, shlex.quote("origin/" + repo.default_branch)),
    ]


def frontmatter_description(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    body = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    for index, line in enumerate(body):
        match = re.match(r"description:\s*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        if value in ("|", ">", "|-", ">-"):
            collected = []
            for extra in body[index + 1:]:
                if extra.startswith((" ", "\t")):
                    collected.append(extra.strip())
                elif not extra.strip():
                    continue
                else:
                    break
            return " ".join(collected)
        return value.strip('"\'')
    return ""


def budget_report(root):
    root = Path(root)
    total = 0
    seen = set()
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            info = os.stat(str(path))
        except OSError:
            continue
        key = (info.st_dev, info.st_ino)
        if key in seen:
            continue
        seen.add(key)
        try:
            total += len(path.read_bytes())
        except OSError:
            pass
    skills = root / skills_dir(root)
    if skills.is_dir():
        try:
            children = sorted(skills.iterdir())
        except OSError:
            children = []
        for child in children:
            manifest = child / "SKILL.md"
            if not manifest.is_file():
                continue
            try:
                text = manifest.read_text("utf-8", "replace")
            except OSError:
                continue
            total += len(frontmatter_description(text).encode("utf-8"))
    cap = 5000
    config = root / ".backpassrc.json"
    if config.is_file():
        try:
            data = json.loads(config.read_text("utf-8", "replace"))
        except ValueError:
            data = {}
        value = data.get("budgetTokens") if isinstance(data, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            cap = value
    tokens = int(math.ceil(total / 4.0))
    return {"tokens": tokens, "cap": cap, "over": tokens > cap}


def first_non_comment_line(text):
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("<!--"):
            while index < len(lines) and "-->" not in lines[index]:
                index += 1
            index += 1
            continue
        return index, stripped
    return None, None


def _read_memory(path, rel, links, fallback):
    try:
        if path.exists() or path.is_symlink():
            return path.read_text("utf-8", "replace")
    except OSError:
        return None
    if rel in links and fallback is not None:
        try:
            return (Path(fallback) / rel).read_text("utf-8", "replace")
        except OSError:
            return None
    return None


def check_imports(repo, links=None, fallback_root=None):
    root = Path(repo.root)
    links = dict(links or {})
    fallback = Path(fallback_root) if fallback_root is not None else None
    errors = []
    directories = set()
    for rel in surface_paths(root):
        path = Path(rel)
        if path.name == "AGENTS.md":
            directories.add(root / path.parent)
        elif path.name == "CLAUDE.md":
            directories.add(root / path.parent)
    for directory in sorted(directories, key=str):
        agents = directory / "AGENTS.md"
        claude = directory / "CLAUDE.md"
        rel_agents = os.path.relpath(str(agents), str(root)).replace(os.sep, "/")
        rel_claude = os.path.relpath(str(claude), str(root)).replace(os.sep, "/")
        agents_link = links.get(rel_agents)
        claude_link = links.get(rel_claude)
        agents_present = agents.exists() or agents.is_symlink() or agents_link is not None
        claude_present = claude.exists() or claude.is_symlink() or claude_link is not None
        if not agents_present:
            if claude_present or directory == root:
                errors.append({"file": rel_agents, "error": "missing AGENTS.md"})
            continue
        if not claude_present:
            errors.append({"file": rel_claude, "error": "missing CLAUDE.md import"})
            continue
        if claude.is_symlink() or claude_link is not None:
            target = os.readlink(str(claude)) if claude.is_symlink() else str(claude_link)
            candidate = os.path.normpath(os.path.join(str(directory), target))
            try:
                same = os.path.realpath(candidate) == os.path.realpath(str(agents))
            except OSError:
                same = False
            if not same:
                errors.append({"file": rel_claude, "error": "symlink points elsewhere"})
            continue
        text = _read_memory(claude, rel_claude, links, fallback)
        if text is None:
            errors.append({"file": rel_claude, "error": "unreadable CLAUDE.md"})
            continue
        if re.search(r"`\s*@AGENTS\.md\s*`", text):
            errors.append({"file": rel_claude, "error": "backticked import"})
        _index, first = first_non_comment_line(text)
        if first != "@AGENTS.md":
            errors.append({"file": rel_claude, "error": "missing @AGENTS.md import"})
        agents_text = _read_memory(agents, rel_agents, links, fallback) or ""
        agents_lines = {line.strip() for line in agents_text.splitlines()
                        if len(line.strip()) >= 4 and not line.strip().startswith("#")}
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped == "@AGENTS.md" or len(stripped) < 4 or stripped.startswith("#"):
                continue
            if stripped.startswith("<!--") or stripped.startswith("```"):
                continue
            if stripped in agents_lines:
                errors.append({"file": rel_claude, "line": number,
                               "error": "line duplicated from AGENTS.md"})
    return {"ok": not errors, "errors": errors}


BACKTICK = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")
SHELL_FENCE = re.compile(r"```(?:sh|bash|zsh|shell|console)\n(.*?)```", re.S | re.I)
PLACEHOLDER = re.compile(r"[<>{}\[\]*?]")
URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
TRACKED_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,8}$")
COMMON_CLIS = {
    "git", "gh", "docker", "kubectl", "terraform", "brew", "cargo", "go", "python",
    "python3", "node", "npm", "npx", "pnpm", "yarn", "bun", "make", "bash", "sh", "zsh",
    "source", "pytest", "uv", "pip", "pip3", "deno", "ruby", "bundle", "rails", "perl",
    "php", "composer", "dotnet", "java", "mvn", "gradle", "ls", "cat", "grep", "rg", "sed",
    "awk", "find", "curl", "wget", "jq", "yq", "tar", "zip", "unzip", "chmod", "mkdir",
    "cp", "mv", "rm", "echo", "printf", "env", "which", "test", "diff", "rsync", "ssh",
    "scp", "open", "pbcopy", "lsof", "timeout", "zstd",
}
SCRIPT_RUNNERS = {"bash", "sh", "zsh", "source", "python", "python3", "node", "deno",
                  "ruby", "perl", "php", "uv", "pytest"}
PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
PACKAGE_BUILTINS = {"install", "i", "add", "remove", "rm", "uninstall", "update", "upgrade",
                    "ci", "init", "create", "publish", "pack", "link", "audit", "why",
                    "outdated", "prune", "dedupe", "list", "ls", "view", "info", "search",
                    "login", "logout", "config", "cache", "store", "workspace", "workspaces"}
NUMERIC_SUFFIX = re.compile(r":\d+(?::\d+)?$")
ANCHOR_SUFFIX = re.compile(r"#.*$")
TRAILING = ".,;:!?)]}\"'"


def strip_reference(value):
    value = value.strip()
    value = NUMERIC_SUFFIX.sub("", value)
    value = ANCHOR_SUFFIX.sub("", value)
    return value.rstrip(TRAILING).strip()


def normalize_rel(value):
    value = str(value).replace(os.sep, "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def looks_like_path(value):
    if value.startswith(".") and "." in value[1:]:
        return True
    return "/" in value or bool(TRACKED_SUFFIX.search(value))


def probable_command(value):
    tokens = value.split()
    if not tokens:
        return False
    return (tokens[0] in COMMON_CLIS or tokens[0] in PACKAGE_MANAGERS
            or tokens[0] in SCRIPT_RUNNERS or tokens[0] == "make")


class References:
    def __init__(self, root):
        self.root = Path(root)
        self.tracked = self._tracked()
        self._ignored = {}

    def _tracked(self):
        proc = run_git(["ls-files", "-z"], self.root)
        if proc is None or proc.returncode != 0:
            return []
        return [item for item in proc.stdout.split("\0") if item]

    def ignored(self, ref):
        if ref not in self._ignored:
            proc = run_git(["check-ignore", "-q", "--", ref], self.root)
            self._ignored[ref] = proc is not None and proc.returncode == 0
        return self._ignored[ref]

    def classify(self, ref, file_rel):
        raw_cmd = ref.strip()
        if raw_cmd and not raw_cmd.startswith("-") and probable_command(raw_cmd):
            return self._command(raw_cmd)
        ref = strip_reference(ref)
        if not ref or ref.startswith("-"):
            return None
        if URL.match(ref):
            return "external"
        if ref.startswith("~") or ref.startswith("/") or ref.startswith("$"):
            return "external"
        if PLACEHOLDER.search(ref):
            return "scoped"
        if looks_like_path(ref):
            memory_dir = (self.root / file_rel).parent
            for base in (self.root, memory_dir):
                try:
                    candidate = (Path(base) / ref)
                    if candidate.exists():
                        if _inside(candidate, self.root):
                            return "ok"
                        return "external"
                except OSError:
                    continue
            if self.ignored(ref):
                return "ignored"
            suffix = normalize_rel(ref)
            matches = [item for item in self.tracked
                       if item == suffix or item.endswith("/" + suffix)]
            if len(matches) == 1:
                return "scoped"
            return "stale"
        return self._command(ref)

    def _command(self, ref):
        try:
            tokens = shlex.split(ref, comments=True)
        except ValueError:
            return "unverified"
        if not tokens:
            return None
        if any(PLACEHOLDER.search(tok) for tok in tokens):
            return "scoped"
        command = tokens[0]
        if command == "make":
            return self._make_target(tokens[1] if len(tokens) > 1 else "")
        if command in PACKAGE_MANAGERS:
            name = None
            if len(tokens) > 1:
                if tokens[1] in ("run", "exec", "dlx", "x") and len(tokens) > 2:
                    name = tokens[2]
                elif not tokens[1].startswith("-"):
                    name = tokens[1]
            if name in PACKAGE_BUILTINS:
                return "external"
            return self._package_script(name)
        if command in SCRIPT_RUNNERS:
            rest = tokens[1:]
            inline_flags = {
                "python": ("-m", "-c"), "python3": ("-m", "-c"),
                "bash": ("-c",), "sh": ("-c",), "zsh": ("-c",),
                "node": ("-e", "--eval", "-p", "--print"),
                "ruby": ("-e",), "perl": ("-e", "-E"),
                "deno": ("eval",), "php": ("-r",),
            }
            value_flags = {
                "pytest": ("-k", "-m", "-o", "-c", "-n", "--rootdir", "--maxfail", "--tb"),
                "python": ("-W", "-X"), "python3": ("-W", "-X"),
                "bash": ("-o", "+o"), "sh": ("-o", "+o"), "zsh": ("-o", "+o"),
                "node": ("-r", "--require", "--import", "--env-file"),
            }
            runner_inline = inline_flags.get(command, ())
            skip_next = False
            for token in rest:
                if skip_next:
                    skip_next = False
                    continue
                if token in runner_inline:
                    return "external"
                if token.startswith("-") and not token.startswith("--") and len(token) > 2:
                    if any("-" + ch in runner_inline for ch in token[1:]):
                        return "external"
                if token in value_flags.get(command, ()):
                    skip_next = True
                    continue
                if token.startswith("-"):
                    continue
                if looks_like_path(token):
                    return self.classify(token, "AGENTS.md")
                return "external"
            return "external"
        if command in COMMON_CLIS:
            return "external"
        return "unverified"

    def _package_script(self, name):
        if not name:
            return "unverified"
        manifests = []
        root_manifest = self.root / "package.json"
        if root_manifest.is_file():
            manifests.append((root_manifest, "ok"))
        for rel in self.tracked:
            if rel.endswith("package.json") and rel != "package.json":
                manifests.append((self.root / rel, "scoped"))
        for path, klass in manifests:
            try:
                data = json.loads(path.read_text("utf-8", "replace"))
            except (OSError, ValueError):
                continue
            scripts = data.get("scripts") if isinstance(data, dict) else None
            if isinstance(scripts, dict) and name in scripts:
                return klass
        return "stale" if manifests else "unverified"

    def _make_target(self, name):
        if not name:
            return "unverified"
        makefile = self.root / "Makefile"
        if not makefile.is_file():
            return "unverified"
        try:
            text = makefile.read_text("utf-8", "replace")
        except OSError:
            return "unverified"
        if re.search(r"^%s\s*:" % re.escape(name), text, re.M):
            return "ok"
        return "stale"


def shell_fence_lines(text):
    lines = set()
    for fence in SHELL_FENCE.finditer(text):
        for line in fence.group(1).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.add(stripped)
    return lines


def references_in(text, file_rel, refs):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in BACKTICK.finditer(line):
            found.append((number, match.group(1).strip(), False))
        for match in LINK.finditer(line):
            found.append((number, match.group(1).strip(), False))
    for fence in SHELL_FENCE.finditer(text):
        start = text[:fence.start()].count("\n") + 2
        for offset, line in enumerate(fence.group(1).splitlines()):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            found.append((start + offset, stripped, True))
    out = []
    for number, value, from_fence in found:
        klass = refs.classify(value, file_rel) if from_fence \
            else classify_candidate(value, file_rel, refs)
        if klass is None:
            continue
        out.append({"file": file_rel, "line": number, "ref": value.strip(), "class": klass})
    return out


def classify_candidate(value, file_rel, refs):
    stripped = value.strip()
    if not stripped:
        return None
    if " " in stripped and not probable_command(stripped):
        return None
    klass = refs.classify(stripped, file_rel)
    if klass == "unverified" and " " not in stripped and not looks_like_path(stripped):
        return None
    return klass


def collect_references(repo, entries):
    refs = References(repo.root)
    results = []
    for entry in entries:
        if entry.get("link"):
            continue
        path = repo.root / entry["path"]
        try:
            text = path.read_text("utf-8", "replace")
        except OSError:
            continue
        results.extend(references_in(text, entry["path"], refs))
    return results


LEAD_KEYS = ("gaps", "entries", "items", "leads")
ALL_PROJECT = {"all", "all-project", "allprojects", "project", "*", ""}


def _sighting_transcript(source):
    if not isinstance(source, str):
        return ""
    if " · " in source:
        parts = source.split(" · ")
        if len(parts) >= 2 and parts[1].strip():
            return parts[1].strip()
    return source.split(":", 1)[-1].strip()


def _entry_text(entry):
    text = (entry.get("proposedInstruction") or entry.get("instruction")
            or entry.get("text") or "")
    return text.strip() if isinstance(text, str) else ""


def _entry_count(value):
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, (dict, list)):
        return len(value)
    return 0


def _make_lead(text, count, transcript):
    return {"proposedInstruction": redact(text), "sessions": count,
            "transcript": transcript, "unverified": True}


def _list_route(entry):
    domain = entry.get("domain", entry.get("project", entry.get("scope", "all")))
    token = str(domain).strip().lower() if domain is not None else ""
    return "lead" if token in ALL_PROJECT else "candidate"


def _ledger_items(data):
    """Route version 1 gap-ledger entries, including the dict-of-sightings schema."""
    items = []
    entries = data.get("entries")
    if isinstance(entries, dict):
        for key in sorted(entries):
            entry = entries[key]
            if not isinstance(entry, dict):
                continue
            text = _entry_text(entry)
            if not text:
                continue
            raw = entry.get("sessions")
            if isinstance(raw, dict):
                sightings = [item for item in raw.values() if isinstance(item, dict)]
            elif isinstance(raw, list):
                sightings = [item for item in raw if isinstance(item, dict)]
            else:
                sightings = []
            count = len(raw) if isinstance(raw, (dict, list)) else 0
            transcript = _sighting_transcript(sightings[0].get("source")) if sightings else ""
            domains = [str(item.get("domain")).strip().lower() for item in sightings
                       if item.get("domain") is not None and str(item.get("domain")).strip()]
            route = "lead" if not domains or all(domain == "project" for domain in domains) \
                else "candidate"
            items.append((route, _make_lead(text, count, transcript)))
        return items
    if isinstance(entries, list):
        listed = entries
    else:
        listed = []
        for key in ("gaps", "items", "leads"):
            value = data.get(key)
            if isinstance(value, list):
                listed = value
                break
    for entry in listed:
        if not isinstance(entry, dict):
            continue
        text = _entry_text(entry)
        if not text:
            continue
        count = _entry_count(entry.get("sessions", entry.get("count")))
        items.append((_list_route(entry),
                      _make_lead(text, count, _sighting_transcript(entry.get("source")))))
    return items


def _summary_items(data):
    """Route version 1 evidence-summary gaps and report-only gaps."""
    items = []
    for key in ("gaps", "reportOnlyGaps"):
        value = data.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, dict):
                continue
            text = _entry_text(entry)
            if not text:
                continue
            try:
                orchestration = int(entry.get("orchestrationSightings") or 0)
            except (TypeError, ValueError):
                orchestration = 0
            candidate = (orchestration > 0 or bool(entry.get("majorityOrchestration"))
                         or bool(entry.get("mixed")) or _list_route(entry) == "candidate")
            items.append(("candidate" if candidate else "lead",
                          _make_lead(text, _entry_count(entry.get("sessions")),
                                     _sighting_transcript(entry.get("source")))))
    return items


def read_backpass(repo):
    notes = []
    leads = []
    candidates = []
    main = repo.main_checkout()
    base = main / ".backpass"
    if not base.exists():
        return {"leads": [], "user_global_candidates": [], "notes": []}
    for name in ("gap-ledger.json", "evidence-summary.json"):
        path = base / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text("utf-8", "replace"))
        except (OSError, ValueError):
            notes.append("%s: unreadable" % name)
            continue
        if not isinstance(data, dict) or data.get("version") != 1:
            notes.append("%s: unsupported version" % name)
            continue
        items = _ledger_items(data) if name == "gap-ledger.json" else _summary_items(data)
        for route, item in items:
            if route == "lead":
                leads.append(item)
            else:
                candidates.append(item)
    return {"leads": leads, "user_global_candidates": candidates, "notes": notes}


def check_command(repo_path):
    try:
        repo = Repo(repo_path)
    except (OSError, ValueError):
        return EXIT_INVALID, {"version": 1, "command": "check", "status": "invalid",
                              "error": "repository is not usable"}
    entries = surface_entries(repo.root)
    report = {
        "version": 1,
        "command": "check",
        "status": "ok",
        "repo": {"id": repo.id, "kind": "git" if repo.is_git else "dir",
                 "head": repo.head, "default_branch": repo.default_branch},
        "delivery": delivery_state(repo, entries),
        "budget": budget_report(repo.root),
        "import": check_imports(repo),
        "references": [{**item, "ref": redact(item["ref"])}
                       for item in collect_references(repo, entries)],
    }
    backpass = read_backpass(repo)
    report["leads"] = backpass["leads"]
    report["user_global_candidates"] = backpass["user_global_candidates"]
    if backpass["notes"]:
        report["notes"] = backpass["notes"]
    return EXIT_OK, report


def stage_command(repo_path, out_path):
    try:
        repo = Repo(repo_path)
    except (OSError, ValueError):
        return EXIT_INVALID, {"version": 1, "command": "stage", "status": "invalid",
                              "error": "repository is not usable"}
    out = Path(out_path)
    if os.path.lexists(str(out)):
        return EXIT_INVALID, {"version": 1, "command": "stage", "status": "invalid",
                              "error": "stage path already exists"}
    if not outside_worktree(out):
        return EXIT_INVALID, {"version": 1, "command": "stage", "status": "invalid",
                              "error": "stage path is inside a git worktree"}
    entries = surface_entries(repo.root)
    try:
        os.makedirs(str(out), mode=0o700)
        os.chmod(str(out), 0o700)
        (out / "base").mkdir(mode=0o700)
        (out / "proposed").mkdir(mode=0o700)
        for entry in entries:
            if entry.get("link") is not None:
                continue
            source = repo.root / entry["path"]
            for folder in ("base", "proposed"):
                target = out / folder / entry["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(source), str(target))
                os.chmod(str(target), entry.get("mode", 0o644))
        manifest = {
            "version": 1,
            "repo": {"id": repo.id, "root": str(repo.root), "head": repo.head,
                     "default_branch": repo.default_branch},
            "delivery": delivery_state(repo, entries),
            "files": entries,
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                           encoding="utf-8")
    except OSError as exc:
        return EXIT_INVALID, {"version": 1, "command": "stage", "status": "invalid",
                              "error": "cannot create stage: %s" % exc}
    return EXIT_OK, {"version": 1, "command": "stage", "status": "ok",
                     "stage": str(out), "files": [entry["path"] for entry in entries]}


def load_manifest(stage):
    path = Path(stage) / "manifest.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text("utf-8", "replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return None
    return data


def invalid(command, message):
    return EXIT_INVALID, {"version": 1, "command": command, "status": "invalid",
                          "error": message}


def blocked(command, findings, status="blocked", **extra):
    payload = {"version": 1, "command": command, "status": status, "findings": findings}
    payload.update(extra)
    return EXIT_BLOCKED, payload


CLAIM_KEYS = {"id", "type", "file", "removed", "added", "basis", "citations", "proof",
              "trail", "target"}
CLAIM_TYPES = {"Fix", "Add", "Remove", "Compress", "Move"}
CITATION_KEYS = {"session", "quote"}
EXPLAINED_KEYS = {"file", "ref", "reason"}


def normalize_claims(data):
    if not isinstance(data, dict):
        return None, "claims must be a JSON object"
    if data.get("version") != 1:
        return None, "unsupported claims version"
    claims = data.get("claims")
    if not isinstance(claims, list):
        return None, "claims must be a list"
    for claim in claims:
        if not isinstance(claim, dict):
            return None, "claim must be an object"
        for key in claim:
            if key not in CLAIM_KEYS:
                return None, "unknown claim key: %s" % key
        if claim.get("type") not in CLAIM_TYPES:
            return None, "unknown claim type: %s" % claim.get("type")
        if not isinstance(claim.get("file"), str):
            return None, "claim file must be a string"
        for key in ("removed", "added"):
            value = claim.get(key, [])
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                return None, "claim %s must be a list of lines" % key
        citations = claim.get("citations", [])
        if not isinstance(citations, list):
            return None, "claim citations must be a list"
        for citation in citations:
            if not isinstance(citation, dict):
                return None, "citation must be an object"
            for key in citation:
                if key not in CITATION_KEYS:
                    return None, "unknown citation key: %s" % key
        proof = claim.get("proof")
        if proof is not None and not isinstance(proof, dict):
            return None, "claim proof must be an object"
    explained = data.get("explained_stale", [])
    if not isinstance(explained, list):
        return None, "explained_stale must be a list"
    for item in explained:
        if not isinstance(item, dict) or set(item) - EXPLAINED_KEYS:
            return None, "unknown explained_stale key"
    for key in data:
        if key not in ("version", "claims", "explained_stale"):
            return None, "unknown claims key: %s" % key
    return data, None


def evidence_index(evidence):
    index = {}
    for session in evidence.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        sid = session.get("id")
        if isinstance(sid, str):
            index[sid] = session
    return index


def quote_problem(citation, index):
    session_id = citation.get("session")
    quote = citation.get("quote")
    if not isinstance(session_id, str) or not isinstance(quote, str):
        return "citation needs a session and a quote"
    folded = fold(quote)
    if len(folded) < 12 or len(folded.split()) < 3:
        return "quote is too short"
    if "..." in quote or "…" in quote:
        return "quote is elided"
    upper = quote.upper()
    if any(marker in upper for marker in ("[REDACTED]", "<REDACTED>", "[REDACT]")):
        return "quote contains a redaction marker"
    session = index.get(session_id)
    if session is None:
        return "quote cites an unknown session"
    for message in session.get("human") or []:
        text = message.get("text")
        if isinstance(text, str) and folded in fold(text):
            if message.get("correction") or is_correction(text):
                return None
            return None
    return "quote is not in one human message of that session"


def quote_matches(citation, index):
    """Return (session, matched_messages) when the quote passes, else (None, [])."""
    if quote_problem(citation, index) is not None:
        return None, []
    quote = fold(citation["quote"])
    session = index[citation["session"]]
    matched = [message for message in session.get("human") or []
               if isinstance(message.get("text"), str) and quote in fold(message["text"])]
    return session, matched


STOPWORDS = {"the", "and", "that", "this", "with", "from", "into", "have", "will", "your",
             "their", "they", "them", "then", "than", "when", "what", "where", "which",
             "there", "here", "been", "being", "were", "was", "are", "for", "not", "but",
             "you", "our", "its", "it's", "can", "should", "would", "could", "does",
             "don't", "do", "doesn't", "about", "after", "before", "over", "under", "also",
             "just", "only", "very", "more", "most", "some", "any", "all", "each", "every"}


def content_words(text):
    return {word.lower() for word in re.findall(r"[A-Za-z]{4,}", text)
            if word.lower() not in STOPWORDS}


def anchor_refs(text, file_rel, refs):
    anchors = set()
    for line in text.splitlines():
        for match in BACKTICK.finditer(line):
            if classify_candidate(match.group(1), file_rel, refs) in ("ok", "scoped"):
                anchors.add(strip_reference(match.group(1)))
    return anchors


def related_to_lines(quote, lines, file_rel, refs):
    joined = " ".join(lines)
    if anchor_refs(quote, file_rel, refs) & anchor_refs(joined, file_rel, refs):
        return True
    return len(content_words(quote) & content_words(joined)) >= 2


PROTECTED = re.compile(
    r"(?i)\b(never|must not|do not|don't|always|secret|credential|password|token|auth|"
    r"permission|security|safety|production|deploy|migration|destructive|force-push|"
    r"billing|payment|privacy|boundary|ask first)\b")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
MODEL_NAME = re.compile(
    r"(?i)\b(claude|anthropic|openai|gpt|gemini|deepseek|opus|sonnet|haiku|cursor|"
    r"copilot|codex|opencode|chatgpt|windsurf)\b")
EVERY_REPO = re.compile(
    r"(?i)\b(every|all|any)\s+(repo|repository|project)s?\b|\bacross\s+projects?\b|"
    r"\bglobally\b")
STYLE = re.compile(r"(?i)\b(response style|tone|be concise|be verbose|reply|respond)\b")
INLINE_CODE_SPAN = re.compile(r"`[^`]*`")


def protected_lines(text):
    marked = []
    heading_protected = False
    for line in text.splitlines():
        if HEADING.match(line):
            heading_protected = bool(PROTECTED.search(line))
        marked.append(heading_protected or bool(PROTECTED.search(line)))
    return marked


def user_global(line, file_rel, refs):
    stripped = INLINE_CODE_SPAN.sub(" ", line)
    if MODEL_NAME.search(stripped) or EVERY_REPO.search(stripped) or STYLE.search(stripped):
        return True
    for match in BACKTICK.finditer(line):
        value = match.group(1).strip()
        if refs.classify(value, file_rel) in ("ok", "scoped"):
            return False
        proc = run_git(["grep", "-F", "-e", value, "--"], refs.root)
        if value and proc is not None and proc.returncode == 0 and proc.stdout.strip():
            return False
    return True


def diff_lines(base_text, proposed_text):
    base = base_text.splitlines()
    proposed = proposed_text.splitlines()
    matcher = difflib.SequenceMatcher(None, base, proposed, autojunk=False)
    removed, added = [], []
    hunks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed.extend(base[i1:i2])
        added.extend(proposed[j1:j2])
        hunks.append((tag, base[i1:i2], proposed[j1:j2]))
    return removed, added, hunks, base, proposed


def read_stage_file(stage, folder, rel):
    folder_root = Path(stage) / folder
    if _path_escapes_root(folder_root, rel, include_leaf=True):
        return ""
    path = folder_root / normalize_rel(rel)
    if not path.is_file() or path.is_symlink():
        return ""
    return path.read_text("utf-8", "replace")


def proposed_paths(stage):
    root = Path(stage) / "proposed"
    found = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        for name in filenames:
            path = Path(dirpath) / name
            found.append(os.path.relpath(str(path), str(root)).replace(os.sep, "/"))
    return sorted(found)


def _read_private_input(path):
    """Read a regular, non-symlinked file outside any worktree exactly once."""
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return None, None, "must be a regular file"
    if not outside_worktree(target):
        return None, None, "is inside a git worktree"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        handle = os.open(str(target), flags)
    except OSError:
        return None, None, "is unreadable"
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode):
            return None, None, "must be a regular file"
        chunks = []
        while True:
            chunk = os.read(handle, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError:
        return None, None, "is unreadable"
    finally:
        os.close(handle)
    return b"".join(chunks), stat.S_IMODE(info.st_mode), None


def check_evidence_file(path, repo_id):
    raw, mode, problem = _read_private_input(path)
    if problem:
        return "evidence " + problem, None
    if mode != 0o600:
        return "evidence mode must be 0600", None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return "evidence is not valid JSON", None
    if not isinstance(data, dict) or data.get("version") != 1:
        return "evidence version must be 1", None
    if data.get("repo_id") != repo_id:
        return "evidence repo_id does not match the stage", None
    return None, raw


def check_claims_file(path):
    raw, _mode, problem = _read_private_input(path)
    if problem:
        return None, None, "claims " + problem
    try:
        return json.loads(raw.decode("utf-8", "replace")), raw, None
    except ValueError:
        return None, None, "claims are not valid JSON"


def move_target_problem(claim, root, proposed_root):
    target = claim.get("target")
    if not isinstance(target, str) or not target:
        return "Move claim needs a target"
    target = normalize_rel(target)
    if ".." in Path(target).parts or os.path.isabs(target):
        return "Move target is not a safe relative path"
    if not is_surface_path(target, root):
        return "Move target is not a surface path"
    if _path_escapes_root(proposed_root, target, include_leaf=True):
        return "Move target escapes the stage"
    if _path_escapes_root(root, target):
        return "Move target escapes the repository"
    if not (Path(proposed_root) / target).is_file():
        return "Move target is missing from the stage"
    return None


def validate_gate(stage_path, evidence_path, claims_path):
    stage = Path(stage_path)
    manifest = load_manifest(stage)
    if manifest is None:
        return invalid("gate", "stage manifest is missing or unreadable")
    stage_repo = manifest.get("repo") or {}
    repo_id = stage_repo.get("id")
    repo_root = stage_repo.get("root")
    if not isinstance(repo_id, str) or not isinstance(repo_root, str):
        return invalid("gate", "stage manifest has no repo id or root")
    repo_root = Path(repo_root)
    evidence_problem, evidence_bytes = check_evidence_file(evidence_path, repo_id)
    if evidence_problem:
        return invalid("gate", evidence_problem)
    raw_claims, claims_bytes, claims_problem = check_claims_file(claims_path)
    if claims_problem:
        return invalid("gate", claims_problem)
    claims, problem = normalize_claims(raw_claims)
    if problem:
        finding = _finding(None, "", "claim_schema", problem)
        gate = {"version": 1, "status": "blocked", "findings": [finding], "reported": [],
                "hashes": {}, "inputs": {}}
        try:
            (stage / "gate.json").write_text(
                json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass
        return EXIT_BLOCKED, {"version": 1, "command": "gate", "status": "blocked",
                              "findings": [finding]}
    try:
        evidence = json.loads(evidence_bytes.decode("utf-8", "replace"))
    except ValueError:
        return invalid("gate", "evidence is not valid JSON")
    index = evidence_index(evidence)

    files = {entry["path"]: entry for entry in manifest["files"]}
    proposed = proposed_paths(stage)
    for rel in proposed:
        if os.path.isabs(rel) or ".." in Path(rel).parts:
            return invalid("gate", "proposed path is absolute or escapes the stage")
        if not is_surface_path(rel, repo_root):
            return invalid("gate", "proposed path is not a surface path: %s" % rel)
        proposed_root = Path(stage) / "proposed"
        if os.path.islink(str(proposed_root / rel)):
            return invalid("gate", "proposed path is a symlink: %s" % rel)
        if _path_escapes_root(proposed_root, rel, include_leaf=True):
            return invalid("gate", "proposed path escapes the stage: %s" % rel)
        if _path_escapes_root(repo_root, rel, include_leaf=True):
            return invalid("gate", "proposed path escapes the repository: %s" % rel)
    proposed_root = Path(stage) / "proposed"
    for claim in claims["claims"]:
        rel = str(claim["file"]).replace(os.sep, "/")
        if not is_surface_path(rel, repo_root):
            return invalid("gate", "claim names a non-surface file: %s" % rel)
        if _path_escapes_root(repo_root, rel):
            return invalid("gate", "claim names a path outside the repository: %s" % rel)
        if _path_escapes_root(proposed_root, rel, include_leaf=True):
            return invalid("gate", "claim names a path outside the stage: %s" % rel)
        if claim.get("type") == "Move":
            target = claim.get("target")
            if not isinstance(target, str) or not target:
                return invalid("gate", "Move claim needs a target")
            target_rel = normalize_rel(target)
            if os.path.isabs(target_rel) or ".." in Path(target_rel).parts:
                return invalid("gate", "Move target is not a safe relative path: %s" % target)
            if not is_surface_path(target_rel, repo_root):
                return invalid("gate", "Move target is not a surface path: %s" % target)
            if _path_escapes_root(repo_root, target_rel):
                return invalid("gate", "Move target escapes the repository: %s" % target)
            if _path_escapes_root(proposed_root, target_rel, include_leaf=True):
                return invalid("gate", "Move target escapes the stage: %s" % target)

    refs = References(repo_root)
    budget_base = _stage_budget(stage, "base", repo_root)
    budget_proposed = _stage_budget(stage, "proposed", repo_root)

    findings = []
    reported = []
    expected_removed, expected_added = _expected_lines(claims["claims"])
    allowed = _allowed_extras(claims["claims"], stage)

    changed_files = []
    for rel in sorted(set(files) | set(proposed) | set(expected_removed)
                      | set(expected_added)):
        entry = files.get(rel)
        if entry and entry.get("link"):
            live = repo_root / rel
            proposed_copy = Path(stage) / "proposed" / rel
            if proposed_copy.exists() and \
                    digest_file(proposed_copy) != digest_file(live):
                findings.append(_finding(None, rel, "symlink_edit",
                                         "a symlinked surface file must not be edited"))
            continue
        base_text = read_stage_file(stage, "base", rel) if entry else ""
        proposed_text = read_stage_file(stage, "proposed", rel)
        removed, added, _hunks, _base, _proposed = diff_lines(base_text, proposed_text)
        _check_existing_stale(rel, base_text, removed, claims, refs, findings, reported)
        _compare_lines(rel, removed, expected_removed.get(rel, []), None,
                       findings, "removed")
        _compare_lines(rel, added, expected_added.get(rel, []),
                       allowed.get(rel, []), findings, "added")
        if base_text == proposed_text:
            continue
        changed_files.append(rel)
        for line in added:
            if redact(line) != line:
                findings.append(_finding(None, rel, "redaction_triggered",
                                         "an added line contains a secret or home path that "
                                         "redaction would change"))
        _check_added_references(rel, added, refs, findings,
                                shell_fence_lines(proposed_text))

    if any(rel.endswith("AGENTS.md") or rel.endswith("CLAUDE.md") for rel in changed_files):
        links = {entry["path"]: entry.get("link") for entry in manifest["files"]
                 if entry.get("link")}
        base_tree = type("BaseTree", (), {"root": Path(stage) / "base"})()
        proposed_tree = type("ProposedTree", (), {"root": Path(stage) / "proposed"})()
        base_errors = {(error.get("file", ""), error.get("error", ""))
                       for error in check_imports(base_tree, links=links,
                                                  fallback_root=repo_root)["errors"]}
        touched_dirs = {os.path.dirname(rel) for rel in changed_files
                        if rel.endswith("AGENTS.md") or rel.endswith("CLAUDE.md")}
        for error in check_imports(proposed_tree, links=links,
                                   fallback_root=repo_root)["errors"]:
            rel = error.get("file", "")
            key = (rel, error.get("error", ""))
            if os.path.dirname(rel) in touched_dirs or key not in base_errors:
                findings.append(_finding(None, rel, "import_check",
                                         error.get("error", "import check failed")))

    for rel in sorted(set(expected_removed) | set(expected_added)):
        if rel and rel not in files and rel not in proposed:
            findings.append(_finding(None, rel, "unknown_file",
                                     "claim names a file outside the surface"))

    add_remove = sum(1 for claim in claims["claims"]
                     if claim.get("type") in ("Add", "Remove"))
    if add_remove > 5:
        findings.append(_finding(None, "", "too_many_claims",
                                 "more than five Add and Remove claims"))

    if changed_files and budget_base["over"] and \
            budget_proposed["tokens"] >= budget_base["tokens"]:
        findings.append(_finding(None, "", "budget_not_smaller",
                                 "an over-budget surface must end strictly smaller"))
    if not budget_base["over"] and budget_proposed["over"]:
        findings.append(_finding(None, "", "budget_over",
                                 "the edit ends over the token cap"))

    for claim in claims["claims"]:
        findings.extend(_check_claim(claim, stage, claims, index, repo_root,
                                     budget_base))

    if findings:
        status = "blocked"
    elif not changed_files and not claims["claims"]:
        status = "no_change"
    else:
        status = "pass"

    hashes = {
        "stage": digest_file(Path(stage) / "manifest.json"),
        "base": tree_digest(Path(stage) / "base"),
        "proposed": tree_digest(Path(stage) / "proposed"),
        "claims": digest_bytes(claims_bytes),
        "evidence": digest_bytes(evidence_bytes),
    }
    user_global = [{"claim": finding.get("claim"), "file": finding.get("file")}
                   for finding in findings if finding.get("code") == "user_global"]
    gate = {"version": 1, "status": status, "findings": findings, "reported": reported,
            "user_global": user_global, "hashes": hashes,
            "inputs": {"claims": str(claims_path), "evidence": str(evidence_path)}}
    try:
        (Path(stage) / "gate.json").write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n",
                                               encoding="utf-8")
    except OSError as exc:
        return invalid("gate", "cannot write gate.json: %s" % exc)
    code = EXIT_OK if status in ("pass", "no_change") else EXIT_BLOCKED
    payload = {"version": 1, "command": "gate", "status": status, "findings": findings,
               "reported": reported, "user_global": user_global, "hashes": hashes}
    return code, payload


def _stage_budget(stage, folder, repo_root):
    root = Path(stage) / folder
    total = 0
    for rel in ("AGENTS.md", "CLAUDE.md"):
        path = root / rel
        if path.is_file():
            total += len(path.read_bytes())
    skills = root / skills_dir(repo_root)
    if skills.is_dir():
        for child in sorted(skills.iterdir()):
            manifest = child / "SKILL.md"
            if manifest.is_file():
                total += len(frontmatter_description(
                    manifest.read_text("utf-8", "replace")).encode("utf-8"))
    cap = budget_report(repo_root)["cap"]
    tokens = int(math.ceil(total / 4.0))
    return {"tokens": tokens, "over": tokens > cap, "cap": cap}


def _finding(claim, file_rel, code, message):
    return {"claim": claim, "file": file_rel, "code": code, "message": message}


def _expected_lines(claims):
    removed, added = {}, {}
    for claim in claims:
        rel = str(claim.get("file", "")).replace(os.sep, "/")
        removed.setdefault(rel, []).extend(claim.get("removed") or [])
        if claim.get("type") == "Move":
            target = normalize_rel(claim.get("target") or "")
            added.setdefault(target, []).extend(
                claim.get("added") or claim.get("removed") or [])
        else:
            added.setdefault(rel, []).extend(claim.get("added") or [])
    return removed, added


def _allowed_extras(claims, stage):
    """Lines a Move may add around the moved body without a second claim."""
    extras = {}
    for claim in claims:
        if claim.get("type") != "Move":
            continue
        target = normalize_rel(claim.get("target") or "")
        if not target:
            continue
        if target.endswith("SKILL.md"):
            lines = read_stage_file(stage, "proposed", target).splitlines()
            if lines and lines[0].strip() == "---":
                for index in range(1, len(lines)):
                    if lines[index].strip() == "---":
                        extras.setdefault(target, []).extend(lines[: index + 1])
                        break
        directory = os.path.dirname(target)
        if directory:
            extras.setdefault(directory + "/CLAUDE.md", []).append("@AGENTS.md")
    return extras


def _compare_lines(rel, actual, expected, extras, findings, label):
    actual_counter = Counter(actual)
    expected_counter = Counter(expected)
    extra_counter = Counter(extras) if label == "added" else Counter()
    if expected_counter - actual_counter:
        findings.append(_finding(None, rel, "phantom_line",
                                 "claimed %s line does not appear in the diff" % label))
    if actual_counter - expected_counter - extra_counter:
        findings.append(_finding(None, rel, "unmapped_hunk",
                                 "%s lines are not mapped to a claim" % label))


def _check_added_references(rel, added, refs, findings, command_lines=()):
    for line in added:
        if not line.strip():
            continue
        if line.strip() in command_lines:
            klass = refs.classify(line.strip(), rel)
            if klass in ("stale", "unverified"):
                findings.append(_finding(None, rel, "reference_" + klass,
                                         "added line has a %s reference" % klass))
            continue
        for match in BACKTICK.finditer(line):
            klass = classify_candidate(match.group(1), rel, refs)
            if klass in ("stale", "unverified"):
                findings.append(_finding(None, rel, "reference_" + klass,
                                         "added line has a %s reference" % klass))
        for match in LINK.finditer(line):
            klass = classify_candidate(match.group(1), rel, refs)
            if klass in ("stale", "unverified"):
                findings.append(_finding(None, rel, "reference_" + klass,
                                         "added line has a %s reference" % klass))


def _check_existing_stale(rel, base_text, removed_lines, claims, refs, findings, reported):
    fixed = set()
    for claim in claims["claims"]:
        claim_file = str(claim.get("file", "")).replace(os.sep, "/")
        if claim_file == rel and claim.get("type") in ("Fix", "Remove", "Compress", "Move"):
            fixed.update(claim.get("removed") or [])
    removed_counter = Counter(removed_lines)
    explained_refs = set()
    for item in claims["explained_stale"]:
        item_file = str(item.get("file")).replace(os.sep, "/")
        ref = str(item.get("ref"))
        explained_refs.add((item_file, strip_reference(ref)))
        explained_refs.add((item_file, strip_reference(redact(ref))))
    lines = base_text.splitlines()
    for item in references_in(base_text, rel, refs):
        if item["class"] != "stale":
            reported.append({"file": rel, "line": item["line"],
                             "ref": redact(item["ref"]), "class": item["class"]})
            continue
        line = lines[item["line"] - 1] if item["line"] - 1 < len(lines) else ""
        if line in fixed and removed_counter[line] > 0:
            continue
        if (rel, strip_reference(item["ref"])) in explained_refs:
            continue
        if (rel, strip_reference(redact(item["ref"]))) in explained_refs:
            continue
        findings.append(_finding(None, rel, "existing_stale",
                                 "existing stale reference is neither fixed nor explained"))


def _check_claim(claim, stage, claims, index, root, budget_base):
    findings = []
    rel = str(claim.get("file")).replace(os.sep, "/")
    kind = claim.get("type")
    refs = References(root)

    if kind == "Fix":
        basis = claim.get("basis")
        if basis == "reference":
            if len(claim.get("removed") or []) != len(claim.get("added") or []):
                findings.append(_finding(claim.get("id"), rel, "fix_line_count",
                                         "reference Fix needs the same line count"))
            base_commands = shell_fence_lines(read_stage_file(stage, "base", rel))
            for removed, added in zip(claim.get("removed") or [], claim.get("added") or []):
                old_command = removed.strip() in base_commands
                if old_command:
                    old_class = refs.classify(removed.strip(), rel)
                    new_class = refs.classify(added.strip(), rel)
                    if old_class != "stale":
                        findings.append(_finding(claim.get("id"), rel, "fix_not_stale",
                                                 "removed line has no stale reference"))
                    if new_class not in ("ok", "scoped", "external"):
                        findings.append(_finding(claim.get("id"), rel, "fix_mismatch",
                                                 "line does not match its replacement"))
                    continue
                stale = [item for item in references_in(removed, rel, refs)
                         if item["class"] == "stale"]
                if not stale:
                    findings.append(_finding(claim.get("id"), rel, "fix_not_stale",
                                             "removed line has no stale reference"))
                if _without_refs(removed) != _without_refs(added):
                    findings.append(_finding(claim.get("id"), rel, "fix_mismatch",
                                             "line does not match its replacement"))
        elif basis == "import":
            if not rel.endswith("CLAUDE.md"):
                findings.append(_finding(claim.get("id"), rel, "import_target",
                                         "import Fix must repair CLAUDE.md"))
            directory = os.path.dirname(rel)
            agents_rel = (directory + "/AGENTS.md") if directory else "AGENTS.md"
            agents = read_stage_file(stage, "proposed", agents_rel)
            for line in claim.get("removed") or []:
                if line not in agents.splitlines() and "@AGENTS.md" not in line:
                    findings.append(_finding(claim.get("id"), rel, "import_missing_line",
                                             "removed line is not in proposed AGENTS.md"))
            for line in claim.get("added") or []:
                if line.strip() and line.strip() != "@AGENTS.md":
                    findings.append(_finding(claim.get("id"), rel, "import_invalid_added",
                                             "import Fix may only add @AGENTS.md"))
        else:
            findings.append(_finding(claim.get("id"), rel, "fix_basis",
                                     "unknown Fix basis"))

    elif kind == "Add":
        added = claim.get("added") or []
        if claim.get("removed"):
            findings.append(_finding(claim.get("id"), rel, "add_has_removed",
                                     "Add claim must not carry removed lines"))
        for line in added:
            if not line.strip():
                continue
            if user_global(line, rel, refs):
                findings.append(_finding(claim.get("id"), rel, "user_global",
                                         "added line is user-global and never written"))
        if not _add_supported(claim, index, rel, added, root):
            findings.append(_finding(claim.get("id"), rel, "add_unsupported",
                                     "Add claim has no passing evidence"))
        for citation in claim.get("citations") or []:
            problem = quote_problem(citation, index)
            if problem:
                findings.append(_finding(claim.get("id"), rel, "quote_invalid", problem))
            quote = citation.get("quote")
            if isinstance(quote, str):
                for line in added:
                    if fold(quote) and fold(quote) in fold(line):
                        findings.append(_finding(claim.get("id"), rel, "quote_verbatim",
                                                 "an added line repeats a cited quote"))

    elif kind == "Remove":
        basis = claim.get("basis")
        removed = claim.get("removed") or []
        base_text = read_stage_file(stage, "base", rel)
        base_commands = shell_fence_lines(base_text)
        if claim.get("added"):
            findings.append(_finding(claim.get("id"), rel, "remove_has_added",
                                     "Remove claim must not carry added lines"))
        marked = protected_lines(base_text)
        line_numbers = {line: i for i, line in enumerate(base_text.splitlines())}
        for line in removed:
            position = line_numbers.get(line)
            if position is not None and marked[position]:
                findings.append(_finding(claim.get("id"), rel, "remove_protected",
                                         "protected boundary line cannot be removed"))
        if basis == "repo_disproof":
            def stale_line(line):
                if line.strip() and line.strip() in base_commands:
                    return refs.classify(line.strip(), rel) == "stale"
                return any(item["class"] == "stale"
                           for item in references_in(line, rel, refs))
            non_empty = [line for line in removed if line.strip()]
            missing = [line for line in non_empty if not stale_line(line)]
            if not non_empty or missing:
                findings.append(_finding(claim.get("id"), rel, "remove_unsupported",
                                         "Remove needs a checker-confirmed stale reference"))
        elif basis == "corroborated_harm":
            for citation in claim.get("citations") or []:
                problem = quote_problem(citation, index)
                if problem:
                    findings.append(_finding(claim.get("id"), rel, "quote_invalid", problem))
            if not _corroborated(claim, index, rel, removed, refs):
                findings.append(_finding(claim.get("id"), rel, "remove_unsupported",
                                         "Remove needs correction quotes from two sessions"))
        else:
            findings.append(_finding(claim.get("id"), rel, "remove_basis",
                                     "Remove basis is not allowed"))

    elif kind == "Compress":
        if not budget_base["over"]:
            findings.append(_finding(claim.get("id"), rel, "compress_under_budget",
                                     "Compress is only allowed when the surface is over budget"))
        base_text = read_stage_file(stage, "base", rel)
        proposed_text = read_stage_file(stage, "proposed", rel)
        if len(proposed_text.encode("utf-8")) >= len(base_text.encode("utf-8")):
            findings.append(_finding(claim.get("id"), rel, "compress_not_smaller",
                                     "Compress must shrink the file"))
        for token in _kept_tokens(base_text) - _kept_tokens(proposed_text):
            findings.append(_finding(claim.get("id"), rel, "compress_lost_token",
                                     "Compress dropped a token, path, number or directive"))

    elif kind == "Move":
        problem = move_target_problem(claim, root, Path(stage) / "proposed")
        if problem:
            findings.append(_finding(claim.get("id"), rel, "move_target", problem))
            return findings
        extra_added = claim.get("added") or []
        if extra_added and extra_added != (claim.get("removed") or []):
            findings.append(_finding(claim.get("id"), rel, "move_extra_added",
                                     "Move may not claim extra added lines"))
        if not budget_base["over"]:
            findings.append(_finding(claim.get("id"), rel, "move_under_budget",
                                     "Move is only allowed when the surface is over budget"))
        target = normalize_rel(claim["target"])
        base_text = read_stage_file(stage, "base", rel)
        marked = protected_lines(base_text)
        positions = {line: i for i, line in enumerate(base_text.splitlines())}
        for line in claim.get("removed") or []:
            position = positions.get(line)
            if position is not None and marked[position]:
                findings.append(_finding(claim.get("id"), rel, "move_protected",
                                         "protected boundary line cannot move"))
        moved = list(claim.get("removed") or [])
        if moved and not _moved_bytes_match(Path(stage) / "base" / rel,
                                            Path(stage) / "proposed" / target, moved):
            findings.append(_finding(claim.get("id"), rel, "move_not_identical",
                                     "moved lines must stay byte-identical and in order"))
        if target.endswith("SKILL.md"):
            expected = skills_dir(root) + "/"
            if not target.startswith(expected):
                findings.append(_finding(claim.get("id"), rel, "move_target",
                                         "a procedure moves only into a project skill"))
        else:
            target_dir = os.path.dirname(target)
            for line in moved:
                for item in references_in(line, rel, refs):
                    if item["class"] in ("ok", "scoped") and target_dir and not (
                            item["ref"] == target_dir
                            or item["ref"].startswith(target_dir + "/")):
                        findings.append(_finding(claim.get("id"), rel, "move_wrong_subtree",
                                                 "moved line covers a path outside the target"))
            bridge = Path(stage) / "proposed" / target_dir / "CLAUDE.md" if target_dir else None
            if bridge is None or not bridge.is_file() or \
                    [ln.strip() for ln in bridge.read_text("utf-8", "replace").splitlines()
                     if ln.strip()] != ["@AGENTS.md"]:
                findings.append(_finding(claim.get("id"), rel, "move_missing_bridge",
                                         "target directory needs a one-line @AGENTS.md bridge"))
    return findings


def _moved_bytes_match(base_path, target_path, moved):
    try:
        base = Path(base_path).read_bytes()
        target = Path(target_path).read_bytes()
    except OSError:
        return False
    raw_lines = base.splitlines(keepends=True)
    decoded = [line.rstrip(b"\r\n").decode("utf-8", "replace") for line in raw_lines]
    wanted = list(moved)
    if not wanted:
        return True
    for index in range(len(decoded) - len(wanted) + 1):
        if decoded[index:index + len(wanted)] != wanted:
            continue
        chunk = b"".join(raw_lines[index:index + len(wanted)])
        if chunk and chunk in target:
            return True
    return False


def _without_refs(line):
    line = BACKTICK.sub("", line)
    line = re.sub(r"\]\([^)]*\)", "]", line)
    return line.strip()


def _kept_tokens(text):
    tokens = set()
    tokens.update(m.group(1) for m in BACKTICK.finditer(text))
    tokens.update(re.findall(r"\b\d+(?:\.\d+)?\b", text))
    tokens.update(word.lower() for word in
                  re.findall(r"(?i)\b(?:never|must|always|do not|don't|only|shall|"
                             r"required|cannot|may not)\b", text))
    return {token for token in tokens if token}


def _corroborated(claim, index, rel, lines, refs):
    groups = set()
    messages = set()
    count = 0
    for citation in claim.get("citations") or []:
        session, matched = quote_matches(citation, index)
        if session is None or not matched:
            continue
        if not related_to_lines(citation["quote"], lines, rel, refs):
            continue
        group = session.get("group") or session.get("id")
        ids = {message.get("msg") for message in matched}
        if group in groups or (ids & messages):
            continue
        groups.add(group)
        messages |= ids
        if all(message.get("correction") or is_correction(str(message.get("text") or ""))
               for message in matched):
            count += 1
    return count >= 2


def _add_supported(claim, index, rel, added, root):
    basis = claim.get("basis")
    refs = References(root)
    if basis == "sessions":
        sessions = set()
        messages = set()
        for citation in claim.get("citations") or []:
            session, matched = quote_matches(citation, index)
            if session is None or not matched:
                continue
            if not related_to_lines(citation["quote"], added, rel, refs):
                continue
            group = session.get("group") or session.get("id")
            ids = {message.get("msg") for message in matched}
            if group in sessions or (ids & messages):
                continue
            sessions.add(group)
            messages |= ids
        return len(sessions) >= 2
    if basis == "correction":
        for citation in claim.get("citations") or []:
            session, matched = quote_matches(citation, index)
            if session is None or not matched:
                continue
            if not any(message.get("correction")
                       or is_correction(str(message.get("text") or ""))
                       for message in matched):
                continue
            if not related_to_lines(citation["quote"], added, rel, refs):
                continue
            if anchor_refs(citation["quote"], rel, refs) & anchor_refs(" ".join(added), rel, refs):
                return True
        return False
    if basis == "repo_proof":
        proof = claim.get("proof") or {}
        target = proof.get("file")
        needle = proof.get("contains")
        if not isinstance(target, str) or not isinstance(needle, str) or not needle:
            return False
        tracked = set(refs.tracked)
        target = normalize_rel(target)
        if target not in tracked:
            return False
        if _path_escapes_root(root, target, include_leaf=True) or (root / target).is_symlink():
            return False
        if not any(needle in line for line in added):
            return False
        try:
            content = (root / target).read_text("utf-8", "replace")
        except OSError:
            return False
        return needle in content
    if basis == "trail":
        trail = claim.get("trail")
        if isinstance(trail, dict):
            path = trail.get("file")
            scope = trail.get("scope")
        else:
            path, scope = trail, "repo"
        if not isinstance(path, str) or scope != "repo":
            return False
        path = normalize_rel(path)
        if os.path.isabs(path) or ".." in Path(path).parts or \
                not path.startswith(".trail/learnings/"):
            return False
        if _path_escapes_root(root, path, include_leaf=True):
            return False
        candidate = root / path
        if not candidate.is_file() or candidate.is_symlink():
            return False
        try:
            text = candidate.read_text("utf-8", "replace")
        except OSError:
            return False
        return bool(re.search(r"(?im)^status:\s*active\s*$", text)) and \
            bool(re.search(r"(?im)^scope:\s*repo\s*$", text))
    return False


def apply_command(stage_path):
    stage = Path(stage_path)
    manifest = load_manifest(stage)
    if manifest is None:
        return invalid("apply", "stage manifest is missing or unreadable")
    gate_path = stage / "gate.json"
    if not gate_path.is_file() or gate_path.is_symlink():
        return invalid("apply", "gate.json is missing")
    try:
        gate = json.loads(gate_path.read_text("utf-8", "replace"))
    except (OSError, ValueError):
        return invalid("apply", "gate.json is not valid JSON")
    status = gate.get("status")
    if status == "no_change":
        return EXIT_OK, {"version": 1, "command": "apply", "status": "no_change"}
    if status != "pass":
        return EXIT_BLOCKED, {"version": 1, "command": "apply", "status": "blocked",
                              "error": "gate did not pass"}
    hashes = gate.get("hashes") or {}
    current = {
        "stage": digest_file(stage / "manifest.json"),
        "base": tree_digest(stage / "base"),
        "proposed": tree_digest(stage / "proposed"),
    }
    for key, value in current.items():
        if hashes.get(key) != value:
            return EXIT_BLOCKED, {"version": 1, "command": "apply", "status": "blocked",
                                  "error": "stage hash mismatch: %s" % key}
    inputs = gate.get("inputs") or {}
    for key in ("claims", "evidence"):
        recorded = hashes.get(key)
        path = inputs.get(key)
        if not isinstance(path, str) or digest_file(path) != recorded:
            return EXIT_BLOCKED, {"version": 1, "command": "apply", "status": "blocked",
                                  "error": "input hash mismatch: %s" % key}
    repo_info = manifest.get("repo") or {}
    raw_root = repo_info.get("root")
    if not isinstance(raw_root, str) or not os.path.isabs(raw_root):
        return invalid("apply", "stage has no live repository")
    root = Path(raw_root)
    if not root.is_dir():
        return invalid("apply", "stage has no live repository")
    return _apply_files(stage, manifest, root)


def _apply_files(stage, manifest, root):
    known = {entry["path"]: entry for entry in manifest.get("files", [])
             if not entry.get("link")}
    proposed = proposed_paths(stage)
    surface = set(known) | set(proposed)
    for rel in sorted(known):
        live = root / rel
        if _path_escapes_root(root, rel, include_leaf=True) or live.is_symlink() \
                or not live.is_file() \
                or digest_file(live) != known[rel].get("sha256"):
            return EXIT_BLOCKED, {"version": 1, "command": "apply",
                                  "status": "concurrent_edit",
                                  "error": "live file changed: %s" % rel}
    changed = []
    for rel in sorted(surface):
        if _path_escapes_root(root, rel, include_leaf=True):
            return invalid("apply", "target path escapes the repository: %s" % rel)
        prop_path = stage / "proposed" / rel
        if not prop_path.is_file():
            continue
        base_sha = digest_file(stage / "base" / rel)
        if base_sha == digest_file(prop_path):
            continue
        live = root / rel
        if rel in known:
            if not live.is_file() or digest_file(live) != base_sha:
                return EXIT_BLOCKED, {"version": 1, "command": "apply",
                                      "status": "concurrent_edit",
                                      "error": "live file changed: %s" % rel}
        elif os.path.lexists(str(live)):
            return EXIT_BLOCKED, {"version": 1, "command": "apply",
                                  "status": "concurrent_edit",
                                  "error": "live file already exists: %s" % rel}
        changed.append(rel)
    live_dirty = status_paths(root) & surface
    live_delivery = delivery_state(Repo(root), surface_entries(root))
    action = live_delivery.get("action")
    if action == "worktree":
        return EXIT_BLOCKED, {"version": 1, "command": "apply", "status": "wrong_checkout",
                              "error": "the stage requires a linked worktree"}
    if action == "patch_only" or live_dirty:
        return _write_patch(stage, manifest, root)
    return _write_in_place(stage, manifest, root, changed)


def _write_patch(stage, manifest, root):
    base = stage / "base"
    proposed = stage / "proposed"
    proc = run_git(["diff", "--no-index", "--no-color", "--", "base", "proposed"], stage)
    if proc is None:
        return invalid("apply", "cannot run git diff")
    patch = proc.stdout
    if not patch.strip():
        return EXIT_OK, {"version": 1, "command": "apply", "status": "no_change"}
    try:
        (stage / "staged.patch").write_text(patch, encoding="utf-8")
    except OSError as exc:
        return invalid("apply", "cannot write staged.patch: %s" % exc)
    return EXIT_OK, {"version": 1, "command": "apply", "status": "patched",
                     "patch": str(stage / "staged.patch")}


def _atomic_restore(path, data, mode):
    handle, temp = tempfile.mkstemp(prefix=".sync-", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.chmod(temp, mode)
        os.replace(temp, str(path))
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _write_in_place(stage, manifest, root, changed):
    known = {entry["path"]: entry for entry in manifest.get("files", [])}
    written = []
    temp = None
    try:
        for rel in changed:
            live = root / rel
            if _path_escapes_root(root, rel, include_leaf=True) or live.is_symlink():
                raise OSError("target path escapes the repository: %s" % rel)
            proposed = stage / "proposed" / rel
            live.parent.mkdir(parents=True, exist_ok=True)
            existed = live.exists()
            handle, temp = tempfile.mkstemp(prefix=".sync-", dir=str(live.parent))
            os.close(handle)
            shutil.copyfile(str(proposed), temp)
            try:
                os.chmod(temp, known.get(rel, {}).get("mode", 0o644))
            except OSError:
                pass
            os.replace(temp, str(live))
            temp = None
            written.append((rel, existed))
    except OSError as exc:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
        for rel, existed in written:
            live = root / rel
            try:
                if existed:
                    _atomic_restore(live, (stage / "base" / rel).read_bytes(),
                                    known.get(rel, {}).get("mode", 0o644))
                else:
                    lives = live
                    if lives.exists():
                        lives.unlink()
            except OSError:
                pass
        return EXIT_BLOCKED, {"version": 1, "command": "apply", "status": "blocked",
                              "error": "replacement failed: %s" % exc}
    return EXIT_OK, {"version": 1, "command": "apply", "status": "applied",
                     "files": list(changed)}


AUDIT_PRUNED_DIRS = (
    ".git", "node_modules", "__pycache__", ".venv", "graft", ".mypy_cache",
    ".pytest_cache", ".backpass", ".worktrees", "dist", "build", ".next",
    ".svelte-kit", "target", "vendor",
)
AUDIT_OVERSIZED_LINES = 300
AUDIT_OVERSIZED_TOKENS = 3000
AUDIT_ROOT_DOCS = ("README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "DEVELOPMENT.md")
AUDIT_MANIFESTS = (
    "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Makefile",
    "Gemfile", "composer.json", "pom.xml", "build.gradle", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml",
)
AUDIT_INSTRUCTION_CATEGORIES = ("memory", "rules", "ide_rules", "skills", "commands", "subagents")
AT_IMPORT_LINE = re.compile(r"^\s*@([^\s`\"'<>]+)\s*$")
AT_IMPORT_TARGET = re.compile(r"(?:^|/)(?:AGENTS|CLAUDE|GEMINI)\.md$|[/.][A-Za-z0-9._-]+$")


def _frontmatter_meta(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {"has_frontmatter": False, "name": "", "description": "",
                "always_apply": None, "has_scope": False}
    body = []
    closed = False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        body.append(line)
    if not closed:
        return {"has_frontmatter": False, "name": "", "description": "",
                "always_apply": None, "has_scope": False}
    name = ""
    always_apply = None
    has_scope = False
    for line in body:
        m_name = re.match(r"name:\s*(.*)$", line)
        if m_name:
            name = m_name.group(1).strip().strip('"\'')
        m_always = re.match(r"alwaysApply:\s*(true|false)\s*$", line, re.I)
        if m_always:
            always_apply = m_always.group(1).lower() == "true"
        if re.match(r"(?:paths|globs|applyTo):\s*", line):
            has_scope = True
    return {
        "has_frontmatter": True,
        "name": name,
        "description": frontmatter_description(text),
        "always_apply": always_apply,
        "has_scope": has_scope,
    }


def _classify_audit_file(rel, skills_rel):
    rel = rel.replace(os.sep, "/")
    parts = Path(rel).parts
    name = parts[-1] if parts else ""
    if name in ("AGENTS.md", "AGENTS.override.md"):
        return "memory", "cross-agent", len(parts) == 1
    if name in ("CLAUDE.md", "CLAUDE.local.md"):
        return "memory", "claude", len(parts) == 1
    if name == "GEMINI.md":
        return "memory", "gemini", len(parts) == 1
    if rel == ".github/copilot-instructions.md":
        return "memory", "copilot", True
    if rel.startswith(".github/instructions/") and rel.endswith(".instructions.md"):
        return "rules", "copilot", False
    if rel.startswith(".claude/rules/") and rel.endswith(".md"):
        return "rules", "claude", True
    if rel.startswith(".agents/rules/") and rel.endswith(".md"):
        return "rules", "cross-agent", True
    if rel == ".cursorrules":
        return "ide_rules", "cursor", True
    if rel.startswith(".cursor/rules/") and (rel.endswith(".mdc") or rel.endswith(".md")):
        return "ide_rules", "cursor", False
    if rel == ".windsurfrules":
        return "ide_rules", "windsurf", True
    if rel.startswith(".windsurf/rules/") and rel.endswith(".md"):
        return "ide_rules", "windsurf", False
    if rel == ".clinerules" or (rel.startswith(".clinerules/") and rel.endswith(".md")):
        return "ide_rules", "cline", True
    skill_roots = [
        (skills_rel.rstrip("/") + "/", "cross-agent"),
        (".agents/skills/", "cross-agent"),
        (".claude/skills/", "claude"),
        (".codex/skills/", "codex"),
        (".gemini/skills/", "gemini"),
    ]
    for prefix, agent in skill_roots:
        if rel.startswith(prefix) and name == "SKILL.md":
            rest = rel[len(prefix):]
            if rest.count("/") == 1:
                return "skills", agent, False
    if rel.startswith(".claude/commands/") and rel.endswith(".md"):
        return "commands", "claude", False
    if rel.startswith(".agents/commands/") and rel.endswith(".md"):
        return "commands", "cross-agent", False
    if rel.startswith(".claude/agents/") and rel.endswith(".md"):
        return "subagents", "claude", False
    if rel.startswith(".agents/agents/") and rel.endswith(".md"):
        return "subagents", "cross-agent", False
    if rel.startswith(".claude/output-styles/") and rel.endswith(".md"):
        return "output_styles", "claude", False
    if rel.startswith(".trail/learnings/") and rel.endswith(".md") and len(parts) == 3:
        return "learnings", "cross-agent", False
    if rel in AUDIT_ROOT_DOCS or (rel.startswith("docs/") and rel.endswith(".md")):
        return "docs", "shared", False
    return None


def audit_surface(root, scope=None):
    root = Path(root)
    scope_rel = None
    if scope is not None:
        raw = str(scope).strip()
        if not raw or raw in (".", "./"):
            scope_rel = None
        else:
            scope_rel = normalize_rel(raw)
            if _path_escapes_root(root, scope_rel, include_leaf=True):
                raise ValueError("scope escapes repository root")
            if not (root / scope_rel).exists():
                raise ValueError("scope path does not exist")
    skills_rel = skills_dir(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        here = Path(dirpath)
        kept = []
        for dirname in sorted(dirnames):
            if dirname in AUDIT_PRUNED_DIRS:
                continue
            if dirname == "worktrees" and here.name == ".claude":
                continue
            child = here / dirname
            try:
                if child.is_symlink():
                    continue
                if (child / ".git").exists() or (child / ".git").is_symlink():
                    continue
            except OSError:
                continue
            kept.append(dirname)
        dirnames[:] = kept
        for filename in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, filename), str(root)).replace(os.sep, "/")
            if scope_rel is not None and rel != scope_rel and not rel.startswith(scope_rel + "/"):
                continue
            classified = _classify_audit_file(rel, skills_rel)
            if classified is None:
                continue
            path = root / rel
            category, agent, always_loaded = classified
            item = {"path": rel, "category": category, "agent": agent,
                    "always_loaded": always_loaded}
            if path.is_symlink():
                item["link"] = os.readlink(str(path))
                item["bytes"] = 0
                item["lines"] = 0
                item["tokens"] = 0
            else:
                try:
                    raw_bytes = path.read_bytes()
                except OSError:
                    continue
                text = raw_bytes.decode("utf-8", "replace")
                meta = _frontmatter_meta(text)
                if category == "rules" and meta["has_scope"]:
                    item["always_loaded"] = False
                elif category == "ide_rules" and meta["always_apply"] is not None:
                    item["always_loaded"] = meta["always_apply"]
                item["bytes"] = len(raw_bytes)
                item["lines"] = len(text.splitlines())
                item["tokens"] = int(math.ceil(len(raw_bytes) / 4.0))
                if category == "skills":
                    item["description_tokens"] = int(
                        math.ceil(len(meta["description"].encode("utf-8")) / 4.0))
            found.append(item)
    found.sort(key=lambda entry: entry["path"])
    return scope_rel, found


def _dangling_at_imports(root, items):
    dangling = []
    for item in items:
        if item.get("link") or item["category"] not in AUDIT_INSTRUCTION_CATEGORIES:
            continue
        rel = item["path"]
        try:
            text = (root / rel).read_text("utf-8", "replace")
        except OSError:
            continue
        in_fence = False
        parent = (root / rel).parent
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            match = AT_IMPORT_LINE.match(line)
            if not match:
                continue
            target = match.group(1).strip()
            if not AT_IMPORT_TARGET.search(target) or URL.match(target):
                continue
            if target.startswith(("~/", "/")):
                continue
            rel_candidate = parent / target
            root_candidate = root / target
            exists = False
            for candidate in (rel_candidate, root_candidate):
                try:
                    if candidate.exists() and _inside(candidate, root):
                        exists = True
                        break
                except OSError:
                    continue
            if not exists:
                dangling.append({"file": rel, "line": number, "import": "@" + target})
    return dangling


def _check_skill_frontmatter(root, items):
    issues = []
    for item in items:
        if item.get("link") or item["category"] != "skills":
            continue
        rel = item["path"]
        try:
            text = (root / rel).read_text("utf-8", "replace")
        except OSError:
            continue
        meta = _frontmatter_meta(text)
        folder = Path(rel).parent.name
        if not meta["has_frontmatter"]:
            issues.append({"file": rel, "error": "missing YAML frontmatter"})
            continue
        if not meta["name"]:
            issues.append({"file": rel, "error": "missing frontmatter name"})
        elif meta["name"] != folder:
            issues.append({"file": rel,
                           "error": "frontmatter name does not match folder (%s != %s)"
                           % (meta["name"], folder)})
        if not meta["description"]:
            issues.append({"file": rel, "error": "missing frontmatter description"})
    return issues


def _check_cross_file_duplicates(root, items):
    seen_inodes = set()
    line_locations = {}
    for item in items:
        if item.get("link") or item["category"] not in ("memory", "rules", "ide_rules"):
            continue
        rel = item["path"]
        path = root / rel
        try:
            info = os.stat(str(path))
            key = (info.st_dev, info.st_ino)
            if key in seen_inodes:
                continue
            seen_inodes.add(key)
            text = path.read_text("utf-8", "replace")
        except OSError:
            continue
        in_fence = False
        seen_in_file = set()
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence or len(stripped) < 40:
                continue
            if stripped.startswith(("#", "<!--", "@", "|", "---")):
                continue
            norm = " ".join(stripped.split())
            if norm in seen_in_file:
                continue
            seen_in_file.add(norm)
            line_locations.setdefault(norm, []).append({"file": rel, "line": number})
    duplicates = []
    for norm, locations in sorted(line_locations.items()):
        if len(locations) >= 2:
            duplicates.append({"text": redact(norm[:140]), "locations": locations})
            if len(duplicates) >= 50:
                break
    return duplicates


def _check_legacy_overlaps(items):
    paths = {item["path"] for item in items}
    overlaps = []
    if ".cursorrules" in paths and any(p.startswith(".cursor/rules/") for p in paths):
        overlaps.append({"legacy": ".cursorrules", "modern": ".cursor/rules/",
                         "note": "legacy .cursorrules present alongside .cursor/rules/"})
    if ".windsurfrules" in paths and any(p.startswith(".windsurf/rules/") for p in paths):
        overlaps.append({"legacy": ".windsurfrules", "modern": ".windsurf/rules/",
                         "note": "legacy .windsurfrules present alongside .windsurf/rules/"})
    return overlaps


def _docs_coverage(root, items):
    manifests = [name for name in AUDIT_MANIFESTS if (root / name).is_file()]
    present_docs = [name for name in ("AGENTS.md",) + AUDIT_ROOT_DOCS if (root / name).is_file()]
    missing_docs = [name for name in ("AGENTS.md", "README.md") if name not in present_docs]
    has_commands = False
    for name in ("AGENTS.md", "README.md"):
        path = root / name
        if path.is_file():
            try:
                if shell_fence_lines(path.read_text("utf-8", "replace")):
                    has_commands = True
                    break
            except OSError:
                pass
    return {
        "manifests": manifests,
        "present_docs": present_docs,
        "missing_recommended_docs": missing_docs,
        "has_command_examples": has_commands,
        "docs_file_count": sum(1 for item in items if item["category"] == "docs"),
    }


def audit_command(repo_path, scope=None):
    try:
        repo = Repo(repo_path)
    except (OSError, ValueError):
        return EXIT_INVALID, {"version": 1, "command": "audit", "status": "invalid",
                              "error": "repository is not usable"}
    try:
        scope_rel, items = audit_surface(repo.root, scope=scope)
    except ValueError as exc:
        return EXIT_INVALID, {"version": 1, "command": "audit", "status": "invalid",
                              "error": str(exc)}
    ref_items = [{**item, "ref": redact(item["ref"])}
                 for item in collect_references(repo, items)]
    ref_counts = Counter(item["class"] for item in ref_items)
    always_tokens = sum(item["tokens"] for item in items if item.get("always_loaded"))
    skill_desc_tokens = sum(item.get("description_tokens", 0) for item in items
                            if item["category"] == "skills")
    oversized = [
        {"path": item["path"], "lines": item["lines"], "tokens": item["tokens"]}
        for item in items
        if item.get("always_loaded") and (
            item["lines"] > AUDIT_OVERSIZED_LINES or item["tokens"] > AUDIT_OVERSIZED_TOKENS)
    ]
    budget = budget_report(repo.root)
    report = {
        "version": 1,
        "command": "audit",
        "status": "ok",
        "repo": {"id": repo.id, "kind": "git" if repo.is_git else "dir",
                 "head": repo.head, "default_branch": repo.default_branch},
        "scope": scope_rel,
        "inventory": items,
        "context_load": {
            "always_loaded_tokens": always_tokens + skill_desc_tokens,
            "always_loaded_file_tokens": always_tokens,
            "skill_description_tokens": skill_desc_tokens,
            "budget_cap": budget["cap"],
            "over_budget": (always_tokens + skill_desc_tokens) > budget["cap"],
            "oversized": oversized,
        },
        "budget": budget,
        "import": check_imports(repo),
        "references": {
            "total": len(ref_items),
            "counts": dict(sorted(ref_counts.items())),
            "stale": [item for item in ref_items if item["class"] == "stale"],
            "unverified": [item for item in ref_items if item["class"] == "unverified"],
            "items": ref_items,
        },
        "structure": {
            "dangling_imports": _dangling_at_imports(repo.root, items),
            "skill_frontmatter": _check_skill_frontmatter(repo.root, items),
            "duplicates": _check_cross_file_duplicates(repo.root, items),
            "legacy_overlaps": _check_legacy_overlaps(items),
        },
        "docs_coverage": _docs_coverage(repo.root, items),
    }
    return EXIT_OK, report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="check_instructions.py")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--repo", required=True)
    check.add_argument("--json", action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("--repo", required=True)
    audit.add_argument("--scope")
    audit.add_argument("--json", action="store_true")
    stage = sub.add_parser("stage")
    stage.add_argument("--repo", required=True)
    stage.add_argument("--out", required=True)
    stage.add_argument("--json", action="store_true")
    gate = sub.add_parser("gate")
    gate.add_argument("--stage", required=True)
    gate.add_argument("--evidence", required=True)
    gate.add_argument("--claims", required=True)
    gate.add_argument("--json", action="store_true")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--stage", required=True)
    apply_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "check":
        code, payload = check_command(args.repo)
    elif args.command == "audit":
        code, payload = audit_command(args.repo, scope=args.scope)
    elif args.command == "stage":
        code, payload = stage_command(args.repo, args.out)
    elif args.command == "gate":
        code, payload = validate_gate(args.stage, args.evidence, args.claims)
    else:
        code, payload = apply_command(args.stage)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
