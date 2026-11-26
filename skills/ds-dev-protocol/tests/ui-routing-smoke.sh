#!/usr/bin/env bash
# tests/ui-routing-smoke.sh - fakes-only UI gate, implementer and premerge routing tests; temp HOME, no model, no network.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P); GATE=$ROOT/scripts/gate.sh
rt() { python3 -I "$ROOT/scripts/routing_lib.py" "$@"; }
T=$(mktemp -d "${TMPDIR:-/tmp}/ui-smoke.XXXXXX"); T=$(cd "$T" && pwd -P); FAILED=0
export T HOME="$T/home" PATH="$T/bin:$PATH"; mkdir -p "$HOME" "$T/bin"; trap 'rm -rf "$T"' EXIT
ok() { printf 'ok   ui: %s\n' "$1"; }; bad() { printf 'FAIL ui: %s\n' "$1"; FAILED=1; }
chk() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
IFS=$'\t' read -r P1PROV P1ROUTE P1MODEL P1OPT P1DK <<< "$(rt ui-gate-tsv plan | sed -n 1p)"
IFS=$'\t' read -r P3PROV P3ROUTE P3MODEL P3OPT P3DK <<< "$(rt ui-gate-tsv plan | sed -n 2p)"
IFS=$'\t' read -r R1PROV R1ROUTE R1MODEL R1OPT R1DK <<< "$(rt ui-gate-tsv review | sed -n 1p)"
IFS=$'\t' read -r R3PROV R3ROUTE R3MODEL R3OPT R3DK <<< "$(rt ui-gate-tsv review | sed -n 2p)"
P1_ALL=(opus-a opus-b); P3_ALL=(neon-a neon-b); R1_ALL=("${P1_ALL[@]}"); R3_ALL=("${P3_ALL[@]}")
IFS=$'\t' read -r IPROV IROUTE IMODEL IMODELID IEFF IPIN IACCT IMAX <<< "$(rt impl-tsv)"
caps() { python3 - "$@" <<'PY'
import json, sys
out = []
for spec in sys.argv[1:]:
    parts = spec.split("|"); model, dk, inst = parts[:3]
    out.append({"providerInstanceId": inst, "driverKind": dk, "canRunChildTask": parts[3] != "0" if len(parts) > 3 else True, "models": [{"id": model}]})
print(json.dumps({"providers": out}))
PY
}
export CAPS=$(caps "$P1MODEL|$P1DK|${P1_ALL[0]}" "$P1MODEL|$P1DK|${P1_ALL[1]}" "$P3MODEL|$P3DK|${P3_ALL[0]}" "$P3MODEL|$P3DK|${P3_ALL[1]}")
cat > "$T/bin/acp" <<'PY'
#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a and a[0] == "acp-mcp-call": a = a[1:]
tool = a[0] if a else ""
try: req = json.loads(a[1]) if len(a) > 1 else {}
except ValueError: req = {}
open(os.environ["T"] + "/t3.calls", "a").write(tool + "\n")
E = lambda k, d="": os.environ.get(k, d)
def record():
    p = E("REC")
    if not p: return None
    d = json.load(open(p)); return d.get("structured_output", d) if isinstance(d, dict) else None
def emit(c): print(json.dumps({"structuredContent": c, "isError": False}))
if tool == "orchestrator_capabilities":
    print(json.dumps({"structuredContent": json.loads(os.environ.get("FAKE_CAPS", os.environ["CAPS"]))}))
elif tool == "t3_thread_configure":
    emit({"modelSelection": {"instanceId": E("INST"), "model": E("MODEL"), "options": [{"id": E("OPTION"), "value": E("EFF")}]}})
elif tool == "t3_thread_read":
    rec = record(); its = [] if rec is None else [{"type": "assistant_message", "itemId": "i", "text": json.dumps(rec)}]
    th = {"threadId": req.get("threadId", "c"), "status": E("STATUS", "completed"), "latestRunId": "run-1",
          "parentThreadId": E("PARENT", "p1"), "providerInstanceId": E("INST"), "model": E("MODEL")}
    if E("ERR"): th.update(json.loads(E("ERR")))
    run = {"runId": "run-1", "status": "completed", "providerInstanceId": E("RUN_INST", E("INST")), "model": E("RUN_MODEL", E("MODEL"))}
    if E("EXECUTED"): run["executedModel"] = E("EXECUTED")
    emit({"thread": th, "recentRuns": [run], "items": its})
