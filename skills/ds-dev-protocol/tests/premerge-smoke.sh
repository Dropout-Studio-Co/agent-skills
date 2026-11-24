#!/usr/bin/env bash
# tests/premerge-smoke.sh - fakes-only tests for scripts/premerge-and-merge.sh and scripts/premerge_lib.py.
# Temp HOME/PATH, fake gh, local bare origin; no network.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P); PM=$ROOT/scripts/premerge-and-merge.sh
T=$(mktemp -d "${TMPDIR:-/tmp}/premerge-smoke.XXXXXX"); T=$(cd "$T" && pwd -P)
export T HOME="$T/home" XDG_STATE_HOME="$T/state" PATH="$T/bin:$PATH"
mkdir -p "$HOME" "$XDG_STATE_HOME" "$T/bin"; : > "$T/body.txt"; : > "$T/gh.head"; FAILED=0
trap 'rm -rf "$T"' EXIT
ok() { printf 'ok   premerge: %s\n' "$1"; }; bad() { printf 'FAIL premerge: %s\n' "$1"; FAILED=1; }
chk() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
cat > "$T/bin/gh" <<'FAKE'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$T/calls.log"
case "$1 $2" in
  "pr checks") [ -n "${FAKE_CHECKS_MSG:-}" ] && echo "$FAKE_CHECKS_MSG"; exit "${FAKE_CHECKS_EXIT:-0}" ;;
  "pr merge") exit 0 ;;
  "pr edit") while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$T/body.txt"; shift; done; exit 0 ;;
  "pr view") python3 -c 'import json,os,sys; t=sys.argv[1]; g=lambda p: open(t+"/"+p).read().strip() if os.path.exists(t+"/"+p) else ""; print(json.dumps({"headRefOid": g("gh.head"), "baseRefName": "main", "state": os.environ.get("FAKE_PR_STATE", "OPEN"), "body": g("body.txt")}))' "$T" ;;
esac
FAKE
chmod +x "$T/bin/gh"
unset GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM; export GIT_CONFIG_NOSYSTEM=1
git config --global user.email smoke@example.com; git config --global user.name Smoke; git config --global init.defaultBranch main
R=$T/repo; git init -q --bare "$T/origin.git"; git init -q "$R"; printf 'a\n' > "$R/f.txt"; git -C "$R" add f.txt
GIT_AUTHOR_DATE=2026-10-01T00:00:00Z GIT_COMMITTER_DATE=2026-10-01T00:00:00Z git -C "$R" commit -qm base
git -C "$R" remote add origin "$T/origin.git"; git -C "$R" push -q origin main; git -C "$R" remote set-head origin main
printf 'feat\n' > "$R/g.txt"; git -C "$R" add g.txt
GIT_AUTHOR_DATE=2026-11-20T00:00:00Z GIT_COMMITTER_DATE=2026-11-20T00:00:00Z git -C "$R" commit -qm feat
H=$(git -C "$R" rev-parse HEAD); B=$(git -C "$R" merge-base origin/main "$H"); TS=2026-11-11T00:00:00Z
new_ev() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; }
# gf EV GATE KEY [VERDICT] [FINDINGS] [TIER] [NONCE]: write a gate.sh-shaped JSON file and print its basename.
# NONCE changes the file bytes only, so a re-plan can overwrite plan-<key>.json with different provenance.
gf() { python3 - "$@" <<'PY'
import json, os, sys
ev, gate, key = sys.argv[1:4]
verdict = sys.argv[4] if len(sys.argv) > 4 else "pass"
findings = json.loads(sys.argv[5]) if len(sys.argv) > 5 else []
tier = sys.argv[6] if len(sys.argv) > 6 else "medium"
nonce = sys.argv[7] if len(sys.argv) > 7 else ""
if gate == "plan":
    out = {"gate": "plan", "tier": tier, "acceptance_criteria": ["a"], "design": "d", "files": ["g.txt"], "tests": ["t"], "risks": [], "rollback": "r"}
else:
    out = {"gate": gate, "head_sha": key, "verdict": verdict, "summary": "ok", "findings": findings}
name = "%s-%s.json" % (gate, key)
json.dump({"structured_output": out, "provenance": ({"nonce": nonce} if nonce else {})}, open(os.path.join(ev, name), "w"), indent=1, sort_keys=True)
print(name)
PY
}
# row EV GATE KEY TIER STATUS VERDICT FILE [k=v ...]: append a T3-verified row with the gate's route/effort defaults.
# Every row gets its own child session_id and a shared non-empty parent_thread_id (a child thread is never reused).
RS=0
row() { local a=("$@") n; n=$((RS + 1)); RS=$n
  python3 - "${a[@]:0:7}" "session_id=child-$n" "parent_thread_id=parent-1" "${a[@]:7}" <<'PY'
import hashlib, json, os, sys
ev, gate, key, tier, status, verdict, fname = sys.argv[1:8]
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
effort = {"plan": "medium" if tier == "low" else "high", "epoch": "medium" if tier == "medium" else "high"}.get(gate, "medium")
route, model, account = ("neon", "gemini-4-neon", "antigravity") if gate == "plan" else ("opus", "claude-opus-5-5", "claudeAgent")
if gate in ("security", "review") and (gate == "security" or tier == "high"): effort = "high"
d = {"ts": "2026-11-11T00:00:00Z", "gate": gate, "tier": tier, "round": 1, "key": key, "base_ref": "", "base_sha": "",
     "diff_sha256": "", "head_sha": key, "facts_sha256": "", "route": route, "model": model, "effort": effort,
     "session_id": "child-1", "parent_thread_id": "parent-1", "account": account, "input_tokens": 0, "output_tokens": 0,
     "cost_usd": 0, "verdict": verdict, "status": status, "reason": "", "file": fname, "file_sha256": "",
     "engine": "t3-delegate", "provenance_mode": "t3-verified"}
for kv in sys.argv[8:]:
    k, v = kv.split("=", 1)
    try: d[k] = json.loads(v)
    except ValueError: d[k] = v
p = os.path.join(ev, fname) if fname else ""
if p and os.path.isfile(p): d["file_sha256"] = sha(p)
open(os.path.join(ev, "gates.log"), "a").write(json.dumps(d) + "\n")
PY
}
rowb() { local ev=$1 gate=$2 key=$3 tier=$4 status=$5 verdict=$6 file=$7 bs ds; shift 7
  bs=$(git -C "$R" merge-base origin/main "$key"); ds=$(git -C "$R" diff --no-color --full-index "$bs" "$key" | shasum -a 256 | awk '{print $1}')
  row "$ev" "$gate" "$key" "$tier" "$status" "$verdict" "$file" "base_ref=origin/main" "base_sha=$bs" "diff_sha256=$ds" "$@"; }
