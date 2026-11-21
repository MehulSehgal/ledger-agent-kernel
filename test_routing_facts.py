"""Facts the page uses to show local-only routing: tiers, flags and status."""
import kernel
from runs import Run


def _model_calls(run):
    return [event["data"] for event in run.events if event["type"] == "model_call"]


def test_confidential_model_calls_are_reported_as_local_and_free(tmp_path):
    run = Run()
    meter = kernel.Meter(1000, run=run, repo_root=tmp_path, confidential_requested=True)
    meter.log("draft", "strong", 10, 5, model="ollama/llama3")
    call = _model_calls(run)[0]
    assert call["tier"] == "local"
    assert call["usd"] == 0.0


def test_standard_model_calls_keep_their_tier(tmp_path):
    run = Run()
    meter = kernel.Meter(1000, run=run, repo_root=tmp_path)
    meter.log("draft", "strong", 10, 5, model="openai/gpt-4o-mini")
    assert _model_calls(run)[0]["tier"] == "strong"


def test_offline_stub_calls_stay_local(tmp_path):
    run = Run()
    meter = kernel.Meter(1000, run=run, repo_root=tmp_path)
    meter.log("draft (offline stub)", "cheap", 10, 5)
    assert _model_calls(run)[0]["tier"] == "local"
