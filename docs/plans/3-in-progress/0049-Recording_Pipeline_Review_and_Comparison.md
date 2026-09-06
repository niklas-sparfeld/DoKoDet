# Recording pipeline review and comparison

## Plan status

- **Summary:** Make the recording workspace show selected generated results and one maintained
  reference per review stage, with simple run, review, and comparison controls.
- **Status:** In Progress
- **Depends on:** 0048 complete
- **Builds on:** Completed 0039, 0040, 0042, and 0045 editors; 0033 analysis diagnostics
- **Supersedes:** The recording UI direction of 0047
- **Outcome:** An operator can run the pipeline on generated or reviewed inputs, maintain one
  reference, and compare retained results without managing review batches or evidence packages.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — add the recording workspace contract and generated client types.
- **M1:** Complete — add the recording pipeline shell, stage summaries, and selectors.
- **M2:** Complete — switch event review to the maintained reference.
- **M3:** Complete — switch visible-card review to the maintained reference.
- **M4:** Complete — switch identity review to the maintained reference.
- **M5:** Complete — add run controls for event, visible-card, and identity processors.
- **M6:** Complete — add observation assembly and reconstruction controls.
- **M7:** Complete — add deterministic event comparison.
- **M8:** Not started — add deterministic visible-card and identity comparison.
- **M9:** Not started — add the comparison workspace and source inspection.
- **M10:** Not started — prove the local workflow and remove obsolete review routes.

### M0 notes — 2026-09-06

The 0048 cutover handoff was checked before implementation. Recording-pipeline resources use the
shipped `/api` prefix. Round-analysis resources remain on `/v1`. The workspace route is a read-only
aggregate over accepted recording, pipeline revision, run, selection, maintained-reference, and
round-analysis stores. It does not create another current-state resource.

| Resource | Shipped route | Client method name |
| --- | --- | --- |
| Recording workspace | `GET /api/recordings/{recording_id}/pipeline` | `getRecordingPipeline` |
| Event runs and selection | `GET|POST /api/recordings/{recording_id}/pipeline/events`; `GET|PUT .../events/selection`; `GET .../events/{run_id}`; `POST .../events/{run_id}/retry`; `GET .../events/{run_id}/result` | `listEventRuns`, `startEventRun`, `getEventSelection`, `updateEventSelection`, `getEventRun`, `retryEventRun`, `getEventResult` |
| Visible-card runs and selection | `GET|POST /api/recordings/{recording_id}/pipeline/visible-cards`; `GET|PUT .../visible-cards/selection`; `GET .../visible-cards/{run_id}`; `POST .../visible-cards/{run_id}/retry`; `GET .../visible-cards/{run_id}/result` | `listVisibleCardRuns`, `startVisibleCardRun`, `getVisibleCardSelection`, `updateVisibleCardSelection`, `getVisibleCardRun`, `retryVisibleCardRun`, `getVisibleCardResult` |
| Visual-identity runs and selection | `GET|POST /api/recordings/{recording_id}/pipeline/visual-identities`; `GET|PUT .../visual-identities/selection`; `GET .../visual-identities/{run_id}`; `POST .../visual-identities/{run_id}/retry`; `GET .../visual-identities/{run_id}/result` | `listVisualIdentityRuns`, `startVisualIdentityRun`, `getVisualIdentitySelection`, `updateVisualIdentitySelection`, `getVisualIdentityRun`, `retryVisualIdentityRun`, `getVisualIdentityResult` |
| Observation runs and selection | `GET|POST /api/recordings/{recording_id}/pipeline/observations`; `GET|PUT .../observations/selection`; `GET .../observations/{run_id}`; `POST .../observations/{run_id}/retry`; `GET .../observations/{run_id}/result` | `listObservationRuns`, `startObservationRun`, `getObservationSelection`, `updateObservationSelection`, `getObservationRun`, `retryObservationRun`, `getObservationResult` |
| Maintained reference | `GET|POST /api/recordings/{recording_id}/pipeline/references/{content_type}`; `PUT .../references/{content_type}/draft`; `POST .../references/{content_type}/complete` | `getPipelineReference`, `createPipelineReference`, `updatePipelineReferenceDraft`, `completePipelineReference` |
| Comparison | Planned in 0049; no shipped route in 0048 | `comparePipelineRuns` |
| Round analysis start | `POST /v1/round-analyses` | `startRecordingAnalysis` |
| Round analysis status | `GET /v1/round-analyses/{analysis_id}` | `getRoundAnalysisStatus` |

