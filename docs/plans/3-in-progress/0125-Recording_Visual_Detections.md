# Recording visual detections

- **Status:** In Progress
- **Depends on:** [0124](../5-closed/0124-Recording_Folders_and_Events.md) closure and stable recording/event references.
- **Outcome:** Generate or annotate alternative visual detection sets, edit their segments, and reopen them from the recording folder.
- **Origin:** [Recording data storage](../../RecordingDataStorage.md).

## Problem and success

Visible-card content is embedded in node revisions and mixes visible evidence with execution
failure. Store concrete detections linked to exact events/frames, with segments belonging to the
detected object. Preserve visible regions, card sides, pile regions, ignore regions, examined
coverage, human work, and independent alternatives. One object's disconnected polygons remain one
object. Reuse existing geometry algorithms and coordinates.

Use the recording-owned detection-set layout. Human and detector content share the same concrete
contract. Empty examined frames are explicit coverage facts; execution failure remains in jobs.
Keep exact frame identity with evidence; do not build a frame database. HEAD selects exact saved
detection sets. Existing nodes cannot provide this folder structure without a domain conversion;
no new generic resource layer is needed.

Non-goals: detector quality, model training, virtual-card fitting, calibration/classification
format conversion, caches, and replacing all review subsystems. Preserve the selected workflow's
human decisions and resumable state; do not create a universal review contract.

## Finite source owners

Backend: `visible_card_pipeline_service.py`, `visible_card_node_draft.py`,
`visible_card_review_store.py`, `frame_review_bindings.py`, `frame_review_workflow_store.py`,
`pipeline_node_reviews.py` and detection branches of edit/selection/lineage/workspace adapters.
Exact-input consumers: `proposed_card_scene_pipeline_service.py`, `calibration_refinement_service.py`,
`visual_identity_pipeline_service.py`, and `observation_pipeline_service.py`.
Content: `table_evidence_analyzer/pipeline_data.py` geometry/detection portions and exact-frame
resolution at the existing frame resolver. Web: detection editor/review and API client call sites
identified in the M0 source map. No consumer format conversion outside detections is authorized.

## Validation and cutover boundaries

0124 M6 proved that the detector reads the selected event-set ID, version, and digest, and
reopens its output after restart. That dependency is complete. Its seven recordings without event
nodes and 203 outputs without saved parent facts are not proof of detection ancestry. Do not
invent references during conversion. Inventory detection-specific cases and report unavailable
inputs before activation.

The existing node authority cannot satisfy the requested recording-folder layout: the detector
publishes `visible-card-data/v2` node revisions and selects them in the node selection store.
The 0115 cutover fixture contains a `data-revision/v1` manifest and v2 content with event coverage,
source video digest, frame identity and polygon components. The parser also accepts v1; the
`test_visible_card_data_migration.py` fixture exercises it. Review and unfinished work have
separate `visible-card-review/v1`, `pipeline-review/v1`, `visible-card-node-draft/v1`,
`frame-review-node-bindings/v1` and `frame-review-workflow/v1` records. These are representative
schemas, not a count or a claim that every retained record has been inventoried. M3 must inspect
the actual retained inventory and account for each encountered schema and unresolved input.

The detector is a writer, and calibration refinement can also publish visible-card revisions and
holds reflow draft context. The scene and observation services read exact node revisions;
classification, comparison, the workspace, node editing/review, and the 0096 frame-review queue
also depend on node references. The browser editor is
`web/src/visibleCards/PipelineNodeVisibleCardEditor.tsx`; its workspace and frame-review entry are
`web/src/pipeline/RecordingPipelineWorkspace.tsx`, `backend/.../frame_review_api.py` and
`frame_review_bindings.py`. M1 must freeze its exact API/client owners before edits. M2 must cover
the calibration writer and the comparison and frame-review entry points as well as the named
consumers. Preserve the frozen 0096 queue and its exact target and progress, or keep a bounded
explicit bridge until that queue finishes. Do not claim old-path removal while an active writer or
reader still needs it. Record each replacement, bridge, and verification in the M3 audit.

