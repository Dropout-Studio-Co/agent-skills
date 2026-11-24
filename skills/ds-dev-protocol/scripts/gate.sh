#!/usr/bin/env bash
# gate.sh - record one ds-dev-protocol gate round with T3-verified provenance.
set -euo pipefail
usage() { cat <<'EOF'
usage: EVID=<dir> gate.sh <plan|review|security|epoch> <low|medium|high>
         --record <json-file> --child-thread <id> --parent-thread <id>
         [--trigger] [--diff FILE] [--base REF]
  plan: key = sha256(EVID/facts.md); thought_level medium on low tier, high on medium/high
  review: key = HEAD or sha256(--diff FILE); effort medium, high on high tier or --trigger
  security: key = HEAD or sha256(--diff FILE); high tier only; effort high
  epoch: key = sha256(EVID/epoch.md); after a round-cap block; max 2 authorized per EVID
exit: 0 pass (or valid plan), 1 verdict fail, 2 usage/precondition/provenance/tree mismatch, 3 blocked, 4 round cap
EOF
}
die() { printf 'gate.sh: %s\n' "$*" >&2; exit 2; }
sha() { shasum -a 256 "$1" | awk '{print $1}'; }
if [ "${1:-}" = --help ]; then usage; exit 0; fi
[ -n "${EVID:-}" ] && [ -d "$EVID" ] || die "EVID must name an existing directory"
[ $# -ge 2 ] || { usage >&2; exit 2; }
SKILL=${SKILL:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
LIB=$SKILL/scripts/gate_lib.py
gate=$1; tier=$2; shift 2
key=""
refuse() { python3 -I "$LIB" --log-invalid --evid "$EVID" --gate "$gate" --tier "$tier" --key "${key:-}" --reason "$*" >/dev/null 2>&1 || true; die "$*"; }
record=""; child=""; parent=""; trigger=0; diff=""; base=""
while [ $# -gt 0 ]; do case $1 in
  --record|--child-thread|--parent-thread|--diff|--base)
    [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"
    case $1 in --record) record=$2 ;; --child-thread) child=$2 ;; --parent-thread) parent=$2 ;; --diff) diff=$2 ;; --base) base=$2 ;; esac
    shift ;;
  --trigger) trigger=1 ;;
  *) die "unknown argument: $1" ;;
esac; shift; done
case $gate in plan|review|security|epoch) ;; *) die "bad gate: $gate" ;; esac
case $tier in low|medium|high) ;; *) die "bad tier: $tier" ;; esac
[ -n "$record" ] || die "--record is required"
[ -f "$record" ] || die "missing record file: $record"
if printf '%s' "$(basename "$record")" | grep -Eq '^(plan|review|security|epoch)-.*\.json$'; then die "--record must not be a gate output file: $(basename "$record")"; fi
[ -n "$child" ] || die "--child-thread is required"
[ -n "$parent" ] || die "--parent-thread is required"
if [ "$tier" = low ] && { [ "$gate" = security ] || [ "$gate" = epoch ]; }; then die "low tier is not valid with $gate"; fi
if [ "$gate" = security ] && [ "$tier" != high ]; then die "security gate requires tier high"; fi
if [ "$gate" = plan ] && [ -n "$diff${base:-}" ]; then die "plan reads EVID/facts.md; no --diff or --base"; fi
if [ "$gate" = epoch ] && [ -n "$diff${base:-}" ]; then die "epoch reads EVID/epoch.md; no --diff or --base"; fi
repo=0; git rev-parse --git-dir >/dev/null 2>&1 && repo=1 || true
reponame=outside; head=""; base_ref=""; mb=""; dsha=""; repocheck=0
tmpd=$(mktemp -d "${TMPDIR:-/tmp}/gate.XXXXXX"); trap 'rm -rf "$tmpd"' EXIT; want=$tmpd/source
if [ "$gate" = plan ]; then
  [ -s "$EVID/facts.md" ] || die "missing $EVID/facts.md"; key=$(sha "$EVID/facts.md"); cp "$EVID/facts.md" "$want"
elif [ "$gate" = epoch ]; then
  [ -s "$EVID/epoch.md" ] || die "missing $EVID/epoch.md"; key=$(sha "$EVID/epoch.md"); cp "$EVID/epoch.md" "$want"
