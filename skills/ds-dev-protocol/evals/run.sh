#!/usr/bin/env bash
# run.sh - drive the ds-dev-protocol behaviour eval set: check, prepare, record, score (bash and
# zsh; every command prints what it does, and no model call happens here).
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
                            exit 2 on hash drift or an out-dir inside a git repository or the skill directory
  record --evid DIR --tier T --record FILE --child-thread ID --parent-thread ID
         [--gate plan|review] [--diff FILE] [--high-effort TAGS] [--trigger] [--force]
                            run scripts/gate.sh --record from that fixture's work/ and keep
                            its exit 0|1|2|3|4; one at 0 or 1 is skipped unless --force; --diff
                            defaults to evid/fixture.diff when omitted
  score [--run DIR] [--variant NAME] [--append-jsonl] [--allow-partial] [--fixture ID]
        [--record FILE]     score via score.py; --run defaults to the newest prepared run
--variant and --fixture names must match [A-Za-z0-9._-]+.
DS_EVAL_GATE overrides the gate script for tests only; production is $SKILL/scripts/gate.sh.
EOF
}
die() { printf 'run.sh: %s\n' "$*" >&2; exit 2; }
idcheck() { case $1 in ""|*[!A-Za-z0-9._-]*) die "bad --variant/--fixture name (allowed: A-Za-z0-9._-): $1" ;; esac; }
abs() { d=$(dirname -- "$1"); [ -d "$d" ] || { printf '%s/%s\n' "$PWD" "$1"; return; }
  printf '%s/%s\n' "$(cd "$d" && pwd -P)" "$(basename -- "$1")"; }
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
      case $1 in --out-dir) out=$2 ;; --variant) variant=$2; idcheck "$2" ;; --fixture) ids="$ids $2"; idcheck "$2" ;; esac
      shift ;;
    *) die "unknown prepare argument: $1" ;;
  esac; shift; done
  real=$(python3 -I -B -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$out") || die "cannot resolve $out"
  probe=$real; while [ ! -d "$probe" ]; do probe=$(dirname "$probe"); done
  root=$(git -C "$probe" rev-parse --show-toplevel 2>/dev/null || true)
  [ -z "$root" ] || die "--out-dir is inside the git repository $root; stage outside it"
  case $real in "$SKILL"|"$SKILL"/*) die "--out-dir is inside the skill directory $SKILL; stage outside it" ;; esac
  hashes || die "input hash drift: fixtures/ or keys.txt no longer match inputs.sha256"
  mkdir -p "$real" || die "cannot create $real"
  out=$real
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
  evid=""; tier=""; rec=""; child=""; parent=""; gate=""; diff=""; high_effort=""; trigger=0; force=0
  while [ $# -gt 0 ]; do case $1 in
    --evid|--tier|--record|--child-thread|--parent-thread|--gate|--diff|--high-effort)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"
      case $1 in --evid) evid=$2 ;; --tier) tier=$2 ;; --record) rec=$2 ;; --gate) gate=$2 ;;
        --child-thread) child=$2 ;; --parent-thread) parent=$2 ;; --diff) diff=$2 ;; --high-effort) high_effort=${high_effort:+$high_effort,}$2 ;; esac
      shift ;;
    --trigger) trigger=1 ;;
    --force) force=1 ;;
    *) die "unknown record argument: $1" ;;
  esac; shift; done
  [ -n "$evid" ] && [ -d "$evid" ] || die "--evid must name a staged evidence directory"
  [ -n "$tier" ] || die "--tier is required"
  [ -n "$rec" ] || die "--record is required"
  gate=${gate:-review}
  evid=$(abs "$evid"); rec=$(abs "$rec"); [ -n "$diff" ] && diff=$(abs "$diff")
  if [ -z "$diff" ] && [ "$gate" != plan ] && [ -f "$evid/fixture.diff" ]; then diff=$evid/fixture.diff; fi
  if [ "$force" = 0 ] && [ -f "$evid/exit" ] && grep -qE '^(0|1)$' "$evid/exit"; then
    printf 'run.sh: %s already recorded at exit %s; pass --force to record again\n' "$evid" "$(cat "$evid/exit")"
    return 0
  fi
  work=$(cd "$evid/.." && pwd -P)/work
  [ -d "$work" ] || die "no work/ next to $evid"
  set -- "$GATE" "$gate" "$tier" --record "$rec" --child-thread "$child" --parent-thread "$parent"
  [ -n "$diff" ] && set -- "$@" --diff "$diff"; [ "$trigger" = 1 ] && set -- "$@" --trigger; [ -n "$high_effort" ] && set -- "$@" --high-effort "$high_effort"
  ( cd "$work" && EVID=$evid SKILL=$SKILL XDG_STATE_HOME=$evid/state bash "$@" )
  rc=$?
  printf '%s\n' "$rc" > "$evid/exit"
  [ "$rc" -le 4 ] || die "gate.sh returned $rc"
  return "$rc"
}

score() {
  asked=0; prev=""
  for arg in "$@"; do
    case $prev in --variant|--fixture) idcheck "$arg" ;; esac
    case $arg in --variant=*|--fixture=*) idcheck "${arg#*=}" ;; esac
    case $arg in --run|--fixture) asked=1 ;; esac
    prev=$arg
  done
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
