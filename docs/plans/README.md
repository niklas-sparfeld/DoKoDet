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
| [0023 — Scalable game reconstruction](0-to-specify/0023-Game_Reconstruction_Development.md) | Completed 0006 foundation; search measurements must define the next scope | Specify later search improvements. Existing reconstruction remains usable through 0048. |
| [0024 — System production readiness](0-to-specify/0024-System_Production_Readiness.md) | Explicit production scope and measured development behavior | Select later production work. Package-only operation is not a current requirement. |
| [0026 — Reconstruction review workflow](0-to-specify/0026-Reconstruction_Review_Workflow.md) | 0006 contracts, later 0023 focused alternatives, and measured review cases | Specify full reconstruction correction beyond the existing inspection exposed by 0049. |

### Backlog

| Epic | Depends on | Outcome |
| --- | --- | --- |
| None | — | — |

### Ready

| Epic | Depends on | Outcome |
| --- | --- | --- |
| None | — | — |

### In Progress

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0049 — Recording pipeline review and comparison](3-in-progress/0049-Recording_Pipeline_Review_and_Comparison.md) | 0048 complete | Reuse the editors with one maintained reference per stage, simple input selection, retained results, and comparison. M0–M4 complete; M5–M10 not started. |

### Blocked

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0051 — Visible-region identity resilience baseline](4-blocked/0051-Visible_Region_Identity_Resilience_Baseline.md) | 0048 and 0049 complete, plus paired reviewed visible-card and identity coverage from at least two source-lineage groups | Preserve visible cards without usable identity, compare actual and corrupted visible regions, and decide whether simple visible-region exclusion is sufficient. M0–M4 not started. |
| [0052 — Selected response to visible-region identity failures](4-blocked/0052-Selected_Visible_Region_Identity_Response.md) | 0051 selects one follow-up identity response | Implement and evaluate at most one response to the measured 0051 failure. Close as not required for any other 0051 conclusion. M0–M3 not started. |
| [0043 — Local visual card identity quality proof](4-blocked/0043-Local_Visual_Card_Identity_Quality_Proof.md) | 0041, 0042, 0048, 0049, and 0051 complete; resolve 0052 if required; plus declared real reviewed coverage | Compare at most two DINOv3 candidates with the fixed resilient identity input contract; lock at most one without changing the backend default. M0–M3 not started. |
| [0044 — Productive local identity model operations](4-blocked/0044-Productive_Local_Identity_Model_Operations.md) | 0043 locks a passing candidate; 0048 and 0049 complete | Reuse maintained references for priority work; add bounded campaigns, explicit promotion, local cutover, and rollback. M0–M3 not started. |
| [0050 — Detector quality and analyzer capabilities](4-blocked/0050-Detector_Quality_and_Analyzer_Capabilities.md) | 0048, 0049, and 0051 complete; resolve 0052 if required; plus reviewed real evidence for a bounded measurement | Measure visible-region providers and composed quality against the fixed resilient identifier, then select at most one justified capability response. M0–M3 not started. |

### Closed

