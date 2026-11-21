"""Facts the page uses to show local-only routing: tiers, flags and status."""
import kernel
from runs import Run


def _model_calls(run):
    return [event["data"] for event in run.events if event["type"] == "model_call"]


def test_confidential_model_calls_are_reported_as_local_and_free(tmp_path):
    run = Run()
    meter = kernel.Meter(1000, run=run, repo_root=tmp_path, confidential_requested=True)
    meter.log("draft", "strong", 10, 5, model="ollama/llama3")
    call = _model_calls(run)[0]
    assert call["tier"] == "local"
    assert call["usd"] == 0.0


def test_standard_model_calls_keep_their_tier(tmp_path):
    run = Run()
    meter = kernel.Meter(1000, run=run, repo_root=tmp_path)
    meter.log("draft", "strong", 10, 5, model="openai/gpt-4o-mini")
    assert _model_calls(run)[0]["tier"] == "strong"


def test_offline_stub_calls_stay_local(tmp_path):
    run = Run()
    meter = kernel.Meter(1000, run=run, repo_root=tmp_path)
    meter.log("draft (offline stub)", "cheap", 10, 5)
    assert _model_calls(run)[0]["tier"] == "local"


def test_brief_result_reports_confidential_and_web_off(tmp_path, monkeypatch):
    import modes

    monkeypatch.setattr(modes, "live_llm", lambda: False)
    run = Run()
    result = modes.run_brief(
        "Acme", "Planning", confidential=True, repo_root=tmp_path, run=run
    )
    assert result["confidential"] is True
    assert result["live"] is False
    details = [e["data"].get("detail", "") for e in run.events if e["type"] == "step"]
    assert any("web lookup off" in detail for detail in details)

    standard = modes.run_brief("Acme", "Planning", confidential=False, repo_root=tmp_path)
    assert standard["confidential"] is False


def test_status_reports_local_routing_and_price_facts(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    for name in ("LEDGER_LOCAL_CHAIN", "LOCAL_PROVIDERS", "BIFROST_URL", "BIFROST_VK_LOCAL"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(server.app)
    body = client.get("/api/status").json()
    assert body["local_models"] is False
    assert isinstance(body["prices_verified"], bool)

    monkeypatch.setenv("LEDGER_LOCAL_CHAIN", "ollama/llama3")
    monkeypatch.setenv("LOCAL_PROVIDERS", "ollama")
    monkeypatch.setenv("BIFROST_URL", "http://gateway.invalid")
    monkeypatch.setenv("BIFROST_VK_LOCAL", "local-key")
    assert client.get("/api/status").json()["local_models"] is True

    monkeypatch.setenv("LOCAL_PROVIDERS", "someone-else")
    assert client.get("/api/status").json()["local_models"] is False
