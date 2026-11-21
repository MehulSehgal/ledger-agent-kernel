from datetime import date, timedelta

import modes
from runs import Run


def _source(url="https://a.test", text="Acme Robotics raised funding.", topic="funding"):
    return {
        "url": url,
        "title": "Funding update",
        "date": (date.today() - timedelta(days=1)).isoformat(),
        "text": text,
        "topic": topic,
    }


def _brief_setup(monkeypatch, sources, live_llm=False):
    monkeypatch.setattr(modes, "live_web", lambda: True)
    monkeypatch.setattr(modes, "live_llm", lambda: live_llm)
    monkeypatch.setattr(modes, "tavily_news", lambda *args, **kwargs: sources)
    monkeypatch.setattr(
        modes,
        "tavily_extract",
        lambda urls, query, chunks=3: (
            {source["url"]: source["text"] for source in sources},
            [],
        ),
    )


def test_live_claim_cleaning_and_relevance(monkeypatch):
    text = (
        "# Funding update\n"
        "Image 123\n"
        "Acme Robotics raised $60 million for expansion. "
        "https://example.test\n"
        "Miami Dolphins signed a long contract yesterday. "
        "### Navigation\n"
        ">>> ***"
    )
    _brief_setup(monkeypatch, [_source(text=text)])
    monkeypatch.setattr(
        modes,
        "extract_offline",
        lambda srcs: [
            {"source_id": 0, "claim": "Acme Robotics raised $60 million for expansion.", "quote": "Acme Robotics raised $60 million for expansion."},
            {"source_id": 0, "claim": "Miami Dolphins signed a long contract yesterday.", "quote": "Miami Dolphins signed a long contract yesterday."},
        ],
    )

    result = modes.run_brief("Acme Robotics", "Planning")

    assert len(result["bullets"]) == 1
    assert "Acme Robotics" in result["bullets"][0]["text"]
    rejected = [item["reason"] for item in result["audit"]["rejected_claims"]]
    assert "not about Acme Robotics" in rejected
    assert "#" not in result["sources"][0]["text"]


def test_live_claim_limits_skip_symbol_sentences(monkeypatch):
    text = (
        "Acme Robotics announced a product expansion across three new markets. "
        ">>> >>> >>> >>> >>> >>> >>> >>> >>> >>> >>>"
    )
    _brief_setup(monkeypatch, [_source(text=text)])
    claims = []
    monkeypatch.setattr(modes, "extract_offline", lambda srcs: claims)

    result = modes.run_brief("Acme Robotics", "Planning")

    assert result["modes"] == {"search": "live", "model": "stub"}
    assert result["audit"]["accepted"] == 0


def test_offline_stub_calls_reserve_and_can_return_partial(monkeypatch, tmp_path):
    text = "Acme raised $60 million in funding to expand production."
    monkeypatch.setattr(modes, "live_web", lambda: False)
    monkeypatch.setattr(modes, "live_llm", lambda: False)
    monkeypatch.setattr(modes, "demo_sources", lambda *args: [_source(text=text)])
    run = Run()

    result = modes.run_brief(
        "Acme",
        "Planning",
        cap=1,
        run=run,
        repo_root=tmp_path,
    )

    assert result["status"] == "partial"
    assert result["modes"]["model"] == "stub"
    assert any(
        event["type"] == "blocked" and event["data"].get("state") == "exhausted"
        for event in run.events
    )
    assert list(
        event["data"]["state"]
        for event in run.events
        if event["type"] == "budget"
    )[-1] == "exhausted"


def test_offline_questions_are_unique_and_limited(monkeypatch):
    monkeypatch.setattr(modes, "live_web", lambda: False)
    monkeypatch.setattr(modes, "live_llm", lambda: False)
    text = "Acme closed funding to expand operations this year."
    source = _source(text=text)
    monkeypatch.setattr(modes, "demo_sources", lambda *args: [source])
    monkeypatch.setattr(
        modes,
        "extract_offline",
        lambda srcs: [
            {"source_id": 0, "claim": text, "quote": text}
        ],
    )

    result = modes.run_brief("Acme", "Planning")

    assert len(result["open_questions"]) <= 3
    normalized = [item.split("]: ", 1)[-1] for item in result["open_questions"]]
    assert len(normalized) == len(set(normalized))
    assert all("claim-1" in item for item in result["open_questions"])