| Epic | Closure reason | Outcome |
| --- | --- | --- |
| [0048 — Pipeline data and execution](5-closed/0048-Pipeline_Data_and_Execution.md) | Complete | M0–M10 complete: recording-video pipeline execution, maintained references with coverage and downstream impact validation, immutable dataset consumer manifests with explicit source/policy/lineage inputs, and the 0049 cutover handoff. Real-data quality measurement remains in 0043 and 0050. |
| [0047 — Current recording annotations and evidence](5-closed/0047-Current_Recording_Annotations_and_Evidence.md) | Superseded | Replaced before implementation by 0048 and 0049. Proposal loss and package management are not the target design. |
| [0041 — Local visual card identity classifier PoC](5-closed/0041-Local_Visual_Card_Identity_Classifier_PoC.md) | Complete | M0–M3 complete: local training, bundle, classifier runtime, and backend capability proved. Quality remains in 0043; new integration work belongs to 0048. |
| [0039 — Web recording data workspace](5-closed/0039-Web_Recording_Data_Workspace.md) | Complete | M0–M4 complete: recording workspace, event review, completion, and development partitions. Further data and review work belongs to 0048/0049. |
| [0022 — TableEvidenceAnalyzer capability development](5-closed/0022-Table_Evidence_Analyzer_Development.md) | Superseded | Retain completed implementation evidence. Foundation and UI work move to 0048/0049; remaining detector and capability experiments move to 0050; identity quality stays in 0043. |
| [0046 — Filesystem storage engine](5-closed/0046-Filesystem_Storage_Engine.md) | Complete | Validated filesystem resources are the only backend storage. Recording bundles, evidence packages, table observations, round analyses, pending videos, and operations data survive restart from canonical files without SQLite, SQLAlchemy, or Alembic. |
| [0038 — Visible-card training-data improvement](5-closed/0038-Visible_Card_Training_Data_Improvement.md) | Complete | Correct Gemini visible geometry and review visible regions with fixed source and teacher lineage. M0–M5 complete; real prompting and human review remain deferred. |
| [0045 — Card event review workflow improvements](5-closed/0045-Card_Event_Review_Workflow_Improvements.md) | Complete | Complete the wide video-first CardEvent workflow with recording-owned review resources, unified event lineage, verified source-context caching, stable review pages, optimistic ordered commands, retry and conflict recovery, and keyboard and pointer review-loop coverage. |
| [0040 — Visible-card annotation review workspace](5-closed/0040-Visible_Card_Annotation_Review_Workspace.md) | Complete | Create, correct, complete, and publish visible-card reviews with immutable lineage, revisions, lifecycle receipts, and existing-freeze-path readiness. |
| [0042 — Visual card identity annotation workspace](5-closed/0042-Visual_Card_Identity_Annotation_Workspace.md) | Complete | Create, review, publish, revise, and freeze visual card identity labels from source-linked visible-card reviews with immutable lineage, lifecycle receipts, and validated group-safe development data. |
| [0037 — Local visible-card detector end-to-end PoC](5-closed/0037-Local_Visible_Card_Detector_PoC.md) | Complete | Prove local RF-DETR training with a real loadable smoke checkpoint, and preserve fixture-tested provider and backend contracts. Real backend execution is out of scope. |
| [0033 — Round analysis timeline and counterfactual explorer](5-closed/0033-Round_Analysis_Timeline.md) | Complete | Explain one completed analysis as synchronized evidence, table-observation, and reconstruction-hypothesis rows, then compare immutable counterfactual runs. M0–M8 complete. |
| [0035 — Backend terminal logging](5-closed/0035-Backend_Terminal_Logging.md) | Complete | Backend terminal logging and diagnostic context. |
| [0034 — Gemini round analysis integration](5-closed/0034-Gemini_Round_Analysis_Integration.md) | Complete | Make the normal round-analysis backend use Gemini for every evidence package and require its runtime credential. |
| [0032 — Round recording analysis PoC](5-closed/0032-Round_Recording_Analysis_PoC.md) | Complete | Use one iOS recording to create the complete video and its evidence packages; M0–M5 provide the reusable backend boundary, durable analysis lifecycle, worker, APIs, runtime artifacts, unified iOS recording boundary, upload gating, durable submission, polling, concise result UI, deterministic fixtures, and local flow documentation. |
| [0036 — iOS recording workspace simplification](5-closed/0036-iOS_Recording_UI_Simplification.md) | Complete | Replace the separate Live and Record flows with one profile-based recording workspace and keep the existing durable upload and analysis lifecycle. M0–M4 complete. |
| [0031 — Round reconstruction integration harness](5-closed/0031-Round_Reconstruction_Integration_Harness.md) | Complete | Reproducibly assemble stored table observations into one explicit round input and record the reconstruction result, with analyzer persistence integration and four scenario outcomes. |
| [0029 — Repository data boundaries and evidence intake](5-closed/0029-Repository_Data_Boundaries_and_Evidence_Intake.md) | Complete | Keep shared intake at the repository root, stage incomplete videos before intake, and preserve accepted evidence packages as pipeline inputs. |
| [0030 — iOS training upload ergonomics](5-closed/0030-iOS_Training_Upload_Ergonomics.md) | Complete | Show preparation and byte-accurate upload progress after a training recording stops. |
| [0028 — Model improvement and promotion](5-closed/0028-Model_Improvement_and_Promotion.md) | Complete | Run bounded component experiments and explicitly promote a new champion model bundle. |
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

