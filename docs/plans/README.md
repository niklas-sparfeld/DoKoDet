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

### Ready

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0044 — Productive local identity model operations](2-ready/0044-Productive_Local_Identity_Model_Operations.md) | 0043, 0048, and 0049 complete | M0–M3 not started. The first 0043 development candidate is measured and retained without promotion; define explicit promotion gates before any local cutover. |

### In Progress

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0080 — Agent-scale visible-card review modules](3-in-progress/0080-Agent_Scale_Visible_Card_Review_Modules.md) | Completed 0059 web workspace module boundaries and completed 0074 unified visible-card review workbench | M0–M5 complete. Public editor and workbench roots are small wrappers; focused tests are split by owner, and `npm run check` includes a passing root/test size guard. The 10 editor failures from M0 remain. Full checks also encounter existing lint, formatting, app-test, and Playwright failures; see M5 evidence. |
| [0083 — Manual RF-DETR runs for proposed card scenes](3-in-progress/0083-Manual_RF_DETR_Proposed_Card_Scene_Runs.md) | 0048, 0049, 0068, and 0073 complete | M0–M1 complete. The preflight passed for all 30 selected recordings; all local RF-DETR visible-card runs completed and retained input, model, run, and output revision lineage. M2 remains. |

### Blocked

| Epic | Depends on | Outcome |
| --- | --- | --- |
| [0050 — Detector quality and analyzer capabilities](4-blocked/0050-Detector_Quality_and_Analyzer_Capabilities.md) | 0048, 0049, and a future fixed identity baseline; 0052 is not required; plus reviewed real evidence for a bounded measurement | Measure visible-region providers and composed quality against a fixed identity baseline, then select at most one justified capability response. The completed 0067 `poc_candidate` is optional later input; M0–M3 not started. |

### Closed

