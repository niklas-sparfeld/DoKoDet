# Recording classifications

- **Status:** Blocked
- **Depends on:** [0126](0126-Recording_Virtual_Scenes.md) closure and stable detection/virtual-object references.
- **Outcome:** Classify detected or virtual objects, review alternatives, and reopen exact classification results from the recording folder.
- **Origin:** [Recording data storage](../../RecordingDataStorage.md).

## Problem and success

Classification content repeats geometry and couples evidence to run outcomes. Store concrete
classification sets that reference exact objects and their visible crop evidence. Preserve
candidate labels/scores, face-down classification, unknown/unusable evidence, human decisions,
and classifier/model/configuration provenance. Preserve predictions and human alternatives in
the same classification contract. An execution error remains a job fact, not a card identity.

Use the recording-owned classification layout and existing root selection protocol. Use existing
classifiers, crop policies, and identity semantics. Small explicit input/output conversions at
their existing call sites suffice; no universal classifier/resource adapter is required.

Non-goals: accuracy improvements, new class vocabularies, physical-card tracking, classifier
training, crop-policy changes, or conversion of training/evaluation datasets.

## Finite source owners

Backend: `visual_identity_pipeline_service.py`, `visual_identity_recording_access.py`,
`pipeline_identity_review.py`, `visual_identity_pipeline_errors.py`, and classification branches
of edit/review/selection/workspace/composition adapters. Content/evidence:
`table_evidence_analyzer/pipeline_data.py`, `visual_identity_crop_input.py`, and
`card_classification.py`. Consumer: `observation_pipeline_service.py`. Web: identity API client,
classification inspection/editor and review call sites frozen before M0/M1 assignments.

## Closure check

Real API/browser: classify one detected object and one virtual object using deterministic
classifiers; retain alternative candidate sets; review/correct one classification; select; reopen
after restart. Preserve the exact source-frame/geometry evidence after detection or scene edits.
Include face-down, insufficient evidence, unknown identity, and an operational processing failure
without manufacturing an empty classification. Distinguish identical visual classes on two objects.

Rehearse conversion of named retained identity/review schemas and exact observation inputs. Verify
labels, scores, crop evidence, decisions, unfinished review, and selections. Disable old identity
node reads. Test save interruption, stale root versions, and separate concurrent edits. Run affected
identity/crop/review/observation/API/browser/static checks and bounded list regressions.

## Milestones

| Milestone | Observable result and commit boundary | State |
| --- | --- | --- |
| M0 | One concrete classification-set contract and real API save/open using exact object evidence | Not started |
| M1 | Existing classifier and browser review use the shared concrete content contract; restart proof | Not started |
| M2 | Exact detected/virtual input handling and observation consumer preserve alternatives and provenance | Not started |
| M3 | Retained-data rehearsal, default classification cutover, replaced-path removal, and qualification | Not started |

### Assignment preparation

After 0126 closes, freeze M0's typed fields, review layout, exact API/client paths, and retained
schemas. M0 adds only classification-set storage and reuses root selection. It must save/open a
resource through a real API, with exact evidence validation; parser-only tests do not suffice.
Commit: concrete store/API and focused tests, evidence, and plan/board updates. Specify M1 before
assignment and M2/M3 after the browser proof. No new crop engine or general provenance framework.

## Execution handoff

Planning only. Baseline: 4 milestones; 4 remain. First API: M0; browser: M1; qualification: M3.
No run authorized. Two correction turns per family maximum under the execution scope review.
Stop for new model/training scope or a broader format conversion outside the named owners.
