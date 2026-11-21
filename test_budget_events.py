"""Budget events carry both the run's budget and the account total."""
import kernel
from runs import Run


def _budget_events(run):
    return [event["data"] for event in run.events if event["type"] == "budget"]


def test_budget_events_report_run_and_account_numbers(tmp_path):
    run = Run()
    store = kernel.UserUsageStore(tmp_path / "usage.json")
    meter = kernel.Meter(
        100, run=run, user_id="alice", user_cap=12000, usage_store=store,
        repo_root=tmp_path,
    )
    meter.log("draft", "cheap", 30, 20)
    event = _budget_events(run)[-1]
    assert (event["run_used"], event["run_cap"]) == (50, 100)
    assert (event["used"], event["cap"]) == (50, 12000)


def test_budget_events_without_a_user_use_the_run_budget_for_both(tmp_path):
    run = Run()
    meter = kernel.Meter(100, run=run, repo_root=tmp_path)
    meter.log("draft", "cheap", 30, 20)
    event = _budget_events(run)[-1]
    assert (event["used"], event["cap"]) == (50, 100)
    assert (event["run_used"], event["run_cap"]) == (50, 100)