## 1. Experience

Keep the recording as the stable owner. Reuse the existing video player, timeline, polygon editor,
identity controls, keyboard shortcuts, and optimistic ordered save queue. Each visual review stage
has two primary views: **Generated** and **Reviewed**. Generated shows the selected processor result.
Reviewed shows the maintained reference and identifies draft work. These views are selection modes,
not a two-result storage limit.

The default next action is visible beside stage progress: Run, Review, Continue review, Compare, or
Open analysis. Put other runs, completed reference revisions, and processor configuration behind
secondary controls. Use stable recording-owned routes for editing. Keep the selected stage, item,
result, and playback position through reload. Do not ask the operator to name a review or choose
among several human reference branches.

Always display the exact input used by a result, such as "Used reviewed events" or "Used generated
visible cards". Default a new run to a completed reviewed input when available. Otherwise use the
selected complete generated input. Show draft, affected-work, and coverage warnings before the
choice. Do not silently change an explicit choice. Send exact revision IDs when the operator starts
a run. Never send a mutable selection pointer in a run request.

If an older result used an earlier reference, show that fact without labeling the result invalid.
If changed evidence affects the current maintained reference, show the affected count and a direct
review action. A processor rerun must not discard human work or create a second maintained reference.

## 2. Review behavior

Use a selected generated result as suggestions over the maintained reference. Accept, correct,
reject, and add operations change the draft only. New suggestions do not overwrite reviewed items.
A rejected suggestion remains in its immutable processor result. It does not need to remain a
prominent row in the normal reviewed view. Completion publishes a new reference revision. Further
corrections continue the same maintained reference.

Event completion includes a full-video pass so missed events can be added. Visible-card completion
records the actual frames inspected, including reviewed empty and unusable frames. Identity review
records usable labels and unresolved source problems. Upstream corrections show affected work and
preserve unchanged items. Show incomplete coverage separately from a processor failure.

Keep the fast controls and save guarantees from 0045. Keep the visible-region semantics from 0040
and the identity controls from 0042. Do not add geometry editing to the identity editor. Link source
problems to the relevant frame and visible-region editor.

Analysis initially uses the existing read-only timeline and counterfactual capabilities. Full
reconstruction correction stays in 0026. This epic does not create reviewed gameplay state by
editing visual observations.

## 3. Comparison behavior

Allow selection of two retained runs and one explicit completed reference revision. Default to runs
that used identical input revisions. Distinguish a processor change from an input change. A
comparison of generated and reviewed upstream input is an upstream-error experiment.

Match events with the declared event timing policy. Match visible-card results on the same resolved
source frame with the declared geometry overlap policy. Compare identity candidates with the same
reviewed visual card identity. Record the matching policy and reviewed scope in every response.
Never match items only because their run-local IDs are equal.

Show matches, misses, extra detections, disagreements, processor failures, and source context.
Missing reference coverage is `not_reviewed`. It is not a false detection or a negative label.
Different frame selections show common covered scope and unmatched coverage separately. Do not show
a paired model-quality delta for runs that used different evidence. Comparison never changes a run,
selection, draft, or completed reference.

The first UI provides inspection and existing metrics. Formal candidate gates and promotion remain
in 0043, 0044, and 0050. Do not add free-form training configuration or a pipeline graph editor.

## 4. Implementation specification

This section fixes the cross-milestone decisions. A milestone can add private helpers. It must not
choose a different owner, route family, URL state model, command lifecycle, or comparison meaning.

### Code ownership

| Boundary | Owner and intended location |
| --- | --- |
| Recording workspace response and HTTP routes | Existing `backend/src/dokodetector_backend/pipeline_api.py` |
| Workspace aggregation and comparison orchestration | Existing `backend/src/dokodetector_backend/pipeline_service.py` |
| Deterministic comparison contracts and functions | `operations/src/doko_operations/pipeline_comparison.py` |
| Generated HTTP types and request methods | Existing `web/src/api/openapi.ts` and `web/src/api/client.ts` |
| Recording pipeline shell and stage summaries | `web/src/pipeline/RecordingPipelineWorkspace.tsx` |
| URL parsing and update helpers | `web/src/pipeline/location.ts` |
| Run forms and status polling | `web/src/pipeline/RunControls.tsx` |
| Comparison selection and result inspection | `web/src/pipeline/ComparisonView.tsx` |
| Recording list and detail composition | Existing `web/src/recordings.tsx` |
| Recording-owned route parsing | Existing `web/src/App.tsx` |
| Event review controls and ordered save queue | Existing `web/src/cardEvents/CardEventEditor.tsx` and `CardEventReviewPage.tsx` |
| Visible-card polygon controls | Existing `web/src/visibleCardReview.tsx` |
| Visual identity controls | Existing `web/src/identityReview.tsx` |
| Read-only reconstruction inspection | Existing `web/src/analysis/AnalysisView.tsx` and `CounterfactualWorkbench.tsx` |

