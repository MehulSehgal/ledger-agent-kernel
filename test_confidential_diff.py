"""Confidential Fix runs show their diff unless the operator or repo says not to."""
import json

import modes
from test_confidential import _ApprovingRun, _confidential_repo


def _failing_repo(path):
    (path / "calculator.py").write_text("def calculate():\n    return 1\n")
    (path / "test_calculator.py").write_text(
        "from calculator import calculate\n"
        "def test_calculate():\n"
        "    assert calculate() == 2\n"
    )


def _fix(tmp_path, monkeypatch, confidential):
    run = _ApprovingRun()
    monkeypatch.setattr(modes, "live_llm", lambda: True)
    monkeypatch.setattr(
        modes, "chat",
        lambda *args: "<<<SEARCH\n    return 1\n===\n    return 2\n>>>REPLACE",
    )
    result = modes.run_fix(run=run, repo_root=tmp_path, confidential=confidential)
    logged = json.dumps({
        "result": result, "events": run.events, "approvals": run.approval_payloads,
    })
    return result, run, logged


def test_confidential_request_returns_the_diff_by_default(tmp_path, monkeypatch):
    _failing_repo(tmp_path)
    result, run, _ = _fix(tmp_path, monkeypatch, confidential=True)
    assert result["status"] == "green"
    assert result["confidential"] is True
    assert "return 2" in result["diff"]
    assert result["symbols"] == ["calculate"] and result["diff_hash"]
    assert any("return 2" in json.dumps(payload) for payload in run.approval_payloads)


def test_opt_out_keeps_confidential_results_hash_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_CONFIDENTIAL_DIFF", "off")
    _failing_repo(tmp_path)
    result, run, logged = _fix(tmp_path, monkeypatch, confidential=True)
    assert result["status"] == "green"
    assert "diff" not in result
    assert result["symbols"] == ["calculate"] and result["diff_hash"]
    assert "return 1" not in logged and "return 2" not in logged


def test_repository_policy_file_always_stays_hash_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_CONFIDENTIAL_DIFF", "on")
    _confidential_repo(tmp_path)
    _failing_repo(tmp_path)
    result, run, logged = _fix(tmp_path, monkeypatch, confidential=False)
    assert "diff" not in result
    assert "return 1" not in logged and "return 2" not in logged


def test_standard_runs_still_return_the_diff(tmp_path, monkeypatch):
    _failing_repo(tmp_path)
    result, _, _ = _fix(tmp_path, monkeypatch, confidential=False)
    assert result["confidential"] is False
    assert "return 2" in result["diff"]
    assert "symbols" not in result
