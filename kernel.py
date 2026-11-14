"""Ledger kernel: token meter + budget degrade, verification gate, Bifrost/Tavily clients."""
import json, os, re, httpx, tempfile, threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from policy import classify_confidential
from runs import NullRun

tok = lambda s: max(1, len(s) // 4)

class BudgetExhausted(Exception): pass
class GatewayError(RuntimeError): pass
class WebSearchError(RuntimeError): pass

PRICE_PATH = Path(__file__).with_name("prices.json")
_price_data = json.loads(PRICE_PATH.read_text(encoding="utf-8"))
if not isinstance(_price_data, dict) or not isinstance(_price_data.get("models"), dict):
    raise ValueError("prices.json must contain a models object")
PRICE_VERIFIED = _price_data.get("verified") is True
PRICE = _price_data["models"]
_SERVICE_CONTEXT = ContextVar("ledger_service_context", default=None)


@contextmanager
def service_context(*, live_llm=None, live_web=None, web_client=None, web_api_key=None):
    context = dict(_SERVICE_CONTEXT.get() or {})
    if live_llm is not None:
        context["live_llm"] = bool(live_llm)
    if live_web is not None:
        context["live_web"] = bool(live_web)
    if web_client is not None:
        context["web_client"] = web_client
    if web_api_key is not None:
        context["web_api_key"] = web_api_key
    token = _SERVICE_CONTEXT.set(context)
    try:
        yield
    finally:
        _SERVICE_CONTEXT.reset(token)


def _web_post(url, **kwargs):
    context = _SERVICE_CONTEXT.get() or {}
    client = context.get("web_client")
    if client is not None:
        return client.post(url, **kwargs)
    return httpx.post(url, **kwargs)


def _web_api_key():
    context = _SERVICE_CONTEXT.get() or {}
    if "web_api_key" in context:
        return context["web_api_key"]
    return os.environ["TAVILY_API_KEY"]


class UserUsageStore:
    """Persist committed token usage and reserve capacity across concurrent runs."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._pending = {}

    def _path(self):
        if self.path is not None:
            return self.path
        configured = os.getenv("LEDGER_USAGE_FILE")
        return Path(configured) if configured else Path.home() / ".ledger-agent-kernel" / "usage.json"

    def _read_locked(self):
        path = self._path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid usage JSON in {path}") from exc
        if not isinstance(payload, dict) or any(
            not isinstance(user, str) or isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0
            for user, tokens in payload.items()
        ):
            raise ValueError(f"invalid usage data in {path}")
        return payload

    def _write_locked(self, payload):
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as output:
                name = output.name
                json.dump(payload, output, separators=(",", ":"), sort_keys=True)
            os.replace(name, path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def total_used(self, user_id):
        with self._lock:
            return self._read_locked().get(user_id, 0) + self._pending.get(user_id, 0)

    def reserve(self, user_id, tokens, cap):
        with self._lock:
            used = self._read_locked().get(user_id, 0) + self._pending.get(user_id, 0)
            if used + tokens > cap:
                raise BudgetExhausted(f"Token budget exhausted for user {user_id}.")
            self._pending[user_id] = self._pending.get(user_id, 0) + tokens

    def release(self, user_id, tokens):
        with self._lock:
            pending = self._pending.get(user_id, 0) - tokens
            if pending > 0:
                self._pending[user_id] = pending
            else:
                self._pending.pop(user_id, None)

    def reconcile(self, user_id, reserved, actual):
        with self._lock:
            pending = self._pending.get(user_id, 0) - reserved
            if pending > 0:
                self._pending[user_id] = pending
            else:
                self._pending.pop(user_id, None)
            payload = self._read_locked()
            payload[user_id] = payload.get(user_id, 0) + actual
            self._write_locked(payload)

    def record_usage(self, user_id, tokens):
        if tokens <= 0:
            return
        with self._lock:
            payload = self._read_locked()
            payload[user_id] = payload.get(user_id, 0) + tokens
            self._write_locked(payload)

    def get_used(self, user_id):
        with self._lock:
            return self._read_locked().get(user_id, 0)


USER_USAGE = UserUsageStore()


@dataclass
class Reservation:
    tier: str
    est_in: int
    max_tokens: int
    user_id: str | None
    closed: bool = False

    @property
    def tokens(self):
        return self.est_in + self.max_tokens


@dataclass
class Meter:
    cap: int = 12000
    calls: list = field(default_factory=list)
    run: object = field(default_factory=NullRun, repr=False, compare=False)
    user_id: str | None = None
    user_cap: int | None = None
    usage_store: UserUsageStore = field(default_factory=lambda: USER_USAGE, repr=False, compare=False)
    repo_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent,
        repr=False,
        compare=False,
    )
    confidential_requested: bool = False
    confidential: bool = False
    _pending_tokens: int = field(default=0, init=False, repr=False)
    _lock: object = field(default_factory=threading.RLock, init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.cap <= 0:
            raise ValueError("token budget must be positive")
        self.repo_root = Path(self.repo_root).resolve()
        self.confidential = self.confidential or classify_confidential(
            self.repo_root,
            self.confidential_requested,
        )
        if self.user_id is not None:
            self.user_id = str(self.user_id).strip()[:128] or "default"
            if self.user_cap is None:
                try:
                    self.user_cap = int(os.getenv("LEDGER_USER_CAP", "12000"))
                except ValueError as exc:
                    raise ValueError("LEDGER_USER_CAP must be a positive integer") from exc
            if self.user_cap <= 0:
                raise ValueError("LEDGER_USER_CAP must be a positive integer")

    def refresh_confidential(self, request_flag=None):
        self.confidential = self.confidential or classify_confidential(
            self.repo_root,
            self.confidential_requested or bool(request_flag),
        )
        return self.confidential

    def used(self): return sum(c["in"] + c["out"] for c in self.calls)

    def reserve(self, est_in, max_out, tier):
        if est_in < 0 or max_out < 1:
            raise ValueError("reservation token counts must be non-negative and max_out positive")
        if tier not in ("cheap", "strong"):
            raise ValueError("tier must be cheap or strong")
        with self._lock:
            local_used = self.used() + self._pending_tokens
            user_used = (
                self.usage_store.total_used(self.user_id)
                if self.user_id is not None else 0
            )
            total = est_in + max_out
            effective_tier = tier
            user_cap = self.user_cap if self.user_id is not None else None
            crosses_local_soft_cap = local_used + total >= 0.8 * self.cap
            crosses_user_soft_cap = (
                user_cap is not None and user_used + total >= 0.8 * user_cap
            )
            if tier == "strong" and (crosses_local_soft_cap or crosses_user_soft_cap):
                effective_tier = "cheap"

            exceeds_local = local_used + total > self.cap
            exceeds_user = user_cap is not None and user_used + total > user_cap
            if tier == "strong" and (exceeds_local or exceeds_user):
                effective_tier = "cheap"
            if exceeds_local or exceeds_user:
                self._emit_budget("exhausted")
                if exceeds_user:
                    raise BudgetExhausted(f"Token budget exhausted for user {self.user_id}.")
                raise BudgetExhausted("Token budget exhausted.")

            reservation = Reservation(
                tier=effective_tier,
                est_in=est_in,
                max_tokens=max_out,
                user_id=self.user_id,
            )
            if self.user_id is not None:
                try:
                    self.usage_store.reserve(self.user_id, reservation.tokens, user_cap)
                except BudgetExhausted:
                    self._emit_budget("exhausted")
                    raise
            self._pending_tokens += reservation.tokens
            return reservation

    def release(self, reservation):
        with self._lock:
            if reservation.closed:
                return
            self._pending_tokens -= reservation.tokens
            if reservation.user_id is not None:
                self.usage_store.release(reservation.user_id, reservation.tokens)
            reservation.closed = True

    def _emit_budget(self, state=None):
        cap = self.cap
        used = self.used()
        if self.user_id is not None:
            cap = self.user_cap
            used = self.usage_store.total_used(self.user_id)
        pct = round(100 * used / cap, 2)
        if state is None:
            state = "exhausted" if used >= cap else "degraded" if used >= 0.8 * cap else "ok"
        self.run.emit("budget", {
            "used": used,
            "cap": cap,
            "pct": pct,
            "state": state,
            "user": self.user_id or "default",
        })

    def pick(self, want):
        u = self.used()
        if u >= self.cap:
            self._emit_budget("exhausted")
            raise BudgetExhausted()
        return "cheap" if want == "strong" and u >= 0.8 * self.cap else want  # degrade at 80%

    def _model_cost(self, model, tin, tout):
        if not PRICE_VERIFIED:
            return None
        price = PRICE.get(model)
        if not isinstance(price, dict):
            return None
        input_rate = price.get("input_per_mtok")
        output_rate = price.get("output_per_mtok")
        if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
            return None
        return (tin * input_rate + tout * output_rate) / 1_000_000

    def log(self, label, tier, tin, tout, model=None, reservation=None, cached=False,
            tokens_cached=None):
        if tokens_cached is not None and (
            isinstance(tokens_cached, bool)
            or not isinstance(tokens_cached, int)
            or tokens_cached < 0
        ):
            raise ValueError("tokens_cached must be a non-negative integer or None")
        model = model or "offline"
        if reservation is not None and not reservation.closed:
            if reservation.user_id is not None:
                self.usage_store.reconcile(
                    reservation.user_id,
                    reservation.tokens,
                    tin + tout,
                )
            reservation.closed = True
            with self._lock:
                self._pending_tokens -= reservation.tokens
        elif self.user_id is not None:
            self.usage_store.record_usage(self.user_id, tin + tout)
        self.calls.append({
            "label": label,
            "tier": tier,
            "in": tin,
            "out": tout,
            "tokens_cached": tokens_cached,
            "model": model,
        })
        event_tier = tier if model != "offline" else "local"
        usd = 0.0 if event_tier == "local" else self._model_cost(model, tin, tout)
        self.run.emit("model_call", {
            "label": label,
            "tier": event_tier,
            "model": model,
            "tokens_in": tin,
            "tokens_out": tout,
            "tokens_cached": tokens_cached,
            "usd": round(usd, 8) if usd is not None else None,
            "cached": cached,
        })
        self._emit_budget()

    def receipt(self):
        usd = 0.0
        if not PRICE_VERIFIED:
            usd = None
        else:
            for call in self.calls:
                if call["model"] == "offline":
                    continue
                cost = self._model_cost(call["model"], call["in"], call["out"])
                if cost is None:
                    usd = None
                    break
                usd += cost
            if usd is not None:
                usd = round(usd, 6)
        return {
            "calls": self.calls,
            "tokens": self.used(),
            "cap": self.cap,
            "usd": usd,
            "prices_verified": PRICE_VERIFIED,
        }

def live_llm():
    context = _SERVICE_CONTEXT.get() or {}
    return context.get("live_llm", bool(os.getenv("BIFROST_URL")))

def live_web():
    context = _SERVICE_CONTEXT.get() or {}
    return context.get("live_web", bool(os.getenv("TAVILY_API_KEY")))

def chat(meter, label, want, system, user, user_id=None):
    """Route one model call through the shared resilient router."""
    from router import complete

    return complete(
        meter.run,
        meter,
        label,
        want,
        system,
        user,
        user_id or meter.user_id,
    )

def to_iso(s):
    if not s: return None
    try: return parsedate_to_datetime(s).date().isoformat()
    except Exception: return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None

def in_window(d, today, window=30):
    try: return today - timedelta(window) <= date.fromisoformat(d) <= today
    except Exception: return False

def tavily_news(query, today, window=30):
    try:
        response = _web_post(
            "https://api.tavily.com/search",
            timeout=30,
            headers={"Authorization": "Bearer " + _web_api_key()},
            json={"query": query, "topic": "news", "max_results": 5,
                  "start_date": (today - timedelta(window)).isoformat(), "end_date": today.isoformat()},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if not isinstance(results, list):
            raise ValueError("results must be a list")
        return [
            {"url": x["url"], "title": x["title"], "date": to_iso(x.get("published_date")),
             "text": x.get("content", "")}
            for x in results
        ]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise WebSearchError(f"Tavily request failed: {exc}") from exc

def tavily_extract(urls, query, chunks=3):
    """Extract content from URLs in Tavily-compatible batches of up to 20."""
    if not 1 <= chunks <= 5:
        raise ValueError("chunks must be between 1 and 5")
    texts, failed = {}, []
    urls = list(dict.fromkeys(urls))
    for offset in range(0, len(urls), 20):
        batch = urls[offset:offset + 20]
        if not batch:
            continue
        try:
            response = _web_post(
                "https://api.tavily.com/extract",
                timeout=60,
                headers={"Authorization": "Bearer " + _web_api_key()},
                json={
                    "urls": batch,
                    "query": query,
                    "chunks_per_source": chunks,
                    "extract_depth": "basic",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("extract response must be an object")
            results = payload.get("results", [])
            failed_results = payload.get("failed_results", [])
            if not isinstance(results, list) or not isinstance(failed_results, list):
                raise ValueError("results and failed_results must be lists")
            returned = set()
            for item in results:
                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                    raise ValueError("each extraction result must contain a URL")
                if not isinstance(item.get("raw_content"), str):
                    raise ValueError("each extraction result must contain raw_content")
                texts[item["url"]] = item["raw_content"]
                returned.add(item["url"])
            for item in failed_results:
                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                    raise ValueError("each failed extraction result must contain a URL")
                failed.append(item["url"])
                returned.add(item["url"])
            failed.extend(url for url in batch if url not in returned)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise WebSearchError(f"Tavily extract request failed: {exc}") from exc
    return texts, list(dict.fromkeys(failed))

from gate import verify
