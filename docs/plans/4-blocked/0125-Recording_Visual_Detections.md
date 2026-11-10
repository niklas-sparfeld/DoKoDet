# Recording visual detections

- **Status:** Blocked
- **Depends on:** [0124](../3-in-progress/0124-Recording_Folders_and_Events.md) closure and stable recording/event references.
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
| M0 | Concrete detection-set storage; real API save/open of exact frame/object/segment evidence | Not started |
| M1 | Existing detector and browser segment editor/review use the same contract; restart proof | Not started |
| M2 | The four named downstream consumers read exact detection resources; preserve alternatives and review | Not started |
| M3 | Retained-data rehearsal, default detection cutover, replaced-path removal, and qualification | Not started |

### Assignment preparation

After 0124 closes, freeze exact detection-editor/client paths and the representative persisted
schemas from the finite owners above. Specify M0's typed detection, coverage, provenance, and
local review layout. M0 adds only the detection-set storage contract and uses the existing root
HEAD write protocol. No new publication authority. Commit: store/API, focused persistence and
geometry regressions, evidence, and plan/board update. Required proof is save/open through a real
API, not a parser-only fixture.

Specify M1 before assignment, then M2/M3 after the browser proof. Keep qualification in M3. If a
consumer needs a broader new representation, retain its current algorithm with a small explicit
input conversion; do not silently convert the next resource type in this epic.

## Execution handoff

Planning only. Baseline: 4 milestones; 4 remain. First API workflow: M0; browser: M1;
qualification: M3. No run authorized. At most two corrections per family under the execution
scope review. A new shared geometry/review framework or displaced browser proof is a scope stop.
