import httpx
from fastapi.testclient import TestClient
from datetime import date, timedelta
from kernel import GatewayError, Meter, BudgetExhausted, WebSearchError, tavily_news, verify
from server import BriefIn, FixIn, app
from modes import pytest as run_pytest, run_brief, run_fix
from pathlib import Path

T = date.today()
SRC = {"date": (T - timedelta(3)).isoformat(), "text": "Acme closed a $60 million Series C round."}

def test_verify_pass():
    assert verify({"claim": "Acme raised $60 million", "quote": "closed a $60 million Series C"}, SRC, T) is None

def test_verify_rejects():
    assert verify({"claim": "x", "quote": "never said this anywhere"}, SRC, T) == "quote not found in source text"
    assert "number 90" in verify({"claim": "raised 90", "quote": "closed a $60 million Series C"}, SRC, T)
    assert verify({"claim": "x", "quote": "Acme closed"}, dict(SRC, date=(T - timedelta(45)).isoformat()), T) == "source date outside window"
    assert verify({"claim": "x", "quote": "Acme closed"}, None, T) == "source not in fetched set"

def test_budget_degrade_and_cap():
    m = Meter(100); assert m.pick("strong") == "strong"
    m.log("a", "cheap", 80, 0); assert m.pick("strong") == "cheap"
    m.log("b", "cheap", 30, 0)
    try: m.pick("cheap"); assert False
    except BudgetExhausted: pass

def test_meter_rejects_non_positive_budget():
    try:
        Meter(0)
        assert False
    except ValueError as exc:
        assert str(exc) == "token budget must be positive"

def test_gateway_errors_are_explicit(monkeypatch):
    class FailedResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("unexpected", request=httpx.Request("POST", "http://gateway"), response=httpx.Response(502))

    def request(*args, **kwargs):
        return FailedResponse()

    monkeypatch.setattr("kernel.httpx.post", request)
    monkeypatch.setenv("BIFROST_URL", "http://gateway")
    try:
        from kernel import chat
        chat(Meter(), "test", "cheap", "system", "user")
        assert False
    except GatewayError:
        pass

def test_web_search_errors_are_explicit(monkeypatch):
    class FailedResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("unexpected", request=httpx.Request("POST", "http://tavily"), response=httpx.Response(503))

    monkeypatch.setattr("kernel.httpx.post", lambda *args, **kwargs: FailedResponse())
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    try:
        tavily_news("Acme", T)
        assert False
    except WebSearchError as exc:
        assert "Tavily request failed" in str(exc)

def test_api_inputs_are_trimmed_and_bounded():
    request = BriefIn(company="  Acme  ", meeting="  Thu 3pm  ", cap=500)
    assert request.company == "Acme"
    assert request.meeting == "Thu 3pm"
    assert FixIn(cap=100).cap == 100
    for model, kwargs in ((BriefIn, {"company": " ", "meeting": "Thu 3pm"}), (FixIn, {"cap": 99})):
        try:
            model(**kwargs)
            assert False
        except ValueError:
            pass

def test_brief_gate():
    r = run_brief("Acme Robotics", "Thu 3pm")
    assert len(r["audit"]["rejected"]) == 2 and len(r["audit"]["pre_dropped"]) == 2 and r["bullets"]

def test_fix_goes_green():
    assert run_fix()["status"] == "green"

def test_pytest_removes_credentials_from_subprocess_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-secret")
    (tmp_path / "test_env.py").write_text(
        "import os\n"
        "def test_credentials_are_absent():\n"
        "    assert 'TAVILY_API_KEY' not in os.environ\n"
    )

    green, out = run_pytest(tmp_path)

    assert green, out

def test_pytest_timeout_fails_with_clear_message(tmp_path):
    (tmp_path / "test_slow.py").write_text(
        "import time\n"
        "def test_slow():\n"
        "    time.sleep(10)\n"
    )

    green, out = run_pytest(tmp_path, timeout=0.1)

    assert not green
    assert "pytest timed out after 0.1 seconds" in out

def test_static_assets_are_scoped_to_frontend():
    client = TestClient(app)

    assert client.get("/").status_code == 200
    for path in ("/kernel.py", "/server.py", "/.env"):
        assert client.get(path).status_code == 404
