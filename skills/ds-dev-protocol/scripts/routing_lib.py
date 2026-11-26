#!/usr/bin/env python3
"""routing_lib.py - the ds-dev-protocol routing source of truth reader/validator/syncer (stdlib only, Python 3.9+).
routing.json holds every route, model, provider, option key, account, cost cap and tier/trigger effort; this
module validates it, derives roles and pinned specs, and syncs opencode/opencode.json and SKILL.md atomically.
Paths are anchored to this file; no environment override or working-directory lookup is honored.
"""
import json, math, os, re, sys, tempfile
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTING_PATH = os.path.join(SKILL_DIR, "routing.json")
START, END = "<!-- routing:start -->", "<!-- routing:end -->"
GATES, MAX_BYTES, MAX_SKILL, MAX_DESC = ("plan", "review", "security", "epoch"), 65536, 23800, 450
TIERS = {"plan": ("low", "medium", "high"), "review": ("low", "medium", "high"), "security": ("high",), "epoch": ("medium", "high")}
ROUTE_KEY, SHORT = re.compile(r"^[a-z0-9][a-z0-9_-]*$"), {"medium": "Med", "high": "High"}
def read(path):
    if os.path.islink(path): raise ValueError("%s is a symlink" % os.path.basename(path))
    try: data = open(path, "rb").read()
    except OSError as problem: raise ValueError("%s is unreadable: %s" % (os.path.basename(path), problem))
    if len(data) > MAX_BYTES: raise ValueError("%s is larger than %d bytes" % (os.path.basename(path), MAX_BYTES))
    try: return data.decode("utf-8")
    except UnicodeDecodeError: raise ValueError("%s is not UTF-8" % os.path.basename(path))
def ident(value, what, slash=False):
    if not isinstance(value, str) or not value: raise ValueError("%s must be a non-empty string" % what)
    if any(ord(ch) < 32 or ch.isspace() or ch == "#" for ch in value): raise ValueError("%s has whitespace, a control character or '#'" % what)
    if slash and "/" in value: raise ValueError("%s must not contain '/'" % what)
    return value
def label(value, what):
    if not isinstance(value, str) or not value.strip() or any(ord(ch) < 32 or ch in "'|`" for ch in value):
        raise ValueError("%s must be non-empty and hold no control character, quote, pipe or backtick" % what)
    return value
def effort(value, allowed, what):
    if not isinstance(value, str) or value not in allowed: raise ValueError("%s %r is not in allowed_efforts" % (what, value))
    return value