| Epic | Closure reason | Outcome |
| --- | --- | --- |
| [0081 — Calibration pose-seed refinement from virtual-card fitting](5-closed/0081_Calibration_Pose_Seed_Refinement.md) | Complete | M0 adds a bounded virtual-card-informed calibration pose seed, keeps the shared robust boundary objective and evidence gates, preserves v3 stored-calibration readability, and passes the frozen comparison without a publication regression. |
| [0082 — Fine-model small-card instance refinement](5-closed/0082-Fine_Model_Visible_Card_Prepass.md) | Complete | M0–M4 complete. Provider v6 is selectable in backend runs and the Web UI, with Gemini unchanged as default. It preserves full-frame recall but does not improve small-card or overlap recall; see the held-out evaluation and known limits in the epic. |
| [0071 — Coarse-to-fine visible-card detection](5-closed/0071-Coarse_to_Fine_Visible_Card_Detection.md) | Superseded | M0–M6 remain the historical implementation record. Epic 0082 replaces and removes the coarse RF-DETR cascade from active provider code and selection surfaces. |
| [0079 — Review-first calibration gates](5-closed/0079_Review_First_Calibration_Gates.md) | Complete | M0 makes spatial coverage and held-out boundaries review warnings, lowers the boundary straightness cutoff, and draws fitted rounded outlines. All 24 frozen real results now publish for human review. |
| [0078 — Automatic calibration without a size reference](5-closed/0078-Automatic_Calibration_Without_Size_Reference.md) | Complete | M0 removes the independent size-reference publication gate, retains optional bias diagnostics, and lets four of 24 frozen real results publish. The other gates remain active. |
| [0077 — Rounded physical card outlines](5-closed/0077-Rounded_Physical_Card_Outlines.md) | Complete | M0 uses a deck-measured corner radius in calibration fits, held-out checks, review overlays, and pose-derived visible regions. One more frozen local result passes the held-out gate; fit P90 and runtime rise slightly. |
| [0076 — Frame-complete automatic calibration candidates](5-closed/0076-Frame_Complete_Calibration_Candidates.md) | Complete | M0 excludes projected outlines outside the source frame. M1 shows fit, held-out, and discarded cards with metrics. M2 excludes cards with projected edges hidden by another detected card or a deep inward notch. The size-reference publication rule was later removed in 0078. |
| [0075 — Robust automatic table-plane calibration](5-closed/0075-Robust_Automatic_Table_Plane_Calibration.md) | Complete | M0–M5 established automatic calibration, anchor refinement, diagnostic fit candidates, and frozen gates. The original size-reference gate and its shrink failure were later changed in 0078; independent outlines remain optional evaluation data. Current evidence does not justify a lens model. |
| [0074 — Unified visible-card review workbench](5-closed/0074-Unified_Visible_Card_Review_Workbench.md) | Complete | M0–M5 complete: one shared Camera/Rectified workbench now owns visible-region, ignore-region, virtual-card, mapping, restore, and frame-decision actions; the Timeline Rail keeps navigation only; the split presentations and legacy editor path are removed. |
| [0073 — Production proposed card scenes and calibration refinement](5-closed/0073-Production_Proposed_Card_Scenes_and_Calibration_Refinement.md) | Complete | M0–M7 complete: production proposals, maintained-reference review, synchronized Source/Rectified card editing, calibration refinement, atomic reflow, preserved lineage, and bounded operator verification are complete. |
| [0070 — Synthetic visible-region training data](5-closed/0070-Synthetic_Visible_Region_Training_Data.md) | Complete | M0–M6 complete with declared gaps. The 50/50 real-plus-synthetic candidate improved frozen real validation mask AP and recall. No legal M6 development source group remained for human correction timing, so the candidate is retained as an experiment and is not promoted as an annotation prefill. |
| [0072 — Pose-based visible-card review](5-closed/0072-Pose_Based_Visible_Card_Review.md) | Complete | M0–M5 complete: shared calibrated card-plane geometry and versioned scene contracts are frozen; deterministic calibration, pose initialization, virtual-table correction, derived visible-region validation, maintained-reference integration, and dataset lineage are verified by a local end-to-end fixture. Unsupported frames fail explicitly; no Gemini, cloud service, or human calibration input is required. |
| [0052 — Selected response to visible-region identity failures](5-closed/0052-Selected_Visible_Region_Identity_Response.md) | Won't Do | No measured 0051 failure selected a follow-up identity response; M0–M3 were not started. |
| [0051 — Visible-region identity resilience baseline](5-closed/0051-Visible_Region_Identity_Resilience_Baseline.md) | Won't Do | The live 4,920-request comparison and M4 decision were not decision-critical. Retain the completed identity-outcome preservation and deterministic crop/receipt infrastructure. |
| [0069 — Auto-accept identities](5-closed/0069-Auto_Accept_Identities.md) | Complete | M0–M2 complete: retained Gemini/local comparisons safely auto-approve matching pending visual identities, with run/result lineage and guarded receipts. Cmd+Arrow moves through unfinished items in all reviewed editors. |
| [0063 — Current CardEventNet training campaign](5-closed/0063-Current_CardEventNet_Training_Campaign.md) | Complete | M0–M15 complete: M15 validated the one-time sealed-test output and Core ML integration bundle against the immutable M14 lock, recorded the runtime contract and parity digest, retained M9 as a development-only integration baseline, and left the production champion unchanged. |
| [0068 — Reviewed RF-DETR local visible-card detector](5-closed/0068-Reviewed_RF_DETR_Local_Visible_Card_Detector.md) | Complete | M0–M4 complete: the reviewed RF-DETR candidate passed the frozen validation and sealed-test gate, was registered as an explicit selectable local segmentation provider, and left the Gemini default plus the existing 0067 PoC artifact unchanged. |
| [0067 — RF-DETR visible-region training campaign](5-closed/0067-RF_DETR_Visible_Region_Training_Campaign.md) | Complete | M0–M4 complete: a fixed RF-DETR SegMedium recipe produced an unpromoted `poc_candidate`. The locked validation gate passed against the unchanged pretrained baseline. The decision report retains corpus limits, source-linked errors, and the optional 0050 handoff. |
| [0062 — Canonical card-state data and face-down identity](5-closed/0062-Canonical_Card_State_and_Face_Down_Identity.md) | Complete | M0–M4 complete: active event data and contracts use the singleton `card_state_changed` value, immutable history remains readable, review and comparison surfaces use one canonical label, `FACE_DOWN` remains outside legal card identities, and the pre-reconstruction observation plus game-engine boundary preserves face-down status, exact visual outcome diagnostics, and source lineage without changing reconstruction. |
| [0064 — CardEvent frame-review editor](5-closed/0064-CardEvent_Frame_Review_Editor.md) | Complete | M0–M2 complete: the reviewed CardEvent editor uses the recording-owned exact source-frame surface, compact left review controls, responsive desktop and narrow layouts, and browser accessibility regression coverage while the right inspector remains unchanged. |
| [0065 — Visible-card ignore regions](5-closed/0065-Visible_Card_Ignore_Regions.md) | Complete | M0–M3 complete: reviewed ignore regions preserve generated lineage, remain separate from card targets, materialize deterministic masks or exact frame exclusions, and neutralize ignored predictions with explicit comparison counts. |
| [0066 — Card-state change interval annotation](5-closed/0066-Card_State_Change_Interval_Annotation.md) | Complete | M0–M4 complete: interval semantics, stable-end anchoring, fixtures, preservation checks, CardEvent viewer interval editing, range-aware Timeline Rail rendering, bound navigation, desktop/narrow browser coverage, interval-aware targets, negative evidence exclusion, diagnostics, and a bounded trick-clear review pilot are in place. |
| [0060 — iOS capture module boundaries](5-closed/0060-iOS_Capture_Module_Boundaries.md) | Complete | M0–M3 complete: evidence-package, repository-intake, recording, upload, and analysis boundaries are split with focused app workflow tests and unchanged UI-facing behavior. |
| [0061 — Card-state change and face-down pipeline](5-closed/0061-Card_State_Change_and_Face_Down_Pipeline.md) | Complete | M0–M3 complete: generic card-state events reach every visible-card input, side-aware candidates preserve face-up, face-down, and unknown evidence, face-down identity abstains explicitly, and observation plus game-engine contracts retain side without changing reconstruction decisions. |
| [0059 — Web workspace module boundaries](5-closed/0059-Web_Workspace_Module_Boundaries.md) | Complete | M0–M7 complete: route and URL-state helpers, recording shell, inspector/history, Timeline Rail coordination, event-stage ownership, visible-card stage ownership, visual-identity stage ownership, observation/round-analysis controls, and analysis presentation ownership have focused sources and regression proof. |
| [0058 — Backend pipeline service boundaries](5-closed/0058-Backend_Pipeline_Service_Boundaries.md) | Complete | M0–M4 complete: pipeline routes, execution, comparison, workspace composition, maintained-reference handlers, shared stores, and application construction have focused ownership with unchanged public contracts. |
| [0057 — Operations module and public API boundaries](5-closed/0057-Operations_Module_and_Public_API_Boundaries.md) | Complete | M0–M3 complete: the eager operations facade is removed, pipeline comparison and round reconstruction have direct contract and execution modules, and focused import and behavior checks pass. |
| [0056 — Superseded review and data interfaces](5-closed/0056-Superseded_Review_and_Data_Interfaces.md) | Complete | M0–M5 complete: removed the obsolete CardEventNet package-review and package-dataset commands, operations review orchestration, old batch stores, and old `doko data review` path; corrected active guidance and proved the retained command surface. |
| [0053 — Agent navigation cleanup discovery](5-closed/0053-Agent_Navigation_Cleanup_Discovery.md) | Complete | Published a first-hop repository map and repeatable baseline. Ranked six cleanup areas as epics 0055–0060 for separate Terra specification. No cleanup was implemented. |
| [0055 — Documentation authority and first hops](5-closed/0055-Documentation_Authority_and_First_Hops.md) | Complete | M0–M3 complete: the root authority route and component map are published, completed 0048/0049 handoffs no longer act as current guidance, and every executable component has an ownership and verification first hop. |
| [0048 — Pipeline data and execution](5-closed/0048-Pipeline_Data_and_Execution.md) | Complete | M0–M10 complete: recording-video pipeline execution, maintained references with coverage and downstream impact validation, immutable dataset consumer manifests with explicit source/policy/lineage inputs, and the 0049 cutover handoff. Real-data quality measurement remains in 0043 and 0050. |
| [0049 — Recording pipeline review and comparison](5-closed/0049-Recording_Pipeline_Review_and_Comparison.md) | Complete | M0–M10 complete: one recording-owned pipeline workspace for accepted video, generated and reviewed inputs, maintained references, reconstruction, comparison, analysis, and dataset readiness. Obsolete review-batch routes and duplicate recording state are removed. Real-data quality measurement remains outside this epic. |
| [0054 — Unified recording workspace layout](5-closed/0054-Unified_Recording_Workspace_Layout.md) | Complete | M0–M10 complete: one responsive recording workspace with a central source surface, shared inspector, and Timeline Rail. The retired comparison page/list is removed, and browser coverage verifies 1440px, 1280px, and narrow layouts. |
| [0047 — Current recording annotations and evidence](5-closed/0047-Current_Recording_Annotations_and_Evidence.md) | Superseded | Replaced before implementation by 0048 and 0049. Proposal loss and package management are not the target design. |
| [0041 — Local visual card identity classifier PoC](5-closed/0041-Local_Visual_Card_Identity_Classifier_PoC.md) | Complete | M0–M3 complete: local training, bundle, classifier runtime, and backend capability proved. Quality remains in 0043; new integration work belongs to 0048. |
| [0039 — Web recording data workspace](5-closed/0039-Web_Recording_Data_Workspace.md) | Complete | M0–M4 complete: recording workspace, event review, completion, and development partitions. Further data and review work belongs to 0048/0049. |
| [0022 — TableEvidenceAnalyzer capability development](5-closed/0022-Table_Evidence_Analyzer_Development.md) | Superseded | Retain completed implementation evidence. Foundation and UI work move to 0048/0049; remaining detector and capability experiments move to 0050; identity quality stays in 0043. |
| [0046 — Filesystem storage engine](5-closed/0046-Filesystem_Storage_Engine.md) | Complete | Validated filesystem resources are the only backend storage. Recording bundles, evidence packages, table observations, round analyses, pending videos, and operations data survive restart from canonical files without SQLite, SQLAlchemy, or Alembic. |
| [0038 — Visible-card training-data improvement](5-closed/0038-Visible_Card_Training_Data_Improvement.md) | Complete | Correct Gemini visible geometry and review visible regions with fixed source and teacher lineage. M0–M5 complete; real prompting and human review remain deferred. |
| [0045 — Card event review workflow improvements](5-closed/0045-Card_Event_Review_Workflow_Improvements.md) | Complete | Complete the wide video-first CardEvent workflow with recording-owned review resources, unified event lineage, verified source-context caching, stable review pages, optimistic ordered commands, retry and conflict recovery, and keyboard and pointer review-loop coverage. |
| [0040 — Visible-card annotation review workspace](5-closed/0040-Visible_Card_Annotation_Review_Workspace.md) | Complete | Create, correct, complete, and publish visible-card reviews with immutable lineage, revisions, lifecycle receipts, and existing-freeze-path readiness. |
| [0042 — Visual card identity annotation workspace](5-closed/0042-Visual_Card_Identity_Annotation_Workspace.md) | Complete | Create, review, publish, revise, and freeze visual card identity labels from source-linked visible-card reviews with immutable lineage, lifecycle receipts, and validated group-safe development data. |
| [0043 — First local DINOv3 card identifier](5-closed/0043-First_Local_DINOv3_Card_Identifier.md) | Complete | M0–M3 complete: the frozen reviewed corpus produced one measured, digest-verified, locally runnable DINOv3 development candidate. Validation reached 0.9402 top-1, 0.9801 top-3, and 0.9394 macro F1 over 301 crops; absent `NINE` and excluded `FACE_DOWN` remain explicitly unmeasured. No promotion or backend-default change was made. |
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

