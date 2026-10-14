# Reviewed virtual-card RF-DETR campaign

## Plan status

- **Summary:** Train and compare RF-DETR candidates from reviewed individual-card masks and
  coarse pile targets, with one compatible synthetic-data addition where supported.
- **Status:** Closed
- **Closure reason:** Complete
- **Depends on:** Completed 0068 and 0070; 0091 M0–M3 for two-class preparation; 0086 M2
  detection-only handoff with reviewed geometry, visible-card masks, ignore or frame-exclusion
  decisions, pile coverage, and source-group assignments. Visual identity review is not required.
- **Supersedes:** Unstarted training in 0084; retain its M0–M2 evidence as historical inspection
- **Outcome:** Verified segmentation views, bounded training, one sealed-test evaluation, and a
  selectable candidate bundle. The runtime default remains unchanged.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-10-13) — audited the three eligible references, source permissions,
  source groups, and prior evaluation use. The persisted stage-use values mirror old data splits;
  the original `project_use` permission allows all campaign stages. Froze the split, checkpoint,
  recipe, candidate counts, budgets, and gates. See the [M0 readiness report](../../reports/0087-M0_Reviewed_RF_DETR_Campaign_Readiness.md)
  and [frozen manifest](../../reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json).
- **M1:** Complete (2026-10-14) — materialized and inspected 130 frames from the three current
  reviewed references. Validation has 36 pile targets; the sealed test has none. See the
  [M1 materialization report](../../reports/0087-M1_Reviewed_Real_Mask_Materialization.md).
- **M2:** Complete with a declared gap (2026-10-14) — omit the synthetic candidate because the
  frozen training group has no approved empty background, and the available 0070 pools use other
  source groups or obsolete geometry. See the [M2 readiness report](../../reports/0087-M2_Synthetic_Addition_Readiness.md).
- **M3:** Complete (2026-10-14) — trained one real-only candidate for 6,503.74 seconds and
  evaluated 40 validation frames. Aggregate validation gates passed; visible-card false predictions
  rose from 0 to 2 while pile false predictions fell from 20 to 0. The sealed test remains unopened.
  See the [M3 training report](../../reports/0087-M3_Real_Only_Training.md).
- **M4:** Not applicable — M2 found no eligible synthetic pool; do not train a mixed candidate.
- **M5:** Complete (2026-10-14) — locked the candidate decision before opening the sealed test,
  evaluated the candidate and baseline once, and registered the candidate as selectable. See the
  [M5 decision report](../../reports/0087-M5_Sealed_Test_and_Bundle_Decision.md) and
  [pretest decision lock](../../reports/0087-M5_Pretest_Decision.json).

## 1. Boundaries and evidence

This campaign uses completed human-reviewed individual-card scenes and pile regions under
[0091](../5-closed/0091-Pile_Region_Feature.md). Unreviewed proposed scenes and review drafts are
not targets. Do not reuse the 0084 mask view as corrected training data: its inspection
found human-hand label spill, and its geometry predates the current measured dimensions. RF-DETR
learns visible-card regions, so visual identity labels and identity-processor runs are outside this
campaign's inputs and gates.

For imported CardEventNet sources, use M0's permission audit to resolve effective campaign uses.
The old `allowed_uses` field can mirror a historical data split and must not replace the original
`source_permission` value when the two conflict.

The 0086 inventory has 22 `project_use` development candidates. The current M0 freeze uses the
three candidates with completed references in the detection handoff. Keep the wider pool as the
target for later corpus updates. Do not use incomplete references or mutable drafts to reach a
recording count. If 0086 adds eligible references, review the source-group split and freeze a new
M0 manifest before rematerialization or training.

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

If the frozen training groups have no compatible synthetic source, omit the candidate under the M0
rule. Record the missing assets and the reasons that existing pools cannot be reused. M4 then does
not run.

### M3 — Run real-only training

Run only the declared M0 real-only candidates with resumable checkpoints and durable logs. Retain
environment, timings, source and recipe digests, bundles, and real validation predictions.

Acceptance: selection uses only frozen validation; metrics reproduce from retained predictions;
the report distinguishes added reviewed-data effects from comparison limits; no test or promotion.

### M3 implementation evidence — 2026-10-14

- The shared campaign trainer now validates the 0087 frozen manifest, M1 split, two-class labels,
  checkpoint pin, and 7,200-second budget. It retains the 0087 identity in the run record and bundle.
- One candidate trained on 42 frames from `IMG_0095`. RF-DETR stopped at epoch 15 by the frozen
  patience-8 rule. The run took 6,503.74 seconds. Checkpoint SHA-256 is
  `d89c5502b3ff01ed673c2ba04e0a8168c9d1efe3d99c064dcafefdc314aea3fa`; bundle digest is
  `018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9`.
- Validation used the pinned pretrained baseline and the candidate on the unchanged 40-frame
  validation partition. Visible-card mask AP and recall were `0.870065` and `0.961165`; pile mask
  AP and recall were `0.958076` and `1.000000`. False predictions fell from 20 to 2, duplicate
  predictions stayed at 0, and the empty prediction rate fell from 0.500 to 0.000. The two false
  candidate predictions are visible cards; the baseline's 20 false predictions are piles.