else: emit({})
PY
chmod +x "$T/bin/acp"; export T3_ACP_MCP_NODE="$T/bin/acp" T3_ACP_MCP_ENTRYPOINT=""
unset GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM; export GIT_CONFIG_NOSYSTEM=1
git config --global user.email smoke@example.com; git config --global user.name Smoke; git config --global init.defaultBranch main
R=$T/repo; git init -q --bare "$T/origin.git"; git init -q "$R"; printf 'a\n' > "$R/f.txt"; git -C "$R" add f.txt; git -C "$R" commit -qm base
git -C "$R" remote add origin "$T/origin.git"; git -C "$R" push -q origin main; git -C "$R" remote set-head origin main
printf 'feat\n' > "$R/g.txt"; git -C "$R" add g.txt; git -C "$R" commit -qm feat
H=$(git -C "$R" rev-parse HEAD); B=$(git -C "$R" merge-base origin/main "$H"); N=1
setc() { export MODEL=$1 INST=$2 OPTION=$3 EFF=$4; }
fresh() { : > "$T/t3.calls"; export REC=""; unset ERR EXECUTED RUN_INST RUN_MODEL STATUS PARENT FAKE_CAPS; }
mk_ev() { E=$T/$1; rm -rf "$E"; mkdir -p "$E"; fresh; }
pkt() { local g=$1 key=$2 base=${3:-}; { printf 'Gate: %s\nkey: %s\nhead: %s\nTier: low\nTier: medium\nTier: high\nScope: ui\n' "$g" "$key" "$H"
  [ -z "$base" ] || printf 'base: %s\n' "$base"; if [ "$g" = plan ]; then cat "$E/facts.md"; else git -C "$R" diff --no-color "$base" HEAD; fi; } > "$E/packet-$g.md"; }
rec_plan() { printf '{"gate":"plan","tier":"%s","acceptance_criteria":["a"],"design":"d","files":["f"],"tests":["t"],"risks":[],"rollback":"r"}\n' "$1" > "$E/rec.json"; export REC=$E/rec.json; }
rec_review() { printf '{"gate":"%s","head_sha":"%s","verdict":"pass","summary":"ok","findings":[]}\n' "$1" "$2" > "$E/rec.json"; export REC=$E/rec.json; }
run() { ( cd "$R" && EVID="$E" bash "$GATE" "$@" >"$T/out" 2>&1 ); RC=$?; }
gcase() { local n=$1 want=$2 g=$3 tier=$4 model=$5 inst=$6 opt=$7 eff=$8 trig=${9:-}; setc "$model" "$inst" "$opt" "$eff"
  run "$g" "$tier" --ui ${trig:+--trigger} --record "$E/rec.json" --child-thread "c$N" --parent-thread p1; N=$((N + 1))
  if [ "$want" = 0 ]; then chk "$n" bash -c "[ $RC = 0 ] && tail -1 '$E/gates.log' | grep -q '\"ui\": true'"; else chk "$n" bash -c "[ $RC = $want ] && tail -1 '$E/gates.log' | grep -qE 'child (model|effort|account)|observed|expected'"; fi; }
