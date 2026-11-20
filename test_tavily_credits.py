"""Tavily credit accounting and cap, using an in-process fake HTTP client."""
from datetime import date

import pytest

import kernel


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeWeb:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/search"):
            return FakeResponse({"results": [
                {"url": "https://a.example/1", "title": "t", "content": "c",
                 "published_date": "2026-11-01"}]})
        urls = kwargs["json"]["urls"]
        ok = urls[: max(len(urls) - 1, 1)]
        return FakeResponse({
            "results": [{"url": u, "raw_content": "x"} for u in ok],
            "failed_results": [{"url": u} for u in urls if u not in ok],
        })


@pytest.fixture(autouse=True)
def reset_counter(monkeypatch):
    monkeypatch.setattr(kernel, "_TAVILY_CREDITS_SPENT", 0)
    monkeypatch.delenv("LEDGER_TAVILY_CREDIT_CAP", raising=False)


def run(fn, *args, **kwargs):
    web = FakeWeb()
    with kernel.service_context(live_web=True, web_client=web, web_api_key="k"):
        return web, fn(*args, **kwargs)


def test_search_pins_basic_depth_and_costs_one_credit():
    web, _ = run(kernel.tavily_news, "q", date(2026, 11, 20))
    assert web.calls[0][1]["json"]["search_depth"] == "basic"
    assert kernel.tavily_credits_spent() == 1


def test_extract_charges_one_credit_per_five_successful_urls():
    urls = [f"https://a.example/{i}" for i in range(11)]  # 10 succeed, 1 fails
    _, (texts, failed) = run(kernel.tavily_extract, urls, "q")
    assert len(texts) == 10 and len(failed) == 1
    assert kernel.tavily_credits_spent() == 2


def test_cap_blocks_before_request_is_sent(monkeypatch):
    monkeypatch.setenv("LEDGER_TAVILY_CREDIT_CAP", "2")
    web = FakeWeb()
    with kernel.service_context(live_web=True, web_client=web, web_api_key="k"):
        kernel.tavily_news("q", date(2026, 11, 20))
        kernel.tavily_news("q", date(2026, 11, 20))
        with pytest.raises(kernel.WebSearchError, match="credit cap"):
            kernel.tavily_news("q", date(2026, 11, 20))
    assert len(web.calls) == 2  # third call never left the process


def test_invalid_cap_is_rejected(monkeypatch):
    monkeypatch.setenv("LEDGER_TAVILY_CREDIT_CAP", "abc")
    with pytest.raises(ValueError):
        kernel.tavily_credit_cap()