def load(skill_dir=None):
    cfg = json.loads(read(os.path.join(os.path.abspath(skill_dir or SKILL_DIR), "routing.json")))
    if not isinstance(cfg, dict) or isinstance(cfg.get("schema_version"), bool) or cfg.get("schema_version") != 1:
        raise ValueError("routing.json must be an object with schema_version 1")
    allowed = cfg.get("allowed_efforts")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(value, str) for value in allowed) or len(set(allowed)) != len(allowed) or set(allowed) - {"medium", "high"}:
        raise ValueError("allowed_efforts must be a non-empty subset of [medium, high]")
    routes, gates = cfg.get("routes"), cfg.get("gates")
    if not isinstance(routes, dict) or not routes: raise ValueError("routes must be a non-empty object")
    for key, route in routes.items():
        if not (isinstance(key, str) and ROUTE_KEY.match(key) and isinstance(route, dict) and ("model" in route or "model_id" in route)):
            raise ValueError("invalid route %r: needs a lowercase key and model or model_id" % (key,))
        label(route.get("label"), "route %s label" % key); ident(route.get("provider"), "route %s provider" % key)
        for field in ("model", "model_id", "option_key"):
            if field in route: ident(route[field], "route %s %s" % (key, field))
        accounts, cost = route.get("accounts"), route.get("max_cost_usd")
        if not isinstance(accounts, list) or not accounts or len(set(map(str, accounts))) != len(accounts):
            raise ValueError("route %s accounts must be a non-empty list of unique names" % key)
        for account in accounts: ident(account, "route %s account" % key)
        if "max_cost_usd" in route and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0):
            raise ValueError("route %s max_cost_usd must be a non-negative number" % key)
    for role, fields in (("conductor", ("model", "option_key")), ("implementer", ("model_id",))):
        spec = cfg.get(role); route = routes.get(spec.get("route")) if isinstance(spec, dict) and isinstance(spec.get("route"), str) else None
        if not isinstance(route, dict) or any(field not in route for field in fields): raise ValueError("%s must name a route with %s" % (role, " and ".join(fields)))
        effort(spec.get("effort"), allowed, "%s effort" % role)
    imp = routes[cfg["implementer"]["route"]]
    if "max_cost_usd" not in imp: raise ValueError("implementer route needs max_cost_usd")
    ident(imp["provider"], "implementer provider", slash=True); ident(imp["model_id"], "implementer model_id", slash=True)
    if not isinstance(gates, dict) or set(gates) != set(GATES): raise ValueError("gates must be exactly plan, review, security, epoch")
    for gate in GATES:
        spec = gates[gate]; route = routes.get(spec.get("route")) if isinstance(spec, dict) and isinstance(spec.get("route"), str) else None
        if not isinstance(route, dict) or "model" not in route or "option_key" not in route: raise ValueError("gate %s needs a route with model and option_key" % gate)
        efforts = spec.get("efforts")
        if not isinstance(efforts, dict) or set(efforts) != set(TIERS[gate]): raise ValueError("gate %s efforts must be %s" % (gate, "/".join(TIERS[gate])))
        for tier, value in efforts.items(): effort(value, allowed, "gate %s %s effort" % (gate, tier))
        if "trigger_effort" in spec: effort(spec["trigger_effort"], allowed, "gate %s trigger_effort" % gate)
    return cfg
def gate_contract(cfg, gate):
    spec = cfg["gates"][gate]; route = cfg["routes"][spec["route"]]
    return route["provider"], spec["route"], route["model"], route["option_key"], tuple(route["accounts"])
def option_keys(cfg):
    return tuple(dict.fromkeys(route["option_key"] for route in cfg["routes"].values() if route.get("option_key")))
def effort_for(cfg, gate, tier, trigger=False):
    spec = cfg["gates"][gate]
    if trigger and tier == "medium" and spec.get("trigger_effort"): return spec["trigger_effort"]
    if tier not in spec["efforts"]: raise ValueError("gate %s has no %s tier" % (gate, tier))
    return spec["efforts"][tier]
def allowed_efforts_for(cfg, gate, tier):
    out = {effort_for(cfg, gate, tier)}
    if cfg["gates"][gate].get("trigger_effort") and tier == "medium": out.add(cfg["gates"][gate]["trigger_effort"])
    return out
def implementer(cfg):
    spec = cfg["implementer"]; route = cfg["routes"][spec["route"]]
    model = "%s/%s" % (route["provider"], route["model_id"])
    return dict(route=spec["route"], provider=route["provider"], model_id=route["model_id"], model=model,
                effort=spec["effort"], pinned="%s#%s" % (model, spec["effort"]), account=route["accounts"][0],
                accounts=tuple(route["accounts"]), max_cost_usd=route["max_cost_usd"], label=route["label"])
def conductor(cfg):
    spec = cfg["conductor"]; route = cfg["routes"][spec["route"]]
    return dict(route=spec["route"], provider=route["provider"], model=route["model"], option_key=route["option_key"],
                accounts=tuple(route["accounts"]), effort=spec["effort"], label=route["label"])
def chain(accounts): return " → ".join("`%s`" % name for name in accounts)
def describe(cfg):
    cond, imp = conductor(cfg), implementer(cfg)
    planner = cfg["routes"][cfg["gates"]["plan"]["route"]]["label"]
    who = cond["label"] if planner == cond["label"] else "%s and %s" % (cond["label"], planner)
    efforts = lambda gate: "/".join(SHORT[value] for value in cfg["gates"][gate]["efforts"].values())
    return ("ds-dev-protocol: 100%% end-to-end completion over presentation. Orchestration V2 4 roles: %s conducts (%s always) "
            "and plans (%s) via gate.sh plan --record; %s %s is sole implementer via implement.sh, no model fallback; %s gates "
            "review, security, epoch (%s, %s, %s). Risk tiers, T3 evidence, head-SHA gates, PR delivery. Always on: every dev task."
            % (who, cond["effort"].capitalize(), efforts("plan"), imp["label"], imp["effort"],
               cfg["routes"][cfg["gates"]["review"]["route"]]["label"], efforts("review"), efforts("security"), efforts("epoch")))