setrow() { python3 - "$E/gates.log" "$1" "$2" "$3" <<'PY'
import json, sys
p, gate, field, value = sys.argv[1:5]
try: value = json.loads(value)
except ValueError: pass
out = []
for line in open(p):
    d = json.loads(line)
    if d.get("gate") == gate: d[field] = value
    out.append(json.dumps(d))
open(p, "w").write("\n".join(out) + "\n")
PY
}
delrows() { python3 - "$E/gates.log" "$1" <<'PY'
import json, sys
p, gate = sys.argv[1:3]
out = [json.loads(l) for l in open(p) if json.loads(l).get("gate") != gate]
open(p, "w").write("".join(json.dumps(d) + "\n" for d in out))
PY
}
# base_ev EV TIER KEY: facts, PLAN/tier re-check, plan row and review (plus security on High), all T3-verified.
base_ev() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; local fs fname
  printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  printf 'Tier: %s\n' "$2" > "$E/PLAN.md"; printf 'Tier: %s\n' "$2" > "$E/tier-recheck-$3.md"
  fname=$(gf "$E" plan "$fs" pass '[]' "$2"); row "$E" plan "$fs" "$2" ok pass "$fname" "facts_sha256=$fs"
  fname=$(gf "$E" review "$3" pass '[]' "$2"); rowb "$E" review "$3" "$2" ok pass "$fname"
  if [ "$2" = high ]; then fname=$(gf "$E" security "$3" pass '[]' high); rowb "$E" security "$3" high ok pass "$fname"; fi; }
pm_reset() { : > "$T/body.txt"; echo "$H" > "$T/gh.head"; : > "$T/calls.log"; }
pmrun() { ( cd "$2" && EVID="$1" bash "$PM" "${@:3}" >"$T/pm.out" 2>&1 ); PRC=$?; }
merged() { ! grep -qE 'pr (edit|merge)' "$T/calls.log"; }
# --- happy paths: Low, Medium, High, --diff, --no-ci
for tier in low medium high; do base_ev "happy-$tier" "$tier" "$H"; pm_reset; pmrun "$E" "$R" 1
  chk "happy $tier exit0+merge+block" bash -c "[ $PRC = 0 ] && grep -q 'pr merge 1 --squash --match-head-commit $H' '$T/calls.log' && ! grep -qE -- '--admin|--auto|--delete-branch' '$T/calls.log' && grep -q '<!-- premerge:start -->' '$T/body.txt' && grep -q '$H' '$T/body.txt'"
  chk "happy $tier wrote txt + merged row" bash -c "test -s '$E/premerge-$H.txt' && grep -q '\"status\": \"merged\"' '$E/gates.log'"; done
