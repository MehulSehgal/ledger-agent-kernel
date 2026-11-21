from pathlib import Path


STATIC = Path(__file__).with_name("static")


def test_workspace_has_three_columns_stepper_and_result_tabs():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "control-panel",
        "collapse-controls",
        "results-panel",
        "meter-panel",
        "run-stepper",
        "result-tab",
        "activity-tab",
        "result-view",
        "activity-view",
        "activity-details",
        "timeline",
    ):
        assert f'id="{element_id}"' in html
    for label in ("Search", "Extract", "Verify", "Synthesize", "Tests", "Locate", "Patch", "Re-test", "Approve"):
        assert label in html or label in script
    assert "updateStepperStep" in script
    assert "role=\"tablist\"" in html
    assert "grid-template-columns: minmax(250px, 280px)" in css
    assert "addTimelineRow(" in script


def test_workspace_summary_empty_state_loaders_and_over_budget_state():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "stat-verified",
        "stat-rejected",
        "stat-sources",
        "stat-tokens",
        "claim-quality-bar",
        "workspace-empty",
        "workspace-skeleton",
        "toast",
        "over-budget",
    ):
        assert f'id="{element_id}"' in html
    assert "<svg" in html
    assert "Choose a scenario or enter a company" in html
    assert 'aria-live="polite"' in html
    assert "Over budget" in html
    assert "Math.min(100" in script
    assert "is-over-budget" in script
    assert "const overBudget = totalUsed > budgetCap" in script
    assert 'aria-valuetext' in script
    assert "is-over-budget .meter-fill" in css
    assert "max-width: 1100px" in css
    assert "is-controls-collapsed" in css
    assert "toast" in script
