"""The page ships a default token budget of 100 everywhere it shows one."""
import re
from pathlib import Path

STATIC = Path(__file__).with_name("static")


def test_budget_input_defaults_to_100():
    html = (STATIC / "index.html").read_text()
    start = html.index('id="token-budget"')
    tag = html[start: html.index(">", start)]
    assert 'value="100"' in tag
    assert '<span id="budget-cap">100</span>' in html
    assert 'aria-valuemax="100"' in html


def test_script_uses_one_default_and_no_old_literals():
    script = (STATIC / "app.js").read_text()
    assert "const DEFAULT_TOKEN_BUDGET = 100;" in script
    old_default = re.compile(r"(?<![0-9])(12000|6000)(?![0-9])")
    assert not old_default.search(script)
    assert not old_default.search((STATIC / "index.html").read_text())
