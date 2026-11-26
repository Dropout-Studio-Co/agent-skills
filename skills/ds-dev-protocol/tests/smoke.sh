#!/usr/bin/env bash
# tests/smoke.sh - doc, static, syntax and line-limit checks; then the gate, pre-merge and implementer suites.
# Fakes only: temp HOME/PATH, local bare origin, no model call, no network. Every check runs outside the skill tree.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P); export ROOT
T=$(mktemp -d "${TMPDIR:-/tmp}/ds-smoke.XXXXXX"); T=$(cd "$T" && pwd -P)
export T HOME="$T/home"; mkdir -p "$HOME" "$T/py"
FAILED=0; trap 'rm -rf "$T"' EXIT
ok() { printf 'ok   %s\n' "$1"; }; bad() { printf 'FAIL %s\n' "$1"; FAILED=1; }
chk() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
SCRIPT=$ROOT/scripts; TESTS=$ROOT/tests
RLIB=$SCRIPT/routing_lib.py; rt() { python3 -I "$RLIB" "$@"; }
IFS=$'\t' read -r NPROV NROUTE NMODEL NOPT NDK <<< "$(rt gate-tsv plan)"; IFS=$'\t' read -r OPROV OROUTE OMODEL OOPT ODK <<< "$(rt gate-tsv review)"
IFS=$'\t' read -r IROUTE IPROV IMODEL IMODELID IEFF IPIN IDK IMAX <<< "$(rt impl-tsv)"; CE=$(rt conductor-tsv | cut -f5); CLABEL=$(rt conductor-tsv | cut -f6)
NEON_INST=(neon-a neon-b neon-c); OPUS_INST=(opus-a opus-b); NEON_ACCT=${NEON_INST[0]}; OPUS_ACCT=${OPUS_INST[0]}
export NMODEL CE CLABEL NDK ODK
# --- syntax: every shell script parses; every Python helper compiles with both interpreters, bytecode under $T ---
for f in "$SCRIPT"/*.sh "$TESTS"/*.sh; do chk "bash -n ${f#$ROOT/}" bash -n "$f"; done
if [ -x /usr/bin/python3 ]; then for f in "$SCRIPT"/*.py; do n=$(basename "$f")
  chk "py_compile $n (system /usr/bin/python3)" bash -c "rm -rf '$T/py'; mkdir -p '$T/py'; cp '$f' '$T/py/$n' && /usr/bin/python3 -I -m py_compile '$T/py/$n'"
done; fi
for f in "$SCRIPT"/*.py; do n=$(basename "$f")
  chk "py_compile $n (python3)" bash -c "rm -rf '$T/py'; mkdir -p '$T/py'; cp '$f' '$T/py/$n' && python3 -I -m py_compile '$T/py/$n'"
done
chk "python helpers are the three stdlib libraries" bash -c "ls '$SCRIPT'/gate_lib.py '$SCRIPT'/implement_lib.py '$SCRIPT'/premerge_lib.py >/dev/null"
# --- line limits: scripts/ <= 200; smoke/gate/premerge <= 375; implement-smoke <= 200 ---
chk "line limits: scripts/ <= 200" bash -c "for f in '$SCRIPT'/*; do [ ! -f \"\$f\" ] || [ \$(wc -l < \"\$f\") -le 200 ] || exit 1; done"
chk "line limits: smoke.sh <= 375" bash -c "[ \$(wc -l < '$TESTS/smoke.sh') -le 375 ]"
chk "line limits: gate-smoke.sh <= 375" bash -c "[ \$(wc -l < '$TESTS/gate-smoke.sh') -le 375 ]"
chk "line limits: premerge-smoke.sh <= 375" bash -c "[ \$(wc -l < '$TESTS/premerge-smoke.sh') -le 375 ]"
chk "line limits: implement-smoke.sh <= 200" bash -c "[ \$(wc -l < '$TESTS/implement-smoke.sh') -le 200 ]"
chk "line limits: ui-routing-smoke.sh <= 200" bash -c "[ \$(wc -l < '$TESTS/ui-routing-smoke.sh') -le 200 ]"
# --- SKILL.md size and frontmatter description ---
chk "SKILL.md <= 25600 bytes" test "$(wc -c < "$ROOT/SKILL.md")" -le 25600
chk "frontmatter description <= 450 chars" bash -c "d=\$(awk -F\"'\" '/^description:/{print \$2; exit}' '$ROOT/SKILL.md'); [ -n \"\$d\" ] && [ \${#d} -le 450 ]"
# --- forbidden tokens: no cswap, agy, Sonnet, xhigh, provisional, code-review or sandboxed in anything the conductor reads ---
TOKENS="cswap agy Sonnet xhigh provisional code-review sandboxed"; TEXTS=("$ROOT/SKILL.md" "$ROOT/reference.md" "$ROOT/plan-gate-brief.md" "$ROOT/review-gate-brief.md" "$ROOT/implementer-brief.md" "$ROOT/opencode/opencode.json" "$SCRIPT")
chk "zero forbidden tokens in docs, briefs, opencode config and scripts/" bash -c "for t in $TOKENS; do ! grep -riq -- \"\$t\" \"\${@:2}\" || exit 1; done" _ "${TEXTS[@]}"
for t in $TOKENS; do chk "token absent: $t" bash -c "! grep -riq -- '$t' \"\${@:2}\"" _ "${TEXTS[@]}"; done
chk "zero execution-protocol references in the skill" bash -c "! grep -rqE 'execution[ -]protocol' '$ROOT' --exclude-dir=tests"
# --- briefs and schemas ---
chk "plan-gate-brief.md has model-agnostic grounding" bash -c "f='$ROOT/plan-gate-brief.md'; test -s \"\$f\" && grep -qF 'Ground everything before you cite it' \"\$f\" && grep -qF 'live repository' \"\$f\" && grep -qF 'official documentation' \"\$f\" && ! grep -qF 'March 2026' \"\$f\""
chk "plan-gate-brief.md has failure-mode guardrails" bash -c "f='$ROOT/plan-gate-brief.md'; grep -qiF 'failure modes' \"\$f\" && grep -qF 'error and edge boundaries' \"\$f\" && grep -qF 'container, isolation and security invariants' \"\$f\""
chk "review-gate-brief.md covers all gates" bash -c "f='$ROOT/review-gate-brief.md'; test -s \"\$f\" && for g in review security epoch; do grep -q -- \"- \$g: \" \"\$f\" || exit 1; done && ! grep -q -- '- plan:' \"\$f\""
chk "briefs carry backend and UI checklists" bash -c "for f in '$ROOT/plan-gate-brief.md' '$ROOT/review-gate-brief.md'; do for p in 'idempotency and safe retries' 'expand/contract zero-downtime migrations' 'backward-compatible contracts' 'lock ordering and concurrency safety' 'interactive states' 'intrinsic responsive reflow' 'reduced-motion accessibility' 'design-system token and primitive reuse' 'modular file and component decomposition'; do grep -qF \"\$p\" \"\$f\" || exit 1; done; done"
chk "plan-schema.json valid" bash -c "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d[\"type\"]==\"object\" and \"gate\" in d[\"required\"] and \"rollback\" in d[\"required\"] and d[\"properties\"][\"tier\"][\"enum\"]==[\"low\",\"medium\",\"high\"]' '$ROOT/plan-schema.json'"
chk "review-schema.json valid" bash -c "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d[\"type\"]==\"object\" and set(d[\"required\"])>={\"gate\",\"head_sha\",\"verdict\",\"summary\",\"findings\"} and d[\"properties\"][\"verdict\"][\"enum\"]==[\"pass\",\"fail\"]' '$ROOT/review-schema.json'"
chk "opencode/opencode.json valid and pinned" bash -c "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d[\"model\"]==sys.argv[2] and \"implementer\" in d[\"agents\"]' '$ROOT/opencode/opencode.json' '$IPIN'"
# --- --help in bash and zsh ---
chk "help (bash)" bash -c "for s in gate.sh implement.sh premerge-and-merge.sh build-packet.sh; do bash '$SCRIPT'/\"\$s\" --help >/dev/null || exit 1; done"
if command -v zsh >/dev/null; then chk "help (zsh)" bash -c "for s in gate.sh implement.sh premerge-and-merge.sh build-packet.sh; do zsh '$SCRIPT'/\"\$s\" --help >/dev/null || exit 1; done"; fi
chk "build-packet.sh is executable and <80 lines" bash -c "[ -x '$SCRIPT/build-packet.sh' ] && [ \$(wc -l < '$SCRIPT/build-packet.sh') -lt 80 ]"
# --- documentation invariants the scripts rely on ---
chk "four-role model routing in SKILL.md" bash -c 'f=$1; for m in $2; do grep -qF "$m" "$f" || exit 1; done; for r in "Architect & Planner" Implementer "Reviewer, Security & Epoch"; do grep -qF "$r" "$f" || exit 1; done' _ "$ROOT/SKILL.md" "$NMODEL $OMODEL $IPIN"
chk "Orchestration V2 contract in SKILL.md" bash -c "f='$ROOT/SKILL.md'; for k in orchestrator_capabilities delegate_task task_cancel t3_submit_output 'T3 Orchestration V2' 'never poll'; do grep -qiF \"\$k\" \"\$f\" || exit 1; done"
chk "medium/high-only effort stated" bash -c "grep -qF 'medium' '$ROOT/SKILL.md' && grep -qF 'high' '$ROOT/SKILL.md' && grep -qF 'No other model, route or account' '$ROOT/SKILL.md' && grep -qF 'no model fallback' '$ROOT/SKILL.md'"
chk "conductor effort locked to medium always" bash -c 'f=$ROOT/SKILL.md; m=$NMODEL; e=$CE; l=$CLABEL; [ "$e" = medium ] && grep -qF "conducts (Medium always)" "$f" && grep -qE "^[|] Conductor [|].*$m.*$e.*always.*never.*high" "$f" && grep -qE "Start check \(MUST\):.*$l at .$e. in T3 Code; any other model or effort stops" "$f" && ! grep -qF "medium (routine) / high" "$f" && ! grep -qF "by tier and complexity" "$f" && ! grep -qF "Gemini 4 Neon (Med/High) conducts" "$f"'
chk "scripts wired into SKILL.md" bash -c "f='$ROOT/SKILL.md'; for s in scripts/gate.sh scripts/premerge-and-merge.sh scripts/implement.sh; do grep -qF \"\$s\" \"\$f\" || exit 1; done && grep -qF 'gate.sh epoch' \"\$f\" && grep -qF 'Rounds are counted per gate from EVID/gates.log' \"\$f\""
chk "reference.md documents T3-verified provenance" bash -c "f='$ROOT/reference.md'; test -s \"\$f\" && grep -qF 't3_thread_read' \"\$f\" && grep -qF 't3-verified' \"\$f\" && grep -qF '4-stage chronology' \"\$f\" && grep -qF 'reference.md' \"\$ROOT/SKILL.md\""
chk "all 12 workflow skills in SKILL.md" bash -c "f='$ROOT/SKILL.md'; bt=\$(printf '\\140'); for s in tdd diagnosing-bugs pr retro setup-pre-commit codebase-design writing-for-agents domain-modeling research prototype wizard grilling; do grep -qF -- \"\$s\$bt\" \"\$f\" || exit 1; done"
chk "P27 shortcuts in SKILL.md" bash -c "grep -qF 'Shortcuts' '$ROOT/SKILL.md' && grep -qF 'shortcut:' '$ROOT/SKILL.md'"
chk "routing/policy stays High" grep -qF 'routing/policy' "$ROOT/SKILL.md"
chk "dynamic ds-* skill discovery in SKILL.md" bash -c "f='$ROOT/SKILL.md'; grep -qF '~/.agents/skills/ds-*/SKILL.md' \"\$f\" && grep -qF 'disable-model-invocation: true' \"\$f\" && grep -qF 'names it explicitly' \"\$f\" && grep -qF 'newly added or updated skill is picked up automatically' \"\$f\""
chk "zero hardcoded sibling ds-* skill names in SKILL.md" bash -c "! grep -oE 'ds-[a-z0-9-]+' '$ROOT/SKILL.md' | grep -vx 'ds-dev-protocol'"
chk "UI 3-tier plan/review routing in SKILL.md" bash -c "f='$ROOT/SKILL.md'; grep -qF '3-tier chain' \"\$f\" && grep -qF 'Scope: ui' \"\$f\" && grep -qF 'Claude Opus 5.5 (Antigravity)' \"\$f\" && grep -qF 'UI review is' \"\$f\""
chk "reference.md documents the UI gates" bash -c "f='$ROOT/reference.md'; grep -qF 'ui_gates' \"\$f\" && grep -qF 'catalog-pending' \"\$f\" && grep -qF -- '--ui' \"\$f\" && grep -qF '(model, providerInstanceId)' \"\$f\" && grep -qF '25600' \"\$f\" && grep -qF 'ds-*/SKILL.md' \"\$f\""
chk "reference.md documents Trail blast" grep -qF 'trail blast --no-owners' "$ROOT/reference.md"
# --- AC36: HEAD rules SKILL.md must keep ---
chk "pre-authorized paragraph" grep -qF '**Pre-authorized (MUST).**' "$ROOT/SKILL.md"
chk "no Rahi date stamps in SKILL.md" bash -c "! grep -qE 'Rahi [0-9]{4}-[0-9]{2}-[0-9]{2}' '$ROOT/SKILL.md'"
chk "hard boundaries stated" bash -c "for p in 'new spend, purchases, paid usage or credits, subscriptions or plan upgrades' 'outbound messages under Rahi' 'exposing secrets or credentials' 'bypassing or weakening a failed gate' 'without verified recovery' 'legal agreements or acceptance records' 'changing the model routing or the conductor' 'passkey touch'; do grep -qF \"\$p\" '$ROOT/SKILL.md' || exit 1; done"
chk "no user authorization left" bash -c "! grep -qE 'only the user|user can authorize|user.s decision|ask the user|user approv' '$ROOT/SKILL.md'"
chk "delta-round rule stated" grep -qF 'Changes since the last round' "$ROOT/SKILL.md"
chk "plan risks and RED in SKILL.md" bash -c "grep -qF '## Plan risks' '$ROOT/SKILL.md' && grep -qF 'RED confirmed:' '$ROOT/SKILL.md'"
chk "brief optional + op record + size" bash -c "grep -qi optional '$ROOT/review-gate-brief.md' && grep -qF 'op-<name>.md' '$ROOT/SKILL.md' && [ \$(wc -c < '$ROOT/SKILL.md') -le 25600 ]"
chk "exit 6 documented" bash -c "bash '$ROOT/scripts/implement.sh' --help | grep -q '6 worktree processes survived' && grep -qF 'Exit 6' '$ROOT/SKILL.md' && ! grep -qF 'stops every process confined' '$ROOT/SKILL.md'"
chk "rounds and rethink stated" bash -c "grep -qF 'Rounds are counted per gate from EVID/gates.log' '$ROOT/SKILL.md' && grep -qF 'Rounds: 3 per plan' '$ROOT/SKILL.md' && grep -qF -- '- After round 3, rethink:' '$ROOT/SKILL.md'"
chk "6-lane ceiling stated" grep -qF 'At most 6 concurrent lanes' "$ROOT/SKILL.md"
chk "source-repo rule stated" grep -qF 'installed copy is never edited first' "$ROOT/SKILL.md"
chk "repo tier floor before the first plan" bash -c "grep -qF 'before the first plan' '$ROOT/SKILL.md' && grep -qF 'tier is never below it' '$ROOT/SKILL.md'"
chk "no local E2E that PR CI already runs" bash -c "grep -qF 'run locally only what PR CI does not run' '$ROOT/SKILL.md' && grep -qF 'all MUST pass before any review gate' '$ROOT/SKILL.md'"
chk "resume line lists the state files" bash -c "l=\$(grep -F 'after a restart re-read it' '$ROOT/SKILL.md'); [ -n \"\$l\" ] && for n in PROGRESS.md PLAN.md gates.log impl.log 'git log'; do printf '%s' \"\$l\" | grep -qF \"\$n\" || exit 1; done"
chk "OpenCode Anthropic OAuth ban" bash -c "grep -qF \"never configure OpenCode's Anthropic provider with subscription OAuth\" '$ROOT/SKILL.md'"
# --- script wiring and route pins ---
chk "gate.sh never runs a model itself" bash -c "! grep -qE 'claude -p|opencode run|cswap' '$SCRIPT/gate.sh' && grep -qF 'T3_ACP_MCP_NODE' '$SCRIPT/gate_lib.py' && grep -qF 'ELECTRON_RUN_AS_NODE' '$SCRIPT/gate_lib.py'"
chk "gate_lib.py defines log_metrics" grep -qF 'def log_metrics' "$SCRIPT/gate_lib.py"
chk "gate-smoke drives the real ACP node path" bash -c "grep -qF 'T3_ACP_MCP_NODE' '$TESTS/gate-smoke.sh' && grep -qF 'acp-mcp-call' '$TESTS/gate-smoke.sh'"
chk "implement.sh reads routing.json and carries no model literal" bash -c "grep -qF 'routing_lib.py' '$SCRIPT/implement.sh' && grep -qF 'impl-tsv' '$SCRIPT/implement.sh' && ! grep -qE 'claude -p|claude-sonnet|--model claude|cswap|sonnetcfg|snclass|SNM' '$SCRIPT/implement.sh' '$SCRIPT/implement_lib.py'"
chk "no home paths in the skill" bash -c "! grep -rqE '/Use[r]s/' '$ROOT' --exclude-dir=__pycache__ --exclude-dir=graft"
# --- behaviour eval set: fixtures, scripts and tests (off the gate path) ---
EVALS=$ROOT/evals
chk "evals line limits" bash -c "for pair in build_fixtures.py:180 fixture-check.sh:90 run.sh:140 score.py:200; do n=\${pair%%:*}; l=\${pair##*:}; [ \$(wc -l < '$EVALS'/\$n) -le \$l ] || exit 1; done"
chk "evals scripts executable" bash -c "[ -x '$EVALS/run.sh' ] && [ -x '$EVALS/fixture-check.sh' ] && [ -x '$EVALS/score.py' ]"
for f in "$EVALS"/*.sh; do chk "bash -n ${f#$ROOT/}" bash -n "$f"; done
if [ -x /usr/bin/python3 ]; then for f in "$EVALS"/*.py; do n=$(basename "$f")
  chk "py_compile evals/$n (system /usr/bin/python3)" bash -c "rm -rf '$T/py'; mkdir -p '$T/py'; cp '$f' '$T/py/$n' && /usr/bin/python3 -I -m py_compile '$T/py/$n'"
done; fi
for f in "$EVALS"/*.py; do n=$(basename "$f")
  chk "py_compile evals/$n (python3)" bash -c "rm -rf '$T/py'; mkdir -p '$T/py'; cp '$f' '$T/py/$n' && python3 -I -m py_compile '$T/py/$n'"
done
chk "evals help (bash)" bash -c "bash '$EVALS/run.sh' --help >/dev/null"
if command -v zsh >/dev/null; then chk "evals help (zsh)" bash -c "zsh '$EVALS/run.sh' --help >/dev/null"; fi
chk "build_fixtures --check" bash -c "cd '$EVALS' && python3 -I -B build_fixtures.py --check >/dev/null"
chk "evals inputs.sha256" bash -c "cd '$EVALS' && shasum -a 256 -c inputs.sha256 >/dev/null"
chk "tests/test_evals.py" bash -c "python3 -I -B -m unittest discover -s '$TESTS' -p 'test_evals.py' >/dev/null 2>&1"
if [ -x /usr/bin/python3 ]; then chk "tests/test_evals.py (system /usr/bin/python3)" bash -c "/usr/bin/python3 -I -B -m unittest discover -s '$TESTS' -p 'test_evals.py' >/dev/null 2>&1"; fi
chk "evals/fixture-check.sh" bash "$EVALS/fixture-check.sh"
chk "zero __pycache__ before the suites" bash -c "[ -z \"\$(find '$ROOT' -name __pycache__ -print -quit)\" ]"
# --- routing source of truth: static contract, guard, sync, validation, alt-routing and commit hook ---
RLIB=$SCRIPT/routing_lib.py
HOOK=$ROOT/../../.githooks/pre-commit
chk "routing.json exists" test -s "$ROOT/routing.json"
chk "routing_lib.py is not executable" bash -c "[ ! -x '$RLIB' ]"
chk "routing_lib.py check (python3)" python3 -I "$RLIB" check
if [ -x /usr/bin/python3 ]; then chk "routing_lib.py check (system /usr/bin/python3)" /usr/bin/python3 -I "$RLIB" check; fi
chk "routing.json contract" bash -c "python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); r=d[\"routes\"]; assert d[\"schema_version\"]==1 and d[\"allowed_efforts\"]==[\"medium\",\"high\"] and set(r)=={\"neon\",\"opus\",\"opus_antigravity\",\"deepseek\"} and r[\"opus_antigravity\"][\"model\"] is None and r[\"opus_antigravity\"][\"option_key\"] is None and not any(\"accounts\" in v for v in r.values()) and {k: v[\"driver_kind\"] for k,v in r.items()}=={\"neon\":\"\u0061ntigravity\",\"opus\":\"claude\u0041gent\",\"opus_antigravity\":\"\u0061ntigravity\",\"deepseek\":\"opencode\"} and r[\"deepseek\"][\"max_cost_usd\"]==0 and set(d[\"gates\"])=={\"plan\",\"review\",\"security\",\"epoch\"} and d[\"gates\"][\"review\"][\"efforts\"][\"medium\"]==\"medium\" and d[\"gates\"][\"review\"][\"trigger_effort\"]==\"high\" and d[\"conductor\"]=={\"route\":\"neon\",\"effort\":\"medium\"} and d[\"implementer\"]=={\"route\":\"deepseek\",\"effort\":\"high\"} and set(d[\"ui_gates\"])=={\"plan\",\"review\"} and [s[\"route\"] for s in d[\"ui_gates\"][\"plan\"]]==[\"opus\",\"opus_antigravity\",\"neon\"] and [s[\"route\"] for s in d[\"ui_gates\"][\"review\"]]==[\"opus\",\"opus_antigravity\",\"neon\"]' '$ROOT/routing.json'"
chk "routing_lib derives roles" bash -c "cd '$SCRIPT' && python3 -I -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import routing_lib as r; c=r.load(); i=r.implementer(c); d=r.conductor(c); g=r.gate_contract(c,\"plan\"); assert i[\"pinned\"]==i[\"model\"]+\"#\"+i[\"effort\"] and i[\"driver_kind\"]==c[\"routes\"][i[\"route\"]][\"driver_kind\"] and d[\"effort\"]==\"medium\" and g[1:3]==(c[\"gates\"][\"plan\"][\"route\"], c[\"routes\"][c[\"gates\"][\"plan\"][\"route\"]][\"model\"]) and g[4]==c[\"routes\"][c[\"gates\"][\"plan\"][\"route\"]][\"driver_kind\"] and r.option_keys(c) and r.allowed_efforts_for(c,\"review\",\"medium\")=={\"medium\",\"high\"} and r.allowed_efforts_for(c,\"review\",\"low\")=={\"medium\"} and r.effort_for(c,\"review\",\"low\",True)==\"medium\"' '$SCRIPT'"
cat > "$T/guard.py" <<'PY'
import json, os, re, sys
root = sys.argv[1]
cfg = json.load(open(os.path.join(root, "routing.json")))
tokens = set()
for route in cfg["routes"].values():
    tokens.add(route["provider"]); tokens.add(route["driver_kind"])
    if route.get("model"): tokens.add(route["model"])
    if "model_id" in route: tokens.add(route["model_id"]); tokens.add(route["provider"] + "/" + route["model_id"])
tokens.discard("opencode")
pat = re.compile(r"(?<![A-Za-z0-9_-])(?:%s)(?![A-Za-z0-9_-])" % "|".join(sorted(map(re.escape, tokens))))
paths = [os.path.join(root, n) for n in ("reference.md", "review-gate-brief.md", "implementer-brief.md", "evals/answer-key.md")]
for base in (os.path.join(root, "scripts"), os.path.join(root, "tests")):
    paths += [os.path.join(d, f) for d, _, fs in os.walk(base) for f in fs]
bad = [os.path.relpath(p, root) for p in paths if pat.search(open(p, errors="replace").read())]
skill = open(os.path.join(root, "SKILL.md"), errors="replace").read()
skill = re.sub(r"<!-- routing:start -->.*?<!-- routing:end -->", "", skill, flags=re.S)
skill = re.sub(r"(?m)^description: '.*'$", "", skill)
if pat.search(skill): bad.append("SKILL.md outside the synced block and description")
print("hardcoded: " + ", ".join(bad) if bad else "")
raise SystemExit(1 if bad else 0)
PY
chk "zero hardcoded active models, providers or accounts" python3 -I "$T/guard.py" "$ROOT"
chk "pre-commit hook is executable and parses" bash -c "bash -n '$HOOK' && [ -x '$HOOK' ]"
rt2() { python3 -I "$T/skill/scripts/routing_lib.py" "$@"; }
mutate() { rm -rf "$T/skill"; cp -R "$ROOT" "$T/skill"; python3 -I "$T/mutate.py" "$T/skill" "$1"; }
cat > "$T/mutate.py" <<'PY'
import json, os, sys
skill, case = sys.argv[1], sys.argv[2]
rp = os.path.join(skill, "routing.json"); sp = os.path.join(skill, "SKILL.md"); op = os.path.join(skill, "opencode/opencode.json")
def save(d): open(rp, "w").write(json.dumps(d, indent=1) + "\n")
d = json.load(open(rp))
if case == "missing": os.remove(rp)
elif case == "corrupt": open(rp, "w").write("{")
elif case == "schema": d["schema_version"] = 2; save(d)
elif case == "low": d["allowed_efforts"] = ["low"]; save(d)
elif case == "max": d["allowed_efforts"] = ["max"]; save(d)
elif case == "tab-model": d["routes"]["neon"]["model"] = "bad\tmodel"; save(d)
elif case == "hash-model": d["routes"]["neon"]["model"] = "bad#model"; save(d)
elif case == "legacy-accounts": d["routes"]["opus"]["accounts"] = ["legacy"]; save(d)
elif case == "bad-driver": d["routes"]["neon"]["driver_kind"] = "bad\tdriver"; save(d)
elif case == "empty-driver": del d["routes"]["deepseek"]["driver_kind"]; save(d)
elif case == "cost": d["routes"]["deepseek"]["max_cost_usd"] = -1; save(d)
elif case == "symlink":
    open(os.path.join(skill, "alt-routing.json"), "w").write(json.dumps(d, indent=1) + "\n"); os.remove(rp)
    os.symlink(os.path.join(skill, "alt-routing.json"), rp)
elif case == "no-marker":
    t = open(sp).read(); open(sp, "w").write(t.replace("<!-- routing:end -->", ""))
elif case == "dup-marker": open(sp, "a").write("<!-- routing:start -->\n")
elif case == "desc": d["routes"]["neon"]["label"] = "X" * 460; save(d)
elif case == "huge": open(sp, "a").write("x" * 2000)
elif case == "oc": open(op, "w").write("{}\n")
elif case == "conductor-option":
    d["routes"]["solo"] = {"label": "Solo Conductor", "provider": "solo-conductor", "model": "solo-model", "driver_kind": "solo-driver"}
    d["conductor"] = {"route": "solo", "effort": "medium"}; save(d)
elif case == "allowed-unhashable": d["allowed_efforts"] = [{}]; save(d)
elif case == "nan-cost": d["routes"][d["implementer"]["route"]]["max_cost_usd"] = float("nan"); save(d)
elif case == "pending-model": d["routes"]["opus_antigravity"]["model"] = "half-model"; save(d)
elif case == "pending-option": d["routes"]["opus_antigravity"]["option_key"] = "effort"; save(d)
elif case == "pending-conductor": d["conductor"] = {"route": "opus_antigravity", "effort": "medium"}; save(d)
elif case == "pending-gate": d["gates"]["plan"]["route"] = "opus_antigravity"; save(d)
elif case == "ui-primary": d["ui_gates"]["plan"][0], d["ui_gates"]["plan"][1] = d["ui_gates"]["plan"][1], d["ui_gates"]["plan"][0]; save(d)
elif case == "ui-missing": del d["ui_gates"]["review"]; save(d)
elif case == "ui-extra": d["ui_gates"]["security"] = []; save(d)
elif case == "ui-empty": d["ui_gates"]["plan"] = []; save(d)
elif case == "ui-dup": d["ui_gates"]["plan"][1]["route"] = "opus"; save(d)
elif case == "ui-model-id": d["ui_gates"]["plan"][1]["route"] = "deepseek"; save(d)
elif case == "ui-effort": d["ui_gates"]["plan"][0]["efforts"]["low"] = "max"; save(d)
PY
invalid_case() { local a b rc1 rc2; mutate "$1"
  a=$(shasum -a 256 "$T/skill/SKILL.md" "$T/skill/opencode/opencode.json" | shasum -a 256 | awk '{print $1}')
  rt2 check >/dev/null 2>"$T/err"; rc1=$?; rt2 sync >/dev/null 2>>"$T/err"; rc2=$?
  b=$(shasum -a 256 "$T/skill/SKILL.md" "$T/skill/opencode/opencode.json" | shasum -a 256 | awk '{print $1}')
  if [ "$rc1" = 2 ] && [ "$rc2" = 2 ] && [ "$a" = "$b" ] && ! grep -q Traceback "$T/err"; then ok "routing invalid: $1"; else bad "routing invalid: $1 (rc $rc1/$rc2, unchanged $([ "$a" = "$b" ] && echo yes || echo no), traceback $(grep -q Traceback "$T/err" && echo yes || echo no))"; fi; }
for c in missing corrupt schema low max tab-model hash-model legacy-accounts bad-driver empty-driver cost symlink no-marker dup-marker desc huge oc conductor-option allowed-unhashable nan-cost pending-model pending-option pending-conductor pending-gate ui-primary ui-missing ui-extra ui-empty ui-dup ui-model-id ui-effort; do invalid_case "$c"; done
mutate none; python3 -I - "$T/skill" <<'PY'
import json, os, sys
s = sys.argv[1]
p = os.path.join(s, "opencode/opencode.json"); d = json.load(open(p)); d["model"] = "drifted/model#low"; open(p, "w").write(json.dumps(d, indent=1) + "\n")
k = os.path.join(s, "SKILL.md"); t = open(k).read(); open(k, "w").write(t.replace("Four roles, one model each", "Drifted roles"))
PY
rt2 check >/dev/null 2>&1; drc=$?
rt2 sync >/dev/null 2>&1; src=$?
rt2 check >/dev/null 2>&1; crc=$?
s1=$(shasum -a 256 "$T/skill/SKILL.md" "$T/skill/opencode/opencode.json"); rt2 sync >/dev/null 2>&1
s2=$(shasum -a 256 "$T/skill/SKILL.md" "$T/skill/opencode/opencode.json"); SPIN=$(rt2 impl-tsv | cut -f6)
chk "routing sync repairs drift and is idempotent" bash -c "[ '$drc' = 1 ] && [ '$src' = 0 ] && [ '$crc' = 0 ] && [ '$s1' = '$s2' ] && python3 -I '$T/skill/scripts/routing_lib.py' opencode-config | grep -qF '\"model\": \"$SPIN\"'"
# --- alt routing: only routing.json changes, sync, then every runtime accepts the new route and rejects the old one ---
rm -rf "$T/skill"; cp -R "$ROOT" "$T/skill"
IFS=$'\t' read -r ONP ONR ONM ONO ONDK <<< "$(python3 -I "$ROOT/scripts/routing_lib.py" gate-tsv plan)"
IFS=$'\t' read -r OPP OPR OPM OPO OPDK <<< "$(python3 -I "$ROOT/scripts/routing_lib.py" gate-tsv review)"
IFS=$'\t' read -r OIR OIP OIM OID OIE OIPIN OIA OIC <<< "$(python3 -I "$ROOT/scripts/routing_lib.py" impl-tsv)"
ONAC=old-plan-a; OPAC=old-review-a
python3 -I - "$T/skill/routing.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["routes"]["neon"].update(label="Alt Planner", provider="alt-provider", model="alt-plan-1", driver_kind="alt-plan-driver")
d["routes"]["opus"].update(label="Alt Reviewer", provider="alt-reviewer", model="alt-review-1", driver_kind="alt-review-driver")
d["routes"]["deepseek"].update(label="Alt Implementer", provider="alt-impl", model_id="alt-code-1", driver_kind="alt-code-driver")
for g in ("review", "security", "epoch"): d["gates"][g]["route"] = "opus"
open(p, "w").write(json.dumps(d, indent=1) + "\n")
PY
rt2 sync || bad "alt routing sync"
caps() { python3 - "$@" <<'PY'
import json, sys
out = []
for spec in sys.argv[1:]:
    model, dk, inst = spec.split("|")
    out.append({"providerInstanceId": inst, "driverKind": dk, "canRunChildTask": True, "models": [{"id": model}]})
print(json.dumps({"providers": out}))
PY
}
APDK=$(rt2 gate-tsv plan | cut -f5); ARDK=$(rt2 gate-tsv review | cut -f5)
export CAPS=$(caps "alt-plan-1|$APDK|alt-plan-a" "alt-plan-1|$APDK|alt-plan-b" "alt-review-1|$ARDK|alt-review-a")
chk "alt routing derived files follow routing.json" bash -c "python3 -I '$T/skill/scripts/routing_lib.py' check && python3 -I '$T/skill/scripts/routing_lib.py' opencode-config | grep -qF '\"model\": \"alt-impl/alt-code-1#high\"' && grep -qF 'alt-plan-1' '$T/skill/SKILL.md' && grep -qF 'alt-review-1' '$T/skill/SKILL.md'"
cat > "$T/acp" <<'PY'
#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a and a[0] == "acp-mcp-call": a = a[1:]
tool = a[0] if a else ""; req = json.loads(a[1]) if len(a) > 1 else {}
open(os.environ["T"] + "/t3.calls", "a").write(tool + "\n")
rec = json.load(open(os.environ["REC"]))
if tool == "orchestrator_capabilities":
    print(json.dumps({"structuredContent": json.loads(os.environ["CAPS"])}))
elif tool == "t3_thread_configure":
    print(json.dumps({"structuredContent": {"modelSelection": {"instanceId": os.environ["INST"], "model": os.environ["MODEL"], "options": [{"id": os.environ["OPTION"], "value": os.environ["EFF"]}]}}}))
elif tool == "t3_thread_read":
    th = {"threadId": req.get("threadId", ""), "status": "completed", "latestRunId": "r", "parentThreadId": "parent-1", "providerInstanceId": os.environ["INST"], "model": os.environ["MODEL"]}
    print(json.dumps({"structuredContent": {"thread": th, "recentRuns": [{"runId": "r", "status": "completed", "providerInstanceId": os.environ["INST"], "model": os.environ["MODEL"]}], "items": [{"type": "assistant_message", "itemId": "i", "text": json.dumps(rec)}]}}))
else: print(json.dumps({"structuredContent": {}}))
PY
chmod +x "$T/acp"
GR=$T/gr; git init -q -b main "$GR"; printf 'a\n' > "$GR/f.txt"; git -C "$GR" add f.txt; git -C "$GR" -c user.name=t -c user.email=t@e commit -qm base
git init -q --bare "$T/gorigin.git"; git -C "$GR" remote add origin "$T/gorigin.git"; git -C "$GR" push -q origin main; git -C "$GR" remote set-head origin main
printf 'b\n' >> "$GR/f.txt"; git -C "$GR" -c user.name=t -c user.email=t@e commit -qam feat; GH=$(git -C "$GR" rev-parse HEAD)
GE=$T/gev; mkdir -p "$GE"; printf 'facts\n' > "$GE/facts.md"; GK=$(shasum -a 256 "$GE/facts.md" | awk '{print $1}')
( cd "$GR" && EVID="$GE" bash "$T/skill/scripts/build-packet.sh" plan medium )
printf '{"gate":"plan","tier":"medium","acceptance_criteria":["a"],"design":"d","files":["f.txt"],"tests":["t"],"risks":[],"rollback":"r"}\n' > "$GE/rec.json"
gaterc() { ( cd "$GR" && EVID="$GE" REC="$GE/rec.json" INST="$1" MODEL="$2" OPTION="$3" EFF="$4" T3_ACP_MCP_NODE="$T/acp" T3_ACP_MCP_ENTRYPOINT="" bash "$T/skill/scripts/gate.sh" plan medium --record "$GE/rec.json" --child-thread "$5" --parent-thread parent-1 ) > "$T/gout" 2>&1; }
gaterc alt-plan-a alt-plan-1 "$(rt2 gate-tsv plan | cut -f4)" "$(rt2 effort plan medium)" alt-c1; gr1=$?
gaterc "$ONAC" "$ONM" "$ONO" "$(python3 -I "$ROOT/scripts/routing_lib.py" effort plan medium)" old-c1; gr2=$?
chk "gate.sh accepts the synced alt route and rejects the old one" bash -c "[ $gr1 = 0 ] && [ $gr2 = 2 ] && test -s '$GE/plan-$GK.json'"
RB=$(git -C "$GR" merge-base origin/main "$GH"); printf 'review notes\n' > "$GR/REVIEW.md"; git -C "$GR" add REVIEW.md; git -C "$GR" -c user.name=t -c user.email=t@e commit -qm review; GH=$(git -C "$GR" rev-parse HEAD)
mkdir -p "$T/trailbin"; printf '#!/bin/sh\nprintf "blast %s\\n" "$*"\n' > "$T/trailbin/trail"; chmod +x "$T/trailbin/trail"
( cd "$GR" && PATH="$T/trailbin:$PATH" EVID="$GE" bash "$T/skill/scripts/build-packet.sh" review medium --base origin/main )
chk "build-packet writes headers, REVIEW.md and Trail blast" bash -c "grep -q '^Gate: review' '$GE/packet-review.md' && grep -q '^key: $GH' '$GE/packet-review.md' && grep -q '^base_ref: origin/main' '$GE/packet-review.md' && grep -q '## REVIEW.md' '$GE/packet-review.md' && grep -q '## Trail blast' '$GE/packet-review.md'"
chk "build-packet rejects invalid combinations, assembles --diff and --ui" bash -c "! EVID='$GE' bash '$T/skill/scripts/build-packet.sh' security low >/dev/null 2>&1 && ! EVID='$GE' bash '$T/skill/scripts/build-packet.sh' security high --ui >/dev/null 2>&1 && ! EVID='$GE' bash '$T/skill/scripts/build-packet.sh' plan low --diff '$GE/facts.md' >/dev/null 2>&1 && ! EVID='$GE' bash '$T/skill/scripts/build-packet.sh' plan low --base refs/heads/main >/dev/null 2>&1 && mkdir -p '$GE/bpd' && cp '$GE/facts.md' '$GE/bpd/facts.md' && printf 'd\\n' > '$T/bp.diff' && EVID='$GE/bpd' bash '$T/skill/scripts/build-packet.sh' review low --diff '$T/bp.diff' && grep -q '^key: ' '$GE/bpd/packet-review.md' && EVID='$GE/bpd' bash '$T/skill/scripts/build-packet.sh' plan low --ui && grep -q '^Scope: ui' '$GE/bpd/packet-plan.md'"
printf '{"gate":"review","head_sha":"%s","verdict":"pass","summary":"ok","findings":[]}\n' "$GH" > "$GE/rec-review.json"
gatev() { ( cd "$GR" && EVID="$GE" REC="$GE/rec-review.json" INST="$1" MODEL="$2" OPTION="$3" EFF="$4" T3_ACP_MCP_NODE="$T/acp" T3_ACP_MCP_ENTRYPOINT="" bash "$T/skill/scripts/gate.sh" review medium --record "$GE/rec-review.json" --child-thread "$5" --parent-thread parent-1 ) > "$T/rout" 2>&1; }
gatev alt-review-a alt-review-1 effort "$(rt2 effort review medium)" alt-r1; rr1=$?
gatev "$OPAC" "$OPM" "$OPO" "$(python3 -I "$ROOT/scripts/routing_lib.py" effort review medium)" old-r1; rr2=$?
chk "gate.sh review accepts the alt route and rejects the old one" bash -c "[ $rr1 = 0 ] && [ $rr2 = 2 ] && test -s '$GE/review-$GH.json'"
gatev alt-review-a alt-review-1 effort "$(rt2 effort review medium)" alt-r2; rr_r2=$?
gatev alt-review-a alt-review-1 effort "$(rt2 effort review medium)" alt-r3m; rr_r3m=$?
gatev alt-review-a alt-review-1 effort "$(rt2 effort review medium 1)" alt-r3h; rr_r3h=$?
chk "gate.sh review medium round 3 auto-enforces high without --trigger" bash -c "[ $rr_r2 = 0 ] && [ $rr_r3m = 2 ] && [ $rr_r3h = 0 ]"
cp "$T/skill/routing.json" "$T/routing.keep"; printf '{' > "$T/skill/routing.json"; : > "$T/t3.calls"
gatev alt-review-a alt-review-1 effort "$(rt2 effort review medium)" bad-r1; rr3=$?
chk "gate.sh fails closed on invalid routing.json" bash -c "[ $rr3 = 2 ] && [ ! -s '$T/t3.calls' ]"; cp "$T/routing.keep" "$T/skill/routing.json"
# implement.sh end-to-end with a fake opencode
IR=$T/irepo; git init -q "$IR"; mkdir -p "$IR/src"; printf 'a\n' > "$IR/src/a.txt"; git -C "$IR" add -A; git -C "$IR" -c user.name=t -c user.email=t@e commit -qm base
IW=$T/iwt; git -C "$IR" worktree add -q --detach "$IW"; IE=$T/iev; mkdir -p "$IE"
alt_route=$(rt2 impl-tsv | cut -f1); alt_model=$(rt2 impl-tsv | cut -f3); alt_pin=$(rt2 impl-tsv | cut -f6)
alt_plan_route=$(rt2 gate-tsv plan | cut -f2); alt_plan_model=$(rt2 gate-tsv plan | cut -f3); alt_plan_acct=alt-plan-a
plan_row() { python3 - "$IE" "$1" "$2" "$3" "$4" "$5" <<'PY'
import hashlib, json, os, sys
ev, route, model, account, effort, provider = sys.argv[1:7]
target = os.path.join(ev, "plan-alt.json")
open(target, "w").write(json.dumps({"structured_output": {"gate": "plan", "tier": "medium", "acceptance_criteria": ["a"], "design": "d", "files": ["src/a.txt"], "tests": ["t"], "risks": [], "rollback": "r"}}, indent=1) + "\n")
row = {"gate": "plan", "status": "ok", "route": route, "model": model, "effort": effort, "account": account, "provenance_mode": "t3-verified", "engine": "t3-delegate", "file": "plan-alt.json", "file_sha256": hashlib.sha256(open(target, "rb").read()).hexdigest(), "key": "k", "session_id": "c", "parent_thread_id": "p", "provider": provider}
open(os.path.join(ev, "gates.log"), "w").write(json.dumps(row) + "\n")
PY
}
plan_row "$alt_plan_route" "$alt_plan_model" "$alt_plan_acct" "$(rt2 effort plan medium)" alt-provider
mkdir -p "$T/ocbin" "$T/calls"; : > "$T/calls/calls.log"; : > "$T/calls/config.log"
printf '#!/bin/bash\nprintf "%%s\\n" "$*" >> "$CALLS/calls.log"\nprintf "%%s\\n" "$OPENCODE_CONFIG_CONTENT" >> "$CALLS/config.log"\nexit 1\n' > "$T/ocbin/opencode"; chmod +x "$T/ocbin/opencode"
imprun() { ( cd "$IW" && PATH="$T/ocbin:$PATH" CALLS="$T/calls" EVID="$IE" bash "$T/skill/scripts/implement.sh" medium --bootstrap none ) > "$T/iout" 2>&1; IRC=$?; }
imprun; ir1=$IRC
chk "implement.sh injects the alt pinned model at runtime" bash -c "[ $ir1 = 3 ] && grep -qF -- '--model $alt_pin' '$T/calls/calls.log' && grep -qF '\"model\": \"$alt_pin\"' '$T/calls/config.log' && ! grep -qF -- '--model $OIPIN' '$T/calls/calls.log'"
: > "$T/calls/calls.log"; plan_row "$ONR" "$ONM" "$ONAC" "$(python3 -I "$ROOT/scripts/routing_lib.py" effort plan medium)" "$ONP"; imprun; ir2=$IRC
chk "implement.sh rejects a plan row on the old route" bash -c "[ $ir2 = 2 ] && [ ! -s '$T/calls/calls.log' ]"
cp "$T/skill/routing.json" "$T/routing.keep"; printf '{' > "$T/skill/routing.json"; imprun; ir3=$IRC
chk "implement.sh fails closed on invalid routing.json" bash -c "[ $ir3 = 2 ] && [ ! -s '$T/calls/calls.log' ]"; cp "$T/routing.keep" "$T/skill/routing.json"
# implement_lib.py dsclass reads the implementer cost cap from routing.json in its own skill copy.
DSK=$T/dsskill; rm -rf "$DSK"; cp -R "$ROOT" "$DSK"
python3 -I - "$DSK/routing.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["routes"][d["implementer"]["route"]]["max_cost_usd"] = 5; open(p, "w").write(json.dumps(d, indent=1) + "\n")
PY
dsexp() { python3 -I - "$1" "$2" "$3" "$IPROV" "$IMODELID" "$IEFF" <<'PY'
import json, sys
out, sid, cost, prov, model, effort = sys.argv[1:7]
json.dump({"info": {"id": sid, "tokens": {"input": 10, "output": 5}, "cost": float(cost)}, "messages": [{"type": "assistant", "model": {"providerID": prov, "id": model, "variant": effort}}]}, open(out, "w"))
PY
}
dsclass() { python3 -I "$DSK/scripts/implement_lib.py" dsclass "$1" "$T/ds.events" s1; }
: > "$T/ds.events"; dsexp "$T/ds-ok.json" s1 3; DSOK=$(dsclass "$T/ds-ok.json" | cut -f1)
dsexp "$T/ds-high.json" s1 6; DSHIGH=$(dsclass "$T/ds-high.json" | cut -f2)
dsexp "$T/ds-neg.json" s1 -1; DSNEG=$(dsclass "$T/ds-neg.json" | cut -f1)
chk "implement_lib dsclass honors max_cost_usd and rejects negative cost" bash -c "[ '$DSOK' = ok ] && [ '$DSHIGH' = 'cost: 6.0' ] && [ '$DSNEG' = unavailable ]"
# premerge-and-merge.sh --diff end-to-end
printf 'outside diff\n' > "$T/pdiff"; PK=$(shasum -a 256 "$T/pdiff" | awk '{print $1}')
pev() { local d=$1 pr=$2 pm=$3 pa=$4 pe=$5 rr=$6 rm=$7 ra=$8 re=$9; rm -rf "$d"; mkdir -p "$d"; printf 'facts\n' > "$d/facts.md"
  local fs=$(shasum -a 256 "$d/facts.md" | awk '{print $1}'); printf 'Tier: medium\n' > "$d/PLAN.md"; printf 'Tier: medium\n' > "$d/tier-recheck-$PK.md"
  printf '{"structured_output": {"gate": "plan", "tier": "medium", "acceptance_criteria": ["a"], "design": "d", "files": ["f"], "tests": ["t"], "risks": [], "rollback": "r"}}\n' > "$d/plan-$fs.json"
  printf '{"structured_output": {"gate": "review", "head_sha": "%s", "verdict": "pass", "summary": "ok", "findings": []}}\n' "$PK" > "$d/review-$PK.json"
  python3 - "$d" "$fs" "$PK" "$pr" "$pm" "$pa" "$pe" "$rr" "$rm" "$ra" "$re" <<'PY'
import hashlib, json, os, sys
ev, fs, key, pr, pm, pa, pe, rr, rm, ra, re = sys.argv[1:12]
def sha(n): return hashlib.sha256(open(os.path.join(ev, n), "rb").read()).hexdigest()
rows = [
 {"gate": "plan", "status": "ok", "route": pr, "model": pm, "effort": pe, "account": pa, "provenance_mode": "t3-verified", "engine": "t3-delegate", "file": "plan-%s.json" % fs, "file_sha256": sha("plan-%s.json" % fs), "key": fs, "facts_sha256": fs, "session_id": "c1", "parent_thread_id": "p", "ts": "2026-11-05T00:00:00Z", "tier": "medium"},
 {"gate": "review", "status": "ok", "verdict": "pass", "route": rr, "model": rm, "effort": re, "account": ra, "provenance_mode": "t3-verified", "engine": "t3-delegate", "file": "review-%s.json" % key, "file_sha256": sha("review-%s.json" % key), "key": key, "head_sha": key, "session_id": "c2", "parent_thread_id": "p", "ts": "2026-11-10T00:00:00Z", "tier": "medium"},
]
open(os.path.join(ev, "gates.log"), "w").write("".join(json.dumps(r) + "\n" for r in rows))
PY
}
prun() { ( cd "$T" && EVID="$1" bash "$T/skill/scripts/premerge-and-merge.sh" --diff "$T/pdiff" ) > "$T/pout" 2>&1; PRC=$?; }
pev "$T/pev-alt" "$(rt2 gate-tsv plan | cut -f2)" "$(rt2 gate-tsv plan | cut -f3)" "${alt_plan_acct}" "$(rt2 effort plan medium)" "$(rt2 gate-tsv review | cut -f2)" "$(rt2 gate-tsv review | cut -f3)" alt-review-a "$(rt2 effort review medium)"
prun "$T/pev-alt"; pr1=$PRC
pev "$T/pev-old" "$ONR" "$ONM" "$ONAC" "$(python3 -I "$ROOT/scripts/routing_lib.py" effort plan medium)" "$OPR" "$OPM" "$OPAC" "$(python3 -I "$ROOT/scripts/routing_lib.py" effort review medium)"
prun "$T/pev-old"; pr2=$PRC
chk "premerge accepts the alt routes and rejects the old ones" bash -c "[ $pr1 = 0 ] && [ $pr2 = 1 ] && grep -q 'FAIL .*provenance' '$T/pout'"
cp "$T/skill/routing.json" "$T/routing.keep"; printf '{' > "$T/skill/routing.json"; prun "$T/pev-alt"; pr3=$PRC
chk "premerge fails closed on invalid routing.json" bash -c "[ $pr3 = 1 ] && grep -q 'invalid routing.json' '$T/pout'"; cp "$T/routing.keep" "$T/skill/routing.json"
# --- .githooks/pre-commit in isolated temp repos ---
hookrepo() { local d=$1; rm -rf "$d"; mkdir -p "$d/skills" "$d/.githooks"; cp -R "$ROOT" "$d/skills/ds-dev-protocol"; cp "$HOOK" "$d/.githooks/pre-commit"
  git init -q "$d"; git -C "$d" config user.name t; git -C "$d" config user.email t@e; git -C "$d" config core.hooksPath .githooks
  git -C "$d" add -A; git -C "$d" commit -qm base >/dev/null 2>&1; }
hrun() { ( cd "$1" && bash .githooks/pre-commit ) >/dev/null 2>&1; HRC=$?; }
D=$T/hook1; hookrepo "$D"; printf 'unrelated\n' > "$D/notes.txt"; git -C "$D" add notes.txt; hrun "$D"
chk "pre-commit passes an unrelated commit" test "$HRC" = 0
D=$T/hook2; hookrepo "$D"; python3 -I - "$D" <<'PY'
import json, sys
p = sys.argv[1] + "/skills/ds-dev-protocol/routing.json"; d = json.load(open(p)); d["routes"]["neon"]["label"] = "Hook Planner"; d["routes"]["deepseek"]["model_id"] = "hook-code-1"; open(p, "w").write(json.dumps(d, indent=1) + "\n")
PY
git -C "$D" add skills/ds-dev-protocol/routing.json; hrun "$D"
chk "pre-commit auto-syncs and stages the derived files" bash -c "[ '$HRC' = 0 ] && git -C '$D' diff --cached --name-only | grep -qx skills/ds-dev-protocol/opencode/opencode.json && git -C '$D' diff --cached --name-only | grep -qx skills/ds-dev-protocol/SKILL.md"
D=$T/hook3; hookrepo "$D"; printf '{"model": "hand/edit#low"}\n' > "$D/skills/ds-dev-protocol/opencode/opencode.json"; git -C "$D" add skills/ds-dev-protocol/opencode/opencode.json; hrun "$D"
chk "pre-commit refuses hand-edited derived files" test "$HRC" = 1
D=$T/hook4; hookrepo "$D"; printf '{' > "$D/skills/ds-dev-protocol/routing.json"; git -C "$D" add skills/ds-dev-protocol/routing.json
A=$(shasum -a 256 "$D/skills/ds-dev-protocol/opencode/opencode.json" "$D/skills/ds-dev-protocol/SKILL.md"); hrun "$D"
B=$(shasum -a 256 "$D/skills/ds-dev-protocol/opencode/opencode.json" "$D/skills/ds-dev-protocol/SKILL.md")
chk "pre-commit refuses invalid routing.json without touching files" bash -c "[ '$HRC' = 1 ] && [ '$A' = '$B' ]"
D=$T/hook5; hookrepo "$D"; python3 -I - "$D" <<'PY'
import json, sys
p = sys.argv[1] + "/skills/ds-dev-protocol/routing.json"; d = json.load(open(p)); d["routes"]["opus"]["label"] = "Staged Reviewer"; open(p, "w").write(json.dumps(d, indent=1) + "\n")
PY
git -C "$D" add skills/ds-dev-protocol/routing.json; printf 'unstaged\n' >> "$D/skills/ds-dev-protocol/SKILL.md"; hrun "$D"
chk "pre-commit refuses unstaged edits in a watched file" test "$HRC" = 1
# --- split suites ---
printf '\n'; for s in gate-smoke.sh premerge-smoke.sh implement-smoke.sh ui-routing-smoke.sh; do
  if bash "$TESTS/$s"; then ok "$s passed"; else bad "$s failed"; fi
done
chk "zero __pycache__ after the suites" bash -c "[ -z \"\$(find '$ROOT' -name __pycache__ -print -quit)\" ]"
printf '\n%s\n' "$([ $FAILED = 0 ] && echo 'ALL TESTS PASSED!' || echo 'TESTS FAILED!')"
exit $FAILED
