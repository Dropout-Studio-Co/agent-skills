#!/usr/bin/env bash
# premerge-and-merge.sh - ds-dev-protocol pre-merge checks, PR body block and squash merge.
set -euo pipefail
usage() { cat <<'EOF'
usage: EVID=<dir> premerge-and-merge.sh <PR-number> [--no-ci]   (repo mode: checks, PR body block, squash merge;
         --no-ci only for a repo with no CI at all: no workflows and no checks reported)
       EVID=<dir> premerge-and-merge.sh --diff FILE   (outside mode: checks only, no gh)
exit: 0 all checks passed (and merged in repo mode), 1 a check failed (nothing merged), 2 usage
EOF
}
die() { printf 'premerge: %s\n' "$*" >&2; exit 2; }
if [ "${1:-}" = --help ]; then usage; exit 0; fi
[ -n "${EVID:-}" ] || die "EVID is unset"
[ -d "$EVID" ] || die "EVID is not a directory: $EVID"
SKILL=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd); LIB=$SKILL/scripts/premerge_lib.py
py() { python3 -I "$LIB" "$@"; }
mode=repo; pr=""; difffile=""; key=""
if [ "${1:-}" = --diff ]; then mode=diff; [ $# -eq 2 ] || { usage >&2; exit 2; }; difffile=$2
  [ -f "$difffile" ] || die "missing diff file: $difffile"; key=$(shasum -a 256 "$difffile" | awk '{print $1}')
else case ${1:-} in ''|*[!0-9]*) usage >&2; exit 2 ;; esac; pr=$1; noci=0
  if [ "${2:-}" = --no-ci ] && [ $# -eq 2 ]; then noci=1; elif [ $# -ne 1 ]; then usage >&2; exit 2; fi
  git rev-parse --git-dir >/dev/null 2>&1 || die "not a git worktree"; key=$(git rev-parse HEAD); fi
TMP=$(mktemp -d "${TMPDIR:-/tmp}/premerge.XXXXXX"); trap 'rm -rf "$TMP"' EXIT; out=$EVID/premerge-$key.txt; : > "$out"; FAILED=0
pass_() { printf 'PASS %s\n' "$1" | tee -a "$out"; }
fail_() { printf 'FAIL %s\n' "$1" | tee -a "$out"; FAILED=1; }
logrow() { printf '{"ts": "%s", "engine": "", "provenance_mode": "", "gate": "%s", "tier": "%s", "round": 0, "key": "%s", "route": "", "model": "", "effort": "", "session_id": "", "parent_thread_id": "", "account": "", "driver_kind": "", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "verdict": "", "status": "%s", "reason": "%s", "file": "", "file_sha256": "", "provider": "", "task_id": "%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$2" "${final:-}" "$3" "$1" "$4" "$(basename "$EVID")" >> "$EVID/gates.log"; }
base=""; prhead=""; prstate=""
if [ "$mode" = repo ]; then
  if git diff --quiet HEAD; then pass_ "clean tracked tree at $key"; else fail_ "tracked tree is dirty"; fi
  prinfo=$(gh pr view "$pr" --json headRefOid,baseRefName,state 2>>"$out") || prinfo=""
  read -r prhead base prstate <<< "$(printf '%s' "$prinfo" | python3 -I -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: d = {}
print(d.get("headRefOid", ""), d.get("baseRefName", ""), d.get("state", ""))')"
  if [ -n "$base" ]; then git fetch -q origin "$base" 2>>"$out" || fail_ "cannot fetch origin/$base"; else fail_ "cannot read PR base"; fi
fi
recheck=$EVID/tier-recheck-$key.md; if [ -s "$recheck" ]; then pass_ "found $(basename "$recheck")"; else fail_ "missing tier-recheck-$key.md"; fi
read -r final rt pt lower <<< "$(py tiers "$EVID/PLAN.md" "$recheck")"
if [ "$final" = none ]; then fail_ "PLAN.md and the tier re-check each need a Tier line (re-check: $rt, PLAN.md: $pt)"; else pass_ "final tier $final"; fi
if [ "$lower" = 1 ]; then fail_ "tier re-check ($rt) is lower than PLAN.md ($pt)"; else pass_ "tier re-check not below PLAN.md"; fi
if [ "$final" != none ]; then
  evout=$(py evidence "$EVID" "$key" "$final" "$base" "$mode") || { printf 'premerge: evidence check crashed; nothing merged\n' >&2; exit 1; }
  while IFS= read -r line; do case $line in
    "PASS "*) pass_ "${line#PASS }" ;;
    "FAIL "*) fail_ "${line#FAIL }" ;;
    *) if [ -n "$line" ]; then printf '%s\n' "$line" | tee -a "$out"; fi ;;
  esac; done <<< "$evout"