base_ev happy-medium medium "$H"; pm_reset; export FAKE_CHECKS_EXIT=1 FAKE_CHECKS_MSG="no checks reported on the 'b' branch"; pmrun "$E" "$R" 1 --no-ci
chk "--no-ci passes on a repo with no CI" bash -c "[ $PRC = 0 ] && grep -q 'CI: none (--no-ci)' '$T/body.txt'"; unset FAKE_CHECKS_EXIT FAKE_CHECKS_MSG
printf 'outside diff\n' > "$T/out.diff"; OK=$(shasum -a 256 "$T/out.diff" | awk '{print $1}'); new_ev outside
printf 'facts\n' > "$E/facts.md"; FS=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); printf 'Tier: low\n' > "$E/PLAN.md"; printf 'Tier: low\n' > "$E/tier-recheck-$OK.md"
f=$(gf "$E" plan "$FS" pass '[]' low); row "$E" plan "$FS" low ok pass "$f" "facts_sha256=$FS"
f=$(gf "$E" review "$OK" pass '[]' low); row "$E" review "$OK" low ok pass "$f"
: > "$T/calls.log"; pmrun "$E" "$R" --diff "$T/out.diff"
chk "--diff exit0 and no gh" bash -c "[ $PRC = 0 ] && [ ! -s '$T/calls.log' ] && test -s '$E/premerge-$OK.txt'"
# --- tier floor: PLAN.md and the re-check each need a Tier line; headings parse; lower fails
base_ev t-heading high "$H"; printf '# PLAN (x) - Tier: High\n' > "$E/PLAN.md"; printf 'Tier: High\n' > "$E/tier-recheck-$H.md"; pm_reset; pmrun "$E" "$R" 1
chk "Tier: High in a heading parses" test "$PRC" = 0
base_ev t-noplan medium "$H"; printf '# PLAN\n' > "$E/PLAN.md"; pm_reset; pmrun "$E" "$R" 1
chk "PLAN.md without a Tier line fails" bash -c "[ $PRC = 1 ] && grep -q 'each need a Tier line' '$T/pm.out'"
base_ev t-norecheck medium "$H"; printf '# recheck\n' > "$E/tier-recheck-$H.md"; pm_reset; pmrun "$E" "$R" 1
chk "tier re-check without a Tier line fails" bash -c "[ $PRC = 1 ] && grep -q 'each need a Tier line' '$T/pm.out'"
base_ev t-lowrecheck medium "$H"; printf 'Tier: low\n' > "$E/tier-recheck-$H.md"; pm_reset; pmrun "$E" "$R" 1
chk "lower re-check tier fails" bash -c "[ $PRC = 1 ] && grep -q 'lower than PLAN.md' '$T/pm.out'"
# --- rejections: facts and every provenance field, all tiers
refuse() { local n=$1 tier=$2 mut=$3 want=$4; base_ev "r-$n" "$tier" "$H"; pm_reset; eval "$mut"; pmrun "$E" "$R" 1
  chk "refuse:$n" bash -c "[ $PRC = 1 ] && grep -q '$want' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"; }
for tier in low medium high; do refuse "facts-$tier" "$tier" 'printf x >> "$E/facts.md"' 'does not match plan.facts_sha256'; done
for spec in 'route=opus' 'model=claude-opus-5-5' 'account=claudeAgent' 'session_id=parent-1' 'effort=medium'; do
  refuse "plan-${spec%%=*}" medium "setrow plan ${spec%%=*} ${spec#*=}" 'plan provenance'; done
for spec in 'route=deepseek-low' 'model=gemini-4-neon' 'account=antigravity' 'session_id=parent-1' 'effort=low'; do
  refuse "review-${spec%%=*}" medium "setrow review ${spec%%=*} ${spec#*=}" 'review provenance'; done
for spec in 'route=fallback' 'provenance_mode=provisional' 'effort=medium' 'model=claude-opus-4-8'; do
  refuse "security-${spec%%=*}" high "setrow security ${spec%%=*} ${spec#*=}" 'security provenance'; done
refuse plan-after-code medium 'setrow plan ts 2026-12-02T00:00:00Z' 'code before plan'
refuse plan-after-code-low low 'setrow plan ts 2026-12-02T00:00:00Z' 'code before plan'
refuse plan-after-code-high high 'setrow plan ts 2026-12-02T00:00:00Z' 'code before plan'
chk "plan-after-code says code before plan" grep -q 'code before plan' "$T/pm.out"
# forged EV: bare, provisional and stale HEAD-era plan rows dated before code must never set the chronology start.
forged_ev() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; local fs f
  printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  printf 'Tier: medium\n' > "$E/PLAN.md"; printf 'Tier: medium\n' > "$E/tier-recheck-$H.md"
  f=$(gf "$E" plan "$fs" pass '[]' medium)
  row "$E" plan "$fs" medium ok pass "" "ts=2026-10-01T00:00:00Z" "engine=" "head_sha=0000000000000000000000000000000000000000"
  row "$E" plan "$fs" medium ok pass "" "ts=2026-10-02T00:00:00Z" "provenance_mode=provisional"
  row "$E" plan "$fs" medium ok pass "plan-old.json" "ts=2026-10-03T00:00:00Z"
  row "$E" plan "$fs" medium ok pass "$f" "facts_sha256=$fs" "ts=2026-11-21T00:00:00Z"
  f=$(gf "$E" review "$H" pass '[]' medium); rowb "$E" review "$H" medium ok pass "$f" "ts=2026-11-22T00:00:00Z"; }
