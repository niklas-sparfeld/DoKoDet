# Local end-to-end recording pipeline

## Plan status

- **Summary:** Run the automatic stages in sequence on a small fixed recording batch and measure
  the composed result with explicit model, input, and failure lineage.
- **Status:** Closed
- **Closure reason:** Complete
- **Depends on:** Completed 0087 and 0088 bundle decisions; completed 0089 no-fix algorithm handoff;
  completed 0092 M4 final refit; completed 0048 and 0049; completed 0091 M7 pile feature handoff.
- **Readiness:** The 0089 replay found no isolated algorithm defect and does not select an
  algorithm change. The 0088 identity decision is available:
  M6 seed 17 is the primary diagnostic bundle and M3 seed 17 is available as a paired diagnostic;
  both are unqualified and all identity proposals require human review. See the
  [0088 M15 handoff](../../reports/0088-M15_Qualification_Decision.md).
- **Outcome:** A resumable local coordinator and a retained measurement report for a three-recording
  development pilot. The report records partial scene results and explains why no composed quality
  claim is available.
- **M0:** Complete — freeze the three-recording development batch, exact source and review
  revisions, model bundles, automatic crop policy, budgets, and coverage gates. See the
  [M0 pilot freeze](../../reports/0090-M0_Composed_Pilot_Freeze.md).
- **M1:** Complete — add a resumable local coordinator around retained stages. See the
  [M1 coordinator report](../../reports/0090-M1_Retained_Pipeline_Coordinator.md).
- **M2:** Complete — verify coordinator restart, cancellation, stale-input protection, status reads,
  and fresh reruns. See the [M2 durability report](../../reports/0090-M2_Durable_Execution.md).
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — freeze the recording scope, stage recipe, references, and metrics. See the
  [M0 pilot freeze](../../reports/0090-M0_Composed_Pilot_Freeze.md).
- **M1:** Complete — coordinate the declared stage order, persist request and revision lineage,
  reuse unchanged completed stages, and stop on terminal failures. See the
  [M1 coordinator report](../../reports/0090-M1_Retained_Pipeline_Coordinator.md).
- **M2:** Complete — persist interruption state, resume with the same processor request, stop
  scheduling after cancellation, read status without worker calls, and require a fresh run ID for
  an explicit rerun. See the [M2 durability report](../../reports/0090-M2_Durable_Execution.md).
- **M3:** Complete — run the frozen three-recording batch and report stage results, timing, failures,
  and coverage limits. See the [M3 composed pilot report](../../reports/0090-M3_Composed_Pilot.md).

## 1. Scope and authority

Reuse durable processor runs, immutable input selections, and comparison boundaries. Start with
a local CLI or application coordinator; add UI only for a measured blocker. Freeze explicit
CardEventNet, RF-DETR, DINO, crop policy, and algorithm versions. Do not silently choose the newest
bundle, fall back to Gemini, retrain, or promote a model.

Use the 0092 M4 final refit as the visible-card bundle. It supersedes the 0087 M3 candidate for this
pilot and includes the `card_pile` class. Keep `gemini` as the runtime default. Use M6 seed 17 as
the declared diagnostic identity bundle and retain M3 seed 17 for a paired diagnostic when useful,
using the exact bundle and report-only confidence routing policy in the
[0088 M15 handoff](../../reports/0088-M15_Qualification_Decision.md). Retain 0088's model
qualification result beside its bundle decision. M6 remains unqualified; every identity proposal
requires human review. This condition is not evidence that the composed pipeline is ready for
productive use.
0093/0094 implementation remains outside this coordinator.

The primary pilot uses automatic upstream outputs from the accepted video: event proposals,
visible-card detection, required calibration and proposed card scenes, visual identity,
table observations, and reconstruction. M0 must specify exactly which stages consume which
outputs. A reviewed scene can be a separate diagnostic input, but must not be described as
fully automatic inference. If the chosen identity crop requires reviewed geometry, define and
verify a separate generated-geometry execution contract or retain a compatible automatic crop
policy. This epic cannot bypass 0085's reviewed-input authority checks.

