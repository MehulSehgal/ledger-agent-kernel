"""Standalone smoke checks for the configured Bifrost and Tavily APIs."""
import json
import os
import sys
from datetime import date, timedelta

import httpx


def _secrets():
    return [
        value
        for name in ("BIFROST_VK", "TAVILY_API_KEY")
        if (value := os.getenv(name))
    ]


def _mask(text):
    for secret in sorted(_secrets(), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def _safe_json(value, parent_key=""):
    key = parent_key.lower()
    if "api_key" in key or "authorization" in key or "virtual_key" in key:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _safe_json(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, str):
        return _mask(value)
    return value


def _print_json(value):
    print(json.dumps(_safe_json(value), indent=2, ensure_ascii=False))


def _response_json(response, service):
    if not response.is_success:
        raise RuntimeError(
            f"{service} returned HTTP {response.status_code}: {_mask(response.text)}"
        )
    return response.json()


def main():
    required = ("BIFROST_URL", "TAVILY_API_KEY", "LEDGER_MODEL_CHEAP")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError("Missing required environment variable(s): " + ", ".join(missing))

    bifrost_headers = {}
    if os.getenv("BIFROST_VK"):
        bifrost_headers["Authorization"] = "Bearer " + os.environ["BIFROST_VK"]

    bifrost_response = httpx.post(
        os.environ["BIFROST_URL"].rstrip("/") + "/v1/chat/completions",
        headers=bifrost_headers,
        timeout=90,
        json={
            "model": os.environ["LEDGER_MODEL_CHEAP"],
            "messages": [{"role": "user", "content": "Reply with: ok"}],
        },
    )
    bifrost_json = _response_json(bifrost_response, "Bifrost")
    print("Bifrost chat completion (raw JSON):")
    _print_json(bifrost_json)

    today = date.today()
    tavily_headers = {
        "Authorization": "Bearer " + os.environ["TAVILY_API_KEY"],
    }
    search_response = httpx.post(
        "https://api.tavily.com/search",
        headers=tavily_headers,
        timeout=30,
        json={
            "query": "OpenAI",
            "topic": "news",
            "max_results": 5,
            "start_date": (today - timedelta(30)).isoformat(),
            "end_date": today.isoformat(),
        },
    )
    search_json = _response_json(search_response, "Tavily search")
    results = search_json.get("results", [])
    if not isinstance(results, list):
        raise ValueError("Tavily search response field 'results' must be a list")
    print("Tavily search top-level JSON keys:")
    print(_mask(json.dumps(list(search_json.keys()))))
    print("Tavily search published_date values:")
    for item in results:
        published_date = item.get("published_date") if isinstance(item, dict) else None
        print(_mask(json.dumps(published_date, ensure_ascii=False)))

    if not results or not isinstance(results[0], dict) or not results[0].get("url"):
        raise ValueError("Tavily search returned no first result URL for extraction")

    extract_response = httpx.post(
        "https://api.tavily.com/extract",
        headers=tavily_headers,
        timeout=30,
        json={
            "urls": [results[0]["url"]],
            "query": "funding",
            "chunks_per_source": 2,
        },
    )
    extract_json = _response_json(extract_response, "Tavily extract")
    print("Tavily extract (raw JSON):")
    _print_json(extract_json)


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        print(_mask(f"Smoke check failed: {exc}"), file=sys.stderr)
        raise SystemExit(1) from None
