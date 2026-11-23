#!/usr/bin/env python3
"""Read-only mechanical survey of a repository's agent instructions and docs.

  audit --repo <root> [--scope <path>] [--budget-tokens N] [--skills-dir DIR] [--json]

Prints one JSON object on stdout; exit 0 ok, 2 invalid/unsafe input. Never writes.
Stdlib only, Python 3.9+.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
GIT_STRIP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
OK, BAD = 0, 2
DEFAULT_SKILLS, DEFAULT_BUDGET, BIG = ".agents/skills", 5000, (300, 3000)
PRUNED = {".git", "node_modules", "__pycache__", ".venv", "graft", ".mypy_cache",
          ".pytest_cache", ".worktrees", "dist", "build", ".next", ".svelte-kit",
          "target", "vendor"}
PRUNED_PATHS = {(".trail", "cache"), (".claude", "worktrees")}
ROOT_DOCS = ("README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "DEVELOPMENT.md")
MANIFESTS = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Makefile", "Gemfile",
             "composer.json", "pom.xml", "build.gradle", "Dockerfile", "docker-compose.yml",
             "docker-compose.yaml")
INSTRUCTION = ("memory", "rules", "ide_rules", "skills", "commands", "subagents")
KNOWN_EXT = {".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonc",
             ".yaml", ".yml", ".toml", ".sh", ".bash", ".zsh", ".svelte", ".css", ".html",
             ".rs", ".go", ".rb", ".php", ".sql", ".xml", ".txt", ".mdc", ".cfg", ".ini",
             ".env"}
SHELLS = ("sh", "bash", "zsh", "shell", "console")
BACKTICK = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
PH = re.compile(r"[<>{}*?\[\]]")
PKG = re.compile(r"^\s*(?:npm|pnpm|bun|yarn)\s+run\s+([^\s;&|]+)")
MAKE = re.compile(r"^\s*make\s+([^\s;&|]+)")
AT = re.compile(r"^\s*@([^\s`\"'<>]+)\s*$")
AT_TARGET = re.compile(r"(?:^|/)(?:AGENTS|CLAUDE|GEMINI)\.md$|[/.][A-Za-z0-9._-]+$")
PR_YES = re.compile(r"(?i)(\bmust\b|\brequires?\b|\brequired\b|\balways\b|\bonly\b|\buse\b|"
                    r"\bthrough\b|\bvia\b|\bopen\b|\bgo through\b).{0,60}\b(pull request|PR)\b")
PR_NO = re.compile(r"(?i)(\bno\b|\bnever\b|\bnot\b|\bdon'?t\b|\bdo not\b|\bforbid\w*\b|"
                   r"\bmust not\b).{0,60}\b(direct(?:ly)?\s+)?(push|commit)")
BRANCH = re.compile(r"\A[A-Za-z0-9._/-]+\Z")

_spec = importlib.util.spec_from_file_location(
    "collect_sessions_shared", str(HERE / "collect_sessions.py"))
COLLECT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(COLLECT)
redact = COLLECT.redact

# Held literals (token prefixes, home roots, the PEM header) are assembled at runtime in
# collect_sessions.py; reuse those patterns instead of restating any literal here.
HYGIENE_PATTERNS = (COLLECT._HOME_PATH, COLLECT._PEM_KEY, COLLECT._JWT,
                    COLLECT._URL_CREDENTIALS) + tuple(COLLECT._SECRETS)


def git(args, cwd):
    env = {k: v for k, v in os.environ.items() if k not in GIT_STRIP}
    try:
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True,
                              text=True, env=env)
    except (OSError, ValueError):
        return None


def out(root, *args):
    proc = git(list(args), root)
    return proc.stdout.strip() if proc and proc.returncode == 0 else ""


def tok(n):
    return (int(n) + 3) // 4


def norm(v):
    v = str(v).replace(os.sep, "/")
    return v[2:] if v.startswith("./") else v


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def escapes(root, rel, leaf=False):
    """True when rel is absolute, climbs out, or crosses a symlink/escape."""
    parts, cur = Path(norm(rel)).parts, Path(root)
    if not parts or os.path.isabs(norm(rel)) or ".." in parts:
        return True
    try:
        for part in (parts if leaf else parts[:-1]):
            cur = cur / part
            if cur.is_symlink() or not inside(os.path.realpath(str(cur)), root):
                return True
    except OSError:
        return True
    return False


def good_branch(name):
    return bool(isinstance(name, str) and BRANCH.match(name) and not name.startswith("-")
                and ".." not in name and "//" not in name)


def branch_exists(root, name):
    proc = git(["show-ref", "--verify", "--quiet", "refs/heads/" + name], root)
    return bool(proc and proc.returncode == 0)


def repo_info(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("repository path is not a directory")
    common = out(root, "rev-parse", "--git-common-dir")
    if not common:
        return {"root": root, "is_git": False, "head": "", "current": "", "default": None,
                "id": hashlib.sha256(str(root).encode("utf-8", "replace")).hexdigest()}
    path = Path(common)
    basis = os.path.realpath(str(path if path.is_absolute() else root / path))
    default = out(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").split("/", 1)[-1]
    if not good_branch(default):
        default = next((n for n in ("main", "master") if branch_exists(root, n)), "")
    if not default:
        name = out(root, "config", "--get", "init.defaultBranch")
        default = name if good_branch(name) and branch_exists(root, name) else ""
    return {"root": root, "is_git": True, "head": out(root, "rev-parse", "HEAD"),
            "current": out(root, "rev-parse", "--abbrev-ref", "HEAD"), "default": default or None,
            "id": hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()}


def status_paths(root):
    proc = git(["status", "--porcelain"], root)
    if not proc or proc.returncode != 0:
        return set()
    return {line[3:].split(" -> ", 1)[-1].strip().strip('"')
            for line in proc.stdout.splitlines() if len(line) >= 4}


def has_pr_rule(root):
    for name in ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md"):
        text = read(Path(root) / name)
        if text and any(PR_YES.search(x) or PR_NO.search(x) for x in text.splitlines()):
            return True
    return False


def worktree_commands(info):
    if not good_branch(info["default"]):
        return []
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = re.sub(r"[^A-Za-z0-9._-]", "-", info["root"].name) or "repo"
    spot = '"$HOME"' + shlex.quote("/.local/state/ds-agent-docs/worktrees/%s-%s" % (name, stamp))
    return ["git fetch origin -- %s" % shlex.quote(info["default"]),
            "git worktree add -b %s -- %s %s" % (
                shlex.quote("docs/ds-sync-%s" % stamp), spot,
                shlex.quote("origin/" + info["default"]))]


def delivery(info, items):
    surfaces = {i["path"] for i in items if i["category"] == "skills" or Path(i["path"]).name in (
        "AGENTS.md", "CLAUDE.md", "AGENTS.override.md", "CLAUDE.local.md")}

    def state(action, reason, dirty=False, commands=None):
        return {"action": action, "reason": reason, "dirty": dirty, "commands": commands or []}

    if status_paths(info["root"]) & surfaces:
        return state("patch_only", "dirty memory file", True)
    if not info["is_git"]:
        return state("in_place", "not a git repository")
    if info["default"] is None:
        return state("patch_only", "unknown default branch")
    if info["current"] == "HEAD":
        return state("worktree", "detached HEAD", commands=worktree_commands(info))
    if info["current"] != info["default"]:
        return state("in_place", "task branch")
    if has_pr_rule(info["root"]):
        return state("worktree", "default branch with a written PR rule",
                     commands=worktree_commands(info))
    return state("in_place", "default branch without a written PR rule")


def frontmatter(text):
    lines = text.splitlines()
    blank = {"has": False, "name": "", "description": "", "scope": False, "always_apply": None}
    if not lines or lines[0].strip() != "---":
        return blank
    body, closed = [], False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        body.append(line)
    if not closed:
        return blank
    name, desc, apply, scope = "", "", None, False
    for index, line in enumerate(body):
        hit = re.match(r"name:\s*(.*)$", line)
        if hit:
            name = hit.group(1).strip().strip('"\'')
        hit = re.match(r"description:\s*(.*)$", line)
        if hit:
            desc = hit.group(1).strip()
            if desc in ("|", ">", "|-", ">-"):
                # Block scalar: only indented continuation lines belong to the description.
                # A later top-level key (for example `metadata:`) ends it.
                parts = []
                for follow in body[index + 1:]:
                    if not follow.strip():
                        continue
                    if follow[:1] not in (" ", "\t"):
                        break
                    parts.append(follow.strip())
                desc = " ".join(parts)
            desc = desc.strip('"\'')
        hit = re.match(r"alwaysApply:\s*(true|false)\s*$", line, re.I)
        if hit:
            apply = hit.group(1).lower() == "true"
        scope = scope or bool(re.match(r"(?:paths|globs|applyTo):\s*", line))
    return {"has": True, "name": name, "description": desc, "scope": scope,
            "always_apply": apply}


def classify(rel, roots):
    name, depth = rel.rsplit("/", 1)[-1], rel.count("/") + 1
    memory = {"AGENTS.md": "cross-agent", "AGENTS.override.md": "cross-agent", "CLAUDE.md": "claude",
              "CLAUDE.local.md": "claude", "GEMINI.md": "gemini"}
    if name in memory:
        return "memory", memory[name], depth == 1
    if rel == ".github/copilot-instructions.md":
        return "memory", "copilot", True
    if rel.startswith(".github/instructions/") and rel.endswith(".instructions.md"):
        return "rules", "copilot", False
    for pre, kind, agent, always in (
            (".claude/rules/", "rules", "claude", True), (".agents/rules/", "rules", "cross-agent", True),
            (".claude/commands/", "commands", "claude", False),
            (".agents/commands/", "commands", "cross-agent", False),
            (".claude/agents/", "subagents", "claude", False),
            (".agents/agents/", "subagents", "cross-agent", False),
            (".claude/output-styles/", "output_styles", "claude", False)):
        if rel.startswith(pre) and rel.endswith(".md"):
            return kind, agent, always
    if rel in (".cursorrules", ".windsurfrules"):
        return "ide_rules", "cursor" if rel == ".cursorrules" else "windsurf", True
    if rel.startswith(".cursor/rules/") and rel.endswith((".mdc", ".md")):
        return "ide_rules", "cursor", False
    if rel.startswith(".windsurf/rules/") and rel.endswith(".md"):
        return "ide_rules", "windsurf", False
    if rel == ".clinerules" or (rel.startswith(".clinerules/") and rel.endswith(".md")):
        return "ide_rules", "cline", True
    for pre, agent in roots:
        if rel.startswith(pre) and name == "SKILL.md" and rel[len(pre):].count("/") == 1:
            return "skills", agent, False
    if rel.startswith(".trail/learnings/") and rel.endswith(".md") and depth == 3:
        return "learnings", "cross-agent", False
    if rel in ROOT_DOCS or (rel.startswith("docs/") and rel.endswith(".md")):
        return "docs", "shared", False
    return None


def skill_roots_for(skills_rel):
    roots, seen = [], set()
    for pre, agent in [(skills_rel.rstrip("/") + "/", "cross-agent"),
                       (".agents/skills/", "cross-agent"), (".claude/skills/", "claude"),
                       (".gemini/skills/", "gemini")]:
        if pre not in seen:
            seen.add(pre)
            roots.append((pre, agent))
    return roots


def discover(info, scope, skills_rel):
    root, roots, items = info["root"], skill_roots_for(skills_rel), []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        here = os.path.relpath(dirpath, str(root)).replace(os.sep, "/")
        here = "" if here == "." else here
        kept = []
        for name in sorted(dirnames):
            child = Path(dirpath) / name
            if name in PRUNED or (here, name) in PRUNED_PATHS or child.is_symlink():
                continue
            try:
                if (child / ".git").exists() or (child / ".git").is_symlink():
                    continue
            except OSError:
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), str(root)).replace(os.sep, "/")
            if scope is not None and rel != scope and not rel.startswith(scope + "/"):
                continue
            found = classify(rel, roots)
            if found is None:
                continue
            kind, agent, always = found
            item = {"path": rel, "category": kind, "agent": agent, "always_loaded": always}
            path = root / rel
            if path.is_symlink():
                item.update({"link": os.readlink(str(path)), "bytes": 0, "lines": 0, "tokens": 0})
            else:
                data = read_bytes(path)
                if data is None:
                    continue
                text = data.decode("utf-8", "replace")
                meta = frontmatter(text)
                if kind == "rules" and meta["scope"]:
                    item["always_loaded"] = False
                elif kind == "ide_rules" and meta["always_apply"] is not None:
                    item["always_loaded"] = meta["always_apply"]
                item.update({"bytes": len(data), "lines": len(text.splitlines()),
                             "tokens": tok(len(data))})
                if kind == "skills":
                    item["description_tokens"] = tok(len(meta["description"].encode("utf-8")))
            items.append(item)
    return sorted(items, key=lambda e: e["path"])


def read_bytes(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def read(path):
    try:
        return path.read_text("utf-8", "replace")
    except OSError:
        return None


def inode(root, rel):
    try:
        info = os.stat(str(root / rel))
        return (info.st_dev, info.st_ino), info.st_size
    except OSError:
        return None, 0


def context_load(root, items, cap):
    seen, files, oversized = set(), 0, []
    for item in items:
        if not item.get("always_loaded"):
            continue
        key, size = inode(root, item["path"])
        if key is None or key in seen:
            continue
        seen.add(key)
        count = tok(size)
        files += count
        if item["lines"] > BIG[0] or count > BIG[1]:
            oversized.append({"path": item["path"], "lines": item["lines"], "tokens": count})
    desc, seen = 0, set()
    for item in items:
        if item["category"] == "skills":
            key, _size = inode(root, item["path"])
            if key is not None and key not in seen:
                seen.add(key)
                desc += item.get("description_tokens", 0)
    total = files + desc
    return {"always_loaded_tokens": total, "always_loaded_file_tokens": files,
            "skill_description_tokens": desc, "budget_cap": cap, "over_budget": total > cap,
            "oversized": oversized}


def outside_fences(text):
    """Yield (line number, stripped line, fence language or None)."""
    in_fence, lang = False, ""
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            lang = stripped.lstrip("`~").strip().lower() if not in_fence else ""
            in_fence = not in_fence
            continue
        yield number, stripped, lang if in_fence else None


def first_outside_comment(text):
    """First non-empty line outside code fences and outside <!-- --> comments."""
    in_comment = False
    for _number, stripped, fence in outside_fences(text):
        if fence is not None:
            continue
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue
        return stripped
    return None


def check_imports(root, items):
    directories = set()
    for item in items:
        if item["category"] == "memory" and Path(item["path"]).name in ("AGENTS.md", "CLAUDE.md"):
            parent = str(Path(item["path"]).parent).replace(os.sep, "/")
            directories.add("" if parent == "." else parent)
    errors = []
    for directory in sorted(directories):
        base = root / directory if directory else root
        rel_a = (directory + "/AGENTS.md") if directory else "AGENTS.md"
        rel_c = (directory + "/CLAUDE.md") if directory else "CLAUDE.md"
        agents, claude = base / "AGENTS.md", base / "CLAUDE.md"
        a_on = agents.exists() or agents.is_symlink()
        c_on = claude.exists() or claude.is_symlink()
        if c_on and not a_on:
            errors.append({"file": rel_a, "error": "missing AGENTS.md"})
        elif a_on and not c_on:
            errors.append({"file": rel_c, "error": "missing CLAUDE.md import"})
        elif a_on and c_on and claude.is_symlink():
            candidate = os.path.normpath(os.path.join(str(base), os.readlink(str(claude))))
            if os.path.realpath(candidate) != os.path.realpath(str(agents)):
                errors.append({"file": rel_c, "error": "symlink points elsewhere"})
        elif a_on and c_on:
            errors.extend(import_errors(rel_c, read(claude), read(agents)))
    return {"ok": not errors, "errors": errors}


def import_errors(rel_c, text, agents_text):
    if text is None:
        return [{"file": rel_c, "error": "unreadable CLAUDE.md"}]
    errors = []
    if re.search(r"`\s*@AGENTS\.md\s*`", text):
        errors.append({"file": rel_c, "error": "backticked import"})
    if first_outside_comment(text) != "@AGENTS.md":
        errors.append({"file": rel_c, "error": "missing @AGENTS.md import"})
    shared = {s for _n, s, _f in outside_fences(agents_text or "") if len(s) >= 4}
    for number, stripped, _f in outside_fences(text):
        if stripped != "@AGENTS.md" and len(stripped) >= 4 and stripped in shared \
                and not stripped.startswith(("#", "<!--")):
            errors.append({"file": rel_c, "line": number, "error": "line duplicated from AGENTS.md"})
    return errors


def strip_ref(value):
    value = re.sub(r":\d+(?::\d+)?$", "", str(value).strip())
    return re.sub(r"#.*$", "", value).rstrip(".,;:!?)]}\"'").strip()


def suffix_of(ref):
    leaf = ref.rsplit("/", 1)[-1]
    return "." + leaf.split(".")[-1] if "." in leaf else ""


def tracked(root):
    proc = git(["ls-files", "-z"], root)
    return [p for p in proc.stdout.split("\0") if p] if proc and proc.returncode == 0 else []


def ignored(root, ref, cache):
    if ref not in cache:
        proc = git(["check-ignore", "-q", "--", ref], root)
        cache[ref] = bool(proc and proc.returncode == 0)
    return cache[ref]


def classify_ref(root, files, ref, file_rel, kind, cache, shell=False):
    ref = strip_ref(ref)
    if not ref or ref.startswith(("#", "-")):
        return None
    if shell:
        hit = PKG.match(ref)
        if hit:
            token = hit.group(1)
            if token.startswith("-"):
                return None
            return "scoped" if PH.search(token) else package(root, files, token)
        hit = MAKE.match(ref)
        if not hit:
            return None
        token = hit.group(1)
        if token.startswith("-"):
            return None
        return "scoped" if PH.search(token) else make(root, token)
    if URL.match(ref) or ref.startswith(("mailto:", "~", "/", "$")):
        return "external"
    if PH.search(ref):
        return "scoped"
    for base in [root] + ([(root / file_rel).parent] if file_rel else []):
        try:
            candidate = base / ref
            if candidate.exists() and inside(candidate, root):
                return "ok"
        except OSError:
            continue
    if ignored(root, ref, cache):
        return "ignored"
    if kind == "link":
        return "stale"
    if "/" not in ref:
        return "ok" if ref in files or any(t.endswith("/" + ref) for t in files) else "scoped"
    if any(t.endswith("/" + ref) for t in files):
        return "ok"
    if ref.startswith("../"):
        return "external"
    first = ref.split("/", 1)[0]
    return "stale" if ref.startswith("./") or (root / first).is_dir() \
        or suffix_of(ref) in KNOWN_EXT else "scoped"


def package(root, files, name):
    manifests = [(root / "package.json", "ok")] if (root / "package.json").is_file() else []
    manifests += [(root / rel, "scoped") for rel in files
                  if rel.endswith("package.json") and rel != "package.json"]
    for path, klass in manifests:
        try:
            scripts = json.loads(path.read_text("utf-8", "replace")).get("scripts")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(scripts, dict) and name in scripts:
            return klass
    return "stale" if manifests else "unverified"


def make(root, target):
    text = read(root / "Makefile") if (root / "Makefile").is_file() else None
    if text is None:
        return "unverified"
    return "ok" if re.search(r"^%s\s*:" % re.escape(target), text, re.M) else "stale"


def ref_item(file_rel, line, value, klass):
    return {"file": file_rel, "line": line, "ref": redact(value.strip()), "class": klass}


def collect_references(root, items):
    files, cache, found = tracked(root), {}, []
    for item in items:
        if item.get("link"):
            continue
        text = read(root / item["path"])
        if text is None:
            continue
        for number, stripped, fence in outside_fences(text):
            if fence is not None:
                if fence in SHELLS and stripped and not stripped.startswith("#"):
                    klass = classify_ref(root, files, stripped, item["path"], "fence", cache, True)
                    if klass:
                        found.append(ref_item(item["path"], number, stripped, klass))
                continue
            for match in LINK.finditer(stripped):
                klass = classify_ref(root, files, match.group(1), item["path"], "link", cache)
                if klass:
                    found.append(ref_item(item["path"], number, match.group(1), klass))
            for match in BACKTICK.finditer(stripped):
                value = match.group(1)
                klass = classify_ref(root, files, value, item["path"], "inline", cache, True)
                if klass is None and " " not in value.strip():
                    klass = classify_ref(root, files, value, item["path"], "inline", cache)
                if klass:
                    found.append(ref_item(item["path"], number, value, klass))
    return found


def structure(root, items):
    dangling, issues, seen, locations = [], [], set(), {}
    for item in items:
        if item.get("link") or item["category"] not in INSTRUCTION:
            continue
        rel, text = item["path"], read(root / item["path"])
        if text is None:
            continue
        for number, stripped, fence in outside_fences(text):
            match = None if fence is not None else AT.match(stripped)
            if match:
                target = match.group(1).strip()
                if not URL.match(target) and not target.startswith(("~/", "/")) \
                        and AT_TARGET.search(target) and not any(
                            exists(c, root) for c in ((root / rel).parent / target, root / target)):
                    dangling.append({"file": rel, "line": number, "import": "@" + target})
        if item["category"] != "skills":
            continue
        meta, folder = frontmatter(text), Path(rel).parent.name
        if not meta["has"]:
            issues.append({"file": rel, "error": "missing YAML frontmatter"})
        elif not meta["name"]:
            issues.append({"file": rel, "error": "missing frontmatter name"})
        elif meta["name"] != folder:
            issues.append({"file": rel, "error": "frontmatter name does not match folder (%s != %s)"
                           % (meta["name"], folder)})
        if meta["has"] and not meta["description"]:
            issues.append({"file": rel, "error": "missing frontmatter description"})
    for item in items:
        if item.get("link") or item["category"] not in ("memory", "rules", "ide_rules"):
            continue
        path = root / item["path"]
        try:
            info = os.stat(str(path))
            if (info.st_dev, info.st_ino) in seen:
                continue
            seen.add((info.st_dev, info.st_ino))
            text = path.read_text("utf-8", "replace")
        except OSError:
            continue
        local = set()
        for number, stripped, fence in outside_fences(text):
            if fence is not None or len(stripped) < 40 \
                    or stripped.startswith(("#", "<!--", "@", "|")):
                continue
            clean = " ".join(stripped.split())
            if clean not in local:
                local.add(clean)
                locations.setdefault(clean, []).append({"file": item["path"], "line": number})
    duplicates = []
    for clean, spots in sorted(locations.items()):
        if len(spots) >= 2:
            duplicates.append({"text": redact(clean[:140]), "locations": spots})
            if len(duplicates) >= 50:
                break
    paths = {item["path"] for item in items}
    overlaps = [{"legacy": old, "modern": new, "note": "legacy %s present alongside %s" % (old, new)}
                for old, new in ((".cursorrules", ".cursor/rules/"),
                                 (".windsurfrules", ".windsurf/rules/"))
                if old in paths and any(p.startswith(new) for p in paths)]
    return {"dangling_imports": dangling, "skill_frontmatter": issues,
            "duplicates": duplicates, "legacy_overlaps": overlaps}


def exists(path, root):
    try:
        return path.exists() and inside(path, root)
    except OSError:
        return False


def hygiene(root, items):
    hits = []
    for item in items:
        if item.get("link") or item["category"] not in INSTRUCTION:
            continue
        text = read(root / item["path"])
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in HYGIENE_PATTERNS):
                hits.append({"file": item["path"], "line": number,
                             "redacted": redact(line.strip())[:200]})
                if len(hits) >= 50:
                    return {"redaction_hits": hits}
    return {"redaction_hits": hits}


def docs(root, items):
    present = [name for name in ("AGENTS.md",) + ROOT_DOCS if (root / name).is_file()]
    has_commands = any(
        re.search(r"^```+\s*(sh|bash|zsh|shell|console)", read(root / name) or "", re.M)
        for name in ("AGENTS.md", "README.md") if (root / name).is_file())
    return {"manifests": [name for name in MANIFESTS if (root / name).is_file()],
            "present_docs": present,
            "missing_recommended_docs": [n for n in ("AGENTS.md", "README.md") if n not in present],
            "has_command_examples": has_commands,
            "docs_file_count": sum(1 for i in items if i["category"] == "docs")}


def resolve(root, value, label, want_dir):
    if value is None:
        return norm(DEFAULT_SKILLS) if label == "skills" else None
    raw = str(value).strip()
    if label == "scope" and raw in ("", ".", "./"):
        return None
    rel = norm(raw) if raw not in ("", ".") else ""
    if rel and escapes(root, rel, leaf=True):
        raise ValueError("%s escapes repository root" % label)
    target = root / rel if rel else root
    if want_dir and not target.is_dir():
        raise ValueError("%s does not exist" % label)
    if not want_dir and (not rel or not target.exists() or not inside(target, root)):
        raise ValueError("%s does not exist" % label)
    return rel or None


def audit_command(repo_path, scope=None, budget=DEFAULT_BUDGET, skills_given=None):
    invalid = {"version": 1, "command": "audit", "status": "invalid"}
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        return BAD, dict(invalid, error="budget tokens must be a positive integer")
    try:
        info = repo_info(repo_path)
        scope_rel = resolve(info["root"], scope, "scope", False)
        skills_rel = resolve(info["root"], skills_given, "skills", True)
    except (OSError, ValueError) as exc:
        return BAD, dict(invalid, error=str(exc) or "repository is not usable")
    items = discover(info, scope_rel, skills_rel)
    refs = collect_references(info["root"], items)
    return OK, {
        "version": 1, "command": "audit", "status": "ok",
        "repo": {"id": info["id"], "kind": "git" if info["is_git"] else "dir", "head": info["head"],
                 "current_branch": "" if info["current"] == "HEAD" else info["current"],
                 "default_branch": info["default"]},
        "scope": scope_rel, "delivery": delivery(info, items), "inventory": items,
        "context_load": context_load(info["root"], items, budget),
        "import": check_imports(info["root"], items),
        "references": {"total": len(refs),
                       "counts": dict(sorted(Counter(i["class"] for i in refs).items())),
                       "stale": [i for i in refs if i["class"] == "stale"], "items": refs},
        "structure": structure(info["root"], items), "hygiene": hygiene(info["root"], items),
        "docs_coverage": docs(info["root"], items)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check_instructions.py")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--repo", required=True)
    audit.add_argument("--scope")
    audit.add_argument("--budget-tokens", type=int, default=DEFAULT_BUDGET)
    audit.add_argument("--skills-dir")
    audit.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    code, payload = audit_command(args.repo, scope=args.scope, budget=args.budget_tokens,
                                  skills_given=args.skills_dir)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
