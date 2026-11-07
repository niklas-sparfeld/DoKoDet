# 0113 M9 — Launch cleanup

## Result

The M0 inventory was re-audited against browser source and the rendered recording and analysis
routes. All seven current browser starts open the shared job-start modal. Inspection, editing,
review and apply controls remain separate. The recording workspace keeps result history and exact
input details. The analysis workspace keeps correction editing and result comparison.

## Current browser-start owners

| Action                         | Browser owner and request route                                                                                              | Shared execution owner                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Event processing               | `RunControls` event action; `event_processing` through `POST /api/jobs`                                                      | `useJobSubmission`, then shared Jobs state                                       |
| Visible-card detection         | `RunControls` visible-card action; `visible_card_detection` through `POST /api/jobs`                                         | `useJobSubmission`, then shared Jobs state                                       |
| Visual identity classification | `RunControls` identity action; `startVisualIdentityRun` posts to `/api/recordings/{recording_id}/pipeline/visual-identities` | The shared modal owns launch input; pipeline workspace retains processor results |
| Table observation assembly     | `ObservationRunControls`; `table_observation_assembly` through `POST /api/jobs`                                              | `useJobSubmission`, then shared Jobs state                                       |
| Round analysis                 | `RoundAnalysisControls`; `round_analysis` through `POST /api/jobs`                                                           | `useJobSubmission`, then shared Jobs state                                       |
| Complete pipeline              | `AutomatedPipelineControls`; preflight and start at `/api/recordings/{recording_id}/pipeline/runs`                           | The modal retries one frozen idempotent request; Jobs owns status                |
| Counterfactual calculation     | `CounterfactualWorkbench`; `counterfactual` through `POST /api/jobs`                                                         | `useJobSubmission`, then shared Jobs state                                       |

`JobActions` in Jobs is the only browser job-retry owner. It calls `retryJob` with a fresh
idempotency key and does not expose an editable launch request. `JobStateProvider` owns shared job
status and polling. Launch controls do not poll for job status. Workspace result reads and analysis
detail reads remain for inspection.

## Caller audit and removals

The source audit found no non-test component caller for these browser client methods: direct
visible-card start, proposed-card-scene start, observation start, calibration-refinement start, and
legacy recording-analysis start. It also found no browser caller for the automated-pipeline run
reader. M9 removed those client methods, their request path helpers, and their stale client tests.
The specialized visible-card and observation endpoints and the other server routes remain intact.

No UI caller exists for `event_import`, `proposed_card_scene_creation`, or `calibration_preview`.
Keep all three registered job capabilities and backend APIs for agent or import tooling. Keep
proposed-scene inspection, calibration evidence editing, refinement editing, and the calibration
apply-validity gate. M9 adds no browser action for these job types.

The replaced compact-form prop and CSS, old processor heading, and unused inline form styles are
removed. Active modal fields and their `pipelineRunSelector` and `pipelineContextGrid` styles stay.
No duplicate active launch button remains. `0112` remains the owner of request-builder extraction;
the active modal callers still own form state, request construction and submission.

## Verification

- `npm test -- --run src/api/client.test.ts src/pipeline/RunControls.test.tsx src/pipeline/ObservationAndAnalysisControls.test.tsx src/pipeline/AutomatedPipelineControls.test.tsx src/analysis/CounterfactualWorkbench.test.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx` — 6 files and 49 tests passed.
- `npx playwright test tests/e2e/job-start-actions.spec.ts tests/e2e/pipeline-cutover.spec.ts tests/e2e/pipeline-lineage-workspace.spec.ts --grep 'job start actions fixture|opens fresh accepted video|fact-complete pipeline|round analysis uses the shared frame' --reporter=line` — 5 passed. The round-analysis route covers counterfactual editing, modal cancel, exact request submission and the job link.
- `npm run typecheck` — passed.
- `npx eslint` on the changed web source, test and inspector files — passed.
- `npx prettier --check` on changed web source, test and CSS files — passed.
- `npm run verify:api` — passed; generated API matched. The exporter printed the existing optional `processor_run_catalog_skipped` notice because its temporary operations root is unavailable.
- Source caller audit with `rg` found no browser references to the removed launch/poller methods and confirmed the seven current owners above.
- Local Markdown-link check across the board, active epic and this report — passed.
- `git diff --check` — passed.

The broad Prettier check reports pre-existing style warnings in the active epic and plan board.
The report itself is formatted. No backend route, generated API contract, or persisted data changed.

No backend route, generated API contract, or persisted data changed.
