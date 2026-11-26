#!/usr/bin/env python3
"""routing_lib.py - the ds-dev-protocol routing source of truth reader/validator/syncer (stdlib only, Python 3.9+).
routing.json holds every route, model, provider, option key, driver kind, cost cap, tier/trigger effort and the UI gate chains.
This module validates it, derives roles, pinned specs and gate contracts, and syncs opencode/opencode.json and SKILL.md;
paths are anchored to this file, and every error exits 2 without writing."""
import json, math, os, re, sys, tempfile
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START, END = "<!-- routing:start -->", "<!-- routing:end -->"
GATES, MAX_BYTES, MAX_SKILL, MAX_DESC = ("plan", "review", "security", "epoch"), 65536, 25600, 450
UI_GATES = ("plan", "review")
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
def pending(route): return "model_id" not in route and route.get("model") is None and route.get("option_key") is None
def load(skill_dir=None):
    cfg = json.loads(read(os.path.join(os.path.abspath(skill_dir or SKILL_DIR), "routing.json")))
    if not isinstance(cfg, dict) or isinstance(cfg.get("schema_version"), bool) or cfg.get("schema_version") != 1: raise ValueError("routing.json must be an object with schema_version 1")
    allowed = cfg.get("allowed_efforts")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(value, str) for value in allowed) or len(set(allowed)) != len(allowed) or set(allowed) - {"medium", "high"}: raise ValueError("allowed_efforts must be a non-empty subset of [medium, high]")
    routes, gates = cfg.get("routes"), cfg.get("gates")
    if not isinstance(routes, dict) or not routes: raise ValueError("routes must be a non-empty object")
    for key, route in routes.items():
        if not (isinstance(key, str) and ROUTE_KEY.match(key) and isinstance(route, dict)): raise ValueError("invalid route %r: needs a lowercase key" % (key,))
        label(route.get("label"), "route %s label" % key); ident(route.get("provider"), "route %s provider" % key); model, option = route.get("model"), route.get("option_key")
        if "model_id" in route:
            if "model" in route or "option_key" in route: raise ValueError("route %s cannot mix model_id with model or option_key" % key)
            ident(route["model_id"], "route %s model_id" % key)
        elif model is None or option is None:
            if "model" not in route or "option_key" not in route or model is not None or option is not None: raise ValueError("route %s is half-configured: model and option_key must both be null (catalog-pending)" % key)
        else: ident(model, "route %s model" % key); ident(option, "route %s option_key" % key)
        if "accounts" in route: raise ValueError("route %s must use driver_kind, never legacy accounts" % key)
        ident(route.get("driver_kind"), "route %s driver_kind" % key)
        cost = route.get("max_cost_usd")
        if "max_cost_usd" in route and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0): raise ValueError("route %s max_cost_usd must be a non-negative number" % key)
    for role, fields in (("conductor", ("model", "option_key")), ("implementer", ("model_id",))):
        spec = cfg.get(role); route = routes.get(spec.get("route")) if isinstance(spec, dict) and isinstance(spec.get("route"), str) else None
        if not isinstance(route, dict) or any(field not in route for field in fields) or pending(route) or not effort(spec.get("effort"), allowed, "%s effort" % role): raise ValueError("%s must name an active route with %s" % (role, " and ".join(fields)))
    imp = routes[cfg["implementer"]["route"]]
    if "max_cost_usd" not in imp: raise ValueError("implementer route needs max_cost_usd")
    ident(imp["provider"], "implementer provider", slash=True); ident(imp["model_id"], "implementer model_id", slash=True)
    if not isinstance(gates, dict) or set(gates) != set(GATES): raise ValueError("gates must be exactly plan, review, security, epoch")
    for gate in GATES:
        spec = gates[gate]; route = routes.get(spec.get("route")) if isinstance(spec, dict) and isinstance(spec.get("route"), str) else None
        if not isinstance(route, dict) or "model" not in route or "option_key" not in route or pending(route): raise ValueError("gate %s needs an active route with model and option_key" % gate)
        if not isinstance(spec.get("efforts"), dict) or set(spec["efforts"]) != set(TIERS[gate]): raise ValueError("gate %s efforts must be %s" % (gate, "/".join(TIERS[gate])))
        for tier, value in spec["efforts"].items(): effort(value, allowed, "gate %s %s effort" % (gate, tier))
        if "trigger_effort" in spec: effort(spec["trigger_effort"], allowed, "gate %s trigger_effort" % gate)
    ui = cfg.get("ui_gates")
    if not isinstance(ui, dict) or set(ui) != set(UI_GATES): raise ValueError("ui_gates must be exactly plan, review")
    for gate in UI_GATES:
        if not isinstance((specs := ui[gate]), list) or not specs: raise ValueError("ui_gates %s must be a non-empty list" % gate)
        seen = set()
        for pos, spec in enumerate(specs):
            name = spec.get("route") if isinstance(spec, dict) else None; route = routes.get(name) if isinstance(name, str) else None
            if not isinstance(route, dict) or (not pending(route) and ("model" not in route or "option_key" not in route)) or (pos == 0 and pending(route)): raise ValueError("ui_gates %s route %r is not an active model/option_key route or is a pending primary" % (gate, name))
            if name in seen: raise ValueError("ui_gates %s has a duplicate route %s" % (gate, name))
            seen.add(name)
            if not isinstance(spec.get("efforts"), dict) or set(spec["efforts"]) != set(TIERS[gate]): raise ValueError("ui_gates %s efforts must be %s" % (gate, "/".join(TIERS[gate])))
            for tier, value in spec["efforts"].items(): effort(value, allowed, "ui_gates %s %s effort" % (gate, tier))
            if "trigger_effort" in spec: effort(spec["trigger_effort"], allowed, "ui_gates %s trigger_effort" % gate)
    return cfg