factev() { mk_ev "$1"; printf 'facts\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; }
rvev() { mk_ev "$1"; pkt review "$H" "$B"; }
# --- plan: Opus tier effort by tier/trigger; Neon fallback is high ---
factev u-plan-low; rec_plan low; gcase "ui plan low accepts Opus medium" 0 plan low "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan low '' "$P1ROUTE")"
fresh; rec_plan low; gcase "ui plan low rejects Opus low" 2 plan low "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" low
factev u-plan-med; rec_plan medium; gcase "ui plan medium accepts Opus medium" 0 plan medium "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")"
fresh; rec_plan medium; gcase "ui plan medium --trigger accepts Opus high" 0 plan medium "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium 1 "$P1ROUTE")" 1
fresh; rec_plan medium; gcase "ui plan medium --trigger rejects Opus medium" 2 plan medium "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")" 1
factev u-plan-high; rec_plan high; gcase "ui plan high accepts Opus high" 0 plan high "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan high '' "$P1ROUTE")"
fresh; rec_plan high; gcase "ui plan high rejects Opus medium" 2 plan high "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" medium
# --- review: Opus low/high high, medium medium; Neon fallback low/high high, medium medium ---
for t in low medium high; do rvev "u-rv-$t"; rec_review review "$H"; gcase "ui review $t accepts Opus $(rt ui-effort review "$t" '' "$R1ROUTE")" 0 review "$t" "$R1MODEL" "${R1_ALL[0]}" "$R1OPT" "$(rt ui-effort review "$t" '' "$R1ROUTE")"; done
for spec in low:medium medium:high high:medium; do rvev "u-rvx-${spec%%:*}"; rec_review review "$H"; gcase "ui review ${spec%%:*} rejects Opus ${spec##*:}" 2 review "${spec%%:*}" "$R1MODEL" "${R1_ALL[0]}" "$R1OPT" "${spec##*:}"; done
for spec in low:high medium:medium; do t=${spec%%:*}; factev "u-plan-neon-$t"; rec_plan "$t"; gcase "ui plan Neon $t accepts ${spec##*:}" 0 plan "$t" "$P3MODEL" "${P3_ALL[0]}" "$P3OPT" "$(rt ui-effort plan "$t" '' "$P3ROUTE")"; fresh; rec_plan "$t"; gcase "ui plan Neon $t rejects $([ "$t" = low ] && echo medium || echo high)" 2 plan "$t" "$P3MODEL" "${P3_ALL[0]}" "$P3OPT" "$([ "$t" = low ] && echo medium || echo high)"; done
for spec in low:high medium:medium; do t=${spec%%:*}; rvev "u-rv-neon-$t"; rec_review review "$H"; gcase "ui review Neon $t accepts ${spec##*:}" 0 review "$t" "$R3MODEL" "${R3_ALL[0]}" "$R3OPT" "$(rt ui-effort review "$t" '' "$R3ROUTE")"; fresh; rec_review review "$H"; gcase "ui review Neon $t rejects $([ "$t" = low ] && echo medium || echo high)" 2 review "$t" "$R3MODEL" "${R3_ALL[0]}" "$R3OPT" "$([ "$t" = low ] && echo medium || echo high)"; done
# --- non-UI stays single-route; --ui is plan/review only; Scope: ui is required ---
factev u-nonui; rec_plan medium; setc "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" high; run plan medium --record "$E/rec.json" --child-thread x1 --parent-thread p1; chk "non-UI plan rejects Opus" test "$RC" = 2
rvev u-nonui-rv; rec_review review "$H"; setc "$R1MODEL" "${R1_ALL[0]}" "$R1OPT" high; run review medium --record "$E/rec.json" --child-thread x2 --parent-thread p1; chk "non-UI review rejects Opus" test "$RC" = 2
fresh; run security high --ui; chk "security rejects --ui with zero T3 calls" bash -c "[ $RC = 2 ] && [ ! -s '$T/t3.calls' ]"
fresh; run epoch high --ui; chk "epoch rejects --ui with zero T3 calls" bash -c "[ $RC = 2 ] && [ ! -s '$T/t3.calls' ]"
mk_ev u-noscope; printf 'facts\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}')
{ printf 'Gate: plan\nkey: %s\nhead: %s\nTier: medium\n' "$K" "$H"; cat "$E/facts.md"; } > "$E/packet-plan.md"; rec_plan medium
setc "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread ns --parent-thread p1; chk "packet without Scope: ui exits 2 with zero T3 calls" bash -c "[ $RC = 2 ] && [ ! -s '$T/t3.calls' ]"
# --- downgrade, recentRuns and refusal fail closed under --ui ---
factev u-down; rec_plan medium; setc claude-opus-4-8 "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread d1 --parent-thread p1; chk "ui silent model downgrade exits 2" test "$RC" = 2
fresh; setc "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")"; export EXECUTED=claude-opus-4-8; run plan medium --ui --record "$E/rec.json" --child-thread d2 --parent-thread p1; chk "ui recentRuns downgrade exits 2" test "$RC" = 2
rvev u-cyber; rec_review review "$H"; setc "$R1MODEL" "${R1_ALL[0]}" "$R1OPT" high; export ERR='{"stop_reason": "refusal"}'; run review medium --ui --record "$E/rec.json" --child-thread cy --parent-thread p1
chk "ui safety refusal exit3 blocked" bash -c "[ $RC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"reason\": \"safety refusal\"' && ! ls '$E'/review-*.json 2>/dev/null"
factev u-cyber-plan; rec_plan medium; setc "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")"; export ERR='{"stop_reason": "refusal"}'; run plan medium --ui --record "$E/rec.json" --child-thread cyp --parent-thread p1
chk "ui plan safety refusal exit3 blocked" bash -c "[ $RC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"reason\": \"safety refusal\"' && ! ls '$E'/plan-*.json 2>/dev/null"
# --- live capabilities: a zero-instance primary tier is skipped, a disabled primary is rejected ---
factev u-skip; rec_plan low; setc "$P3MODEL" "${P3_ALL[0]}" "$P3OPT" "$(rt ui-effort plan low '' "$P3ROUTE")"; export FAKE_CAPS=$(caps "$P3MODEL|$P3DK|${P3_ALL[0]}" "$P3MODEL|$P3DK|${P3_ALL[1]}"); run plan low --ui --record "$E/rec.json" --child-thread s1 --parent-thread p1; chk "ui plan skips a zero-instance primary tier" test "$RC" = 0
fresh; rec_plan low; setc "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan low '' "$P1ROUTE")"; export FAKE_CAPS=$(caps "$P1MODEL|$P1DK|${P1_ALL[0]}|0" "$P3MODEL|$P3DK|${P3_ALL[0]}"); run plan low --ui --record "$E/rec.json" --child-thread s2 --parent-thread p1; chk "ui plan rejects a disabled primary instance" test "$RC" = 2
factev u-anti; rec_plan low; export FAKE_CAPS=$(caps "$P1MODEL|$P3DK|anti-opus-a"); setc "$P1MODEL" anti-opus-a "$P1OPT" "$(rt ui-effort plan low '' "$P1ROUTE")"; run plan low --ui --record "$E/rec.json" --child-thread ant --parent-thread p1; chk "ui plan rejects Opus on Neon's driver_kind" bash -c "[ $RC = 2 ] && grep -q 'not a live' '$E/gates.log'"
# --- default usage_limit failover: two active tiers, no account-name collision ---
factev u-fo; rec_plan medium; export ERR='{"error":"usage_limit"}'
setc "$P1MODEL" "${P1_ALL[0]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread f1 --parent-thread p1; f1=$RC; cp "$T/out" "$T/f1"
setc "$P1MODEL" "${P1_ALL[1]}" "$P1OPT" "$(rt ui-effort plan medium '' "$P1ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread f2 --parent-thread p1; f2=$RC; cp "$T/out" "$T/f2"
setc "$P3MODEL" "${P3_ALL[0]}" "$P3OPT" "$(rt ui-effort plan medium '' "$P3ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread f3 --parent-thread p1; f3=$RC; cp "$T/out" "$T/f3"
setc "$P3MODEL" "${P3_ALL[1]}" "$P3OPT" "$(rt ui-effort plan medium '' "$P3ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread f4 --parent-thread p1; f4=$RC; chk "default failover Opus instances -> Neon instances -> blocked" bash -c "[ $f1 = 2 ] && [ $f2 = 2 ] && [ $f3 = 2 ] && [ $f4 = 3 ] && grep -q '${P1_ALL[1]}' '$T/f1' && grep -q '${P3_ALL[0]}' '$T/f2' && grep -q '${P3_ALL[1]}' '$T/f3' && tail -1 '$E/gates.log' | grep -q '\"status\": \"blocked\"'"
factev u-zero; rec_plan medium; export ERR='{"error":"usage_limit"}'; export FAKE_CAPS=$(caps "$P3MODEL|$P3DK|${P3_ALL[0]}" "$P3MODEL|$P3DK|${P3_ALL[1]}")
setc "$P3MODEL" "${P3_ALL[0]}" "$P3OPT" "$(rt ui-effort plan medium '' "$P3ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread z1 --parent-thread p1; z1=$RC
setc "$P3MODEL" "${P3_ALL[1]}" "$P3OPT" "$(rt ui-effort plan medium '' "$P3ROUTE")"; run plan medium --ui --record "$E/rec.json" --child-thread z2 --parent-thread p1; chk "zero-instance primary tier is skipped during failover" bash -c "[ $z1 = 2 ] && [ $RC = 3 ] && ! grep -q '${P1_ALL[0]}' '$T/out' && tail -1 '$E/gates.log' | grep -q 'quota exhausted on every live instance'"
# --- 3-tier failover with a synthetic shared-driver mid route ---
ALT=$T/alt; cp -R "$ROOT" "$ALT"
python3 -I -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["routes"]["alt_mid"]={"label":"Alt Mid","provider":"alt-mid-provider","model":"alt-mid-model","option_key":"effort","driver_kind":"alt-shared"}; d["routes"]["neon"]["driver_kind"]="alt-shared"; d["ui_gates"]["plan"].insert(1,{"route":"alt_mid","efforts":{"low":"medium","medium":"medium","high":"high"}}); d["ui_gates"]["review"].insert(1,{"route":"alt_mid","efforts":{"low":"high","medium":"medium","high":"high"}}); open(p,"w").write(json.dumps(d, indent=1)+"\n")' "$ALT/routing.json"
python3 -I "$ALT/scripts/routing_lib.py" sync || bad "alt ui routing sync"
A1=$(python3 -I "$ALT/scripts/routing_lib.py" ui-gate-tsv plan | sed -n 1p); A2=$(python3 -I "$ALT/scripts/routing_lib.py" ui-gate-tsv plan | sed -n 2p); A3=$(python3 -I "$ALT/scripts/routing_lib.py" ui-gate-tsv plan | sed -n 3p)
IFS=$'\t' read -r A1P A1R A1M A1O A1DK <<< "$A1"; IFS=$'\t' read -r A2P A2R A2M A2O A2DK <<< "$A2"; IFS=$'\t' read -r A3P A3R A3M A3O A3DK <<< "$A3"
A1L=(alt-opus-a alt-opus-b); A2L=(alt-mid-a alt-mid-b); A3L=(alt-neon-a alt-neon-b); chk "alt tiers are distinct models; the two shared-driver tiers share a driver kind" bash -c "[ '$A1M' != '$A2M' ] && [ '$A2M' != '$A3M' ] && [ '$A2DK' = '$A3DK' ] && [ '$A1DK' != '$A2DK' ]"
mk_ev u-alt; printf 'facts\n' > "$E/facts.md"; K=$(shasum -a 256 "$E/facts.md" | awk '{print $1}'); pkt plan "$K"; rec_plan medium; export ERR='{"error":"usage_limit"}'
export CAPS=$(caps "$A1M|$A1DK|${A1L[0]}" "$A1M|$A1DK|${A1L[1]}" "$A2M|$A2DK|${A2L[0]}" "$A2M|$A2DK|${A2L[1]}" "$A3M|$A3DK|${A3L[0]}" "$A3M|$A3DK|${A3L[1]}")
runalt() { ( cd "$R" && EVID="$E" bash "$ALT/scripts/gate.sh" "$@" >"$T/out" 2>&1 ); RC=$?; }
AE1=$(python3 -I "$ALT/scripts/routing_lib.py" ui-effort plan medium '' "$A1R"); AE2=$(python3 -I "$ALT/scripts/routing_lib.py" ui-effort plan medium '' "$A2R"); AE3=$(python3 -I "$ALT/scripts/routing_lib.py" ui-effort plan medium '' "$A3R")
AM=("$A1M" "$A1M" "$A2M" "$A2M" "$A3M" "$A3M"); AA=("${A1L[0]}" "${A1L[1]}" "${A2L[0]}" "${A2L[1]}" "${A3L[0]}" "${A3L[1]}")
AO=("$A1O" "$A1O" "$A2O" "$A2O" "$A3O" "$A3O"); AE=("$AE1" "$AE1" "$AE2" "$AE2" "$AE3" "$AE3")
for i in 0 1 2 3 4 5; do setc "${AM[$i]}" "${AA[$i]}" "${AO[$i]}" "${AE[$i]}"; runalt plan medium --ui --record "$E/rec.json" --child-thread "a$i" --parent-thread p1
  if [ "$i" -lt 5 ]; then chk "alt failover step $((i+1)) -> $((i+2))" bash -c "[ $RC = 2 ] && grep -q '${AA[$((i+1))]}' '$T/out' && grep -q '${AM[$((i+1))]}' '$T/out'"
  else chk "alt failover all six (model, account) pairs then blocked" bash -c "[ $RC = 3 ] && tail -1 '$E/gates.log' | grep -q '\"status\": \"blocked\"'"; fi; done
