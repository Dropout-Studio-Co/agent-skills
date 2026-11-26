#!/usr/bin/env python3
"""gate_lib.py - T3-verified provenance, schema, round-cap, epoch and logging for gate.sh (stdlib only)."""
import argparse, hashlib, json, os, subprocess, sys, time
sys.dont_write_bytecode = True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import routing_lib as routing
RANK = {"low": 0, "medium": 1, "high": 2}; SEVERITY = {"important": "Important", "nit": "Nit", "pre-existing": "Pre-existing"}
ERR_KEYS = ("stopReason", "stop_reason", "error", "errorCode", "errorMessage", "code", "type", "reason", "status", "message", "detail", "details")
USAGE_PAT = ("usage_limit", "rate_limit", "rate limit", "usage limit", "quota", "429")
def now(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def same(left, right): return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
def parse(text):
    try: return json.loads(text)
    except (TypeError, ValueError): return None
def sha_file(path):
    try: return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError: return ""
def git(*argv):
    try: return subprocess.run(("git",) + argv, capture_output=True, text=True).stdout.strip()
    except OSError: return None
def load_rows(evid):
    try: lines = open(os.path.join(evid, "gates.log"), errors="replace").read().splitlines()
    except OSError: return []
    return [row for row in map(parse, lines) if isinstance(row, dict)]
def unwrap(value):
    if isinstance(value, str): value = parse(value)
    if isinstance(value, list): value = next((item for item in value if isinstance(item, dict)), {})
    if not isinstance(value, dict) or value.get("isError") is True: return None
    for key in ("structuredContent", "result", "data"):
        if isinstance(value.get(key), dict): return unwrap(value[key])
    parsed = [parse(item.get("text")) if isinstance(item, dict) else None for item in value.get("content") or []]
    nested = next((entry for entry in parsed if isinstance(entry, dict)), None)
    return unwrap(nested) if nested is not None else value
def t3(tool, payload):
    node = os.environ.get("T3_ACP_MCP_NODE", "").strip(); entry = os.environ.get("T3_ACP_MCP_ENTRYPOINT", "").strip()
    if not node: return None
    argv = [node] + ([entry] if entry else []) + ["acp-mcp-call", tool, json.dumps(payload)]
    try: done = subprocess.run(argv, capture_output=True, text=True, env=dict(os.environ, ELECTRON_RUN_AS_NODE="1"), timeout=120)
    except (OSError, ValueError, subprocess.SubprocessError): return None
    return unwrap(parse(done.stdout)) if done.returncode == 0 else None
def items_of(read):
    thread = read.get("thread") if isinstance(read.get("thread"), dict) else {}
    return next((source if isinstance(source, list) else source["items"] for source in (read, thread, read.get("activity"), thread.get("activity")) if (isinstance(source, list) and source) or (isinstance(source, dict) and isinstance(source.get("items"), list) and source["items"])), [])
def parse_json(text):
    text = (text if isinstance(text, str) else "").strip(); text = text.split("\n", 1)[-1].rsplit("```", 1)[0] if text.startswith("```") else text
    start, end = text.find("{"), text.rfind("}")
    return (lambda value: value if isinstance(value, dict) else None)(parse(text[start:end + 1]) if 0 <= start < end else None)
def full_text(thread, item):
    text = item.get("text") if isinstance(item.get("text"), str) else ""
    offset = item.get("nextTextOffset")
    for _ in range(40):
        if item.get("textTruncated") is not True or not isinstance(offset, int) or offset <= 0: break
        chunk = t3("t3_thread_read", {"threadId": thread, "itemId": item.get("itemId"), "textOffset": offset, "maxCharsPerItem": 20000}); chunk = chunk if isinstance(chunk, dict) else {}
        found = chunk if isinstance(chunk.get("text"), str) else next((entry for entry in items_of(chunk) if entry.get("itemId") == item.get("itemId")), {})
        piece = found.get("text") if isinstance(found, dict) else None; following = found.get("nextTextOffset") if isinstance(found, dict) else None
        if not isinstance(piece, str) or not piece: break
        text += piece
        if not isinstance(following, int) or following <= offset: break
        offset = following
    return text
def output_of(read, thread):
    found = {}
    for item in items_of(read):
        if not isinstance(item, dict): continue
        if item.get("type") == "assistant_message": slot, value = "message", parse_json(full_text(thread, item))
        elif item.get("type") == "dynamic_tool" and item.get("status") == "completed":
            call = parse_json(full_text(thread, item)) or {}
            raw = (call.get("input") or {}).get("json") if str(call.get("toolName") or "").endswith("t3_submit_output") and isinstance(call.get("input"), dict) else None
            slot, value = "submit", parse_json(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else None)
        else: continue
        if isinstance(value, dict): found[slot] = value
    return found.get("submit") or found.get("message")
def thread_info(read, cfg, keys):
    thread = read.get("thread") if isinstance(read.get("thread"), dict) else read
    selection = cfg.get("modelSelection") if isinstance(cfg.get("modelSelection"), dict) else cfg
    runs = [run for run in (read.get("recentRuns") or thread.get("recentRuns") or []) if isinstance(run, dict)]
    latest = thread.get("latestRunId") or read.get("latestRunId")
    run = next((entry for entry in runs if latest and (entry.get("runId") or entry.get("id")) == latest), runs[0] if runs else {})
    meta = " ".join(str(node[key]) for node in (read, thread, run) if isinstance(node, dict) for key in ERR_KEYS if isinstance(node.get(key), (str, int, float)) and not isinstance(node.get(key), bool)).lower(); notice = " ".join(item.get("text") for item in items_of(read) if isinstance(item, dict) and item.get("type") == "system_notice" and isinstance(item.get("text"), str)).lower()
    options = {}
    for source in (selection.get("options"), thread.get("options"), (thread.get("target") or {}).get("options")):
        if isinstance(source, dict): options.update(source)
        elif isinstance(source, list): options.update({entry["id"]: entry.get("value") for entry in source if isinstance(entry, dict) and entry.get("id")})
    seen = []
    for source in [node for node in [selection, thread, read] + runs if isinstance(node, dict)]:
        opts = source.get("options")
        effort = next((opts.get(key) for key in keys if isinstance(opts, dict) and opts.get(key)), "") if isinstance(opts, dict) else next((entry.get("value") for entry in opts or [] if isinstance(entry, dict) and entry.get("id") in keys), "")
        strings = lambda *keys: next((source[key] for key in keys if isinstance(source.get(key), str) and source.get(key)), "")
        seen.append(dict(model=strings("model", "modelId"), executed=strings("executedModel"), instance=strings("instanceId", "providerInstanceId"), effort=effort if isinstance(effort, str) else ""))
    pick = lambda *keys: next((source[key] for source in (selection, thread, read, run) for key in keys if isinstance(source, dict) and source.get(key)), "")
    usage = next((item for item in (thread.get("usage"), read.get("usage"), run.get("usage"), thread.get("tokenUsage")) if isinstance(item, dict)), {})
    stops = [node[key] for node in [selection, thread, read, run] + runs + items_of(read) if isinstance(node, dict) for key in ("stop_reason", "stopReason") if isinstance(node.get(key), str) and node.get(key)] or [""]
    return {"status": pick("status"), "parent": thread.get("parentThreadId") or read.get("parentThreadId") or "", "instance": pick("instanceId", "providerInstanceId"), "model": pick("model", "modelId"), "run_status": run.get("status"), "usage": usage, "options": options, "meta": meta, "notice": notice, "seen": seen, "stop": stops[0], "refusal": "refusal" in stops, "cyber": "[cyber]" in meta or "[cyber]" in notice}
def validate(schema, value, path="$"):
    if schema.get("type") == "object" or schema.get("required"):
        if not isinstance(value, dict): return path + " must be an object"
        problems = [path + " missing " + name for name in schema.get("required", []) if name not in value]
        problems += ["%s unexpected key %s" % (path, name) for name in value if schema.get("additionalProperties") is False and name not in (schema.get("properties") or {})]
        problems += [validate(sub, value[key], path + "." + key) for key, sub in (schema.get("properties") or {}).items() if key in value]
        return next((problem for problem in problems if problem), "")
    if schema.get("type") == "array" and not isinstance(value, list): return path + " must be an array"
    if schema.get("type") == "array": return next((problem for problem in (validate(schema.get("items") or {}, item, "%s[%d]" % (path, index)) for index, item in enumerate(value)) if problem), "")
    if schema.get("type") == "string" and not isinstance(value, str): return path + " must be a string"
    if schema.get("type") == "string" and "enum" in schema and value not in schema["enum"]: return "%s must be one of %s" % (path, schema["enum"])
    return ""
def log_metrics(evid, args, payload, model, round_no):
    if args.gate not in ("review", "security"): return
    path = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state"), "review-metrics", "findings.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as handle:
            for finding in [item for item in payload.get("findings") or [] if isinstance(item, dict)]:
                handle.write(json.dumps(dict(date=now()[:10], task=os.path.basename(os.path.abspath(evid)), repo=args.repo or "outside", sha=args.key, tier=args.tier, round=round_no, reviewer=model, outcome="reported", **{"class": args.gate}, severity=SEVERITY.get(finding.get("severity", ""), finding.get("severity", "")))) + "\n")
    except OSError: return
def main():
    parser = argparse.ArgumentParser(add_help=False)
    for name in "evid gate tier record child-thread parent-thread key expected-head facts-sha base-ref base-sha diff-sha repo skill trigger ui reason".split(): parser.add_argument("--" + name, default="")
    parser.add_argument("--log-invalid", action="store_true")
    args = parser.parse_args(); rows = load_rows(args.evid); trigger = args.trigger.strip() not in ("", "0"); ui = args.ui.strip() not in ("", "0")
    def authorized(row):
        path = os.path.join(args.evid, os.path.basename(row.get("file") or "-")); return row.get("gate") == "epoch" and row.get("status") == "ok" and row.get("verdict") == "pass" and os.path.isfile(path) and row.get("file_sha256") == sha_file(path)
    epochs = [index for index, row in enumerate(rows) if authorized(row)]
    plans = [index for index, row in enumerate(rows) if row.get("gate") == "plan" and row.get("status") == "ok"]
    epoch_start = epochs[-1] + 1 if epochs else 0; plan_start = max(epoch_start, plans[-1] + 1 if plans else 0)
    last_ok = max((index for index, row in enumerate(rows) if row.get("gate") == args.gate and row.get("status") == "ok"), default=-1)
    used = sum(1 for index, row in enumerate(rows) if index >= plan_start and row.get("gate") == args.gate and row.get("status") == "ok"); total = sum(1 for index, row in enumerate(rows) if index >= epoch_start and row.get("gate") == args.gate and row.get("status") == "ok")
    round_no = len(plans) + 1 if args.gate == "plan" else used + 1
    def emit(**fields):
        row = dict(ts=now(), task_id=os.path.basename(os.path.abspath(args.evid)), gate=args.gate, tier=args.tier, round=round_no, key=args.key, facts_sha256=args.facts_sha, base_ref=args.base_ref, base_sha=args.base_sha, diff_sha256=args.diff_sha, head_sha=args.expected_head, status="invalid", provenance_mode="", engine="t3-delegate", provider="", route="", model="", effort="", ui=ui, session_id=args.child_thread, parent_thread_id=args.parent_thread, account="", input_tokens=0, output_tokens=0, cost_usd=0, verdict="", reason="", file="", file_sha256="")
        row.update(fields); open(os.path.join(args.evid, "gates.log"), "a").write(json.dumps(row, sort_keys=True) + "\n")
    def stop(code, **fields): emit(**fields); return code
    if args.log_invalid: return stop(2, reason=args.reason or "gate.sh refused")
    if ui and args.gate not in routing.UI_GATES: return stop(2, reason="--ui is valid on plan and review only")
    try: RCFG = routing.load()
    except ValueError as problem: return stop(2, reason="invalid routing.json: %s" % problem)
    if args.gate == "epoch":
        caps = [row for row in rows[epoch_start:] if row.get("gate") in ("review", "security") and row.get("status") == "blocked" and row.get("reason") == "round cap after re-plan"]
        if not caps: return stop(2, reason="epoch needs a review/security round-cap block")
        if RANK.get(args.tier, 0) < RANK.get(caps[-1].get("tier", ""), 0): return stop(2, reason="epoch tier is below the blocked gate tier")
        if any(row.get("gate") == "epoch" and row.get("status") == "ok" and row.get("verdict") == "fail" for row in rows[epoch_start:]): return stop(3, status="blocked", reason="epoch denied for this block")
        if len(epochs) >= 2: return stop(3, status="blocked", reason="epoch ceiling: 2 authorized per task")
    elif args.gate != "plan" and total >= 6: return stop(3, status="blocked", reason="round cap after re-plan")
    elif used >= 3: return stop(4, status="cap", reason="3 ok rounds reached; re-plan required")
    if args.child_thread == args.parent_thread: return stop(2, reason="child thread id equals the parent thread id")
    if any(row.get("session_id") == args.child_thread and row.get("status") == "ok" for row in rows): return stop(2, reason="child thread id was already recorded on an ok gate row")
    if args.gate in ("review", "security") and epochs and not any(index > epochs[-1] and row.get("gate") == "plan" and row.get("status") == "ok" for index, row in enumerate(rows)): return stop(2, reason="a passing epoch requires a fresh plan before %s" % args.gate)
    read = t3("t3_thread_read", {"threadId": args.child_thread, "view": "activity", "maxCharsPerItem": 20000}); cfg = t3("t3_thread_configure", {"threadId": args.child_thread})
    if not isinstance(read, dict) or not isinstance(cfg, dict): return stop(2, reason="T3 MCP verification unavailable (t3_thread_read/t3_thread_configure)")
    info = thread_info(read, cfg, routing.option_keys(RCFG)); contracts = routing.gate_contracts(RCFG, args.gate, ui=ui)
    hit = next((c for c in contracts if c[2] == info["model"] and info["instance"] in c[4]), contracts[0]); provider, route, model, option, accounts = hit
    effort = routing.effort_for(RCFG, args.gate, args.tier, trigger or (args.gate == "review" and round_no >= 3), ui=ui, route=route); chosen = info["options"].get(option) or ""
    obs = dict(model=info["model"], effort=chosen, account=info["instance"])
    def bad(reason):
        prior = any(row.get("gate") == args.gate and row.get("key") == args.key and row.get("status") == "invalid" and str(row.get("reason", "")).startswith("invalid output") for row in rows[last_ok + 1:])
        if prior: return stop(3, status="blocked", reason="invalid output after retry", **obs)
        return stop(2, reason="invalid output: " + reason, **obs)
    if not info["parent"] or info["parent"] != args.parent_thread: return stop(2, reason="child thread parent %r does not match --parent-thread" % (info["parent"],), **obs)
    if (args.gate != "plan" or ui) and (info["refusal"] or info["cyber"]): return stop(3, status="blocked", reason="cyber refusal", **obs)
    if any(pattern in info["meta"] or pattern in info["notice"] for pattern in USAGE_PAT):
        tried = {(row.get("model"), row.get("account")) for row in rows[last_ok + 1:] if (row.get("gate"), row.get("key"), row.get("status"), row.get("reason")) == (args.gate, args.key, "invalid", "usage_limit")} | {(info["model"], info["instance"])}
        rest = [pair for pair in [(c[2], acct) for c in contracts for acct in c[4]] if pair not in tried]
        if not rest: return stop(3, status="blocked", reason="%s quota exhausted on every instance" % model, **obs)
        emit(status="invalid", reason="usage_limit", **obs)
        sys.stderr.write("gate.sh: usage limit on %s; retry this gate on %s %s\n" % (info["instance"] or "unknown", rest[0][1], rest[0][0])); return 2
    if info["status"] != "completed": return stop(2, reason="child thread status is %r, not completed" % (info["status"],), **obs)
    if info["run_status"] and info["run_status"] not in ("completed", "succeeded", "success", "done"): return stop(2, reason="latest run status is %r, not completed" % (info["run_status"],), **obs)
    if args.expected_head and git("rev-parse", "HEAD") != args.expected_head: return stop(2, reason="HEAD moved during the gate run", **obs)
    if args.expected_head and git("status", "--porcelain", "--untracked-files=all"): return stop(2, reason="worktree is dirty after the gate run", **obs)
    if info["instance"] not in accounts: return stop(2, reason="child account %r is not a permitted %s instance" % (info["instance"], provider), **obs)
    if info["model"] != model: return stop(2, reason="child model is %r, expected %s" % (info["model"], model), **obs)
    if chosen != effort: return stop(2, reason="child %s is %r, expected %s" % (option, chosen, effort), **obs)
    for seen in info["seen"]:
        for field, expected, label in (("model", model, "model"), ("executed", model, "executed model"), ("effort", effort, option)):
            if seen[field] and seen[field] != expected: return stop(2, reason="observed %s is %r, expected %s" % (label, seen[field], expected), **obs)
        if seen["instance"] and (seen["instance"] != info["instance"] or seen["instance"] not in accounts): return stop(2, reason="observed account %r disagrees with the modelSelection instance %r" % (seen["instance"], info["instance"]), **obs)
    try: payload = json.load(open(args.record))
    except (OSError, ValueError) as problem: return stop(2, reason="--record is not readable JSON: %s" % problem, **obs)
    if not isinstance(payload, dict): return bad("--record payload is not a JSON object")
    if isinstance(payload.get("structured_output"), dict): payload = payload["structured_output"]
    try: schema = json.load(open(os.path.join(args.skill, "plan-schema.json" if args.gate == "plan" else "review-schema.json")))
    except (OSError, ValueError) as problem: return stop(2, reason="gate schema unavailable: %s" % problem, **obs)
    if (problem := validate(schema, payload)): return bad(problem)
    if payload.get("gate") != args.gate: return bad("record gate %r does not match %s" % (payload.get("gate"), args.gate))
    if args.gate == "plan" and payload.get("tier") != args.tier: return bad("record tier %r does not match %s" % (payload.get("tier"), args.tier))
    if args.gate != "plan" and payload.get("head_sha") != args.key: return bad("record head_sha %r does not match key %s" % (payload.get("head_sha"), args.key))
    final = output_of(read, args.child_thread)
    if not isinstance(final, dict) or not same(payload, final): return bad("record payload does not match the child thread output (final submission only)")
    verdict = payload.get("verdict", "pass")
    if verdict == "pass" and any(isinstance(item, dict) and item.get("severity") == "important" for item in payload.get("findings") or []): return bad("verdict pass is invalid alongside an Important finding")
    name = "%s-%s.json" % (args.gate, args.key)
    provenance = dict(provenance_mode="t3-verified", engine="t3-delegate", provider=provider, route=route, model=model, effort=effort, ui=ui, session_id=args.child_thread, parent_thread_id=args.parent_thread, account=info["instance"], verified_at=now())
    target = os.path.join(args.evid, name); open(target, "w").write(json.dumps({"structured_output": payload, "provenance": provenance}, indent=2, sort_keys=True) + "\n")
    usage = info["usage"]; count = lambda *keys: next((usage[key] for key in keys if isinstance(usage.get(key), (int, float)) and not isinstance(usage.get(key), bool)), 0)
    emit(status="ok", verdict=verdict, file=name, file_sha256=sha_file(target), input_tokens=count("inputTokens", "input_tokens"), output_tokens=count("outputTokens", "output_tokens"), cost_usd=count("costUsd", "cost_usd", "totalCostUsd"), provenance_mode="t3-verified", provider=provider, route=route, model=model, effort=effort, account=info["instance"])
    log_metrics(args.evid, args, payload, model, round_no)
    print("%s %s model=%s effort=%s account=%s verdict=%s file=%s" % (args.gate, args.key, model, effort, info["instance"], verdict, name))
    return 0 if args.gate == "plan" or verdict == "pass" else 1
if __name__ == "__main__": sys.exit(main())
