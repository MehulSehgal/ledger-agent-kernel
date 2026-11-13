import httpx
import pytest
from fastapi.testclient import TestClient

import router
from kernel import BudgetExhausted, Meter, UserUsageStore
from runs import Run
from server import app


def _success(url, provider, model):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            "extra_fields": {
                "routing_info": {
                    "provider": provider,
                    "model": model,
                    "is_fallback": provider != "openai",
                }
            },
        },
        request=httpx.Request("POST", url),
    )


def _meter(tmp_path, user_id="alice", cap=2000, user_cap=2000):
    return Meter(
        cap=cap,
        user_id=user_id,
        user_cap=user_cap,
        usage_store=UserUsageStore(tmp_path / "usage.json"),
    )


def test_429_retries_then_client_fallback_emits_failover(monkeypatch, tmp_path):
    monkeypatch.setenv("BIFROST_URL", "http://bifrost")
    monkeypatch.setenv("LEDGER_CHAIN_CHEAP", "openai/primary,anthropic/fallback")
    monkeypatch.setenv("LEDGER_VK_ALICE", "user-vk")
    monkeypatch.setattr(router.time, "sleep", lambda _: None)
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) <= 2:
            return httpx.Response(
                429,
                json={"error": "rate limited"},
                request=httpx.Request("POST", url),
            )
        return _success(url, "anthropic", "fallback")

    monkeypatch.setattr(router.httpx, "post", post)
    run = Run()
    meter = _meter(tmp_path)

    result = router.complete(run, meter, "draft", "cheap", "system", "prompt", "alice")

    assert result == "ok"
    assert len(calls) == 3
    assert calls[0][1]["json"]["fallbacks"] == ["anthropic/fallback"]
    assert calls[0][1]["json"]["max_tokens"] > 0
    assert calls[0][1]["headers"]["Authorization"] == "Bearer user-vk"
    failover = next(event for event in run.events if event["type"] == "failover")
    assert failover["data"]["from"] == "openai/primary"
    assert failover["data"]["to"] == "anthropic/fallback"
    assert "429" in failover["data"]["reason"]


def test_reservation_rejects_before_http_request(monkeypatch, tmp_path):
    monkeypatch.setenv("BIFROST_URL", "http://bifrost")
    monkeypatch.setenv("LEDGER_CHAIN_CHEAP", "openai/primary")
    calls = []
    monkeypatch.setattr(router.httpx, "post", lambda *args, **kwargs: calls.append(args))
    meter = _meter(tmp_path, cap=8, user_cap=1000)

    with pytest.raises(BudgetExhausted):
        router.complete(Run(), meter, "draft", "cheap", "system", "prompt", "alice")

    assert calls == []


def test_strong_reservation_rejects_when_full_cheap_request_cannot_fit(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("BIFROST_URL", "http://bifrost")
    monkeypatch.setenv("LEDGER_CHAIN_CHEAP", "openai/primary")
    calls = []
    monkeypatch.setattr(router.httpx, "post", lambda *args, **kwargs: calls.append(args))
    meter = _meter(tmp_path, cap=100, user_cap=1000)

    with pytest.raises(BudgetExhausted):
        router.complete(Run(), meter, "draft", "strong", "system", "prompt", "alice")

    assert calls == []


def test_user_cap_degrades_at_eighty_percent_then_stops(tmp_path):
    store = UserUsageStore(tmp_path / "usage.json")
    store.record_usage("alice", 80)
    run = Run()
    meter = Meter(
        cap=200,
        run=run,
        user_id="alice",
        user_cap=100,
        usage_store=store,
    )

    reservation = meter.reserve(est_in=1, max_out=10, tier="strong")

    assert reservation.tier == "cheap"
    meter.log(
        "call",
        reservation.tier,
        1,
        10,
        model="openai/model",
        reservation=reservation,
    )
    assert store.get_used("alice") == 91
    with pytest.raises(BudgetExhausted, match="alice"):
        meter.reserve(est_in=1, max_out=10, tier="cheap")
    assert run.events[-1]["type"] == "budget"
    assert run.events[-1]["data"]["state"] == "exhausted"

    reopened = UserUsageStore(tmp_path / "usage.json")
    assert reopened.get_used("alice") == 91


def test_chaos_endpoint_simulates_failure_and_marks_failover(monkeypatch, tmp_path):
    monkeypatch.setenv("LEDGER_DEMO", "1")
    monkeypatch.setenv("BIFROST_URL", "http://bifrost")
    monkeypatch.setenv("LEDGER_CHAIN_CHEAP", "openai/primary,anthropic/fallback")
    monkeypatch.setattr(router.time, "sleep", lambda _: None)
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs)
        return _success(url, "anthropic", "fallback")

    monkeypatch.setattr(router.httpx, "post", post)
    client = TestClient(app)
    configured = client.post(
        "/api/chaos",
        json={"target": "openai/primary", "mode": "429"},
    )
    assert configured.status_code == 200

    run = Run()
    router.complete(run, _meter(tmp_path), "draft", "cheap", "system", "prompt", "alice")

    assert len(calls) == 1
    failover = next(event for event in run.events if event["type"] == "failover")
    assert failover["data"]["reason"] == "chaos (simulated)"
    client.post("/api/chaos", json={"target": "openai/primary", "mode": "off"})


def test_run_cache_avoids_second_request_and_receipt_marks_prices_unverified(monkeypatch, tmp_path):
    monkeypatch.setenv("BIFROST_URL", "http://bifrost")
    monkeypatch.setenv("LEDGER_CHAIN_CHEAP", "openai/primary")
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs)
        return _success(url, "openai", "primary")

    monkeypatch.setattr(router.httpx, "post", post)
    run = Run()
    meter = _meter(tmp_path)

    assert router.complete(run, meter, "draft", "cheap", "system", "prompt", "alice") == "ok"
    tokens_after_first = meter.used()
    assert router.complete(run, meter, "draft", "cheap", "system", "prompt", "alice") == "ok"

    assert len(calls) == 1
    assert meter.used() == tokens_after_first
    assert any(event["type"] == "model_call" and event["data"]["cached"] for event in run.events)
    receipt = meter.receipt()
    assert receipt["prices_verified"] is False
    assert receipt["usd"] is None


def test_chaos_route_is_disabled_without_demo_flag(monkeypatch):
    monkeypatch.delenv("LEDGER_DEMO", raising=False)

    response = TestClient(app).post(
        "/api/chaos",
        json={"target": "openai/primary", "mode": "down"},
    )

    assert response.status_code == 404