- The 0087 evaluator now retains two-class validation predictions with missing `card_side` values
  on pile targets treated as unknown to side slices. It does not open the 0087 sealed test during
  M3. Validation report and prediction digests are in the
  [M3 training report](../../reports/0087-M3_Real_Only_Training.md).
- This result uses one eligible training reference and has no paired retraining control. The other
  19 development candidates with incomplete references were not added. No bundle promotion or
  runtime-default change occurred.

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
detection-handoff digest, compares original CardEventNet permissions with persisted stage-use
values, audits source groups, excludes prior evaluation groups, pins the RF-DETR 1.9.4 checkpoint,
and writes the deterministic M0 manifest. Seven imported records have stage-use values that mirror
historical splits despite `source_permission: project_use`. The selected validation group has 36 pile
targets and meets the two-class minimum. The sealed test has no pile targets. No training or
inference was run.

### M1 implementation evidence — 2026-10-14

- `operations/scripts/materialize_0087_m1.py` joins the frozen M0 split to its digest-pinned 0086
  handoff, verifies source bundles and permission metadata, then uses the shared exact-frame and
  mask materializer.
- The view contains 42 train frames, 40 validation frames, and 48 sealed-test frames. It has 338
  reviewed visible-card targets and 74 pile targets. The sealed test has zero pile targets.
- COCO validation accepted every card polygon and pile RLE mask. The verified local view digest is
  `cc0891f04f8e9e4a59790e9f3eac52d91bdaeaf85b43a5a84a7aa563de119e29`.
- Eleven overlays covered beginning, middle, end, and pile-dense frames across all selected
  recordings. Full-resolution overlays were inspected for each recording. Human-hand pixels were
  not included in card masks.
- The pinned RF-DETR 1.9.4 checkpoint loaded with the frozen two-class configuration. Its 90-class
  detection head was reinitialized to two classes. No training or inference ran.
- See the [M1 materialization report](../../reports/0087-M1_Reviewed_Real_Mask_Materialization.md)
  for the digests and repeatable command. The generated view is disposable under `.runtime`.

### M2 implementation evidence — 2026-10-14

- The frozen M0 split assigns only `cardeventnet-IMG_0095` to training. Its M1 view contains 42
  reviewed frames. The 0070 approved empty-table set contains no `IMG_0095` background.
- The 0070 planar production pool uses nine other recordings. Its manifest is digest-pinned, but
  those backgrounds and geometry do not belong to the frozen 0087 training group. The older
  all-recordings pool has an `IMG_0095` scene, but it uses the superseded card-region inpainting
  background strategy.
- The planar pool freezes card aspect ratio `1.5`. Current card-plane geometry uses `91/59`
  (`1.542373`). Reusing those scenes would violate M2's current-geometry requirement.
- M0 permits omission when no compatible two-class pool is available. No synthetic images were
  added, and no mixed training view was created. The unchanged real validation and sealed-test
  partitions remain the M1 views. M4 is therefore not applicable.
- See the [M2 readiness report](../../reports/0087-M2_Synthetic_Addition_Readiness.md) for the
  source manifests, digests, and reproducible audit facts.

### M5 implementation evidence — 2026-10-14

- The pretest decision lock pins the M0 manifest, M1 materialization, M3 validation report, training
  run, and candidate bundle. It permits one baseline/candidate pass and makes candidate selection
  conditional on nonzero visible-card recall for every sealed-test recording.
- The lock passed M0's measured validation gates. The sealed test had 48 retained frames and 130
  visible-card targets, above the frozen minimum. It had no pile targets.
- One sealed-test pass used the baseline and candidate on all 48 frames. Candidate visible-card
  mask AP 50:95 was `0.858450`, recall was `1.000000`, false predictions were 0, and duplicate
  predictions were 0. Baseline recall was 0 with 35 false predictions. Every target was detected.
- The candidate passed the frozen recall gate and is registered as a selectable
  `local-rfdetr-segmentation` provider. The registry keeps `gemini` as default. No automatic provider
  or runtime default changed.
- The local bundle loader verified the exported bundle, M0/M1 lineage, and checkpoint digest before
  inference. Mean candidate inference time was `1,311.377 ms/frame` on MPS; model load time was
  `435.727 ms`. Baseline means were `267.462 ms/frame` and `3,425.909 ms` load time.
- The selected bundle digest is
  `018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9`; checkpoint SHA-256 is
  `d89c5502b3ff01ed673c2ba04e0a8168c9d1efe3d99c064dcafefdc314aea3fa`. Its local path and the
  retained one-time prediction artifacts are in the [M5 decision report](../../reports/0087-M5_Sealed_Test_and_Bundle_Decision.md).
- This result covers one training recording and one sealed-test recording. The sealed test has no
  pile targets, and the reviewed data has no empty-background frames. It makes no pile-quality,
  empty-scene, or broad recording-generalization claim. Human-hand, ordinary-overlap, and pile-edge
  slices remain unavailable.
