"""Brief mode and Fix mode on the shared kernel. Runs fully offline unless BIFROST_URL / TAVILY_API_KEY are set."""
import re, ast, sys, json, tempfile, subprocess
from pathlib import Path
from datetime import date, timedelta
from math import log
from kernel import *

QUERIES = {"news": "{c} news", "launches": "{c} product launch", "hires": "{c} hires appointed",
           "funding": "{c} funding raised", "risks": "{c} lawsuit OR outage OR layoffs"}
sents = lambda t: [x for x in re.split(r"(?<=[.!?])\s+", t) if len(x) > 25]

def demo_sources(c, t):
    d = lambda n: (t - timedelta(n)).isoformat()
    rows = [("launches", 3, "Atlas 2 launch", f"{c} unveiled Atlas 2, a warehouse robot that moves 40 percent more pallets per hour. Shipments begin in December. Analysts called the pricing aggressive."),
            ("hires", 9, "New chief revenue officer", f"{c} hired Dana Reyes as chief revenue officer. Reyes previously ran sales at a logistics software firm. The company also added 15 engineers this quarter."),
            ("funding", 14, "Series C round", f"{c} closed a $60 million Series C led by Northgate Capital. The round values the company at $480 million. Proceeds will fund a second factory."),
            ("risks", 21, "Supplier delay", f"{c} warned that a battery supplier delay could push some deliveries into January. Two customers have asked for revised schedules."),
            ("news", 45, "Old profile", f"{c} was profiled in a trade magazine. The piece covered its 2019 founding and early customers."),
            ("news", None, "Undated post", f"{c} announced a partnership with a regional port authority.")]
    return [{"topic": k, "title": ti, "url": f"https://news.example.com/{i}", "date": d(n) if n else None, "text": tx} for i, (k, n, ti, tx) in enumerate(rows)]

def extract_offline(srcs, inject=True):
    """Offline 'cheap model': TF-IDF salience over sentences, top 2 per source. Optionally injects two
    bad claims (fabricated quote, wrong number) so the verification gate has something to catch."""
    allx = [x for s in srcs for x in sents(s["text"])]; df = {}
    for x in allx:
        for w in set(re.findall(r"[a-z]{3,}", x.lower())): df[w] = df.get(w, 0) + 1
    def score(x):
        ws = set(re.findall(r"[a-z]{3,}", x.lower()))
        return sum(log(1 + len(allx) / df[w]) for w in ws) / (len(ws) + 1) + 1.5 * bool(re.search(r"\d", x))
    out = [{"source_id": s["id"], "claim": x, "quote": x} for s in srcs for x in sorted(sents(s["text"]), key=score, reverse=True)[:2]]
    if inject and srcs:
        out.append({"source_id": srcs[0]["id"], "claim": "Atlas 2 won a $90 million defence contract.", "quote": "Atlas 2 won a $90 million defence contract."})
        h = next((s for s in srcs if "15 engineers" in s["text"]), None)
        if h: out.append({"source_id": h["id"], "claim": "The company added 25 engineers this quarter.", "quote": "The company also added 15 engineers this quarter."})
    return out

def run_brief(company, meeting, cap=12000):
    m, today = Meter(cap), date.today()
    live = live_web()
    raw = [dict(s, topic=k) for k, q in QUERIES.items() for s in tavily_news(q.format(c=company), today)] if live else demo_sources(company, today)
    seen, srcs, dropped = set(), [], []
    for s in raw:   # pre-filter before paying for extraction
        why = "date missing" if not s["date"] else "outside 30-day window" if not in_window(s["date"], today) else "duplicate URL" if s["url"] in seen else None
        if why: dropped.append({"title": s["title"], "reason": why}); continue
        seen.add(s["url"]); s["id"] = len(srcs); srcs.append(s)
    ctx = "\n".join(f"[{s['id']}] {s['text']}" for s in srcs)
    if live_llm():
        try: claims = json.loads(re.search(r"\[.*\]", chat(m, "extract claims", "cheap", "Return ONLY a JSON list of {source_id, claim, quote}. quote must be verbatim.", f"Company: {company}\n{ctx}"), re.S).group())
        except Exception: claims = []
    else:
        claims = extract_offline(srcs); m.log("extract claims (offline stub)", "cheap", tok(ctx), tok(json.dumps(claims)))
    ok, rejected = [], []
    for c in claims:
        why = verify(c, srcs[c["source_id"]] if isinstance(c.get("source_id"), int) and c["source_id"] < len(srcs) else None, today)
        (rejected.append({"claim": c["claim"], "reason": why}) if why else ok.append(c))
    nums = {i: n + 1 for n, i in enumerate(sorted({c["source_id"] for c in ok}))}
    bullets = []
    if ok:   # strong model is only called when something survived the gate
        if live_llm():
            txt = chat(m, "synthesize", "strong", "Write short bullets. End each with citation ids like [3]. Use only the claims given.",
                       json.dumps([{"id": nums[c["source_id"]], "claim": c["claim"]} for c in ok]))
            for l in txt.splitlines():
                ids = [int(i) for i in re.findall(r"\[(\d+)\]", l)]
                if ids and all(i in nums.values() for i in ids): bullets.append({"text": re.sub(r"\s*\[\d+\]", "", l).lstrip("-* "), "cites": ids})
        else:
            for c in ok: bullets.append({"text": c["claim"], "topic": srcs[c["source_id"]]["topic"], "cites": [nums[c["source_id"]]]})
            m.log("synthesize (offline stub)", "strong", tok(json.dumps(ok)), tok(json.dumps(bullets)))
    for b in bullets: b["quote"] = next((c["quote"] for c in ok if nums[c["source_id"]] in b["cites"] and c["claim"] == b["text"]), "")
    r = m.receipt(); base = tok("\n".join(s["text"] for s in srcs)) + 400
    return {"mode": "brief", "live": live, "company": company, "meeting": meeting, "window": [(today - timedelta(30)).isoformat(), today.isoformat()],
            "sources": [{"n": nums[s["id"]], "title": s["title"], "url": s["url"], "date": s["date"]} for s in srcs if s["id"] in nums],
            "bullets": bullets, "open_questions": [f"What is the delivery plan if the supplier delay persists? (inference)", f"How will {company} use the second factory to change its pricing? (inference)"],
            "audit": {"accepted": len(ok), "rejected": rejected, "pre_dropped": dropped}, "receipt": r,
            "baseline_tokens": base, "cost_per_verified": round(r["usd"] / max(len(ok), 1), 6)}

