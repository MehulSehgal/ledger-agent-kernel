import pytest


@pytest.fixture(autouse=True)
def isolate_ledger_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setenv("LEDGER_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.delenv("LEDGER_DEMO", raising=False)
    # Keep tests offline and free: real credentials in the developer's shell must
    # never turn offline tests into live Tavily/Bifrost calls that spend credits.
    for name in ("TAVILY_API_KEY", "LEDGER_TAVILY_CREDIT_CAP", "BIFROST_URL", "BIFROST_VK",
                 "LEDGER_GITHUB_OWNERS", "LEDGER_CLONE_ROOT"):
        monkeypatch.delenv(name, raising=False)
