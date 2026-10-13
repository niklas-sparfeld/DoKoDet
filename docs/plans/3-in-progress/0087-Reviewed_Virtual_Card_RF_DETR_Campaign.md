# Reviewed virtual-card RF-DETR campaign

## Plan status

- **Summary:** Train and compare RF-DETR candidates from reviewed individual-card masks and
  coarse pile targets, with one compatible synthetic-data addition where supported.
- **Status:** In Progress
- **Depends on:** Completed 0068 and 0070; 0091 M0–M3 for two-class preparation; 0086 M2
  detection-only handoff with reviewed geometry, visible-card masks, ignore or frame-exclusion
  decisions, pile coverage, and source-group assignments. Visual identity review is not required.
- **Supersedes:** Unstarted training in 0084; retain its M0–M2 evidence as historical inspection
- **Outcome:** Verified segmentation views, bounded training, real evaluation, and a retained bundle
  decision. Improvement is measured, not assumed.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-10-13) — audited the three eligible references, source permissions,
  source groups, and prior evaluation use. Froze the split, checkpoint, recipe, candidate counts,
  budgets, and gates. Two-class training readiness is blocked because validation has no pile
  targets; no sealed-test group is available. See the [M0 readiness report](../../reports/0087-M0_Reviewed_RF_DETR_Campaign_Readiness.md)
  and [frozen manifest](../../reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json).
- **M1:** Not started — materialize and inspect the real segmentation view.
- **M2:** Not started — regenerate and inspect the synthetic addition.
- **M3:** Blocked — the only validation-permitted reference has zero pile targets, below the
  frozen minimum of 30. Do not train until validation has pile-positive support or the two-class
  quality gate changes through a reviewed plan update.
- **M4:** Not started — train the declared synthetic mixture and compare on real validation.
- **M5:** Not started — publish the locked evaluation and bundle decision.

## 1. Boundaries and evidence

This campaign uses completed human-reviewed individual-card scenes and pile regions under
[0091](../5-closed/0091-Pile_Region_Feature.md). Unreviewed proposed scenes and review drafts are
not targets. Do not reuse the 0084 mask view as corrected training data: its inspection
found human-hand label spill, and its geometry predates the current measured dimensions. RF-DETR
learns visible-card regions, so visual identity labels and identity-processor runs are outside this
campaign's inputs and gates.

Reuse the 0068 SegMedium trainer, evaluation, bundle, and provider boundaries. Reuse the 0070
synthetic generator. Its historical 50/50 comparison improved real validation mask AP from
0.813872 to 0.830406 and recall from 0.973404 to 0.984043. That experiment does not authorize
promotion or prove a new mixture will improve the corrected corpus.

This epic does not train DINO, tune pose fitting, change runtime defaults, or implement end-to-end
automation. [0088](../4-blocked/0088-Reviewed_Virtual_Card_DINO_Campaign.md) is independent of its
training result.

## 2. Campaign rules

Freeze source groups, selected references, mask policy, model package and checkpoint, resolution,
seed, augmentation, optimizer, checkpoint-selection rule, resource budget, and acceptance gates
before training. Use completed reviewed visible regions derived from corrected scenes. Project
rounded outlines and remove card-card occlusion, then apply reviewed non-card exclusions. Reject
unresolved occlusion, invalid calibration, empty masks, and unsupported loss masking with receipts.
RLE encoding must preserve holes and disconnected components through the pinned trainer.

Use 0091's fixed two-class mapping: precise `visible_card` masks and coarse `card_pile` footprints.
Piles are ordinary positive targets, not ignores or `iscrowd` annotations. Consumed group members
do not become individual targets. Freeze the footprint and pixel-ownership policies separately
from precise-card masks. Pile-bearing frames require reviewed pile coverage; older references
do not establish pile negatives. Genuine ignores retain explicit loss-safe exclusions.

0091 implements export, trainer, evaluator, bundle, and runtime support. This epic runs the real
campaign and owns its budgets and numerical quality gates. Preparation requires 0091 M0–M3;
M5's pile-capable inference verification requires M4, not completion of 0091. Neither epic waits
for the other's complete closure. Missing real pile support blocks a pile-model quality claim.

0091 M3 pins RF-DETR 1.9.4, category IDs 1=`visible_card` and 2=`card_pile`, reviewed-card pixel
priority, and uncompressed column-major pile RLE. Its evaluator reports class-specific mask and box
metrics, class confusion, pile-contained card predictions, and card recall near piles. Fixture and
one-epoch trainer smoke results establish software support only; they do not select a candidate or
establish a quality gate. Treat the two-class bundle as a training artifact until 0091 M4 completes
provider and proposal handling.

0091 M7 completes provider and downstream software handling. See its
[capability handoff](../../reports/0091-Pile_Region_Capability_Handoff.md) for the reproducible
fixture command and bounded one-frame real-bundle smoke procedure. 0087 remains responsible for
the trained-model decision and numerical quality gates.

M0 must first reconcile historical split and test usage. Do not silently reuse a previously opened
sealed test as a fresh sealed test. Freeze either an eligible unopened test or explicitly label
previously observed data as diagnostic evaluation. Never move a protected group into training.