Adapt the three editors in place. Extract components when necessary, but do not copy complete legacy
pages into the new folder. Keep review validation in the 0048 backend adapters. The web client must
not reproduce content validation, coverage rules, matching, or next reference revision logic.

M0 must read `docs/Pipeline_Data_Cutover_Handoff.md`, which 0048 M10 produces. Add a checked cutover
table to this epic under the active M0 notes. Map each required 0048 route and generated client
method to its concrete shipped name. If 0048 used a route prefix that differs from the table below,
change this plan and the generated client in the M0 commit. Do not add a second route as an alias.

### HTTP resource families

Use the versioned route prefix that 0048 ships. Recording-pipeline resources use `/api`; round
analysis keeps its existing `/v1` route. These are the UI-facing resources after the cutover:

| Method and path | Purpose |
| --- | --- |
| `GET /api/recordings/{recording_id}/pipeline` | Load the complete recording workspace summary. |
| `GET /api/recordings/{recording_id}/pipeline/{content_type}/revisions/{revision_id}` | Load one selected data revision for display. |
| `PUT /api/recordings/{recording_id}/pipeline/{content_type}/selection` | Change selected generated or completed-reference revision with `expected_revision`. |
| `POST /api/recordings/{recording_id}/pipeline/{processor_type}/runs` | Start a new run with exact input revision IDs. |
| `GET /api/recordings/{recording_id}/pipeline/runs/{run_id}` | Read one run and its result or failure state. |
| `POST /api/recordings/{recording_id}/pipeline/runs/{run_id}/retry` | Retry the same frozen request after a partial or failed attempt. |
| `GET /api/recordings/{recording_id}/pipeline/{content_type}/reference` | Load the one maintained reference and its current draft. |
| `POST /api/recordings/{recording_id}/pipeline/{content_type}/reference/draft` | Start or resume a draft from an exact base and optional suggestion revision. |
| `PUT /api/recordings/{recording_id}/pipeline/{content_type}/reference/draft/commands/{command_id}` | Apply one idempotent, revision-guarded edit command. |
| `POST /api/recordings/{recording_id}/pipeline/{content_type}/reference/complete` | Complete coverage and publish the immutable reference revision. |
| `POST /api/recordings/{recording_id}/pipeline/comparisons` | Calculate one deterministic comparison without changing stored data. |
| `POST /v1/round-analyses` | Start reconstruction with an exact observation revision and round context. |
| `GET /v1/round-analyses/{analysis_id}` | Read reconstruction status and exact frozen inputs. |

The 0048 derived-view endpoints supply event frames, visible-card source frames, identity crops, and
video snippets. The web app must use those URLs. It must not construct cache paths or read review
batch media routes.

### Recording workspace contract

Add a strict `pipeline-workspace/v1` response. It has `recording_id`, accepted video identity and
duration, and these stages in fixed order:

1. `events`
2. `visible_cards`
3. `visual_identities`
4. `table_observations`
5. `round_analyses`

Each stage summary has:

- its stage key, processor type, output content type, and whether it has a maintained reference;
- input options with exact revision IDs, origin, completion or coverage state, and display label;
- the selection document revision, selected generated revision ID, and selected completed reference
  revision ID when applicable;
- retained runs in reverse creation order, including status, attempt, exact inputs, implementation,
  model, policies, output revision IDs, timestamps, progress, and failure summary;
- reference state `empty|draft|complete`, draft revision, selected completion, coverage summary, and
  affected count when the stage is reviewable; and
- explicit `can_run`, `run_blockers`, `can_review`, `review_blockers`, and comparable run IDs.

