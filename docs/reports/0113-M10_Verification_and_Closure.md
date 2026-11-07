# 0113 M10 — Verification and closure

## Result

M0–M10 are complete. All seven current browser starts use the shared Actions and modal flow:
event processing, visible-card detection, visual identity classification, table-observation
assembly, round analysis, complete pipeline, and counterfactual calculation. The focused component
fixtures exercise each action's exact request and accepted job receipt. The deterministic browser
routes verify the shared shell, complete-pipeline and counterfactual starts, and Jobs result
navigation after reload.

Jobs remains the only owner of job status, polling, retry and result links. The M9 caller audit
found no active superseded launch path. `event_import`, `proposed_card_scene_creation`, and
`calibration_preview` have no browser caller and remain registered agent/API capabilities. This
epic adds no UI for them.

## Verification

- `npm test -- --run src/api/client.test.ts src/jobs/JobStartActions.test.tsx src/jobs/JobStartInfrastructure.test.tsx src/pipeline/RunControls.test.tsx src/pipeline/ObservationAndAnalysisControls.test.tsx src/pipeline/AutomatedPipelineControls.test.tsx src/analysis/CounterfactualWorkbench.test.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx` — 8 files, 59 tests passed. Coverage includes all seven starts, exact and multi-input refs, empty/missing inputs, ambiguity, unavailable models, stale choice responses after navigation, submission rejection, uncertain acceptance, duplicate submission, and accepted job links.
- `npx playwright test tests/e2e/job-start-actions.spec.ts tests/e2e/pipeline-cutover.spec.ts tests/e2e/pipeline-lineage-workspace.spec.ts --grep 'job start actions fixture|opens fresh accepted video|fact-complete pipeline|round analysis uses the shared frame' --reporter=line` — 5 passed. The shared shell checks keyboard opening, Escape and focus return, desktop and narrow layouts, drawer access, cancel without submission, and the accepted video/pipeline/round-analysis routes. The pipeline route checks an accepted parent job link; the round-analysis route checks exact counterfactual inputs, accepted link, and saved selection after reload.
- `npx playwright test tests/e2e/jobs.spec.ts --grep 'history pagination and browser navigation keep the exact job and result link' --reporter=line` — 1 passed. It follows the exact job and result link through reload, back and forward navigation.
- `npm run typecheck` — passed.
- `npm run lint -- --no-warn-ignored` — passed.
- `npm run verify:api` — passed; generated API matches. The exporter printed the existing optional `processor_run_catalog_skipped` notice because its temporary operations data root is unavailable.
- Prettier — the new M10 report passes. The existing board and plan do not pass at baseline: their `HEAD` versions also differ from Prettier output (264 and 34 diff lines). No broad reformat was applied.
- M9 source caller audit and registry reconciliation — passed; Jobs is the only job retry/status/polling owner. The inventory and agent-only dispositions remain in [M0](0113-M0_Launch_Inventory.md) and [M9](0113-M9_Launch_Cleanup.md).
- Local Markdown-link check across the board, closed epic and M0–M10 reports — passed. `git diff --check` — passed.

## Operator handoff

Start work from the **Actions** group in the right sidebar. Each of the seven browser actions opens
the shared modal. Confirm the exact input revisions and required facts shown there before starting.
After acceptance, follow the job link into Jobs. Use Jobs for status and retry. Open a result through
its exact result link. Review, edits, calibration apply, and counterfactual correction remain
separate actions.

The launch inventory and removal record is in [M0](0113-M0_Launch_Inventory.md) and
[M9](0113-M9_Launch_Cleanup.md). `event_import`, `proposed_card_scene_creation`, and
`calibration_preview` remain agent/API capabilities without browser actions.

## Run handoff

Requested: 11 milestones. Completed: 11 (M0–M10). Remaining: 0. No next milestone. No blocker.
