# Round analysis timeline and counterfactual explorer

## Plan status

- **Summary:** Explain one completed round analysis as synchronized evidence, table-observation,
  and reconstruction-hypothesis rows, then support immutable counterfactual comparisons.
- **Status:** In Progress
- **Depends on:** Completed [Plan 0031](../5-closed/0031-Round_Reconstruction_Integration_Harness.md)
  and completed [Plan 0032](../5-closed/0032-Round_Recording_Analysis_PoC.md).
- **Related:** [Plan 0026](../0-to-specify/0026-Reconstruction_Review_Workflow.md) owns correction
  constraints, reviewed reconstruction, and the complete round editor.
- **Reviewed:** 2026-08-30 against repository baseline `c6d372def`, the current game-engine,
  operations, evidence-package, table-observation, and round-analysis contracts, and the supported
  stable frontend major versions.
- **UI decision:** Use a desktop-first React and TypeScript browser UI. The existing backend serves
  its production assets. Do not put this diagnostic workflow in the iOS capture UI.

## Milestone status

- **M0:** Complete — replace the operations result with a scored per-action explanation contract.
- **M1:** Complete — project one immutable analysis into timeline data and serve its central frames.
- **M2:** Complete — establish the frontend toolchain, generated API types, and typed client.
- **M3:** Complete — package and serve a production frontend with one API smoke view.
- **M4:** Complete — render the first synchronized three-column timeline for a resolved fixture.
- **M5:** Complete — explain alternatives, incomplete input, impossible input, and diagnostics.
- **M6:** Pending — derive and recompute strict counterfactual inputs without source mutation.
- **M7:** Pending — persist and serve immutable counterfactual results.
- **M8:** Pending — compare the baseline and counterfactual results with visual change markers.

## 1. Outcome

An operator can open one completed round analysis in a local browser and follow the complete path
from recorded evidence to the game engine result.

The main view is an ordered list. Each row uses three synchronized columns:

| Evidence | Table observation | Reconstruction hypothesis |
| --- | --- | --- |
| Event time, event sequence, package ID, and the available frame nearest the event time | Observation status, analyzer identity, observed cards, identity candidates, probabilities, and available capability scores | The selected or ignored action for each observed card, the resulting card play and trick position, score contributions, and focused alternatives |

Show inferred missing card plays as explicit rows between evidence rows. Label them as engine
inferences with no source evidence. Never manufacture an evidence or table-observation value for
them.

The view starts with the best reconstruction hypothesis. An operator can select another retained
hypothesis. The interpretation column and changed card plays update while the evidence and table
observations stay fixed. A compact header shows the reconstruction status, hypothesis rank and
score, search truncation, and the current trick sequence.

Later milestones let the operator create a counterfactual run from the same immutable analysis.
The first supported changes are:

- exclude one table observation or one observed card from reconstruction;
- change the probability of an existing visual card identity candidate; and
- restore the baseline value.

The UI compares the baseline and counterfactual results. It does not change an evidence package,
table observation, source analysis, or reviewed reconstruction.

## 2. Fixed decisions

1. Build a local, desktop-first React 19 single-page application with strict TypeScript and Vite 8.
   Use client-side rendering. Do not add server-side rendering or a Node.js application server.
2. Open the UI with an explicit analysis ID. Do not add an analysis history, search, accounts, or
   remote access in this epic.
3. Read the exact immutable `input.json` and `result.json` artifacts recorded by the analysis.
   Do not reconstruct the view from the latest database rows or the latest analyzer output.
4. Select the central frame deterministically from the evidence package: use the stored frame with
   the smallest absolute `actual_offset_ms`; break ties by `actual_offset_ms` and then `part_name`.
   Show a clear missing-frame state when the package has no frame.
5. Preserve a per-hypothesis action for every input observed card. Identify a source action by its
   observation ID and observed-card ID together; the observed-card ID is not globally unique in the
   current input contract. A source action is `selected` or `ignored`. Preserve each inferred
   missing card play as a separate `inferred` action and identify it by its one-based play index.
   Do not infer this mapping in the browser from parallel lists.