The aggregate reads existing 0048 stores. It owns no extra current-state file. Sort equal timestamps
by opaque identifier. A missing optional model identity stays absent. Keep `empty`, active run,
`partial`, `failed`, generated-only, draft, affected, incomplete coverage, and complete as distinct
states. A failed upstream item is not a reviewed empty item.

Derive the primary action in one pure web function with this priority:

1. `Continue review` when a reviewable stage has a draft or affected current work.
2. `Run` when no complete generated result is selected and `can_run` is true.
3. `Review` when a generated result exists, no completed reference exists, and `can_review` is true.
4. `Compare` when a completed reference and at least two comparable runs exist.
5. `Open analysis` when the selected round analysis is complete.
6. `Run again` when the stage can run and no earlier rule applies.

Show the first blocker when no action is available. Keep the complete blocker list in the details
panel. Test the priority table as data. Do not spread action precedence across React components.

### Recording routes and persisted view state

Use these browser paths:

```text
/recordings/{recording_id}
/recordings/{recording_id}/pipeline/{stage}
/recordings/{recording_id}/pipeline/{stage}/compare
```

The detail path redirects only by `history.replaceState` to the selected or first available stage.
Do not perform a network redirect. The path owns `stage`. Query parameters own optional view state:

| Parameter | Rule |
| --- | --- |
| `view` | `generated` or `reviewed`; omit for the stage default. |
| `revision` | Exact displayed historical data revision; omit for the selected pointer. |
| `item` | Selected event, frame, or visible-card identifier. |
| `t_us` | Integer playback position in microseconds. |
| `left` and `right` | Exact run IDs on the comparison route. |
| `reference` | Exact completed reference revision on the comparison route. |

Backend selection pointers persist shared generated and completed-reference defaults. The URL
persists one browser's stage, view, historical override, selected item, playback position, and
comparison choices. Do not use local storage for these values. Update item and playback parameters
with `replaceState`; use `pushState` for stage, view, and comparison navigation. Clamp `t_us` to the
probed video duration. Remove stale `item`, `revision`, or run IDs after the workspace response proves
that they do not exist, and show one concise notice.

### Run controls and polling

A run form submits exact input revision IDs and the complete selectable configuration or policy
values defined by 0048. The primary form exposes only generated or reviewed input origin. A secondary
panel shows retained exact revisions, implementation and model identity, and bounded processor
configuration. Do not expose arbitrary JSON.

Use these processor keys:

- `event_detection` uses the accepted recording video;
- `visible_card_detection` uses one event revision;
- `visual_identity_classification` uses one visible-card revision;
- `observation_assembly` uses compatible event, visible-card, and identity revisions.

Round analysis uses the existing round-analysis service and HTTP lifecycle after the 0048 M7
cutover. It is not stored or retried as a generic processor run. It accepts one table-observation
revision plus explicit round context and rules version. A failed analysis can seed a new request,
but it does not change the failed analysis.

Poll active processor runs and round analyses once per second. Stop on a terminal state, abort on
unmount, and refresh the workspace after termination. Processor `Retry` retains the run ID and frozen
request. Processor `Run again` creates a new run ID. A failed round analysis starts a new analysis
request with copied explicit inputs. Page reload must resume polling. A terminal processor failure,
incomplete review coverage, incompatible inputs, and missing source video need different messages
and actions.

### Reference commands and conflict recovery

Every draft command has `command_id`, `expected_revision`, `kind`, and a content-specific payload.
The server returns the complete reference snapshot and the applied command ID. Use these command
kinds:

| Content type | Command kinds |
| --- | --- |
| `events` | `add_event`, `replace_event`, `remove_event`, `accept_suggestion`, `reject_suggestion`, `set_coverage` |
| `visible_cards` | `set_frame_review`, `accept_frame_suggestions`, `set_frame_empty`, `set_frame_unusable` |
| `visual_identities` | `set_identity`, `accept_identity_suggestion`, `mark_identity_unusable`, `report_source_problem` |

`set_frame_review` sends the complete validated set of visible regions for one resolved frame. A
polygon drag changes local state and sends one command at pointer release. Event UI values can use
seconds, but the API conversion must use integer microseconds. Identity commands reference exact
upstream card, frame, geometry, crop policy, and crop digest identities from the loaded draft.