## Closure check

Real API/browser: select event evidence, run a deterministic detector, save a detection set, edit
one object's segments, keep another alternative, review geometry, select and reopen after restart.
Include multi-segment occlusion, zero detections with coverage, pile/ignore geometry, and absent
evidence. Show one downstream scene/classifier consumer opening the exact saved detection version
with old detection-node reads disabled. Historical inputs survive later edits.

Rehearse conversion of named retained detector/review schemas in disposable storage. Verify
coordinates, IDs, frame/event references, decisions, unfinished review, and current selections.
Preserve recovery evidence. Test save/HEAD interruption and conflicting edits separately from
concurrent reads. Run affected detection/frame-review/API/web tests and static/generated API
checks. Retain 0123's bounded list checks. No model-quality claim is required for storage closure.

## Milestones

| Milestone | Observable result and commit boundary | State |
| --- | --- | --- |
| M0 | Concrete detection-set storage; real API save/open of exact frame/object/segment evidence | Complete |
| M1 | Existing detector and browser segment editor/review use the same contract; restart proof | Complete |
| M2 | Convert exact-input consumers and calibration reflow writer; preserve comparison and frame-review access | Complete |
| M3 | Retained-data rehearsal, default detection cutover, replaced-path removal, and qualification | Not started |

### Assignment preparation

M0 adds one concrete detection-set storage contract and a save/open API. Use
`recording_folder_store.py`, the event-set store/API as the publication pattern, and the existing
frame and geometry validators. Store immutable versions at the folder paths in the storage
convention. Set metadata identifies recording, set, version, origin, source and producer facts,
exact optional event-set references including digest, and explicitly examined frames. A frame
records its exact source-frame identity and optional event IDs; a direct frame need not have an
event. Each detection has a frame-local object ID, kind, and ordered, separately identified polygon
segments in source-image coordinates. Preserve card-side facts and explicit pile and ignore
regions. Empty examined frames remain present; an absent or failed frame is not empty coverage.
Reject duplicate IDs, invalid geometry, mismatched recording/source or event references, and
version overwrite. Keep execution failure in jobs. Save and open need not select a version; leave
existing node selection authoritative until M1 specifies the actual selection cutover. Do not add
a second publication authority or a review store in M0. M1 specifies the typed local review and
draft layout against the existing editor and retained facts before implementing it.

M0 owners: a concrete backend detection-set store and API, their app registration and API models,
the existing recording/event stores and frame/geometry validators, and focused API/store tests.
The commit contains those changes, evidence, and plan/board updates. Prove save and exact reopen
through a real API with disposable persisted data and restart, including two disconnected segments
on one object, an examined empty frame, pile/ignore geometry, and a direct frame. Verify immutable
versions, invalid and missing evidence, and interrupted save; run affected backend tests, Ruff,
generated API checks, and `git diff --check`. M0 does not convert the detector, browser, HEAD,
review, or downstream paths.

Specify M1 before assignment, then M2/M3 after the browser proof. Keep qualification in M3. If a
consumer needs a broader new representation, retain its current algorithm with a small explicit
input conversion; do not silently convert the next resource type in this epic.

### M1 assignment

Launch the existing detector for an exact event set, open its saved detection set in the recording
workspace, edit and save one object's segments, record a geometry review, and reopen the exact
saved content and review after backend restart. Keep an earlier version unchanged. Use a
deterministic detector stub in the real-backend browser check. Failed frame work remains in jobs;
only examined frames enter detection coverage. Do not infer missing event or frame evidence.
M0 save/open remains the version authority. A direct exact set/version link is sufficient for this
proof; leave node selection and downstream node readers in place until their cutover.

Owners: `visible_card_pipeline_service.py` and its job/run and app wiring; the M0 detection-set
store/API; `web/src/pipeline/RecordingPipelineWorkspace.tsx`, `RecordingWorkspaceShell.tsx`,
`pipelineNodeClient.ts`, `pipelineProcessingClient.ts`, and
`web/src/visibleCards/PipelineNodeVisibleCardEditor.tsx` plus focused clients and tests. Reuse
`GeometrySurface` and frame resolution. A narrow output conversion can keep existing node output
for still-active consumers during this milestone. Do not change their selection authority.

