from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import fixer
import modes
import router
from kernel import GatewayError, Meter, UserUsageStore
from server import FixIn, app


def _toy_snapshot():
    root = Path(fixer.__file__).resolve().parent / "bench" / "tasks" / "toy_cart"
    return {
        path.name: path.read_bytes()
        for path in (root / "cart.py", root / "test_cart.py", root / "offline.patch")
    }


def test_fix_input_defaults_allow_cap_only():
    request = FixIn(cap=100)

    assert request.repo_path is None
    assert request.task is None
    assert request.test_cmd == ["python", "-m", "pytest"]


@pytest.mark.parametrize("run_fix", [fixer.run_fix, modes.run_fix])
def test_legacy_fix_without_repo_uses_offline_toy_without_writing(
    run_fix, monkeypatch
):
    monkeypatch.delenv("LEDGER_OFFLINE_STUB", raising=False)
    before = _toy_snapshot()

    result = run_fix()

    assert result["status"] == "green"
    assert result["engine"] == "offline stub"
    assert _toy_snapshot() == before


def test_legacy_fix_endpoint_accepts_cap_only_without_writing(monkeypatch):
    monkeypatch.delenv("LEDGER_OFFLINE_STUB", raising=False)
    before = _toy_snapshot()

    response = TestClient(app).post("/api/fix", json={"cap": 6000})

    assert response.status_code == 200
    assert response.json()["status"] == "green"
    assert response.json()["engine"] == "offline stub"
    assert _toy_snapshot() == before


def test_budget_store_prefers_ledger_budget_file(tmp_path, monkeypatch):
    budget_path = tmp_path / "budget.json"
    legacy_path = tmp_path / "legacy-usage.json"
    monkeypatch.setenv("LEDGER_BUDGET_FILE", str(budget_path))
    monkeypatch.setenv("LEDGER_USAGE_FILE", str(legacy_path))

    store = UserUsageStore()
    store.record_usage("alice", 7)

    assert store.get_used("alice") == 7
    assert budget_path.exists()
    assert not legacy_path.exists()


def test_plain_meter_does_not_consult_persisted_user_budget(
    tmp_path, monkeypatch
):
    store = UserUsageStore(tmp_path / "budget.json")
    store.record_usage("default", 12000)
    meter = Meter(usage_store=store)
    monkeypatch.setenv("BIFROST_URL", "http://gateway")
    monkeypatch.setenv("LEDGER_CHAIN_CHEAP", "openai/primary")

    def failed_request(url, **kwargs):
        return httpx.Response(
            502,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(router.httpx, "post", failed_request)
    monkeypatch.setattr(router.time, "sleep", lambda _: None)

    with pytest.raises(GatewayError):
        router.complete(meter.run, meter, "test", "cheap", "system", "user")

    assert meter.user_id is None
    assert store.get_used("default") == 12000