[0091](../5-closed/0091-Pile_Region_Feature.md) owns pile support at the individual boundaries.
Its [M7 handoff](../../reports/0091-Pile_Region_Capability_Handoff.md) documents the software
capability. The selected 0092 M4 refit now provides a real two-class bundle. Freeze its capability
and observation versions in the coordinator. Keep pile detections separate
from individual cards, bypass identity and pose work for piles, and retain pile evidence through
engine input. Distinguish retained but unused pile evidence from gameplay inference. If the
selected bundle cannot detect piles, declare that coverage limit before the pilot; do not hide
it as an empty pile collection or silently use a different model.

Use a small varied development batch with reviewed event, geometry, identity, and reconstruction
coverage where available. Keep reviewed targets separate from execution inputs. System holdout
remains sealed; a later authorized locked system evaluation is separate from this development pilot.

No new model campaign, algorithm research, full review workflow, productive promotion UI, or
production deployment belongs here. Broader capability selection stays in
[0050](0050-Detector_Quality_and_Analyzer_Capabilities.md); productive identity operations stay in
[0044](../1-backlog/0044-Productive_Local_Identity_Model_Operations.md).

## 2. Delivery milestones

### M0 — Freeze the composed pilot

Select a small fixed batch that includes clean and overlapping cards, staged activity and real
rounds where eligible, and at least one known failure case. Freeze model bundles, source groups,
stage inputs, frame extraction, time and resource budgets, expected outputs, and reference coverage.
Declare quality and operational gates before execution, including missing reviewed reconstruction
coverage. Verify the chosen crop policy is valid for automatic inputs.

Acceptance: deterministic preflight; every prerequisite and input is explicit; no protected
development source; no hidden human-reviewed execution input; no stage starts during preflight.

### M1 — Coordinate the retained stages

Add the smallest sequential coordinator around existing application boundaries. Persist each
stage's request, state, exact input and output revisions, and terminal failure. Stop dependent work
when an upstream prerequisite fails. Continue other recordings only under the frozen batch policy.

**M1 outcome:** The `dokodetector-pipeline-coordinator` command reads a request file and calls the
local backend stage APIs in the frozen order. Reconstruction requires explicit round context or an
explicit skip decision. See the [M1 coordinator report](../../reports/0090-M1_Retained_Pipeline_Coordinator.md).

Acceptance: one local command starts the declared sequence; completed unchanged stages are reused;
request acceptance is not reported as completion; fixtures prove exact output-to-input lineage.

### M2 — Verify durable execution behavior

Use local failure injection to verify cancellation, backend restart, interrupted checkpoints,
stale inputs, and explicit rerun. Check that status reads do not wait on worker completion and that
the coordinator can resume without browser presence or duplicate stage execution.

Acceptance: terminal and partial failures are actionable; downstream stages do not consume failed
or mismatched revisions; cancellation and restart preserve completed artifacts; no silent cloud
fallback; relevant persistence and lifecycle tests pass.

**M2 outcome:** The coordinator keeps completed stage outputs across interruption and cancellation.
It resumes an interrupted stage with the same processor run ID. A changed request or input lineage
gets a new run ID, and downstream stages receive only outputs validated earlier in the current
sequence. `--status` reads the local manifest. `--cancel` asks the coordinator to stop polling and
scheduling stages. The backend worker can continue its current stage; a later resume attaches to the
same durable request. `--rerun` starts a new coordinator run with new processor IDs. See the
[M2 durability report](../../reports/0090-M2_Durable_Execution.md).

### M3 — Execute and measure the pilot

Run the frozen batch and retain automatic predictions, stage timings, failures, and reconstruction
results. Compare against declared reviewed coverage. Report event, segmentation, identity,
observation, and reconstruction quality separately, then report the composed result. Measure
operator intervention and distinguish diagnostic reviewed-input runs from automatic runs.

Acceptance: a reproducible stage-by-stage report explains each failed recording and missing
reference; quality claims match review coverage; no tuning from system holdout; broader work is
captured as a separate measured follow-up. No production default or promotion changes occur.

## 3. Verification

Use local fixture pipelines, recorded video, mocks, and bounded real execution. Run focused
operations, backend stage, persistence, comparison, and reconstruction checks plus applicable
static checks. Test web code only if this epic changes it.