# --- implement.sh accepts T3-verified ui=true plans, rejects bad ones, stays pinned to the implementer ---
IR=$T/irepo; git init -q "$IR"; mkdir -p "$IR/src"; printf 'a\n' > "$IR/src/a.txt"; git -C "$IR" add -A; git -C "$IR" -c user.name=t -c user.email=t@e commit -qm base
IW=$T/iwt; git -C "$IR" worktree add -q --detach "$IW"; IE=$T/iev; mkdir -p "$IE" "$T/ocbin" "$T/calls"; : > "$T/calls/calls.log"
printf '#!/bin/bash\nprintf "%%s\\n" "$*" >> "$CALLS/calls.log"\nprintf "%%s\\n" "$OPENCODE_CONFIG_CONTENT" >> "$CALLS/config.log"\nexit 1\n' > "$T/ocbin/opencode"; chmod +x "$T/ocbin/opencode"
mkplan() { python3 - "$IE" "$1" "$2" "$3" "$4" "$5" <<'PY'
import hashlib, json, os, sys
ev, ui, route, model, account, effort = sys.argv[1:7]
target = os.path.join(ev, "plan-ui.json")
open(target, "w").write(json.dumps({"structured_output": {"gate": "plan", "tier": "medium", "acceptance_criteria": ["a"], "design": "d", "files": ["src/a.txt"], "tests": ["t"], "risks": [], "rollback": "r"}}, indent=1) + "\n")
row = {"gate": "plan", "status": "ok", "route": route, "model": model, "effort": effort, "account": account, "provenance_mode": "t3-verified", "engine": "t3-delegate", "file": "plan-ui.json", "file_sha256": hashlib.sha256(open(target, "rb").read()).hexdigest(), "key": "k", "session_id": "c", "parent_thread_id": "p"}
if ui != "-": row["ui"] = json.loads(ui)
open(os.path.join(ev, "gates.log"), "w").write(json.dumps(row) + "\n")
PY
}
im() { ( cd "$IW" && PATH="$T/ocbin:$PATH" CALLS="$T/calls" EVID="$IE" bash "$ROOT/scripts/implement.sh" medium --bootstrap none >"$T/iout" 2>&1 ); IRC=$?; }
implcase() { local n=$1 want=$2; shift 2; git -C "$IW" reset -q --hard; git -C "$IW" clean -qffdx; rm -rf "$IE"; mkdir -p "$IE"; : > "$T/calls/calls.log"; mkplan "$@"; im
  if [ "$want" = accept ]; then chk "$n" bash -c "[ $IRC = 3 ] && grep -qF -- '--model $IPIN' '$T/calls/calls.log' && grep -qF '\"model\": \"$IPIN\"' '$T/calls/config.log'"; else chk "$n" bash -c "[ $IRC = 2 ] && [ ! -s '$T/calls/calls.log' ]"; fi; }