1. **Use the 0068 RF-DETR detector or the 0082 fine-frame refinement as a selectable local option.**
   Set `VISIBLE_CARD_PROVIDER=local-rfdetr-segmentation` or
   `VISIBLE_CARD_PROVIDER=local-rfdetr-fine-frame` only when the retained segmentation bundle is
   available; keep Gemini as the default provider.
2. **Continue 0063 with M15 only after the operator completes M14.** M14 created a development-only
   integration lock and exact one-time sealed-test and Core ML export/parity handoffs. Do not tune,
   promote, or treat M9 as the production champion.
3. **Use the completed 0060 iOS module boundaries as the current app ownership baseline.** Epic
   0057 is complete.
4. **Start 0044 from Ready.** Use the retained 0043 report to define promotion gates before any
   local cutover. Keep the 0043 bundle unpromoted until those gates pass.
5. **Keep 0050 blocked until a future fixed identity baseline and sufficient reviewed evidence
   exist.** Make it Ready only when a bounded detector/composed measurement has fixed inputs,
   metrics, thresholds, and a budget. Do not run an open-ended search.
6. **Keep 0043’s measured limits as the input to 0044.** Reuse 0048/0049 rather than introducing
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
- 0049 satisfies the recording-workspace dependency for 0051. M0–M2 are complete because the
  coverage contract, outcome-preservation boundary, and local deterministic crop conditions
  proceed without new review. The local operations store has
  no `pipeline-references` artifacts, so the baseline reports the paired-review gap and stops
  before validation classification.