forged_ev r-forged-plan; pm_reset; pmrun "$E" "$R" 1
chk "refuse:unverified/HEAD-era plan rows never set the chronology" bash -c "[ $PRC = 1 ] && grep -q 'code before plan' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
base_ev r-code-after medium "$H"; pm_reset
printf '{"ts":"2026-11-11T00:00:00Z","step":"s","status":"start"}\n{"ts":"2026-11-20T00:00:00Z","step":"s","status":"done","route":"deepseek"}\n' > "$E/impl.log"
pmrun "$E" "$R" 1; chk "refuse:code-after-review" bash -c "[ $PRC = 1 ] && grep -q 'code after the gate' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
base_ev r-nosec high "$H"; delrows security; rm -f "$E"/security-*.json; pm_reset; pmrun "$E" "$R" 1
chk "refuse:missing security on High" bash -c "[ $PRC = 1 ] && grep -q 'missing passing security' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
base_ev r-baseref medium "$H"; setrow review base_ref origin/other; pm_reset; pmrun "$E" "$R" 1
chk "refuse:wrong base_ref binding" bash -c "[ $PRC = 1 ] && grep -q 'bound to a partial or different diff' '$T/pm.out'"
base_ev r-lowtier medium "$H"; setrow review tier low; pm_reset; pmrun "$E" "$R" 1
chk "refuse:gate tier below the task tier" bash -c "[ $PRC = 1 ] && grep -q 'row tier' '$T/pm.out'"
# --- child-thread identity: duplicate session_id and empty parent_thread_id are refused ---
base_ev r-dupses medium "$H"; PSID=$(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).readline())["session_id"])' "$E/gates.log")
setrow review session_id "$PSID"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:duplicate session_id" bash -c "[ $PRC = 1 ] && grep -q 'reuses the child session' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
base_ev r-emptypar medium "$H"; setrow review parent_thread_id ""; pm_reset; pmrun "$E" "$R" 1
chk "refuse:empty parent_thread_id" bash -c "[ $PRC = 1 ] && grep -q 'is not a child thread run' '$T/pm.out'"
# --- a later fail at the same head beats an earlier pass on that head ---
base_ev r-flip medium "$H"; f=$(gf "$E" review "$H" fail '[]' medium); rowb "$E" review "$H" medium ok fail "$f"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:later fail after an earlier pass on HEAD" bash -c "[ $PRC = 1 ] && grep -q 'is missing, failing, or has an important finding' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
# --- rounds and last-status: 3 since plan, 6 total, a blocked gate never merges ---
base_ev r-rounds3 medium "$H"; for i in 1 2 3; do f=$(gf "$E" review "$H" pass '[]' medium); rowb "$E" review "$H" medium ok pass "$f"; done; pm_reset; pmrun "$E" "$R" 1
chk "refuse:4 ok rounds since the plan" bash -c "[ $PRC = 1 ] && grep -q 'too many ok rounds' '$T/pm.out'"
base_ev r-rounds6 medium "$H"; for i in 1 2 3 4 5 6; do f=$(gf "$E" review "$H" pass '[]' medium); rowb "$E" review "$H" medium ok pass "$f"; done; pm_reset; pmrun "$E" "$R" 1
chk "refuse:7 ok rounds total" bash -c "[ $PRC = 1 ] && grep -q 'too many ok rounds' '$T/pm.out'"
base_ev r-blocked medium "$H"; row "$E" review "$H" medium blocked "" ""; pm_reset; pmrun "$E" "$R" 1
chk "refuse:last status blocked" bash -c "[ $PRC = 1 ] && grep -q 'blocked gate is logged' '$T/pm.out'"
# --- re-plan and epoch: chronology uses the first plan, so later plans still merge ---
replan_ev() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; local fs f t
  printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  printf 'Tier: medium\n' > "$E/PLAN.md"; printf 'Tier: medium\n' > "$E/tier-recheck-$H.md"
  f=$(gf "$E" plan "$fs" pass '[]' medium); row "$E" plan "$fs" medium ok pass "$f" "facts_sha256=$fs" "ts=2026-11-05T00:00:00Z"
  printf '{"ts": "2026-11-20T12:00:00Z", "route": "deepseek", "model": "opencode-go/deepseek-v4.1-flash", "effort": "high", "status": "done", "step": "s", "round": 1}\n' > "$E/impl.log"
  for t in 21 22 23; do f=$(gf "$E" review "$H" pass '[]' medium); rowb "$E" review "$H" medium ok pass "$f" "ts=2026-11-${t}T00:00:00Z"; done
  f=$(gf "$E" plan "$fs" pass '[]' medium replan); row "$E" plan "$fs" medium ok pass "$f" "facts_sha256=$fs" "ts=2026-11-24T00:00:00Z"
  f=$(gf "$E" review "$H" pass '[]' medium); rowb "$E" review "$H" medium ok pass "$f" "ts=2026-11-25T00:00:00Z"; }
