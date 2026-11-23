#!/usr/bin/env python3
"""Collect a compact digest of past AI-agent sessions for one repository.

Scans local transcript stores of common coding agents (Claude Code and OpenCode,
plus any extra dirs you pass), keeps only sessions that ran inside the repo (its
main checkout or any live linked worktree), and prints the high-signal parts:
human messages (corrections flagged first) and failed tool calls. Secrets and
home paths are redacted.

Stdlib only. Usage:
  python3 collect_sessions.py [--repo PATH] [--days 60] [--max-chars 60000]
                              [--extra-dir DIR ...] [--strict]
                              [--evidence-out PATH]
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

HOME = Path.home()
GIT_STRIP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")

NOISE = re.compile(
    r"^\s*<(system-reminder|command-|local-command|user_instructions|environment_context)", re.I)
NOISE_PREFIXES = (
    "<task-notification",
    "Stop hook feedback",
    "<user-prompt-submit-hook>",
    "This session is being continued from a previous",
    "Base directory for this skill:",
    "Caveat: The messages below",
    "# Handoff:",
)
PASTED = re.compile(r"<pasted_content[^>]*>.*?(?:</pasted_content>|\Z)", re.S)
SELF_SESSION_MARKERS = ("<!-- ds-agent-docs:self-session -->",
                        "<!-- backpass:self-session -->")
IMPLEMENTER_OPENING = "You are the implementer for one step of a plan"
HUMAN_ROLES = ("user", "human", "user_message")

# Redaction. Held literals (token prefixes, home roots, the PEM header) are
# assembled at runtime so this file never carries a literal the sync holds.
_TOKEN_PREFIX = "gh"
_GITHUB_PAT = "git" + "hub" + "_pat_"
_SHOPIFY_TOKEN = "shp" + "(?:at|ca|pa|ss)_"
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_PEM_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_HOME_PATH = re.compile(r"(?:/" + "Users" + r"|/" + "home" + r")/[^/\s\"'`]+")
_SECRETS = [
    re.compile(r"(sk-[A-Za-z0-9_-]{16,}|" + _TOKEN_PREFIX + r"p_[A-Za-z0-9]{20,}|"
               + _TOKEN_PREFIX + r"[ousr]_[A-Za-z0-9]{20,}|"
               + _GITHUB_PAT + r"[A-Za-z0-9_]{20,}|"
               + _SHOPIFY_TOKEN + r"[A-Za-z0-9_]{16,}|"
               r"xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})"),
    re.compile(r"(?i)\b(bearer|token|password|passwd|secret|api[_-]?key)\b\s*[:=]?\s*\S{6,}"),
]

FENCED_CODE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
SENTENCE_START = re.compile(
    r"^(?:no|nope)\s*[,.;:!\-]"
    r"|^wrong\b|^incorrect\b|^stop\b|^don'?t\b|^do not\b|^never\b", re.I)
ANYWHERE = re.compile(
    r"that'?s wrong|not like that|i told you|i said|you should have|you shouldn'?t|"
    r"you forgot|you missed|you broke|instead of|\binstead\s*[.!]?$", re.I)


def _url_credentials(match):
    return match.group(1) + "[REDACTED]@"


def redact(value):
    text = value if isinstance(value, str) else str(value)
    text = _PEM_KEY.sub("[REDACTED]", text)
    text = _JWT.sub("[REDACTED]", text)
    text = _URL_CREDENTIALS.sub(_url_credentials, text)
    text = _EMAIL.sub("[REDACTED]", text)
    for pattern in _SECRETS:
        text = pattern.sub("[REDACTED]", text)
    text = _HOME_PATH.sub("[REDACTED]", text)
    return text


def fold(value):
    """Whitespace-folded text used for quote matching."""
    return re.sub(r"\s+", " ", value).strip()


def is_correction(text):
    """True when a human message reads as a correction of the agent's work."""
    if not isinstance(text, str) or not text.strip():
        return False
    cleaned = FENCED_CODE.sub(" ", text)
    cleaned = INLINE_CODE.sub(" ", cleaned)
    for raw in SENTENCE_SPLIT.split(cleaned):
        sentence = raw.strip()
        if not sentence or sentence.endswith("?"):
            continue
        if SENTENCE_START.search(sentence) or ANYWHERE.search(sentence):
            return True
    return False


