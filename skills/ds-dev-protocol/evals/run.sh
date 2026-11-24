#!/usr/bin/env bash
# run.sh - drive the ds-dev-protocol behaviour eval set: check, prepare, record, score.
# bash and zsh. Every command prints what it does; no model call happens here.
set -u
HERE=$(cd "$(dirname "$0")" && pwd -P)
SKILL=$(cd "$HERE/.." && pwd -P)
GATE=${DS_EVAL_GATE:-$SKILL/scripts/gate.sh}
STATE=${XDG_STATE_HOME:-$HOME/.local/state}
usage() {
  cat <<EOF
usage: evals/run.sh <command> [options]
  check                     verify inputs.sha256, then run fixture-check.sh
  prepare [--out-dir DIR] [--variant NAME] [--fixture ID]...
                            stage each fixture's src/ as a non-git work/ tree and its packet
                            as evid/ under DIR (default $STATE/dev-evidence/evals/<utc>);
                            exit 2 on hash drift or an out-dir inside a git repository
  record --evid DIR --tier T --record FILE --child-thread ID --parent-thread ID
         [--gate plan|review] [--diff FILE] [--trigger] [--force]
                            run scripts/gate.sh --record from that fixture's work/ and keep
                            its exit code 0|1|2|3|4; a fixture already at exit 0 or 1 is
                            skipped unless --force
  score [--run DIR] [--variant NAME] [--append-jsonl] [--allow-partial]
        [--fixture ID --record FILE]
                            score via score.py; --run defaults to the newest prepared run
DS_EVAL_GATE overrides the gate script for tests only; production is $SKILL/scripts/gate.sh.
EOF
}
die() { printf 'run.sh: %s\n' "$*" >&2; exit 2; }
hashes() { (cd "$HERE" && shasum -a 256 -c inputs.sha256 >/dev/null); }

check() {
  hashes || die "input hash drift: fixtures/ or keys.txt no longer match inputs.sha256"
  bash "$HERE/fixture-check.sh"
}

prepare() {
  out=$STATE/dev-evidence/evals/$(date -u +%Y%m%dT%H%M%SZ); variant=base; ids=""
  while [ $# -gt 0 ]; do case $1 in
    --out-dir|--variant|--fixture)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"
      case $1 in --out-dir) out=$2 ;; --variant) variant=$2 ;; --fixture) ids="$ids $2" ;; esac
      shift ;;
    *) die "unknown prepare argument: $1" ;;
  esac; shift; done
  probe=$out
  while [ ! -d "$probe" ]; do probe=$(dirname "$probe"); done
  root=$(git -C "$probe" rev-parse --show-toplevel 2>/dev/null || true)
  [ -z "$root" ] || die "--out-dir is inside the git repository $root; stage outside it"
  hashes || die "input hash drift: fixtures/ or keys.txt no longer match inputs.sha256"
  mkdir -p "$out" || die "cannot create $out"
  out=$(cd "$out" && pwd -P)
  manifest=$out/manifest.json
  printf '{"variant": "%s", "created": "%s", "fixtures": [' "$variant" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$manifest"
  first=1
  for id in $(printf '%s\n' ${ids:-$(cd "$HERE/fixtures" && ls)}); do
    meta=$(python3 -I -B -c 'import json, sys; m = json.load(open(sys.argv[1])); print(m["kind"], m["tier"], m["key"])' "$HERE/fixtures/$id/meta.json") \
      || die "cannot read fixtures/$id/meta.json"
    kind=${meta%% *}; rest=${meta#* }; tier=${rest%% *}; key=${rest#* }
    dir=$out/$variant-$id; work=$dir/work; evid=$dir/evid
    rm -rf "$dir"; mkdir -p "$work" "$evid" || die "cannot stage $dir"
    cp -R "$HERE/fixtures/$id/src/." "$work/" || die "cannot copy fixtures/$id/src"
    if [ "$kind" = plan ]; then
      cp "$HERE/fixtures/$id/facts.md" "$HERE/fixtures/$id/packet-plan.md" "$evid/" || die "cannot stage $id packet"
    else
      cp "$HERE/fixtures/$id/fixture.diff" "$HERE/fixtures/$id/packet-review.md" "$evid/" || die "cannot stage $id packet"
    fi
    git -C "$work" rev-parse --git-dir >/dev/null 2>&1 && die "$work is inside a git worktree; gate.sh needs a non-git tree"
    [ $first = 1 ] || printf ', ' >> "$manifest"; first=0
    printf '{"id": "%s", "kind": "%s", "tier": "%s", "key": "%s", "work": "%s", "evid": "%s"}' \
      "$id" "$kind" "$tier" "$key" "$work" "$evid" >> "$manifest"
    printf 'staged %s (%s, %s)\n' "$id" "$kind" "$tier"
  done
  printf ']}\n' >> "$manifest"
  printf 'manifest: %s\n' "$manifest"
}