replan_ev r-replan
chk "re-plan overwrote plan-<key>.json (plan 1 sha is stale)" bash -c "python3 -c 'import json,sys; p=[d for d in (json.loads(l) for l in open(sys.argv[1])) if d[\"gate\"]==\"plan\"]; sys.exit(0 if len(p)==2 and p[0][\"file_sha256\"]!=p[1][\"file_sha256\"] else 1)' '$E/gates.log'"
pm_reset; pmrun "$E" "$R" 1
chk "re-plan after 3 rounds passes code before plan" bash -c "[ $PRC = 0 ] && ! grep -q 'code before plan' '$T/pm.out'"
epoch_replan() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; local fs f
  printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  printf 'Tier: high\n' > "$E/PLAN.md"; printf 'Tier: high\n' > "$E/tier-recheck-$H.md"
  f=$(gf "$E" plan "$fs" pass '[]' high); row "$E" plan "$fs" high ok pass "$f" "facts_sha256=$fs" "ts=2026-11-05T00:00:00Z"
  printf '{"ts": "2026-11-20T12:00:00Z", "route": "deepseek", "model": "opencode-go/deepseek-v4.1-flash", "effort": "high", "status": "done", "step": "s", "round": 1}\n' > "$E/impl.log"
  f=$(gf "$E" epoch a pass '[]' high); row "$E" epoch a high ok pass "$f" "ts=2026-11-21T00:00:00Z"
  f=$(gf "$E" plan "$fs" pass '[]' high replan); row "$E" plan "$fs" high ok pass "$f" "facts_sha256=$fs" "ts=2026-11-22T00:00:00Z"
  f=$(gf "$E" review "$H" pass '[]' high); rowb "$E" review "$H" high ok pass "$f" "ts=2026-11-23T00:00:00Z"
  f=$(gf "$E" security "$H" pass '[]' high); rowb "$E" security "$H" high ok pass "$f" "ts=2026-11-24T00:00:00Z"; }
epoch_replan r-epochreplan; pm_reset; pmrun "$E" "$R" 1
chk "post-epoch re-plan passes code before plan" bash -c "[ $PRC = 0 ] && ! grep -q 'code before plan' '$T/pm.out'"
# --- a file-less ok plan row with full T3 provenance never sets the chronology start ---
fileless_ev() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; local fs f
  printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  printf 'Tier: medium\n' > "$E/PLAN.md"; printf 'Tier: medium\n' > "$E/tier-recheck-$H.md"
  row "$E" plan "$fs" medium ok pass "" "ts=2026-10-01T00:00:00Z"
  f=$(gf "$E" plan "$fs" pass '[]' medium); row "$E" plan "$fs" medium ok pass "$f" "facts_sha256=$fs" "ts=2026-11-21T00:00:00Z"
  f=$(gf "$E" review "$H" pass '[]' medium); rowb "$E" review "$H" medium ok pass "$f" "ts=2026-11-22T00:00:00Z"; }