implcase "implement accepts ui=true Opus medium plan" accept true "$P1ROUTE" "$P1MODEL" "${P1_ALL[0]}" "$(rt ui-effort plan medium '' "$P1ROUTE")"
implcase "implement accepts ui=true Neon high plan" accept true "$P3ROUTE" "$P3MODEL" "${P3_ALL[0]}" "$(rt ui-effort plan low '' "$P3ROUTE")"
implcase "implement accepts ui=true Neon medium plan" accept true "$P3ROUTE" "$P3MODEL" "${P3_ALL[0]}" medium
implcase "implement rejects ui=true Neon low plan" reject true "$P3ROUTE" "$P3MODEL" "${P3_ALL[0]}" low
implcase "implement rejects ui=true unknown route" reject true ghost ghost-model ghost-account high
implcase "implement rejects non-boolean ui" reject '"yes"' "$P1ROUTE" "$P1MODEL" "${P1_ALL[0]}" "$(rt ui-effort plan medium '' "$P1ROUTE")"
implcase "implement rejects non-UI Opus plan" reject - "$P1ROUTE" "$P1MODEL" "${P1_ALL[0]}" high
# --- premerge-and-merge.sh --diff validates ui=true only on plan/review against the UI contract ---
printf 'outside diff\n' > "$T/pdiff"; PK=$(shasum -a 256 "$T/pdiff" | awk '{print $1}')
pm_ev() { python3 - "$T/$1" "$2" "$PK" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}" <<'PY'
import hashlib, json, os, sys
ev, tier, key, cfgp, pr, pu, pe, ptier, rr, ru, re, extra = sys.argv[1:13]
cfg = json.load(open(cfgp)); routes = cfg["routes"]; os.makedirs(ev, exist_ok=True)
open(os.path.join(ev, "facts.md"), "w").write("facts\n"); fs = hashlib.sha256(open(os.path.join(ev, "facts.md"), "rb").read()).hexdigest()
open(os.path.join(ev, "PLAN.md"), "w").write("Tier: %s\n" % tier); open(os.path.join(ev, "tier-recheck-%s.md" % key), "w").write("Tier: %s\n" % tier)
rows = []
def write(gate, k, route, ui, eff, tier2, body):
    r = routes[route]; name = "%s-%s.json" % (gate, k); acct = {"opus": "opus-a", "alt_mid": "alt-mid-a", "neon": "neon-a", "deepseek": "deepseek-a"}.get(route, "fallback-a")
    open(os.path.join(ev, name), "w").write(json.dumps({"structured_output": body, "provenance": {}}) + "\n")
    d = {"ts": "2026-11-11T00:00:00Z", "gate": gate, "status": "ok", "verdict": "pass", "route": route, "model": r.get("model") or r.get("model_id"), "effort": eff, "account": acct, "driver_kind": r["driver_kind"], "tier": tier2, "key": k, "head_sha": k, "session_id": "c-%s" % gate, "parent_thread_id": "p", "engine": "t3-delegate", "provenance_mode": "t3-verified", "file": name, "file_sha256": hashlib.sha256(open(os.path.join(ev, name), "rb").read()).hexdigest()}
    if gate == "plan": d["facts_sha256"] = fs
    if ui != "absent": d["ui"] = json.loads(ui)
    rows.append(d)
