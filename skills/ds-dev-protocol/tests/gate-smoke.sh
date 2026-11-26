#!/usr/bin/env bash
# tests/gate-smoke.sh - fakes-only tests for scripts/gate.sh --record (T3-verified provenance); a fake ACP node
# stands in for `ELECTRON_RUN_AS_NODE=1 $T3_ACP_MCP_NODE acp-mcp-call <tool> <json>`; temp HOME/PATH, no network.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P); GATE=$ROOT/scripts/gate.sh
rt() { python3 -I "$ROOT/scripts/routing_lib.py" "$@"; }
IFS=$'\t' read -r NP NR NM NO NDK <<< "$(rt gate-tsv plan)"; IFS=$'\t' read -r OP OR OM OO ODK <<< "$(rt gate-tsv review)"
NEON_ALL=(neon-a neon-b neon-c); NEON_ACCT=${NEON_ALL[0]}; OPUS_ALL=("${NEON_ALL[@]}"); OPUS_ACCT=$NEON_ACCT
export DEF_MODEL="$OM" DEF_INSTANCE="$OPUS_ACCT" DEF_OPTION="$OO" OR OM OPUS_ACCT
caps() { python3 - "$@" <<'PY'
import json, sys
out = []
for spec in sys.argv[1:]:
    parts = spec.split("|"); model, dk, inst = parts[:3]
    out.append({"providerInstanceId": inst, "driverKind": dk, "canRunChildTask": parts[3] != "0" if len(parts) > 3 else True, "models": [{"id": model}]})
print(json.dumps({"providers": out}))
PY
}
export CAPS=$(caps "$NM|$NDK|${NEON_ALL[0]}" "$NM|$NDK|${NEON_ALL[1]}" "$NM|$NDK|${NEON_ALL[2]}")
EH=$(rt effort epoch high); EM=$(rt effort epoch medium)
T=$(mktemp -d "${TMPDIR:-/tmp}/gate-smoke.XXXXXX"); T=$(cd "$T" && pwd -P)
export T HOME="$T/home" XDG_STATE_HOME="$T/state" PATH="$T/bin:$PATH"
mkdir -p "$HOME" "$XDG_STATE_HOME" "$T/bin"; FAILED=0
trap 'rm -rf "$T"' EXIT
ok() { printf 'ok   gate: %s\n' "$1"; }; bad() { printf 'FAIL gate: %s\n' "$1"; FAILED=1; }
chk() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
cat > "$T/bin/acp-node" <<'FAKE'
#!/usr/bin/env python3
# Fake T3 ACP node: `acp-mcp-call <tool> <json>` prints T3's real result envelope.
import json, os, sys
a = sys.argv[1:]
if a and a[0] == "acp-mcp-call": a = a[1:]
tool = a[0] if a else ""
try: req = json.loads(a[1]) if len(a) > 1 else {}
except ValueError: req = {}
open(os.path.join(os.environ["T"], "t3.calls"), "a").write(tool + "\n")
E = lambda k, d="": os.environ.get(k, d)
def record():
    p = E("FAKE_RECORD")
    if not p: return None
    d = json.load(open(p))
    if isinstance(d, dict) and isinstance(d.get("structured_output"), dict): return d["structured_output"]
    return d
def submit(item, rec): return {"type": "dynamic_tool", "itemId": item, "status": "completed", "text": json.dumps({"toolName": "t3_submit_output", "input": {"json": json.dumps(rec)}})}
def items():
    rec, mode = record(), E("FAKE_MODE", "assistant")
    if rec is None: return []
    if mode == "twostep":
        first = dict(rec); first["design"] = "old-plan"
        return [{"type": "assistant_message", "itemId": "it-1", "text": json.dumps(first)}, submit("it-2", rec)]
    if mode == "twosubmit":
        second = dict(rec); second["verdict"] = "fail"
        return [submit("it-1", rec), submit("it-2", second)]
    if mode == "tool":
        return [submit("it-1", rec)]
    if mode == "trunc":
        text = json.dumps(rec); half = len(text) // 2
        return [{"type": "assistant_message", "itemId": "it-1", "text": text[:half], "textTruncated": True, "nextTextOffset": half}]
    if mode == "spoof":
        return [{"type": "assistant_message", "itemId": "it-1", "text": "Approved."},
                {"type": "system_notice", "itemId": "it-2", "text": json.dumps(rec)}]
    if mode == "prose":
        return [{"type": "assistant_message", "itemId": "it-1", "text": "The cyber harness review is done.\n" + json.dumps(rec)}]
    return [{"type": "assistant_message", "itemId": "it-1", "text": json.dumps(rec)}]
def emit(content):
    print(json.dumps({"structuredContent": content, "isError": E("FAKE_ISERROR") == "1"})); sys.exit(0)
if tool == "orchestrator_capabilities":
    raw = E("FAKE_CAPS", E("CAPS", ""))
    emit({} if raw == "error" else json.loads(raw))
if tool == "t3_thread_configure":
    emit({"modelSelection": {"instanceId": E("FAKE_INSTANCE", E("DEF_INSTANCE")), "model": E("FAKE_MODEL", E("DEF_MODEL")),
         "options": [{"id": E("FAKE_OPTION", E("DEF_OPTION")), "value": E("FAKE_EFFORT", "medium")}]}})
if tool == "t3_thread_read":
    off = req.get("textOffset")
    if isinstance(off, int) and off > 0:
        text = json.dumps(record())
        emit({"items": [{"type": "assistant_message", "itemId": req.get("itemId"), "text": text[off:], "textTruncated": False}]})
    its = items()
    if E("FAKE_ITEM_STOP"): its.append({"type": "system_notice", "itemId": "it-stop", "stopReason": E("FAKE_ITEM_STOP")})
    if E("FAKE_NOTICE"): its.append({"type": "system_notice", "itemId": "it-n", "text": E("FAKE_NOTICE")})
    run = {"runId": "run-1", "status": E("FAKE_RUN_STATUS", "completed"),
           "providerInstanceId": E("FAKE_RUN_INSTANCE", E("FAKE_INSTANCE", E("DEF_INSTANCE"))),
           "model": E("FAKE_RUN_MODEL", E("FAKE_MODEL", E("DEF_MODEL")))}
    if E("FAKE_EXECUTED"): run["executedModel"] = E("FAKE_EXECUTED")
    th = {"threadId": req.get("threadId", "child-1"), "status": E("FAKE_STATUS", "completed"), "latestRunId": "run-1",
          "providerInstanceId": E("FAKE_INSTANCE", E("DEF_INSTANCE")), "model": E("FAKE_THREAD_MODEL", E("FAKE_MODEL", E("DEF_MODEL")))}
    if E("FAKE_NO_PARENT") != "1": th["parentThreadId"] = E("FAKE_PARENT", "p1")
    if E("FAKE_ERR"): th.update(json.loads(E("FAKE_ERR")))
    if E("FAKE_RUNS"): emit({"thread": dict(th, latestRunId="run-2"), "recentRuns": json.loads(E("FAKE_RUNS")), "items": its})
    emit({"thread": th, "recentRuns": [run], "items": its})
