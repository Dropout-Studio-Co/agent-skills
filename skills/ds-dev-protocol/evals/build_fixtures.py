#!/usr/bin/env python3
"""Build or verify the ds-dev-protocol behaviour eval fixtures (stdlib only, Python 3.9+).

usage: python3 -I -B evals/build_fixtures.py [--check]

  (default)  regenerate fixture.diff, packet-review.md / packet-plan.md, meta.json,
             keys.txt and inputs.sha256 from the fixture trees under fixtures/
  --check    recompute every one of them in memory and refuse on any byte that
             differs from disk; writes nothing and leaves no bytecode cache

Sources of truth: fixtures/<id>/fixture.json (request, tier, criteria) plus that
fixture's pre/, src/ or facts.md files. Nothing here embeds fixture text.
"""
import difflib
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
STATIC = ("keys.txt", "rubric.json")


def files(root):
    """Every text file under root as {posix relative path: text}, sorted."""
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(root.rglob("*")) if path.is_file() and "__pycache__" not in path.parts}


def diff(pre, post):
    """Unified diff of two trees, in the format gate.sh review accepts as --diff."""
    out = []
    for name in sorted(set(pre) | set(post)):
        a, b = pre.get(name), post.get(name)
        if a == b:
            continue
        left = a.splitlines(keepends=True) if a is not None else []
        right = b.splitlines(keepends=True) if b is not None else []
        out += list(difflib.unified_diff(left, right, "/dev/null" if a is None else "a/" + name,
                                        "/dev/null" if b is None else "b/" + name))
    return "".join(out)


def packet(meta, key, body):
    """The packet a gate reads: it must carry the gate, the tier, the key and the source body."""
    if meta["kind"] == "plan":
        return "Gate: plan\nTier: %s\nKey (sha256 of facts.md): %s\n\n%s" % (meta["tier"], key, body)
    lines = ["Gate: review", "Tier: " + meta["tier"], "Triggers: none",
             "Key (sha256 of the diff file): " + key, "", "## Request (verbatim)", meta["request"],
             "", "## Acceptance criteria (PLAN.md)"]
    lines += ["- " + item for item in meta.get("ac") or []]
    if meta.get("note"):
        lines += ["", meta["note"]]
    if meta.get("round2"):
        round2 = meta["round2"]
        lines += ["", "## Changes since the last round", "Last reviewed key: " + round2["last_key"], "",
                  "Diff from the last reviewed version:", "```diff", round2["delta"].rstrip("\n"), "```", "",
                  "Earlier findings:"]
        for finding, reason in round2["earlier"]:
            lines += ["- Finding (important): " + finding, "  " + reason]
    return "\n".join(lines + ["", "## Full diff", body])


def fixture_ids():
    return sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())


def generated():
    """{path relative to evals/: expected text} for every derived file."""
    out, keys = {}, []
    for fid in fixture_ids():
        root = FIXTURES / fid
        meta = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
        base = "fixtures/" + fid
        if meta["kind"] == "plan":
            body = (root / "facts.md").read_text(encoding="utf-8")
            key = hashlib.sha256(body.encode("utf-8")).hexdigest()
            out[base + "/packet-plan.md"] = packet(meta, key, body)
        else:
            body = diff(files(root / "pre") if (root / "pre").is_dir() else {}, files(root / "src"))
            key = hashlib.sha256(body.encode("utf-8")).hexdigest()
            out[base + "/fixture.diff"] = body
            out[base + "/packet-review.md"] = packet(meta, key, body)
        keys.append("%s %s" % (fid, key))
        out[base + "/meta.json"] = json.dumps(
            {"id": fid, "kind": meta["kind"], "gate": meta["kind"], "tier": meta["tier"], "key": key,
             "expect": meta["expect"], "summary": meta["summary"]}, indent=2, sort_keys=True) + "\n"
    out["keys.txt"] = "\n".join(keys) + "\n"
    snapshot = {}
    for path in sorted(FIXTURES.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            rel = path.relative_to(HERE).as_posix()
            snapshot[rel] = out.get(rel, path.read_text(encoding="utf-8"))
    snapshot.update(out)
    for name in STATIC:
        if name not in snapshot:
            snapshot[name] = (HERE / name).read_text(encoding="utf-8")
    out["inputs.sha256"] = "".join(
        "%s  %s\n" % (hashlib.sha256(snapshot[name].encode("utf-8")).hexdigest(), name)
        for name in sorted(snapshot))
    return out


def main():
    out = generated()
    if "--check" in sys.argv[1:]:
        bad = []
        for rel in sorted(out):
            path = HERE / rel
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != out[rel]:
                bad.append(rel)
        for rel in bad:
            print("fixture drift: %s" % rel)
        print("build_fixtures --check: %d files verified, %d drifted" % (len(out), len(bad)))
        return 1 if bad else 0
    for rel, text in sorted(out.items()):
        path = HERE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print("build_fixtures: wrote %d files for %d fixtures" % (len(out), len(fixture_ids())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