def gate_contracts(cfg, gate, ui=False):
    if ui and gate not in UI_GATES: raise ValueError("gate %s has no ui route" % gate)
    specs = cfg["ui_gates"][gate] if ui else [cfg["gates"][gate]]
    return [(r["provider"], spec["route"], r["model"], r["option_key"], r["driver_kind"]) for spec in specs for r in [cfg["routes"][spec["route"]]] if r.get("model") is not None and r.get("option_key") is not None]
def gate_contract(cfg, gate): return gate_contracts(cfg, gate)[0]
def spec_for(cfg, gate, ui=False, route=None):
    if ui and gate not in UI_GATES: raise ValueError("gate %s has no ui route" % gate)
    specs = cfg["ui_gates"][gate] if ui else [cfg["gates"][gate]]
    specs = [spec for spec in specs if spec["route"] == route] if route is not None else specs
    if not specs: raise ValueError("gate %s has no route %r" % (gate, route))
    return specs[0]
def option_keys(cfg): return tuple(dict.fromkeys(route["option_key"] for route in cfg["routes"].values() if route.get("option_key")))
def effort_for(cfg, gate, tier, trigger=False, ui=False, route=None):
    spec = spec_for(cfg, gate, ui, route)
    if trigger and tier == "medium" and spec.get("trigger_effort"): return spec["trigger_effort"]
    if tier not in spec["efforts"]: raise ValueError("gate %s has no %s tier" % (gate, tier))
    return spec["efforts"][tier]
def allowed_efforts_for(cfg, gate, tier, ui=False, route=None):
    spec = spec_for(cfg, gate, ui, route); out = {effort_for(cfg, gate, tier, False, ui, route)}
    if spec.get("trigger_effort") and tier == "medium": out.add(spec["trigger_effort"])
    return out
def implementer(cfg):
    spec = cfg["implementer"]; route = cfg["routes"][spec["route"]]; model = "%s/%s" % (route["provider"], route["model_id"])
    return dict(route=spec["route"], provider=route["provider"], model_id=route["model_id"], model=model, effort=spec["effort"], pinned="%s#%s" % (model, spec["effort"]), driver_kind=route["driver_kind"], max_cost_usd=route["max_cost_usd"], label=route["label"])
def conductor(cfg):
    spec = cfg["conductor"]; route = cfg["routes"][spec["route"]]
    return dict(route=spec["route"], provider=route["provider"], model=route["model"], option_key=route["option_key"], driver_kind=route["driver_kind"], effort=spec["effort"], label=route["label"])
def describe(cfg):
    cond, imp = conductor(cfg), implementer(cfg); planner = cfg["routes"][cfg["gates"]["plan"]["route"]]["label"]
    who = cond["label"] if planner == cond["label"] else "%s and %s" % (cond["label"], planner)
    efforts = lambda gate: "/".join(SHORT[cfg["gates"][gate]["efforts"][tier]] for tier in TIERS[gate])
    ui = cfg["ui_gates"]; ui_eff = lambda gate: "/".join(SHORT[ui[gate][0]["efforts"][tier]] for tier in TIERS["plan"])
    return ("ds-dev-protocol: Always on by default for all work across every harness, model, AI agent & T3 Code; off only on explicit request, session-only (never globally). %s conducts (%s always), plans (%s); "
            "%s %s implementer (implement.sh, no model fallback); %s review/security/epoch (%s, %s, %s); UI %s (plan %s, review %s)."
            % (who, cond["effort"].capitalize(), efforts("plan"), imp["label"], imp["effort"], cfg["routes"][cfg["gates"]["review"]["route"]]["label"], efforts("review"), efforts("security"), efforts("epoch"), ">".join(spec["route"] for spec in ui["plan"]), ui_eff("plan"), ui_eff("review")))