6. For each selected action, preserve the observation ID, observed-card ID, one-based play index,
   player, selected visual card identity, candidate probability, identity log-score contribution,
   and each available visual-evidence score contribution. For each ignored action, preserve the
   observation ID, observed-card ID, and engine-applied ignore penalty. For each inferred action,
   preserve the one-based play index, player, inferred card identity, and engine-applied
   missing-play penalty. Preserve `total_score` on the hypothesis. The sum of all action
   contributions must equal `total_score` with an absolute tolerance of `1e-9`.
7. Replace `round-reconstruction-result/v1` with `round-reconstruction-result/v2` when the action
   mapping is added. Do not add a compatibility reader or optional fallback for older runtime
   artifacts. Update the operations result tests, all four reconstruction scenario expectations,
   and the Plan 0032 compact result fixtures in the same milestone.
8. Keep engine language exact. A table observation is evidence, not a card play. A reconstruction
   hypothesis is one possible legal sequence, not truth. Use `selected`, `ignored`, and `inferred`
   instead of `correct`, `false`, or `detected play`.
9. Keep counterfactual changes separate from correction constraints. A counterfactual run is a
   diagnostic derived result. It is not a human assertion and cannot create a reviewed
   reconstruction.
10. Persist each counterfactual request and its derived input and result as immutable disposable
    runtime artifacts. Record the source analysis ID and source artifact hashes. Reuse the source
    analysis search limits unless the contract is extended in a later epic.
11. When one candidate probability changes from `p` to `q`, retain the existing candidate set. For
    each other candidate with probability `r`, use `r × (1 - q) / (1 - p)`. Require every derived
    probability to be finite and greater than zero and require the sum to remain within the
    table-observation contract tolerance. Sort the derived candidates by descending probability;
    preserve their baseline order when probabilities tie. A one-candidate distribution cannot be
    overridden. Reject any value that cannot produce a valid distribution. Do not add or replace
    identity candidates in this epic.
12. Verify the three-column layout at a `1440 × 900` CSS-pixel viewport and the stacked layout at a
    `390 × 844` CSS-pixel viewport. These are test sizes, not device support claims.

## 3. Frontend architecture

Use a mainstream frontend stack with a small dependency surface:

| Concern | Decision |
| --- | --- |
| UI framework | React 19 with function components and hooks |
| Language | Strict TypeScript; do not add plain JavaScript source files |
| Build and development server | Vite 8 |
| Runtime and package manager | Node.js 24 LTS from `mise.toml` and its bundled npm client |
| Styling | Plain CSS with custom properties and CSS Modules for component-local styles |
| API types | Generate TypeScript types from the FastAPI OpenAPI document with `openapi-typescript` |
| API client | One small typed wrapper around browser `fetch` |
| Component tests | Vitest, React Testing Library, and `@testing-library/user-event` |
| Browser tests | Playwright against the built UI and a fixture-backed FastAPI process |
| Lint and format | ESLint flat configuration, `typescript-eslint`, React Hooks rules, and Prettier |
| Dependency lock | Commit `package-lock.json` and install with `npm ci` in verification |

Create one root `web/` package named `dokodetector-web`. Keep frontend source, tests, and generated
API types in that package. Keep Python code and Python templates out of it.

Vite owns the development loop. Its development server proxies `/v1` requests to the local FastAPI
server. A production build writes hashed static assets. Package those assets with the backend. The
FastAPI process serves the entry document and assets under `/round-analyses/`; all API and media
requests stay same-origin. The entry path is `/round-analyses/{analysis_id}`. A direct load or
browser refresh of that path must return the entry document. A normal local backend start must not
require a running Node.js process.

Use the FastAPI OpenAPI document as the API type source. Add a reproducible command that starts the
application with test settings, writes its OpenAPI document, and generates the TypeScript
declarations from that document. Commit the generated declarations so a clean checkout can build
the packaged UI. Verification regenerates them and fails on a diff. Do not hand-maintain duplicate
request or response interfaces.

Use React state and derived values for the selected row, selected hypothesis, disclosures, and
counterfactual draft. Use `useReducer` when these transitions become coupled. Do not add Redux,
Zustand, MobX, TanStack Query, or another state library in this epic. The timeline is one immutable
load plus explicit counterfactual mutations, so browser `fetch` and local React state are enough.

Use the browser URL and `URLSearchParams` for the selected row and hypothesis. Do not add a frontend
router while the application has one screen. Reconsider React Router only when a later epic adds a
second independent screen.