## Next steps

1. **Continue 0049.** Deliver M1–M10 to expose the retained data and maintained references through
   the existing recording editors.
2. **Collect and review real development coverage through that workflow.** Keep source groups and
   sealed holdouts intact. Use the same maintained references to compare model runs. Record gaps;
   do not lower review or coverage requirements merely to unblock model work.
3. **Run 0051 before another identity or visible-region model experiment.** Freeze actual and
   corrupted predicted-region conditions, preserve cards with unusable identity evidence, and
   measure the simple exclusion crop policies. Use its decision to specify one response in 0052 or
   close 0052 as not required.
4. **Resolve 0052 from the 0051 decision.** Start its one selected response or close it as not
   required before another identity or visible-region model experiment.
5. **Reassess 0043 and 0050 after the resilient identity baseline is fixed.** Make 0043 Ready when
   its class/session coverage gates and frozen recipe are actionable. Make 0050 Ready when a bounded
   detector/composed measurement has reviewed evidence, fixed inputs, metrics, thresholds, and a
   budget. Neither requires the other to complete; prioritize the measured pipeline bottleneck. Do
   not run an open-ended search.
6. **Start 0044 only after 0043 locks a passing candidate.** Reuse 0048/0049 rather than introducing
   another review lifecycle. Promotion and backend default changes remain explicit later actions.
7. **Keep 0023, 0026, and 0024 as later specification work.** They do not block the current engine,
   existing analysis inspection, or local feasibility workflow. Specify search improvements and full
   reconstruction correction from measured cases. Agree a production scope before production work.

For each started epic, `next phase` means its next incomplete milestone. After each milestone,
commit to main, update the epic and this board, report all milestone states, and compact the working
context. Check dependencies again before changing a Blocked epic to Ready.

### Planning decisions — 2026-09-04

- Close 0039 and 0041 because their listed milestones are complete. Do not extend their scope.
- Supersede 0047 and retire the duplicate-numbered, unimplemented recording-simplification draft
  formerly called 0046. Its developed proposal is preserved in closed 0047. The completed
  **0046 — Filesystem storage engine** keeps its number and historical scope.
- Supersede 0022; do not use its old cloud-first sequence, package contracts, prices, or provisional
  thresholds as the new pipeline plan. Useful remaining measurement questions are in 0050.
- Keep and refine 0043/0044 because bounded quality proof and explicit model operations are still
  needed. Replace their obsolete 0047 dependencies with 0048/0049.
- Keep all completed run results and completed reference revisions. One maintained reference is a
  simple default, not a rule to overwrite processor output.
- Use original video as the recording pipeline source. Derive frames, crops, and snippets with
  defined policies. Device packages remain a showcase and are never pipeline inputs or fallbacks.
- Planning changes do not implement these runtime contracts. The milestones in 0048 and 0049 own
  the cutover and remove obsolete paths. Existing closed epics are historical, not new requirements.

### Planning decisions — 2026-09-06

- Add 0051 before another identity or visible-region model experiment. It owns visual identity
  outcome resilience, deterministic imperfect-region conditions, visible-region exclusion, and the
  fixed risk-versus-coverage baseline.
- Add conditional 0052 for at most one identity response selected by 0051. Close it as not required
  when a simple crop policy, more data, the current policy, or later provider work is the 0051
  conclusion.
- Keep all visible-card proposals in table observations when identity evidence is unusable or
  processing fails. Do not fabricate an identity to preserve the proposal.
- Keep RF-DETR segmentation and other visible-region provider changes out of 0051 and 0052. Epic
  0050 can measure a provider candidate only after the resilient downstream identifier is fixed.
- Keep temporal association in 0050. It remains optional evidence and does not replace the stream of
  all currently visible cards.

## Closed-epic policy

Closed epic files are immutable historical records. Do not update them for new terminology,
architecture, or planning policy. Add later evidence to the earliest active epic that owns the
issue. Create a bounded follow-up epic only when no active epic owns it.

Change a closed epic only after an explicit user request, to remove restricted information, or to
repair a link after an authorized move or rename. Keep the exception mechanical and minimal. Do not
reopen or rewrite the closed plan through an exception.
