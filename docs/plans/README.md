# DokoDetector epic board

Each numbered Markdown file is an epic. Its contents can combine the specification and its work
items. The four-digit epic number records creation order. The folder records the current status.

## Workflow

| Order | Status | Folder | Meaning |
| --- | --- | --- | --- |
| 0 | To Specify | [`0-to-specify/`](0-to-specify/) | The direction is useful, but evidence or requirements must define the epic. |
| 1 | Backlog | [`1-backlog/`](1-backlog/) | The epic is specified, but it is not selected for delivery. |
| 2 | Ready | [`2-ready/`](2-ready/) | The epic is clear, actionable, and available to start. |
| 3 | In Progress | [`3-in-progress/`](3-in-progress/) | Work on the epic is active. |
| 4 | Blocked | [`4-blocked/`](4-blocked/) | Work cannot continue until a named dependency or blocker is resolved. |
| 5 | Closed | [`5-closed/`](5-closed/) | No more work is planned in this epic. A closure reason is required. |

Use only these values in the `Status` field. Record prerequisites in a separate `Depends on`
field. A dependency does not replace the status. If an unmet dependency prevents work, use the
`Blocked` status.

When an epic changes status, update its `Status` field and move its file to the matching folder.
Update relative links in the same change.

Closed epics use a `Closure reason` such as `Complete`, `Won't Do`, `Superseded`, `Duplicate`, or
`Invalid`. Add a `Closure note` when the reason needs context.

## Board

The shared target architecture is
[Table Observation and Game Reconstruction](../TableObservationReconstruction.md).

### To Specify

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0022 — TableEvidenceAnalyzer capability development](0-to-specify/0022-Table_Evidence_Analyzer_Development.md) | 0020, 0021, and reviewed real evidence; tracking also needs 0025 | Select measured visible-card, transition, spatial, and tracking methods. |
| [0023 — Scalable game reconstruction](0-to-specify/0023-Game_Reconstruction_Development.md) | 0006 search measurements | Scale observation inference to uncertain rounds and complete games. |
| [0024 — System production readiness](0-to-specify/0024-System_Production_Readiness.md) | Integration, snippet, observation, reconstruction, and review measurements | Select production work from measured requirements. |
| [0026 — Reconstruction review workflow](0-to-specify/0026-Reconstruction_Review_Workflow.md) | 0006 and 0023 review contracts and measured cases | Build focused review and complete human correction. |

### Backlog

| Epic | Depends on | Outcome |
| --- | --- | --- |
| None | — | — |

### Ready

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0028 — Model improvement and promotion](2-ready/0028-Model_Improvement_and_Promotion.md) | 0021 and 0027 | Run bounded component experiments and explicitly promote a new champion model bundle. |

### In Progress

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0029 — Repository data boundaries and evidence intake](3-in-progress/0029-Repository_Data_Boundaries_and_Evidence_Intake.md) | 0027 | Keep shared intake at the repository root, stage incomplete videos before intake, and preserve accepted evidence packages as pipeline inputs. |

### Blocked

| Epic | Depends on | Outcome |
| --- | --- | --- |
| None | — | — |

### Closed