def render_block(cfg):
    cond, imp = conductor(cfg), implementer(cfg)
    plan, review, sec, epoch = (cfg["gates"][name] for name in GATES)
    planner, reviewer = cfg["routes"][plan["route"]], cfg["routes"][sec["route"]]
    other = [value for value in cfg["allowed_efforts"] if value != cond["effort"]]
    used = [cfg["routes"][k] for k in dict.fromkeys([cfg["conductor"]["route"], cfg["implementer"]["route"]] + [cfg["gates"][g]["route"] for g in GATES])]
    chains, solo = [chain(r["accounts"]) for r in used if len(r["accounts"]) > 1], ["`%s` alone" % r["accounts"][0] for r in used if len(r["accounts"]) == 1]
    non_cond = "/".join(dict.fromkeys(r["label"] for r in (imp, reviewer) if r["label"] != cond["label"]))
    rows = [
        "Four roles, one model each, no substitution:", "",
        "| Role | Model and effort (%s only) | Path |" % "/".join(cfg["allowed_efforts"]), "|---|---|---|",
        "| Conductor | %s `%s`, `%s` always (never `%s` or other) | this T3 Code thread (%s) |" % (cond["label"], cond["model"], cond["effort"], other[0] if other else "any other", ", ".join(cond["accounts"])),
        "| Architect & Planner | %s `%s`, `%s` Low, `%s` Medium, `%s` High | fresh `delegate_task` (%s), then `gate.sh plan --record` |" % (planner["label"], planner["model"], plan["efforts"]["low"], plan["efforts"]["medium"], plan["efforts"]["high"], chain(planner["accounts"])),
        "| Implementer | %s `%s`, `variant: %s` always | `scripts/implement.sh`, the documented mechanical runner, no OS sandbox; sole implementer, no fallback |" % (imp["label"], imp["pinned"], imp["effort"]),
        "| Reviewer, Security & Epoch | %s `%s`, review `%s`/`%s` Low/Medium and `%s` High (`%s` with `--trigger`); security `%s`; epoch `%s`/`%s` | fresh `delegate_task` (%s), then `gate.sh <gate> --record` |" % (reviewer["label"], reviewer["model"], review["efforts"]["low"], review["efforts"]["medium"], review["efforts"]["high"], review.get("trigger_effort", review["efforts"]["high"]), sec["efforts"]["high"], epoch["efforts"]["medium"], epoch["efforts"]["high"], chain(reviewer["accounts"])),
        "",
        "- **Same-provider instance failover only:** a child that hits `usage_limit`, or a reviewer child stalled holding a turn "
        "open, is `task_cancel`led and re-dispatched as a fresh `delegate_task` with the full packet and schema on the next "
        "enabled same-provider, same-model, same-effort instance: %s. Never cross a provider or model, never ask. When every "
        "instance is exhausted, log `blocked` (exit 3), record `STATUS: blocked external — <model> quota exhausted; waiting for "
        "reset` with `Routes tried:`, finish unaffected work and stop cleanly." % ", ".join(chains + solo),
        "- **Start check (MUST):** session must be %s at `%s` in T3 Code; any other model or effort stops. %s never conducts: "
        "runs only its brief, no gate, premerge, git mutation or PR." % (cond["label"], cond["effort"], non_cond or imp["label"]),
    ]
    return "\n".join([START] + rows + [END])