def ui_efforts(specs): return ["/".join(spec["efforts"][tier] for tier in TIERS["plan"]) for spec in specs]
def render_block(cfg):
    cond, imp = conductor(cfg), implementer(cfg); plan, review, sec, epoch = (cfg["gates"][name] for name in GATES)
    planner, reviewer = cfg["routes"][plan["route"]], cfg["routes"][sec["route"]]; other = [value for value in cfg["allowed_efforts"] if value != cond["effort"]]
    non_cond = "/".join(dict.fromkeys(r["label"] for r in (imp, reviewer) if r["label"] != cond["label"]))
    ui = cfg["ui_gates"]; ui_routes = [cfg["routes"][spec["route"]] for spec in ui["plan"]]; ui_names = " → ".join(r["label"] if r.get("model") is None else "%s `%s`" % (r["label"], r["model"]) for r in ui_routes)
    plan_eff, review_eff = ui_efforts(ui["plan"]), ui_efforts(ui["review"]); trig = ui["plan"][0].get("trigger_effort")
    ui_plan = "UI plan (Low/Med/High): `%s`%s" % (plan_eff[0], " (`%s` `--trigger`)" % trig if trig else "") + (", fallback `%s`" % plan_eff[-1] if len(plan_eff) > 1 else "")
    ui_review = "`%s`" % review_eff[0] + (" (fallback `%s`)" % review_eff[-1] if len(review_eff) > 1 and review_eff[-1] != review_eff[0] else "")
    rows = [
        "Four roles, one model each, no substitution:", "",
        "| Role | Model and effort (%s only) | Path |" % "/".join(cfg["allowed_efforts"]), "|---|---|---|",
        "| Conductor | %s `%s`, `%s` always (never `%s` or other) | this T3 Code thread (`%s`) |" % (cond["label"], cond["model"], cond["effort"], other[0] if other else "any other", cond["driver_kind"]),
        "| Architect & Planner | %s `%s`, `%s` Low, `%s` Medium, `%s` High | fresh `delegate_task` on a live `%s` instance, then `gate.sh plan --record` |" % (planner["label"], planner["model"], plan["efforts"]["low"], plan["efforts"]["medium"], plan["efforts"]["high"], planner["driver_kind"]),
        "| Implementer | %s `%s`, `variant: %s` always | `scripts/implement.sh`, the documented mechanical runner, no OS sandbox; sole implementer, no fallback |" % (imp["label"], imp["pinned"], imp["effort"]),
        "| Reviewer, Security & Epoch | %s `%s`, review `%s`/`%s` Low/Medium and `%s` High (`%s` with `--trigger`); security `%s`; epoch `%s`/`%s` | fresh `delegate_task` on a live `%s` instance, then `gate.sh <gate> --record` |" % (reviewer["label"], reviewer["model"], review["efforts"]["low"], review["efforts"]["medium"], review["efforts"]["high"], review.get("trigger_effort", review["efforts"]["high"]), sec["efforts"]["high"], epoch["efforts"]["medium"], epoch["efforts"]["high"], reviewer["driver_kind"]),
        "",
        "- **Dynamic `driver_kind` failover:** call `orchestrator_capabilities`; use only live `providerInstanceId` serial IDs (never display names or emails). A child hitting `usage_limit` is `task_cancel`led and re-dispatched as a fresh `delegate_task` on the next live instance of the same `driver_kind`, model and effort: never cross a `driver_kind` or model, never ask. When every live pair is tried, log `blocked` (exit 3), record `STATUS: blocked external — <model> quota exhausted; waiting for reset` with `Routes tried:`, stop cleanly.",
        "- **Start check (MUST):** session must be %s at `%s` in T3 Code; any other model or effort stops. %s never conducts: runs only its brief, no gate, premerge, git mutation or PR." % (cond["label"], cond["effort"], non_cond or imp["label"]),
        "- **Frontend & UI routing (`--ui`, plan and review only):** with `--ui` and `Scope: ui` in the packet the gate uses this %d-tier chain in priority order: %s. A tier applies when a live `orchestrator_capabilities` instance of its `driver_kind` runs its model; a `ui_gates` route with zero live instances is skipped automatically. %s Non-UI gates keep the single route above. If every UI tier is exhausted, log `blocked` (exit 3) and never use another model." % (len(ui_routes), ui_names, ui_plan + "; UI review " + ui_review + "."),
    ]
    return "\n".join([START] + rows + [END])