- Add 0053 as an independent repository cleanup discovery pass. Optimize cleanup for lower agent
  navigation and context cost. Use three model tiers but only two epic levels: Sol discovers work
  areas, Terra specifies each work-area epic, and Luna implements its milestones. Do not create a
  separate implementation epic for every Luna milestone.
- Add 0054 as a presentation-only follow-up to completed 0048 and 0049. The current implementation
  puts duplicate stage summaries, selectors, history, and run controls before the video and repeats
  temporal navigation in lists or tables. Use one viewport shell, central task surface, right-side
  metadata inspector, and shared bottom Timeline Rail. Keep backend and persistence contracts
  unchanged.

### Planning decisions — 2026-09-07

- Close 0053 after its discovery-only M0. Its report records the first-hop repository map,
  repeatable baseline, retained candidates, rejected moves, and ranking. It changes no cleanup
  candidate.
- Add 0055 through 0060 as independent `To Specify` work areas. Use one Terra specification pass per
  area. Use Luna-sized delivery milestones inside each work-area epic and do not create a third epic
  layer by default.
- Specify documentation authority first and obsolete interfaces second. Then specify operations,
  backend, web, and iOS module boundaries. Preserve active epic ownership and close any candidate
  whose detailed consumer or dependency evidence does not justify delivery.

