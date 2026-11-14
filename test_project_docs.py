import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_requirements_pin_every_dependency():
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert requirements
    assert all("==" in requirement for requirement in requirements)
    assert all(not any(operator in requirement for operator in ("<", ">", "~=")) for requirement in requirements)


def test_ci_runs_pytest_on_push_with_python_312():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert re.search(r"(?m)^on:\s*\n\s+push:\s*$", workflow)
    assert re.search(r"(?m)^\s+python-version:\s*[\"']3\.12[\"']\s*$", workflow)
    assert "python -m pip install -r requirements.txt" in workflow
    assert re.search(r"(?m)^\s+- run:\s+pytest -q\s*$", workflow)


def test_readme_covers_requested_sections_and_real_call_sites():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for heading in (
        "What it is",
        "Status",
        "Architecture",
        "Windows quickstart",
        "Environment variables",
        "Bifrost and Tavily call sites",
        "Reproducing the benchmark",
        "AI-tool disclosure",
        "Limitations",
    ):
        assert heading.casefold() in readme.casefold()

    assert "```mermaid" in readme
    assert "router.complete" in readme
    assert "tavily_news" in readme
    assert "tavily_extract" in readme
    assert "Claude" in readme
    assert "Copilot" in readme
    assert all(status in readme.casefold() for status in ("done", "verified live", "not done"))


def test_readme_numbers_are_sourced_only_from_benchmark_summary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_numbers = set(re.findall(r"\d+(?:\.\d+)?", readme))
    number_words = re.findall(
        r"(?<![A-Za-z-])(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|first|second|third|fourth|fifth|"
        r"sixth|seventh|eighth|ninth|tenth|once|twice)(?![A-Za-z-])",
        readme,
        flags=re.IGNORECASE,
    )
    summary_path = ROOT / "bench" / "results" / "summary.json"

    assert not number_words
    if not summary_path.exists():
        assert not readme_numbers
        return

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_numbers = set()

    def collect_numbers(value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            summary_numbers.add(str(value))
        elif isinstance(value, dict):
            for nested in value.values():
                collect_numbers(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_numbers(nested)

    collect_numbers(summary)
    assert readme_numbers <= summary_numbers


def test_demo_is_a_three_minute_script():
    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")

    assert "three-minute" in demo.casefold()
    assert "00:00" in demo
    assert "03:00" in demo
