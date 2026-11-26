#!/usr/bin/env python3
"""routing_lib.py - routing.json reader/validator/syncer for ds-dev-protocol (stdlib only, Python 3.9+)."""
import json, math, os, re, sys, tempfile
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START, END = "<!-- routing:start -->", "<!-- routing:end -->"
GATES, MAX_BYTES, MAX_SKILL, MAX_DESC = ("plan", "review", "security", "epoch"), 65536, 25600, 450
UI_GATES = ("plan", "review"); TIERS = {"plan": ("low", "medium", "high"), "review": ("low", "medium", "high"), "security": ("high",), "epoch": ("medium", "high")}
TRIGGERS = {"plan": ("arch-trust-state", "scope-multi", "arch-ambiguous", "reactive-replan"), "review": ("diff-large", "contract-or-guard", "ui-overhaul", "reactive-round"), "security": ("attack-surface", "reactive-round"), "epoch": ()}; EFFORT_RANK = {"medium": 0, "high": 1}
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
    if any(ord(ch) < 32 or ch.isspace() or ch == "#" for ch in value) or (slash and "/" in value): raise ValueError("%s has whitespace, a control character, '#' or '/'" % what)
    return value
def label(value, what):
    if not isinstance(value, str) or not value.strip() or any(ord(ch) < 32 or ch in "'|`" for ch in value):
        raise ValueError("%s must be non-empty and hold no control character, quote, pipe or backtick" % what)
    return value
def effort(value, allowed, what):
    if not isinstance(value, str) or value not in allowed: raise ValueError("%s %r is not in allowed_efforts" % (what, value))
    return value
def pending(route): return "model_id" not in route and route.get("model") is None and route.get("option_key") is None
def check_efforts(spec, gate, allowed):
    values = spec.get("efforts")
    if not isinstance(values, dict) or set(values) != set(TIERS[gate]): raise ValueError("%s efforts must be %s" % (gate, "/".join(TIERS[gate])))
    for tier, value in values.items(): effort(value, allowed, "%s %s effort" % (gate, tier))
    if any(EFFORT_RANK[values[low]] > EFFORT_RANK[values[high]] for low, high in zip(TIERS[gate], TIERS[gate][1:])): raise ValueError("%s efforts must not fall across %s" % (gate, "/".join(TIERS[gate])))
    if "trigger_effort" in spec: effort(spec["trigger_effort"], allowed, "%s trigger_effort" % gate)
    if "trigger_effort" in spec and EFFORT_RANK[spec["trigger_effort"]] < max(EFFORT_RANK[value] for value in values.values()): raise ValueError("%s trigger_effort is below its tier efforts" % gate)
def parse_triggers(gate, raw="", legacy=False):
    if gate not in TRIGGERS: raise ValueError("unknown gate %s" % gate)
    tags = (raw.split(",") if raw else []) + (["legacy-trigger"] if legacy else [])
    if legacy and not TRIGGERS[gate]: raise ValueError("gate %s takes no trigger" % gate)
    for pos, tag in enumerate(tags):
        if not tag or tag != tag.strip() or any(ch.isspace() for ch in tag): raise ValueError("invalid --high-effort tag %r" % tag)
        if tag == "legacy-trigger" and (not legacy or pos != len(tags) - 1): raise ValueError("legacy-trigger is not an --high-effort tag")
        if tag != "legacy-trigger" and tag not in TRIGGERS[gate]: raise ValueError("effort trigger %r is not valid for %s" % (tag, gate))
    return list(dict.fromkeys(tags))
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
        if "max_cost_usd" in route and (isinstance(route["max_cost_usd"], bool) or not isinstance(route["max_cost_usd"], (int, float)) or not math.isfinite(route["max_cost_usd"]) or route["max_cost_usd"] < 0): raise ValueError("route %s max_cost_usd must be a non-negative number" % key)
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
        check_efforts(spec, gate, allowed)
    ui = cfg.get("ui_gates")
    if not isinstance(ui, dict) or set(ui) != set(UI_GATES): raise ValueError("ui_gates must be exactly plan, review")
    for gate in UI_GATES:
        if not isinstance((specs := ui[gate]), list) or not specs or len({spec.get("route") if isinstance(spec, dict) else None for spec in specs}) != len(specs): raise ValueError("ui_gates %s must be a non-empty list with unique routes" % gate)
        for pos, spec in enumerate(specs):
            name = spec.get("route") if isinstance(spec, dict) else None; route = routes.get(name) if isinstance(name, str) else None
            if not isinstance(route, dict) or (not pending(route) and ("model" not in route or "option_key" not in route)) or (pos == 0 and pending(route)): raise ValueError("ui_gates %s route %r is not an active model/option_key route or is a pending primary" % (gate, name))
            check_efforts(spec, gate, allowed)
    return cfg
def gate_contracts(cfg, gate, ui=False):
    if ui and gate not in UI_GATES: raise ValueError("gate %s has no ui route" % gate)
    specs = cfg["ui_gates"][gate] if ui else [cfg["gates"][gate]]
    return [(r["provider"], spec["route"], r["model"], r["option_key"], r["driver_kind"]) for spec in specs for r in [cfg["routes"][spec["route"]]] if r.get("model") is not None and r.get("option_key") is not None]
