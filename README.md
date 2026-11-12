# Ledger

**Cheaper agents. Stronger evidence.** Ledger makes AI agents do a cheap,
deterministic check before they spend on an expensive model—and attaches proof
to every outcome.

## The idea

Most AI agents waste money in two ways: they read more context than they need,
and they make claims they cannot back up. Those are the same problem. The
agent should build the **smallest context that is sufficient and verifiable**.

Ledger is one shared kernel with two modes:

### Brief mode — sourced pre-meeting intelligence

1. Search Tavily for news from the last 30 days.
2. Use a cheap model to extract claims with verbatim quotes.
3. Run a deterministic verification gate. The source must be fetched, the
   quote must appear in its text, every number must match, and the source date
   must be inside the window.
4. Drop and log failed claims with a reason.
5. Call the strong model once—and only with verified claims. If nothing passes,
   do not call it.
6. Return a one-page brief with numbered footnotes, quotes, a verification
   audit, open questions, and a token receipt.

### Fix mode — focused coding repairs

1. Run the tests first. If they pass, spend zero model tokens.
2. Locate the failure without an LLM using the traceback and the functions the
   failing test calls.
3. Send the strong model only those relevant functions, never whole files.
4. Apply one small, diff-only edit and rerun the tests.
5. Stop as soon as the tests are green. If the failure looks like an API
   change, use Tavily to fetch current documentation instead of guessing.

## One kernel, two guarantees

- **Token meter:** records every model call and prints a cost receipt.
- **Budget control:** at 80%, route strong-model work to the cheap model; at
  100%, return a partial result instead of crashing.
- **Evidence ledger:** every briefing claim links to a URL, date, and quote;
  every coding outcome links to a test result.

## Sponsor roles

- **Bifrost** is the control plane for model calls: routing, budgets, caching,
  fallbacks, and logs.
- **Tavily** is the only web-knowledge source: date-filtered news, extraction,
  and documentation lookup.

## Headline metric

**Cost per verified outcome:** one sourced claim that passes the gate, or one
coding task whose tests pass.

> Ledger checks cheaply before spending and attaches proof to everything it
> says.

## Quick start

```bash
pip install -r requirements.txt
uvicorn server:app --port 8000     # run from this folder
```

Open http://localhost:8000. With no keys set it runs in offline replay with
bundled sources and a stub model.

## Live mode

```bash
export TAVILY_API_KEY=...                 # news search with start/end date window
export BIFROST_URL=http://localhost:8080  # OpenAI-compatible gateway
export LEDGER_CHEAP=openai/gpt-4o-mini    # optional, provider/model
export LEDGER_STRONG=anthropic/claude-sonnet-4-5
```

## Layout

| File | Role |
|---|---|
| `kernel.py` | Meter, budget degrade, `verify()` gate, Bifrost and Tavily clients |
| `modes.py` | Brief pipeline and Fix pipeline |
| `server.py` | FastAPI: `/api/status`, `/api/brief`, `/api/fix` |
| `index.html` | Frontend |
| `test_ledger.py` | Offline tests: `pytest -q` |

## Status

Prototype. Prices in `kernel.py` are placeholders. Offline stub models exercise
the pipeline and verification gate. Live mode uses Tavily search content;
Tavily Extract is not wired, and Bifrost fallback and prompt-cache pass-through
are not yet verified.

## License

MIT
