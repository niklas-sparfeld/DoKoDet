# Round analysis timeline and counterfactual explorer

## Plan status

- **Summary:** Explain one completed round analysis as synchronized evidence, table-observation,
  and reconstruction-hypothesis rows, then support immutable counterfactual comparisons.
- **Status:** Ready
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

- **M0:** Pending — replace the operations result with a scored per-action explanation contract.
- **M1:** Pending — project one immutable analysis into timeline data and serve its central frames.
- **M2:** Pending — establish the frontend toolchain, generated API types, and typed client.
- **M3:** Pending — package and serve a production frontend with one API smoke view.
- **M4:** Pending — render the first synchronized three-column timeline for a resolved fixture.
- **M5:** Pending — explain alternatives, incomplete input, impossible input, and diagnostics.
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

### M1 — Timeline projection and frame delivery

- Load and hash-check one completed analysis's exact input and result artifacts.
- Add the strict timeline projection and central-frame selection.
- Add the analysis-scoped immutable stored-frame endpoint and contract tests for foreign, missing,
  and invalid media.

### M2 — Frontend foundation

- Add Node.js 24 LTS to `mise.toml` and scaffold the root `web/` package with React, strict
  TypeScript, Vite, npm, ESLint, Prettier, Vitest, Testing Library, and Playwright.
- Generate and verify the OpenAPI TypeScript declarations and add the typed `fetch` boundary.
- Add the Vite-to-FastAPI development proxy and prove the typed development path with automated
  checks.

### M3 — Production asset boundary

- Add one typed API smoke view and a production Vite build with hashed static assets.
- Package the build with the backend and serve direct loads and refreshes of the analysis entry
  route without a Node.js process.
- Verify development and packaged production modes.

### M4 — Resolved timeline UI

- Render a resolved fixture in the three-column layout with row and hypothesis navigation.
- Add focused browser-level tests for rendering, deep links, and keyboard navigation.

### M5 — Alternative and failure explanations

- Add focused-decision links, hypothesis comparison, score details, and raw JSON disclosure.
- Cover ambiguous, incomplete, impossible, missing-frame, insufficient-evidence, and truncated
  fixtures.
- Complete narrow-width layout, accessible labels, non-color status cues, and local documentation.

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