Review is the one new persistent contract in M1: a recording-local review record beside the
detection set, with a safe review ID, exact set/version, reviewer, question, decision, covered
frame/object IDs, and timestamp. Validate targets against that immutable version; save and reopen
independently for each review. Persist unfinished editing as saved detection-set versions; do not
merge independent review decisions or invent completed coverage. Preserve existing node review
and 0096 queue paths until M2. Use existing atomic file primitives; do not introduce a shared
review framework or another transaction authority. Record the exact review API and path in the M1
report with their owner and tests.

Commit: detector adapter, detection-set editor and review path, real-backend browser proof,
focused backend/web checks, generated API, evidence and plan/board update. Verify exact event and
frame evidence, edit and review persistence, earlier-version preservation, empty and failed frame
distinction, restart, and existing node consumer/review regressions. Run affected backend tests,
`web/npm run check`, real-backend Playwright workflow, and Markdown link checks.

### M2 assignment

Observable result: the scene, calibration reflow, visual identity, and observation paths can use an
explicit saved detection-set version, and comparison can compare exact saved detection versions.
Use `{set_id, version, content_sha256}` as the detection reference. Validate it against the
recording-owned M0 store at request acceptance and again when work runs; retain it in durable run
and output lineage so a later edit or restart cannot change the input. Reject missing, mismatched,
or cross-recording evidence. Keep the existing identity and calibration inputs under their current
authorities. A small in-memory conversion to the existing visible-card algorithm input is allowed;
do not publish a shadow node as authority for the new path. Preserve event/frame identity, geometry,
empty coverage, IDs, and review facts needed by each consumer. Fail explicitly when existing
algorithms cannot represent evidence rather than inventing data or dropping it silently.

Owners: `proposed_card_scene_pipeline_service.py`, `calibration_refinement_service.py`,
`visual_identity_pipeline_service.py` and its `visual_identity_request.py` and crop-input adapters,
`observation_pipeline_service.py`, detection branches of `pipeline_comparison_service.py` and API,
their request/run/lineage contracts in `operations/.../pipeline_data.py`, app composition and
focused client call sites and tests. The calibration reflow writer must save a new detection-set
version with its exact input and preserve its existing draft decisions. Existing nodes remain the
bounded bridge for old inputs and the frozen 0096 queue; do not change its target or progress in
M2. Do not remove old paths or convert scene/classification formats here. M3 owns retained-data
conversion, selection cutover, removal and qualification.

Checks: for each named path, save real detection evidence and prove exact input and output lineage,
restart, rejected wrong digest/missing input, and preserved historical input after another edit;
use deterministic processor stubs. Include calibration write/reopen and two alternatives in
comparison. At least one scene or classifier uses the saved version with old detection-node reads
disabled. Run affected consumer, comparison, frame-review, detection store and API suites, static
and generated API checks, web check, and the M1 real-backend browser test. Commit implementation,
tests, evidence and plan/board updates together. If preserving the actual consumer contract needs a
new persistent transaction or an unbounded set of adapters, stop for scope review before adding it.

## Execution handoff

Luna loop authorized for four milestones. Baseline: 4; completed: 3; remaining: 1. This run:
requested 4, completed 3, remaining 1. Run re-plans: 0/10; M0 re-plans: 0/5; M0 corrections:
2/2. Correction 1 added a process-exit publication test and rejected self-intersecting polygons.
Correction 2 aligned persistence with the required frame/detection/segment folder paths and added
path-level reopen coverage. M1 re-plans: 0/5; M1 corrections: 2/2. Correction 1 constrains each
geometry review to one validated frame/object pair, adds a duplicate frame-local object ID
regression, and reopens the earlier version after backend restart in the browser proof. Correction
2 makes the existing 0096 review test return the same fixture digest from authorized and ordinary
revision reads; it preserves the production content-mismatch rejection. Original outcome,
non-goals, and closure checks remain above. The first complete detector and browser
workflow is proved in M1; qualification remains in M3. See the
[M0 evidence](../../reports/0125-M0_Detection_Set_Storage.md)
and [M1 evidence](../../reports/0125-M1_Detection_Set_Editing_and_Review.md).