fileless_ev r-fileless; pm_reset; pmrun "$E" "$R" 1
chk "refuse:file-less T3-verified plan row never sets the chronology" bash -c "[ $PRC = 1 ] && grep -q 'code before plan' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
# --- PR state and CI: head mismatch, failing checks, --no-ci three ways ---
base_ev r-headneq medium "$H"; pm_reset; echo deadbeef > "$T/gh.head"; pmrun "$E" "$R" 1
chk "refuse:PR head mismatch" bash -c "[ $PRC = 1 ] && grep -q 'is not OPEN at' '$T/pm.out' && ! grep -qE 'pr (edit|merge)' '$T/calls.log'"
base_ev r-checksfail medium "$H"; pm_reset; export FAKE_CHECKS_EXIT=1 FAKE_CHECKS_MSG="ci failed"; pmrun "$E" "$R" 1; unset FAKE_CHECKS_EXIT FAKE_CHECKS_MSG
chk "refuse:gh pr checks failing" bash -c "[ $PRC = 1 ] && grep -q 'gh pr checks not green' '$T/pm.out' && ! grep -qE 'pr (edit|merge)' '$T/calls.log'"
base_ev r-nociml medium "$H"; pm_reset; ML=$(printf "ci failed\nno checks reported on the 'b' branch"); export FAKE_CHECKS_EXIT=1 FAKE_CHECKS_MSG="$ML"; pmrun "$E" "$R" 1 --no-ci; unset FAKE_CHECKS_EXIT FAKE_CHECKS_MSG
chk "refuse:--no-ci multi-line message" bash -c "[ $PRC = 1 ] && ! grep -qE 'pr (edit|merge)' '$T/calls.log'"
O=$T/ci; git clone -q "$T/origin.git" "$O"; mkdir -p "$O/.github/workflows"; echo x > "$O/.github/workflows/ci.yml"; git -C "$O" add -A; git -C "$O" commit -qm ci; git -C "$O" push -q origin main
base_ev r-nocisub medium "$H"; mkdir -p "$R/sub"; pm_reset; export FAKE_CHECKS_EXIT=1 FAKE_CHECKS_MSG="no checks reported on the 'b' branch"; pmrun "$E" "$R/sub" 1 --no-ci; unset FAKE_CHECKS_EXIT FAKE_CHECKS_MSG
chk "refuse:--no-ci from a subdir sees origin workflows" bash -c "[ $PRC = 1 ] && ! grep -qE 'pr (edit|merge)' '$T/calls.log'"
git -C "$O" rm -rq .github; git -C "$O" commit -qm noci; git -C "$O" push -q origin main; rm -rf "$O"
base_ev r-nociwf medium "$H"; mkdir -p "$R/.github/workflows"; pm_reset; export FAKE_CHECKS_EXIT=1 FAKE_CHECKS_MSG="no checks reported"; pmrun "$E" "$R" 1 --no-ci; unset FAKE_CHECKS_EXIT FAKE_CHECKS_MSG
chk "refuse:--no-ci in a worktree with workflows" bash -c "[ $PRC = 1 ] && ! grep -qE 'pr (edit|merge)' '$T/calls.log'"; rm -rf "$R/.github"
# --- raised from Low: pass with the logged Low plan+review, fail without the Low review
R0=$R H0=$H; R=$T/raised; git clone -q "$T/origin.git" "$R"; printf 'r\n' > "$R/pr.txt"; git -C "$R" add pr.txt
GIT_AUTHOR_DATE=2026-11-01T00:00:00Z GIT_COMMITTER_DATE=2026-11-01T00:00:00Z git -C "$R" commit -qm pr
H=$(git -C "$R" rev-parse HEAD)
raised() { local n=$1 drop=${2:-}; E=$T/$n; rm -rf "$E"; mkdir -p "$E"; local fs f
  printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  printf 'Tier: medium\n' > "$E/PLAN.md"; printf 'Tier: medium\n' > "$E/tier-recheck-$H.md"
  # realistic chronology: low_plan <= first_code (2026-11-01) <= low_review <= raised_plan <= raised_review
  row "$E" plan "$fs" low ok pass "" "ts=2026-10-30T00:00:00Z"; row "$E" review "$H" low ok pass "" "ts=2026-11-02T00:00:00Z"
  [ "$drop" = lowreview ] && delrows review && row "$E" review "$H" low ok pass "" "ts=2026-11-15T00:00:00Z"
  f=$(gf "$E" plan "$fs" pass '[]' medium); row "$E" plan "$fs" medium ok pass "$f" "facts_sha256=$fs" "ts=2026-11-05T00:00:00Z"
  f=$(gf "$E" review "$H" pass '[]' medium); rowb "$E" review "$H" medium ok pass "$f" "ts=2026-11-10T00:00:00Z"; }
# lowts EV TS: move only the Low review row (a pre-code Low review is not a valid raised-from-Low excuse).
lowts() { python3 - "$E/gates.log" "$1" <<'PY'
import json, sys
p, ts = sys.argv[1:3]; out = []
for line in open(p):
    d = json.loads(line)
    if d.get("gate") == "review" and d.get("tier") == "low": d["ts"] = ts
    out.append(json.dumps(d))
open(p, "w").write("\n".join(out) + "\n")
PY
}
# barelow EV: forge bare Low rows (no T3 provenance); they must not excuse the chronology.
barelow() { python3 - "$E/gates.log" <<'PY'
import json, sys
p = sys.argv[1]; out = []
for line in open(p):
    d = json.loads(line)
    if d.get("tier") == "low": d.update(engine="", provenance_mode="", route="", model="", account="")
    out.append(json.dumps(d))
open(p, "w").write("\n".join(out) + "\n")
PY
}
raised raised-ok; pm_reset; pmrun "$E" "$R" 1
chk "raised-from-Low passes" bash -c "[ $PRC = 0 ] && grep -q 'raised from Low' '$T/pm.out'"
raised raised-no lowreview; pm_reset; pmrun "$E" "$R" 1
chk "raised-from-Low without the Low review fails" bash -c "[ $PRC = 1 ] && grep -q 'code before plan' '$T/pm.out'"
raised raised-pre; lowts 2026-10-31T00:00:00Z; pm_reset; pmrun "$E" "$R" 1
chk "refuse:pre-code Low review" bash -c "[ $PRC = 1 ] && grep -q 'code before plan' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
raised raised-forged; barelow; pm_reset; pmrun "$E" "$R" 1
chk "refuse:forged bare Low rows" bash -c "[ $PRC = 1 ] && grep -q 'code before plan' '$T/pm.out'"
R=$R0 H=$H0
# --- epoch integrity: denied, ceiling, missing fresh plan, missing file
epoch_case() { base_ev "$1" high "$H"; local f
  f=$(gf "$E" epoch a pass '[]' high); row "$E" epoch a high ok pass "$f"
  f=$(gf "$E" epoch b fail '[]' high); row "$E" epoch b high ok fail "$f"; }