elif [ -n "$diff" ]; then
  [ -f "$diff" ] || die "missing diff file: $diff"; key=$(sha "$diff"); cp "$diff" "$want"
else
  [ "$repo" = 1 ] || die "not a git worktree"
  key=$(git rev-parse HEAD)
  base_ref=${base:-$(git symbolic-ref -q --short refs/remotes/origin/HEAD || echo origin/main)}
  printf '%s' "$base_ref" | grep -Eq '^origin/[A-Za-z0-9._/-]+$' || refuse "--base must be an origin/<branch> ref: $base_ref"
  mb=$(git merge-base "$base_ref" HEAD) || refuse "no merge-base with $base_ref"
  git diff --no-color "$mb" HEAD > "$want"; [ -s "$want" ] || refuse "empty diff against $base_ref"
  dsha=$(git diff --no-color --full-index "$mb" HEAD | shasum -a 256 | awk '{print $1}')
  git -c core.quotePath=false diff --name-only -z "$mb" HEAD | tr '\0' '\n' > "$tmpd/names"
  if grep -Eiq '(^|/)(opencode\.jsonc?$|\.opencode/|\.claude/|\.agents/|AGENTS\.md$|CLAUDE\.md$)' "$tmpd/names"; then
    [ "$tier" = low ] && refuse "agent config changed: tier must be at least medium"
  fi
  python3 -I - "$mb" <<'PY' || refuse "a text file reads as 'Binary files differ' (.gitattributes -diff/binary); drop the attribute before gating"
import subprocess, sys
def blob(rev, path):
    out = subprocess.run(["git", "cat-file", "blob", rev + ":" + path], capture_output=True)
    return out.stdout[:8000] if out.returncode == 0 else None
for entry in subprocess.run(["git", "diff", "--no-renames", "--numstat", "-z", sys.argv[1], "HEAD"], capture_output=True, check=True).stdout.split(b"\0"):
    if entry.startswith(b"-\t-\t"):
        path = entry[4:].decode("utf-8", "surrogateescape")
        sides = [side for side in (blob(sys.argv[1], path), blob("HEAD", path)) if side is not None]
        if sides and all(b"\0" not in side for side in sides):
            sys.exit(1)
PY
fi
if { [ "$gate" = plan ] || [ "$gate" = epoch ]; } && [ "$repo" = 1 ]; then repocheck=1; fi
if { [ "$gate" = review ] || [ "$gate" = security ]; } && [ -z "$diff" ]; then repocheck=1; fi
if [ "$repocheck" = 1 ]; then
  reponame=$(basename "$(git rev-parse --show-toplevel)")
  head=$(git rev-parse HEAD)
  if [ "$gate" = review ] || [ "$gate" = security ]; then head=$key; fi
  [ -z "$(git status --porcelain --untracked-files=all)" ] || refuse "worktree is dirty or has untracked files; a gate must run on a clean tree"
fi
packet=$EVID/packet-$gate.md
[ -s "$packet" ] || refuse "missing $packet"
python3 -I - "$packet" "$gate" "$key" "$want" "$mb" "$tier" "$head" <<'PY' || refuse "packet must bind the key, 'Gate: $gate', 'Tier: $tier', the merge-base, the HEAD and the exact gate source"
import sys
path, gate, key, source, base, tier, head = sys.argv[1:8]
text = open(path, encoding="utf-8", errors="replace").read()
body = open(source, encoding="utf-8", errors="replace").read().strip()
ok = bool(body) and key in text and "Gate: " + gate in text and "Tier: " + tier in text and body in text
if gate in ("review", "security") and base:
    ok = ok and base in text
if gate in ("plan", "epoch") and len(head) == 40:
    ok = ok and head in text
sys.exit(0 if ok else 1)
PY
fsha=""
if [ -f "$EVID/facts.md" ]; then fsha=$(sha "$EVID/facts.md"); fi
rc=0
python3 -I "$SKILL/scripts/gate_lib.py" --evid "$EVID" --gate "$gate" --tier "$tier" \
  --record "$record" --child-thread "$child" --parent-thread "$parent" --trigger "$trigger" \
  --key "$key" --expected-head "$head" --facts-sha "$fsha" --base-ref "$base_ref" --base-sha "$mb" \
  --diff-sha "$dsha" --repo "$reponame" --skill "$SKILL" || rc=$?
exit "$rc"
