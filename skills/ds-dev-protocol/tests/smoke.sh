#!/usr/bin/env bash
# tests/smoke.sh - doc, static, syntax and line-limit checks; then the gate, pre-merge and implementer suites.
# Fakes only: temp HOME/PATH, local bare origin, no model call, no network.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P); export ROOT
T=$(mktemp -d "${TMPDIR:-/tmp}/ds-smoke.XXXXXX"); T=$(cd "$T" && pwd -P)
export T HOME="$T/home"; mkdir -p "$HOME"
FAILED=0; trap 'rm -rf "$T"' EXIT
ok() { printf 'ok   %s\n' "$1"; }; bad() { printf 'FAIL %s\n' "$1"; FAILED=1; }
chk() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
SCRIPT=$ROOT/scripts; TESTS=$ROOT/tests
# --- syntax: every shell script parses; every Python helper compiles ---
for f in "$SCRIPT"/*.sh "$TESTS"/*.sh; do chk "bash -n ${f#$ROOT/}" bash -n "$f"; done
for f in "$SCRIPT"/*.py; do chk "py_compile ${f#$ROOT/}" bash -c "cp '$f' '$T/compile.py' && python3 -I -m py_compile '$T/compile.py'"; done
chk "python helpers are the three stdlib libraries" bash -c "ls '$SCRIPT'/gate_lib.py '$SCRIPT'/implement_lib.py '$SCRIPT'/premerge_lib.py >/dev/null"
# --- line limits: every file in scripts/ is at most 200 lines; smoke.sh at most 375 ---
chk "line limits: scripts/ <= 200" bash -c "for f in '$SCRIPT'/*; do [ ! -f \"\$f\" ] || [ \$(wc -l < \"\$f\") -le 200 ] || exit 1; done"
chk "line limits: smoke.sh <= 375" bash -c "[ \$(wc -l < '$TESTS/smoke.sh') -le 375 ]"
chk "line limits: split suites <= 400" bash -c "for f in '$TESTS'/gate-smoke.sh '$TESTS'/premerge-smoke.sh '$TESTS'/implement-smoke.sh; do [ \$(wc -l < \"\$f\") -le 400 ] || exit 1; done"
# --- SKILL.md size and frontmatter description ---
chk "SKILL.md <= 25600 bytes" test "$(wc -c < "$ROOT/SKILL.md")" -le 25600
chk "frontmatter description <= 450 chars" bash -c "d=\$(awk -F\"'\" '/^description:/{print \$2; exit}' '$ROOT/SKILL.md'); [ -n \"\$d\" ] && [ \${#d} -le 450 ]"
# --- forbidden tokens: no cswap, agy, Sonnet, xhigh, provisional or code-review anywhere the conductor reads ---
chk "zero forbidden tokens in SKILL.md, reference.md, scripts/" bash -c "for t in cswap agy Sonnet xhigh provisional code-review; do ! grep -riq -- \"\$t\" '$ROOT/SKILL.md' '$ROOT/reference.md' '$SCRIPT' || exit 1; done"
for t in cswap agy Sonnet xhigh provisional code-review; do chk "token absent: $t" bash -c "! grep -riq -- '$t' '$ROOT/SKILL.md' '$ROOT/reference.md' '$SCRIPT'"; done
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
chk "gate.sh never runs a model itself" bash -c "! grep -qE 'claude -p|opencode run|cswap' '$SCRIPT/gate.sh' && grep -qF 'T3_ACP_MCP_NODE' '$SCRIPT/gate_lib.py' && grep -qF 'ELECTRON_RUN_AS_NODE' '$SCRIPT/gate_lib.py'"
chk "gate-smoke drives the real ACP node path" bash -c "grep -qF 'T3_ACP_MCP_NODE' '$TESTS/gate-smoke.sh' && grep -qF 'acp-mcp-call' '$TESTS/gate-smoke.sh'"
chk "implement.sh is DeepSeek-only" bash -c "grep -qF 'opencode-go/deepseek-v4.1-flash' '$SCRIPT/implement.sh' && ! grep -qE 'claude -p|claude-sonnet|--model claude|cswap|sonnetcfg|snclass|SNM' '$SCRIPT/implement.sh' '$SCRIPT/implement_lib.py'"
chk "no home paths in the skill" bash -c "! grep -rqE '/Use[r]s/' '$ROOT'"
# --- split suites ---
printf '\n'
for s in gate-smoke.sh premerge-smoke.sh implement-smoke.sh; do
  if bash "$TESTS/$s"; then ok "$s passed"; else bad "$s failed"; fi
done
printf '\n%s\n' "$([ $FAILED = 0 ] && echo 'ALL TESTS PASSED!' || echo 'TESTS FAILED!')"
exit $FAILED
