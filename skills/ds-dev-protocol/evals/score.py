#!/usr/bin/env python3
"""score.py - validate and score gate-eval records against rubric.json (stdlib only).

usage: score.py --fixture <id> --record <file>
       score.py --run <out-dir> [--variant NAME] [--append-jsonl] [--allow-partial]

exit: 0 every scored fixture matched; 1 a miss (an uncaught defect, an Important on a clean
fixture, or over five nits); 2 invalid (usage, oversized or unreadable record, schema
failure, wrong key, partial batch, or a metrics path inside a git repository).
"""
import argparse, fcntl, json, os, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
REPO = SKILL.parent.parent
STATE = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
USAGE = "usage: score.py --fixture <id> --record <file> | --run <out-dir> [--variant <n>] [--append-jsonl]"


def validate(schema, value, path="$"):
    """Validate value against the subset of JSON Schema the gate schemas use."""
    kind = schema.get("type")
    if kind == "object" or schema.get("required"):
        if not isinstance(value, dict):
            return path + " must be an object"
        allowed = schema.get("properties") or {}
        problems = [path + " missing " + n for n in schema.get("required", []) if n not in value]
        problems += ["%s unexpected key %s" % (path, n) for n in value if schema.get("additionalProperties") is False and n not in allowed]
        problems += [validate(allowed[n], value[n], path + "." + n) for n in allowed if n in value]
        return next((problem for problem in problems if problem), "")
    if kind == "array" and not isinstance(value, list):
        return path + " must be an array"
    if kind == "array":
        items = schema.get("items") or {}
        return next((p for p in (validate(items, v, "%s[%d]" % (path, i)) for i, v in enumerate(value)) if p), "")
    if kind == "string":
        if not isinstance(value, str):
            return path + " must be a string"
        if "enum" in schema and value not in schema["enum"]:
            return "%s must be one of %s" % (path, schema["enum"])
    return ""


def read_record(path, limit):
    """Return (payload, problem); a gate output file is unwrapped to its structured_output."""
    try:
        size = os.path.getsize(path)
    except OSError as problem:
        return None, "record %s not readable: %s" % (Path(path).name, problem.strerror)
    if size > limit:
        return None, "record is %d bytes; the limit is %d" % (size, limit)
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:
        return None, "record %s is not readable JSON: %s" % (Path(path).name, problem)
    if isinstance(value, dict) and isinstance(value.get("structured_output"), dict):
        value = value["structured_output"]
    return value, ""


def score_review(payload, rule, limits):
    notes, findings = [], [item for item in payload.get("findings") or [] if isinstance(item, dict)]
    important = [item for item in findings if item.get("severity") == "important"]
    nits = [item for item in findings if item.get("severity") == "nit"]
    if len(nits) > limits["max_nits"]:
        notes.append("%d nits; the brief caps nits at %d" % (len(nits), limits["max_nits"]))
    if rule["expect"] == "clean":
        if important:
            notes.append("%d Important finding(s) on a clean fixture; first at %s"
                         % (len(important), important[0].get("location")))
        if payload.get("verdict") != "pass":
            notes.append("verdict %r; a clean fixture must pass" % payload.get("verdict"))
        return not notes, notes
    hits = [item for item in important if re.search(rule["file"], str(item.get("location")))
            and re.search(rule["pattern"], "%s %s" % (item.get("failure_scenario"), item.get("evidence")))]
    if payload.get("verdict") != "fail":
        notes.append("verdict %r; the defect needed a fail" % payload.get("verdict"))
    if not hits:
        notes.append("no Important at %s matching %s" % (rule["file"], rule["pattern"]))
    return not notes, notes


def score_plan(payload, rule, tier):
    notes = ["plan tier %r, fixture tier %s" % (payload.get("tier"), tier)] if payload.get("tier") != tier else []
    files = " ".join(str(item) for item in payload.get("files") or [])
    notes += ["plan files do not name %s" % need for need in rule.get("files") or [] if not re.search(need, files)]
    text = " ".join([str(payload.get("design") or "")] +
                    [str(item) for key in ("acceptance_criteria", "tests", "risks")
                     for item in payload.get(key) or []])
    if not re.search(rule["pattern"], text):
        notes.append("plan text does not name the required cause or guard: %s" % rule["pattern"])
    if rule.get("forbid") and re.search(rule["forbid"], text):
        notes.append("plan text drops the guard: %s" % rule["forbid"])
    return not notes, notes


