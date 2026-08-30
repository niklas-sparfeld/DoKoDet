# Round analysis frontend

This package renders one immutable round analysis served by the local FastAPI backend.

## Local development

Install the locked dependencies and start Vite with the backend proxy:

```text
npm ci
npm run dev
```

Open `/round-analyses/{analysis_id}`. The Vite server proxies `/v1` requests to
`http://127.0.0.1:8000`. Set `VITE_API_PROXY_TARGET` when the backend uses another local port.

Run the complete frontend checks with:

```text
npm run check
npm run test:e2e
```

## Explanation controls

- Select a retained hypothesis to compare its possible legal sequence and score.
- Select a timeline row or use the arrow keys to keep evidence and interpretation aligned.
- Use a focused-decision link to jump to its source observation row.
- Expand score details, engine diagnostics, or raw JSON when the compact explanation is not enough.

## Counterfactual comparison

- Exclude an observation or one of its observed cards, or edit an existing candidate probability.
- Run the drafted changes to create an immutable derived reconstruction.
- Read the baseline and counterfactual side by side. Change markers cover plays, source actions,
  focused decisions, hypothesis scores, and diagnostics.
- Use Restore baseline to clear the draft and return to the source analysis view. Counterfactual
  artifacts are not corrections and do not change the source evidence.

The `ambiguous`, `incomplete`, and `impossible` query fixtures used by Playwright are local test
fixtures only. They are not backend API modes.