epoch_case r-denied; pm_reset; pmrun "$E" "$R" 1
chk "refuse:denied epoch" bash -c "[ $PRC = 1 ] && grep -q 'denied epoch' '$T/pm.out'"
base_ev r-ceiling high "$H"; for k in a b c; do f=$(gf "$E" epoch "$k" pass '[]' high); row "$E" epoch "$k" high ok pass "$f"; done
pm_reset; pmrun "$E" "$R" 1; chk "refuse:epoch ceiling over 2" bash -c "[ $PRC = 1 ] && grep -q 'max 2 per task' '$T/pm.out'"
base_ev r-epfail high "$H"; f=$(gf "$E" epoch a fail '[]' high); row "$E" epoch a high ok pass "$f"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:epoch record verdict fail despite a pass row" bash -c "[ $PRC = 1 ] && grep -q 'epoch record is missing, failing, or has an important finding' '$T/pm.out'"
base_ev r-epimp high "$H"; f=$(gf "$E" epoch b pass '[{"severity":"important","location":"x:1","failure_scenario":"s","evidence":"e"}]' high); row "$E" epoch b high ok pass "$f"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:epoch record with an important finding" bash -c "[ $PRC = 1 ] && grep -q 'epoch record is missing, failing, or has an important finding' '$T/pm.out'"
E=$T/r-noresh; rm -rf "$E"; mkdir -p "$E"; printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
printf 'Tier: high\n' > "$E/PLAN.md"; printf 'Tier: high\n' > "$E/tier-recheck-$H.md"
f=$(gf "$E" plan "$fs" pass '[]' high); row "$E" plan "$fs" high ok pass "$f" "facts_sha256=$fs"
f=$(gf "$E" epoch a pass '[]' high); row "$E" epoch a high ok pass "$f"
f=$(gf "$E" review "$H" pass '[]' high); rowb "$E" review "$H" high ok pass "$f"
f=$(gf "$E" security "$H" pass '[]' high); rowb "$E" security "$H" high ok pass "$f"
pm_reset; pmrun "$E" "$R" 1; chk "refuse:missing fresh plan after epoch" bash -c "[ $PRC = 1 ] && grep -q 'predates the epoch reset' '$T/pm.out'"
# --- stray gate JSON and off-route / legacy impl rows
base_ev r-stray medium "$H"; printf '{}' > "$E/plan-other.json"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:stray gate JSON" bash -c "[ $PRC = 1 ] && grep -q 'not written by gate.sh: plan-other.json' '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
base_ev r-straycopy medium "$H"; cp "$E/review-$H.json" "$E/review-copy.json"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:gate file copied under a different basename" bash -c "[ $PRC = 1 ] && grep -q 'not written by gate.sh: review-copy.json' '$T/pm.out'"
base_ev r-impl medium "$H"; printf '{"route": "sonnet", "model": "claude-sonnet-5-5", "effort": "high", "status": "done"}\n' > "$E/impl.log"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:off-route impl.log" bash -c "[ $PRC = 1 ] && grep -q 'FAIL implementer log has an off-route row' '$T/pm.out'"
base_ev r-badts medium "$H"; printf '{"ts": "not-a-date", "route": "deepseek", "model": "opencode-go/deepseek-v4.1-flash", "effort": "high", "status": "done", "step": "s", "round": 1}\n' > "$E/impl.log"; pm_reset; pmrun "$E" "$R" 1
chk "refuse:unparseable done ts in impl.log" bash -c "[ $PRC = 1 ] && grep -q 'done implementation row has no parseable ts' '$T/pm.out'"
base_ev r-fallback medium "$H"; setrow review route provisional; pm_reset; pmrun "$E" "$R" 1
chk "refuse:legacy fallback/provisional route" bash -c "[ $PRC = 1 ] && grep -q 'review provenance' '$T/pm.out'"
# --- carry-forward: identical PR diff at a newer head carries; any diff change never does
advance_main() { git -C "$T/other" fetch -q origin main; git -C "$T/other" reset -q --hard origin/main; printf 'm\n' > "$T/other/$1"
  git -C "$T/other" add "$1"; git -C "$T/other" commit -qm "main $1"; git -C "$T/other" push -q origin main; }
