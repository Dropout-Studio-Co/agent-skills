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
DOCS=("$ROOT/SKILL.md" "$ROOT/reference.md" "$ROOT/plan-gate-brief.md" "$ROOT/implementer-brief.md" "$ROOT/opencode/opencode.json")
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
# --- SKILL.md size and frontmatter description ---
chk "SKILL.md <= 25600 bytes" test "$(wc -c < "$ROOT/SKILL.md")" -le 25600
chk "frontmatter description <= 450 chars" bash -c "d=\$(awk -F\"'\" '/^description:/{print \$2; exit}' '$ROOT/SKILL.md'); [ -n \"\$d\" ] && [ \${#d} -le 450 ]"
# --- forbidden tokens: no cswap, agy, Sonnet, xhigh, provisional, code-review or sandboxed in anything the conductor reads ---
TOKENS="cswap agy Sonnet xhigh provisional code-review sandboxed"
chk "zero forbidden tokens in docs, briefs, opencode config and scripts/" bash -c "for t in $TOKENS; do ! grep -riq -- \"\$t\" '$ROOT/SKILL.md' '$ROOT/reference.md' '$ROOT/plan-gate-brief.md' '$ROOT/implementer-brief.md' '$ROOT/opencode/opencode.json' '$SCRIPT' || exit 1; done"
for t in $TOKENS; do chk "token absent: $t" bash -c "! grep -riq -- '$t' '$ROOT/SKILL.md' '$ROOT/reference.md' '$ROOT/plan-gate-brief.md' '$ROOT/implementer-brief.md' '$ROOT/opencode/opencode.json' '$SCRIPT'"; done
chk "zero execution-protocol references in the skill" bash -c "! grep -rqE 'execution[ -]protocol' '$ROOT' --exclude-dir=tests"
# --- briefs and schemas ---
chk "plan-gate-brief.md has Neon grounding" bash -c "f='$ROOT/plan-gate-brief.md'; test -s \"\$f\" && grep -qF 'Ground everything before you cite it' \"\$f\" && grep -qF 'March 2026' \"\$f\" && grep -qF 'official documentation' \"\$f\""
chk "plan-gate-brief.md has failure-mode guardrails" bash -c "f='$ROOT/plan-gate-brief.md'; grep -qiF 'failure modes' \"\$f\" && grep -qF 'error and edge boundaries' \"\$f\" && grep -qF 'container, isolation and security invariants' \"\$f\""
chk "opus-gate-brief.md covers all gates" bash -c "f='$ROOT/opus-gate-brief.md'; test -s \"\$f\" && for g in review security epoch; do grep -q -- \"- \$g: \" \"\$f\" || exit 1; done"
chk "plan-schema.json valid" bash -c "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d[\"type\"]==\"object\" and \"gate\" in d[\"required\"] and \"rollback\" in d[\"required\"] and d[\"properties\"][\"tier\"][\"enum\"]==[\"low\",\"medium\",\"high\"]' '$ROOT/plan-schema.json'"
chk "review-schema.json valid" bash -c "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d[\"type\"]==\"object\" and set(d[\"required\"])>={\"gate\",\"head_sha\",\"verdict\",\"summary\",\"findings\"} and d[\"properties\"][\"verdict\"][\"enum\"]==[\"pass\",\"fail\"]' '$ROOT/review-schema.json'"
chk "opencode/opencode.json valid and pinned" bash -c "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d[\"model\"].endswith(\"deepseek-v4.1-flash#high\") and \"implementer\" in d[\"agents\"]' '$ROOT/opencode/opencode.json'"
# --- --help in bash and zsh ---
chk "help (bash)" bash -c "for s in gate.sh implement.sh premerge-and-merge.sh; do bash '$SCRIPT'/\"\$s\" --help >/dev/null || exit 1; done"
if command -v zsh >/dev/null; then chk "help (zsh)" bash -c "for s in gate.sh implement.sh premerge-and-merge.sh; do zsh '$SCRIPT'/\"\$s\" --help >/dev/null || exit 1; done"; fi
# --- documentation invariants the scripts rely on ---
chk "four-role model routing in SKILL.md" bash -c "f='$ROOT/SKILL.md'; for m in gemini-4-neon claude-opus-5-5 'opencode-go/deepseek-v4.1-flash#high'; do grep -qF \"\$m\" \"\$f\" || exit 1; done && grep -qF 'Architect & Planner' \"\$f\" && grep -qF 'Implementer' \"\$f\" && grep -qF 'Reviewer, Security & Epoch' \"\$f\""
chk "Orchestration V2 contract in SKILL.md" bash -c "f='$ROOT/SKILL.md'; for k in orchestrator_capabilities delegate_task task_cancel t3_submit_output 'T3 Orchestration V2' 'never poll'; do grep -qiF \"\$k\" \"\$f\" || exit 1; done"
chk "medium/high-only effort stated" bash -c "grep -qF 'medium' '$ROOT/SKILL.md' && grep -qF 'high' '$ROOT/SKILL.md' && grep -qF 'No other model, route or account' '$ROOT/SKILL.md' && grep -qF 'no model fallback' '$ROOT/SKILL.md'"
chk "scripts wired into SKILL.md" bash -c "f='$ROOT/SKILL.md'; for s in scripts/gate.sh scripts/premerge-and-merge.sh scripts/implement.sh; do grep -qF \"\$s\" \"\$f\" || exit 1; done && grep -qF 'gate.sh epoch' \"\$f\" && grep -qF 'Rounds are counted per gate from EVID/gates.log' \"\$f\""
chk "reference.md documents T3-verified provenance" bash -c "f='$ROOT/reference.md'; test -s \"\$f\" && grep -qF 't3_thread_read' \"\$f\" && grep -qF 't3-verified' \"\$f\" && grep -qF '4-stage chronology' \"\$f\" && grep -qF 'reference.md' \"\$ROOT/SKILL.md\""
# --- AC36: HEAD rules SKILL.md must keep ---
chk "pre-authorized paragraph" grep -qF 'Pre-authorized (Rahi 2026-11-13' "$ROOT/SKILL.md"
chk "hard boundaries stated" bash -c "for p in 'new spend, purchases, paid usage or credits, subscriptions or plan upgrades' 'outbound messages under Rahi' 'exposing secrets or credentials' 'bypassing or weakening a failed gate' 'without verified recovery' 'legal agreements or acceptance records' 'changing the model routing or the conductor' 'passkey touch'; do grep -qF \"\$p\" '$ROOT/SKILL.md' || exit 1; done"
chk "no user authorization left" bash -c "! grep -qE 'only the user|user can authorize|user.s decision|ask the user|user approv' '$ROOT/SKILL.md'"
chk "delta-round rule stated" grep -qF 'Changes since the last round' "$ROOT/SKILL.md"
chk "plan risks and RED in SKILL.md" bash -c "grep -qF '## Plan risks' '$ROOT/SKILL.md' && grep -qF 'RED confirmed:' '$ROOT/SKILL.md'"
chk "brief optional + op record + size" bash -c "grep -qi optional '$ROOT/opus-gate-brief.md' && grep -qF 'op-<name>.md' '$ROOT/SKILL.md' && [ \$(wc -c < '$ROOT/SKILL.md') -le 25600 ]"
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
chk "implement.sh is DeepSeek-only" bash -c "grep -qF 'opencode-go/deepseek-v4.1-flash' '$SCRIPT/implement.sh' && ! grep -qE 'claude -p|claude-sonnet|--model claude|cswap|sonnetcfg|snclass|SNM' '$SCRIPT/implement.sh' '$SCRIPT/implement_lib.py'"
chk "no home paths in the skill" bash -c "! grep -rqE '/Use[r]s/' '$ROOT' --exclude-dir=__pycache__ --exclude-dir=graft"
# --- split suites ---
printf '\n'
for s in gate-smoke.sh premerge-smoke.sh implement-smoke.sh; do
  if bash "$TESTS/$s"; then ok "$s passed"; else bad "$s failed"; fi
done
printf '\n%s\n' "$([ $FAILED = 0 ] && echo 'ALL TESTS PASSED!' || echo 'TESTS FAILED!')"
exit $FAILED
