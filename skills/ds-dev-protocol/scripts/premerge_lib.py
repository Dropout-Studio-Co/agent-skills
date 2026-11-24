#!/usr/bin/env python3
# premerge_lib.py - evidence checks for scripts/premerge-and-merge.sh (python3 -I premerge_lib.py <cmd> ...); stdlib only.
import calendar, glob, hashlib, json, os, re, subprocess, sys, time
NEON, OPUS = "gemini-4-neon", "claude-opus-5-5"
AG, CL = ("antigravity", "antigravity_2"), ("claudeAgent", "claudeAgent_2", "claudeAgent_3")
RANK = {"low": 0, "medium": 1, "high": 2}
FIELDS = "ts engine provenance_mode gate tier round key base_ref base_sha diff_sha256 head_sha facts_sha256 route model effort session_id parent_thread_id account input_tokens output_tokens cost_usd verdict status reason file file_sha256".split()

def sha(f): return hashlib.sha256(open(f, "rb").read()).hexdigest()

def rows(f):
    out = []
    for l in (open(f, errors="replace") if os.path.exists(f) else []):
        if not l.strip(): continue
        try: out.append(json.loads(l))
        except Exception: out.append(None)
    return out
def ep(d):
    try: return calendar.timegm(time.strptime(str(d.get("ts", "")), "%Y-%m-%dT%H:%M:%SZ"))
    except Exception: return None

