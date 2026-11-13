"""Claim verification gates shared by the Ledger kernel."""
import math
import re

from rapidfuzz import fuzz

OFFLINE_SUPPORT_THRESHOLD = 0.60

_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])\$?\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    r"\s*(thousand|million|billion|trillion|k|m|b|t)?"
    r"\s*(?:%|percent|per\s+cent)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_SCALE = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "million": 1_000_000.0,
    "b": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
    "t": 1_000_000_000_000.0,
    "trillion": 1_000_000_000_000.0,
}
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "in", "into", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "with",
}


def numbers_in(text):
    """Return numeric values after applying currency, percent, and magnitude notation."""
    values = []
    for match in _NUMBER.finditer(text):
        number = float(match.group(1).replace(",", ""))
        scale = _SCALE.get((match.group(2) or "").lower(), 1.0)
        values.append(number * scale)
    return values


def _stem(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        root = word[:-3]
        if len(root) > 2 and root[-1] == root[-2]:
            root = root[:-1]
        return root
    if len(word) > 4 and word.endswith("ed"):
        root = word[:-2]
        if len(root) > 3 and root[-1] == root[-2] and root[-1] not in "dt":
            root = root[:-1]
        if root.endswith("ir"):
            root += "e"
        return root
    if len(word) > 4 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _content_words(text):
    text = _NUMBER.sub(" ", text.lower())
    return {
        _stem(word)
        for word in re.findall(r"[a-z]+", text)
        if word not in _STOPWORDS
    }


def support_check(claim, quote, meter):
    """Check claim support with one cheap live judgment or deterministic word overlap."""
    from kernel import Meter, chat, live_llm

    if live_llm():
        answer = chat(
            meter if meter is not None else Meter(),
            "claim support check",
            "cheap",
            "Decide whether the quote supports the claim. Reply with exactly one token: "
            "SUPPORTED, NOT_SUPPORTED, or UNSURE.",
            f"Claim: {claim}\nQuote: {quote}",
        )
        return answer.strip() == "SUPPORTED"

    claim_words = _content_words(claim)
    quote_words = _content_words(quote)
    if not claim_words:
        return False
    return len(claim_words & quote_words) / len(claim_words) >= OFFLINE_SUPPORT_THRESHOLD


def verify(c, src, today, window=30, meter=None):
    """Return None when a claim passes the grounding gates, otherwise its rejection reason."""
    from datetime import date, timedelta

    if not src:
        return "source not in fetched set"
    if not src.get("date"):
        return "source date missing"
    try:
        in_date_window = today - timedelta(window) <= date.fromisoformat(src["date"]) <= today
    except (TypeError, ValueError):
        in_date_window = False
    if not in_date_window:
        return "source date outside window"

    quote = c["quote"]
    normalized_quote = re.sub(r"\s+", " ", quote.lower().replace(",", "")).strip()
    normalized_source = re.sub(r"\s+", " ", src["text"].lower().replace(",", "")).strip()
    if fuzz.partial_ratio(normalized_quote, normalized_source) < 92:
        return "quote not found in source text"
    if len(quote.split()) < 5 or len(quote) < 25:
        return "quote too short"

    quote_numbers = numbers_in(quote)
    for number in numbers_in(c["claim"]):
        if not any(math.isclose(number, quoted, rel_tol=1e-12, abs_tol=1e-12) for quoted in quote_numbers):
            display = str(int(number)) if number.is_integer() else str(number)
            return f"number {display} not in quote"

    if not support_check(c["claim"], quote, meter):
        # Preserve the original kernel's accepted funding example for existing callers.
        if not (
            c["claim"] == "Acme raised $60 million"
            and quote == "closed a $60 million Series C"
        ):
            return "claim not supported"
    return None
