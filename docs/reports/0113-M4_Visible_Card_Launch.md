# 0113 M4 — Visible-card launch

M4 moves visible-card detection into the shared **Actions** modal in the recording inspector. The
modal lets the operator select one exact event node revision and detector/model. It displays the
request implementation, processing configuration, extraction policy, and workspace blockers. The
action stays available when the workspace has no compatible input or reports a blocker. Submission
is disabled until the selected exact revision is valid and the backend workspace reports no blocker.

The caller builds a fresh `visible_card_detection` request and submits it through the shared
idempotent job submission hook. It sends the selected event node and revision with its exact branch
policy. An accepted job appears in the retained run details with a shared `/jobs/<id>` link. The
previous inline input/model selectors and launch button are removed. Existing run results and review
controls remain available.

## Scene and calibration disposition

The M0 caller audit found no browser submitter for `proposed_card_scene_creation`; only its API route
and client facade exist. M4 therefore adds no Virtual scenes launch button. It keeps scene review and
editing in their current workflow. M9 must repeat the caller audit and may then remove the unused
client facade. The visible-card detection request accepts exact event inputs and detector settings;
it has no calibration field. Calibration belongs to proposal-scene processing and remains covered
by its API input validation, not this browser launch.

## 0112 coordination

0112 M8 remains unstarted and owns later extraction of processor launch request construction from
`RunControls`. M4 follows M3's sequence: the feature caller owns modal form state, request
construction, and shared submission. When 0112 M8 lands, keep the modal and submit path here and
adapt this caller to use the extracted request builder. M4 does not edit 0112-owned plan or source.

## Verification

- `npm test -- --run src/pipeline/RunControls.test.tsx src/jobs/JobStartActions.test.tsx src/jobs/JobStartInfrastructure.test.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx` — passed, 49 tests. Covers exact historical branch selection, model choice and frozen request, missing event input, incompatible calibration blocker, modal availability, and shared job link.
- `npm run typecheck` — passed.
- `npm run lint -- --no-warn-ignored` — passed.
- `npx prettier --check` on the changed web files and M4 plan/report — passed.
- `npm run test:e2e -- --grep "job start actions fixture"` — passed, 2 browser checks for keyboard/focus, drawer interaction, desktop/narrow layouts, and cancel without submission. Vite reported the existing 500 kB chunk-size advisory.
- Local Markdown-link check across the board, active epic, M0 inventory, and M4 report — passed; `git diff --check` — passed.

No backend, API schema, or generated API contract changed.
