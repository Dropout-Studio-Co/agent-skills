#!/usr/bin/env python3
"""gate_lib.py - T3-verified provenance, schema, round-cap, epoch and logging for gate.sh (stdlib only)."""
import argparse, hashlib, json, os, subprocess, sys, time
OPUS = ("anthropic", "opus", "claude-opus-5-5", "effort", ("claudeAgent", "claudeAgent_2", "claudeAgent_3"))
CONTRACTS = {"plan": ("google-antigravity", "neon", "gemini-4-neon", "thought_level", ("antigravity", "antigravity_2")),
             "review": OPUS, "security": OPUS, "epoch": OPUS}
RANK = {"low": 0, "medium": 1, "high": 2}
ERR_KEYS = ("stopReason", "stop_reason", "error", "errorCode", "errorMessage", "code", "type", "reason", "status", "message", "detail", "details")
USAGE_PAT = ("usage_limit", "rate_limit", "rate limit", "usage limit", "quota", "429")
SEVERITY = {"important": "Important", "nit": "Nit", "pre-existing": "Pre-existing"}
def now(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def same(left, right): return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
def parse(text):
    try: return json.loads(text)
    except (TypeError, ValueError): return None
def sha_file(path):
    try: return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError: return ""
def effort_for(gate, tier, trigger):
    if gate == "plan": return "medium" if tier == "low" else "high"
    if gate == "review": return "high" if tier == "high" or trigger else "medium"
    return "high" if gate == "security" or tier == "high" else "medium"
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
    for item in value.get("content") or []:
        parsed = parse(item.get("text")) if isinstance(item, dict) else None
        if isinstance(parsed, dict): return unwrap(parsed)
    return value
def t3(tool, payload):
    node = os.environ.get("T3_ACP_MCP_NODE", "").strip(); entry = os.environ.get("T3_ACP_MCP_ENTRYPOINT", "").strip()
    if not node: return None
    argv = [node] + ([entry] if entry else []) + ["acp-mcp-call", tool, json.dumps(payload)]
    try: done = subprocess.run(argv, capture_output=True, text=True, env=dict(os.environ, ELECTRON_RUN_AS_NODE="1"), timeout=300)
    except (OSError, ValueError, subprocess.SubprocessError): return None
    return unwrap(parse(done.stdout)) if done.returncode == 0 else None

def items_of(read):
    thread = read.get("thread") if isinstance(read.get("thread"), dict) else {}
    for source in (read, thread, read.get("activity"), thread.get("activity")):
        if isinstance(source, list) and source: return source
        if isinstance(source, dict) and isinstance(source.get("items"), list) and source["items"]: return source["items"]
    return []
def parse_json(text):
    text = (text if isinstance(text, str) else "").strip()
    if text.startswith("```"): text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    value = parse(text[start:end + 1]) if 0 <= start < end else None
    return value if isinstance(value, dict) else None
def full_text(thread, item):
    text = item.get("text") if isinstance(item.get("text"), str) else ""
    offset = item.get("nextTextOffset")
    for _ in range(40):
        if item.get("textTruncated") is not True or not isinstance(offset, int) or offset <= 0: break
        chunk = t3("t3_thread_read", {"threadId": thread, "itemId": item.get("itemId"), "textOffset": offset, "maxCharsPerItem": 20000})
        chunk = chunk if isinstance(chunk, dict) else {}
        found = chunk if isinstance(chunk.get("text"), str) else next((entry for entry in items_of(chunk) if entry.get("itemId") == item.get("itemId")), {})
        piece = found.get("text") if isinstance(found, dict) else None; following = found.get("nextTextOffset") if isinstance(found, dict) else None
        if not isinstance(piece, str) or not piece: break
        text += piece
        if not isinstance(following, int) or following <= offset: break
        offset = following
    return text
def candidates(read, thread):
    found = []
    for item in items_of(read):
        if not isinstance(item, dict): continue
        if item.get("type") == "assistant_message": value = parse_json(full_text(thread, item))
        elif item.get("type") == "dynamic_tool" and item.get("status") == "completed":
            call = parse_json(full_text(thread, item)) or {}
            raw = (call.get("input") or {}).get("json") if str(call.get("toolName") or "").endswith("t3_submit_output") and isinstance(call.get("input"), dict) else None
            value = parse_json(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else None)
        else: continue
        if isinstance(value, dict): found.append(value)
    return found
def thread_info(read, cfg):
    thread = read.get("thread") if isinstance(read.get("thread"), dict) else read
    selection = cfg.get("modelSelection") if isinstance(cfg.get("modelSelection"), dict) else cfg
    target = thread.get("target") if isinstance(thread.get("target"), dict) else {}
    runs = [run for run in (read.get("recentRuns") or thread.get("recentRuns") or []) if isinstance(run, dict)]
    latest = thread.get("latestRunId") or read.get("latestRunId")
    run = next((entry for entry in runs if latest and (entry.get("runId") or entry.get("id")) == latest), runs[0] if runs else {})
    meta = " ".join(str(node[key]) for node in (read, thread, run) if isinstance(node, dict) for key in ERR_KEYS if isinstance(node.get(key), (str, int, float)) and not isinstance(node.get(key), bool)).lower()
    notice = " ".join(item.get("text") for item in items_of(read) if isinstance(item, dict) and item.get("type") == "system_notice" and isinstance(item.get("text"), str)).lower()
    options = {}
    for source in (selection.get("options"), thread.get("options"), target.get("options")):
        if isinstance(source, dict): options.update(source)
        elif isinstance(source, list): options.update({entry["id"]: entry.get("value") for entry in source if isinstance(entry, dict) and entry.get("id")})
    pick = lambda *keys: next((source[key] for source in (selection, thread, read, run) for key in keys if isinstance(source, dict) and source.get(key)), "")
    usage = next((item for item in (thread.get("usage"), read.get("usage"), run.get("usage"), thread.get("tokenUsage")) if isinstance(item, dict)), {})
    return {"status": pick("status"), "parent": thread.get("parentThreadId") or read.get("parentThreadId") or "", "instance": pick("instanceId", "providerInstanceId"), "model": pick("model", "modelId"), "executed": run.get("executedModel") or pick("executedModel"), "run_model": run.get("model"), "run_instance": run.get("providerInstanceId"), "run_status": run.get("status"), "usage": usage, "options": options, "meta": meta, "notice": notice}

def validate(schema, value, path="$"):
    kind = schema.get("type")
    if kind == "object" or schema.get("required"):
        if not isinstance(value, dict): return path + " must be an object"
        problems = [path + " missing " + name for name in schema.get("required", []) if name not in value]
        problems += ["%s unexpected key %s" % (path, name) for name in value if schema.get("additionalProperties") is False and name not in (schema.get("properties") or {})]
        problems += [validate(sub, value[key], path + "." + key) for key, sub in (schema.get("properties") or {}).items() if key in value]
        return next((problem for problem in problems if problem), "")
    if kind == "array":
        if not isinstance(value, list): return path + " must be an array"
        return next((problem for problem in (validate(schema.get("items") or {}, item, "%s[%d]" % (path, index)) for index, item in enumerate(value)) if problem), "")
    if kind == "string":
        if not isinstance(value, str): return path + " must be a string"
        if "enum" in schema and value not in schema["enum"]: return "%s must be one of %s" % (path, schema["enum"])
    return ""
def metrics(evid, args, payload, model, round_no):
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
    for name in "evid gate tier record child-thread parent-thread key expected-head facts-sha base-ref base-sha diff-sha repo skill trigger".split(): parser.add_argument("--" + name, default="")
    args = parser.parse_args(); rows = load_rows(args.evid); trigger = args.trigger.strip() not in ("", "0")
    def authorized(row):
        path = os.path.join(args.evid, os.path.basename(row.get("file") or "-"))
        return (row.get("gate") == "epoch" and row.get("status") == "ok" and row.get("verdict") == "pass" and os.path.isfile(path) and row.get("file_sha256") == sha_file(path))
    epochs = [index for index, row in enumerate(rows) if authorized(row)]
    plans = [index for index, row in enumerate(rows) if row.get("gate") == "plan" and row.get("status") == "ok"]
    epoch_start = epochs[-1] + 1 if epochs else 0; plan_start = max(epoch_start, plans[-1] + 1 if plans else 0)
    used = sum(1 for index, row in enumerate(rows) if index >= plan_start and row.get("gate") == args.gate and row.get("status") == "ok")
    total = sum(1 for index, row in enumerate(rows) if index >= epoch_start and row.get("gate") == args.gate and row.get("status") == "ok")
    round_no = len(plans) + 1 if args.gate == "plan" else used + 1

    def emit(**fields):
        row = dict(ts=now(), task_id=os.path.basename(os.path.abspath(args.evid)), gate=args.gate, tier=args.tier, round=round_no, key=args.key, facts_sha256=args.facts_sha, base_ref=args.base_ref, base_sha=args.base_sha, diff_sha256=args.diff_sha, head_sha=args.expected_head, status="invalid", provenance_mode="", engine="t3-delegate", provider="", route="", model="", effort="", session_id=args.child_thread, parent_thread_id=args.parent_thread, account="", input_tokens=0, output_tokens=0, cost_usd=0, verdict="", reason="", file="", file_sha256="")
        row.update(fields); open(os.path.join(args.evid, "gates.log"), "a").write(json.dumps(row, sort_keys=True) + "\n")
    def stop(code, **fields):
        emit(**fields); return code

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
    read = t3("t3_thread_read", {"threadId": args.child_thread, "view": "activity", "maxCharsPerItem": 20000})
    cfg = t3("t3_thread_configure", {"threadId": args.child_thread})
    if not isinstance(read, dict) or not isinstance(cfg, dict): return stop(2, reason="T3 MCP verification unavailable (t3_thread_read/t3_thread_configure)")
    info = thread_info(read, cfg); provider, route, model, option, accounts = CONTRACTS[args.gate]
    effort = effort_for(args.gate, args.tier, trigger); chosen = info["options"].get(option) or ""
    obs = dict(model=info["model"], effort=chosen, account=info["instance"])
    if not info["parent"] or info["parent"] != args.parent_thread: return stop(2, reason="child thread parent %r does not match --parent-thread" % (info["parent"],), **obs)
    if args.gate != "plan" and ("refusal" in info["meta"] or "[cyber]" in info["meta"] or any(word in info["notice"] for word in ("[cyber]", "refusal", "refused", "declined"))): return stop(3, status="blocked", reason="cyber refusal", **obs)
    if any(pattern in info["meta"] or pattern in info["notice"] for pattern in USAGE_PAT): return stop(3, status="invalid", reason="usage_limit", **obs)
    if info["status"] != "completed": return stop(2, reason="child thread status is %r, not completed" % (info["status"],), **obs)
    if info["run_status"] and info["run_status"] not in ("completed", "succeeded", "success", "done"): return stop(2, reason="latest run status is %r, not completed" % (info["run_status"],), **obs)
    if args.expected_head and git("rev-parse", "HEAD") != args.expected_head: return stop(2, reason="HEAD moved during the gate run", **obs)
    if args.expected_head and git("status", "--porcelain", "--untracked-files=all"): return stop(2, reason="worktree is dirty after the gate run", **obs)
    if info["instance"] not in accounts: return stop(2, reason="child account %r is not a permitted %s instance" % (info["instance"], provider), **obs)
    if info["model"] != model: return stop(2, reason="child model is %r, expected %s" % (info["model"], model), **obs)
    if info["executed"] and info["executed"] != model: return stop(2, reason="child executed model is %r, expected %s" % (info["executed"], model), **obs)
    if info["run_model"] and info["run_model"] != model: return stop(2, reason="latest run model is %r, expected %s" % (info["run_model"], model), **obs)
    if info["run_instance"] and info["run_instance"] not in accounts: return stop(2, reason="latest run account %r is not a permitted %s instance" % (info["run_instance"], provider), **obs)
    if chosen != effort: return stop(2, reason="child %s is %r, expected %s" % (option, chosen, effort), **obs)
    try: payload = json.load(open(args.record))
    except (OSError, ValueError) as problem: return stop(2, reason="--record is not readable JSON: %s" % problem, **obs)
    if isinstance(payload.get("structured_output"), dict): payload = payload["structured_output"]
    try: schema = json.load(open(os.path.join(args.skill, "plan-schema.json" if args.gate == "plan" else "review-schema.json")))
    except (OSError, ValueError) as problem: return stop(2, reason="gate schema unavailable: %s" % problem, **obs)
    if (problem := validate(schema, payload)): return stop(2, reason="record schema: " + problem, **obs)
    if payload.get("gate") != args.gate: return stop(2, reason="record gate %r does not match %s" % (payload.get("gate"), args.gate), **obs)
    if args.gate == "plan" and payload.get("tier") != args.tier: return stop(2, reason="record tier %r does not match %s" % (payload.get("tier"), args.tier), **obs)
    if args.gate != "plan" and payload.get("head_sha") != args.key: return stop(2, reason="record head_sha %r does not match key %s" % (payload.get("head_sha"), args.key), **obs)
    if not any(same(payload, candidate) for candidate in candidates(read, args.child_thread)): return stop(2, reason="record payload does not match the child thread output", **obs)
    verdict = payload.get("verdict", "pass")
    if verdict == "pass" and any(isinstance(item, dict) and item.get("severity") == "important" for item in payload.get("findings") or []): return stop(2, reason="verdict pass is invalid alongside an Important finding", **obs)
    name = "%s-%s.json" % (args.gate, args.key)
    provenance = dict(provenance_mode="t3-verified", engine="t3-delegate", provider=provider, route=route, model=model, effort=effort, session_id=args.child_thread, parent_thread_id=args.parent_thread, account=info["instance"], verified_at=now())
    target = os.path.join(args.evid, name); open(target, "w").write(json.dumps({"structured_output": payload, "provenance": provenance}, indent=2, sort_keys=True) + "\n")
    usage = info["usage"]; count = lambda *keys: next((usage[key] for key in keys if isinstance(usage.get(key), (int, float)) and not isinstance(usage.get(key), bool)), 0)
    emit(status="ok", verdict=verdict, file=name, file_sha256=sha_file(target), input_tokens=count("inputTokens", "input_tokens"), output_tokens=count("outputTokens", "output_tokens"), cost_usd=count("costUsd", "cost_usd", "totalCostUsd"), provenance_mode="t3-verified", provider=provider, route=route, model=model, effort=effort, account=info["instance"])
    metrics(args.evid, args, payload, model, round_no)
    print("%s %s model=%s effort=%s account=%s verdict=%s file=%s" % (args.gate, args.key, model, effort, info["instance"], verdict, name))
    return 0 if args.gate == "plan" or verdict == "pass" else 1
if __name__ == "__main__": sys.exit(main())