Keep one ordered queue per draft. Apply commands optimistically and send one at a time. On success,
hydrate the returned snapshot and replay later local commands. On a duplicate command response,
discard the acknowledged queue entry. On HTTP 409, fetch the current draft, discard acknowledged
commands, and replay pending commands in order. Pause the queue and show a conflict only when a
pending command's source item or evidence identity changed. On network or server failure, keep the
queue and offer retry. Completion stays disabled while the queue is active, failed, or conflicted.
Use the backend coverage response as the completion authority.

### Comparison contract

Add strict `pipeline-comparison-request/v1` and `pipeline-comparison/v1` contracts. A request has
`recording_id`, `content_type`, left and right run IDs, one completed reference revision ID, and one
tagged matching policy. Resolve and validate every run and revision before comparison. Both runs and
the reference must use the same accepted video digest and requested content type.

A comparable run has status `complete`, or status `partial` with a validated output revision for the
requested content type. A failed run without a valid output revision is not selectable. Preserve its
failure in the run history.

The response has:

- a deterministic `comparison_id` from the canonical request, three content digests, and algorithm
  version;
- exact left, right, and reference run or revision identities and their upstream input revisions;
- mode `paired_processor` when both runs use identical upstream inputs and policies, otherwise
  `upstream_experiment`;
- normalized reviewed scope, common covered scope, and left-only or right-only evidence scope;
- the full matching policy and algorithm version;
- per-side counts and metrics calculated only inside reviewed coverage;
- an optional paired delta only in `paired_processor` mode; and
- stable source-ordered items with outcome `match|miss|extra|disagreement|failure|not_reviewed|unpaired_input`
  and derived-view source links.

Calculate responses on demand. Do not add a comparison store. Equal requests over unchanged
revisions must return byte-equivalent domain content apart from transport headers.

For events, group by qualified event type and reuse `cardevent.events.match_events`. Use the event
anchor defined by the content schema and an explicit non-negative `tolerance_us`. Report unmatched
reference events as misses and unmatched run events inside full reviewed intervals as extras.

For visible cards, compare only equal resolved-frame identities. Convert reviewed visible regions
to their declared derived boxes. Reuse the existing one-to-one geometry matching primitive with an
explicit IoU threshold and deterministic tie breaks. A run item on an uncovered frame is
`not_reviewed`. Keep successful empty, failed, and uncovered frame outcomes distinct.

For visual identities, match the exact upstream visible card when run and reference use the same
visible-card revision. Otherwise match through equal frame identity and the visible-card geometry
policy before checking the top visual card identity. Report lower-ranked candidate facts for
inspection. Geometry that cannot be paired is `unpaired_input`, not an identity error.

Do not reuse campaign-level comparison artifacts as this response. Extract and reuse pure matching
functions from `cardevent.events`, `visible_card_evaluation.py`, and `visible_card_comparison.py`
where their input meaning matches. Add adapters for the 0048 data-revision payloads.

## 5. Delivery milestones

### M0 — Workspace contract and generated client

Read the 0048 cutover handoff and record the checked route and method map. Add the strict workspace
response models and aggregation method in the fixed backend locations. Add the one `GET` route. It
must read the accepted recording and 0048 stores without writing state. Regenerate OpenAPI and add
typed client methods. Do not change the recording page.

Acceptance:

- video-only, active-run, failed-run, generated-only, draft, affected, incomplete, and completed
  fixtures produce distinct stage facts in fixed order;
- exact input revisions, processor identities, policies, coverage, failures, and selection revisions
  survive the HTTP translation;
- restart produces the same summary from stored resources;
- an invalid or missing selected pointer returns a diagnostic and cannot fabricate a result; and
- the checked 0048 route map names every API used by M1–M10.

Run focused backend pipeline service/API tests, OpenAPI generation and client verification, backend
Ruff, and web type checking.

### M1 — Recording pipeline shell and selectors

Add the recording-owned paths, URL helpers, workspace component, fixed stage navigation, summary
cards, primary-action function, and generated/reviewed selectors. Change `RecordingDetailView` to
compose the new workspace. Keep the recording list behavior. Use the 0048 selection update with its
expected revision when an operator chooses another default revision. Keep history in a details panel.

Acceptance:

- all fixed stage, action-priority, and blocker fixtures render the specified label and action;
- reload and back/forward navigation preserve stage, view, revision, item, and `t_us` state;
- stale URL identifiers are removed with a notice;
- a stale selection update shows the winning selection and does not overwrite it; and
- keyboard navigation, narrow layout, web tests, types, lint, and formatting pass.

