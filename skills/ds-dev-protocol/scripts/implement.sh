#!/usr/bin/env bash
# implement.sh - run one ds-dev-protocol implementer round from the last logged plan. The route, provider, model,
# effort, account and cost cap come from routing.json at runtime (scripts/routing_lib.py): it is the sole
# implementer route, with no model fallback.
# It runs through `opencode run --standalone`, the documented mechanical runner (no OS sandbox): the role limits in
# opencode/opencode.json, the OPENCODE_DISABLE_* pins, process reaping, the cost check and one bounded delimiter-leak
# auto-resume all apply. Every attempt is logged to EVID/impl.log.
set -uo pipefail
usage() { cat <<'EOF'
usage: EVID=<dir> implement.sh <low|medium|high> --bootstrap <cmd|none> [--step NAME] [--notes FILE] [--trigger]
       EVID=<dir> implement.sh --discard --bootstrap <cmd|none>   (reset a worktree a killed run left behind)
       EVID=<dir> implement.sh --check                             (validate that EVID/impl.log uses the pinned implementer route)
  run from the root of a clean, linked task worktree; the brief comes from the last plan gate.sh logged in EVID
  the route, model, effort, account and cost cap come from routing.json; there is no fallback model
  env: IMPL_DEADLINE (seconds for one round: the probe, the main run and its one resume; default 3600)
exit: 0 done (conductor reads the diff, then re-runs the bootstrap), 1 failed round, 2 usage or precondition (no model call),
      3 implementer route unavailable (log blocked external and stop; no model fallback, zero reviewer calls),
      4 round cap (3 per step and plan), 5 escalate (EVID/escalation-<tag>.md),
      6 worktree processes survived (the worktree is tainted: read, run or commit nothing from it; remove it, use a new path)
EOF
}
die() { printf 'implement.sh: %s\n' "$*" >&2; exit 2; }
SKILL=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P); LIB=$SKILL/scripts/implement_lib.py; py() { python3 -I "$LIB" "$@"; }
# main runs only after bash has parsed the whole file, so an edit to this file during a run cannot change what runs.
main() {
if [ "${1:-}" = --help ]; then usage; exit 0; fi
[ -n "${EVID:-}" ] || die "EVID is unset"
[ -d "$EVID" ] || die "EVID is not a directory: $EVID"
EVID=$(cd "$EVID" && pwd -P)
if [ "${1:-}" = --check ]; then [ $# -eq 1 ] || die "--check takes no other arguments"; if py check "$EVID"; then exit 0; else exit 1; fi; fi
mode=run; tier=-; boot=""; hasboot=0; step=main; notes=-; trigger=0
if [ "${1:-}" = --discard ]; then mode=discard; shift
else [ $# -ge 1 ] || { usage >&2; exit 2; }; tier=$1; shift; case $tier in low|medium|high) ;; *) die "bad tier: $tier" ;; esac; fi
while [ $# -gt 0 ]; do case $1 in
  --bootstrap) shift; [ $# -gt 0 ] && [ -n "$1" ] || die "--bootstrap needs a command or none"; boot=$1; hasboot=1 ;;
  --trigger) [ "$mode" = run ] || die "--trigger is only valid for a run"; trigger=1 ;;
  --step) shift; [ $# -gt 0 ] || die "--step needs a name"; step=$1 ;;
  --notes) shift; [ "$mode" = run ] && [ $# -gt 0 ] || die "--notes needs a file"; [ -f "$1" ] || die "missing notes file: $1"; notes=$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1") ;;
  *) die "unknown argument: $1" ;; esac; shift; done
[ "$hasboot" = 1 ] || die "--bootstrap <cmd|none> is required (the repo's setup command, from its AGENTS.md/CLAUDE.md/README)"
printf '%s' "$step" | grep -Eq '^[A-Za-z0-9._-]+$' || die "bad step name: $step"
case ${IMPL_DEADLINE:-3600} in ''|*[!0-9]*|0) die "IMPL_DEADLINE must be whole seconds above 0" ;; esac; DEADLINE=${IMPL_DEADLINE:-3600}
# TMO is the timeout handed to each model call; T0 starts the round clock the resume's remaining budget is measured from.
TMO=$DEADLINE; T0=$SECONDS
WT=$(git rev-parse --show-toplevel 2>/dev/null) || die "not inside a git worktree"; WT=$(cd "$WT" && pwd -P)
[ "$(pwd -P)" = "$WT" ] || die "run from the worktree root: $WT"
GD=$(git rev-parse --path-format=absolute --git-dir) && GC=$(git rev-parse --path-format=absolute --git-common-dir) || die "cannot read git dirs"
GD=$(cd "$GD" && pwd -P); GC=$(cd "$GC" && pwd -P); [ "$GD" != "$GC" ] || die "not a linked worktree (create one with git worktree add --detach)"
H=$(cd "$HOME" && pwd -P); EVROOT=$H/.local/state/dev-evidence
inside() { case $1 in "$2"|"$2"/*) return 0 ;; esac; return 1; }
if inside "$H" "$WT" || inside "$WT" "$EVROOT" || inside "$EVROOT" "$WT"; then die "refusing worktree $WT: it is HOME or its ancestor, or overlaps the evidence root"; fi
# reap: stop every process whose cwd is in the worktree or under it; fails closed (exit 6).
RT=""; RM=""; RE=""; TAINT=0; BASE=""
reap() { REAPED=$(cd / && py reap "$WT" "$$"); }
tainted() { TAINT=1; local why=${1:-worktree processes survived: $REAPED}; if [ -n "$RT" ]; then py row "$EVID" "$step" "${round:-0}" "${ps:-}" "$tier" "$RT" "$RM" "$RE" failed "$why" "${SID:--}" 0 0 0
  else py row "$EVID" "$step" 0 "" "" "" "" "" discarded "$why" "" 0 0 0; fi
  printf 'implement.sh: %s. The worktree %s is tainted: read, run, bootstrap or commit nothing from it; from the main checkout run git worktree remove --force %s, never reuse that path, and continue in a fresh worktree.\n' "$why" "$WT" "$WT" >&2; exit 6; }
bootstrap() { [ "$boot" = none ] && return 0; (cd "$WT" && bash -c "$boot") >> "$EVID/impl-bootstrap.log" 2>&1 && return 0
  printf 'implement.sh: bootstrap failed (see %s); the worktree is reset but not set up\n' "$EVID/impl-bootstrap.log" >&2; return 1; }
discard() { reap || tainted; rm -rf "$WT/.impl"
  if [ -z "$BASE" ]; then git -C "$WT" reset --hard -q || tainted "reset failed"; git -C "$WT" clean -ffdxq; bootstrap; return; fi
  git -C "$WT" reset --hard -q || tainted "restore to BASE failed"
  git -C "$WT" checkout -q -f --detach "$BASE" || tainted "restore to BASE failed"; git -C "$WT" clean -ffdxq
  [ "$(git -C "$WT" rev-parse HEAD)" = "$BASE" ] && [ -z "$(git -C "$WT" status --porcelain --untracked-files=all)" ] || tainted "restore to BASE failed"
  bootstrap; }
if [ "$mode" = discard ]; then discard; brc=$?; py row "$EVID" "$step" 0 "" "" "" "" "" discarded "--discard" "" 0 0 0
  printf 'implement.sh: worktree reset to HEAD\n'; exit $((brc ? 1 : 0)); fi
# Routing comes from routing.json at runtime; invalid routing.json or opencode/opencode.json fails closed before any model call.
RLIB=$SKILL/scripts/routing_lib.py
routing_tsv=$(python3 -I "$RLIB" impl-tsv) || die "invalid routing.json: run python3 -I $RLIB check"
IFS=$'\t' read -r RT _ DSM DSID RE PINNED _ MAXCOST <<< "$routing_tsv"
OCCFG=$(python3 -I "$RLIB" opencode-config) || die "invalid opencode/opencode.json"
[ -z "$(git status --porcelain --untracked-files=all)" ] || die "worktree is not clean; commit or discard changes first"
[ ! -e "$WT/.impl" ] && [ ! -L "$WT/.impl" ] || die "$WT/.impl exists; run implement.sh --discard first"
if py laststart "$EVID"; then die "the last impl.log row is start: a run was killed; run implement.sh --discard --bootstrap <cmd|none> first"; fi
pinfo=$(py plan "$EVID" "$step") || die "no logged planner plan in $EVID/gates.log with a matching file (run gate.sh plan first)"
IFS=$'\t' read -r pf ps round counted <<< "$pinfo"
if [ "$counted" -ge 3 ]; then printf 'implement.sh: 3 rounds for step %s on this plan; re-plan through gate.sh plan\n' "$step" >&2; exit 4; fi
tag=$step-r$round-${ps:0:8}; BASE=$(git rev-parse HEAD)
# Trusted state stays in this process and EVID; the brief and its result live under .impl/ in the worktree.
py row "$EVID" "$step" "$round" "$ps" "$tier" "" "" "" start "" "" 0 0 0
RUN=$(mktemp -d "${TMPDIR:-/tmp}/implement.XXXXXX"); RUN=$(cd "$RUN" && pwd -P); mkdir -p "$RUN/x"; RM=$DSM
trap 'rm -rf "$RUN"; [ "$TAINT" = 1 ] || rm -rf "$WT/.impl"' EXIT; trap 'trap - INT TERM HUP; reap || tainted; printf "implement.sh: interrupted; run implement.sh --discard next\n" >&2; exit 130' INT TERM HUP
brief=$EVID/impl-$tag-brief.md; err=$EVID/impl-$tag.err; : > "$err"; py brief "$SKILL/implementer-brief.md" "$pf" "$WT" "$notes" "$brief" || die "cannot build the brief"
mkimpl() { mkdir "$WT/.impl" && cp "$brief" "$WT/.impl/brief.md"; }; mkimpl
patch_out() { { git status --porcelain --untracked-files=all; git diff --binary "$BASE"; } > "$EVID/impl-$tag-$1-discarded.patch" 2>/dev/null; }
# The OpenCode config pinning env is the role-limit and routing pin; the child inherits the caller's XDG and TMPDIR values.
oc() { env OPENCODE_CONFIG_DIR="$SKILL/opencode" OPENCODE_CONFIG_CONTENT="$OCCFG" OPENCODE_DISABLE_CLAUDE_CODE=1 \
    OPENCODE_DISABLE_FREE_MODELS=1 timeout -k 30 "$TMO" "$@"; }
# ds NAME AGENT MSG [ARGS]: one opencode run in the worktree, exported and classified. Sets KIND (ok|unavailable|timeout), WHY, SID, TIN, TOUT, COST.
ds() { local name=$1 agent=$2 msg=$3 evf=$EVID/impl-$tag-$1.events rc; shift 3; KIND=unavailable; SID=-; TIN=0; TOUT=0; COST=0
  if ! command -v opencode >/dev/null 2>&1; then WHY="opencode not on PATH"; return; fi
  (cd "$WT" && oc opencode run --standalone --archived --agent "$agent" --model "$PINNED" --format json \
    --title "$(basename "$EVID")-$step-r$round-$name" "$@" "$msg" < /dev/null > "$evf" 2>> "$err") & wait $!; rc=$?; reap || tainted
  if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then KIND=timeout; WHY="timeout after ${TMO}s"; return; fi
  SID=$(py sid "$evf"); SID=${SID:--}; local ex=$EVID/impl-$tag-$name-export.json; : > "$ex"
  [ "$SID" = - ] || { (cd "$RUN/x" && oc opencode session export --standalone "$SID") > "$ex" 2>> "$err" & wait $!; reap || tainted; }
  IFS=$'\t' read -r KIND WHY TIN TOUT COST <<< "$(py dsclass "$ex" "$evf" "$SID")"; }
# outcome ROUTE MODEL EFFORT FORCED: AC13 checks on a verified-model run; done keeps the changes, anything else is saved and discarded.
outcome() { local st why; IFS=$'\t' read -r st why <<< "$(cd / && py final "$EVID" "$WT" "$pf" "$tag" "$step" "$round" "$ps" "$tier" "$1" "$2" "$3" "$SID" "$TIN" "$TOUT" "$COST" "$4" "$BASE")"
  printf 'implement %s round %s route=%s status=%s reason=%s\n' "$step" "$round" "$1" "$st" "$why"
  case $st in
    done) rm -rf "$WT/.impl"; git clean -ffdXq
      printf 'implement.sh: done. Conductor: read the full diff (git status; git diff HEAD) before running anything from it, then re-run the bootstrap.\n'; exit 0 ;;
    escalate) patch_out "$1"; discard; printf 'implement.sh: escalated; read %s\n' "$EVID/escalation-$tag.md"; exit 5 ;;
    *) patch_out "$1"; discard; exit 1 ;; esac; }
unavail() { py row "$EVID" "$step" "$round" "$ps" "$tier" "$1" "$2" "$3" unavailable "$WHY" "$SID" "$TIN" "$TOUT" "$COST"
  printf 'implement %s round %s route=%s unavailable: %s\n' "$step" "$round" "$1" "$WHY" >&2; }
# Stop detection: the implementer owes .impl/result.json; a `<|tool_calls_cbegin|>` prompt delimiter in THIS turn's own
# assistant text means the model leaked a tool-call start token and the turn terminated early instead of working. Only the
# current turn's events file is read: the cumulative session export still holds an earlier turn's leak on a resume, and a
# tool output or a file the run read can quote the literal string.
resdone() { [ -f "$WT/.impl/result.json" ] && [ ! -L "$WT/.impl/result.json" ]; }
samehead() { [ "$(git -C "$WT" rev-parse HEAD)" = "$BASE" ]; }
leaked() { [ "$(py leak "$EVID/impl-$tag-$1.events")" = leak ]; }
UMSG="implement.sh: the implementer route is unavailable ($PINNED); no fallback model is permitted: log blocked external in PROGRESS.md, finish unaffected work, stop"
ds probe implementer-probe "Reply with OK only."
if [ "$KIND" = ok ]; then ds main implementer "Implement the attached brief exactly. Write .impl/result.json last, then stop." -f "$WT/.impl/brief.md"
  if [ "$KIND" = timeout ]; then outcome "$RT" "$DSM" "$RE" "$WHY"; fi
  if [ "$KIND" = ok ]; then LE=0; leaked main && LE=1; LK=$LE; resdone || LK=1
    # ONE bounded auto-resume in the same round, only while HEAD is intact, the deadline has time left, the session exists
    # and the run stayed under the 250K input-token ceiling. A second stop fails the round and counts as one strike.
    if [ "$LK" = 1 ] && samehead; then RSN="premature turn termination"; [ "$LE" = 0 ] || RSN="tool-call delimiter leak"
      REM=$((DEADLINE - (SECONDS - T0)))
      if [ "$SID" != - ] && [ "$TIN" -lt 250000 ] && [ "$REM" -gt 0 ]; then
        TMO=$REM; ds resume implementer "Resume and finish the brief. Write .impl/result.json last, then stop." --session "$SID"; TMO=$DEADLINE
        # The resume's own classification decides: unavailable stops the round at once (no failed or cost row), a timeout
        # keeps its reason, and only a verified turn is judged on its own events and .impl/result.json.
        if [ "$KIND" = unavailable ]; then unavail "$RT" "$DSM" "$RE"; patch_out "$RT"; discard; printf '%s\n' "$UMSG" >&2; exit 3; fi
        if [ "$KIND" = timeout ]; then outcome "$RT" "$DSM" "$RE" "$WHY"; fi
        if resdone && ! leaked resume; then outcome "$RT" "$DSM" "$RE" -; fi
        if [ "$LE" = 1 ] || leaked resume; then RSN="tool-call delimiter leak"; else RSN="premature turn termination"; fi
      fi
      outcome "$RT" "$DSM" "$RE" "$RSN"
    fi
    outcome "$RT" "$DSM" "$RE" -
  fi
  unavail "$RT" "$DSM" "$RE"; patch_out "$RT"; discard
else [ "$KIND" != timeout ] || WHY="probe $WHY"; unavail "$RT" "$DSM" "$RE"; fi
printf '%s\n' "$UMSG" >&2; exit 3
}
main "$@"; exit $?