def logrow(ev, **d):
    r = dict((k, 0 if k in ("round", "input_tokens", "output_tokens") else "") for k in FIELDS)
    r["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); r.update(d)
    open(os.path.join(ev, "gates.log"), "a").write(json.dumps(r) + "\n")

def tiers(plan, recheck):
    def t(p):
        try: return [x.lower() for x in re.findall(r"\bTier:\s*\**\s*(low|medium|high)\b", open(p, errors="replace").read(), re.I)]
        except Exception: return []
    pl, rc = t(plan), t(recheck); pt = max(pl, key=lambda x: RANK[x]) if pl else ""; rt = rc[-1] if rc else ""
    f = max(pt, rt, key=lambda x: RANK[x]) if (pt and rt) else "none"
    print(f, rt or "none", pt or "none", 1 if rt and pt and RANK[rt] < RANK[pt] else 0)

def evidence(ev, key, tier, base, mode):
    out = []
    P, F = (lambda t: out.append("PASS " + t)), (lambda t: out.append("FAIL " + t))
    tid = os.path.basename(os.path.abspath(ev)); R, ids = [], {}
    for n, d in enumerate(rows(os.path.join(ev, "gates.log")), 1):
        if not isinstance(d, dict): F("gates.log row %d is not JSON" % n); continue
        R.append((n - 1, d))
        if d.get("status") != "ok" or d.get("gate") not in ("plan", "review", "security", "epoch"): continue
        s, p = str(d.get("session_id") or ""), str(d.get("parent_thread_id") or "")
        if not s or not p or s == p: F("gates.log row %d (%s) is not a child thread run" % (n, d.get("gate")))
        elif s in ids: F("gates.log row %d reuses the child session of row %d" % (n, ids[s]))
        else: ids[s] = n

    def fileof(d, g):
        f = os.path.join(ev, os.path.basename(str(d.get("file") or "-")))
        return f if os.path.isfile(f) and d.get("file_sha256") == sha(f) and re.fullmatch(g + r"-[^.]+\.json", os.path.basename(f)) else None

    def sop(f):
        try:
            o = json.load(open(f)); o = o.get("structured_output", o) if isinstance(o, dict) else None
            return o if isinstance(o, dict) else {}
        except Exception: return {}

    def prov(d, g, tr=None):
        tr = tr or tier
        if d.get("engine") != "t3-delegate" or d.get("provenance_mode") != "t3-verified": return "%s is not T3-verified" % g
        s, p = str(d.get("session_id") or ""), str(d.get("parent_thread_id") or "")
        if not s or not p or s == p: return "%s child session is missing or equals the parent" % g
        if g == "plan":
            if d.get("route") != "neon" or d.get("model") != NEON: return "plan is not the Neon route"
            if d.get("account") not in AG: return "plan account is not an Antigravity instance"
            want = "medium" if tr == "low" else "high"
            return "" if d.get("effort") == want else "plan effort %r is not %s" % (d.get("effort"), want)
        if d.get("route") != "opus" or d.get("model") != OPUS: return "%s is not the Opus 5.5 route" % g
        if d.get("account") not in CL: return "%s account is not a Claude instance" % g
        if g == "epoch":
            t = d.get("tier")
            if t not in ("medium", "high") or RANK[t] < RANK[tr]: return "epoch tier is below the task tier"
            return "" if d.get("effort") == ("medium" if t == "medium" else "high") else "epoch effort does not match its tier"
        if g == "security" or tr == "high": return "" if d.get("effort") == "high" else "%s effort %r is not high" % (g, d.get("effort"))
        return "" if d.get("effort") in ("medium", "high") else "%s effort %r is not medium or high" % (g, d.get("effort"))

    def gmerge(b, s):
        mb = subprocess.run(["git", "merge-base", "origin/" + b, s], capture_output=True).stdout.decode().strip()
        return (mb, hashlib.sha256(subprocess.run(["git", "diff", "--no-color", "--full-index", mb, s], capture_output=True).stdout).hexdigest()) if mb else None

    def bound(d, k):
        if d.get("head_sha") not in ("", None, k) or (base and d.get("head_sha") != k): return False
        if not base: return True
        m = gmerge(base, k); return bool(m) and d.get("base_ref") == "origin/" + base and d.get("base_sha") == m[0] and d.get("diff_sha256") == m[1]

    def jsonok(d, g, k):
        f = fileof(d, g)
        if not f: return None
        o = sop(f); fs = o.get("findings") or []
        if o.get("gate") != g or o.get("verdict") != "pass" or str(o.get("head_sha", "")) != k: return None
        if not isinstance(fs, list) or any(not isinstance(x, dict) or x.get("severity") == "important" for x in fs): return None
        return f

    def gdiff(s):
        m = gmerge(base, s) if base else None
        if not m: return None
        t = subprocess.run(["git", "diff", "--no-color", "--full-index", "--binary", m[0], s], capture_output=True).stdout.decode("utf-8", "surrogateescape")
        return "\n".join(re.sub(r"^@@ .* @@.*$", "@@", l) for l in t.split("\n"))

    auth = []
    for i, d in [(i, d) for i, d in R if d.get("gate") == "epoch" and d.get("status") == "ok" and d.get("verdict") == "pass"]:
        e = prov(d, "epoch")
        if e: F("epoch authorization row: " + e)
        elif not jsonok(d, "epoch", str(d.get("key", ""))): F("epoch record is missing, failing, or has an important finding")
        else: auth.append((i, d))
    E = auth[-1][0] if auth else -1
    plans = [(i, d) for i, d in R if d.get("gate") == "plan" and d.get("status") == "ok"]
    pd = plans[-1][1] if plans else None; P2 = next((i for i, d in plans if i > E), None); pt = ep(pd) if pd else None; p0 = min([t for t in (ep(d) for _, d in plans) if t is not None], default=None)
    live = lambda i: E < 0 or (P2 is not None and i > P2)
    if E >= 0 and P2 is None: F("epoch reset at row %d has no fresh plan after it" % (E + 1))
    if not pd: F("no logged plan row")
    else:
        e = prov(pd, "plan"); F("plan provenance: " + e) if e else P("plan provenance ok (neon %s, %s)" % (pd.get("effort"), pd.get("account")))
        if pd.get("tier") != tier: F("plan tier %r is not %s" % (pd.get("tier"), tier))
        if not fileof(pd, "plan"): F("plan file is missing or its sha256 does not match")
        elif pt is None: F("plan row has no parseable ts")
        fd = os.path.join(ev, "facts.md")
        if not os.path.isfile(fd): F("missing facts.md")
        elif pd.get("facts_sha256") != sha(fd): F("facts.md does not match plan.facts_sha256")
        else: P("facts.md matches plan.facts_sha256")

    res = {}; hd = gdiff(key) if mode == "repo" and base else None
    for g in ("review", "security") if tier == "high" else ("review",):
        gk = [(i, d) for i, d in R if d.get("gate") == g and d.get("key") == key]
        cand = [(i, d) for i, d in gk if d.get("status") in ("ok", "fail") and live(i)]
        pick, reason, fails, src = None, None, set(), None
        if cand:
            i, d = cand[-1]; e = prov(d, g)
            if d.get("status") != "ok": reason = "the last %s run at %s did not pass" % (g, key)
            elif d.get("verdict") != "pass" or not jsonok(d, g, key): reason = "%s-%s.json is missing, failing, or has an important finding" % (g, key)
            elif e: reason = "%s provenance: %s" % (g, e)
            elif RANK.get(d.get("tier", ""), -1) < RANK[tier]: reason = "%s row tier %r is below %s" % (g, d.get("tier"), tier)
            elif not bound(d, key): reason = "gate bound to a partial or different diff: %s-%s.json" % (g, key)
            else: pick = d
        elif any(d.get("status") == "ok" for i, d in gk): reason = "the %s on %s predates the epoch reset; a fresh plan must precede it" % (g, key)
        if pick:
            P("gate %s passes at %s" % (g, key)); res[g] = (ep(pick), pick); continue
        if cand: reason = reason or "missing passing %s-%s.json" % (g, key)
        elif mode == "repo" and base and hd:
            for i, d in R:
                x = d.get("key")
                if d.get("gate") == g and d.get("status") == "ok" and x and x != key and d.get("verdict") != "pass" and gdiff(x) == hd: fails.add(x)
            for i, d in R:
                x = d.get("key")
                if d.get("gate") != g or d.get("status") != "ok" or d.get("verdict") != "pass" or not x or x == key or not live(i): continue
                if RANK.get(d.get("tier", ""), -1) < RANK[tier] or prov(d, g) or not jsonok(d, g, x) or not bound(d, x) or x in fails or gdiff(x) != hd: continue
                src = d; break
            if fails: src = None; reason = "%s failed on this exact diff at an earlier head; never carried" % g
        if src:
            out.append("CARRY %s %s -> %s" % (g, src.get("key"), key)); logrow(ev, gate=g, tier=tier, key=key, status="carry", provider="", task_id=tid, reason="carried from " + str(src.get("key"))); res[g] = (ep(src), src)
        else: F(reason or "missing passing %s-%s.json" % (g, key))

    IL = [d for d in rows(os.path.join(ev, "impl.log")) if isinstance(d, dict)]; CS = [d for d in IL if d.get("status") != "start"]
    fc = None
    if mode == "repo" and base:
        nums = [int(x) for x in subprocess.run(["git", "log", "--format=%at", "origin/%s..%s" % (base, key)], capture_output=True).stdout.decode().split() if x.isdigit()]
        fc = min(nums) if nums else None
    t0 = ep(CS[0]) if CS else None; bad = []
    if CS and t0 is None: F("the first implementation row has no parseable ts")
    elif t0 is not None and p0 is not None and p0 > t0: bad.append(("the first implementation row", t0))
    if fc is not None and p0 is not None and p0 > fc: bad.append(("the branch's first commit", fc))
    DN = [d for d in IL if d.get("status") == "done"]
    if any(ep(d) is None for d in DN): F("a done implementation row has no parseable ts")
    low = lambda g: [(ep(d), d) for i, d in R if d.get("gate") == g and d.get("status") == "ok" and d.get("tier") == "low" and ep(d) is not None and live(i)]
    ft = min([t for t in (t0, fc) if t is not None], default=0)
    laid = bool(tier != "low" and pt is not None and ft < pt and pd and pd.get("tier") == tier and any(t <= ft for t, _ in low("plan")))
    exc = laid and any(t <= ft and not prov(d, "plan", "low") for t, d in low("plan")) and any(ft <= x[0] <= pt and not prov(x[1], "review", "low") for x in low("review")) and all(r[0] is not None and pt <= r[0] for r in res.values())
    if exc: P("code predates the plan: raised from Low, fresh %s plan before review" % tier)
    elif bad or laid: F("code before plan: %s predates the plan row" % ", ".join(x for x, _ in bad or [("the first code", ft)]))
    else: P("plan precedes code")
    done = [ep(d) for d in DN if ep(d) is not None]
    late = [g for g, r in res.items() if r[0] is None or (done and max(done) > r[0])]
    early = [g for g, r in res.items() if r[0] is not None and pt is not None and r[0] < pt]
    if late: F("code after the gate: the last completed implementation row is later than %s" % ",".join(sorted(late)))
    elif early: F("plan after the gate: the plan row is later than %s" % ",".join(sorted(early)))
    elif done: P("code precedes %s" % " and ".join(sorted(res)))

    s = plans[-1][0] + 1 if plans else 0; e0 = auth[-1][0] + 1 if auth else 0
    for g in ("review", "security") if tier == "high" else ("review",):
        n = len([1 for i, d in R if i >= s and live(i) and d.get("gate") == g and d.get("status") == "ok"])
        tot = len([1 for i, d in R if i >= e0 and live(i) and d.get("gate") == g and d.get("status") == "ok"])
        if n > 3 or tot > 6: F("%s has too many ok rounds (since plan/total: %d/%d; max 3/6)" % (g, n, tot))
        else: P("%s rounds ok (%d/%d)" % (g, n, tot))
    last = dict((d.get("gate"), d.get("status")) for i, d in R if i >= s and d.get("status") in ("ok", "blocked"))
    F("a blocked gate is logged") if "blocked" in last.values() else P("no blocked gate logged")
    denied = [i for i, d in R if i >= e0 and d.get("gate") == "epoch" and d.get("status") in ("ok", "blocked") and d.get("verdict") != "pass"]
    if len(auth) > 2: F("epoch authorizations: max 2 per task (%d)" % len(auth))
    elif denied: F("epoch authorizations: a denied epoch follows the active reset")
    else: P("epoch authorizations ok (%d)" % len(auth))
    okf = set((os.path.basename(str(d.get("file") or "-")), d.get("file_sha256")) for i, d in R if d.get("status") == "ok")
    stray = sorted(b for b in (os.path.basename(f) for f in glob.glob(os.path.join(ev, "*.json"))) if re.fullmatch(r"(plan|review|security|epoch)-[^.]+\.json", b) and (b, sha(os.path.join(ev, b))) not in okf)
    if stray: F("gate files not written by gate.sh: " + ",".join(stray))
    else: P("every gate file was written by gate.sh")
    print("\n".join(out))


a = sys.argv[1:]
if a and a[0] == "tiers": tiers(*a[1:3])
elif a and a[0] == "evidence": evidence(*a[1:6])
else: sys.exit("premerge_lib.py: unknown command " + " ".join(a[:1]))