### M1 notes — 2026-09-06

Added `RecordingPipelineWorkspace` with recording-owned stage and comparison paths, fixed five-stage
navigation, summary cards, data-driven primary-action priority, generated/reviewed view controls,
historical revision selection, and retained run or analysis history. `RecordingDetailView` composes
the shell for pipeline paths while the recording list and legacy review routes remain unchanged for
the later editor milestones.

The workspace replaces the detail path with `history.replaceState`, keeps stage and query state in
the browser URL, clamps playback time to the accepted video duration, and removes unavailable
revision, item, and comparison identifiers with one notice. Generated default changes use the
shipped 0048 selection route and the current selection revision. A `409` selection conflict reloads
the workspace and shows the winning selection without applying the stale choice.

Focused web fixtures cover the action-priority table, shell composition, URL state, stale state
cleanup, client selection requests, and selection conflict recovery.

### M2 — Event maintained-reference editor

Adapt the existing timeline, screenshots, event table, and `CardEventEditor` to the recording-owned
event reference resource. Replace review creation and named-review navigation with Review or Continue
review. Translate existing editor actions to the fixed commands and integer microseconds. Add full
recording coverage controls and source-linked generated suggestions.

Acceptance:

- keyboard and pointer tests add a missed event, correct an event, accept and reject suggestions,
  remove an event, and record full-video coverage;
- ordered delayed saves, duplicate command responses, network retry, and resolvable revision conflicts
  preserve every command exactly once;
- completion stays disabled for coverage gaps, active saves, failed saves, and conflicts;
- a new event run or selected generated result leaves the draft unchanged; and
- the responsiveness checks retained from 0045 pass.

### M2 notes — 2026-09-06

Added the recording-owned CardEvent maintained-reference editor. The generated view loads one
selected immutable event result as suggestions. The reviewed view loads or starts the one recording
reference and supports timeline and screenshot navigation, event add/correct/accept/reject/remove,
frame nudging, keyboard shortcuts, and full-recording coverage. Editor actions use ordered commands
with command IDs and integer microseconds. The backend stores command digests to replay duplicate
requests without applying an operation twice. Transient saves retry, revision conflicts identify the
first unapplied command and can reload the winning draft, and completion stays blocked until all
commands, event decisions, reviewer fields, and full coverage are ready.

Focused API and editor tests cover command payloads, pointer and keyboard edits, retry and conflict
recovery, generated-result isolation, coverage gating, and completion. Web tests, type checking,
linting, production build, OpenAPI verification, backend reference tests, Ruff, and formatting pass.

### M3 — Visible-card maintained-reference editor

Adapt frame navigation, proposal overlays, polygon editing, and frame outcomes to selected data
revisions and the maintained visible-card reference. Replace batch and item IDs with reference draft,
resolved-frame, and source item identities. Load source images only from the 0048 derived-view API.
Keep the existing geometry validation and pointer controls.

Acceptance:

- accept, reshape, remove, add, reviewed-empty, and unusable flows work without batch creation;
- one pointer gesture emits one complete `set_frame_review` command after release;
- changing the selected detector result leaves reviewed geometry unchanged;
- a changed event frame shows missing coverage and preserves unchanged frame work;
- cold-cache image retrieval works from the accepted video; and
- conflict, keyboard, pointer, type, lint, and component checks pass.

### M3 notes — 2026-09-06

Added `PipelineVisibleCardEditor` to the recording pipeline workspace. The generated view reads the
selected immutable visible-card result. The reviewed view uses one recording-owned maintained
reference with resolved-frame navigation, source-video playback, derived exact-event frame URLs,
proposal overlays, polygon editing, accept, remove, add, reviewed-empty, and unusable actions.

Visible-card edits use the fixed `set_frame_review`, `accept_frame_suggestions`, `set_frame_empty`,
and `set_frame_unusable` commands. The ordered command queue keeps command IDs, retries transient
failures, pauses on revision conflicts, and saves one complete frame review after pointer release.
Completion records visible-frame coverage, including explicit cards, empty, and unusable decisions.
The backend preserves the source item and resolved frame identity and serves recording-owned derived
frames with immutable cache headers. OpenAPI and the typed client include the new result and frame
resources.

