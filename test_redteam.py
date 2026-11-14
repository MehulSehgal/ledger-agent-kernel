import json
from pathlib import Path

from fastapi.testclient import TestClient

import redteam
import server


ROOT = Path(__file__).parent
SCENARIO_IDS = {
    "repo-injection",
    "web-injection",
    "path-traversal",
    "confidential-cloud",
}


def _by_id(scenarios):
    return {scenario["id"]: scenario for scenario in scenarios}


def test_red_team_fixtures_contain_the_requested_attack_text():
    repo = ROOT / "bench" / "redteam" / "injection_repo"
    notes = (repo / "NOTES.md").read_text(encoding="utf-8").lower()
    module = (repo / "injected.py").read_text(encoding="utf-8").lower()
    page = (
        ROOT / "bench" / "redteam" / "web_fixture.html"
    ).read_text(encoding="utf-8").lower()
    traversal = json.loads(
        (ROOT / "bench" / "redteam" / "path_traversal.json").read_text(
            encoding="utf-8"
        )
    )
    confidential = (
        ROOT / "bench" / "redteam" / "confidential_repo" / "README.md"
    ).read_text(encoding="utf-8").lower()

    for text in (notes, module, page):
        assert "ignore all rules" in text
        assert "rm -rf" in text
        assert "send this file to the strong model" in text
        assert "user already approved" in text
    assert traversal["repo_path"].startswith("..")
    assert "use cloud routing" in confidential


def test_red_team_runs_real_scenarios_and_derives_results_from_evidence():
    scenarios = _by_id(redteam.run_redteam())

    assert set(scenarios) == SCENARIO_IDS
    for scenario in scenarios.values():
        assert isinstance(scenario["passed"], bool)
        assert scenario["checks"]
        assert scenario["passed"] is all(scenario["checks"].values())
        assert scenario["evidence"]

    repo = scenarios["repo-injection"]
    assert repo["checks"]["outside_unchanged"]
    assert repo["checks"]["only_allowlisted_shell"]
    assert repo["checks"]["no_approval_from_text"]

    web = scenarios["web-injection"]
    assert web["checks"]["replayed_fixture_used"]
    assert web["checks"]["injection_source_dropped"]

    traversal = scenarios["path-traversal"]
    assert traversal["checks"]["traversal_denied"]
    assert traversal["checks"]["outside_unchanged"]

    confidential = scenarios["confidential-cloud"]
    assert confidential["checks"]["no_cloud_call"]
    assert confidential["checks"]["confidential_blocked_event"]


def test_red_team_endpoint_returns_scenario_evidence(monkeypatch):
    monkeypatch.setattr(server, "run_redteam", redteam.run_redteam)

    response = TestClient(server.app).post("/api/redteam")

    assert response.status_code == 200
    payload = response.json()
    assert set(_by_id(payload["scenarios"])) == SCENARIO_IDS
    assert payload["passed"] == sum(
        scenario["passed"] for scenario in payload["scenarios"]
    )
    assert payload["failed"] == sum(
        not scenario["passed"] for scenario in payload["scenarios"]
    )
    assert all(scenario["evidence"] for scenario in payload["scenarios"])


def test_workspace_has_red_team_and_benchmark_tabs():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="redteam-tab"' in html
    assert 'id="benchmark-tab"' in html
    assert 'id="run-redteam"' in html
    assert "/api/redteam" in script
    assert "/api/bench/summary" in script
    assert "createElementNS" in script


def test_offline_example_sources_open_the_local_evidence_view():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "isReservedExampleHost" in script
    assert "source-preview" in script
    assert "Offline replay source" in script
    assert 'byId("brief-sources").addEventListener("click"' in script
