import pytest


@pytest.fixture(autouse=True)
def isolate_ledger_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setenv("LEDGER_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.delenv("LEDGER_DEMO", raising=False)