Do not add Tailwind CSS, a component library, an icon package, or a charting library. Build the
layout from semantic HTML, CSS Grid, native controls, and small project components. This keeps the
first frontend focused on React, TypeScript, browser state, and accessibility.

Do not use htmx in this epic. htmx fits server-owned HTML interactions, but this view has coupled
client state across rows, hypotheses, deep links, and baseline comparison. Combining HTML partials
with custom client state would introduce two UI state models. Keep FastAPI responsible for strict
JSON, media, and immutable computation; keep React responsible for presentation and transient
interaction state.

Pin the current stable dependency versions when M2 starts and retain them in `package-lock.json`.
Use supported stable releases, not release candidates. Do not enable React Compiler in the initial
scaffold. Add it later only after the plain build is established and its value is measured.

## 4. Timeline projection

Add a strict backend-owned timeline response. It joins existing immutable values for presentation;
it is not a new source artifact. The response contains:

- analysis identity, reconstruction status, search limits, diagnostics, and artifact hashes;
- ordered evidence rows keyed by observation ID and package ID;
- the selected central-frame URL and its offset, timestamp, digest, and dimensions;
- the complete table observation for each row;
- one interpretation block per retained hypothesis, using the engine action mapping;
- focused decisions linked by their source observation IDs;
- separate inferred-play rows anchored before, between, or after observation rows by play index; and
- warnings for missing media, insufficient evidence, ignored observations, and truncated search.

Use one endpoint:

```text
GET /v1/round-analyses/{analysis_id}/timeline
```

Add a read-only frame endpoint for a stored package and declared frame part. Resolve the requested
part through stored metadata:

```text
GET /v1/round-analyses/{analysis_id}/evidence-packages/{package_id}/frames/{part_name}
```

Require the package ID to occur in the exact reconstruction input for the named analysis. Return
only the validated stored JPEG, with `image/jpeg`, a digest ETag, and an immutable cache header.
Reject path syntax, undeclared parts, and packages that do not belong to the analysis.

The projection must fail clearly if the stored analysis artifacts fail their recorded hashes, do
not match the analysis ID, or refer to unavailable source observations. Do not silently use newer
data. Return `404` for an unknown analysis or source identifier, `409` when the analysis is not
complete, and a typed `500` integrity error when recorded source or artifact bytes do not match
their digest.

## 5. User interface

Use a responsive grid. At the declared desktop test width, keep the three columns aligned in one
row. At the declared narrow test width, stack the three cells inside each row in the same
evidence-to-interpretation order.

The first version supports:

- a sticky summary with result status, selected hypothesis, score, trick progress, and warnings;
- previous and next row controls plus keyboard navigation;
- a hypothesis selector with rank and score;
- confidence bars for identity candidates and compact values for other analyzer capabilities;
- a clear selected, ignored, or inferred label for every engine action;
- links between a focused decision, its source rows, and its affected card play;
- expandable score details and engine diagnostics;
- expandable raw table-observation and reconstruction-result JSON for diagnosis; and
- stable empty states for missing frames, insufficient evidence, no hypotheses, and no focused
  decisions.

Use text, icons, and color together for status and change markers. Keep the frame aspect ratio.
Avoid a horizontally scrolling page at the supported desktop width. Preserve row and hypothesis
selection in the URL so a specific explanation can be shared locally and reproduced.

## 6. Counterfactual contract and comparison

Add a strict request with a client-created counterfactual ID, source analysis ID, source input and
result hashes, excluded observation IDs, excluded observed-card references, and
candidate-probability overrides. An observed-card reference contains its observation ID and
observed-card ID. An override also contains the candidate card identity. Use UUIDs for the analysis
and counterfactual IDs. Validate every reference against the source input. Require unique
references. Reject an observed-card exclusion or probability override when its parent observation
is excluded, and reject multiple overrides for the same candidate. Require at least one effective
change. Reject exclusion of every source observation and reject an override that equals its
baseline probability.

Materialize a new reconstruction input in memory. Do not modify or replace the source input. An
excluded table observation is absent from the derived input. An excluded observed card is absent
from its derived table observation. A probability override creates a derived candidate
distribution under the rule in fixed decision 11.