| Epic | Closure reason | Outcome |
| --- | --- | --- |
| [0030 — iOS training upload ergonomics](5-closed/0030-iOS_Training_Upload_Ergonomics.md) | Complete | Show preparation and byte-accurate upload progress after a training recording stops. |
| [0027 — Shared training data operations](5-closed/0027-Shared_Training_Data_Operations.md) | Complete | Capture source material once and process it independently for CardEventNet and the TableEvidenceAnalyzer. |
| [0021 — TableEvidenceAnalyzer model training](5-closed/0021-Table_Evidence_Analyzer_Training_Pipeline.md) | Complete | Build the train, evaluate, checkpoint, and export loop for analyzer model components. |
| [0001 — CardEventNet v1](5-closed/0001-CardEventNet_v1.md) | Complete | Initial CardEventNet pipeline. |
| [0002 — iOS CardEventNet PoC](5-closed/0002-iOS_CardEventNet_PoC.md) | Complete | iOS inference PoC. |
| [0003 — iOS evidence upload](5-closed/0003-iOS_EvidenceUpload.md) | Complete | Evidence package and V1 upload contract. |
| [0004 — Backend evidence upload](5-closed/0004-Backend_EvidenceUpload.md) | Complete | Local evidence-ingestion backend. |
| [0005 — VisionDetector local pipeline PoC](5-closed/0005-VisionDetector_v1.md) | Complete | Scripted vision-result pipeline and real-recognition handoff. |
| [0006 — Table observation reconstruction PoC](5-closed/0006-GameEngine_v1.md) | Complete | Freeze the observation boundary and build the rules and reconstruction oracle. |
| [0007 — CardEventNet cloud training](5-closed/0007-CardEventNet_CloudTraining.md) | Complete | Portable single-GPU training. |
| [0008 — CardEventNet training-data improvements](5-closed/0008-CardEventNet_TrainingDataImprovements.md) | Complete | Historical data tooling. |
| [0009 — CardEventNet training performance](5-closed/0009-CardEventNet_Training_Performance.md) | Complete | Faster training pipeline. |
| [0010 — CardEventNet training diagnostics](5-closed/0010-CardEventNet_Training_Diagnostics.md) | Complete | Training diagnostics. |
| [0011 — CardEventNet corrective work](5-closed/0011-CardEventNet_Corrective.md) | Complete | Annotation and training corrections. |
| [0012 — CardEventNet improvement loop](5-closed/0012-CardEventNet_Unattended_Improvement_Loop.md) | Complete | Bounded improvement experiment. |
| [0013 — CardEventNet full-frame input](5-closed/0013-CardEventNet_FullFrameInput.md) | Complete | Full-frame preprocessing migration. |
| [0014 — CardEventNet review queue](5-closed/0014-CardEventNet_ReviewQueue_Workflow.md) | Complete | Interactive review workflow. |
| [0015 — CardEventNet transition targets](5-closed/0015-CardEventNet_Transition_Targets.md) | Complete | Transition-target experiment. |
| [0016 — iOS evidence-upload integration](5-closed/0016-iOS_EvidenceUpload_Integration.md) | Complete | Local iOS-to-backend-to-detector pipeline. |
| [0017 — iOS evidence-upload production readiness](5-closed/0017-iOS_EvidenceUpload_ProductionReadiness.md) | Superseded by 0024 | iOS hardening reference. |
| [0018 — Backend evidence-upload production readiness](5-closed/0018-Backend_EvidenceUpload_ProductionReadiness.md) | Superseded by 0024 | Backend hardening reference. |
| [0019 — App training recordings](5-closed/0019-App_TrainingRecordings.md) | Complete | Deliberate recording intake and local end-to-end workflow. |
| [0020 — Data foundation](5-closed/0020-Data_Foundation.md) | Complete | Shared source, annotation, review, dataset, split, and lifecycle-receipt foundation. |
| [0025 — Video snippet evidence](5-closed/0025-Video_Snippet_Evidence.md) | Complete | Bounded V2 video snippets with reviewed 960×540 exploratory evidence. |

## Near-term delivery sequence

1. Start 0029 with repository-root path and bundle contracts. Complete its pending-video path before
   changing evidence-package intake.
2. Start 0028 with registry, recipe, campaign, and report contracts. Then implement the
   CardEventNet campaign and promotion path before the TableEvidenceAnalyzer adapter.
3. Run 0030 in parallel when iOS capacity is available. Keep its upload-progress changes separate
   from the 0029 evidence-package producer contract.
4. Put corrected 0025 packages through the completed 0027 table-evidence review path. Use the
   resulting coverage and failure measurements to specify 0022. Do not treat the three 0025 M6
   packages as a sufficient recognition dataset by themselves.
5. Record the 0006 search, ambiguity, merging, correction, and feature-ablation measurements needed
   to specify 0023.
6. Specify 0022 after reviewed real frames and snippets provide its entry measurements.
7. Specify 0023 after its 0006 measurement set is recorded. Add real observation behavior later
   without replacing the identity-only oracle baseline.
8. Specify 0026 after focused review cases and correction behavior are measured.
9. Specify 0024 only after end-to-end product and operational measurements exist.

## Closed-epic policy

Closed epic files are immutable historical records. Do not update them for new terminology,
architecture, or planning policy. Add later evidence to the earliest active epic that owns the
issue. Create a bounded follow-up epic only when no active epic owns it.

Change a closed epic only after an explicit user request, to remove restricted information, or to
repair a link after an authorized move or rename. Keep the exception mechanical and minimal. Do not
reopen or rewrite the closed plan through an exception.
