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

## Event payloads

| Type | `data` fields |
| --- | --- |
| `step` | `id`, `title`, `status` (`running`, `ok`, `fail`, or `skipped`), `detail` |
| `model_call` | `label`, `tier` (`local`, `cheap`, or `strong`), `model`, `tokens_in`, `tokens_out`, `usd`, `cached` |
| `failover` | `from`, `to`, `reason` (may be `chaos (simulated)`) |
| `budget` | `used`, `cap`, `pct`, `state` (`ok`, `degraded`, or `exhausted`), `user` |
| `claim` | `id`, `text`, `status` (`verified` or `rejected`), `reason`, `source_n`, `quote`, `url`, `date` |
| `approval_request` | `hash`, `kind` (`WRITE`, `SHELL`, `GIT`, or `NETWORK`), `summary`, `payload`, `risk` |
| `approval_result` | `hash`, `decision` (`approved`, `denied`, or `timeout`), `once` |
| `blocked` | `kind`, `reason`, `source` (`policy`, `confidential`, or `injection`) |
| `result` | Final payload; its shape is defined by the application. |
| `error` | `message` |