Run the existing reconstruction entry point with the source search limits. Publish the canonical
counterfactual `request.json`, derived `input.json`, and `result.json` together under the
round-analysis runtime root. Publish all three files atomically and record their SHA-256 digests.
Use the counterfactual ID as the derived reconstruction run ID. Run the reconstruction synchronously
in the request for this local tool. A failed request must not leave a final artifact directory.

Use these endpoints:

```text
POST /v1/round-analyses/{analysis_id}/counterfactuals
GET  /v1/round-analyses/{analysis_id}/counterfactuals/{counterfactual_id}
```

The create response contains the validated request, artifact identities and hashes, and the strict
reconstruction result. Idempotent reuse of the same counterfactual ID and canonical request returns
the stored response. Reuse with different content is a conflict. The read endpoint makes a shared
local URL reproducible after a page reload. Do not add a counterfactual list endpoint, queue,
database table, or retention policy in this epic.

The comparison UI shows:

- baseline and counterfactual status, hypothesis count, best score, and truncation state;
- inserted, removed, and changed card plays;
- observations and observed cards whose selected or ignored action changed;
- changed focused decisions and score contributions; and
- a warning when search truncation makes the comparison incomplete.

The operator can return to the exact baseline without deleting the counterfactual artifact.

## 7. Delivery milestones

### M0 — Engine explanation actions

- Make the game engine retain selected, ignored, and inferred actions directly on each
  reconstruction hypothesis. Make operations serialize and validate those records.
- Retain per-action score contributions and `total_score`. Validate their sum with the fixed
  tolerance.
- Replace the operations result with `round-reconstruction-result/v2` and update its scenario and
  compact API fixtures and tests.

#### M0 implementation evidence — 2026-08-30

- Added selected, ignored, and inferred action records to each retained engine hypothesis. Each
  selected and ignored source action uses its observation ID and observed-card ID together.
- Added per-action identity, visual-evidence, ignore, and missing-play score contributions. The
  operations contract validates action alignment, fixed penalties, and `total_score` arithmetic
  within `1e-9`.
- Replaced the operations result artifact with `round-reconstruction-result/v2`. Updated the four
  status scenarios, the compact round-analysis fixture, and the relevant engine, operations, and
  backend tests.
- Verification: 73 game-engine tests, 98 operations tests, 126 backend tests, and Ruff checks for
  all three Python packages pass. The existing FastAPI test-client deprecation warning remains.

### M1 — Timeline projection and frame delivery

- Load and hash-check one completed analysis's exact input and result artifacts.
- Add the strict timeline projection and central-frame selection.
- Add the analysis-scoped immutable stored-frame endpoint and contract tests for foreign, missing,
  and invalid media.

#### M1 implementation evidence — 2026-08-30

- Added a strict backend timeline projection that hash-checks the exact stored input and result
  artifacts, validates their analysis identity and source records, and verifies the referenced
  table observations and evidence packages before projection.
- Added deterministic central-frame selection for each evidence row. The selected frame uses the
  smallest absolute `actual_offset_ms`, then `actual_offset_ms`, then `part_name`, and includes its
  immutable URL, timestamp, digest, and dimensions. Missing frames produce an explicit warning.
- Added analysis-scoped JPEG delivery with package ownership checks, safe part-name validation,
  source-file digest verification, digest ETags, and immutable cache headers. Integrity failures
  return the typed `analysis_integrity_error` response.
- Added warnings, ranked hypothesis action mappings, focused-decision links, and inferred-play
  rows anchored before, between, or after evidence rows.
- Verification: 129 backend tests and Ruff checks pass. The existing FastAPI test-client
  deprecation warning remains.

### M2 — Frontend foundation

- Add Node.js 24 LTS to `mise.toml` and scaffold the root `web/` package with React, strict
  TypeScript, Vite, npm, ESLint, Prettier, Vitest, Testing Library, and Playwright.
- Generate and verify the OpenAPI TypeScript declarations and add the typed `fetch` boundary.
- Add the Vite-to-FastAPI development proxy and prove the typed development path with automated
  checks.

#### M2 implementation evidence — 2026-08-30

- Added Node.js `24.20.0` to `mise.toml` and scaffolded the root `web/` package with React
  `19.2.8`, strict TypeScript `5.9.3`, Vite `8.2.2`, npm, ESLint `10.9.1`, Prettier `3.9.6`,
  Vitest `4.1.11`, Testing Library, and Playwright `1.62.1`. Committed `package-lock.json` and
  kept generated API output under `web/src/api/`.