Focused editor and API tests, the full web test suite, the production web build, backend tests, API
verification, Ruff, and changed-file formatting checks pass. The package-wide web check still reports
an existing formatting warning in `web/src/visibleCardReview.tsx`, which is outside this milestone.

### M4 — Visual identity maintained-reference editor

Adapt crop review and source context to selected identity results and the maintained identity
reference. Preserve suit/rank controls, keyboard actions, usability decisions, and source-problem
links. Load crops and frames from derived-view URLs. Link geometry problems to the recording-owned
visible-card editor with its stage, item, and playback URL state.

Acceptance:

- a missing or empty prediction remains manually labelable;
- accept, select identity, mark unusable, and report source problem send the fixed commands;
- a geometry or crop digest change shows affected identity work while unchanged cards retain review;
- crop retrieval after cache deletion works;
- completion and dataset readiness display the backend's exact coverage facts; and
- no identity route or component permits geometry edits.

### M4 notes — 2026-09-06

Added `PipelineVisualIdentityEditor` to the recording pipeline workspace. The generated view reads
the selected immutable visual-identity result. The reviewed view uses one recording-owned
maintained reference with source-frame and crop derived views, canonical suit-and-rank controls,
manual labels for empty predictions, identity usability decisions, and source-problem links to the
visible-card geometry stage. Identity review never edits geometry.

Identity edits use fixed `accept_identity_suggestion`, `select_identity`, `set_identity_unusable`,
and `report_identity_source_problem` commands. The ordered command queue keeps command IDs,
retries transient failures, pauses on revision conflicts, and supports rebasing a selected result
so changed geometry or crop digests become affected while unchanged cards retain their decisions.
Completion sends the exact identity-card coverage facts and shows the backend coverage payload and
dataset-readiness state.

The backend now exposes typed visual-identity results and recording-owned derived identity crops.
The crop route re-resolves the accepted video and verifies the stored frame, geometry, crop policy,
and crop digest after cache deletion. OpenAPI and the typed client include the new result and crop
resources.

Focused identity editor, client, reference, and cold-cache API tests pass. The full backend and
web suites, web build, API verification, Ruff, and changed-file formatting checks pass. The
operations suite still reports two existing missing model-improvement skill files outside this
milestone.

### M5 — Visual processor run controls

Add `RunControls` for event detection, visible-card detection, and visual identity classification.
Use exact input options from the workspace response. Show selected defaults first and retain exact
historical revisions in the secondary panel. Add status polling, retry, run-again, progress, terminal
failure, and actual-input displays.

Acceptance:

- an operator runs event detection from video, detection from generated and reviewed events, and
  classification from generated and reviewed visible cards;
- every created request contains exact input IDs and full implementation, model, configuration, and
  policy values;
- reload resumes active polling and stops after a terminal state;
- retry retains the run ID and frozen inputs, while run-again creates a new run ID; and
- missing video, incompatible input, partial result, and processor failure have different messages.

### M5 notes — 2026-09-06

Added `RunControls` to the recording workspace for event detection, visible-card detection, and
visual identity classification. The form uses the selected generated or reviewed upstream revision,
offers retained historical revisions in a secondary panel, and displays the exact input and frozen
implementation, model, configuration, and policy values after a run starts. Active runs poll once per
second and resume from the workspace after reload. Retry keeps the run ID and frozen request. Run
again creates a new run ID. Terminal, partial, missing-video, and incompatible-input messages remain
distinct. The visible-card adapter now accepts and removes its explicit event-revision selector
before strict request validation.

### M6 — Observation assembly and reconstruction controls

Add run controls for observation assembly and round analysis. Filter the input selector to compatible
revision sets supplied by the backend. Require explicit round context and rules version before round
analysis. Connect the selected completed analysis to the existing diagnostic timeline and
counterfactual workbench. Keep advanced context fields in the secondary panel.

Acceptance:

- an operator assembles observations from one exact compatible event, visible-card, and identity set;
- incompatible source, event, frame, card, or geometry lineages cannot be submitted;
- an operator starts reconstruction from one exact observation revision and explicit round context;
- each result displays its actual inputs and a stable recording-owned analysis link;
- video-only fixture analysis does not read or require an evidence package; and
- existing timeline and counterfactual component tests remain valid.

### M6 notes — 2026-09-06