def gate_contract(cfg, gate): return gate_contracts(cfg, gate)[0]
def spec_for(cfg, gate, ui=False, route=None):
    if ui and gate not in UI_GATES: raise ValueError("gate %s has no ui route" % gate)
    specs = [spec for spec in (cfg["ui_gates"][gate] if ui else [cfg["gates"][gate]]) if route is None or spec["route"] == route]
    if not specs: raise ValueError("gate %s has no route %r" % (gate, route))
    return specs[0]
def option_keys(cfg): return tuple(dict.fromkeys(route["option_key"] for route in cfg["routes"].values() if route.get("option_key")))
def effort_for(cfg, gate, tier, trigger=False, ui=False, route=None):
    spec = spec_for(cfg, gate, ui, route)
    if tier not in spec["efforts"]: raise ValueError("gate %s has no %s tier" % (gate, tier))
    return spec["trigger_effort"] if trigger and spec.get("trigger_effort") else spec["efforts"][tier]
def allowed_efforts_for(cfg, gate, tier, ui=False, route=None):
    spec = spec_for(cfg, gate, ui, route); base = effort_for(cfg, gate, tier, False, ui, route)
    return {base, spec["trigger_effort"]} if spec.get("trigger_effort") else {base}
def implementer(cfg):
    spec = cfg["implementer"]; route = cfg["routes"][spec["route"]]; model = "%s/%s" % (route["provider"], route["model_id"])
    return dict(route=spec["route"], provider=route["provider"], model_id=route["model_id"], model=model, effort=spec["effort"], pinned="%s#%s" % (model, spec["effort"]), driver_kind=route["driver_kind"], max_cost_usd=route["max_cost_usd"], label=route["label"])
def conductor(cfg):
    spec = cfg["conductor"]; route = cfg["routes"][spec["route"]]
    return dict(route=spec["route"], provider=route["provider"], model=route["model"], option_key=route["option_key"], driver_kind=route["driver_kind"], effort=spec["effort"], label=route["label"])
def effort_text(spec, tiers, short=True):
    values = [spec["efforts"][tier] for tier in tiers]; trigger = spec.get("trigger_effort")
    base = "/".join(dict.fromkeys((SHORT[value] if short else value) for value in values)) if len(set(values)) > 1 else (SHORT[values[0]] if short else values[0])
    return base + ("+%s" % SHORT[trigger] if trigger and trigger not in values else "") if short else "`%s`" % base + (" (`%s` on `--high-effort`)" % trigger if trigger else "")
def ui_summary(specs):
    out, tail = effort_text(specs[0], TIERS["plan"]), effort_text(specs[-1], TIERS["plan"])
    return out if tail == out else "%s/%s" % (out, tail)
def describe(cfg):
    cond, imp = conductor(cfg), implementer(cfg); planner = cfg["routes"][cfg["gates"]["plan"]["route"]]["label"]
    who = cond["label"] if planner == cond["label"] else "%s and %s" % (cond["label"], planner); gate = lambda name: effort_text(cfg["gates"][name], TIERS[name]); ui = cfg["ui_gates"]
    return ("ds-dev-protocol: Always on by default for all work across every harness, model, AI agent & T3 Code; off only on explicit request, session-only (never globally). %s conducts (%s always), plans (%s); "
            "%s %s implementer (implement.sh, no model fallback); %s review/security/epoch (%s, %s, %s); UI %s (plan %s, review %s)."
            % (who, cond["effort"].capitalize(), gate("plan"), imp["label"], imp["effort"], cfg["routes"][cfg["gates"]["review"]["route"]]["label"], gate("review"), gate("security"), gate("epoch"), ">".join(spec["route"] for spec in ui["plan"]), ui_summary(ui["plan"]), ui_summary(ui["review"])))
