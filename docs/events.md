# Server-Sent Events contract

Each event is a Server-Sent Event whose `data` field contains one JSON object:

```json
{
  "seq": 1,
  "ts": "ISO timestamp",
  "type": "step",
  "data": {}
}
```

- `seq`: integer sequence number.
- `ts`: ISO timestamp.
- `type`: event type listed below.
- `data`: object containing that event's payload.

Events are also sent as named SSE events (`event: step`, `event: result`, etc.).
The browser can reconnect using the same `EventSource`; its retry request
includes `Last-Event-ID`. The run console falls back to `GET /api/runs/{id}` to
recover terminal status if the event stream remains unavailable. Status
polling does not include missed event payloads.

## Event payloads

| Type | `data` fields |
| --- | --- |
| `step` | `id`, `title`, `status` (`running`, `ok`, `fail`, or `skipped`), `detail`; clients may derive duration from event timestamps |
| `model_call` | `label`, `tier` (`local`, `cheap`, or `strong`), `model`, `tokens_in`, `tokens_out`, `tokens_cached` (null if unreported), `usd` (null if unavailable), `cached` |
| `failover` | `from`, `to`, `reason` (may be `chaos (simulated)`) |
| `budget` | `used`, `cap`, `pct`, `state` (`ok`, `degraded`, or `exhausted`), `user`, `run_used`, `run_cap`; with a user id, `used` and `cap` describe the account total and `run_used` and `run_cap` the run's own token budget |
| `claim` | `id`, `text`, `status` (`verified` or `rejected`), `reason`, `source_n`, `quote`, `url`, `date` |
| `approval_request` | `hash`, `kind` (`WRITE`, `SHELL`, `GIT`, or `NETWORK`), `summary`, `payload`, `risk`; WRITE payloads may include a unified diff, SHELL payloads the argv and execution details, NETWORK payloads the exact query |
| `approval_result` | `hash`, `decision` (`approved` or `denied`), `once` |
| `blocked` | `kind`, `reason`, `source` (`policy`, `confidential`, or `injection`) |
| `result` | Final payload; its shape is defined by the application. |
| `error` | `message` |

`result.receipt` carries the final `tokens`, `cap`, `usd`, `prices_verified`,
and model-call records. A null/unverified price is not a measured cost.
Cached-token counts remain null when the provider does not report them.
`baseline_tokens` from older results is not proof of a measured baseline;
clients should show savings only when an explicitly measured baseline is
present.

Brief results include at most 2,000 characters of text per source. Each
verified bullet has a boolean `checks` object for `fetched`,
`date_in_window`, `quote_found`, `numbers_match`, and `supported`, plus
per-claim evidence. `audit.rejected_claims` carries rejection reasons and
labels injected cases as `red-team test claim`.

The approval endpoint accepts the exact pending hash:
`POST /api/runs/{id}/approve` with `{ "hash": "...", "decision": "approved",
"once": true|false }`. Approval requests time out after 300 seconds and are
denied on timeout.

The browser console treats an approval request as a waiting state, opens a
focus-trapped drawer with Deny focused by default, and submits all three
decisions to that endpoint. Its countdown also submits a denial at 300 seconds;
Escape never approves an action. `blocked` events populate the blocked-action
panel, while `failover` events update the failover banner.

## Red-team and benchmark endpoints

`POST /api/redteam` runs the local scenarios and returns dynamically evaluated
results:

```json
{
  "scenarios": [
    {
      "id": "scenario-id",
      "name": "Scenario name",
      "passed": true,
      "checks": { "check-name": true },
      "evidence": []
    }
  ],
  "passed": 1,
  "failed": 0
}
```

Each scenario's `evidence` contains run events using the event envelope above.
The red-team screen displays four scenario cards with pass/fail rings, check
chips, plain-language attack descriptions, and collapsed evidence.
`GET /api/bench/summary` serves the generated benchmark summary or returns
404 when no summary exists. Its `metadata` includes `task_count`, `run_count`,
`provenance_complete`, the recorded `models`, `task_sources`, and `engines`.
The benchmark screen marks missing/incomplete provenance, seeded tasks, and
offline-stub runs as unmeasured and hides their comparison charts. A measured
summary displays pass rates with 95% Wilson intervals, per-arm token means, a
task/run/model/date caption, and CSV export.

`result.confidential` is true when the run was confidential, whether the
request asked for it or the repository's own policy did. Confidential runs
report their model calls with the `local` tier. A confidential Fix result keeps
`symbols` and `diff_hash`, and also carries `diff` unless
`LEDGER_CONFIDENTIAL_DIFF=off` is set or the repository has its own
confidential policy file. See `docs/PRICING.md` for how `usd` is decided.
