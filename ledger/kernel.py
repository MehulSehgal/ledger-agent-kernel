"""Ledger kernel: token meter + budget degrade, verification gate, Bifrost/Tavily clients."""
import os, re, httpx
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from rapidfuzz import fuzz

PRICE = {"cheap": (0.15, 0.60), "strong": (3.00, 15.00)}  # $/Mtok, PLACEHOLDERS: set real rates
tok = lambda s: max(1, len(s) // 4)

class BudgetExhausted(Exception): pass

@dataclass
class Meter:
    cap: int = 12000
    calls: list = field(default_factory=list)
    def used(self): return sum(c["in"] + c["out"] for c in self.calls)
    def pick(self, want):
        u = self.used()
        if u >= self.cap: raise BudgetExhausted()
        return "cheap" if want == "strong" and u >= 0.8 * self.cap else want  # degrade at 80%
    def log(self, label, tier, tin, tout):
        self.calls.append({"label": label, "tier": tier, "in": tin, "out": tout})
    def receipt(self):
        usd = sum(c["in"] * PRICE[c["tier"]][0] + c["out"] * PRICE[c["tier"]][1] for c in self.calls) / 1e6
        return {"calls": self.calls, "tokens": self.used(), "cap": self.cap, "usd": round(usd, 6)}

def live_llm(): return bool(os.getenv("BIFROST_URL"))
def live_web(): return bool(os.getenv("TAVILY_API_KEY"))

def chat(meter, label, want, system, user):
    """One call through the Bifrost gateway (OpenAI-compatible). Models are provider/model strings."""
    tier = meter.pick(want)
    model = os.getenv(f"LEDGER_{tier.upper()}", "openai/gpt-4o-mini" if tier == "cheap" else "anthropic/claude-sonnet-4-5")
    r = httpx.post(os.environ["BIFROST_URL"].rstrip("/") + "/v1/chat/completions", timeout=90,
                   json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).json()
    out, u = r["choices"][0]["message"]["content"], r.get("usage", {})
    meter.log(label, tier, u.get("prompt_tokens", tok(system + user)), u.get("completion_tokens", tok(out)))
    return out

def to_iso(s):
    if not s: return None
    try: return parsedate_to_datetime(s).date().isoformat()
    except Exception: return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None

def in_window(d, today, window=30):
    try: return today - timedelta(window) <= date.fromisoformat(d) <= today
    except Exception: return False

def tavily_news(query, today, window=30):
    r = httpx.post("https://api.tavily.com/search", timeout=30,
                   headers={"Authorization": "Bearer " + os.environ["TAVILY_API_KEY"]},
                   json={"query": query, "topic": "news", "max_results": 5,
                         "start_date": (today - timedelta(window)).isoformat(), "end_date": today.isoformat()}).json()
    return [{"url": x["url"], "title": x["title"], "date": to_iso(x.get("published_date")), "text": x.get("content", "")}
            for x in r.get("results", [])]

norm = lambda s: re.sub(r"\s+", " ", s.lower().replace(",", "")).strip()

def verify(c, src, today, window=30):
    """Cheap deterministic gate. Returns None if the claim passes, else the rejection reason."""
    if not src: return "source not in fetched set"
    if not src.get("date"): return "source date missing"
    if not in_window(src["date"], today, window): return "source date outside window"
    q = norm(c["quote"])
    if fuzz.partial_ratio(q, norm(src["text"])) < 92: return "quote not found in source text"
    for n in re.findall(r"\d+(?:\.\d+)?", norm(c["claim"])):
        if n not in q: return f"number {n} not in quote"
    return None
