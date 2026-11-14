import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bench.bench as benchmark
import bench.brief_eval as brief_eval
from kernel import Meter
from runs import Run
import server


ROOT = Path(__file__).parent


def test_toy_task_manifest_describes_its_failing_test():
    tasks = benchmark.load_tasks(max_tasks=10)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == "toy_cart"
    assert task["source"] == "seeded"
    assert task["failing_test"] == "test_cart.py::test_total_multiplies_by_quantity"
    assert task["repo_dir"].is_dir()
    assert task["test_cmd"] == ["python", "-m", "pytest"]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", task["failing_test"]],
        cwd=task["repo_dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_benchmark_summary_computes_wilson_and_bootstrap_statistics():
    records = [
        {
            "arm": "ledger",
            "pass": True,
            "tokens_in": 100,
            "tokens_out": 20,
            "tokens_cached": 5,
            "usd": 0.02,
        },
        {
            "arm": "ledger",
            "pass": False,
            "tokens_in": 200,
            "tokens_out": 40,
            "tokens_cached": 0,
            "usd": 0.04,
        },
    ]

    summary = benchmark.summarize_records(records, bootstrap_samples=200)

    arm = summary["arms"]["ledger"]
    assert arm["n"] == 2
    assert arm["passes"] == 1
    assert arm["pass_rate"] == 0.5
    assert 0 < arm["pass_rate_ci95"][0] < 0.5 < arm["pass_rate_ci95"][1] < 1
    assert arm["mean_tokens_in"]["mean"] == 150
    assert arm["mean_tokens_in"]["ci95"] == benchmark.summarize_records(
        records, bootstrap_samples=200
    )["arms"]["ledger"]["mean_tokens_in"]["ci95"]
    assert arm["mean_usd"]["mean"] == 0.03
    assert arm["cost_per_verified_outcome"] == 0.06


def test_unreported_cached_tokens_remain_explicitly_unknown():
    run = Run()
    meter = Meter(run=run)
    meter.log("sample", "cheap", 10, 4, model="offline")
    event = next(event for event in run.events if event["type"] == "model_call")

    assert event["data"]["tokens_cached"] is None
    assert meter.receipt()["calls"][0]["tokens_cached"] is None


def test_summary_does_not_estimate_cost_when_any_trial_cost_is_unknown():
    summary = benchmark.summarize_records(
        [
            {"arm": "ledger", "pass": True, "usd": 0.01},
            {"arm": "ledger", "pass": False, "usd": None},
        ],
        bootstrap_samples=20,
    )

    assert summary["arms"]["ledger"]["mean_usd"] == {"mean": None, "ci95": None}
    assert summary["arms"]["ledger"]["cost_per_verified_outcome"] is None


def test_trial_record_uses_run_receipt_and_event_metrics():
    record = benchmark.build_record(
        arm="ledger",
        task={"id": "toy_cart"},
        run_number=2,
        result={
            "status": "green",
            "receipt": {
                "calls": [{"model": "offline", "in": 12, "out": 5}],
                "tokens": 17,
                "usd": None,
            },
            "steps": [
                {"step": "Apply attempt 1 in sandbox"},
                {"step": "Run full regression suite"},
            ],
        },
        events=[
            {
                "type": "model_call",
                "data": {"tokens_in": 12, "tokens_out": 5, "tokens_cached": 3},
            },
            {"type": "failover", "data": {}},
        ],
        seconds=1.25,
    )

    assert record["pass"] is True
    assert record["tokens_in"] == 12
    assert record["tokens_out"] == 5
    assert record["tokens_cached"] == 3
    assert record["usd"] is None
    assert record["attempts"] == 1
    assert record["failovers"] == 1
    assert record["models_used"] == ["offline"]
    assert record["seconds"] == 1.25
    assert record["date"]


@pytest.mark.parametrize(("arm", "expected_mode"), (("ledger", "fix"), ("baseline", "baseline")))
def test_toy_benchmark_trial_fixes_a_disposable_copy_through_approval_api(
    monkeypatch, arm, expected_mode
):
    task = benchmark.load_tasks(max_tasks=1)[0]
    original = (task["repo_dir"] / "cart.py").read_bytes()
    monkeypatch.setenv("LEDGER_OFFLINE_STUB", "1")
    monkeypatch.delenv("BIFROST_URL", raising=False)

    result, events, _ = benchmark._run_trial(task, arm)

    assert result["status"] == "green"
    assert result["mode"] == expected_mode
    assert result["engine"] == "offline stub"
    assert any(event["type"] == "approval_result" for event in events)
    assert (task["repo_dir"] / "cart.py").read_bytes() == original


def test_benchmark_arms_select_expected_fixer_modes():
    assert benchmark._arm_parameters("baseline") == {
        "baseline": True,
        "no_triage": False,
        "no_tavily": False,
    }
    assert benchmark._arm_parameters("ledger_no_triage") == {
        "baseline": False,
        "no_triage": True,
        "no_tavily": False,
    }
    assert benchmark._arm_parameters("ledger_no_tavily") == {
        "baseline": False,
        "no_triage": False,
        "no_tavily": True,
    }


def test_benchmark_run_appends_each_trial_and_can_write_summary(tmp_path):
    task = benchmark.load_tasks(max_tasks=1)[0]
    runs_path = tmp_path / "runs.jsonl"

    records = benchmark.run_benchmark(
        arms=("ledger",),
        runs=2,
        max_tasks=1,
        execute_trial=lambda task, arm: (
            {
                "status": "green",
                "steps": [],
                "receipt": {
                    "calls": [{"model": "offline", "in": 3, "out": 1}],
                    "usd": 0.0,
                },
            },
            [
                {
                    "type": "model_call",
                    "data": {"tokens_in": 3, "tokens_out": 1, "tokens_cached": 0},
                }
            ],
            0.5,
        ),
        runs_path=runs_path,
    )

    assert len(records) == 2
    assert [record["run"] for record in benchmark._read_records(runs_path)] == [1, 2]
    summary = benchmark.write_summary(records, tmp_path / "summary.json", bootstrap_samples=20)
    assert summary["arms"]["ledger"]["n"] == 2
    assert (tmp_path / "summary.json").is_file()


def test_benchmark_summary_endpoint_returns_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "BENCH_SUMMARY_PATH", tmp_path / "summary.json")

    response = TestClient(server.app).get("/api/bench/summary")

    assert response.status_code == 404