- Added an isolated backend OpenAPI export command. It creates the FastAPI app with local POC
  analyzer and temporary SQLite and evidence paths, then writes the document used by
  `openapi-typescript`. `npm run verify:api` regenerates into a temporary file and fails on any
  declaration diff.
- Added a typed browser `fetch` client for analysis status, timeline, and frame delivery. Its
  response types derive directly from the generated operation schemas.
- Added the Vite `/v1` proxy with `VITE_API_PROXY_TARGET` override, a local proxy integration
  test, React Testing Library tests, and a Playwright production-preview smoke test.
- Verification: clean `npm ci`, `npm run check`, `npm run build`, and `npm run test:e2e` pass;
  the frontend has 5 unit/integration tests and 1 browser test. The backend suite remains green
  at 130 tests. The existing FastAPI test-client deprecation warning remains.

### M3 — Production asset boundary

- Add one typed API smoke view and a production Vite build with hashed static assets.
- Package the build with the backend and serve direct loads and refreshes of the analysis entry
  route without a Node.js process.
- Verify development and packaged production modes.

### M3 implementation evidence — 2026-08-30

- Added a route-aware React smoke view that reads the explicit analysis ID from
  `/round-analyses/{analysis_id}`, loads status and the immutable timeline through the generated
  API client, and shows stable loading, progress, error, and connected states.
- Configured Vite with the `/round-analyses/` base path so production JavaScript and CSS use hashed
  same-origin asset URLs under `/round-analyses/assets/`.
- Added a configurable `FRONTEND_DIST` backend boundary. FastAPI serves the packaged entry document
  for direct analysis loads and refreshes and serves the hashed assets without a Node.js process.
  The default source-checkout path also works when the backend has its own nested mise config.
- Added backend package-route tests, React tests, a production-preview browser test, and local
  frontend run instructions. The browser test verifies the hashed asset URL and the smoke API
  state. A real Vite build was requested through FastAPI `TestClient`.
- Verification: `npm ci`, `npm run check`, `npm run build`, and `npm run test:e2e` pass; the
  frontend has 6 unit/integration tests and 2 browser tests. The focused backend round-analysis
  and packaged-frontend tests pass. The existing FastAPI test-client deprecation warning remains.

### M4 — Resolved timeline UI

- Render a resolved fixture in the three-column layout with row and hypothesis navigation.
- Add focused browser-level tests for rendering, deep links, and keyboard navigation.

**Status: Complete (2026-08-30).**

- Replaced the M3 smoke panel with a typed resolved-analysis view. It renders evidence, table
  observation, and reconstruction columns from the immutable timeline response. It keeps the
  columns aligned on desktop and stacks their cells on narrow screens.
- Added the sticky analysis summary, hypothesis selector, confidence bars, selected/ignored/
  inferred action labels, central-frame and missing-frame states, explicit engine-inference rows,
  row controls, and URL-backed row and hypothesis selection.
- Added Home, End, ArrowUp, and ArrowDown row navigation. Switching hypotheses changes the
  interpretation column while the evidence and table-observation columns stay fixed.
- Added a typed resolved fixture, component tests for hypothesis switching and deep links, and
  Playwright coverage at 1440×900 for the three-column layout plus keyboard navigation.
- Verification: frontend typecheck, ESLint, Prettier, generated API drift check, Vitest (7 tests),
  the production Vite build, and Playwright (3 browser tests) pass.

### M5 — Alternative and failure explanations

- Add focused-decision links, hypothesis comparison, score details, and raw JSON disclosure.
- Cover ambiguous, incomplete, impossible, missing-frame, insufficient-evidence, and truncated
  fixtures.
- Complete narrow-width layout, accessible labels, non-color status cues, and local documentation.

**Status: Complete (2026-08-30).**

- Added focused-decision cards with retained alternatives, the selected play, and source-row jump
  links. Added a retained-hypothesis comparison table with selected, ignored, and inferred action
  counts.
- Added state-aware explanations for ambiguous, incomplete, and impossible results. Added stable
  empty states for no hypotheses and no focused decisions. Warning codes and status labels keep
  missing frames, insufficient evidence, and search truncation visible without relying on color.
