"""Tests for the ds-dev-protocol behaviour eval set (stdlib only, Python 3.9+).

Run: python3 -I -B -m unittest skills/ds-dev-protocol/tests/test_evals.py
Every fixture command runs with -I -B so no bytecode cache lands in the repository.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
EVALS = SKILL / "evals"
REPO = SKILL.parent.parent
KEYS = {
    "F1": "70f073f5116d8d0c89858e50f0ad12f9c292dca0ea553160e6759909c4224943",
    "F2": "cdab3e6dfba2ec864b232cac477ca8d4f053c7c1c91af08de95ab9f4a985e9ab",
    "F3": "b255e8cd37c0549d037791449be4d2c5c9ba94958ed00d0074cc2bac603ec16e",
    "F4": "1eeda8623c148d3475ec9902f5c2e6458362aae5a02f6af948acc654f4d477f5",
    "F5": "cb5abbe67a1e12dca7d62e989d809ea424578c6b9b7b647ff3d0277164e69f28",
}
FIXTURE_IDS = ["F1", "F2", "F3", "F4", "F5", "plan-guard-kept", "plan-root-cause", "review-race"]


def run(*argv, cwd=None, env=None):
    """Run a command in the eval directory (or cwd) and return the CompletedProcess."""
    return subprocess.run([str(item) for item in argv], cwd=str(cwd or EVALS),
                          capture_output=True, text=True, env=env)


def python(*argv, cwd=None):
    return run(sys.executable, "-I", "-B", *argv, cwd=cwd)


def fixture_key(fid):
    for line in (EVALS / "keys.txt").read_text(encoding="utf-8").splitlines():
        if line.split()[0] == fid:
            return line.split()[1]
    return ""


def review_payload(fid, verdict, findings):
    return {"gate": "review", "head_sha": fixture_key(fid), "verdict": verdict,
            "summary": "synthetic record for %s" % fid, "findings": findings}


def important(location, scenario, evidence="reproduced by hand"):
    return {"severity": "important", "location": location, "failure_scenario": scenario, "evidence": evidence}


PASSING = {
    "F1": review_payload("F1", "fail", [important("stats.py:6", "average_score divides by an empty score list; ZeroDivisionError for a new user")]),
    "F2": review_payload("F2", "fail", [important("test_slug.py:11", "the regression test does not exercise repeated spaces and passes against the pre-fix slugify")]),
    "F3": review_payload("F3", "fail", [important("pagination.py:7", "off-by-one: size - 1 drops the last item of every page")]),
    "F4": review_payload("F4", "pass", []),
    "F5": review_payload("F5", "pass", []),
    "review-race": review_payload("review-race", "fail", [important("coupons.py:9", "check-then-act race: two threads both see no row and both insert; no lock or unique constraint")]),
    "plan-root-cause": {"gate": "plan", "tier": "medium", "acceptance_criteria": ["a tag-free request sees no tags"],
                        "design": "filters_for shallow-copies DEFAULT_FILTERS, so every request shares one tags list; return a fresh list (deepcopy) per call",
                        "files": ["filters.py", "tests/test_filters.py"], "tests": ["search twice, assert filters_for({})['tags'] == []"],
                        "risks": ["the cache key changes with the tag list"], "rollback": "git revert"},
    "plan-guard-kept": {"gate": "plan", "tier": "high", "acceptance_criteria": ["nested export paths stay inside the tenant"],
                        "design": "keep os.path.realpath on both sides and the os.path.commonpath check, and add nested-path tests; symlink escapes stay refused",
                        "files": ["exports.py", "tests/test_exports.py"], "tests": ["nested path allowed, .. refused, symlink refused"],
                        "risks": ["a string prefix check would reopen traversal"], "rollback": "git revert"},
}


def write_records(root, payloads):
    """Write one gate-shaped record per fixture and return a manifest dict."""
    entries = []
    for fid in FIXTURE_IDS:
        meta = json.loads((EVALS / "fixtures" / fid / "meta.json").read_text(encoding="utf-8"))
        evid = Path(root) / ("evid-" + fid)
        evid.mkdir(parents=True, exist_ok=True)
        if payloads.get(fid) is not None:
            record = {"structured_output": payloads[fid], "provenance": {"provenance_mode": "t3-verified"}}
            (evid / ("%s-%s.json" % (meta["kind"], meta["key"]))).write_text(
                json.dumps(record), encoding="utf-8")
        entries.append({"id": fid, "kind": meta["kind"], "tier": meta["tier"], "key": meta["key"], "evid": str(evid)})
    out = Path(root) / "run"
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps({"variant": "unit", "fixtures": entries}), encoding="utf-8")
    return out


class FixtureSetTests(unittest.TestCase):
    def test_build_fixtures_check(self):
        done = python("build_fixtures.py", "--check")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("0 drifted", done.stdout)

    def test_inputs_sha256(self):
        done = run("shasum", "-a", "256", "-c", "inputs.sha256")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("FAILED", done.stdout)

    def test_frozen_keys(self):
        for fid, key in KEYS.items():
            self.assertEqual(fixture_key(fid), key, fid)
            meta = json.loads((EVALS / "fixtures" / fid / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["key"], key, fid)

    def test_no_home_paths_and_no_legacy_name(self):
        for path in EVALS.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("/" + "Users/", text, str(path))
                self.assertIsNone(re.search("execution[ -]protocol", text), str(path))

    def test_no_pycache(self):
        self.assertEqual([str(p) for p in EVALS.rglob("__pycache__")], [])

    def test_plan_facts_do_not_leak_the_diagnosis(self):
        facts = (EVALS / "fixtures" / "plan-root-cause" / "facts.md").read_text(encoding="utf-8")
        for spoiler in ("shallow", "DEFAULT_FILTERS", "filters.py:8", "dict("):
            self.assertNotIn(spoiler, facts)
        guard = (EVALS / "fixtures" / "plan-guard-kept" / "facts.md").read_text(encoding="utf-8")
        for spoiler in ("realpath", "commonpath", "abspath"):
            self.assertNotIn(spoiler, guard)

    def test_line_limits_and_executable_bits(self):
        limits = {"build_fixtures.py": 180, "fixture-check.sh": 90, "run.sh": 140, "score.py": 200}
        for name, limit in limits.items():
            lines = len((EVALS / name).read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(lines, limit, name)
        for name in ("fixture-check.sh", "run.sh", "score.py"):
            self.assertTrue(os.access(EVALS / name, os.X_OK), name)

    def test_shell_syntax(self):
        for shell in ("bash", "zsh"):
            if shutil.which(shell):
                done = run(shell, "-n", EVALS / "run.sh")
                self.assertEqual(done.returncode, 0, done.stderr)
        done = run("bash", "-n", EVALS / "fixture-check.sh")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_fixture_check(self):
        done = run("bash", EVALS / "fixture-check.sh")
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr)
        self.assertIn("ALL 8 FIXTURES VERIFIED", done.stdout)


class RunScriptTests(unittest.TestCase):
    def test_help_in_bash_and_zsh(self):
        self.assertEqual(run("bash", EVALS / "run.sh", "--help").returncode, 0)
        self.assertEqual(python("score.py", "--help").returncode, 0)
        if shutil.which("zsh"):
            self.assertEqual(run("zsh", EVALS / "run.sh", "--help").returncode, 0)

    def test_default_gate_is_the_skill_gate(self):
        self.assertIn('GATE=${DS_EVAL_GATE:-$SKILL/scripts/gate.sh}', (EVALS / "run.sh").read_text(encoding="utf-8"))

    def test_record_forwards_high_effort_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stub = root / "stub.sh"
            stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$STUB_ARGS"\n', encoding="utf-8")
            (root / "evid").mkdir()
            (root / "work").mkdir()
            (root / "record.json").write_text("{}", encoding="utf-8")
            args_file = root / "args.txt"
            env = dict(os.environ, DS_EVAL_GATE=str(stub), STUB_ARGS=str(args_file))
            for tags in ("diff-large", "diff-large,ui-overhaul"):
                done = run("bash", EVALS / "run.sh", "record", "--evid", "evid", "--tier", "medium",
                           "--record", "record.json", "--child-thread", "c1", "--parent-thread", "p1",
                           "--high-effort", tags, "--force", cwd=root, env=env)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                seen = args_file.read_text(encoding="utf-8").splitlines()
                self.assertIn("--high-effort", seen)
                self.assertEqual(seen[seen.index("--high-effort") + 1], tags)

    def test_record_rejects_high_effort_without_a_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "evid").mkdir()
            done = run("bash", EVALS / "run.sh", "record", "--evid", "evid", "--tier", "medium",
                       "--record", "record.json", "--child-thread", "c1", "--parent-thread", "p1",
                       "--high-effort", cwd=root)
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertIn("--high-effort needs a value", done.stderr)

    def test_record_keeps_gate_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "stub.sh"
            stub.write_text('#!/usr/bin/env bash\nexit "${STUB_EXIT:-0}"\n', encoding="utf-8")
            evid = Path(tmp) / "evid"
            evid.mkdir()
            (Path(tmp) / "work").mkdir()
            record = Path(tmp) / "record.json"
            record.write_text("{}", encoding="utf-8")
            for code in (0, 1, 2, 3, 4):
                env = dict(os.environ, DS_EVAL_GATE=str(stub), STUB_EXIT=str(code))
                done = run("bash", EVALS / "run.sh", "record", "--evid", evid, "--gate", "review",
                           "--tier", "medium", "--record", record, "--child-thread", "c1",
                           "--parent-thread", "p1", "--force", env=env)
                self.assertEqual(done.returncode, code, done.stdout + done.stderr)
                self.assertEqual((evid / "exit").read_text(encoding="utf-8").strip(), str(code))

    def test_record_skips_a_scored_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "stub.sh"
            stub.write_text('#!/usr/bin/env bash\nexit 0\n', encoding="utf-8")
            evid = Path(tmp) / "evid"
            evid.mkdir()
            (Path(tmp) / "work").mkdir()
            record = Path(tmp) / "record.json"
            record.write_text("{}", encoding="utf-8")
            (evid / "exit").write_text("1\n", encoding="utf-8")
            env = dict(os.environ, DS_EVAL_GATE=str(stub))
            done = run("bash", EVALS / "run.sh", "record", "--evid", evid, "--tier", "medium",
                       "--record", record, "--child-thread", "c1", "--parent-thread", "p1", env=env)
            self.assertEqual(done.returncode, 0)
            self.assertIn("already recorded", done.stdout)

    def test_record_resolves_paths_and_defaults_the_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stub = root / "stub.sh"
            stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$STUB_ARGS"\n'
                            'printf "state=%s\\n" "${XDG_STATE_HOME:-unset}" >> "$STUB_ARGS"\n',
                            encoding="utf-8")
            (root / "evid").mkdir()
            (root / "work").mkdir()
            (root / "evid" / "fixture.diff").write_text("diff\n", encoding="utf-8")
            (root / "record.json").write_text("{}", encoding="utf-8")
            args_file = root / "args.txt"
            env = dict(os.environ, DS_EVAL_GATE=str(stub), STUB_ARGS=str(args_file))
            done = run("bash", EVALS / "run.sh", "record", "--evid", "evid", "--tier", "medium",
                       "--record", "record.json", "--child-thread", "c1", "--parent-thread", "p1",
                       "--force", cwd=root, env=env)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            seen = args_file.read_text(encoding="utf-8").splitlines()
            real = os.path.realpath(str(root))
            self.assertIn(real + "/record.json", seen)
            self.assertIn(real + "/evid/fixture.diff", seen)
            self.assertIn("state=" + real + "/evid/state", seen)

    def test_prepare_stages_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            done = run("bash", EVALS / "run.sh", "prepare", "--out-dir", out)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(entry["id"] for entry in manifest["fixtures"]), FIXTURE_IDS)
            for entry in manifest["fixtures"]:
                work = Path(entry["work"])
                self.assertTrue(list(work.glob("*.py")), entry["id"])
                self.assertNotEqual(run("git", "-C", work, "rev-parse", "--git-dir").returncode, 0)
                for hidden in ("answer-key.md", "rubric.json", "meta.json", "fixture.json"):
                    self.assertFalse((work / hidden).exists(), "%s %s" % (entry["id"], hidden))
                evid = Path(entry["evid"])
                self.assertTrue((evid / "facts.md").exists() if entry["kind"] == "plan"
                                else (evid / "fixture.diff").exists(), entry["id"])

    def test_prepare_rejects_an_unsafe_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            done = run("bash", EVALS / "run.sh", "prepare", "--variant", "../escape",
                       "--out-dir", out)
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertIn("bad --variant/--fixture name", done.stderr)
            self.assertFalse(out.exists())

    def test_prepare_refuses_an_in_repo_out_dir(self):
        target = SKILL / "evals" / ".prepare-probe"
        in_git = run("git", "-C", SKILL, "rev-parse", "--git-dir").returncode == 0
        done = run("bash", EVALS / "run.sh", "prepare", "--out-dir", target)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("inside the git repository" if in_git else "inside the skill directory", done.stderr)
        self.assertFalse(target.exists())

    def test_prepare_refuses_out_dir_inside_non_git_skill_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "ds-dev-protocol"
            shutil.copytree(EVALS, skill / "evals", ignore=shutil.ignore_patterns("__pycache__"))
            runner = skill / "evals" / "run.sh"
            self.assertNotEqual(run("git", "-C", skill, "rev-parse", "--git-dir").returncode, 0)
            (root / "link").symlink_to(skill / "evals", target_is_directory=True)
            cases = [skill / "evals" / ".stage", skill, root / "link", root / "missing" / ".." / skill.name]
            for target in cases:
                done = run("bash", runner, "prepare", "--out-dir", target)
                self.assertEqual(done.returncode, 2, "%s: %s" % (target, done.stdout + done.stderr))
                self.assertIn("inside the skill directory", done.stderr, str(target))
                self.assertFalse((Path(os.path.realpath(str(target))) / "manifest.json").exists(), str(target))
            sibling = Path(str(skill) + "-sibling")
            done = run("bash", runner, "prepare", "--out-dir", sibling, "--fixture", "F1")
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue((sibling / "manifest.json").exists())

    def test_prepare_refuses_out_dir_inside_temp_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "home").mkdir()
            env = dict(os.environ, HOME=str(repo / "home"), GIT_CONFIG_NOSYSTEM="1")
            init = run("git", "-C", repo, "init", "-q", env=env)
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
            target = repo / "stage"
            done = run("bash", EVALS / "run.sh", "prepare", "--out-dir", target, env=env)
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertIn("inside the git repository", done.stderr)
            self.assertFalse(target.exists())

    def test_prepare_refuses_hash_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "skill" / "evals"
            shutil.copytree(EVALS, copy, ignore=shutil.ignore_patterns("__pycache__"))
            (copy / "fixtures" / "F1" / "src" / "stats.py").write_text("# drift\n", encoding="utf-8")
            done = run("bash", copy / "run.sh", "prepare", "--out-dir", Path(tmp) / "out")
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertIn("hash drift", done.stderr)


class ScoreTests(unittest.TestCase):
    def test_single_fixture_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fid in FIXTURE_IDS:
                record = Path(tmp) / (fid + ".json")
                record.write_text(json.dumps({"structured_output": PASSING[fid]}), encoding="utf-8")
                done = python("score.py", "--fixture", fid, "--record", record)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertIn("ok", done.stdout)

    def test_a_missing_record_exits_two_without_appending(self):
        with tempfile.TemporaryDirectory() as tmp:
            payloads = dict(PASSING)
            payloads["F3"] = None
            out = write_records(tmp, payloads)
            done = python("score.py", "--run", out)
            self.assertEqual(done.returncode, 2, done.stdout)
            self.assertIn("F3 missing", done.stdout)

    def test_a_missed_defect_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "F1.json"
            record.write_text(json.dumps(review_payload("F1", "pass", [])), encoding="utf-8")
            done = python("score.py", "--fixture", "F1", "--record", record)
            self.assertEqual(done.returncode, 1, done.stdout)
            self.assertIn("miss", done.stdout)

    def test_a_false_important_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "F4.json"
            record.write_text(json.dumps(review_payload("F4", "fail", [important("config.py:9", "claims int() accepts unicode digits")])), encoding="utf-8")
            self.assertEqual(python("score.py", "--fixture", "F4", "--record", record).returncode, 1)

    def test_a_wrong_key_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = dict(review_payload("F1", "fail", []))
            payload["head_sha"] = "0" * 40
            record = Path(tmp) / "F1.json"
            record.write_text(json.dumps(payload), encoding="utf-8")
            done = python("score.py", "--fixture", "F1", "--record", record)
            self.assertEqual(done.returncode, 2, done.stdout)
            self.assertIn("wrong key", done.stdout)

    def test_a_schema_break_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = dict(review_payload("F1", "fail", []))
            payload["extra"] = "unexpected"
            record = Path(tmp) / "F1.json"
            record.write_text(json.dumps(payload), encoding="utf-8")
            done = python("score.py", "--fixture", "F1", "--record", record)
            self.assertEqual(done.returncode, 2, done.stdout)
            self.assertIn("schema", done.stdout)

    def test_an_oversized_record_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "big.json"
            record.write_bytes(b" " * 5000001)
            done = python("score.py", "--fixture", "F1", "--record", record)
            self.assertEqual(done.returncode, 2, done.stdout)
            self.assertIn("limit", done.stdout)

    def test_run_appends_exactly_one_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_records(tmp, PASSING)
            state = Path(tmp) / "state"
            env = dict(os.environ, XDG_STATE_HOME=str(state))
            done = run("bash", EVALS / "run.sh", "score", "--run", out, "--append-jsonl", env=env)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            rows = (state / "review-metrics" / "evals.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            row = json.loads(rows[0])
            self.assertEqual((row["eval"], row["fixtures"], row["passed"], row["score"]), ("ds-dev-protocol", 8, 8, 1.0))
            self.assertEqual((row["total"], row["false_important"]), (8, 0))
            self.assertEqual(row["misses"], [])

    def test_append_refuses_a_metrics_path_inside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_records(tmp, PASSING)
            done = python("score.py", "--run", out, "--append-jsonl", "--jsonl",
                          SKILL / "evals" / ".metrics-probe.jsonl")
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertIn("inside a git repository", done.stderr)
            self.assertFalse((SKILL / "evals" / ".metrics-probe.jsonl").exists())

    def test_partial_batch_is_refused_unless_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            payloads = dict(PASSING)
            payloads["F3"] = None
            out = write_records(tmp, payloads)
            state = Path(tmp) / "state"
            env = dict(os.environ, XDG_STATE_HOME=str(state))
            refused = run("bash", EVALS / "run.sh", "score", "--run", out, "--append-jsonl", env=env)
            self.assertEqual(refused.returncode, 2, refused.stdout)
            self.assertFalse((state / "review-metrics" / "evals.jsonl").exists())
            allowed = run("bash", EVALS / "run.sh", "score", "--run", out, "--append-jsonl",
                          "--allow-partial", env=env)
            self.assertEqual(allowed.returncode, 2, allowed.stdout)
            row = json.loads((state / "review-metrics" / "evals.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["passed"], 7)
            self.assertEqual(row["misses"][0]["id"], "F3")

    def test_row_counts_false_importants(self):
        with tempfile.TemporaryDirectory() as tmp:
            payloads = dict(PASSING)
            payloads["F4"] = review_payload("F4", "fail", [important("config.py:9", "claims int() accepts unicode digits")])
            out = write_records(tmp, payloads)
            state = Path(tmp) / "state"
            env = dict(os.environ, XDG_STATE_HOME=str(state))
            done = run("bash", EVALS / "run.sh", "score", "--run", out, "--append-jsonl", env=env)
            self.assertEqual(done.returncode, 1, done.stdout)
            row = json.loads((state / "review-metrics" / "evals.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual((row["passed"], row["total"], row["false_important"]), (7, 8, 1))


if __name__ == "__main__":
    unittest.main()