if "epoch" in extra:
    e = cfg["gates"]["epoch"]; write("epoch", "e", e["route"], "true" if "ui-epoch" in extra else "false", e["efforts"][tier if tier in e["efforts"] else "high"], tier, {"gate": "epoch", "head_sha": key, "verdict": "pass", "summary": "ok", "findings": []})
write("plan", fs, pr, pu, pe, ptier, {"gate": "plan", "tier": ptier, "acceptance_criteria": ["a"], "design": "d", "files": ["f"], "tests": ["t"], "risks": [], "rollback": "r"})
write("review", key, rr, ru, re, tier, {"gate": "review", "head_sha": key, "verdict": "pass", "summary": "ok", "findings": []})
if "security" in extra:
    s = cfg["gates"]["security"]; write("security", key, s["route"], "true" if "ui-sec" in extra else "false", s["efforts"]["high"], tier, {"gate": "security", "head_sha": key, "verdict": "pass", "summary": "ok", "findings": []})
open(os.path.join(ev, "gates.log"), "w").write("".join(json.dumps(r) + "\n" for r in rows))
PY
}
pmrun() { ( cd "$T" && EVID="$T/$1" bash "$2" --diff "$T/pdiff" >"$T/pout" 2>&1 ); PRC=$?; }
pmc() { local n=$1 w=$2 s=$3; shift 3; pm_ev "$n" "$@"; pmrun "$n" "$s"; if [ "$w" = 0 ]; then chk "$n" test "$PRC" = 0; else chk "$n" test "$PRC" = 1; fi; }
PM=$ROOT/scripts/premerge-and-merge.sh; APM=$ALT/scripts/premerge-and-merge.sh; OP_EFF=$(rt ui-effort plan medium '' "$P1ROUTE"); PH=$(rt ui-effort plan high '' "$P1ROUTE"); RV_M=$(rt ui-effort review medium '' "$R1ROUTE"); RV_H=$(rt ui-effort review low '' "$R1ROUTE"); NEON_M=$(rt ui-effort plan medium '' "$P3ROUTE")
pmc "premerge accepts ui=true Opus plan/review" 0 "$PM" medium "$ROOT/routing.json" "$P1ROUTE" true "$OP_EFF" medium "$P1ROUTE" true "$RV_M" -
pmc "premerge accepts ui=true Neon medium plan/review" 0 "$PM" medium "$ROOT/routing.json" "$P3ROUTE" true "$NEON_M" medium "$R3ROUTE" true "$RV_M" -
pmc "premerge accepts active alt_mid" 0 "$APM" medium "$ALT/routing.json" "$A2R" true "$AE2" medium "$A2R" true "$(python3 -I "$ALT/scripts/routing_lib.py" ui-effort review medium '' "$A2R")" -
pmc "premerge rejects ui=true Neon medium plan high" 1 "$PM" medium "$ROOT/routing.json" "$P3ROUTE" true high medium "$R3ROUTE" true "$RV_M" -
pmc "premerge rejects ui=true Opus medium review high" 1 "$PM" medium "$ROOT/routing.json" "$P1ROUTE" true "$OP_EFF" medium "$P1ROUTE" true high -
pmc "premerge rejects ui=true Opus high-tier plan medium" 1 "$PM" high "$ROOT/routing.json" "$P1ROUTE" true medium high "$P1ROUTE" true "$RV_H" security
pmc "premerge rejects ui=true on security" 1 "$PM" high "$ROOT/routing.json" "$P1ROUTE" true "$PH" high "$P1ROUTE" true "$RV_H" security+ui-sec; chk "premerge security ui failure names the ui flag" grep -q 'security ui flag is not valid' "$T/pout"
pmc "premerge rejects ui=true on epoch" 1 "$PM" high "$ROOT/routing.json" "$P1ROUTE" true "$PH" high "$P1ROUTE" true "$RV_H" security+epoch+ui-epoch; chk "premerge epoch ui failure names the ui flag" grep -q 'epoch ui flag is not valid' "$T/pout"
pmc "premerge rejects non-boolean ui" 1 "$PM" medium "$ROOT/routing.json" "$P1ROUTE" '"yes"' "$OP_EFF" medium "$P1ROUTE" true "$RV_M" -; chk "premerge non-boolean ui failure names the ui flag" grep -q 'plan ui flag is not valid' "$T/pout"
pmc "premerge rejects non-UI Opus plan" 1 "$PM" medium "$ROOT/routing.json" "$P1ROUTE" absent "$OP_EFF" medium "$R3ROUTE" absent "$RV_M" -
pmc "premerge rejects non-UI Opus review" 1 "$PM" medium "$ROOT/routing.json" "$P3ROUTE" absent "$NEON_M" medium "$P1ROUTE" false "$RV_M" -
pm_ev "pm-opus-dk" medium "$ROOT/routing.json" "$P1ROUTE" true "$OP_EFF" medium "$P1ROUTE" true "$RV_M" -; python3 -c 'import json,sys; p=sys.argv[1]; dk=sys.argv[2]; r=[json.loads(l) for l in open(p)]; [x.update(driver_kind=dk) for x in r if x.get("route")=="opus"]; open(p,"w").write("".join(json.dumps(x)+"\n" for x in r))' "$T/pm-opus-dk/gates.log" "$P3DK"; pmrun "pm-opus-dk" "$PM"; chk "premerge rejects Opus on Neon's driver_kind" bash -c "[ $PRC = 1 ] && grep -q 'provenance' '$T/pout'"
printf '\n%s\n' "$([ $FAILED = 0 ] && echo 'UI ROUTING TESTS PASSED' || echo 'UI ROUTING TESTS FAILED')"
exit $FAILED
