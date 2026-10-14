# Local end-to-end recording pipeline

## Plan status

- **Summary:** Run the automatic stages in sequence on a small fixed recording batch and measure
  the composed result with explicit model, input, and failure lineage.
- **Status:** Blocked
- **Depends on:** 0087 and 0088 bundle decisions; 0089 algorithm handoff; completed 0048 and 0049
  0091 M7 pile feature handoff and explicit real pile-model capability decision.
- **Blocker:** Fixed model and algorithm decisions for the composed run are not available.
- **Outcome:** A resumable local coordinator, retained stage results, and a measured development
  pilot from video through reconstruction.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — freeze recording scope, stage recipe, references, and metrics.
- **M1:** Not started — implement or reuse sequential execution over retained stage boundaries.
- **M2:** Not started — verify restart, cancellation, and failure behavior.
- **M3:** Not started — run the development pilot and publish the composed result.

## 1. Scope and authority

Reuse durable processor runs, immutable input selections, and comparison boundaries. Start with
a local CLI or application coordinator; add UI only for a measured blocker. Freeze explicit
CardEventNet, RF-DETR, DINO, crop policy, and algorithm versions. Do not silently choose the newest
bundle, fall back to Gemini, retrain, or promote a model.

Retain 0088's model qualification result beside its bundle decision. An unqualified bundle is an
explicit diagnostic condition, not evidence that the composed pipeline is ready for productive use.
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
capability and the current absence of a selected trained pile model.
Freeze its capability and observation versions in the coordinator. Keep pile detections separate
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

Acceptance: one local command starts the declared sequence; completed unchanged stages are reused;
request acceptance is not reported as completion; fixtures prove exact output-to-input lineage.

### M2 — Verify durable execution behavior

Use local failure injection to verify cancellation, backend restart, interrupted checkpoints,
stale inputs, and explicit rerun. Check that status reads do not wait on worker completion and that
the coordinator can resume without browser presence or duplicate stage execution.

Acceptance: terminal and partial failures are actionable; downstream stages do not consume failed
or mismatched revisions; cancellation and restart preserve completed artifacts; no silent cloud
fallback; relevant persistence and lifecycle tests pass.

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
