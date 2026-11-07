# 0113 M0 — Browser launch inventory

Inventory checked at `21a1146b0` on 2026-11-07. Registry source: `backend/src/dokodetector_backend/app.py`; browser sources: `web/src/pipeline/RunControls.tsx`, `ObservationRunControls.tsx`, `RoundAnalysisControls.tsx`, `AutomatedPipelineControls.tsx`, `analysis/CounterfactualWorkbench.tsx`, and shared Jobs components. The frontend client has older start methods without active component callers; they are not counted as browser submission paths.

## Active browser submissions

| Call site / job type | Route and submitted inputs | Defaults and validation | Current owner → replacement owner / removal |
| --- | --- | --- | --- |
| `RunControls.startProcessorRun` — `event_processing` | `POST /api/jobs`; context recording ID; request contains run ID, accepted recording video, processor implementation/model/configuration and extraction policy. | Run ID is generated. Defaults: CardEventNet `file-v1`, exact-event extraction. Backend freezes source video digest and validates the frozen request. Accepted video is fixed context, shown as such. | `RecordingWorkspaceInspector` → M3 shared Actions/modal; remove inline launch form in M9. |
| `RunControls.startProcessorRun` — `visible_card_detection` | `POST /api/jobs`; context recording ID; request contains run ID, exact selected input node/revision, processor, model/provider, configuration and extraction policy. | Run ID generated; provider/model variant defaults to Gemini. Exact input and model variant are displayed. Disabled without compatible input; backend validates frozen request. | `RecordingWorkspaceInspector` → M4 shared Actions/modal; remove inline launch form in M9. |
| `RunControls.startRun` — `visual_identity_classification` | `POST /api/recordings/{recording_id}/pipeline/visual-identities`; request includes run ID, exact crop input ref/kind, processor, model/provider, crop policy and processing configuration. | Run ID generated. Defaults: local classifier; predicted-region crop policy except reviewed input uses oracle-visible-region; PPM output. Requires one exact crop geometry input. Proposal-derived virtual cards force local classification and are identified as unreviewed evidence. | `RecordingWorkspaceInspector` → M5 shared Actions/modal; remove inline launch form in M9. Classification is computation. Identity accept/reject controls in `PipelineNodeVisualIdentityEditor` remain human decisions and are not launch controls. |
| `ObservationRunControls.startRun` — `table_observation_assembly` | `POST /api/recordings/{recording_id}/pipeline/observations`; request includes run ID, exact event/visible-card/identity node-revision refs, implementation, model, configuration and extraction/crop policies. | Run ID generated; assembler v1, empty config, exact-event extraction, null model/crop policy unless copied from the latest run. Requires one backend-compatible input set; none means disabled with blocker. | `RecordingWorkspaceInspector` → M6 shared Actions/modal; remove inline launch form in M9. |
| `RoundAnalysisControls.startAnalysis` — `round_analysis` | `POST /v1/round-analyses`; body: analysis ID, recording/round/session IDs, exact observation node/revision, game ID, four active players, dealer, first-trick leader, rules version, correction-constraint revision IDs, search limits. | Analysis ID generated. Observation defaults to selected generated revision, then first input option. Recording supplies game/round/session defaults; players, dealer, leader and rules are blank until loaded from a prior analysis or entered. Search defaults: 1 missing play, 256 hypotheses, 250000 nodes. Validation requires all round facts, four distinct players, leader in player set, valid identifiers, positive search limits and a stored observation revision. | `RecordingWorkspaceInspector` → M6 shared Actions/modal; remove inline form in M9. |
| `AutomatedPipelineControls.start` — `automated_pipeline` parent | `POST /api/recordings/{recording_id}/pipeline/runs`; idempotency key, rules version, search limits, stage configurations; backend derives session/round facts and freezes pipeline input. | UUID idempotency key; rules `v1`; limits 1/256/250000. Stage provider/config comes from latest compatible runs with local fallbacks. Existing preflight blocks missing accepted video or round facts and reports blockers. | `RecordingWorkspaceInspector` → M7 shared Actions/modal; remove separate complete-pipeline preflight/start UI in M9. |
| `CounterfactualWorkbench.runCounterfactual` — `counterfactual` | `POST /api/jobs`; context analysis ID; body includes counterfactual ID, source analysis/input/result hashes, excluded observations/cards, identity overrides and candidate-probability overrides. | ID generated; source/hash values fixed from selected analysis. Button disabled with no changes, invalid probability, or all observations excluded. Backend checks hashes and constraints. | `CounterfactualWorkbench` → M8 shared Actions/modal; remove inline launch controls in M9. Preserve draft editing and result comparison. |

Shared job retry is exposed by `JobActionControls` (`web/src/jobs/JobComponents.tsx`) from job details and Jobs views. It posts to `POST /api/jobs/{job_id}/retry` with a fresh idempotency key and empty body. The Job Manager owns retry policy, frozen inputs and history. Keep this retry in Jobs; do not expose editable inputs or a second launch form. `JobListView` “Retry” retries a failed list read, not a job.