def render_skill(text, cfg):
    desc = describe(cfg)
    if len(desc) > MAX_DESC or "'" in desc or "\n" in desc: raise ValueError("description must be one single-quoted line of at most %d characters" % MAX_DESC)
    lines = text.split("\n"); starts = [i for i, line in enumerate(lines) if line.strip() == START]; ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if len(starts) != 1 or len(ends) != 1: raise ValueError("SKILL.md must hold exactly one routing:start and one routing:end marker")
    top, bottom = starts[0], ends[0]
    if bottom < top: raise ValueError("routing markers are out of order")
    hits = [i for i, line in enumerate(lines) if line.startswith("description: '")]
    if len(hits) != 1: raise ValueError("SKILL.md needs exactly one single-quoted frontmatter description line")
    lines[hits[0]] = "description: '%s'" % desc; lines[top:bottom + 1] = render_block(cfg).split("\n"); out = "\n".join(lines)
    if len(out.encode("utf-8")) > MAX_SKILL: raise ValueError("rendered SKILL.md is %d bytes (max %d)" % (len(out.encode("utf-8")), MAX_SKILL))
    return out
def render_opencode(text, cfg):
    try: data = json.loads(text)
    except ValueError: raise ValueError("opencode/opencode.json is not valid JSON")
    if not isinstance(data, dict) or not isinstance(data.get("agents"), dict) or "implementer" not in data["agents"]: raise ValueError("opencode/opencode.json needs an agents.implementer entry")
    pinned = implementer(cfg)["pinned"]
    if data.get("model") == pinned: return text
    data["model"] = pinned
    return json.dumps(data, indent=1) + "\n"
def inspect(skill_dir=None):
    base = os.path.abspath(skill_dir or SKILL_DIR); cfg = load(base); pairs = []
    for rel, render in (("opencode/opencode.json", render_opencode), ("SKILL.md", render_skill)):
        path = os.path.join(base, rel); current = read(path); pairs.append((path, current, render(current, cfg)))
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
    cfg, pairs = inspect(skill_dir); [write(path, wanted) for path, current, wanted in pairs if current != wanted]; return cfg
def tsv(*fields): return "\t".join(str(field) for field in fields)
def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "check":
            drifted = [path for path, current, wanted in inspect()[1] if current != wanted]
            return (sys.stderr.write("routing_lib: drifted: %s\n" % ", ".join(drifted)), 1)[1] if drifted else 0
        if cmd == "sync": sync(); return 0
        if cmd == "opencode-config":
            text = render_opencode(read(os.path.join(SKILL_DIR, "opencode", "opencode.json")), load())
            sys.stdout.write(text if text.endswith("\n") else text + "\n"); return 0
        cfg = load()
        if cmd == "impl-tsv":
            imp = implementer(cfg); print(tsv(imp["route"], imp["provider"], imp["model"], imp["model_id"], imp["effort"], imp["pinned"], imp["driver_kind"], imp["max_cost_usd"])); return 0
        if cmd == "gate-tsv" and len(argv) == 3:
            provider, route, model, option, driver_kind = gate_contract(cfg, argv[2]); print(tsv(provider, route, model, option, driver_kind)); return 0
        if cmd == "ui-gate-tsv" and len(argv) == 3:
            for provider, route, model, option, driver_kind in gate_contracts(cfg, argv[2], ui=True): print(tsv(provider, route, model, option, driver_kind))
            return 0
        if cmd == "conductor-tsv":
            cond = conductor(cfg); print(tsv(cond["provider"], cond["route"], cond["model"], cond["option_key"], cond["effort"], cond["label"], cond["driver_kind"])); return 0
        if cmd == "effort" and len(argv) in (4, 5):
            print(effort_for(cfg, argv[2], argv[3], len(argv) == 5 and argv[4] not in ("", "0"))); return 0
        if cmd == "ui-effort" and len(argv) in (4, 5, 6):
            print(effort_for(cfg, argv[2], argv[3], len(argv) >= 5 and argv[4] not in ("", "0"), ui=True, route=argv[5] if len(argv) == 6 else None)); return 0
    except (ValueError, OSError) as problem:
        sys.stderr.write("routing_lib: %s\n" % problem); return 2
    sys.stderr.write("usage: routing_lib.py <check|sync|opencode-config|impl-tsv|gate-tsv GATE|ui-gate-tsv GATE|conductor-tsv|effort GATE TIER [trigger]|ui-effort GATE TIER [trigger] [route]>\n"); return 2
if __name__ == "__main__": sys.exit(main(sys.argv))
