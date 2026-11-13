import json
import threading
import time

from fastapi.testclient import TestClient

from runs import Run, RunRegistry
from server import app, run_registry
from modes import run_fix


def test_run_emits_sequenced_contract_events():
    run = Run(id="run-test")

    first = run.emit("step", {
        "id": "start",
        "title": "Starting",
        "status": "running",
        "detail": "",
    })
    second = run.emit("claim", {
        "id": "claim-1",
        "text": "Claim",
        "status": "verified",
        "reason": None,
        "source_n": 1,
        "quote": "Quote",
        "url": "https://example.test",
        "date": "2026-11-13",
    })

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert first["type"] == "step"
    assert first["ts"]
    assert second["data"]["status"] == "verified"


def test_run_approval_wait_and_resolution():
    run = Run()
    outcome = []
    waiter = threading.Thread(
        target=lambda: outcome.append(
            run.wait_for_approval("approval-hash", 2, kind="SHELL", summary="Run tests")
        )
    )
    waiter.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if any(event["type"] == "approval_request" for event in run.events):
            break
        time.sleep(0.01)

    assert run.resolve_approval("approval-hash", "approved", once=True)
    waiter.join(timeout=2)

    assert outcome == ["approved"]
    result = next(event for event in run.events if event["type"] == "approval_result")
    assert result["data"] == {
        "hash": "approval-hash",
        "decision": "approved",
        "once": True,
    }


def test_run_cancel_and_registry_retains_only_fifty():
    run = Run()
    assert run.cancel()
    assert run.status == "cancelled"
    assert run.cancelled.is_set()

    registry = RunRegistry()
    created = [Run(id=f"run-{index}") for index in range(51)]
    for item in created:
        registry.add(item)

    assert len(registry) == 50
    assert registry.get("run-0") is None
    assert registry.get("run-50") is created[-1]


def test_run_fix_accepts_run_and_emits_final_result():
    run = Run()

    result = run_fix(run=run)

    assert result["status"] == "green"
    assert any(event["type"] == "step" for event in run.events)
    assert run.events[-1]["type"] == "result"


def test_run_stream_sends_heartbeat_while_pending():
    run = Run()

    assert next(run.stream(heartbeat=0.01)) == ": heartbeat\n\n"


def test_streaming_offline_brief_and_legacy_brief_shape(monkeypatch, tmp_path):
    monkeypatch.delenv("BIFROST_URL", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("LEDGER_USAGE_FILE", str(tmp_path / "usage.json"))
    client = TestClient(app)

    started = client.post(
        "/api/runs",
        json={"mode": "brief", "params": {"company": "Acme", "meeting": "Planning"}},
    )

    assert started.status_code == 202
    run_id = started.json()["run_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get(f"/api/runs/{run_id}").json()
        if status["status"] != "running":
            break
        time.sleep(0.02)
    assert status["status"] == "completed"

    stream = client.get(
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": "0"},
    )
    assert stream.status_code == 200
    events = [
        json.loads(line.removeprefix("data: ").strip())
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]
    types = [event["type"] for event in events]
    assert types.index("step") < types.index("model_call")
    assert types.index("model_call") < types.index("claim")
    assert types.index("claim") < types.index("result")
    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)
    model_call = next(event["data"] for event in events if event["type"] == "model_call")
    budget = next(event["data"] for event in events if event["type"] == "budget")
    assert model_call["tier"] == "local"
    assert model_call["model"] == "offline"
    assert {"used", "cap", "pct", "state", "user"} <= set(budget)

    legacy = client.post(
        "/api/brief",
        json={"company": "Acme", "meeting": "Planning"},
    )
    assert legacy.status_code == 200
    assert {"mode", "sources", "bullets", "open_questions", "audit", "receipt"} <= set(legacy.json())
    legacy_fix = client.post("/api/fix", json={"cap": 6000})
    assert legacy_fix.status_code == 200
    assert {"mode", "steps", "receipt", "status"} <= set(legacy_fix.json())


def test_events_replay_after_last_event_id():
    run = Run()
    run.emit("step", {"id": "one", "title": "One", "status": "ok", "detail": ""})
    run.emit("step", {"id": "two", "title": "Two", "status": "ok", "detail": ""})
    run.emit("result", {"ok": True})
    run_registry.add(run)

    response = TestClient(app).get(
        f"/api/runs/{run.id}/events",
        headers={"Last-Event-ID": "1"},
    )

    replayed = [
        json.loads(line.removeprefix("data: ").strip())
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["seq"] for event in replayed] == [2, 3]


def test_run_approval_and_cancel_routes():
    run = Run()
    run_registry.add(run)
    waiter = threading.Thread(
        target=lambda: run.wait_for_approval("route-hash", 2, kind="GIT")
    )
    waiter.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if any(event["type"] == "approval_request" for event in run.events):
            break
        time.sleep(0.01)

    client = TestClient(app)
    approved = client.post(
        f"/api/runs/{run.id}/approve",
        json={"hash": "route-hash", "decision": "approved", "once": False},
    )
    assert approved.status_code == 200
    waiter.join(timeout=2)

    cancellable = Run()
    run_registry.add(cancellable)
    cancelled = client.post(f"/api/runs/{cancellable.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