### Planning decisions — 2026-09-11

- Reconcile active epic 0051 after durable pipeline revisions moved from `.runtime` to
  `data/operations` and the runtime adopted polygon crop defaults. Do not alter closed cleanup epics
  to record this active-work consequence.
- Treat `IMG_0090` and `IMG_0091` as one visually similar development comparison group for 0051.
  They cannot alone prove independent validation coverage even when their imported session
  identifiers differ.
- Use the newly imported `IMG_0661` recording as the intended different validation source after its
  visible-card and visual identity maintained references are complete.
- Keep 0052, 0043, and 0050 blocked until 0051 publishes its frozen comparison and decision.
- 0061 is complete as the small pre-reconstruction processor correction. CardEventNet emits only
  generic `card_state_changed` proposals. Visible-card detection processes every event and keeps
  all three card sides. Visual identity abstains explicitly on face-down cards. Observation
  assembly and the game-engine parser preserve the side, while reconstruction behavior, new side
  processors, and temporal association stay out of scope.
- 0051 must use the completed 0061 side and identity semantics when it freezes another classifier
  comparison.
- Add 0062 because 0061 left the retired event taxonomy in active annotations and UI and represented
  face-down as generic unusable identity evidence. Canonicalize current event data and make
  `FACE_DOWN` a visual class outside the 24 legal card identities.
- Use the completed 0062 contracts before 0051 freezes another classifier comparison. Keep semantic
  event prediction, new processors, temporal association, model training, and reconstruction
  behavior out of scope.

### Planning decisions — 2026-09-13

- Add 0065 for ambiguous untidy card stacks found during `IMG_0661` visible-card review. An ignore
  region is reviewed data beside card candidates. It is not a card, card side, identity-usability
  value, or model class.
- Preserve all generated Gemini candidates. Let one atomic human-review operation replace selected
  maintained-reference candidates with one `untidy_stack` ignore region and retain their source
  revision and candidate IDs.
- A mixed frame keeps its normal card targets. Dataset consumers must mask ignored pixels or exclude
  the complete frame explicitly. They must never learn ignored pixels as ordinary background.
