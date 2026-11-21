from pathlib import Path

import bench.bench as benchmark


ROOT = Path(__file__).parent
STATIC = ROOT / "static"


def test_benchmark_records_and_summary_keep_task_and_model_provenance():
    record = benchmark.build_record(
        arm="ledger",
        task={"id": "toy_cart", "source": "seeded"},
        run_number=1,
        result={
            "status": "green",
            "engine": "offline stub",
            "receipt": {"calls": [{"model": "offline", "in": 0, "out": 0}]},
        },
        events=[],
        seconds=1,
    )

    assert record["task_source"] == "seeded"
    assert record["engine"] == "offline stub"

    summary = benchmark.summarize_records(
        [
            record,
            {
                **record,
                "arm": "baseline",
                "run": 2,
            },
        ],
        bootstrap_samples=20,
    )
    assert summary["metadata"] == {
        "task_count": 1,
        "run_count": 2,
        "provenance_complete": True,
        "models": ["offline"],
        "task_sources": ["seeded"],
        "engines": ["offline stub"],
    }


def test_legacy_benchmark_records_are_marked_as_missing_provenance():
    summary = benchmark.summarize_records(
        [{"arm": "baseline", "task_id": "toy_cart", "pass": True}],
        bootstrap_samples=20,
    )

    assert summary["metadata"]["provenance_complete"] is False


def test_safety_screen_supports_scenario_cards_run_progress_and_summary():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert 'id="redteam-tab"' in html
    assert 'id="run-redteam"' in html
    assert "scenario-status-ring" in script
    assert "scenario-check-chip" in script
    assert "scenario-explanation" in script
    assert "redteam-progress" in script
    assert "Run all" in script
    assert "scenario-list" in css
    assert "grid-template-columns: repeat(2" in css


def test_evaluation_hides_unmeasured_comparisons_and_exports_real_results():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert 'id="benchmark-tab"' in html
    assert "Toy task, offline stub: not a measured result" in script
    assert "isUnmeasuredBenchmark" in script
    assert "renderBenchmarkTokenTable" in script
    assert "exportBenchmarkCsv" in script
    assert "metadata.task_count" in script
    assert "metadata.run_count" in script
    assert "metadata.provenance_complete !== true" in script
    assert "benchmark-provenance" in css