git clone -q "$T/origin.git" "$T/other"
carry_case() { local n=$1 kind=${2:-} D=$T/$1 br=origin/main bs ds f fs x h; rm -rf "$D"; git clone -q "$T/origin.git" "$D"; printf 'pr\n' > "$D/pr.txt"
  git -C "$D" add pr.txt; git -C "$D" commit -qm pr; x=$(git -C "$D" rev-parse HEAD)
  if [ "$kind" = partial ]; then printf 'p0\n' > "$D/p0.txt"; git -C "$D" add p0.txt; git -C "$D" commit -qm p0; git -C "$D" update-ref refs/remotes/origin/tmp HEAD; br=origin/tmp; fi
  [ "$kind" = bin ] && printf 'a\000b' > "$D/bin.dat" && git -C "$D" add bin.dat && git -C "$D" commit -qm bin
  advance_main "$n.txt"; git -C "$D" fetch -q origin main; git -C "$D" merge -q -m merge origin/main
  h=$(git -C "$D" rev-parse HEAD); E=$T/$n-ev; rm -rf "$E"; mkdir -p "$E"
  printf 'facts\n' > "$E/facts.md"; fs=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  printf 'Tier: medium\n' > "$E/PLAN.md"; printf 'Tier: medium\n' > "$E/tier-recheck-$h.md"
  f=$(gf "$E" plan "$fs" pass '[]' medium); row "$E" plan "$fs" medium ok pass "$f" "facts_sha256=$fs"
  bs=$(git -C "$D" merge-base "$br" "$x"); ds=$(git -C "$D" diff --no-color --full-index "$bs" "$x" | shasum -a 256 | awk '{print $1}')
  f=$(gf "$E" review "$x" pass '[]' medium); row "$E" review "$x" medium ok pass "$f" "base_ref=$br" "base_sha=$bs" "diff_sha256=$ds"
  CASE_E=$E CASE_D=$D CASE_X=$x CASE_H=$h; }
carry_case carry; : > "$T/calls.log"; echo "$CASE_H" > "$T/gh.head"; pmrun "$CASE_E" "$CASE_D" 1
chk "carry exits 0, prints CARRY, logs carry" bash -c "[ $PRC = 0 ] && grep -q 'CARRY review $CASE_X -> $CASE_H' '$T/pm.out' && grep -q '\"status\": \"carry\"' '$CASE_E/gates.log' && [ ! -e '$CASE_E/review-$CASE_H.json' ]"
carry_case carry-change; D=$CASE_D; printf 'changed\n' > "$D/pr.txt"; git -C "$D" commit -qam ch; h=$(git -C "$D" rev-parse HEAD)
printf 'Tier: medium\n' > "$CASE_E/tier-recheck-$h.md"; echo "$h" > "$T/gh.head"; : > "$T/calls.log"; pmrun "$CASE_E" "$D" 1
chk "carry refused after a content change" bash -c "[ $PRC = 1 ] && ! grep -q CARRY '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
carry_case carry-ws; D=$CASE_D; printf 'pr  \n' > "$D/pr.txt"; git -C "$D" commit -qam ws; h=$(git -C "$D" rev-parse HEAD)
printf 'Tier: medium\n' > "$CASE_E/tier-recheck-$h.md"; echo "$h" > "$T/gh.head"; : > "$T/calls.log"; pmrun "$CASE_E" "$D" 1
chk "carry refused after a whitespace-only change" bash -c "[ $PRC = 1 ] && ! grep -q CARRY '$T/pm.out'"
carry_case carry-bin bin; D=$CASE_D; printf 'a\000c' > "$D/bin.dat"; git -C "$D" commit -qam bin; h=$(git -C "$D" rev-parse HEAD)
printf 'Tier: medium\n' > "$CASE_E/tier-recheck-$h.md"; echo "$h" > "$T/gh.head"; : > "$T/calls.log"; pmrun "$CASE_E" "$D" 1
chk "carry refused after a binary change" bash -c "[ $PRC = 1 ] && ! grep -q CARRY '$T/pm.out'"
carry_case carry-part partial; : > "$T/calls.log"; echo "$CASE_H" > "$T/gh.head"; pmrun "$CASE_E" "$CASE_D" 1
chk "carry refused for a partial-base source" bash -c "[ $PRC = 1 ] && ! grep -q CARRY '$T/pm.out' && [ \$(grep -cE 'pr (edit|merge)' '$T/calls.log') = 0 ]"
carry_case carry-fail; f=$(gf "$CASE_E" review "$CASE_X" fail '[]' medium); sh=$(shasum -a 256 "$CASE_E/$f" | awk '{print $1}')
setrow review verdict fail; setrow review file_sha256 "$sh"; echo "$CASE_H" > "$T/gh.head"; : > "$T/calls.log"; pmrun "$CASE_E" "$CASE_D" 1
chk "fail on the same diff blocks carry" bash -c "[ $PRC = 1 ] && grep -q 'failed on this exact diff' '$T/pm.out' && ! grep -q CARRY '$T/pm.out'"
printf '\n%s\n' "$([ $FAILED = 0 ] && echo 'PRE-MERGE TESTS PASSED' || echo 'PRE-MERGE TESTS FAILED')"
exit $FAILED
