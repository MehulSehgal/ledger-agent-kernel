"""Requests that omit a token budget get the default of 100 tokens."""
import pytest
from pydantic import ValidationError

from server import DEFAULT_TOKEN_BUDGET, BriefIn, FixIn


def test_default_budget_is_100_for_brief_and_fix():
    assert DEFAULT_TOKEN_BUDGET == 100
    assert BriefIn().cap == 100
    assert FixIn().cap == 100


def test_an_explicit_budget_still_wins():
    assert BriefIn(cap=12000).cap == 12000
    assert FixIn(cap=6000).cap == 6000


def test_budgets_below_the_floor_are_rejected():
    with pytest.raises(ValidationError):
        BriefIn(cap=99)
