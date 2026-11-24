#!/usr/bin/env bash
# tests/implement-smoke.sh - fakes-only tests for the DeepSeek-High-only scripts/implement.sh; temp HOME, no model call, no network.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P); IM=$ROOT/scripts/implement.sh
T=$(mktemp -d "${TMPDIR:-/tmp}/impl-smoke.XXXXXX"); T=$(cd "$T" && pwd -P); FAILED=0 OUTSIDE=0
trap 'kill "$OUTSIDE" 2>/dev/null; rm -rf "$T"' EXIT
ok() { printf 'ok   impl: %s\n' "$1"; }; bad() { printf 'FAIL impl: %s\n' "$1"; FAILED=1; }
chk() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
export T HOME=$T/home; EVR=$HOME/.local/state/dev-evidence; E=$EVR/task
mkdir -p "$E" "$T/bin" "$T/oc" "$T/sys"; ln -s "$(command -v python3)" "$T/sys/python3"
cat > "$T/oc/opencode" <<'FAKE'
#!/bin/bash
printf 'opencode %s | cfg=%s free=%s cc=%s xdg=%s state=%s tmp=%s pwd=%s\n' "$*" "${OPENCODE_CONFIG_DIR:-}" "${OPENCODE_DISABLE_FREE_MODELS:-}" "${OPENCODE_DISABLE_CLAUDE_CODE:-}" "${XDG_CACHE_HOME:-}" "${XDG_STATE_HOME:-}" "${TMPDIR:-}" "$PWD" >> "$T/calls.log"
LEAK='<|tool_calls_cbegin|>'
if [ "$1 $2" = "session export" ]; then id=${!#}; n=$(cat "$T/runseq" 2>/dev/null || echo 0)
  m=deepseek-v4.1-flash; e=null; extra=
  case $n in
    1) m=${FAKE_PROBE_MODEL:-$m} ;;
    3) [ -z "${FAKE_ERR_RESUME:-}" ] || e="{\"type\": \"$FAKE_ERR_RESUME\"}" ;;
    *) [ -z "${FAKE_ERR:-}" ] || e="{\"type\": \"$FAKE_ERR\"}" ;;
  esac
  # The cumulative session export keeps an earlier turn's leak; a clean resume turn must still be judged on its own events.
  { [ -z "$FAKE_LEAK" ] && [ -z "$FAKE_LEAK_RESUME" ]; } || extra=', {"type": "text", "part": {"text": "'"$LEAK"'"}}'
  printf '{"info": {"id": "%s", "cost": 0, "tokens": {"input": %s, "output": 2}}, "messages": [{"type": "assistant", "model": {"providerID": "opencode-go", "id": "%s", "variant": "high"}, "error": %s}%s]}\n' "$id" "${FAKE_TIN:-5}" "$m" "$e" "$extra"
  exit 0; fi