def test_benchmark_summary_endpoint_serves_generated_summary(tmp_path, monkeypatch):
    summary_path = tmp_path / "summary.json"
    expected = {"arms": {"ledger": {"n": 1}}}
    summary_path.write_text(json.dumps(expected), encoding="utf-8")
    monkeypatch.setattr(server, "BENCH_SUMMARY_PATH", summary_path)

    response = TestClient(server.app).get("/api/bench/summary")

    assert response.status_code == 200
    assert response.json() == expected


def test_brief_evaluation_writes_claim_labels_and_reason_counts(tmp_path, monkeypatch):
    def fake_run_brief(company, meeting, run):
        run.emit("claim", {"text": company + " verified", "status": "verified"})
        run.emit(
            "claim",
            {"text": company + " rejected", "status": "rejected", "reason": "quote too short"},
        )
        return {
            "audit": {
                "accepted": 1,
                "rejected": [{"reason": "quote too short"}],
            }
        }

    monkeypatch.setattr(brief_eval, "run_brief", fake_run_brief)

    report = brief_eval.evaluate_briefs(output_dir=tmp_path)

    assert len(report["companies"]) == 8
    assert report["verified"] == 8
    assert report["rejected_by_reason"] == {"quote too short": 8}
    with (tmp_path / "brief_labels.csv").open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 16
    assert all(row["correct?"] == "" for row in rows)
