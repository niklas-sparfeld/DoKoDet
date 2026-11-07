# 0113 M6: Observation and analysis launch

## Result

Observation assembly and round analysis now start from the shared job-start modal in the recording
workspace inspector. The old inline start forms and their feature-specific execution panels are gone.
The existing Jobs UI owns execution status and polling.

The observation modal shows each exact input role: events, visible cards, and visual identities. It
shows the compatible set, node and revision IDs, revision policy, implementation, model,
configuration, and extraction policy. It blocks missing or malformed sets. It submits the same
processor request fields used by the existing endpoint.

The round-analysis modal shows one exact observation node revision, game ID, round ID, session ID,
four active player IDs in seat order, dealer, first-trick leader, rules version, search limits, and
optional correction revision IDs. Round facts start blank. The form blocks missing fields, duplicate
players, invalid IDs, a leader outside the player set, missing rules, and invalid search limits. It
submits the exact observation ref and entered facts.

Both actions use the shared job submission hook. An accepted job displays the shared receipt link.
A failed response with uncertain acceptance keeps the modal open, freezes its inputs, and retries the
same request with the same idempotency key and payload. The launch components reset when recording
navigation changes, so an open form cannot move to another recording.

## API check and decision

The current contracts support the M6 acceptance criteria without a backend change:

- The registered `table_observation_assembly` Job Manager participant freezes the request and
  validates all three exact canonical node references against recording, content type, revision, and
  current-head policy.
- The registered `round_analysis` participant validates the exact table-observation node reference,
  recording context, round facts, rules, and search limits before it stores the analysis inputs.
- `/api/jobs` accepts either existing job type with an idempotency key and returns a `JobDetail`.
  The shared submission hook reuses the key and exact payload after an uncertain response.
- The accepted job ID links to the shared Jobs UI. No feature-specific poller was added.

The observation and round-analysis feature endpoints return domain status records instead of the
shared job receipt. M6 therefore uses `/api/jobs` with the existing registered request types. This
keeps the frozen request and job lifecycle contracts intact.

## Checks

- `npm test -- --run src/pipeline/ObservationAndAnalysisControls.test.tsx` — passed (6 tests).
- `npm run typecheck` — passed.
- `npx eslint src/pipeline/ObservationRunControls.tsx src/pipeline/RoundAnalysisControls.tsx src/pipeline/ObservationAndAnalysisControls.test.tsx` — passed.
- `npx prettier --check src/pipeline/ObservationRunControls.tsx src/pipeline/RoundAnalysisControls.tsx src/pipeline/ObservationAndAnalysisControls.test.tsx` — passed.
- `npx playwright test e2e/pipeline-lineage-workspace.spec.ts -g "round analysis uses the shared frame" --reporter=line` — passed. The fixture now passes `/@vite/` and `/@react-refresh` modules to the local dev server; previously its catch-all route returned 404 for these modules, leaving the page empty.
- The component fixtures cover exact multi-input refs, an incomplete set blocker, missing round facts,
  ambiguous/incomplete role sets, four distinct players, a valid fact request, exact observation
  revision, accepted job receipt, and same-key/same-payload retry after uncertain acceptance.

## Limits

No known M6 acceptance gap. The complete-pipeline action, calibration and counterfactual actions,
final launch cleanup, and full workflow closure remain in M7–M10. Epic 0112 client and `RunControls`
extraction remain separate work; M6 changed no 0112-owned files.
