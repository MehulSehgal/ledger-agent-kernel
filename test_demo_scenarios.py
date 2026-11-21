"""The clickable demo scenarios must start real, finishable runs."""
import re
from pathlib import Path

from modes import run_brief

STATIC = Path(__file__).parent / "static"


def _presets():
    source = (STATIC / "app.js").read_text()
    block = source[source.index("const demoPresets"):source.index("function presetHint")]
    names = re.findall(r"^  (\w+): \{", block, flags=re.M)
    companies = re.findall(r'company: "([^"]+)"', block)
    budgets = [int(n) for n in re.findall(r"budget: (\d+)", block)]
    confidential = [v == "true" for v in re.findall(r"confidential: (true|false)", block)]
    return list(zip(names, companies, budgets, confidential))


def test_three_distinct_scenarios_are_defined():
    presets = _presets()
    assert [p[0] for p in presets] == ["board", "market", "confidential"]
    assert len({p[1] for p in presets}) == 3
    assert [p[3] for p in presets] == [False, False, True]


def test_every_scenario_completes_within_its_own_budget():
    for name, company, budget, confidential in _presets():
        result = run_brief(company, "Thu 3pm", cap=budget, confidential=confidential)
        assert result["receipt"]["tokens"] <= budget, name
        assert result["audit"]["accepted"] > 0, name
        assert bool(result.get("confidential")) is confidential, name


def test_plan_card_markup_and_hooks_exist():
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "app.js").read_text()
    for element_id in ("demo-plan", "demo-plan-title", "demo-plan-steps", "demo-plan-outcome"):
        assert f'id="{element_id}"' in html
    assert 'requestSubmit()' in js and "finishPlan(result)" in js and "failPlan(data.message)" in js