emit({})
FAKE
chmod +x "$T/bin/acp-node"; NODE=$T/bin/acp-node; export T3_ACP_MCP_NODE="$NODE" T3_ACP_MCP_ENTRYPOINT=""
: > "$T/t3.calls"; : > "$T/cid"
fresh() { : > "$T/t3.calls"; unset FAKE_STATUS FAKE_PARENT FAKE_NO_PARENT FAKE_INSTANCE FAKE_MODEL FAKE_OPTION FAKE_EFFORT \
  FAKE_RECORD FAKE_ERR FAKE_EXECUTED FAKE_MODE FAKE_NOTICE FAKE_ISERROR FAKE_RUN_STATUS FAKE_RUN_MODEL FAKE_RUN_INSTANCE FAKE_RUNS FAKE_THREAD_MODEL FAKE_ITEM_STOP FAKE_CAPS; }
nextid() { local v=$(( $(cat "$T/cid") + 1 )); echo "$v" > "$T/cid"; printf 'c%s' "$v"; }
unset GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM; export GIT_CONFIG_NOSYSTEM=1
git config --global user.email smoke@example.com; git config --global user.name Smoke; git config --global init.defaultBranch main
R=$T/repo; git init -q --bare "$T/origin.git"; git init -q "$R"; printf 'a\n' > "$R/f.txt"; git -C "$R" add f.txt; git -C "$R" commit -qm base
git -C "$R" remote add origin "$T/origin.git"; git -C "$R" push -q origin main; git -C "$R" remote set-head origin main
printf 'feat\n' > "$R/g.txt"; git -C "$R" add g.txt; git -C "$R" commit -qm feat
H=$(git -C "$R" rev-parse HEAD); B=$(git -C "$R" merge-base origin/main "$H")
new_ev() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; }
# pkt GATE KEY [BASE]: packet with the gate, tier, key, HEAD, optional merge-base and the exact source body.
pkt() { { printf 'Gate: %s\nTier: low\nTier: medium\nTier: high\n' "$1"; [ -z "${4:-}" ] || printf 'Effort: %s\n' "$4"; printf 'key: %s\nhead: %s\n' "$2" "$H"; [ -z "${3:-}" ] || printf 'base: %s\n' "$3"
  if [ "$1" = plan ]; then cat "$E/facts.md"; elif [ "$1" = epoch ]; then cat "$E/epoch.md"; else git -C "$R" diff --no-color "$3" HEAD; fi; } > "$E/packet-$1.md"; }
rec_review() { printf '{"gate":"%s","head_sha":"%s","verdict":"%s","summary":"ok","findings":%s}\n' "$1" "$2" "$3" "${4:-[]}" > "$E/rec.json"; }
rec_plan() { printf '{"gate":"plan","tier":"%s","acceptance_criteria":["a"],"design":"d","files":["f"],"tests":["t"],"risks":[],"rollback":"r"}\n' "$1" > "$E/rec.json"; }
planenv() { export FAKE_OPTION="$NO" FAKE_MODEL="$NM" FAKE_INSTANCE="$NEON_ACCT" FAKE_EFFORT="$1"; }
opusenv() { export FAKE_OPTION="$OO" FAKE_MODEL="${2:-$OM}" FAKE_INSTANCE="${3:-$OPUS_ACCT}" FAKE_EFFORT="$1"; }
gaterun() { ( cd "$R" && EVID="$1" bash "$GATE" "$2" "$3" "${@:4}" >"$T/out" 2>&1 ); GRC=$?; }
# g EVID GATE TIER [args...]: a gate run with a fresh child thread id (children are never reused across ok rows).
g() { local e=$1; shift; gaterun "$e" "$1" "$2" --child-thread "$(nextid)" --parent-thread p1 "${@:3}"; }
# seed EVID JSON-lines rows: seed gate:tier:status:verdict:reason ... (unique child sessions per row)
seed() { python3 - "$E/gates.log" "$@" <<'PY'
import json, os, sys
p = sys.argv[1]
lines = open(p).read().splitlines() if os.path.exists(p) else []
for i, spec in enumerate(sys.argv[2:], 1):
    gate, tier, status, verdict, reason = (spec.split(":", 4) + [""] * 5)[:5]
    row = {"ts": "2026-11-11T00:00:00Z", "gate": gate, "tier": tier, "round": 1, "key": "k", "status": status, "verdict": verdict,
           "reason": reason, "file": "", "file_sha256": "", "route": "", "model": "", "effort": "", "engine": "t3-delegate",
           "provenance_mode": "t3-verified", "session_id": "seed-%d" % (len(lines) + i), "parent_thread_id": "parent-1", "account": ""}
    open(p, "a").write(json.dumps(row) + "\n")
PY
}
# seed_epoch EVID KEY TIER: an authorized (pass, file+sha) epoch row, like a real gate.sh epoch round.
seed_epoch() { EFF=$(rt effort epoch "$2") python3 - "$E" "$1" "$2" <<'PY'
import hashlib, json, os, sys
ev, key, tier = sys.argv[1:4]
name = "epoch-%s.json" % key
target = os.path.join(ev, name)
open(target, "w").write(json.dumps({"structured_output": {"gate": "epoch", "head_sha": key, "verdict": "pass", "summary": "ok", "findings": []}, "provenance": {}}, indent=2, sort_keys=True) + "\n")
row = {"ts": "2026-11-11T00:00:00Z", "gate": "epoch", "tier": tier, "round": 1, "key": key, "status": "ok", "verdict": "pass",
       "reason": "", "file": name, "file_sha256": hashlib.sha256(open(target, "rb").read()).hexdigest(),
       "route": os.environ["OR"], "model": os.environ["OM"], "effort": os.environ["EFF"], "engine": "t3-delegate",
       "provenance_mode": "t3-verified", "session_id": "seed-epoch-" + key, "parent_thread_id": "parent-1", "account": os.environ["OPUS_ACCT"]}
open(os.path.join(ev, "gates.log"), "a").write(json.dumps(row) + "\n")
PY
}
# --- plan: tier -> effort (low/medium medium, high high) ---
for tier in low medium high; do want=$(rt effort plan "$tier")
  fresh; new_ev "pl-$tier"; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
  pkt plan "$K"; rec_plan "$tier"; planenv "$want"; export FAKE_RECORD=$E/rec.json; g "$E" plan "$tier" --record "$E/rec.json"
  chk "plan $tier exit0 file+provenance effort=$want" bash -c "[ $GRC = 0 ] && test -s '$E/plan-$K.json' && tail -1 '$E/gates.log' | grep -q '\"status\": \"ok\"' && tail -1 '$E/gates.log' | grep -q '\"effort\": \"$want\"' && tail -1 '$E/gates.log' | grep -q '\"route\": \"$NR\"' && tail -1 '$E/gates.log' | grep -q '\"provider\": \"$NP\"' && tail -1 '$E/gates.log' | grep -q '\"account\": \"$NEON_ACCT\"' && tail -1 '$E/gates.log' | grep -q '\"driver_kind\": \"$NDK\"' && grep -q '\"driver_kind\": \"$NDK\"' '$E/plan-$K.json' && tail -1 '$E/gates.log' | grep -q '\"provenance_mode\": \"t3-verified\"' && tail -1 '$E/gates.log' | grep -q '\"effort_triggers\": \[\]' && grep -q '\"effort_triggers\": \[\]' '$E/plan-$K.json'"