- Complete 0065 before 0051 freezes affected `IMG_0661` items. Keep segmenter training and provider
  selection in later epic 0050.

### Planning decisions — 2026-09-15

- Complete 0051 M0 reconciliation against the shared repository validator and durable
  `data/operations` revision store. Freeze `cardeventnet-IMG_0090` and `cardeventnet-IMG_0091` as
  development and `cardeventnet-IMG_0661` as validation.
- The completed `IMG_0661` visual identity reference opens the M0 coverage gate. The generated M0
  artifact records 200 available development pairs, 100 validation pairs, a bounded 4,920-request
  preflight, and five explicit identity exclusions without classifying any crop.
- Complete 0051 M3 implementation with a dry-run planner, resumable crop receipts, pinned
  classifier-result receipts, and retained paired comparison output. Keep the live provider run as
  an explicit operator action within the frozen budget.

### Planning decision — 2026-09-17

- Move 0043 to Ready for the first local reviewed DINOv3 candidate. The current selected references
  already meet its `doko-40-v1` face-up train and validation coverage gate.
- Keep corpus membership open until the M1 freeze so newly completed human references can enter the
  first run through the existing split and eligibility rules.
- Do not make the live 0051 comparison or conditional 0052 response prerequisites for the first
  local candidate. They remain inputs to later resilience or quality work.
- The first candidate remains unpromoted. Missing `NINE` data and intentionally excluded
  `FACE_DOWN` outcomes are explicit unsupported classes, not inferred quality. The current
  face-down outcomes mostly come from untidy stacks without trustworthy ignore-region treatment
  and do not enter the first campaign.
- The operator runs real pretrained-weight acquisition and training. The agent completes short
  preflight work and supplies one exact concrete command for each long-running operation.

### Planning decision — 2026-09-18

- Add 0070 as a Ready, bounded synthetic visible-region training-data experiment. It builds on the
  completed reviewed RF-DETR detector and does not depend on the blocked composed-quality epic
  0050.
- Use operator-marked single-card frames for clean cutouts and reviewed complete quadrilaterals for
  table-setup-specific perspective examples. Do not claim that one card identifies a global camera
  homography.
- Use only 0068 training-partition source material for cards, backgrounds, geometry, image
  distributions, and optional reviewed occluders. Synthetic scenes can enter training only. Keep
  real validation and sealed-test data unchanged and free of synthetic contributors.
- Generate exact visible-region masks from compositing order, clipping, and occlusion. Do not ask
  Gemini to label generated scenes and do not synthesize visible-card ignore regions.
- Judge the experiment on real held-out quality and measured human correction effort. Do not
  promote a provider or change a runtime default in 0070.

### Planning decision — 2026-09-22

- Add 0074 as a Ready presentation-only consolidation after completed 0073. Treat source-frame
  polygons, virtual cards, ignore regions, detector suggestions, and mapping diagnostics as layers
  of one selected visible-card frame, not as separate review products.
- Use four independent UI dimensions: one Camera or Rectified viewpoint, zero or more visible
  layers, one visible-region, virtual-card, or mapping edit tool, and one stable contextual command
  bar.
- Use one button to toggle Camera and Rectified. Use one pressed or unpressed button for each
  visibility layer. Remove dedicated zoom, pan, and fit buttons; retain direct mouse and trackpad
  gestures plus focused-surface keyboard controls.
- Keep Accept card, Accept anchor, Apply mapping, and Accept frame explicit and distinct. Keep
  temporal navigation in the Timeline Rail. Do not change backend contracts, review authority,
  immutable lineage, calibration behavior, or dataset semantics.
- Remove the replaced polygon and pose-editor presentations after their behavior moves to the
  shared workbench. Do not retain compatibility paths for the undeployed UI structure.

## Closed-epic policy

Closed epic files are immutable historical records. Do not update them for new terminology,
architecture, or planning policy. Add later evidence to the earliest active epic that owns the
issue. Create a bounded follow-up epic only when no active epic owns it.

Change a closed epic only after an explicit user request, to remove restricted information, or to
repair a link after an authorized move or rename. Keep the exception mechanical and minimal. Do not
reopen or rewrite the closed plan through an exception.
