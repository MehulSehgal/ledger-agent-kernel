from pathlib import Path


STATIC = Path(__file__).with_name("static")


def test_shell_routes_home_workspace_safety_and_evaluation():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    for route in ("#/", "#/workspace", "#/safety", "#/evaluation"):
        assert route in html
    assert 'id="home-screen"' in html
    assert 'id="workspace-screen"' in html
    assert 'id="redteam-screen"' in html
    assert 'id="benchmark-screen"' in html
    assert "Agents you can audit." in html
    assert "Evidence-first" in html
    assert "Policy-gated" in html
    assert "Local-first" in html
    assert "How it works" in html
    assert "Try a scenario" in html
    assert "Cheaper agents." not in html


def test_theme_and_frontend_contract_are_retained():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="theme-toggle"' in html
    assert 'id="redteam-tab"' in html
    assert 'id="benchmark-tab"' in html
    assert 'id="run-redteam"' in html
    assert ':root' in css and '[data-theme="light"]' in css
    for token in ("#0b1117", "#111b23", "#17232d", "#243541", "#e7eef3", "#93a7b4", "#6ea8fe", "#4cc38a", "#e5b95c", "#f0817a"):
        assert token in css
    assert "prefers-reduced-motion" in css
    assert "@media print" in css
    assert "localStorage" in script
    assert "prefers-color-scheme" in script
    assert "hashchange" in script
    for required in (
        '"/api/redteam"',
        '"/api/bench/summary"',
        "createElementNS",
        "isReservedExampleHost",
        "source-preview",
        '"Offline replay source (no live article URL)"',
        'byId("brief-sources").addEventListener("click"',
    ):
        assert required in script


def test_navigation_and_mode_badge_contract():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="mode-status"' in html
    assert '"Live search"' in script
    assert '"Stub model"' in script
    assert "`${searchMode} · ${modelMode}`" in script
    assert 'data-preset="board"' in html
    assert 'data-preset="market"' in html
    assert 'data-preset="confidential"' in html