## Registry dispositions

Production registry at this revision has ten entries:

| Type | Browser disposition / route | Owner |
| --- | --- | --- |
| `event_processing` | Active browser launch, `/api/jobs` (above). | M3 |
| `event_import` | No browser submitter. Generic job API only; agent/import tooling disposition, no UI in this epic. | Retain registry; no UI/removal planned. |
| `visible_card_detection` | Active browser launch, `/api/jobs` (above). | M4 |
| `proposed_card_scene_creation` | No active browser submitter. A client method and route exist, but no component invokes it. Preserve as API/agent capability; do not add a new UI in this epic. | M4 inventory covers scene actions; no launch integration absent a browser caller. Remove unused client facade only in M9 if caller audit remains clear. |
| `visual_identity_classification` | Active browser launch through the pipeline-stage route (above). | M5 |
| `table_observation_assembly` | Active browser launch through the pipeline-stage route (above). | M6 |
| `round_analysis` | Active browser launch through `/v1/round-analyses` (above). | M6 |
| `automated_pipeline` | Active browser launch through recording pipeline route (above); creates managed child jobs. | M7 |
| `calibration_preview` | No current browser submitter. Generic `/api/jobs` contract accepts a proposal revision and draft ID, then freezes a snapshot. Calibration refinement start/edit/apply routes are separate short commands and must retain their review/apply authority. | M8 owns calculation if a caller appears; no UI launch to remove now. |
| `counterfactual` | Active browser launch through `/api/jobs` (above). | M8 |

The client exposes unused `startVisibleCardRun`, `startProposedCardSceneRun`, `startCalibrationRefinement` and `startRecordingAnalysis` methods. No non-test browser component calls these methods. `createRoundAnalysis` is the active round path. M9 removes only after confirming no caller was added. No conditional classification start exists inside an approval action: event/visible-card/identity inference has explicit RunControls submission; review editor accept/reject actions only write review decisions. Jobs retry remains with 0110.

## Shared interaction contract

- Desktop: retain the current right-hand inspector/sidebar slot in `RecordingWorkspaceInspector`. Add one Actions group with a consistent button size, spacing and “<work>…” labels. A complete-pipeline button stays distinct from a stage action. Keep the center and lineage browsing unchanged.
- Narrow view: expose the same Actions group in an accessible right-sidebar drawer. Use one modal over the drawer, with one focus trap and return focus to the invoking action. The drawer stays operable when output or prerequisites are absent.
- Modal: explain work and outputs; show fixed context readably; expose required exact refs, model/provider and options as labeled controls; show prerequisites and availability; keep advanced optional fields collapsible. Present a final summary and Start/Cancel in the same modal. Opening it submits nothing.
- Empty: explain the action and show missing inputs or a link to their source workspace; leave the action discoverable.
- Loading: label which choices or availability are loading; do not submit stale dependent selections.
- Invalid: keep values, focus the first invalid required field, and show actionable errors beside it and in a summary.
- Submitting: show the action in progress and disable duplicate submission. On uncertain response, reconcile with existing acceptance/idempotency behavior before allowing resubmit.
- Accepted: close modal, preserve inspected branch/frame, and provide a persistent shared Jobs link. Closing does not cancel work.
- Failed: keep values and actionable backend error visible, allow correction/retry only after acceptance is known, and do not discard review or working state.

Required inputs must be selectable in the modal or shown as fixed context with their source and exact identity. This includes accepted source video, all input roles/revisions, provider/model, and all required round facts. Missing facts must block submission; never infer round facts. Review acceptance, calibration apply, edits, and output selection remain explicit domain actions outside the launch modal.

## Layout inspection and checks

Inspected the local `RecordingPipelineWorkspace` fixture and the current desktop inspector composition. The inspector mounts compact run controls at the right-hand slot. The shell CSS switches at 900 px and 600 px; narrow mode stacks the top bar and reduces content padding. The existing fixture does not exercise viewport breakpoints, so M1 must add/inspect desktop and narrow render fixtures for sidebar access and focus return. No existing modal or drawer needs migration.

Focused checks for this milestone: registered-type vs report reconciliation; browser caller grep (`enqueueJob`, `start*Run`, `createRoundAnalysis`, `startAutomatedPipelineRun`, retry controls); local fixture/CSS inspection at desktop and narrow breakpoints; Markdown links to the moved epic and report; `git diff --check`. Future caller-focused tests are named in each owner row and the existing M10 completion checks.

## 0112 coordination

0112 remains In Progress and M8 is not started. Its M8 owns extraction of processor launch request construction from `RunControls`; 0113 M4/M5 own launch integration. Before either launch-boundary implementation begins, compare the surviving component/request owner and agree the boundary. 0113 M0 is inventory only and made no implementation change to 0112-owned paths. Keep the 0112 handoff and work unchanged until that sequencing point.
