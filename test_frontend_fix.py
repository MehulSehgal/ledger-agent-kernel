from pathlib import Path


STATIC = Path(__file__).with_name("static")


APPROVAL_IDS = (
    "approval-overlay",
    "approval-drawer",
    "approval-kind",
    "approval-countdown",
    "approval-title",
    "approval-description",
    "approval-hash",
    "approval-detail",
    "deny-approval",
    "approve-run",
    "approve-once",
    "approval-feedback",
)


def test_fix_result_has_stage_metrics_diff_viewer_and_test_chips():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "run-stepper",
        "fix-diff-viewer",
        "fix-file-list",
        "fix-view-unified",
        "fix-view-side-by-side",
        "fix-diff-side-by-side",
        "fix-test-results",
    ):
        assert f'id="{element_id}"' in html
    for stage in ("Tests", "Locate", "Patch", "Re-test", "Approve"):
        assert stage in html or stage in script
    assert "stepper-duration" in script
    assert "stepper-tokens" in script
    assert "stepper-tier" in script
    assert "renderFixDiff" in script
    assert "test-chip" in script
    assert "diff-side-by-side" in css
    assert "diff-line-add" in css and "diff-line-remove" in css


def test_approval_modal_preserves_ids_and_adds_risk_countdown_and_shortcuts():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for element_id in APPROVAL_IDS:
        assert f'id="{element_id}"' in html
    for element_id in ("approval-risk", "approval-countdown-ring", "approval-shortcuts"):
        assert f'id="{element_id}"' in html
    assert "shortcut-hint" in html
    assert "data-approval-key" in script
    assert "approval-risk" in script
    assert "stroke-dashoffset" in script
    assert "justify-content: center" in css
    assert "approval-countdown-ring" in css