fi
if bash "$(dirname "${BASH_SOURCE[0]}")/implement.sh" --check >>"$out" 2>&1; then pass_ "implementer log: pinned routes only"; else fail_ "implementer log has an off-route row"; fi
[ "$FAILED" = 0 ] || { printf 'premerge: checks failed; nothing merged\n' >&2; exit 1; }
if [ "$mode" = diff ]; then printf 'premerge: checks passed; wrote premerge-%s.txt\n' "$key"; exit 0; fi
if [ "$prstate" = OPEN ] && [ "$prhead" = "$key" ]; then pass_ "PR $pr is OPEN at $key"; else fail_ "PR $pr is not OPEN at $key (head $prhead)"; fi
if [ "$FAILED" = 0 ]; then ck=0; ckout=$(gh pr checks "$pr" 2>&1) || ck=$?
  if [ "$ck" = 0 ]; then pass_ "gh pr checks green"; elif [ "$noci" = 1 ] && [ "$(printf '%s\n' "$ckout" | grep -c .)" = 1 ] && printf '%s' "$ckout" | grep -Eq "^no checks reported on the '.*' branch$" && [ ! -d "$(git rev-parse --show-toplevel)/.github/workflows" ] && [ -z "$(git ls-tree --full-tree "origin/$base" .github/workflows 2>/dev/null)" ]; then pass_ "CI: none (--no-ci)"; else printf '%s\n' "$ckout" >> "$out"; fail_ "gh pr checks not green (exit $ck)"; fi; fi
[ "$FAILED" = 0 ] || exit 1
body=$(gh pr view "$pr" --json body 2>/dev/null | python3 -I -c 'import json,sys
try: print(json.load(sys.stdin).get("body", ""))
except Exception: print("")')
printf '%s' "$body" > "$TMP/body.md"
python3 -I - "$TMP/body.md" "$out" "$key" "$TMP/newbody.md" <<'PY'
import os, sys
src, checks, head, dst = sys.argv[1:5]
body = open(src).read() if os.path.exists(src) else ""
block = "<!-- premerge:start -->\n```\n%s\n```\nhead: %s\n<!-- premerge:end -->" % (open(checks).read().strip(), head)
a, b = "<!-- premerge:start -->", "<!-- premerge:end -->"
if a in body and b in body: body = body[:body.index(a)] + block + body[body.index(b) + len(b):]
else: body = (body.rstrip() + "\n\n" + block + "\n") if body.strip() else block + "\n"
open(dst, "w").write(body)
PY
if gh pr edit "$pr" --body-file "$TMP/newbody.md" 2>>"$out"; then pass_ "PR body updated with premerge block"; else fail_ "gh pr edit failed"; exit 1; fi
if gh pr view "$pr" --json body 2>/dev/null | python3 -I -c 'import re,sys
m = re.search(r"<!-- premerge:start -->(.*?)<!-- premerge:end -->", sys.stdin.read(), re.S)
sys.exit(0 if m and sys.argv[1] in m.group(1) else 1)' "$key"; then pass_ "PR body block contains $key"; else fail_ "PR body block missing $key"; exit 1; fi
if gh pr merge "$pr" --squash --match-head-commit "$key" 2>>"$out"; then pass_ "merged PR $pr at $key"; logrow merged "" "$key" "squash merge"; else fail_ "gh pr merge failed"; exit 1; fi
exit 0