def render_block(cfg):
    cond, imp = conductor(cfg), implementer(cfg); plan, review, sec, epoch = (cfg["gates"][name] for name in GATES)
    planner, reviewer = cfg["routes"][plan["route"]], cfg["routes"][sec["route"]]; other = [value for value in cfg["allowed_efforts"] if value != cond["effort"]]
    non_cond = "/".join(dict.fromkeys(r["label"] for r in (imp, reviewer) if r["label"] != cond["label"]))
    ui = cfg["ui_gates"]; ui_routes = [cfg["routes"][spec["route"]] for spec in ui["plan"]]; ui_names = " → ".join(r["label"] if r.get("model") is None else "%s `%s`" % (r["label"], r["model"]) for r in ui_routes)
    ui_plan = effort_text(ui["plan"][0], TIERS["plan"], False) + (", fallback %s" % effort_text(ui["plan"][-1], TIERS["plan"], False) if len(ui["plan"]) > 1 and effort_text(ui["plan"][-1], TIERS["plan"], False) != effort_text(ui["plan"][0], TIERS["plan"], False) else "")
    rows = [
        "Four roles, one model each, no substitution:", "",
        "| Role | Model and effort (%s only) | Path |" % "/".join(cfg["allowed_efforts"]), "|---|---|---|",
        "| Conductor | %s `%s`, `%s` always (never `%s` or other) | this T3 Code thread (`%s`) |" % (cond["label"], cond["model"], cond["effort"], other[0] if other else "any other", cond["driver_kind"]),
        "| Architect & Planner | %s `%s`, %s | fresh `delegate_task` on a live `%s` instance, then `gate.sh plan --record` |" % (planner["label"], planner["model"], effort_text(plan, TIERS["plan"], False), planner["driver_kind"]),
        "| Implementer | %s `%s`, `variant: %s` always | `scripts/implement.sh`, the documented mechanical runner, no OS sandbox; sole implementer, no fallback |" % (imp["label"], imp["pinned"], imp["effort"]),
        "| Reviewer, Security & Epoch | %s `%s`, review %s; security %s; epoch %s | fresh `delegate_task` on a live `%s` instance, then `gate.sh <gate> --record` |" % (reviewer["label"], reviewer["model"], effort_text(review, TIERS["review"], False), effort_text(sec, TIERS["security"], False), effort_text(epoch, TIERS["epoch"], False), reviewer["driver_kind"]),
        "",
        "- **Dynamic `driver_kind` failover:** call `orchestrator_capabilities`; use only live `providerInstanceId` serial IDs (never display names or emails). A child hitting `usage_limit` is `task_cancel`led and re-dispatched as a fresh `delegate_task` on the next live instance of the same `driver_kind`, model and effort: never cross a `driver_kind` or model, never ask. When every live pair is tried, log `blocked` (exit 3), record `STATUS: blocked external — <model> quota exhausted; waiting for reset` with `Routes tried:`, stop cleanly.",
        "- **Start check (MUST):** session must be %s at `%s` in T3 Code; any other model or effort stops. %s never conducts: runs only its brief, no gate, premerge, git mutation or PR." % (cond["label"], cond["effort"], non_cond or imp["label"]),
        "- **Frontend & UI routing (`--ui`, plan and review only):** with `--ui` and `Scope: ui` in the packet the gate uses this %d-tier chain in priority order: %s. A tier applies when a live `orchestrator_capabilities` instance of its `driver_kind` runs its model; a `ui_gates` route with zero live instances is skipped automatically. UI plan: %s; UI review %s. Non-UI gates keep the single route above. If every UI tier is exhausted, log `blocked` (exit 3) and never use another model." % (len(ui_routes), ui_names, ui_plan, effort_text(ui["review"][0], TIERS["plan"], False)),
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
    if data.get("model") == (pinned := implementer(cfg)["pinned"]): return text
    return json.dumps(dict(data, model=pinned), indent=1) + "\n"
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
            drifted = [path for path, current, wanted in inspect()[1] if current != wanted]; return (sys.stderr.write("routing_lib: drifted: %s\n" % ", ".join(drifted)), 1)[1] if drifted else 0
        if cmd == "sync": sync(); return 0
        if cmd == "check-triggers" and len(argv) in (3, 4): print(",".join(parse_triggers(argv[2], argv[3] if len(argv) == 4 else ""))); return 0
        if cmd == "opencode-config": text = render_opencode(read(os.path.join(SKILL_DIR, "opencode", "opencode.json")), load()); sys.stdout.write(text if text.endswith("\n") else text + "\n"); return 0
        cfg = load()
        if cmd == "impl-tsv": imp = implementer(cfg); print(tsv(imp["route"], imp["provider"], imp["model"], imp["model_id"], imp["effort"], imp["pinned"], imp["driver_kind"], imp["max_cost_usd"])); return 0
        if cmd == "gate-tsv" and len(argv) == 3: print(tsv(*gate_contract(cfg, argv[2]))); return 0
        if cmd == "ui-gate-tsv" and len(argv) == 3: [print(tsv(*contract)) for contract in gate_contracts(cfg, argv[2], ui=True)]; return 0
        if cmd == "conductor-tsv": cond = conductor(cfg); print(tsv(cond["provider"], cond["route"], cond["model"], cond["option_key"], cond["effort"], cond["label"], cond["driver_kind"])); return 0
        if cmd == "effort" and len(argv) in (4, 5): print(effort_for(cfg, argv[2], argv[3], len(argv) == 5 and argv[4] not in ("", "0"))); return 0
        if cmd == "ui-effort" and len(argv) in (4, 5, 6): print(effort_for(cfg, argv[2], argv[3], len(argv) >= 5 and argv[4] not in ("", "0"), ui=True, route=argv[5] if len(argv) == 6 else None)); return 0
    except (ValueError, OSError) as problem:
        sys.stderr.write("routing_lib: %s\n" % problem); return 2
    sys.stderr.write("usage: routing_lib.py <check|sync|check-triggers GATE RAW|opencode-config|impl-tsv|gate-tsv GATE|ui-gate-tsv GATE|conductor-tsv|effort GATE TIER [trigger]|ui-effort GATE TIER [trigger] [route]>\n"); return 2
if __name__ == "__main__": sys.exit(main(sys.argv))
