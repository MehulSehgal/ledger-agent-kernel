from pathlib import Path


STATIC = Path(__file__).with_name("static")


def test_brief_result_uses_master_detail_evidence_layout():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "brief-master-detail",
        "evidence-panel",
        "evidence-excerpt",
        "evidence-full-source",
        "brief-rejected",
    ):
        assert f'id="{element_id}"' in html
    assert "brief-claim-card" in script
    assert "appendHighlightedQuote" in script
    assert "evidence-check-icon" in script
    assert "grid-template-columns: minmax(0, 1fr) minmax(280px" in css
    assert "-webkit-line-clamp: 3" in css


def test_brief_evidence_source_table_and_mobile_keyboard_contract():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "View full source text" in html
    assert '<details class="brief-source-details"' in html
    assert "Sources (" in script
    assert 'createElement("table", "sources-table")' in script
    assert 'row.title = label' in script
    assert "ArrowDown" in script and "ArrowUp" in script
    assert 'event.key === "Escape"' in script
    assert '@media (max-width: 899px)' in css
    assert ".evidence-panel.is-open" in css
    assert 'byId("brief-sources").addEventListener("click"' in script
    assert "isReservedExampleHost" in script
    assert '"Offline replay source (no live article URL)"' in script
    assert '"source-preview"' in script