M0 contract: each version has recording, set, version, origin, source video digest, producer facts,
exact optional event-set references with content digests, and an explicit list of examined frames.
Each frame has the existing exact-frame identity, optional exact event IDs, and zero or more
detections. Each frame-local object has a kind, card side when it is a visible card, and identified
polygon segments in source-image pixel coordinates. Empty detections mean examined with no result;
missing or failed evidence is not accepted as empty. Versions are immutable. Save and open do not
select a version.

M1 changes: the existing visible-card detector saves examined outcomes to M0 versions while its
legacy node output remains available to active readers. The workspace links the latest exact
detection-set version. The editor saves segment changes as a new immutable version and records a
geometry review against that exact version. Review records use
`detection-sets/<set-id>/reviews/<review-id>.json`; the API saves and lists those records below the
exact set/version route. The only new M1 contract is this recording-local geometry review. No
selection authority, downstream node read, existing node review, or 0096 queue changed.

M1 scope review: the real-backend browser workflow now proves exact event input, deterministic
detection output, edited segments, independent geometry review, and restart/reopen. Empty examined
frames are included; a failed frame remains in the run outcome and is absent from detection
coverage. Earlier detection-set versions remain unchanged. Keep the approach for M2. No new
prerequisite was found. Next proof: specify M2 against the named exact-input consumers, calibration
writer, comparison path, and 0096 frame-review bridge. Keep M3 qualification in place. Stop if M2
requires another authority/framework or would displace qualification.

M1 checks: the focused detection backend suite passed (16 tests). The combined node-review and
0096 regression set passed all 37 tests, including the corrected receipt test. The node editor's
six browser component tests passed. Ruff, web check (46 files, 243 tests), generated API,
real-backend Playwright, Markdown links, and `git diff --check` passed. The 0096 test originally
failed on pre-M1 `8047f255` because its test-only digest mock covered ordinary but not authorized
revision reads; correction 2 supplies one consistent digest. See the M1 report for exact commands
and the mismatch rejection boundary. This milestone adds one review-record contract and no new
authority. Existing node output, selection, downstream readers, node reviews, and 0096 progress
remain in place.

M0 scope review after two correction turns (recorded before M1): the original folder-storage
approach remains valid.
The first correction added process interruption and geometry boundaries; the second aligned the
saved paths with the promised layout. Both reduced M0's acceptance gap and passed focused checks
and independent review. The user-facing detector/browser workflow is not yet proved. No new
prerequisite is needed before M1: reuse M0 versions and the existing detector, editor, and node
bridge. Next proof is the M1 real-backend browser workflow above. Stop if it requires a shared
framework, further publication authority, or moving that proof past M1. M0's 2/2 correction
history remains closed; M1 starts at 0/2 corrections and 0/5 re-plans.

M1 scope review after two correction turns: the first complete detector/browser workflow is now
proved. The first correction disambiguated frame-local review targets and proved the older version
after restart; the second fixed a pre-M1 test fixture whose two read paths returned inconsistent
digests. Both passed the combined checks and independent review. Keep the current approach: M2
uses exact M0 versions and existing algorithm adapters, with the old node path as a bounded bridge.
No new persistent authority is required. M2's exact reference extends existing request and lineage
data because the four consumers otherwise cannot name a saved detection version. M3 remains the
qualification checkpoint. M1 corrections 2/2 remain closed; M2 starts at 0/2 corrections and 0/5
re-plans. Stop if a new transaction authority or additional unbounded prerequisite is needed.