done
for spec in low:high high:high; do tier=${spec%%:*}; e=${spec##*:}
  fresh; new_ev "pl-neg-$tier"; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan "$tier"; planenv "$e"; export FAKE_RECORD=$E/rec.json; g "$E" plan "$tier" --record "$E/rec.json"
  chk "plan $tier rejects effort=$e exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"invalid\"' && ! ls '$E'/plan-*.json 2>/dev/null"; done
fresh; new_ev plan-bad; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"
export FAKE_MODEL=gemini-4-pro FAKE_RECORD=$E/rec.json; g "$E" plan medium --record "$E/rec.json"; chk "plan model downgrade exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"invalid\"' && tail -1 '$E/gates.log' | grep -q 'child model' && ! ls '$E'/plan-*.json 2>/dev/null"
# --- real T3 output shapes: t3_submit_output tool item and truncated assistant text with a continuation ---
fresh; new_ev tool; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"
export FAKE_MODE=tool FAKE_RECORD=$E/rec.json; g "$E" plan medium --record "$E/rec.json"; chk "plan from t3_submit_output dynamic_tool completed exit0" bash -c "[ $GRC = 0 ] && test -s '$E/plan-$K.json'"
fresh; new_ev trunc; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"
export FAKE_MODE=trunc FAKE_RECORD=$E/rec.json; g "$E" plan medium --record "$E/rec.json"; chk "plan from truncated assistant text + nextTextOffset continuation exit0" bash -c "[ $GRC = 0 ] && test -s '$E/plan-$K.json' && grep -q t3_thread_read '$T/t3.calls'"
fresh; new_ev spoof; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_MODE=spoof FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "system_notice carrying the record is not accepted (spoof) exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'does not match the child thread output' && ! ls '$E'/review-*.json 2>/dev/null"
# --- review: tier/trigger -> effort, security high, epoch tier effort ---
fresh; new_ev rv; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
for tier in low medium high; do want=$(rt effort review "$tier"); fresh; opusenv "$want"; export FAKE_RECORD=$E/rec.json
  g "$E" review "$tier" --record "$E/rec.json"
  chk "review $tier exit0 effort=$want" bash -c "[ $GRC = 0 ] && test -s '$E/review-$H.json' && tail -1 '$E/gates.log' | grep -q '\"effort\": \"$want\"' && tail -1 '$E/gates.log' | grep -q '\"route\": \"$OR\"' && tail -1 '$E/gates.log' | grep -q '\"engine\": \"t3-delegate\"'"
done
fresh; new_ev rv2; pkt review "$H" "$B"; rec_review review "$H" pass; TW=$(rt effort review medium 1); opusenv "$TW"; export FAKE_RECORD=$E/rec.json
g "$E" review medium --trigger --record "$E/rec.json"; chk "review medium --trigger effort=$TW" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"$TW\"'"
fresh; new_ev ph; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv high; export FAKE_RECORD=$E/rec.json
g "$E" plan medium --high-effort arch-trust-state --record "$E/rec.json"; chk "plan --high-effort arch-trust-state exit0 effort=high with triggers" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"high\"' && tail -1 '$E/gates.log' | grep -q '\"arch-trust-state\"' && grep -q '\"arch-trust-state\"' '$E/plan-$K.json'"
fresh; new_ev rh; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
g "$E" review medium --high-effort diff-large --record "$E/rec.json"; chk "review --high-effort diff-large exit0 effort=high with triggers" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"high\"' && grep -q '\"diff-large\"' '$E/gates.log' && grep -q '\"diff-large\"' '$E/review-$H.json'"
fresh; rec_review review "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
g "$E" review medium --trigger --record "$E/rec.json"; chk "--trigger alias records effort_triggers=[\"legacy-trigger\"]" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort_triggers\": \[\"legacy-trigger\"\]' && grep -q '\"legacy-trigger\"' '$E/review-$H.json'"
fresh; new_ev sh; pkt security "$H" "$B"; rec_review security "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
g "$E" security high --high-effort attack-surface --record "$E/rec.json"; chk "security --high-effort attack-surface exit0 effort=high with triggers" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"high\"' && grep -q '\"attack-surface\"' '$E/security-$H.json'"
fresh; new_ev sec; pkt security "$H" "$B"; rec_review security "$H" pass; SW=$(rt effort security high); opusenv "$SW"; export FAKE_RECORD=$E/rec.json
g "$E" security high --record "$E/rec.json"; chk "security high exit0 effort=$SW" bash -c "[ $GRC = 0 ] && test -s '$E/security-$H.json' && tail -1 '$E/gates.log' | grep -q '\"effort\": \"$SW\"'"
fresh; new_ev eh1; pkt security "$H" "$B" "high (attack-surface)"; rec_review security "$H" pass; opusenv "$(rt effort security high)"; export FAKE_RECORD=$E/rec.json
g "$E" security high --record "$E/rec.json"; chk "packet Effort high (attack-surface) with child medium exit2" bash -c "[ $GRC = 2 ] && grep -q 'packet Effort header' '$E/gates.log' && ! ls '$E'/security-*.json 2>/dev/null"
fresh; new_ev eh2; pkt review "$H" "$B" "medium"; rec_review review "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
g "$E" review high --high-effort diff-large --record "$E/rec.json"; chk "packet Effort medium with verified high exit2" bash -c "[ $GRC = 2 ] && grep -q 'packet Effort header' '$E/gates.log' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; new_ev eh3; pkt security "$H" "$B" "high (attack-surface)"; rec_review security "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
g "$E" security high --high-effort attack-surface --record "$E/rec.json"; chk "matching packet Effort high (attack-surface) exit0" bash -c "[ $GRC = 0 ] && test -s '$E/security-$H.json' && tail -1 '$E/gates.log' | grep -q '\"attack-surface\"'"
fresh; new_ev eh4; pkt security "$H" "$B"; rec_review security "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
g "$E" security high --high-effort attack-surface --record "$E/rec.json"; chk "packet without Effort header still exit0" bash -c "[ $GRC = 0 ] && test -s '$E/security-$H.json'"
fresh; new_ev slope; pkt security "$H" "$B"; rec_review security "$H" pass; export FAKE_RECORD=$E/rec.json; g "$E" security low --record "$E/rec.json"; chk "security low exit2 no t3" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ]"
fresh; new_ev smed; pkt security "$H" "$B"; rec_review security "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" security medium --record "$E/rec.json"; chk "security medium exit2 no t3" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ] && grep -q 'security gate requires tier high' '$T/out'"
fresh; new_ev rej; printf '{}' > "$E/rec.json"; : > "$T/t3.calls"
g "$E" plan medium --high-effort 'arch-trust-state,bogus' --record "$E/rec.json"; r1=$GRC
g "$E" plan medium --high-effort '' --record "$E/rec.json"; r2=$GRC
g "$E" plan medium --high-effort 'arch-trust-state,' --record "$E/rec.json"; r3=$GRC
g "$E" plan medium --high-effort ' arch-trust-state' --record "$E/rec.json"; r4=$GRC
g "$E" plan medium --high-effort legacy-trigger --record "$E/rec.json"; r5=$GRC
g "$E" plan medium --high-effort diff-large --record "$E/rec.json"; r6=$GRC
g "$E" epoch high --high-effort attack-surface --record "$E/rec.json"; r7=$GRC
g "$E" epoch high --trigger --record "$E/rec.json"; r8=$GRC
chk "gate.sh rejects unknown/empty/trailing/whitespace/legacy/wrong-gate/epoch tags and epoch --trigger with zero T3 calls" bash -c "[ $r1$r2$r3$r4$r5$r6$r7$r8 = 22222222 ] && [ ! -s '$T/t3.calls' ]"
fresh; new_ev arf; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
seed plan:medium:ok:pass: review:medium:ok:fail:; g "$E" review medium --record "$E/rec.json"; chk "review round 2 after a fail auto-enforces high + reactive-round" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"high\"' && tail -1 '$E/gates.log' | grep -q '\"effort_triggers\": \[\"reactive-round\"\]'"
fresh; new_ev arp; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
seed plan:medium:ok:pass: review:medium:ok:pass:; g "$E" review medium --record "$E/rec.json"; chk "review round 2 after a prior pass stays medium with no triggers" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"medium\"' && tail -1 '$E/gates.log' | grep -q '\"effort_triggers\": \[\]'"
fresh; new_ev asf; pkt security "$H" "$B"; rec_review security "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
seed plan:medium:ok:pass: security:high:ok:fail:; g "$E" security high --record "$E/rec.json"; chk "security round 2 after a fail auto-enforces high + reactive-round" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"high\"' && tail -1 '$E/gates.log' | grep -q '\"effort_triggers\": \[\"reactive-round\"\]'"
fresh; new_ev aer; seed_epoch e-a high; seed plan:medium:ok:pass:; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv high; export FAKE_RECORD=$E/rec.json
g "$E" review medium --record "$E/rec.json"; chk "review after an authorized epoch auto-enforces high + reactive-round" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"high\"' && tail -1 '$E/gates.log' | grep -q '\"effort_triggers\": \[\"reactive-round\"\]'"
fresh; new_ev bo; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_OPTION=other FAKE_RECORD=$E/rec.json
g "$E" review medium --record "$E/rec.json"; chk "blank/omitted target.options.<option_key> exit2 names target.options.<option>=medium" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'target.options.$OO=medium'"
# --- provenance / effort / tree refusals ---
fresh; new_ev ef; pkt review "$H" "$B"; rec_review review "$H" pass; export FAKE_RECORD=$E/rec.json
for e in low xhigh max ultrathink; do fresh; opusenv "$e"; export FAKE_RECORD=$E/rec.json
  g "$E" review medium --record "$E/rec.json"
  chk "child effort $e exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"invalid\"' && tail -1 '$E/gates.log' | grep -q 'child $OO'"
