#!/usr/bin/env bash
# build-packet.sh - atomically assemble EVID/packet-<gate>.md for gate.sh --record (no model, no network).
set -euo pipefail
usage() { cat <<'EOF'
usage: EVID=<dir> build-packet.sh <plan|review|security|epoch> <low|medium|high> [--ui] [--base REF] [--diff FILE]
  plan/epoch: body EVID/facts.md or EVID/epoch.md
  review/security: git diff against origin/<base> (default origin/HEAD or origin/main), or --diff FILE
  writes EVID/packet-<gate>.md; gate.sh binds its key, Gate:, Tier:, merge-base, HEAD and exact source
EOF
}
die() { printf 'build-packet: %s\n' "$*" >&2; exit 2; }
[ "${1:-}" = --help ] && { usage; exit 0; }
[ -n "${EVID:-}" ] && [ -d "$EVID" ] || die "EVID must name an existing directory"
[ $# -ge 2 ] || { usage >&2; exit 2; }
gate=$1 tier=$2; shift 2
case $gate in plan|review|security|epoch) ;; *) die "bad gate: $gate" ;; esac
case $tier in low|medium|high) ;; *) die "bad tier: $tier" ;; esac
ui=0 base="" diff=""
while [ $# -gt 0 ]; do case $1 in
  --ui) ui=1 ;;
  --base|--diff) [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"; if [ "$1" = --base ]; then base=$2; else diff=$2; fi; shift ;;
  *) die "unknown argument: $1" ;;
esac; shift; done
[ "$ui" = 1 ] && case $gate in plan|review) ;; *) die "--ui is valid on plan and review only" ;; esac
[ "$gate" = security ] && [ "$tier" != high ] && die "security gate requires tier high"
{ [ "$gate" = security ] || [ "$gate" = epoch ]; } && [ "$tier" = low ] && die "low tier is not valid with $gate"
case $gate in plan|epoch) [ -z "$diff$base" ] || die "$gate reads EVID/facts.md or EVID/epoch.md; no --diff or --base" ;; esac
repo=0; git rev-parse --git-dir >/dev/null 2>&1 && repo=1
top=""; [ "$repo" = 0 ] || top=$(git rev-parse --show-toplevel)
sha() { shasum -a 256 "$1" | awk '{print $1}'; }
head=""; base_ref=""; mb=""
tmp=$(mktemp "$EVID/.packet-$gate.XXXXXX"); trap 'rm -f "$tmp" "$tmp.diff"' EXIT
{
  printf 'Gate: %s\nTier: %s\n' "$gate" "$tier"
  [ "$ui" = 0 ] || printf 'Scope: ui\n'
  if [ "$gate" = plan ]; then [ -s "$EVID/facts.md" ] || die "missing $EVID/facts.md"; body=$EVID/facts.md
  elif [ "$gate" = epoch ]; then [ -s "$EVID/epoch.md" ] || die "missing $EVID/epoch.md"; body=$EVID/epoch.md
  elif [ -n "$diff" ]; then [ -s "$diff" ] || die "missing diff file: $diff"; body=$diff
  else
    [ "$repo" = 1 ] || die "review/security need a git worktree or --diff"
    base_ref=${base:-$(git symbolic-ref -q --short refs/remotes/origin/HEAD || echo origin/main)}
    printf '%s' "$base_ref" | grep -Eq '^origin/[A-Za-z0-9._/-]+$' || die "--base must be an origin/<branch> ref: $base_ref"
    mb=$(git merge-base "$base_ref" HEAD) || die "no merge-base with $base_ref"
    git diff --no-color "$mb" HEAD > "$tmp.diff" || die "cannot diff against $base_ref"
    [ -s "$tmp.diff" ] || die "empty diff against $base_ref"
    body=$tmp.diff
  fi
  [ "$repo" = 0 ] || head=$(git rev-parse HEAD)
  key=$(sha "$body"); [ -z "$base_ref" ] || key=$head
  printf 'key: %s\n' "$key"
  [ -z "$head" ] || printf 'head: %s\n' "$head"
  [ -z "$base_ref" ] || printf 'base_ref: %s\nbase: %s\n' "$base_ref" "$mb"
  cat "$body"
} > "$tmp"
if [ "$repo" = 1 ] && { [ "$gate" = review ] || [ "$gate" = security ]; } && [ -z "$diff" ]; then
  if [ -f "$top/REVIEW.md" ] && [ ! -L "$top/REVIEW.md" ] && [ -s "$top/REVIEW.md" ]; then
    { printf '\n## REVIEW.md\n'; cat "$top/REVIEW.md"; } >> "$tmp"
  fi
  if [ -n "$base_ref" ] && command -v trail >/dev/null 2>&1; then
    if blast=$(trail blast --no-owners --base "$base_ref" 2>/dev/null) && [ -n "$blast" ]; then
      printf '\n## Trail blast\n%s\n' "$blast" >> "$tmp"
    fi
  fi
fi
mv -f "$tmp" "$EVID/packet-$gate.md"