M2 changes: scene proposals, visual identity, and observation assembly accept an explicit
`{set_id, version, content_sha256}` detection-set reference. Each path validates the exact version
at acceptance and execution, writes the reference to the durable run and output artifact lineage,
and fails when the existing algorithm cannot represent the stored geometry. Calibration apply now
requires the exact saved detection-set reference, rechecks it before reflow, and records it in the
new corrected version. The reference participates in the calibration receipt identity. This supports
edited alternatives while the current node draft continues to retain its decisions. Comparison reads
the exact version's geometry reviews: accepted objects remain, rejected objects are excluded, frames
with only rejected objects are excluded from coverage, unreviewed objects fail, and explicit empty
frames remain empty. Unsupported geometry fails. The existing node and 0096 frame-review routes
remain the bridge for old inputs. No selection or review authority changed. The only persistent
contract added was the M0 detection-set reference in pipeline request and lineage data; no new
store or transaction authority was added.

Calibration preview, apply, and target proposal generation now use the selected set's pixel geometry.
Frame identities remain exact. Existing node review decisions and ignore regions remain under their
current authority. The real apply regression edits one saved polygon, verifies that the published
proposal reflects it, reopens the output detection set, and verifies exact input lineage and a
retained frame review.

M2 scope review after correction 2: calibration reflow consumes saved geometry through preview and
target proposal generation. The real apply test proves an edited alternative changes the published
proposal and keeps exact lineage after reopen. The existing node review authority remains the source
of preserved frame decisions. The geometry review contract covers one exact frame/object pair, so
comparison validates each object independently and excludes frames with no accepted objects.
It does not infer a review for unreviewed objects or empty frames. This uses the existing M1 review
authority. A hard-snapshot calibration performance fixture has no recording folder, so it supplies
a recording-folder adapter to the production detection-set store; the apply regression reopens the
edited output through a new store instance. The first complete workflow remains the M1
browser proof. M3 retains the planned migration rehearsal, selection cutover, old-path removal, and
qualification. No new prerequisite or scope change was needed. M2 corrections: 2/2; M2 re-plans:
0/5; run re-plans: 0/10. Next milestone: M3.

M2 checks and evidence are recorded in the [M2 report](../../reports/0125-M2_Exact_Detection_Set_Consumers.md).

M2 checks: `uv run --project operations pytest -q operations/tests/test_pipeline_data.py
operations/tests/test_pipeline_comparison.py` passed 21 tests. The combined backend consumer,
comparison, detection-store, and lineage command passed 68 tests:
`uv run --project backend pytest -q backend/tests/test_pipeline_vision_comparison_api.py
backend/tests/test_pipeline_comparison_api.py backend/tests/test_calibration_refinement_service.py
backend/tests/test_detection_set_api.py backend/tests/test_detection_set_inputs.py
backend/tests/test_observation_pipeline_api.py backend/tests/test_visual_identity_pipeline_api.py
backend/tests/test_proposed_card_scene_pipeline.py backend/tests/test_pipeline_lineage_writer.py
backend/tests/test_visible_card_pipeline_api.py`.
The node-review, node-selection and 0096 frame-review command passed 54 tests:
`uv run --project backend pytest -q backend/tests/test_pipeline_node_reviews.py
backend/tests/test_frame_review_bindings.py backend/tests/test_frame_review_queue.py
backend/tests/test_frame_review_api.py backend/tests/test_visible_card_review_frontend.py
backend/tests/test_pipeline_node_selection_store.py backend/tests/test_pipeline_api.py
backend/tests/test_pipeline_comparison_api.py backend/tests/test_pipeline_vision_comparison_api.py`.
The calibration apply/readback fixture passed with a visibly edited saved polygon, exact proposal
readback, output lineage reopen, and preserved node review. The real-backend detection-set browser
workflow passed after this correction.
Backend and operations Ruff checks passed. `cd web && npm run generate:api`, `cd web && npm run
check` (46 files, 243 tests), and `cd web && npm run test:e2e:detection-set` (one real-backend
workflow) passed. Local links and `git diff --check` passed.