def render_skill(text, cfg):
    desc = describe(cfg)
    if len(desc) > MAX_DESC: raise ValueError("description is %d characters (max %d)" % (len(desc), MAX_DESC))
    if "'" in desc or "\n" in desc: raise ValueError("description cannot be a single-quoted YAML scalar")
    lines = text.split("\n")
    if sum(1 for line in lines if line.strip() == START) != 1 or sum(1 for line in lines if line.strip() == END) != 1:
        raise ValueError("SKILL.md must hold exactly one routing:start and one routing:end marker")
    top = next(index for index, line in enumerate(lines) if line.strip() == START)
    bottom = next(index for index, line in enumerate(lines) if line.strip() == END)
    if bottom < top: raise ValueError("routing markers are out of order")
    hits = [index for index, line in enumerate(lines) if line.startswith("description: '")]
    if len(hits) != 1: raise ValueError("SKILL.md needs exactly one single-quoted frontmatter description line")
    lines[hits[0]] = "description: '%s'" % desc
    lines[top:bottom + 1] = render_block(cfg).split("\n")
    out = "\n".join(lines)
    if len(out.encode("utf-8")) > MAX_SKILL: raise ValueError("rendered SKILL.md is %d bytes (max %d)" % (len(out.encode("utf-8")), MAX_SKILL))
    return out
def render_opencode(text, cfg):
    try: data = json.loads(text)
    except ValueError: raise ValueError("opencode/opencode.json is not valid JSON")
    if not isinstance(data, dict) or not isinstance(data.get("agents"), dict) or "implementer" not in data["agents"]:
        raise ValueError("opencode/opencode.json needs an agents.implementer entry")
    pinned = implementer(cfg)["pinned"]
    if data.get("model") == pinned: return text
    data["model"] = pinned
    return json.dumps(data, indent=1) + "\n"
def inspect(skill_dir=None):
    base = os.path.abspath(skill_dir or SKILL_DIR); cfg = load(base); pairs = []
    for rel, render in (("opencode/opencode.json", render_opencode), ("SKILL.md", render_skill)):
        path = os.path.join(base, rel); current = read(path)
        pairs.append((path, current, render(current, cfg)))
    return cfg, pairs
def write(path, text):
    handle, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".routing-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream: stream.write(text)
        os.replace(tmp, path)
    except OSError as problem: raise ValueError("cannot write %s: %s" % (os.path.basename(path), problem))
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def sync(skill_dir=None):
    cfg, pairs = inspect(skill_dir)
    for path, current, wanted in pairs:
        if current != wanted: write(path, wanted)
    return cfg
def tsv(*fields): return "\t".join(str(field) for field in fields)
def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "check":
            drifted = [path for path, current, wanted in inspect()[1] if current != wanted]
            if drifted: sys.stderr.write("routing_lib: drifted: %s\n" % ", ".join(drifted)); return 1
            return 0
        if cmd == "sync": sync(); return 0
        if cmd == "opencode-config":
            text = render_opencode(read(os.path.join(SKILL_DIR, "opencode", "opencode.json")), load())
            sys.stdout.write(text if text.endswith("\n") else text + "\n"); return 0
        cfg = load()
        if cmd == "impl-tsv":
            imp = implementer(cfg); print(tsv(imp["route"], imp["provider"], imp["model"], imp["model_id"], imp["effort"], imp["pinned"], imp["account"], imp["max_cost_usd"])); return 0
        if cmd == "gate-tsv" and len(argv) == 3:
            provider, route, model, option, accounts = gate_contract(cfg, argv[2])
            print(tsv(provider, route, model, option, " ".join(accounts))); return 0
        if cmd == "conductor-tsv":
            cond = conductor(cfg); print(tsv(cond["provider"], cond["route"], cond["model"], cond["option_key"], cond["effort"], cond["label"], " ".join(cond["accounts"]))); return 0
        if cmd == "effort" and len(argv) in (4, 5):
            print(effort_for(cfg, argv[2], argv[3], len(argv) == 5 and argv[4] not in ("", "0"))); return 0
    except (ValueError, OSError) as problem:
        sys.stderr.write("routing_lib: %s\n" % problem); return 2
    sys.stderr.write("usage: routing_lib.py <check|sync|opencode-config|impl-tsv|gate-tsv GATE|conductor-tsv|effort GATE TIER [trigger]>\n"); return 2
if __name__ == "__main__": sys.exit(main(sys.argv))