Freeze at most one real-only control and one corrected-real-only candidate for M3. Use a paired
retraining control only if an unchanged common validation partition and compatible source-group
assignments exist. Otherwise select the retained baseline bundle and state the limit on attribution.
M4 adds one fixed real-plus-synthetic candidate to the corrected real view. Keep real-sample exposure
equal between corrected-real-only and mixed candidates; report added synthetic compute separately.
Do not sweep ratios, seeds, model sizes, or thresholds.

Synthetic contributors must come from training groups only, including card cutouts, reviewed empty
backgrounds, geometry, and calibration. Retain exact contributor lineage. Synthetic frames are not
independent real coverage. Evaluate only on real reviewed frames.
Existing synthetic individual-card overlaps are not pile labels. Freeze their two-class exposure
and target compatibility explicitly. Pile synthesis is not part of 0091; omit the synthetic
candidate with a recorded reason if this campaign cannot define a compatible pool.

## 3. Delivery milestones

### M0 — Freeze detection inputs and decisions

Audit the detection-only 0086 handoff and prior evaluation usage. Select only completed, eligible
visible-card references and source groups. Record per-frame ignore-region masks or explicit frame
exclusions. Freeze the comparison design, candidates, counts, minimum support, recipes, budgets, and
numerical gates. Include mask AP, recall, false detections, duplicates, empty predictions, and
per-recording coverage. Freeze overlap, small-card, frame-edge, and human-hand slices where real
support exists. Do not wait for visual identity completion.
Freeze individual-card metrics separately from pile localization and classification, pile/card
confusion, fragments predicted inside piles, and individual-card recall near piles. Include
ordinary overlapping tricks as a confusion slice. Aggregate AP is not a sufficient gate.

Acceptance: immutable manifest and deterministic readiness; no protected contributor enters training;
candidate count and total budget are fixed; missing support blocks training with exact reasons.

### M1 — Materialize reviewed real masks

Extract exact source frames and materialize corrected visible instance masks. Retain ignored-pixel
or frame-exclusion receipts, tight boxes, source and geometry digests, and reviewed-reference lineage.
Include coarse pile targets under 0091's policy and verify that consumed cards are absent from
individual targets. Pile-only images remain positive training samples.
Inspect overlays from every recording and all declared risk slices. Smoke-load through pinned RF-DETR.

Acceptance: cold and warm views have equal digests; decoded trainer masks match source masks;
human-hand pixels are excluded; no conflicting targets share an exact frame; visual review and
finite-target smoke checks pass before training.

### M2 — Prepare the synthetic addition

Regenerate one frozen synthetic pool with current physical geometry from eligible training-only
cutouts and backgrounds. Freeze the mixture and sampling policy. Inspect overlays and smoke-load
the merged view. Record generator coverage gaps, including card sides and appearance variation.

Acceptance: deterministic rendering and exact mask ownership; unchanged real evaluation views;
no held-out contributor; inspected pool and mixture digests match the training manifest.

### M3 — Run real-only training

Run only the declared M0 real-only candidates with resumable checkpoints and durable logs. Retain
environment, timings, source and recipe digests, bundles, and real validation predictions.

Acceptance: selection uses only frozen validation; metrics reproduce from retained predictions;
the report distinguishes added reviewed-data effects from comparison limits; no test or promotion.

### M4 — Measure the synthetic mixture

Run the one fixed mixed candidate. Compare it with the corrected-real-only candidate on identical
real validation data and slices. Retain resource use and unchanged real exposure evidence.

Acceptance: the report states improved, harmed, or inconclusive outcomes; no extra candidate is
trained from observed failures; synthetic quality never replaces real validation.

### M5 — Publish the evaluation and bundle decision

Lock the selected candidate and decision before any eligible sealed-test execution. Run that test
once only if the frozen gate and authorization permit it. Otherwise record why it did not run.
Verify export, load, local inference, latency, and lineage. Register an explicit selectable bundle
only if M0's gates permit it; retain a failed candidate as an experiment. Leave defaults unchanged.

Acceptance: decision report, predictions, bundle digests, evaluation history, limitations, and next
actions are reproducible. Hand the exact selected bundle or retained baseline to
[0089](../4-blocked/0089-Virtual_Card_Algorithm_Edge_Cases.md) and
[0090](../4-blocked/0090-Local_End_to_End_Recording_Pipeline.md). A negative campaign outcome still
permits a handoff.

## 4. Verification

Use focused operations materialization, mask, exclusion, split, and reproducibility tests. Use trainer
smoke, evaluation, resume, export, and local provider checks. Run relevant Python static checks.
No cloud infrastructure or real capture hardware is required.

### M0 implementation evidence — 2026-10-13

The read-only freeze command is `operations/scripts/freeze_0087_m0.py`. It validates the 0086
detection-handoff digest, audits source permissions and source groups, excludes prior evaluation
groups, pins the retrievable RF-DETR 1.9.4 checkpoint, and writes the deterministic M0 manifest.
The live 0086 handoff rebuilt to the same digest as the checked-in report. M0 is frozen, but two-class
training readiness is blocked: the only evaluation-permitted group has no reviewed pile positives.
No training or inference was run.
