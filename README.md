# Ledger

Gate before you spend: one agent kernel that does real work on the fewest tokens and proves every claim it makes.

Two modes share one kernel (token meter, budget degrade, verification gate):

- **Brief**: pre-meeting briefing. Date-windowed news, claim extraction, deterministic verification, then one strong-model synthesis over verified claims only.
- **Fix**: coding agent. Tests first, deterministic localization with `ast`, one diff-only patch call, early exit on green.

Headline metric: cost per verified outcome.

## Quick start

```bash
pip install -r requirements.txt
uvicorn server:app --port 8000     # run from this folder
```

Open http://localhost:8000. With no keys set it runs in offline replay (bundled sources, stub model).

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
| `static/index.html` | Frontend |
| `tests/` | Offline tests: `pytest tests` |

## Status

Prototype. No benchmark numbers yet; prices in `kernel.py` are placeholders; the offline stub models exist to exercise the pipeline and the gate. Live mode uses Tavily search content (Extract with query is not wired). Bifrost fallback and prompt-cache pass-through are unverified.

## License

MIT
