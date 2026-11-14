from datetime import date, timedelta

import pytest

import gate
from kernel import verify as kernel_verify
from modes import extract_offline


TODAY = date.today()


def source(text):
    return {"date": (TODAY - timedelta(days=1)).isoformat(), "text": text}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$60 million", [60_000_000.0]),
        ("60M", [60_000_000.0]),
        ("$60,000,000", [60_000_000.0]),
        ("1.2B", [1_200_000_000.0]),
        ("5%", [5.0]),
    ],
)
def test_numbers_in_normalizes_magnitudes_and_formatting(text, expected):
    assert gate.numbers_in(text) == expected


@pytest.mark.parametrize(
    ("claim", "quote", "reason"),
    [
        (
            "Acme added 5 engineers",
            "Acme added 15 engineers this quarter according to the report.",
            "number 5 not in quote",
        ),
        (
            "Acme raised $6 million",
            "Acme raised $60 million in a Series C round led by Northgate Capital.",
            "number 6000000 not in quote",
        ),
    ],
)
def test_verify_requires_equal_numeric_values(claim, quote, reason):
    assert gate.verify({"claim": claim, "quote": quote}, source(quote), TODAY) == reason


def test_verify_accepts_equivalent_number_formats():
    quote = "Acme announced 60,000,000 in funding to expand operations this year."
    assert gate.verify(
        {"claim": "Acme raised $60 million in funding", "quote": quote},
        source(quote),
        TODAY,
    ) is None


def test_verify_rejects_semantic_flip_and_short_quote():
    quote = "Acme closed a $60 million Series C round led by Northgate Capital."
    assert gate.verify(
        {"claim": "Acme went bankrupt", "quote": quote},
        source(quote),
        TODAY,
    ) == "claim not supported"
    assert gate.verify(
        {"claim": "Acme raised funding", "quote": "Acme"},
        source("Acme"),
        TODAY,
    ) == "quote too short"


def test_offline_support_uses_stemmed_content_word_overlap():
    assert gate.support_check(
        "The company added new engineers this quarter",
        "The company also adds 15 engineers this quarter",
        meter=None,
    )
    assert not gate.support_check(
        "Acme went bankrupt",
        "Acme closed a $60 million Series C funding round",
        meter=None,
    )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("SUPPORTED", True), ("NOT_SUPPORTED", False), ("UNSURE", False)],
)
def test_live_support_check_calls_once_at_cheap_tier(monkeypatch, answer, expected):
    calls = []
    monkeypatch.setattr("kernel.live_llm", lambda: True)
    monkeypatch.setattr(
        "kernel.chat",
        lambda meter, label, want, system, user: calls.append((label, want)) or answer,
    )

    assert gate.support_check("A claim", "A quote", meter=object()) is expected
    assert calls == [("claim support check", "cheap")]


def test_kernel_reexports_gate_verify():
    assert kernel_verify is gate.verify


def test_offline_extraction_injects_three_tagged_red_team_cases():
    claims = extract_offline(
        [
            {
                "id": 0,
                "text": "Acme added 15 engineers this quarter. Acme closed a $60 million Series C round.",
            }
        ]
    )
    injected = [claim for claim in claims if claim.get("injected")]

    assert {claim["red_team_case"] for claim in injected} == {
        "substring-number",
        "semantic-flip",
        "tiny-quote",
    }


def test_brief_audit_labels_red_team_claims():
    from modes import run_brief

    result = run_brief("Acme", "Planning")
    red_team = result["audit"]["red_team"]

    assert len(red_team) == 3
    assert all(item["label"] == "red-team test claim" for item in red_team)
    assert all(item["blocked"] for item in red_team)