Added backend-approved compatible revision triples and preflight lineage validation for observation
assembly. Added recording-workspace controls for observation assembly and explicit round
reconstruction, including exact inputs, polling, retry and run-again behavior for assembly,
secondary round context and search fields, rules version, actual input display, and retained
analysis links. A completed analysis opens the existing diagnostic timeline and counterfactual
workbench on the recording-owned pipeline route. Pipeline analyses use table-observation artifacts
only and do not require evidence packages.

### M7 — Event comparison

Add the shared comparison request, response, scope, item, and policy contracts. Implement event
matching and the on-demand comparison service/API path. Keep the web work to typed client generation.
Do not add comparison UI or visible-card matching.

Acceptance:

- fixtures cover paired processor runs, changed upstream input, matches, misses, extras, failures,
  partial reviewed intervals, and unreviewed intervals;
- the declared event type and tolerance determine one-to-one matching with stable tie breaks;
- counts and metrics exclude unreviewed intervals;
- paired delta is absent for an upstream experiment; and
- equal requests return equal comparison IDs and byte-equivalent domain responses.

### M7 notes — 2026-09-06

Added shared `pipeline-comparison-request/v1` and `pipeline-comparison/v1` contracts for event
comparisons. The backend resolves two complete or partial retained event runs with valid outputs and
one completed maintained reference, validates their recording video and lineage, and calculates the
result on demand. Event matching groups qualified event types and uses the declared anchor and
microsecond tolerance with maximum-cardinality, minimum-error, stable tie breaks. Reviewed, common,
and side-only coverage is normalized. Metrics exclude unreviewed intervals. Paired runs expose a
right-minus-left delta; changed upstream inputs use `upstream_experiment` with no paired delta. The
recording-scoped API route and typed client method do not create comparison state or UI.

### M8 — Visible-card and identity comparison

Extend the comparison implementation for visible cards and visual identities. Add adapters from the
0048 payloads to the existing geometry matching primitives. Apply the fixed reviewed-scope and
upstream-experiment rules. Do not add UI.

Acceptance:

- visible-card fixtures cover matched, missed, extra, empty, failed, unreviewed, and unequal-frame
  cases at IoU boundary values;
- identity fixtures cover exact upstream cards, geometry-based pairing, correct top candidate,
  disagreement, empty candidates, source failure, and unpaired geometry;
- disconnected reviewed polygons use the declared derived box policy;
- different frame selections expose common and unmatched scope without scoring uncovered frames; and
- deterministic ordering and comparison IDs survive input-order changes.

### M9 — Comparison workspace

Add the recording-owned comparison route and `ComparisonView`. Select two terminal runs and one
completed reference. Initialize the URL with the newest compatible pair. Show the mode, exact inputs,
matching policy, reviewed scope, summary, and source-ordered outcome list. Seek the recording video
or open the derived frame or crop when an operator selects an item.

Acceptance:

- event, visible-card, and identity fixtures render every specified outcome and source action;
- changing left, right, or reference updates the URL and comparison without changing backend
  selections;
- an upstream experiment has no paired-quality claim;
- `not_reviewed`, processor failure, empty, miss, extra, and disagreement use distinct text; and
- back/forward navigation, loading, error, narrow-layout, type, lint, formatting, and component tests
  pass.

### M10 — Workflow proof and cleanup

Exercise one fixture recording from accepted video through selected runs, the three maintained
references, observation assembly, reconstruction, comparison, analysis, and dataset readiness. Use
the 0048 cutover inventory to remove obsolete review-batch creation routes, old batch-owned web
paths, duplicate current-state ownership, and package update controls from this workflow. Keep pure
validators and adapters that the new services use. Retain the app's packaging and upload showcase.
Do not add compatibility routes, stores, or data migrations.

Acceptance:

- browser tests cover fresh video, manual review, generated suggestions, reruns, upstream correction,
  cold caches, failed jobs, reload, and save conflicts;
- file-access tracing proves that the workflow reads no evidence-package media or manifest;
- no active web link or generated client method targets a removed review-batch route;
- relevant web, backend, operations, analyzer, engine, generated API/client, formatting, and local
  link checks pass through the project toolchain; and
- one bounded real operator exercise is recorded when local recordings are available. Report data
  gaps without a quality claim. A missing real corpus does not keep fixture-proven work open.

## 6. Handoff

After M10, mark this epic complete and reassess 0043 and 0050 with measured data coverage. Do not
start either epic only because this UI is complete. Epic 0044 remains blocked until 0043 locks a
passing candidate.