record() {
  evid=""; tier=""; rec=""; child=""; parent=""; gate=""; diff=""; trigger=0; force=0
  while [ $# -gt 0 ]; do case $1 in
    --evid|--tier|--record|--child-thread|--parent-thread|--gate|--diff)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"
      case $1 in
        --evid) evid=$2 ;;
        --tier) tier=$2 ;;
        --record) rec=$2 ;;
        --child-thread) child=$2 ;;
        --parent-thread) parent=$2 ;;
        --gate) gate=$2 ;;
        --diff) diff=$2 ;;
      esac
      shift ;;
    --trigger) trigger=1 ;;
    --force) force=1 ;;
    *) die "unknown record argument: $1" ;;
  esac; shift; done
  [ -n "$evid" ] && [ -d "$evid" ] || die "--evid must name a staged evidence directory"
  [ -n "$tier" ] || die "--tier is required"
  [ -n "$rec" ] || die "--record is required"
  gate=${gate:-review}
  mark=$evid/exit
  if [ "$force" = 0 ] && [ -f "$mark" ] && grep -qE '^(0|1)$' "$mark"; then
    printf 'run.sh: %s already recorded at exit %s; pass --force to record again\n' "$evid" "$(cat "$mark")"
    return 0
  fi
  work=$(cd "$evid/.." && pwd -P)/work
  [ -d "$work" ] || die "no work/ next to $evid"
  set -- "$GATE" "$gate" "$tier" --record "$rec" --child-thread "$child" --parent-thread "$parent"
  [ -n "$diff" ] && set -- "$@" --diff "$diff"
  [ "$trigger" = 1 ] && set -- "$@" --trigger
  ( cd "$work" && EVID=$evid SKILL=$SKILL bash "$@" )
  rc=$?
  printf '%s\n' "$rc" > "$mark"
  [ "$rc" -le 4 ] || die "gate.sh returned $rc"
  return "$rc"
}

score() {
  asked=0
  for arg in "$@"; do case $arg in --run|--fixture) asked=1 ;; esac; done
  if [ "$asked" = 0 ]; then
    latest=$(ls -dt "$STATE"/dev-evidence/evals/*/ 2>/dev/null | head -1)
    [ -n "$latest" ] || die "no prepared run under $STATE/dev-evidence/evals/; pass --run DIR"
    python3 -I -B "$HERE/score.py" --run "${latest%/}" "$@"
  else
    python3 -I -B "$HERE/score.py" "$@"
  fi
}

cmd=${1:-}
[ $# -gt 0 ] && shift
case $cmd in
  --help|-h) usage; exit 0 ;;
  check) check "$@" ;;
  prepare) prepare "$@" ;;
  record) record "$@" ;;
  score) score "$@" ;;
  "") usage >&2; exit 2 ;;
  *) die "unknown command: $cmd" ;;
esac
exit $?