def clip(text, limit):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_git(args, cwd):
    """Run git with repository-selecting variables stripped from the environment."""
    env = {key: value for key, value in os.environ.items() if key not in GIT_STRIP}
    try:
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True,
                              text=True, env=env)
    except (OSError, ValueError):
        return None


def repo_root(arg):
    if arg:
        return Path(arg).resolve()
    proc = run_git(["rev-parse", "--show-toplevel"], Path.cwd())
    if proc is not None and proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return Path.cwd().resolve()


def _relative_to(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except (OSError, ValueError):
        return False


def _nearest_existing(value):
    path = Path(value)
    try:
        path = path.resolve()
    except OSError:
        path = Path(os.path.abspath(str(path)))
    while not path.exists():
        parent = path.parent
        if parent == path:
            return None
        path = parent
    return path


def _common_dir(path):
    proc = run_git(["rev-parse", "--git-common-dir"], path)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = Path(path) / common
    try:
        common = common.resolve()
    except OSError:
        common = Path(os.path.abspath(str(common)))
    return str(common)


class Repo:
    """What counts as 'inside this repository': live worktrees sharing a common dir."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.is_git = False
        self.common = None
        self.worktrees = [self.root]
        self._member_cache = {}
        self._member_lock = threading.Lock()
        common = _common_dir(self.root)
        if common is not None:
            self.common = common
            self.is_git = True
            proc = run_git(["worktree", "list", "--porcelain"], self.root)
            if proc is not None and proc.returncode == 0:
                found = []
                for line in proc.stdout.splitlines():
                    if not line.startswith("worktree "):
                        continue
                    path = Path(line[len("worktree "):].strip())
                    try:
                        found.append(path.resolve())
                    except OSError:
                        found.append(Path(os.path.abspath(str(path))))
                if found:
                    self.worktrees = found
        basis = self.common if self.common is not None else str(self.root)
        self.repo_id = hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()

    def encoded_names(self):
        names = set()
        for worktree in [self.root] + list(self.worktrees):
            for path in (worktree, Path(os.path.realpath(str(worktree)))):
                names.add(re.sub(r"[^A-Za-z0-9]", "-", str(path)))
        return names

    def member(self, cwd):
        """True when cwd belongs to this repository; lookups are cached under a lock."""
        key = cwd if isinstance(cwd, str) else str(cwd)
        with self._member_lock:
            if key not in self._member_cache:
                self._member_cache[key] = self._member(key)
            return self._member_cache[key]

    def _member(self, cwd):
        if not isinstance(cwd, str) or not cwd.strip():
            return False
        if not self.is_git:
            return _relative_to(cwd, self.root)
        anchor = _nearest_existing(cwd)
        if anchor is None:
            return False
        if not any(_relative_to(anchor, worktree) for worktree in self.worktrees):
            return False
        common = _common_dir(anchor)
        return common is not None and common == self.common


def transcript_lines(path):
    """Yield decoded lines of a .jsonl or .jsonl.zst transcript, closing the source."""
    if path.suffix == ".zst":
        try:
            proc = subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                    errors="replace")
        except (OSError, ValueError):
            return
        try:
            for line in proc.stdout:
                yield line
        except OSError:
            return
        finally:
            proc.stdout.close()
            proc.wait()
        return
    try:
        handle = open(str(path), "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        try:
            for line in handle:
                yield line
        except OSError:
            return


def iter_json_records(path):
    """Yield one item per counted transcript entry: a dict, or None when it did not parse.

    Yields nothing for an unreadable file, so the item count stays the same total a
    whole-file read produced. `.jsonl` and `.jsonl.zst` stream line by line; blank lines
    are not counted. A `.json` object or list is parsed once.
    """
    if path.suffix == ".json":
        try:
            raw = path.read_text("utf-8", "replace")
        except (OSError, ValueError):
            return
        try:
            data = json.loads(raw)
        except ValueError:
            yield None
            return
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("messages") or data.get("history") or [data]
            if not isinstance(items, list):
                items = [data]
        else:
            items = [None]
        for item in items:
            yield item if isinstance(item, dict) else None
        return
    for line in transcript_lines(path):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            yield None
            continue
        yield record if isinstance(record, dict) else None


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in (None, "text", "input_text") \
                    and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    if isinstance(content, dict):
        return text_of(content.get("content") or content.get("text") or content.get("parts"))
    return ""


def find_cwd(record):
    for key in ("cwd", "workdir", "projectRoot", "project_root"):
        if isinstance(record.get(key), str):
            return record[key]
    payload = record.get("payload")
    if isinstance(payload, dict):
        return find_cwd(payload)
    return None


def record_parts(record):
    payload = record.get("payload")
    node = payload if isinstance(payload, dict) else record
    message = node.get("message")
    msg = message if isinstance(message, dict) else None
    return node, msg


def record_role(record):
    node, msg = record_parts(record)
    return (msg or {}).get("role") or node.get("role") or node.get("type") or record.get("type")


def field(record, key):
    node, msg = record_parts(record)
    for source in (record, node, msg):
        if isinstance(source, dict) and key in source:
            return source.get(key)
    return None


def origin_kind(value):
    if isinstance(value, dict):
        inner = value.get("kind", value.get("type"))
        return inner if isinstance(inner, str) else None
    return value if isinstance(value, str) else None


def remove_pasted(text):
    return PASTED.sub("", text)


def user_raw_text(record):
    node, msg = record_parts(record)
    content = None
    if isinstance(msg, dict):
        content = msg.get("content", msg.get("parts", msg.get("text")))
    if content is None:
        content = node.get("content", node.get("parts", node.get("text")))
    text = text_of(content)
    if not text and isinstance(node.get("message"), str):
        text = node["message"]
    return text if isinstance(text, str) else ""


def human_text(record):
    """Return the human-authored text of a record, or None when it is not human evidence."""
    node, msg = record_parts(record)
    if record_role(record) not in HUMAN_ROLES:
        return None
    if field(record, "isMeta") or field(record, "isSidechain") or field(record, "isCompactSummary"):
        return None
    kind = origin_kind(field(record, "origin"))
    if kind is not None and kind != "human":
        return None
    turn = origin_kind(field(record, "turnOrigin"))
    if turn is not None and turn != "human":
        return None
    entrypoint = field(record, "entrypoint")
    if isinstance(entrypoint, str) and entrypoint.startswith("sdk"):
        return None
    prompt_source = field(record, "promptSource")
    if prompt_source is not None and prompt_source != "typed":
        return None
    session_kind = field(record, "sessionKind")
    if isinstance(session_kind, str) and session_kind.lower() == "bg":
        return None
    user_type = field(record, "userType")
    if user_type is not None and user_type != "external":
        return None
    content = None
    if isinstance(msg, dict):
        content = msg.get("content", msg.get("parts", msg.get("text")))
    if content is None:
        content = node.get("content", node.get("parts", node.get("text")))
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return None
    text = text_of(content)
    if not text and isinstance(node.get("message"), str):
        text = node["message"]
    if not isinstance(text, str):
        return None
    text = remove_pasted(text).strip()
    if not text or NOISE.match(text) or text.startswith(NOISE_PREFIXES):
        return None
    return text


def _is_self_session(text):
    text = text.lstrip()
    return any(text.startswith(marker) for marker in SELF_SESSION_MARKERS)


def message_id(record, text):
    node, msg = record_parts(record)
    for source in (record, node, msg):
        if not isinstance(source, dict):
            continue
        for key in ("uuid", "messageId", "message_id", "id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def error_texts(record):
    node, msg = record_parts(record)
    out = []
    content = None
    if isinstance(msg, dict):
        content = msg.get("content")
    if content is None:
        content = node.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                out.append(text_of(block.get("content")))
    if node.get("type") in ("function_call_output", "exec_command_end"):
        output = node.get("output") if isinstance(node.get("output"), dict) else node
        code = output.get("exit_code") if isinstance(output, dict) else None
        if code not in (None, 0):
            out.append(text_of(output.get("output") or output.get("stderr") or ""))
    return [text for text in out if text]


def is_headless(record):
    entrypoint = field(record, "entrypoint")
    if isinstance(entrypoint, str) and entrypoint.startswith("sdk"):
        return True
    kind = field(record, "sessionKind")
    return isinstance(kind, str) and kind.lower() == "bg"


def well_formed_message(node, msg):
    if isinstance(msg, dict) and any(key in msg for key in ("content", "parts", "text")):
        return True
    message = node.get("message")
    if isinstance(message, str) and message.strip():
        return True
    if isinstance(node.get("content"), (str, list)):
        return True
    if isinstance(node.get("text"), str):
        return True
    return False


def recognized_record(record):
    """Return (recognized, is_well_formed_user_message)."""
    if not isinstance(record, dict):
        return False, False
    if not (isinstance(record.get("type"), str) or isinstance(record.get("role"), str)):
        return False, False
    node, msg = record_parts(record)
    role = record_role(record)
    if role in HUMAN_ROLES or role == "assistant":
        ok = well_formed_message(node, msg)
        return ok, bool(ok and role in HUMAN_ROLES)
    return True, False


def make_session(source, label, mtime, headless, human, errors, excluded=False, group=None):
    if not human and not errors:
        excluded = True
    try:
        mtime = float(mtime or 0)
    except (TypeError, ValueError):
        mtime = 0.0
    label = redact(str(label))
    return {
        "id": "%s:%s" % (source, label),
        "source": source,
        "label": label,
        "mtime": mtime,
        "kind": "headless" if headless else "interactive",
        "group": redact(str(group or label)),
        "human": human,
        "errors": [redact(error) for error in errors if error],
        "excluded": excluded,
    }


def scan_jsonl_session(path, mtime, source, repo):
    """Scan one transcript in a single streaming pass; the record count is the drift total."""
    total = recognized = 0
    user_ok = headless = excluded = False
    last_cwd, started = None, False
    human, errors = [], []
    for record in iter_json_records(path):
        total += 1
        if record is None:
            continue
        ok, is_user = recognized_record(record)
        if ok:
            recognized += 1
        if is_user:
            user_ok = True
        # A whole-session marker anywhere excludes the session, whatever its cwd.
        if not excluded and record_role(record) in HUMAN_ROLES:
            raw = user_raw_text(record)
            excluded = _is_self_session(raw) or raw.lstrip().startswith(IMPLEMENTER_OPENING)
        found = find_cwd(record)
        if found is not None:
            last_cwd, started = found, True
        if not started or last_cwd is None or not repo.member(last_cwd):
            continue
        if is_headless(record):
            headless = True
        text = human_text(record)
        if text:
            human.append({"msg": message_id(record, text), "text": redact(text),
                          "correction": is_correction(text)})
        errors.extend(error_texts(record))
    session = make_session(source, path.name, mtime, headless, human, errors, excluded=excluded)
    return session, {"total": total, "recognized": recognized, "user_ok": user_ok}


def scan_targets(targets, source, repo):
    """Scan (path, mtime) targets; sessions and stats keep the exact input order."""
    stats = {"total": 0, "recognized": 0, "user_ok": False}
    if not targets:
        return [], stats
    if len(targets) == 1:
        scanned = [scan_jsonl_session(targets[0][0], targets[0][1], source, repo)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            scanned = list(pool.map(
                lambda pair: scan_jsonl_session(pair[0], pair[1], source, repo), targets))
    sessions = []
    for session, file_stats in scanned:
        sessions.append(session)
        stats["total"] += file_stats["total"]
        stats["recognized"] += file_stats["recognized"]
        stats["user_ok"] = stats["user_ok"] or file_stats["user_ok"]
    return sessions, stats


def candidate_project_dirs(claude_home, repo):
    projects = claude_home / "projects"
    if not projects.is_dir():
        return []
    names = repo.encoded_names()
    out = []
    try:
        entries = list(projects.iterdir())
    except OSError:
        return []
    for entry in entries:
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if not is_dir:
            continue
        for name in names:
            if entry.name == name or entry.name.startswith(name + "-"):
                out.append(entry)
                break
    return out


def claude_sessions(repo, cutoff):
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (HOME / ".claude"))
    targets = []
    for directory in sorted(candidate_project_dirs(claude_home, repo)):
        try:
            files = sorted(list(directory.glob("*.jsonl")) + list(directory.glob("*.jsonl.zst")))
        except OSError:
            continue
        for path in files:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                targets.append((path, mtime))
    return scan_targets(targets, "claude-code", repo)


def extra_sessions(repo, extra_dirs, cutoff):
    targets = []
    for directory in extra_dirs:
        try:
            files = sorted(Path(directory).expanduser().rglob("*.json*"))
        except OSError:
            continue
        for path in files:
            try:
                if not path.is_file():
                    continue
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                targets.append((path, mtime))
    return scan_targets(targets, "extra", repo)


def filesystem_sessions(repo, extra_dirs, cutoff):
    """Scan the filesystem stores: Claude Code first, then the extra dirs."""
    return claude_sessions(repo, cutoff), extra_sessions(repo, extra_dirs, cutoff)


def drift_source(source, stats):
    if stats["total"] >= 20 and (stats["recognized"] * 2 < stats["total"] or not stats["user_ok"]):
        return source
    return None


def opencode_store():
    data_home = Path(os.environ.get("XDG_DATA_HOME") or (HOME / ".local" / "share"))
    return data_home / "opencode" / "opencode.db"


def recognize_opencode(mtype, data):
    if mtype == "user":
        ok = isinstance(data.get("text"), str)
        return ok, ok
    if mtype == "assistant":
        return isinstance(data.get("content"), list), False
    return True, False


def opencode_human_text(text):
    cleaned = remove_pasted(text).strip()
    if not cleaned or NOISE.match(cleaned) or cleaned.startswith(NOISE_PREFIXES):
        return None
    return cleaned


def opencode_errors(data):
    errors = []
    for item in data.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "tool":
            continue
        state = item.get("state") or {}
        if not isinstance(state, dict) or state.get("status") != "error":
            continue
        err = state.get("error")
        if isinstance(err, dict):
            message, kind = err.get("message"), err.get("type")
            if message and kind:
                detail = "%s: %s" % (kind, message)
            elif message or kind:
                detail = message or kind
            else:
                detail = json.dumps(err)
        elif isinstance(err, str) and err:
            detail = err
        else:
            detail = state.get("output") or item.get("name") or "tool error"
            if not isinstance(detail, str):
                detail = json.dumps(detail)
        errors.append(detail)
    return errors


def opencode_sessions(repo, cutoff):
    db = opencode_store()
    if not db.is_file():
        print("collect_sessions: no OpenCode database at %s; skipped" % db, file=sys.stderr)
        return [], 0, None
    base = "file:%s?mode=ro" % quote(str(db))
    wal = Path(str(db) + "-wal")
    shm = Path(str(db) + "-shm")
    if not wal.exists():
        uri = base + "&immutable=1"
    elif shm.exists():
        uri = base
    else:
        print("collect_sessions: OpenCode database has a WAL but no shared-memory file; "
              "skipped: %s" % db, file=sys.stderr)
        return [], 0, None
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        print("collect_sessions: cannot read OpenCode database %s; skipped: %s" % (db, exc),
              file=sys.stderr)
        return [], 0, "opencode"

    sessions = []
    v1_only = 0
    try:
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
            columns = set()
            if "session_v2" in tables:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(session_v2)")}
        except sqlite3.Error as exc:
            print("collect_sessions: skipping the OpenCode store (%s): %s" % (db, exc),
                  file=sys.stderr)
            return [], 0, "opencode"
        missing = ("session_v2" not in tables or "session_message" not in tables
                   or "parent_id" not in columns)
        if missing:
            print("collect_sessions: skipping the OpenCode store (%s): required tables or "
                  "parent_id column missing" % db, file=sys.stderr)
            return [], 0, "opencode"
        v2_ids = {row[0] for row in conn.execute("SELECT id FROM session_v2")}
        try:
            v1_columns = {row[1] for row in conn.execute("PRAGMA table_info(session)")}
            if v1_columns:
                has_time = "time_updated" in v1_columns
                query = "SELECT id, directory" + (", time_updated" if has_time else "") + \
                        " FROM session"
                for row in conn.execute(query):
                    session_id, directory = row[0], row[1]
                    if session_id in v2_ids:
                        continue
                    if not isinstance(directory, str) or not directory.strip():
                        continue
                    if not repo.member(directory):
                        continue
                    if has_time:
                        try:
                            last = float(row[2] or 0)
                        except (TypeError, ValueError):
                            last = 0.0
                        mtime = last / 1000.0 if last > 1e12 else last
                        if mtime < cutoff:
                            continue
                    v1_only += 1
        except sqlite3.Error:
            pass
        try:
            fork_select = ", s.fork_session_id" if "fork_session_id" in columns else ""
            rows = conn.execute(
                "SELECT s.id, s.directory, MAX(m.time_created), s.parent_id"
                + fork_select +
                " FROM session_v2 s "
                "JOIN session_message m ON m.session_id=s.id GROUP BY s.id").fetchall()
        except sqlite3.Error as exc:
            print("collect_sessions: skipping the OpenCode store (%s): %s" % (db, exc),
                  file=sys.stderr)
            return [], v1_only, "opencode"
        total = recognized = 0
        user_ok = False
        for row in rows:
            session_id, directory, last, parent_id = row[:4]
            fork_id = row[4] if len(row) > 4 else None
            group = fork_id if isinstance(fork_id, str) and fork_id else str(session_id)
            try:
                last_value = float(last or 0)
                mtime = last_value / 1000.0 if last_value > 1e12 else last_value
            except (TypeError, ValueError):
                mtime = 0.0
            if not isinstance(directory, str) or not directory.strip():
                continue
            if mtime < cutoff or not repo.member(directory):
                continue
            if parent_id not in (None, ""):
                sessions.append(make_session("opencode", str(session_id), mtime, False,
                                             [], [], excluded=True, group=group))
                continue
            human, errors = [], []
            excluded = False
            try:
                messages = conn.execute(
                    "SELECT id, type, data FROM session_message WHERE session_id = ? "
                    "ORDER BY seq", (session_id,)).fetchall()
            except sqlite3.Error as exc:
                print("collect_sessions: skipping an OpenCode session (%s): %s"
                      % (session_id, exc), file=sys.stderr)
                continue
            for message_id_value, mtype, data_text in messages:
                total += 1
                try:
                    data = json.loads(data_text)
                except (TypeError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                ok, well_formed_user = recognize_opencode(mtype, data)
                if ok:
                    recognized += 1
                if well_formed_user:
                    user_ok = True
                    raw = data.get("text")
                    stripped = raw.lstrip()
                    if _is_self_session(raw) or \
                            stripped.startswith(IMPLEMENTER_OPENING):
                        excluded = True
                    text = opencode_human_text(raw)
                    if text:
                        human.append({
                            "msg": str(message_id_value),
                            "text": redact(text),
                            "correction": is_correction(text),
                        })
                elif mtype == "assistant" and isinstance(data.get("content"), list):
                    errors.extend(opencode_errors(data))
            sessions.append(make_session("opencode", str(session_id), mtime, False, human,
                                         errors, excluded=excluded, group=group))
    finally:
        conn.close()
    if total >= 20 and (recognized * 2 < total or not user_ok):
        return sessions, v1_only, "opencode"
    return sessions, v1_only, None


def week_buckets(sessions, now):
    buckets = {}
    for session in sessions:
        index = int(max(0.0, now - session["mtime"]) // (7 * 86400))
        buckets.setdefault(index, []).append(session)
    return buckets


def round_robin(sessions, now):
    """One session per weekly bucket in turn, interactive groups before headless."""
    ordered = []
    for kind in ("interactive", "headless"):
        group = [s for s in sessions if not s["excluded"] and s["kind"] == kind]
        buckets = week_buckets(group, now)
        keys = sorted(buckets)
        for key in keys:
            buckets[key].sort(key=lambda s: s["mtime"], reverse=True)
        position = {key: 0 for key in keys}
        more = True
        while more:
            more = False
            for key in keys:
                if position[key] < len(buckets[key]):
                    ordered.append(buckets[key][position[key]])
                    position[key] += 1
                    more = True
    return ordered


def session_block(session):
    day = time.strftime("%Y-%m-%d", time.localtime(session["mtime"]))
    lines = ["## %s · %s · %s" % (day, session["source"], session["label"])]
    flagged = [item for item in session["human"] if item["correction"]][:15]
    others = [item for item in session["human"] if not item["correction"]]
    lines.extend("- ⚑ %s" % clip(item["text"], 400) for item in flagged)
    lines.extend("- %s" % clip(item["text"], 250) for item in others[:15])
    lines.extend("- ✗ error: %s" % clip(error, 200) for error in session["errors"][:8])
    return "\n".join(lines) + "\n"


def date_range(sessions):
    if not sessions:
        return "none", "none"
    stamps = [session["mtime"] for session in sessions]
    return (time.strftime("%Y-%m-%d", time.localtime(min(stamps))),
            time.strftime("%Y-%m-%d", time.localtime(max(stamps))))


def counts_for(sessions):
    total = len(sessions)
    interactive = sum(1 for s in sessions if not s["excluded"] and s["kind"] == "interactive")
    headless = sum(1 for s in sessions if not s["excluded"] and s["kind"] == "headless")
    return total, interactive, headless, total - interactive - headless


def header_line(repo, days, counts, shown, shown_sessions):
    total, interactive, headless, excluded = counts
    start, end = date_range(shown_sessions)
    return ("# Session digest for %s\n_%d sessions in last %d days: %d interactive, %d headless, "
            "%d excluded, %d shown. %s to %s. Corrections marked ⚑._"
            % (redact(str(repo.root)), total, days, interactive, headless, excluded, shown,
               start, end))


def build_digest(repo, sessions, days, max_chars, now, drift):
    counts = counts_for(sessions)
    ordered = round_robin(sessions, now)
    pairs = [(session, session_block(session)) for session in ordered]
    shown = 0
    chosen = []
    chosen_sessions = []
    for _ in range(6):
        header = header_line(repo, days, counts, shown, chosen_sessions)
        remaining = max_chars - len(header)
        chosen, chosen_sessions = [], []
        for session, block in pairs:
            if len(block) <= remaining:
                chosen.append(block)
                chosen_sessions.append(session)
                remaining -= len(block)
        if len(chosen) == shown:
            break
        shown = len(chosen)
    header = header_line(repo, days, counts, shown, chosen_sessions)
    body = "".join(chosen)
    lines = ["FORMAT DRIFT: %s" % source for source in drift]
    lines.append(header)
    text = "\n".join(lines) + "\n" + body
    return text, shown, counts, date_range(chosen_sessions)


def build_evidence(repo, sessions, days, now, drift, v1_only):
    total, interactive, headless, excluded = counts_for(sessions)
    included = [s for s in sessions if not s["excluded"]]
    start, end = date_range(included)
    return {
        "version": 1,
        "repo_id": repo.repo_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "window_days": days,
        "counts": {
            "total": total,
            "interactive": interactive,
            "headless": headless,
            "excluded": excluded,
            "shown": len(included),
            "opencode_v1_only": v1_only,
        },
        "date_range": {"start": start, "end": end},
        "drift": list(drift),
        "sessions": [{
            "id": session["id"],
            "source": session["source"],
            "kind": session["kind"],
            "date": time.strftime("%Y-%m-%d", time.localtime(session["mtime"])),
            "group": session["group"],
            "human": session["human"],
            "errors": session["errors"],
        } for session in included],
    }


def _inside_git_worktree(directory):
    probe = Path(directory)
    try:
        probe = probe.resolve()
    except OSError:
        probe = Path(os.path.abspath(str(probe)))
    while True:
        if probe.name == ".git":
            return True
        try:
            if (probe / ".git").exists():
                return True
        except OSError:
            pass
        if probe.parent == probe:
            break
        probe = probe.parent
    proc = run_git(["rev-parse", "--show-toplevel"], directory)
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def evidence_path_problem(path):
    target = Path(path)
    if os.path.lexists(str(target)):
        return "path already exists"
    parent = target.parent if str(target.parent) else Path(".")
    try:
        parent_real = Path(os.path.realpath(str(parent)))
    except OSError:
        return "parent path is not usable"
    if not parent_real.is_dir():
        return "parent directory does not exist"
    if _inside_git_worktree(parent_real):
        return "path is inside a git worktree"
    return None


def write_evidence(path, data):
    problem = evidence_path_problem(path)
    if problem:
        print("collect_sessions: refusing to write evidence (%s): %s" % (problem, path),
              file=sys.stderr)
        return 2
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(path), flags, 0o600)
    except OSError as exc:
        print("collect_sessions: cannot create evidence file %s: %s" % (path, exc),
              file=sys.stderr)
        return 2
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        print("collect_sessions: cannot write evidence file %s: %s" % (path, exc),
              file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--max-chars", type=int, default=60000)
    parser.add_argument("--extra-dir", action="append", default=[])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--evidence-out")
    args = parser.parse_args(argv)

    repo = Repo(repo_root(args.repo))
    now = time.time()
    cutoff = now - args.days * 86400
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        stored = pool.submit(filesystem_sessions, repo, args.extra_dir, cutoff)
        opens_future = pool.submit(opencode_sessions, repo, cutoff)
        (claude, claude_stats), (extra, extra_stats) = stored.result()
        opens, v1_only, opencode_drift = opens_future.result()
    sessions = claude + extra + opens
    drift = [source for source in (drift_source("claude-code", claude_stats),
                                   drift_source("extra", extra_stats),
                                   opencode_drift) if source]

    text, shown, counts, _range = build_digest(repo, sessions, args.days, args.max_chars,
                                               now, drift)
    if args.evidence_out:
        evidence = build_evidence(repo, sessions, args.days, now, drift, v1_only)
        evidence["counts"]["digest_shown"] = shown
        status = write_evidence(args.evidence_out, evidence)
        if status:
            return status
    print(text, end="")
    if args.strict and drift:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