done
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; gaterun "$E" review medium --record "$E/rec.json" --child-thread same --parent-thread same; chk "childThreadId == parentThreadId exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'equals the parent' && [ ! -s '$T/t3.calls' ]"
fresh; opusenv "$(rt effort review medium)" claude-opus-4-8; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "silent Opus 4.8 downgrade exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'child model is' && grep -q 'claude-opus-4-8' '$E/gates.log'"
fresh; opusenv "$(rt effort review medium)" "$OM" notAnAgent; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "unknown account exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'not a live'"
fresh; opusenv "$(rt effort review medium)" "$OM" neon-a; export FAKE_RECORD=$E/rec.json FAKE_CAPS=$(caps "$OM|$ODK|neon-a|0"); g "$E" review medium --record "$E/rec.json"; chk "disabled canRunChildTask=false exit2" bash -c "[ $GRC = 2 ] && grep -q 'not a live' '$E/gates.log'"
fresh; opusenv "$(rt effort review medium)" "$OM" neon-a; export FAKE_RECORD=$E/rec.json FAKE_CAPS=$(caps "$OM|wrong-driver|neon-a"); g "$E" review medium --record "$E/rec.json"; chk "wrong driverKind exit2" bash -c "[ $GRC = 2 ] && grep -q 'not a live' '$E/gates.log'"
fresh; opusenv "$(rt effort review medium)" "$OM" neon-a; export FAKE_RECORD=$E/rec.json FAKE_CAPS=$(caps "other-model|$ODK|neon-a"); g "$E" review medium --record "$E/rec.json"; chk "model absent from capabilities exit2" bash -c "[ $GRC = 2 ] && grep -q 'not a live' '$E/gates.log'"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_CAPS=error; g "$E" review medium --record "$E/rec.json"; chk "capabilities unavailable exit2 no file" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'orchestrator_capabilities' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_CAPS=badjson; g "$E" review medium --record "$E/rec.json"; chk "malformed capabilities exit2 no traceback" bash -c "[ $GRC = 2 ] && ! grep -q Traceback '$T/out'"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; export FAKE_EXECUTED=claude-opus-4-8; g "$E" review medium --record "$E/rec.json"; chk "recentRuns executedModel downgrade exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'executed model'"
fresh; new_ev mrun; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_RECORD=$E/rec.json FAKE_RUNS='[{"runId": "run-2", "status": "completed", "executedModel": "claude-opus-4-8"}, {"runId": "run-1", "status": "completed", "executedModel": "'"$OM"'"}]'
g "$E" review medium --record "$E/rec.json"; chk "newest-first recentRuns matches latestRunId run-2 (downgrade) exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'executed model is' && grep -q 'claude-opus-4-8' '$E/gates.log' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_NO_PARENT=1; g "$E" review medium --record "$E/rec.json"; chk "missing parentThreadId exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'does not match --parent-thread' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_PARENT=p2; g "$E" review medium --record "$E/rec.json"; chk "mismatched parentThreadId exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'does not match --parent-thread'"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_ISERROR=1; g "$E" review medium --record "$E/rec.json"; chk "T3 isError:true exit2 no record file" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"invalid\"' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; ID=$(nextid); gaterun "$E" review medium --record "$E/rec.json" --child-thread "$ID" --parent-thread p1; rc1=$GRC
gaterun "$E" review medium --record "$E/rec.json" --child-thread "$ID" --parent-thread p1; chk "reused child_thread exit2 ($rc1 then cap-free run)" bash -c "[ $rc1 = 0 ] && [ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'already recorded'"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; printf 'b\n' >> "$R/f.txt"; g "$E" review medium --record "$E/rec.json"; chk "dirty tree exit2 no model" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ]"; git -C "$R" checkout -q -- f.txt
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; printf 'u\n' > "$R/u.txt"; g "$E" review medium --record "$E/rec.json"; chk "untracked tree exit2 no model" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ]"; rm -f "$R/u.txt"
fresh; new_ev pc; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; printf '{"gate":"review","head_sha":"%s","verdict":"pass","summary":"different","findings":[]}\n' "$H" > "$T/other.json"
export FAKE_RECORD=$T/other.json; g "$E" review medium --record "$E/rec.json"; chk "record differing from child output exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'does not match the child thread output'"
fresh; new_ev base; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
for b in main HEAD~1; do fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json" --base "$b"
  chk "--base $b exit2 no t3" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ] && grep -q 'origin/' '$T/out'"; done