- Added expandable score contributions, engine diagnostics, selected table-observation JSON, and
  reconstruction-result JSON. Added local frontend instructions in `web/README.md`.
- Added typed ambiguous, incomplete, and impossible fixtures and component/browser coverage for
  terminal explanations, warning cues, source links, disclosures, keyboard navigation, and the
  stacked `390 × 844` layout with no page overflow.
- Verification: `npm run check`, `npm run test:e2e` (5 browser tests), and `git diff --check`
  pass.

### M6 — Counterfactual derivation

- Add the strict counterfactual request and reference validation.
- Implement observation exclusion, observed-card exclusion, and candidate-probability overrides.
- Run deterministic recomputation with the source search limits and the counterfactual ID as the
  run ID.
- Add tests that prove derivation and recomputation do not change source artifacts or stored table
  observations.

### M7 — Counterfactual runtime

- Add atomic immutable runtime artifacts, source hashes, and canonical idempotency.
- Add the synchronous create and read APIs. Prove retry behavior after a failed publication.
- Prove conflict handling and retrieval after an application restart.

### M8 — Visual counterfactual comparison

- Add row controls for the supported changes and an explicit Run action.
- Show baseline and derived hypotheses side by side with changed rows, plays, decisions, scores,
  and diagnostics.
- Add end-to-end fixture cases for a changed result and an unchanged result.

## 8. Tests and acceptance criteria

- Every input observed card appears exactly once as selected or ignored in each retained
  hypothesis. Every inferred missing play appears exactly once as inferred.
- The per-action contributions reproduce each retained hypothesis score within the declared
  tolerance.
- The timeline row order follows the immutable reconstruction input. The central frame selection is
  deterministic and its bytes match the stored digest.
- A resolved fixture shows the complete evidence-to-observation-to-card-play path without reading
  raw JSON.
- An operator can switch between ambiguous hypotheses and see only the interpretation and card-play
  differences change.
- Incomplete and impossible results explain absent hypotheses, insufficient evidence, rejected
  branches, ignored observations, and search truncation without implying ground truth.
- The layout is usable at `1440 × 900` and stacks without lost content at `390 × 844`. Keyboard
  navigation and non-color status labels work.
- Repeated counterfactual requests with the same ID and content return byte-identical artifacts.
  Conflicting reuse fails.
- A counterfactual can be read again by analysis ID and counterfactual ID after an application
  restart while the runtime artifacts still exist.
- Counterfactual fixture tests cover excluding an observation, excluding one observed-card
  reference, increasing one existing candidate probability, a changed best hypothesis, and no
  result change.
- Source evidence packages, table observations, and analysis artifacts remain byte-for-byte
  unchanged after all view and counterfactual operations.
- `npm ci`, TypeScript checking, generated-API drift checking, ESLint, Prettier checking, Vitest,
  the production Vite build, and Playwright pass through the toolchain declared in `mise.toml`.
- Relevant game-engine, operations, and backend tests plus Ruff and formatting checks pass through
  `mise exec`.

## 9. Non-goals

- Human correction, correction constraints, reviewed reconstruction, or review-queue completion.
- Editing a card play, player, card-play order, trick boundary, or complete round sequence.
- Treating a counterfactual result as truth or automatically promoting it to a correction.
- Video playback, synchronized scrubbing, spatial overlays, card crops, or card tracklet graphics.
- Live or incremental reconstruction during recording.
- Analysis history, search, multi-user access, authentication, cloud deployment, or production
  retention.
- New analyzer capabilities, model training, probability calibration, or reconstruction search
  improvements.
- Server-side rendering, React Server Components, a Node.js application server, or a full-stack
  JavaScript framework.
- htmx, a frontend router, a client state library, a component library, or a CSS framework.

## 10. Relationship to later review work

This epic provides the read-only explanation and diagnostic comparison surface. Plan 0026 remains
the owner of human correction and reviewed reconstruction. A later Plan 0026 specification can
reuse the timeline projection, media delivery, and row interaction patterns. It must convert human
decisions into correction constraints and rerun reconstruction through that contract. It must not
reuse counterfactual probability changes as corrections.

Close this epic when M0–M8 pass with checked-in local fixtures and an operator can explain one
baseline result, run the three supported counterfactual changes, and compare the derived result
without modifying any source value.
