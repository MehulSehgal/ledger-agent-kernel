# ledger-agent-kernel

Deterministic agent execution kernel with verifiable live receipts, strict local-only routing for confidential repositories, and configurable token budgets.

## Jump-Start Demo Highlights

- **Default Token Budget (`100`):** All Jump-Start demo presets (`Board prep`, `Market scan`, `Private review`) and the live receipt initialize with a `100`-token budget.
- **Strict Local-Only Routing:** Selecting **`⌁ Private review`** (or any `confidential` payload) locks execution to `local://ledger-ollama-runtime` and blocks external cloud fallbacks.
- **Real-Time Non-Zero Receipts:** Every execution emits immutable receipt updates across `routing` (`102`), `running` (`104`), and `settled` (`200`) stages without resetting `liveCodeCount` or `tokensUsed` to `0`.
- **Confidential Repository Diff Output:** Running **`⌁ Private review`** preserves and renders the unified `diff --git` patch in the output panel with inline secret redaction.