n=$(( $(cat "$T/runseq" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$T/runseq"
agent=""; resume=0; while [ $# -gt 0 ]; do [ "$1" = --agent ] && agent=$2; [ "$1" = --session ] && resume=1; shift; done
id=ses_main; c=${FAKE_COST:-0}; leak=0
if [ "$agent" = implementer-probe ]; then id=ses_probe; c=0
elif [ "$resume" = 1 ]; then c=${FAKE_RESUME_COST:-0}; [ -z "${FAKE_RESUME_ACTION:-}" ] || eval "$FAKE_RESUME_ACTION"
else [ -z "${FAKE_ACTION:-}" ] || eval "$FAKE_ACTION"; fi
case $n in
  1) [ -z "${FAKE_PROBE_LEAK:-}" ] || leak=1 ;;
  3) [ -z "${FAKE_LEAK_RESUME:-}" ] || leak=1; [ -z "${FAKE_RESUME_SLEEP:-}" ] || exec sleep "$FAKE_RESUME_SLEEP" ;;
  *) [ -z "${FAKE_LEAK:-}" ] || leak=1 ;;
esac
# A leak is the delimiter in THIS turn's own assistant text; a tool output quoting it is not.
[ "$leak" = 0 ] || printf '{"type": "text", "sessionID": "%s", "part": {"text": "%s"}}\n' "$id" "$LEAK"
[ -z "${FAKE_TOOLQUOTE:-}" ] || printf '{"type": "tool", "sessionID": "%s", "part": {"output": "%s"}}\n' "$id" "$LEAK"
printf '{"type": "step_finish", "sessionID": "%s", "part": {"cost": %s}}\n' "$id" "$c"
FAKE
cat > "$T/bin/lsof" <<'FAKE'
#!/bin/bash
# Claim one process that can never be signalled (above the PID ceiling, not ours), so the reaper must fail closed.
[ -e "$T/taint" ] && printf 'p999999\nn%s\n' "$W"; exec /usr/sbin/lsof "$@"
FAKE
chmod +x "$T/bin"/* "$T/oc"/*
export W=$T/wt; R=$T/repo; git init -q -b main "$R"; mkdir -p "$R/src" "$R/tests"
printf 'a\n' > "$R/src/a.txt"; printf "it('x', () => {})\n" > "$R/tests/a.test.js"; printf '{"devDependencies": {}}\n' > "$R/package.json"
printf 'lock\n' > "$R/bun.lock"; printf '*.ok\nignored.txt\n' > "$R/.gitignore"
git -C "$R" add -A; git -C "$R" -c user.name=t -c user.email=t@e commit -qm base; git -C "$R" worktree add -q --detach "$W"
# mkplan NAME [field=value ...]: a T3-verified Neon plan row (route/model/provenance/engine) that implement_lib.py accepts.
mkplan() { local f=plan-$1.json; shift; local fs fld
  printf '{"structured_output": {"gate": "plan", "tier": "medium", "acceptance_criteria": ["ac"], "design": "d-%s", "files": ["src/a.txt", "src/b.txt", "tests/", "docs/", "package.json", "bun.lock", ".github/"], "tests": ["t"]}}\n' "${f%.json}" > "$E/$f"
  fs=$(shasum -a 256 "$E/$f" | awk '{print $1}')
  python3 - "$E/gates.log" "$f" "$fs" "$@" <<'PY'
import json, sys
p, f, fs = sys.argv[1:4]
d = {"gate": "plan", "status": "ok", "route": "neon", "model": "gemini-4-neon", "effort": "medium", "provenance_mode": "t3-verified",
     "engine": "t3-delegate", "file": f, "file_sha256": fs, "key": fs, "session_id": "child-1", "parent_thread_id": "parent-1", "account": "antigravity"}
for kv in sys.argv[4:]:
    k, v = kv.split("=", 1); d[k] = v
open(p, "a").write(json.dumps(d) + "\n")
PY
}
fresh() { rm -f "$T/taint" "$T/runseq"; git -C "$W" reset -q --hard; git -C "$W" clean -qffdx; rm -rf "$E"; mkdir -p "$E"; mkplan p1; : > "$T/calls.log"
  unset FAKE_ACTION FAKE_RESUME_ACTION FAKE_COST FAKE_RESUME_COST FAKE_ERR FAKE_ERR_RESUME FAKE_PROBE_MODEL FAKE_PROBE_LEAK FAKE_LEAK FAKE_LEAK_RESUME FAKE_TIN FAKE_TOOLQUOTE FAKE_RESUME_SLEEP IMPL_DEADLINE NOOC NOEV CWD XDG_CACHE_HOME XDG_STATE_HOME; }
im() { local p="$T/bin:$T/sys:/usr/bin:/bin:/usr/sbin:/sbin"; [ -n "${NOOC:-}" ] || p="$T/oc:$p"
  ( cd "${CWD:-$W}" && if [ -z "${NOEV:-}" ]; then export EVID=$E; else unset EVID; fi
    PATH=$p bash "$IM" "$@" ) > "$T/out" 2>&1; IRC=$?; }
nmodel() { grep -cE '^(opencode|claude) ' "$T/calls.log"; }
runs() { grep -c '^opencode run ' "$T/calls.log"; }
clean() { [ -z "$(git -C "$W" status --porcelain --untracked-files=all)" ]; }
RES='printf "{\"status\": \"done\", \"tests_run\": [\"t\"], \"not_checked\": []}" > .impl/result.json'
# --- preconditions: exit 2, no opencode call ---
pre() { local d=$1; shift; im "$@"; if [ "$IRC" = 2 ] && [ "$(nmodel)" = 0 ]; then ok "pre: $d"; else bad "pre: $d (rc $IRC, $(nmodel) calls)"; fi; }
fresh; NOEV=1 pre "EVID unset" medium --bootstrap none
fresh; pre "no --bootstrap" medium
fresh; echo x >> "$W/src/a.txt"; pre "dirty file" medium --bootstrap none
fresh; echo x > "$W/new.txt"; pre "untracked file" medium --bootstrap none
fresh; mkdir "$W/.impl"; pre ".impl exists" medium --bootstrap none
fresh; echo '{"status": "start", "step": "main"}' >> "$E/impl.log"; pre "trailing start row" medium --bootstrap none
fresh; : > "$E/gates.log"; pre "no logged plan" medium --bootstrap none
fresh; echo x >> "$E/plan-p1.json"; pre "plan hash mismatch" medium --bootstrap none
fresh; rm -f "$E"/plan-*.json; pre "plan file missing" medium --bootstrap none
fresh; CWD=$R pre "main checkout, not a linked worktree" medium --bootstrap none
fresh; git -C "$R" worktree add -q --detach "$EVR/wtx"; CWD=$EVR/wtx pre "worktree under the evidence root" medium --bootstrap none; git -C "$R" worktree remove --force "$EVR/wtx"
fresh; pre "bad tier max" max --bootstrap none
# --- Neon plan lookup: route, model, effort and t3 provenance are all required ---
badplan() { local d=$1 kv=$2; fresh; : > "$E/gates.log"; mkplan p1 "$kv"; im medium --bootstrap none
  if [ "$IRC" = 2 ] && [ "$(nmodel)" = 0 ]; then ok "plan lookup: $d"; else bad "plan lookup: $d (rc $IRC)"; fi; }
badplan "route must be neon" route=opus
badplan "model must be gemini-4-neon" model=claude-opus-5-5
badplan "effort xhigh rejected" effort=xhigh
badplan "effort empty rejected" effort=
badplan "provenance_mode must be t3-verified" provenance_mode=provisional
badplan "engine must be t3-delegate" engine=claude-delegate
# --- happy DeepSeek run ---
fresh; mkdir -p "$T/xc" "$T/xs" "$T/tmpx"; FAKE_ACTION="echo b > src/a.txt; echo x > ignored.txt; $RES" IMPL_MODEL=x OPENCODE_MODEL=y XDG_CACHE_HOME=$T/xc XDG_STATE_HOME=$T/xs TMPDIR=$T/tmpx im medium --bootstrap none
chk "happy: exit 0" test "$IRC" = 0
chk "happy: probe first" bash -c "grep '^opencode run' '$T/calls.log' | head -1 | grep -q -- '--agent implementer-probe'"
chk "happy: pinned argv, no --auto" bash -c "grep -qF -- 'run --standalone --archived --agent implementer --model opencode-go/deepseek-v4.1-flash#high --format json' '$T/calls.log' && ! grep -q -- '--auto' '$T/calls.log'"
MR=$(grep -- '--agent implementer ' "$T/calls.log")
chk "happy: env inherited (XDG/TMPDIR not redirected)" bash -c "printf '%s' \"\$1\" | grep -qF -- 'cfg=$ROOT/opencode free=1 cc=1 xdg=$T/xc state=$T/xs tmp=$T/tmpx'" _ "$MR"
chk "happy: export cwd is not the worktree" bash -c "! grep '^opencode session export' '$T/calls.log' | grep -q 'pwd=$W\$'"
chk "happy: log start then deepseek done" bash -c "head -1 '$E/impl.log' | grep -q '\"status\": \"start\"' && tail -1 '$E/impl.log' | grep -q '\"route\": \"deepseek\", \"model\": \"opencode-go/deepseek-v4.1-flash\", \"effort\": \"high\", \"status\": \"done\"'"
chk "happy: result in EVID, .impl gone, ignored gone, change kept" bash -c "ls '$E'/impl-main-r1-*-result.json && test ! -e '$W/.impl' && test ! -e '$W/ignored.txt' && grep -q b '$W/src/a.txt'"
chk "no other DeepSeek variant in the scripts" bash -c "! grep -qE '#(medium|low|max)' '$IM' '$ROOT/scripts/implement_lib.py'"
# --- DeepSeek High only: unavailability exits 3 with zero claude calls ---
unavail() { local d=$1; shift; im medium --bootstrap none; if [ "$IRC" = 3 ] && ! grep -q '^claude' "$T/calls.log" && tail -1 "$E/impl.log" | grep -q '"route": "deepseek".*"model": "opencode-go/deepseek-v4.1-flash".*"effort": "high".*"status": "unavailable"'; then ok "unavailable: $d"; else bad "unavailable: $d (rc $IRC)"; fi; }
fresh; NOOC=1 unavail "opencode not on PATH"
fresh; FAKE_PROBE_MODEL=beam-free unavail "probe returns a free model"; chk "unavailable: no main run after a bad probe" bash -c "! grep -q -- '--agent implementer ' '$T/calls.log'"
fresh; FAKE_COST=0.01 FAKE_ACTION="$RES" unavail "non-zero cost"
fresh; FAKE_ERR=provider.go-limit FAKE_ACTION="echo b > src/a.txt" unavail "provider error mid-run"
chk "unavailable: partial patch kept, tree clean" bash -c "grep -q src/a.txt '$E'/impl-*-discarded.patch && [ -z \"\$(git -C '$W' status --porcelain --untracked-files=all)\" ]"
# --- bounded auto-resume: delimiter leak / premature stop, once ---
fresh; FAKE_ACTION="echo b > src/a.txt" FAKE_RESUME_ACTION="$RES" im medium --bootstrap none
chk "resume: premature stop resumes once and finishes" bash -c "[ $IRC = 0 ] && [ \$(grep -c '^opencode run ' '$T/calls.log') = 3 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"done\"' && grep -q b '$W/src/a.txt'"
fresh; FAKE_LEAK=1 FAKE_RESUME_ACTION="$RES" im medium --bootstrap none
chk "resume: tool-call delimiter leak resumes once and finishes" bash -c "[ $IRC = 0 ] && [ \$(grep -c '^opencode run ' '$T/calls.log') = 3 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"done\"' && grep -q '<|tool_calls_cbegin|>' '$E'/impl-main-r1-*-main.events && ! grep -q '<|tool_calls_cbegin|>' '$E'/impl-main-r1-*-resume.events && grep -q '<|tool_calls_cbegin|>' '$E'/impl-main-r1-*-resume-export.json"
fresh; FAKE_ACTION="echo b > src/a.txt" im medium --bootstrap none
chk "resume: a second stop fails cleanly" bash -c "[ $IRC = 1 ] && [ \$(grep -c '^opencode run ' '$T/calls.log') = 3 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"failed\", \"reason\": \"premature turn termination\"' && ls '$E'/impl-*-discarded.patch >/dev/null && [ -z \"\$(git -C '$W' status --porcelain --untracked-files=all)\" ]"
fresh; FAKE_LEAK=1 FAKE_LEAK_RESUME=1 im medium --bootstrap none
chk "resume: leak on the resume fails as a leak" bash -c "[ $IRC = 1 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"failed\", \"reason\": \"tool-call delimiter leak\"' && [ \$(grep -c '^opencode run ' '$T/calls.log') = 3 ]"
fresh; FAKE_TOOLQUOTE=1 FAKE_ACTION="$RES" im medium --bootstrap none
chk "leak: a tool output quoting the delimiter does not trigger a resume" bash -c "[ $IRC = 0 ] && [ \$(grep -c '^opencode run ' '$T/calls.log') = 2 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"done\"' && ! grep -q '\"status\": \"failed\"' '$E/impl.log'"
fresh; FAKE_ACTION="echo b > src/a.txt" FAKE_ERR_RESUME=provider.go-limit im medium --bootstrap none
chk "resume unavailable: exit 3, cost 0, no failed row" bash -c "[ $IRC = 3 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"unavailable\"' && tail -1 '$E/impl.log' | grep -q '\"cost_usd\": 0' && ! grep -q '\"status\": \"failed\"' '$E/impl.log' && ls '$E'/impl-*-discarded.patch >/dev/null"
fresh; IMPL_DEADLINE=3 FAKE_ACTION="echo b > src/a.txt" FAKE_RESUME_SLEEP=60 im medium --bootstrap none
chk "resume timeout keeps its own timeout reason" bash -c "[ $IRC = 1 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"failed\", \"reason\": \"timeout' && [ \$(grep -c '^opencode run ' '$T/calls.log') = 3 ] && [ -z \"\$(git -C '$W' status --porcelain --untracked-files=all)\" ]"
# --- not_checked is copied into EVID/impl-<tag>.json ---
fresh; FAKE_ACTION='printf "{\"status\": \"done\", \"tests_run\": [\"t\"], \"not_checked\": [\"device check\"]}" > .impl/result.json' im medium --bootstrap none
chk "not_checked copied to EVID/impl-<tag>.json" bash -c "[ $IRC = 0 ] && grep -q '\"not_checked\": \[' '$E'/impl-main-r1-*.json && grep -q 'device check' '$E'/impl-main-r1-*.json"
fresh; FAKE_ACTION='printf "{\"status\": \"done\", \"not_checked\": \"none\"}" > .impl/result.json' im medium --bootstrap none
chk "not_checked must be a list" bash -c "[ $IRC = 1 ] && tail -1 '$E/impl.log' | grep -q 'not_checked'"
# --- outcome checks: exit 1, failed, clean tree, patch saved ---
fcase() { fresh; FAKE_ACTION=$2 im medium --bootstrap none
  if [ "$IRC" = 1 ] && tail -1 "$E/impl.log" | grep -q '"status": "failed"' && clean && ls "$E"/impl-*-discarded.patch >/dev/null 2>&1; then ok "fail: $1"; else bad "fail: $1 (rc $IRC)"; fi; }
fcase "no result.json" "echo b > src/a.txt; :"
fcase "path outside the plan files" "echo b > other.txt; $RES"
fcase ".github file matched only by a directory entry" "mkdir -p .github/workflows; echo x > .github/workflows/x.yml; $RES"
fcase "nested repository under a listed directory" "git init -q tests/sub; echo x > tests/sub/f; $RES"
fcase "FIFO package.json" "rm package.json; mkfifo package.json; $RES"
fcase "lockfile change" "echo y >> bun.lock; $RES"
fcase "new devDependency" "printf '{\"devDependencies\": {\"left-pad\": \"1\"}}\n' > package.json; $RES"
fcase "deleted test file" "rm tests/a.test.js; $RES"
fcase "added skip marker" "echo \"it.skip('y', () => {})\" >> tests/a.test.js; $RES"
fcase "result.json is a symlink" "echo '{\"status\": \"done\"}' > '$T/res.json'; ln -s '$T/res.json' .impl/result.json"
fresh; H0=$(git -C "$W" rev-parse HEAD); FAKE_ACTION="echo c > src/a.txt; git -c user.name=t -c user.email=t@e commit -qam x; $RES" im medium --bootstrap none
chk "HEAD moved: failed, HEAD restored, clean, patch saved" bash -c "[ $IRC = 1 ] && tail -1 '$E/impl.log' | grep -q '\"status\": \"failed\", \"reason\": \"HEAD moved' && [ \"\$(git -C '$W' rev-parse HEAD)\" = '$H0' ] && [ -z \"\$(git -C '$W' status --porcelain --untracked-files=all)\" ] && grep -q src/a.txt '$E'/impl-*-discarded.patch"
fresh; H0=$(git -C "$W" rev-parse HEAD); G=$(git -C "$W" rev-parse --git-dir); FAKE_ACTION="echo c > src/a.txt; git -c user.name=t -c user.email=t@e commit -qam x; touch \"\$(git rev-parse --git-dir)/index.lock\"; $RES" im medium --bootstrap none
chk "restore failure: exit 6, restore to BASE failed" bash -c "[ $IRC = 6 ] && tail -1 '$E/impl.log' | grep -q '\"reason\": \"restore to BASE failed'"
rm -f "$G/index.lock"; git -C "$W" checkout -q --detach "$H0"
fresh; FAKE_ACTION='echo q > .impl/escalation.md; printf "{\"status\": \"escalate\"}" > .impl/result.json' im medium --bootstrap none
chk "escalate: exit 5, escalation in EVID, clean" bash -c "[ $IRC = 5 ] && ls '$E'/escalation-*.md && [ -z \"\$(git -C '$W' status --porcelain)\" ]"
fresh; FAKE_ACTION='printf "{\"status\": \"escalate\"}" > .impl/result.json' im medium --bootstrap none; chk "escalate without escalation.md: exit 1" test "$IRC" = 1
# --- timeout and reaper ---
fresh; IMPL_DEADLINE=2 FAKE_ACTION="sleep 31" im medium --bootstrap none
chk "timeout: failed, reason timeout, nothing left running" bash -c "[ $IRC = 1 ] && tail -1 '$E/impl.log' | grep -q '\"reason\": \"timeout' && ! pgrep -f '^sleep 31\$'"
fresh; (cd "$T" && exec sleep 302) & OUTSIDE=$!; FAKE_ACTION="(sleep 301 &); $RES" im medium --bootstrap none
chk "reaper: detached child in the worktree killed, outside process kept" bash -c "! pgrep -f '^sleep 301\$' && kill -0 $OUTSIDE"
# --- fail closed: a surviving worktree process gives exit 6 and nothing else runs ---
fresh; FAKE_ACTION="echo planted > src/a.txt; touch '$T/taint'; $RES" im medium --bootstrap "touch $T/boot3"
chk "survivor after the main run: exit 6, failed row, no result copy, no patch, no bootstrap" bash -c "[ $IRC = 6 ] && tail -1 '$E/impl.log' | grep -q '\"route\": \"deepseek\".*\"status\": \"failed\", \"reason\": \"worktree processes survived' && ! ls '$E'/impl-*-result.json '$E'/*discarded.patch && test ! -e '$T/boot3' && grep -q planted '$W/src/a.txt'"
fresh; echo '{"status": "start", "step": "main"}' >> "$E/impl.log"; echo junk > "$W/junk.txt"; touch "$T/taint"; im --discard --bootstrap "touch $T/boot4"
chk "survivor on --discard: exit 6, no reset, no bootstrap" bash -c "[ $IRC = 6 ] && test -e '$W/junk.txt' && test ! -e '$T/boot4'"
# --- rounds, discard, check ---
fresh; PS=$(shasum -a 256 "$E/plan-p1.json" | awk '{print $1}'); for i in 1 2 3; do printf '{"step": "main", "round": %s, "plan_sha256": "%s", "route": "deepseek", "status": "failed"}\n' "$i" "$PS" >> "$E/impl.log"; done
im medium --bootstrap none; chk "round cap: exit 4, no model call" bash -c "[ $IRC = 4 ] && [ \$(grep -cE '^(opencode|claude) ' '$T/calls.log') = 0 ]"
mkplan p2; FAKE_ACTION="$RES" im medium --bootstrap none; chk "a new plan restarts the rounds" test "$IRC" = 0
fresh; echo '{"status": "start", "step": "main"}' >> "$E/impl.log"; echo junk > "$W/junk.txt"; im --discard --bootstrap "touch $T/boot2"
chk "--discard: reset, bootstrap, discarded row" bash -c "[ $IRC = 0 ] && [ -z \"\$(git -C '$W' status --porcelain --untracked-files=all)\" ] && test -e '$T/boot2' && tail -1 '$E/impl.log' | grep -q '\"status\": \"discarded\"'"
fresh; git -C "$R" -c user.name=t -c user.email=t@e commit -q --allow-empty -m other; H0=$(git -C "$W" rev-parse HEAD); BASE=$(git -C "$R" rev-parse HEAD) im --discard --bootstrap none
chk "--discard ignores BASE from the environment" bash -c "[ $IRC = 0 ] && [ \"\$(git -C '$W' rev-parse HEAD)\" = '$H0' ]"
FAKE_ACTION="$RES" im medium --bootstrap none; chk "after --discard the next call runs" test "$IRC" = 0
DOK='{"route": "deepseek", "model": "opencode-go/deepseek-v4.1-flash", "effort": "high", "status": "done", "step": "s", "round": 1}'
DUN='{"route": "deepseek", "model": "opencode-go/deepseek-v4.1-flash", "effort": "high", "status": "unavailable", "step": "s", "round": 2}'
ck() { local d=$1 want=$2 rc; shift 2; rm -f "$E/impl.log"; for r in "$@"; do echo "$r" >> "$E/impl.log"; done
  ( EVID=$E bash "$IM" --check ) >/dev/null 2>&1; rc=$?; if [ "$rc" = "$want" ]; then ok "check: $d"; else bad "check: $d (rc $rc)"; fi; }
ck "no log passes" 0; ck "valid log passes" 0 '{"route": "", "status": "start", "step": "s"}' "$DOK" "$DUN" '{"route": "", "status": "discarded"}'
ck "deepseek effort medium fails" 1 "${DOK/\"high\"/\"medium\"}"; ck "deepseek beam-free fails" 1 "${DOK/deepseek-v4.1-flash/beam-free}"
ck "sonnet route fails" 1 '{"route": "sonnet", "model": "claude-sonnet-5-5", "effort": "high", "status": "done"}'
ck "route kimi fails" 1 '{"route": "kimi", "status": "done"}'; ck "non-zero cost fails" 1 "${DOK/\"step\"/\"cost_usd\": 1, \"step\"}"
# --- brief: the installed tdd skill (a sibling of the skill folder) is appended for the implementer ---
TDH="## tdd skill (reference for writing the Tests; the rules above, the plan and the notes win; the plan's Tests are the agreed seams: never ask, use no other skill)"
mkdir -p "$T/sk/ds-dev-protocol" "$T/sk/tdd"; cp "$ROOT/implementer-brief.md" "$T/sk/ds-dev-protocol/implementer-brief.md"
{ printf -- '---\nname: tdd\ndescription: x\n---\n'; echo TDD-BODY-MARK; } > "$T/sk/tdd/SKILL.md"
echo TESTS-MARK > "$T/sk/tdd/tests.md"; echo MOCK-MARK > "$T/sk/tdd/mocking.md"; echo NOTE-MARK > "$T/notes.md"
fresh; python3 -I "$ROOT/scripts/implement_lib.py" brief "$T/sk/ds-dev-protocol/implementer-brief.md" "$E/plan-p1.json" "$W" "$T/notes.md" "$T/b1.md"
chk "brief: installed tdd appended without frontmatter, between Tests and notes" bash -c 'f=$1; h=$2
  for m in "$h" TDD-BODY-MARK TESTS-MARK MOCK-MARK "### SKILL.md" "### tests.md" "### mocking.md"; do grep -qF -- "$m" "$f" || exit 1; done
  ! grep -qE "^name: tdd$" "$f" || exit 1
  a=$(grep -n "^## Tests" "$f" | head -1 | cut -d: -f1); b=$(grep -n "^## tdd skill" "$f" | head -1 | cut -d: -f1); c=$(grep -n "^## Notes from the conductor" "$f" | head -1 | cut -d: -f1)
  [ -n "$a" ] && [ -n "$b" ] && [ -n "$c" ] && [ "$a" -lt "$b" ] && [ "$b" -lt "$c" ]' _ "$T/b1.md" "$TDH"
mkdir -p "$T/sk2/ds-dev-protocol"; cp "$ROOT/implementer-brief.md" "$T/sk2/ds-dev-protocol/implementer-brief.md"
fresh; python3 -I "$ROOT/scripts/implement_lib.py" brief "$T/sk2/ds-dev-protocol/implementer-brief.md" "$E/plan-p1.json" "$W" - "$T/b2.md"
chk "brief: no tdd section without an installed tdd" bash -c "grep -qF '## Tests (one at a time: write it, see it fail, make it pass)' '$T/b2.md' && ! grep -qF '## tdd skill' '$T/b2.md'"
chk "brief: one test at a time, not all first" bash -c "grep -qF 'one at a time' '$ROOT/scripts/implement_lib.py' && ! grep -qF 'write them first' '$ROOT/implementer-brief.md' && ! grep -qF 'write them first' '$ROOT/scripts/implement_lib.py'"
printf '\n%s\n' "$([ $FAILED = 0 ] && echo 'IMPLEMENT TESTS PASSED' || echo 'IMPLEMENT TESTS FAILED')"
exit $FAILED