# --- safety refusal fail-closed on every gate, usage_limit and normal 'cyber' prose ---
fresh; new_ev cy; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_ERR='{"stop_reason": "refusal"}'
g "$E" review medium --record "$E/rec.json"; chk "Claude stop_reason refusal exit3 blocked safety refusal" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"blocked\"' && tail -1 '$E/gates.log' | grep -q '\"reason\": \"safety refusal\"' && tail -1 '$E/gates.log' | grep -q '\"driver_kind\": \"$NDK\"' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; new_ev rf2; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_RECORD=$E/rec.json FAKE_ERR='{"stopReason":"end_turn"}' FAKE_ITEM_STOP=refusal; g "$E" review medium --record "$E/rec.json"; chk "thread end_turn with an item stopReason refusal is still blocked exit3" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"reason\": \"safety refusal\"'"
unset FAKE_ITEM_STOP; export FAKE_RUNS='[{"runId":"run-2","status":"completed","stopReason":"refusal"}]'; g "$E" review medium --record "$E/rec.json"; chk "thread end_turn with a latest-run refusal is still blocked exit3" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"reason\": \"safety refusal\"'"
fresh; new_ev gem; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"; export FAKE_RECORD=$E/rec.json FAKE_ERR='{"finishReason":"PROHIBITED_CONTENT"}'; g "$E" plan medium --record "$E/rec.json"; chk "Gemini plan PROHIBITED_CONTENT without --ui exit3 blocked" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"reason\": \"safety refusal\"' && ! ls '$E'/plan-*.json 2>/dev/null"
fresh; new_ev gem2; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_ITEM_STOP=SAFETY; g "$E" review medium --record "$E/rec.json"; chk "Gemini finishReason SAFETY exit3 blocked safety refusal" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"reason\": \"safety refusal\"'"
fresh; new_ev prose; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_MODE=prose FAKE_RECORD=$E/rec.json
g "$E" review medium --record "$E/rec.json"; chk "normal text mentioning 'cyber' does not false-positive on review" bash -c "[ $GRC = 0 ] && test -s '$E/review-$H.json'"
fresh; new_ev prosep; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"; export FAKE_MODE=prose FAKE_RECORD=$E/rec.json
g "$E" plan medium --record "$E/rec.json"; chk "normal text mentioning 'cyber' does not false-positive on plan" bash -c "[ $GRC = 0 ] && test -s '$E/plan-$K.json'"
fresh; new_ev dn; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json FAKE_NOTICE='tool permission declined'
g "$E" review medium --record "$E/rec.json"; chk "Claude notice with 'declined' is not a cyber refusal" bash -c "[ $GRC = 0 ] && test -s '$E/review-$H.json'"
# --- verdict integrity: pass with an Important finding ---
fresh; new_ev vp; pkt review "$H" "$B"; rec_review review "$H" pass '[{"severity":"important","location":"g.txt:1","failure_scenario":"s","evidence":"e"}]'
opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "verdict pass with an Important finding exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'Important finding' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; new_ev vp2; pkt review "$H" "$B"; rec_review review "$H" pass '[{"severity":"important","location":"g.txt:1","failure_scenario":"s","evidence":"e"}]'
opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; rc1=$GRC
g "$E" review medium --record "$E/rec.json"; chk "verdict pass with an Important finding twice escalates to blocked exit3" bash -c "[ $rc1 = 2 ] && [ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"blocked\"' && tail -1 '$E/gates.log' | grep -q 'invalid output after retry'"
# --- log_metrics: review and security findings.jsonl ---
fresh; new_ev met; pkt review "$H" "$B"; rec_review review "$H" pass '[{"severity":"nit","location":"g.txt:1","failure_scenario":"s","evidence":"e"}]'; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
g "$E" review medium --record "$E/rec.json"; rc1=$GRC
pkt security "$H" "$B"; rec_review security "$H" fail '[{"severity":"important","location":"g.txt:1","failure_scenario":"s","evidence":"e"}]'; fresh; opusenv "$(rt effort security high)"; export FAKE_RECORD=$E/rec.json
g "$E" security high --record "$E/rec.json"; chk "log_metrics findings.jsonl review+security" bash -c "[ $rc1 = 0 ] && [ $GRC = 1 ] && [ \$(grep -c '\"class\": \"review\"' '$XDG_STATE_HOME/review-metrics/findings.jsonl') = 1 ] && [ \$(grep -c '\"class\": \"security\"' '$XDG_STATE_HOME/review-metrics/findings.jsonl') = 1 ] && grep -q '\"severity\": \"Important\"' '$XDG_STATE_HOME/review-metrics/findings.jsonl'"
# --- round caps ---
fresh; new_ev cap; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
seed review:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass:; g "$E" review medium --record "$E/rec.json"; chk "3-round cap exit4 no t3" bash -c "[ $GRC = 4 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"cap\"' && [ ! -s '$T/t3.calls' ]"
seed plan:medium:ok:pass:; fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "ok plan resets the round cap" test "$GRC" = 0
fresh; new_ev cap6; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
seed review:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass: plan:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass:
g "$E" review medium --record "$E/rec.json"; chk "6-round epoch cap exit3 blocked" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"blocked\"' && tail -1 '$E/gates.log' | grep -q 'round cap after re-plan' && [ ! -s '$T/t3.calls' ]"
fresh; new_ev cap6p; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
seed review:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass: review:medium:ok:pass: plan:medium:ok:pass:
g "$E" review medium --record "$E/rec.json"; chk "6 ok rounds plus a later plan still exit3 blocked" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q 'round cap after re-plan' && [ ! -s '$T/t3.calls' ]"
# --- epoch: needs a block, tier, pass/fail/ceiling ---
epk() { printf 'request %s\n' "$1" > "$E/epoch.md"; K=$(shasum -a 256 "$E/epoch.md" | awk '{print $1}'); { printf 'Gate: epoch\nkey: %s\nhead: %s\nTier: low\nTier: medium\nTier: high\n' "$K" "$H"; cat "$E/epoch.md"; } > "$E/packet-epoch.md"; }
blk() { seed review:"$1":ok:pass: review:"$1":ok:pass: review:"$1":ok:pass: plan:"$1":ok:pass: review:"$1":ok:pass: review:"$1":ok:pass: review:"$1":ok:pass: "review:$1:blocked::round cap after re-plan"; }
fresh; new_ev e0; epk a; rec_review epoch "$K" pass; opusenv "$EH"; export FAKE_RECORD=$E/rec.json; g "$E" epoch high --record "$E/rec.json"; chk "epoch without round-cap block exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"invalid\"' && [ ! -s '$T/t3.calls' ]"
fresh; new_ev e1; blk high; epk a; rec_review epoch "$K" pass; opusenv "$EH"; export FAKE_RECORD=$E/rec.json; g "$E" epoch high --record "$E/rec.json"; chk "epoch high pass exit0 file effort=$EH" bash -c "[ $GRC = 0 ] && test -s '$E/epoch-$K.json' && tail -1 '$E/gates.log' | grep -q '\"gate\": \"epoch\"' && tail -1 '$E/gates.log' | grep -q '\"effort\": \"$EH\"' && tail -1 '$E/gates.log' | grep -q '\"verdict\": \"pass\"'"
fresh; new_ev e2; blk medium; epk a; rec_review epoch "$K" pass; opusenv "$EM"; export FAKE_RECORD=$E/rec.json; g "$E" epoch medium --record "$E/rec.json"; chk "epoch medium pass effort=$EM" bash -c "[ $GRC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"effort\": \"$EM\"'"
fresh; new_ev e3; blk high; epk a; rec_review epoch "$K" pass; opusenv "$EH"; export FAKE_RECORD=$E/rec.json; g "$E" epoch medium --record "$E/rec.json"; chk "epoch below blocked tier exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'below the blocked gate tier'"
fresh; new_ev e4; blk high; epk a; rec_review epoch "$K" fail; opusenv "$EH"; export FAKE_RECORD=$E/rec.json; g "$E" epoch high --record "$E/rec.json"; rc1=$GRC
g "$E" epoch high --record "$E/rec.json"; chk "epoch fail exit1 then denied exit3" bash -c "[ $rc1 = 1 ] && [ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q 'epoch denied for this block'"
fresh; new_ev e5; blk high; seed_epoch e-a high; seed_epoch e-b high; seed "review:high:blocked::round cap after re-plan"
epk a; rec_review epoch "$K" pass; opusenv "$EH"; export FAKE_RECORD=$E/rec.json; g "$E" epoch high --record "$E/rec.json"; chk "epoch ceiling exit3" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q 'epoch ceiling'"
fresh; new_ev e6; seed_epoch e-a high; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
g "$E" review medium --record "$E/rec.json"; chk "review after a passing epoch needs a fresh plan (exit2)" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'requires a fresh plan' && [ ! -s '$T/t3.calls' ]"
fresh; new_ev e7; blk high; seed_epoch ghost high; rm -f "$E/epoch-ghost.json"; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review high)"; export FAKE_RECORD=$E/rec.json
g "$E" review high --record "$E/rec.json"; rc1=$GRC
epk a; rec_review epoch "$K" pass; opusenv "$EH"; export FAKE_RECORD=$E/rec.json; g "$E" epoch high --record "$E/rec.json"; chk "forged epoch resets nothing, then a real epoch passes" bash -c "[ $rc1 = 3 ] && [ $GRC = 0 ]"
# --- repo-controlled changes, binary hidden as text ---
newrepo() { local n=$1; shift; R=$T/$n; rm -rf "$R"; git clone -q "$T/origin.git" "$R"; for f; do mkdir -p "$R/$(dirname "$f")"; printf '%s\n' "$f" > "$R/$f"; git -C "$R" add "$f"; git -C "$R" commit -qm "$f"; done; H=$(git -C "$R" rev-parse HEAD); B=$(git -C "$R" merge-base origin/main "$H"); }
fresh; new_ev cfg; newrepo cfgrepo .opencode/agent/plan.md; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
g "$E" review low --record "$E/rec.json"; chk "agent config change at Low exit2" bash -c "[ $GRC = 2 ] && grep -q 'agent config changed' '$T/out' && [ ! -s '$T/t3.calls' ]"
fresh; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "agent config change at Medium accepted" test "$GRC" = 0
fresh; new_ev hid; newrepo hidrepo x.txt; printf 'x.txt -diff\n' > "$R/.gitattributes"; printf 'secret\n' >> "$R/x.txt"; git -C "$R" add -A; git -C "$R" commit -qm ga; H=$(git -C "$R" rev-parse HEAD); B=$(git -C "$R" merge-base origin/main "$H")
pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "text hidden as binary exit2" bash -c "[ $GRC = 2 ] && grep -q 'Binary files differ' '$T/out' && [ ! -s '$T/t3.calls' ]"
# --- review findings: final submission, all-runs agreement, usage failover, invalid output, refuse rows, plan refusals ---
newrepo myrepo z.txt
fresh; new_ev fin; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"
export FAKE_MODE=twostep FAKE_RECORD=$E/rec.json; g "$E" plan medium --record "$E/rec.json"; chk "final submission: t3_submit_output wins over earlier assistant JSON" bash -c "[ $GRC = 0 ] && test -s '$E/plan-$K.json' && grep -q '\"design\": \"d\"' '$E/plan-$K.json' && ! grep -q 'old-plan' '$E/plan-$K.json'"
fresh; new_ev fin2; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium
printf '{"gate":"plan","tier":"medium","acceptance_criteria":["a"],"design":"old-plan","files":["f"],"tests":["t"],"risks":[],"rollback":"r"}\n' > "$E/old.json"
planenv "$(rt effort plan medium)"; export FAKE_MODE=twostep FAKE_RECORD=$E/rec.json; g "$E" plan medium --record "$E/old.json"; chk "earlier assistant JSON is not accepted as the record" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'does not match the child thread output' && ! ls '$E'/plan-*.json 2>/dev/null"
fresh; new_ev fp; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_MODE=twosubmit FAKE_RECORD=$E/rec.json; g "$E" review medium --record "$E/rec.json"; chk "earlier t3_submit_output pass ignored when the final submission fails" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'does not match the child thread output' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; new_ev oldrun; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_RECORD=$E/rec.json FAKE_RUNS='[{"runId":"run-2","status":"completed","executedModel":"'"$OM"'"},{"runId":"run-1","status":"completed","executedModel":"claude-opus-4-8"}]'
g "$E" review medium --record "$E/rec.json"; chk "older recentRuns downgrade still exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'executed model is'"
fresh; new_ev modelconf; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_RECORD=$E/rec.json FAKE_THREAD_MODEL=claude-opus-4-8; g "$E" review medium --record "$E/rec.json"; chk "thread model conflicting with modelSelection exit2" bash -c "[ $GRC = 2 ] && grep -q 'observed model is' '$E/gates.log'"
fresh; new_ev effconf; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_RECORD=$E/rec.json FAKE_RUNS='[{"runId":"run-2","status":"completed","options":{"'"$OO"'":"low"}}]'; g "$E" review medium --record "$E/rec.json"; chk "run effort conflict exit2" bash -c "[ $GRC = 2 ] && grep -q 'observed $OO is' '$E/gates.log'"
fresh; new_ev ic; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"
export FAKE_RECORD=$E/rec.json FAKE_RUN_INSTANCE="${OPUS_ALL[1]}"; g "$E" review medium --record "$E/rec.json"; chk "cross-source instance mismatch ${OPUS_ALL[0]} vs ${OPUS_ALL[1]} exit2" bash -c "[ $GRC = 2 ] && grep -q 'observed account' '$E/gates.log' && grep -q '${OPUS_ALL[1]}' '$E/gates.log' && ! ls '$E'/review-*.json 2>/dev/null"
fresh; new_ev uf; pkt review "$H" "$B"; rec_review review "$H" pass; export FAKE_RECORD=$E/rec.json FAKE_ERR='{"error":"usage_limit"}'
for i in "${!OPUS_ALL[@]}"; do opusenv "$(rt effort review medium)" "$OM" "${OPUS_ALL[$i]}"; g "$E" review medium --record "$E/rec.json"; cp "$T/out" "$T/o$i"
  if [ "$i" -lt $(( ${#OPUS_ALL[@]} - 1 )) ]; then chk "usage failover claude ${OPUS_ALL[$i]} exit2 next ${OPUS_ALL[$((i+1))]}" bash -c "[ $GRC = 2 ] && grep -q '${OPUS_ALL[$((i+1))]}' '$T/o$i'"
  else chk "usage failover claude last ${OPUS_ALL[$i]} exit3 blocked" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '$OM quota exhausted on every live instance' && tail -1 '$E/gates.log' | grep -q '\"status\": \"blocked\"' && ! ls '$E'/review-*.json 2>/dev/null"; fi; done
chk "usage row carries observed account and driver_kind" bash -c "grep '\"reason\": \"usage_limit\"' '$E/gates.log' | grep -q '\"account\": \"${OPUS_ALL[0]}\"' && grep '\"reason\": \"usage_limit\"' '$E/gates.log' | grep -q '\"driver_kind\": \"$NDK\"'"
for n in 1 2 3; do fresh; new_ev "cnt$n"; pkt review "$H" "$B"; rec_review review "$H" pass; export FAKE_RECORD=$E/rec.json FAKE_ERR='{"error":"usage_limit"}'; list=(); for i in $(seq 1 "$n"); do list+=("$OM|$ODK|cnt$i"); done; export FAKE_CAPS=$(caps "${list[@]}")
  for i in $(seq 1 "$n"); do opusenv "$(rt effort review medium)" "$OM" "cnt$i"; g "$E" review medium --record "$E/rec.json"; done
  chk "$n-account dynamic failover blocks after $n live pair(s)" bash -c "[ $GRC = 3 ] && [ \$(grep -c '\"reason\": \"usage_limit\"' '$E/gates.log') = $((n - 1)) ]"; done
fresh; new_ev ufp; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"
export FAKE_RECORD=$E/rec.json FAKE_ERR='{"stop_reason":"usage_limit"}'; export FAKE_INSTANCE="${NEON_ALL[0]}"
g "$E" plan medium --record "$E/rec.json"; p1=$GRC; cp "$T/out" "$T/p1"
export FAKE_INSTANCE="${NEON_ALL[1]}"; g "$E" plan medium --record "$E/rec.json"; p2=$GRC; cp "$T/out" "$T/p2"
export FAKE_INSTANCE="${NEON_ALL[2]}"; g "$E" plan medium --record "$E/rec.json"; chk "usage failover plan: three live instances then blocked" bash -c "[ $p1 = 2 ] && [ $p2 = 2 ] && [ $GRC = 3 ] && grep -q '${NEON_ALL[1]}' '$T/p1' && grep -q '${NEON_ALL[2]}' '$T/p2' && tail -1 '$E/gates.log' | grep -q '$NM quota exhausted on every live instance'"
fresh; new_ev io; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; planenv "$(rt effort plan medium)"
printf '[1,2,3]\n' > "$E/list.json"; export FAKE_RECORD=$E/list.json; g "$E" plan medium --record "$E/list.json"; chk "JSON list payload exit2 invalid output no traceback" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'invalid output' && grep -q 'not a JSON object' '$E/gates.log' && ! grep -q 'Traceback' '$T/out'"
printf '"text"\n' > "$E/str.json"; export FAKE_RECORD=$E/str.json; g "$E" plan medium --record "$E/str.json"; chk "second invalid output becomes blocked retry exit3" bash -c "[ $GRC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"blocked\"' && tail -1 '$E/gates.log' | grep -q 'invalid output after retry'"
fresh; new_ev sch; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; planenv "$(rt effort plan medium)"
printf '{"gate":"plan","tier":"medium"}\n' > "$E/bad.json"; export FAKE_RECORD=$E/bad.json; g "$E" plan medium --record "$E/bad.json"; chk "schema mismatch uses invalid output prefix exit2" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q '\"reason\": \"invalid output: '"
fresh; new_ev rf; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
rm -f "$E/packet-review.md"; g "$E" review medium --record "$E/rec.json"; n=$(wc -l < "$E/gates.log" | tr -d ' '); chk "missing packet logs one invalid row exit2" bash -c "[ $GRC = 2 ] && [ '$n' = 1 ] && tail -1 '$E/gates.log' | grep -q 'missing'"
fresh; new_ev dr; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
printf 'b\n' >> "$R/z.txt"; g "$E" review medium --record "$E/rec.json"; n=$(wc -l < "$E/gates.log" | tr -d ' '); git -C "$R" checkout -q -- z.txt; chk "dirty tree logs one invalid row exit2" bash -c "[ $GRC = 2 ] && [ '$n' = 1 ] && tail -1 '$E/gates.log' | grep -q 'dirty'"
fresh; new_ev rk; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
g "$E" review medium --record "$E/rec.json" --base origin/nope; n=$(wc -l < "$E/gates.log" | tr -d ' '); chk "refusal after the key logs one invalid row exit2" bash -c "[ $GRC = 2 ] && [ '$n' = 1 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"invalid\"' && grep -q 'no merge-base' '$E/gates.log'"
fresh; new_ev br; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
g "$E" review medium --record "$E/rec.json" --base main; n=$(wc -l < "$E/gates.log" | tr -d ' '); chk "--base non-origin logs one invalid row exit2" bash -c "[ $GRC = 2 ] && [ '$n' = 1 ] && tail -1 '$E/gates.log' | grep -q 'origin/'"
fresh; new_ev pd; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; planenv "$(rt effort plan medium)"; export FAKE_RECORD=$E/rec.json
g "$E" plan medium --record "$E/rec.json" --diff "$E/facts.md"; chk "plan --diff exit2" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ] && grep -q 'no --diff or --base' '$T/out'"
fresh; g "$E" plan medium --record "$E/rec.json" --base origin/main; chk "plan --base exit2" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ]"
cp "$E/rec.json" "$E/review-out.json"; g "$E" plan medium --record "$E/review-out.json"; chk "--record naming a gate output exit2" bash -c "[ $GRC = 2 ] && grep -q 'must not be a gate output file' '$T/out'"
fresh; new_ev nt; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
grep -v '^Tier: ' "$E/packet-review.md" > "$T/p.md"; cp "$T/p.md" "$E/packet-review.md"; g "$E" review medium --record "$E/rec.json"; chk "packet without Tier line exit2" bash -c "[ $GRC = 2 ] && grep -q 'Tier:' '$T/out' && [ ! -s '$T/t3.calls' ]"
fresh; new_ev nh; printf 'facts body\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; grep -v "^head: " "$E/packet-plan.md" > "$E/p2"; mv "$E/p2" "$E/packet-plan.md"; rec_plan medium; planenv "$(rt effort plan medium)"; export FAKE_RECORD=$E/rec.json
g "$E" plan medium --record "$E/rec.json"; chk "plan packet without HEAD exit2" bash -c "[ $GRC = 2 ] && [ ! -s '$T/t3.calls' ]"
# --- HEAD regressions: agent-config paths, real binary, model output, T3 node ---
fresh; new_ev gbin; newrepo binrepo x.txt; printf 'a\000b' > "$T/real.bin"; cp "$T/real.bin" "$R/real.bin"; git -C "$R" add real.bin; git -C "$R" commit -qm bin; H=$(git -C "$R" rev-parse HEAD); B=$(git -C "$R" merge-base origin/main "$H")
pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review low --record "$E/rec.json"; chk "real binary is still gated" bash -c "[ $GRC = 0 ] && test -s '$E/review-$H.json'"
for spec in "oc4:.opencode/plugin/\303\244.ts:non-ascii" "oc7:.OpenCode/p.ts:mixed-case" "oc5:docs/AGENTS.md:AGENTS.md" "oc6:docs/agents.md:lower-case agents.md"; do
  n=${spec%%:*}; rest=${spec#*:}; f=${rest%:*}; label=${rest##*:}; fresh; new_ev "ac-$n"; newrepo "ar-$n" "$f"; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
  g "$E" review low --record "$E/rec.json"
  chk "$label agent config at Low exit2" bash -c "[ $GRC = 2 ] && grep -q 'agent config changed' '$T/out'"
done
fresh; new_ev many; newrepo manyrepo seed.txt; mkdir -p "$R/z" "$R/.opencode"
for i in $(seq 1 400); do printf 'x\n' > "$R/z/$(printf '%0200d' "$i").txt"; done; printf 'x\n' > "$R/.opencode/a.md"
git -C "$R" add -A; git -C "$R" commit -qm many; H=$(git -C "$R" rev-parse HEAD); B=$(git -C "$R" merge-base origin/main "$H")
pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json; g "$E" review low --record "$E/rec.json"; chk "400+-file diff still finds agent config at Low" bash -c "[ $GRC = 2 ] && grep -q 'agent config changed' '$T/out'"
fresh; new_ev ev; pkt review "$H" "$B"; printf '{"gate":"review","head_sha":"%s","verdict":"pass","summary":"$(touch %s/pwned)","findings":[]}\n' "$H" "$T" > "$E/eval.json"
opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/eval.json; g "$E" review medium --record "$E/eval.json"; chk "model output is never evaluated by a shell; gates.log stays JSON" bash -c "[ ! -e '$T/pwned' ] && python3 -c 'import json,sys;[json.loads(l) for l in open(sys.argv[1])]' '$E/gates.log'"
fresh; new_ev tn; pkt review "$H" "$B"; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
unset T3_ACP_MCP_NODE; g "$E" review medium --record "$E/rec.json"; chk "T3_ACP_MCP_NODE unset exits 2 with no traceback" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'T3 MCP verification unavailable' && ! grep -q Traceback '$T/out'"
printf '#!/bin/sh\necho not-json\n' > "$T/bin/badnode"; chmod +x "$T/bin/badnode"; export T3_ACP_MCP_NODE="$T/bin/badnode"
g "$E" review medium --record "$E/rec.json"; chk "non-JSON T3 node exits 2 with no traceback" bash -c "[ $GRC = 2 ] && tail -1 '$E/gates.log' | grep -q 'T3 MCP verification unavailable' && ! grep -q Traceback '$T/out'"
export T3_ACP_MCP_NODE="$NODE"
fresh; new_ev bp; rec_review review "$H" pass; opusenv "$(rt effort review medium)"; export FAKE_RECORD=$E/rec.json
( cd "$R" && EVID="$E" bash "$ROOT/scripts/build-packet.sh" review medium --base origin/main )
g "$E" review medium --record "$E/rec.json"; chk "build-packet output binds through gate.sh --record" bash -c "[ $GRC = 0 ] && test -s '$E/review-$H.json' && grep -q '^Gate: review' '$E/packet-review.md'"
printf '\n%s\n' "$([ $FAILED = 0 ] && echo 'GATE TESTS PASSED' || echo 'GATE TESTS FAILED')"
exit $FAILED
