# Recording virtual scenes

- **Status:** Blocked
- **Depends on:** [0125](0125-Recording_Visual_Detections.md) closure and stable detection/frame references.
- **Outcome:** Generate, edit, select, and reopen calibrated virtual scenes beside their recording evidence.
- **Origin:** [Recording data storage](../../RecordingDataStorage.md).

## Problem and success

Calibrations, proposed scenes, edited scenes, and their inputs use several process-oriented
representations. Store exact calibrations and concrete virtual-scene sets in the recording folder.
Preserve pose, stacking order, source frame, supporting detections, pile/ignore evidence, review,
and alternative scenes. Human edits and processor scenes use the same scene content contract.
Existing calibration and scene algorithms remain unchanged.

Use the storage decision's calibration and scene layouts. Calibration and scene persistence are
separate milestone contracts; do not hide both in a storage-foundation assignment. Calculate
rendered visible regions from poses when needed. A pile footprint need not reveal its cards.
Existing exact calibration/scene content is the smaller basis; new fitting, tracking, scene graph,
or publication-framework work has no failing requirement here.

Non-goals: fitting quality, joint optimization improvements, model changes, classifier/observation
storage conversion, generalized calibration history, and new physical-card identity inference.

## Finite source owners

Backend: `calibration_refinement_service.py`, `calibration_refinement_api.py`,
`calibration_reflow_context.py`, `proposed_card_scene_pipeline_service.py`,
`proposed_card_scene_jobs.py`, `virtual_scene_data.py`, scene branches of node edit/review/selection
and workspace adapters, plus their composition entries. Content: existing `card_scene_contract.py`
and `operations/card_plane_geometry.py` contracts. Consumers: `visual_identity_pipeline_service.py`
and `observation_pipeline_service.py` scene/crop inputs. Web: calibration client, calibration panel,
and virtual-scene editor/review call sites frozen before their assignments.

## Closure check

Real API/browser: open exact detections, select a calibration, generate a scene with deterministic
processing, edit poses/order, review it, retain an alternative, select and reopen after restart.
Preserve exact scene/calibration links after another calibration is saved. Exercise the ordinary
calibration preview/accept path without moving job scheduling into domain content.

Verify visible-region rendering and classifier crop inputs against the same exact old geometry.
Rehearse conversion of named calibration/proposal/review schemas; compare usable content, frames,
decisions, unfinished work, selections, and exact downstream inputs. Disable replaced scene-node
reads in the proof. Test interrupted saves/HEAD selection and concurrent conflicting edits.
Run affected calibration/scene/crop/API/browser/static checks; preserve bounded list reads.

## Milestones

| Milestone | Observable result and commit boundary | State |
| --- | --- | --- |
| M0 | Existing calibration content saved/read as a concrete recording resource through real APIs | Not started |
| M1 | Concrete virtual-scene sets; API save/select/open tied to exact detections and calibration | Not started |
| M2 | Existing fitting, browser editing/review, and exact classifier crop input use the new scene resource | Not started |
| M3 | Retained-data rehearsal, default scene/calibration cutover, replaced-path removal, and qualification | Not started |

### Assignment preparation

After 0125 closes, freeze calibration writer/editor/schema paths. M0 changes only the calibration
storage boundary and its API adapter; it adds at most one persistence contract. Required proof:
save/open an exact calibration through real services/APIs and restart, including invalidation
after camera/table movement. Commit: concrete calibration code, focused tests, evidence, and plans.
Specify M1's one scene-set contract before assignment. Freeze M2's finite editor and consumer set
after the API workflow; qualify in M3. A model-quality issue is a separate outcome unless this
exact save/open workflow fails because of it.

## Execution handoff

Planning only. Baseline: 4 milestones; 4 remain. Calibration API: M0; scene API: M1; browser: M2;
qualification: M3. No run authorized. Two corrections per family maximum under the execution
scope review. Do not add another prerequisite contract or defer the browser proof beyond M2.