# ---------------- Fix mode ----------------
TOY = {"cart.py": '''PRICES = {"pen": 2, "book": 12}

def format_price(x):
    return "$%.2f" % x

def apply_discount(x, pct):
    return x * (1 - pct / 100)

def total(items):
    return sum(i["price"] for i in items)

def receipt_lines(items):
    return [f'{i["name"]}: {format_price(i["price"] * i["qty"])}' for i in items]

def shipping(x):
    return 0 if x > 50 else 5
''', "test_cart.py": '''from cart import total

def test_total_uses_quantity():
    items = [{"name": "pen", "price": 10, "qty": 2}, {"name": "book", "price": 5, "qty": 2}]
    assert total(items) == 30
'''}

def pytest(d):
    p = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "--tb=short", "-p", "no:cacheprovider"], cwd=d, capture_output=True, text=True,
                       env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})  # no stale bytecode
    return p.returncode == 0, p.stdout

def run_fix(cap=6000):
    d = Path(tempfile.mkdtemp()); m = Meter(cap); steps = []
    for n, t in TOY.items(): (d / n).write_text(t)
    green, out = pytest(d); steps.append({"step": "Run tests", "detail": "failing" if not green else "already green, 0 tokens spent", "ok": green})
    if green: return {"mode": "fix", "steps": steps, "receipt": m.receipt(), "status": "green"}
    frames = {f for _, _, f in re.findall(r"^(\S+\.py):(\d+): in (\w+)", out, re.M)}
    defs = {}
    for f in d.glob("*.py"):
        src = f.read_text()
        for n in ast.parse(src).body:
            if isinstance(n, ast.FunctionDef): defs[n.name] = (f.name, ast.get_source_segment(src, n))
    called = {c.func.id for n in ast.walk(ast.parse(TOY["test_cart.py"])) for c in [n] if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    cands = [k for k in defs if (k in frames or k in called) and not k.startswith("test_")]
    repo_map = "\n".join(f"{f}: def {n}(...)" for n, (f, _) in defs.items())
    ctx = repo_map + "\n\n" + "\n\n".join(defs[k][1] for k in cands)
    full = sum(len(t) for t in TOY.values()) // 4
    steps.append({"step": "Localize (no LLM)", "detail": f"traceback frames + called symbols → {', '.join(cands)}; context {tok(ctx)} tok vs {full} tok full files", "ok": True})
    fail = "\n".join(l for l in out.splitlines() if l.startswith("E "))[:300]
    prompt = f"Fix the bug. Reply with SEARCH/REPLACE blocks only.\nFailure: {fail}\n{ctx}"
    try:
        if live_llm(): reply = chat(m, "patch", "strong", "Output <<<SEARCH ... === ... >>>REPLACE blocks for file cart.py.", prompt)
        else:
            reply = '<<<SEARCH\n    return sum(i["price"] for i in items)\n===\n    return sum(i["price"] * i["qty"] for i in items)\n>>>REPLACE'
            m.log("patch (offline stub)", "strong", tok(prompt), tok(reply))
    except BudgetExhausted:
        return {"mode": "fix", "steps": steps + [{"step": "Budget", "detail": "cap reached, returning partial result", "ok": False}], "receipt": m.receipt(), "status": "partial"}
    diff = []
    for a, b in re.findall(r"<<<SEARCH\n(.*?)\n===\n(.*?)\n>>>REPLACE", reply, re.S):
        p = d / "cart.py"; s = p.read_text()
        if s.count(a) == 1: p.write_text(s.replace(a, b)); diff.append({"old": a, "new": b})
    steps.append({"step": "Apply diff-only edit", "detail": f"{len(diff)} SEARCH/REPLACE block applied", "ok": bool(diff)})
    green, _ = pytest(d); steps.append({"step": "Re-run tests", "detail": "green, early exit" if green else "still failing", "ok": green})
    r = m.receipt(); base = full + tok(out) * 3
    return {"mode": "fix", "live": live_llm(), "steps": steps, "diff": diff, "receipt": r, "baseline_tokens": base, "status": "green" if green else "red"}
