# Pricing and the live cost line

The kernel never guesses a price. `prices.json` ships with every price set to
`null` and `"verified": false`, so a cloud call has no dollar cost until you
add real numbers.

The **Live cost** line on the receipt tells three cases apart:

| Shows | Meaning |
| --- | --- |
| `$0 · local only` | Every call so far was an offline stub or a local model. Nothing was billed. |
| `Not priced` | At least one cloud call ran, but `prices.json` has no verified price for its model. |
| A dollar amount | Every cloud call had a verified price. |

## Adding prices

Look up the current list prices on your provider's pricing page, then edit
`prices.json`:

```json
{
  "verified": true,
  "models": {
    "provider/model-name": {
      "input_per_mtok": 0.0,
      "output_per_mtok": 0.0
    }
  }
}
```

Replace the zeros with the real USD price per million input and output tokens.
Set `verified` to `true` only after you checked the numbers yourself.

The key must match the model name exactly as the receipt's call list and
`/api/status` show it. Redeploy afterwards so the server reads the new file.

## Local models

Confidential runs only use local models, so their calls report the `local`
tier and no API cost.