def evaluate(fid, path, rubric, keys):
    """Return (status, notes) with status one of ok, miss, invalid."""
    rule = rubric["fixtures"].get(fid)
    if not rule:
        return "invalid", ["unknown fixture %r" % (fid,)]
    meta = json.loads((HERE / "fixtures" / fid / "meta.json").read_text(encoding="utf-8"))
    if meta.get("key") != keys.get(fid):
        return "invalid", ["fixture meta key %s disagrees with keys.txt %s" % (meta.get("key"), keys.get(fid))]
    payload, problem = read_record(path, rubric["limits"]["max_record_bytes"])
    if problem or not isinstance(payload, dict):
        return "invalid", [problem or "record is not a JSON object"]
    if payload.get("gate") != rule["kind"]:
        return "invalid", ["record gate %r, fixture kind %s" % (payload.get("gate"), rule["kind"])]
    schema = json.loads((SKILL / ("plan-schema.json" if rule["kind"] == "plan" else "review-schema.json")).read_text(encoding="utf-8"))
    problem = validate(schema, payload)
    if problem:
        return "invalid", ["schema " + problem]
    if rule["kind"] == "review" and payload.get("head_sha") != keys.get(fid):
        return "invalid", ["wrong key: head_sha %r, fixture key %s" % (payload.get("head_sha"), keys.get(fid))]
    ok, notes = (score_plan(payload, rule, meta["tier"]) if rule["kind"] == "plan"
                 else score_review(payload, rule, rubric["limits"]))
    return ("ok" if ok else "miss"), notes


def inside_repo(path):
    """True when path sits inside this skills repository or any git worktree."""
    resolved = Path(os.path.abspath(path))
    if resolved == REPO or REPO in resolved.parents:
        return True
    probe = resolved.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    try:
        return subprocess.run(["git", "-C", str(probe), "rev-parse", "--git-dir"],
                              capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def append_row(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(json.dumps(row, sort_keys=True) + "\n"); handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    for name in ("fixture", "record", "run", "variant", "jsonl"):
        parser.add_argument("--" + name, default="")
    for name in ("append-jsonl", "allow-partial", "help"):
        parser.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    if args.help: print(USAGE); return 0
    rubric = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))
    keys = dict(line.split() for line in (HERE / "keys.txt").read_text(encoding="utf-8").split("\n") if line.strip())
    if not args.run:
        if not args.fixture or args.fixture not in rubric["fixtures"] or not args.record:
            print(USAGE, file=sys.stderr)
            return 2
        if args.append_jsonl:
            print("score.py: --append-jsonl needs a full --run, never one fixture", file=sys.stderr)
            return 2
        status, notes = evaluate(args.fixture, args.record, rubric, keys)
        print("%s %s%s" % (args.fixture, status, "" if not notes else ": " + "; ".join(notes)))
        return {"ok": 0, "miss": 1}.get(status, 2)
    try:
        manifest = json.loads((Path(args.run) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:
        print("score.py: %s is not a prepared run: %s" % (args.run, problem), file=sys.stderr)
        return 2
    results = []
    for entry in manifest.get("fixtures") or []:
        path = Path(entry.get("evid") or "") / ("%s-%s.json" % (entry.get("kind"), entry.get("key")))
        status, notes = ("missing", ["%s not recorded" % path.name]) if not path.is_file() else evaluate(entry.get("id"), path, rubric, keys)
        results.append({"id": entry.get("id"), "status": status, "notes": notes})
        print("%s %s%s" % (entry.get("id"), status, "" if not notes else ": " + "; ".join(notes)))
    passed = sum(1 for item in results if item["status"] == "ok")
    counts = {name: sum(1 for item in results if item["status"] == name) for name in ("invalid", "missing")}
    row = {"date": time.strftime("%Y-%m-%d"), "eval": "ds-dev-protocol", "fixtures": len(results),
           "passed": passed, "variant": args.variant or manifest.get("variant") or Path(args.run).name,
           "score": round(passed / len(results), 3) if results else 0,
           "misses": [item for item in results if item["status"] != "ok"]}
    print(json.dumps({name: row[name] for name in ("variant", "fixtures", "passed", "score")}, sort_keys=True))
    if not args.append_jsonl:
        return 0 if not sum(counts.values()) and passed == len(results) else 1
    target = Path(args.jsonl) if args.jsonl else STATE / "review-metrics" / "evals.jsonl"
    if inside_repo(target):
        print("score.py: refusing to append inside a git repository: %s" % target, file=sys.stderr)
        return 2
    if sum(counts.values()) and not args.allow_partial:
        print("score.py: %d invalid and %d missing; pass --allow-partial to record anyway"
              % (counts["invalid"], counts["missing"]), file=sys.stderr)
        return 2
    append_row(target, row)
    print("appended one row to %s" % target)
    return 0 if not sum(counts.values()) and passed == len(results) else 1

if __name__ == "__main__": sys.exit(main())
