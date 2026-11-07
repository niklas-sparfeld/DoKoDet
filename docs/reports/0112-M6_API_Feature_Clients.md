# 0112 M6 API feature clients

## Result

`client.ts` now composes feature clients. It has no request methods, URL builders, or broad type
re-exports. `clientTypes.ts` holds the typed client method contract used by the feature factories.
Each factory returns only its own methods.

| Owner | Module | Main responsibility |
| --- | --- | --- |
| Recordings | `recordingsClient.ts` | Recording list and detail, repository bundle URLs |
| Pipeline processing | `pipelineProcessingClient.ts` | Pipeline runs, workspace, selections, comparisons, result reads, shared frame URLs |
| Calibration | `calibrationClient.ts` | Calibration refinement and calibration reads |
| Analysis | `analysisClient.ts` | Recording analysis, round analysis, timeline, evidence frame, and counterfactual routes |
| Jobs | `jobsClient.ts` | Job list, detail, logs, enqueue, cancel, retry, and queue movement |
| Frame review | `frameReviewClient.ts` | Frame-review page and workflow routes |
| Shared composition | `client.ts` | Compose the typed feature client objects only |
| Shared HTTP | `transport.ts` | Existing M5 request handling, errors, headers, and abort behavior |

The repository had no standalone jobs client before M6. M6 added `jobsClient.ts`. It keeps the job
routes beside their existing job contract types. Frame-review routes have a separate client. The
existing jobs and lineage modules remain independent. No feature client or production consumer
imports `client.ts`. Consumers import their feature client, contract, or URL owner. UI components
that need methods from two owners compose those factories locally.

## Behavior and focused tests

The clients preserve request methods, response types, URL encoding, query ordering, request bodies,
headers, and abort signals. Feature tests are in `recordingsClient.test.ts`,
`pipelineProcessingClient.test.ts`, `calibrationClient.test.ts`, `analysisClient.test.ts`, and the
existing `jobsClient.test.ts`. Frame-review behavior remains covered by
`frameReview/FrameReviewQueueView.test.tsx`. `client.test.ts` covers the aggregate composition.

Physical line counts are within the M0 budgets:

| Path | Lines |
| --- | ---: |
| `client.ts` | 21 |
| `clientTypes.ts` | 262 |
| `recordingsClient.ts` | 41 |
| `pipelineProcessingClient.ts` | 290 |
| `calibrationClient.ts` | 136 |
| `analysisClient.ts` | 103 |
| `jobsClient.ts` | 107 |
| `frameReviewClient.ts` | 41 |
| New focused API test files | 30–59 each |

## Verification

- `cd web && npm run check` — passed: typecheck, ESLint, Prettier, generated API verification, and all 214 web tests in 40 files.
- `git diff --check` — passed.
- Generated API export logged that its temporary processor-run catalog resource root was unavailable; the generated API diff passed. This is the existing environment limit recorded in M5.

The focused tests use deterministic fetch stubs. This milestone changes web request ownership only; it does not change persistence or backend behavior.
