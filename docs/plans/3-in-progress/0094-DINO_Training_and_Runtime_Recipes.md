# DINO training and runtime recipes

## Plan status

- **Summary:** Deliver reproducible multi-resolution DINO recipes, bounded encoder adaptation,
  25-class evaluation, and reloadable confidence-aware local bundles.
- **Status:** In Progress
- **Depends on:** Completed [0093](../5-closed/0093-Visual_Classification_Annotation_and_Crop_Inputs.md)
  annotation/crop handoff; existing materialized and licensed 0043 pretrained assets and local
  training/runtime infrastructure. No dependency on completed 0086 M5 or new 0088 model results.
- **Outcome:** Tested software recipes and exact local runtime/bundle contracts for
  [0088](../4-blocked/0088-Reviewed_Virtual_Card_DINO_Campaign.md), without a model-quality claim.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — freeze supported recipe, feature, checkpoint, and bundle contracts in
  [the M0 contract](../../reports/0094-M0_Recipe_Contract.md).
- **M1:** Complete — implement resolution-aware preprocessing and frozen-model bundles. See
  [the M1 verification report](../../reports/0094-M1_Preprocessing_and_Frozen_Bundles.md).
- **M2:** Complete — add deterministic class/source-weighted epoch schedules, exposure receipts, and
  exact sample-cursor resume. See the [M2 verification report](../../reports/0094-M2_Epoch_Sampling_and_Resume.md).
- **M3:** Complete — implement deterministic source-space rotation, color, blur, and crop
  augmentation with paired mask handling. See the [M3 verification report](../../reports/0094-M3_Source_Space_Augmentation.md).
- **M4:** Complete — add CLS-plus-mean-patch features to frozen training, checkpoints, bundles, and
  inference. See the [M4 verification report](../../reports/0094-M4_Alternate_Frozen_Features.md).
- **M5:** Complete — add targeted final-block training and checkpoint resume. See the
  [M5 verification report](../../reports/0094-M5_Targeted_Encoder_Adaptation.md).
- **M6:** Complete — export exact encoder and head states with separate pretrained provenance,
  recipe metadata, and file digests. The runtime loads adapted weights from the local bundle. See
  the [M6 verification report](../../reports/0094-M6_Adapted_Encoder_Bundles.md).
- **M7:** Complete — report all-class support and confusion, source-group/slice outcomes, and
  digest-checked paired Gemini receipts. See the [M7 verification report](../../reports/0094-M7_All_Class_and_Paired_Evaluation.md).
- **M8:** Not started — fit and retain scalar confidence calibration and review thresholds.
- **M9:** Not started — verify a small local lifecycle and publish the recipe handoff.

## 1. Evidence and boundaries

The existing trainer freezes the entire ViT-S/16 encoder and uses one linear head on pooler_output,
which the installed implementation supplies as the final CLS token. It prepares 224-pixel Lanczos
letterboxes. The local backbone accepted 224/336/384/448 in the 2026-10-14 smoke investigation.
The trainer builds one fixed batch list before its epoch loop. Its augmentation selector ignores
the epoch argument, so each example receives the same augmented view each epoch.

The current bundle loader requires uncalibrated output and ties weights to the pretrained encoder.
New adapted-weight and calibrated-score support must be explicit. Do not mutate a frozen old
bundle or claim its head learned FACE_DOWN because the target map has 25 entries.

Implement reusable software against fixtures and bounded local smoke inputs. Full corpus review,
Gemini quality comparison, candidate selection, final-test access and numerical success belong to 0088. Do not run an architecture search, download different pretrained models, switch the default
provider, or add promotion/campaign UI. Keep implementation milestones separate from campaign fits.

## 2. Recipe rules

Support square input sizes 224, 384, and optional 448 as explicit recipe values, each divisible by
the 16-pixel patch size. Preserve source aspect ratio, visible mask and grey fill. Crop extraction,
source decoder/filter choice, preprocessing, feature layout and model weights have separate
digests. Training, calibration, evaluation and inference use the same versioned transform. Larger
input retains more source detail but does not reduce the relative grey area or recover missing pixels.

Use all 25 positive visual targets. Preserve UNKNOWN as abstention rather than an extra softmax
class. For evaluation, human side labels remain targets, not shortcuts supplied to the classifier.
Retain reviewed-side bypasses as separately attributed pipeline behavior.

Sampling must vary reproducibly by seed and epoch and resume at the exact next example/batch.
Record class/recording exposure and repeat-view grouping. Class/group weighting must be a declared
training recipe; evaluation is unbalanced real evidence. Resume includes sampler, RNG, optimizer,
scheduler, progress and augmentation state or a reproducible equivalent. Batch-size fallback is
declared before a fit, not silently changed after observations.

Apply arbitrary rotations and mild colour/exposure, blur and crop perturbations in source-image
space before final resize. Keep mask and image aligned, hidden/hand/other-card pixels excluded,
neutral fill stable, mirrors disabled and red/black distinctions intact. Each supported operation
has bounded parameters. Exclude or constrain an operation when it can remove all positive-class
evidence. Runtime-mask errors are evaluated using actual automatic crops; do not import occluder
pixels under the label of an identity-preserving augmentation.

The second frozen-feature recipe concatenates final CLS and mean final patch features. Exclude
register/class tokens from the mean. Keep grey patches in the declared unweighted baseline;
mask-weighted pooling and additional heads are out of scope. This is aligned with the feature
construction in [Meta's linear evaluation](https://github.com/facebookresearch/dinov3/blob/main/dinov3/eval/linear.py).

The one adaptation recipe trains the final two transformer blocks, final normalization and head.
All other encoder parameters remain frozen. Record exact parameter names, optimizer groups,
encoder/head learning-rate ratio, stopping, precision and resource caps. Do not leave a whole-encoder
no_grad wrapper around trainable blocks. No pretrained asset or original bundle is overwritten.

## 3. Delivery milestones

### M0 — Freeze software contracts

Inspect current transform, task adapter, checkpoints, export/load, evaluator and provider outputs.
Define explicit recipe values for size, feature layout, trainable blocks, sampler, augmentation,
and confidence policy. Separate original pretrained provenance from actual adapted inference weights.
Freeze small fixtures and required field/version changes before implementation.

Acceptance: each recipe is finite and interpretable; the 25-class map is exact; invalid size/layout
or weight combinations fail; old active artifacts and human source data are not rewritten.

### M1 — Implement configurable preprocessing and frozen bundles

Replace hard-coded 224 assumptions in tensor preparation, configuration and bundle validation with
the declared size. Keep normalization, aspect ratio and padding explicit. Thread the same transform
through training and runtime without selecting it from ambient defaults.

Acceptance: 224/384/448 fixtures yield finite correct-shaped tensors and reloadable frozen-encoder
bundles; identical input/config produces identical pixels; mismatched transform digests fail. Run
one batch-one local backbone feasibility check, with latency/memory reported as smoke evidence.

### M2 — Implement epoch sampling and exact resume

Add epoch-specific shuffling and declared class/source exposure weighting. Persist or regenerate
the exact schedule and next-batch cursor. Keep fitting and exposure budgets explicit.

Acceptance: uninterrupted and interrupted/resumed fixture fits reproduce ordered sample receipts
and final state within the declared deterministic tolerance; seeds/epochs change ordering; source
and class balance is measured rather than assumed. No full dataset or quality benchmark is needed.
**Complete:** the trainer now uses a class- and source-frame-weighted schedule with an explicit
per-epoch sample budget. It saves ordered sample IDs, exposure counts, schedule digests, and the
next-sample cursor in run records and checkpoints. Checkpoint v2 regenerates and checks a partial
epoch schedule before resume. Campaign recipes declare this sampling policy.

### M3 — Implement safe changing augmentations

Include seed, epoch, sample ID and operation in augmentation randomness. Add bounded source-space
rotation, exposure and blur/crop perturbation support with joint visible-mask handling. Reuse the
same deterministic input preparation for every recipe.

Acceptance: epochs change the view; replay/resume repeats it exactly; masks/fill and card marks
remain valid in focused examples; mirrors and undeclared transforms are rejected. Failure cases
do not become FACE_DOWN examples merely because the face is unreadable.

**Complete:** training now applies bounded source-space transforms before the shared letterbox
transform. Per-operation randomness uses seed, epoch, sample ID, and operation. The augmentation
helper transforms an optional visible mask with nearest-neighbor geometry and rejects empty,
mismatched, or overly cropped support. Missing masks are declared as full-crop support. See the
verification report for the current crop-cache mask limitation.

### M4 — Implement the alternate frozen feature recipe

Add CLS-plus-mean-patch extraction, the corresponding linear-head dimensions, checkpoint metadata
and frozen-encoder bundle/runtime dispatch. Keep the original CLS recipe as an explicit control.

Acceptance: token selection and feature shape fixtures pass; frozen encoder parameters do not
change; training/export/reload/inference features and logits agree; incompatible heads fail.

**Complete:** both frozen layouts are explicit in the identity recipe. `cls_mean_patch` joins the
final CLS token with the mean of final spatial patch tokens. It excludes CLS and register tokens
from the mean and checks the patch count for the selected input resolution. Training records the
layout and head width; checkpoint resume, export, bundle loading, and runtime reject incompatible
layouts or head widths. The existing CLS layout remains the default control. Fixture evidence and
the focused verification results are in the M4 report.

### M5 — Implement targeted encoder adaptation

Add the exact final-two-block/final-normalization training adapter, optimizer/scheduler groups and
resume metadata. Use a small fixture fit to verify gradients and frozen parameter invariants.

Acceptance: only declared parameters change; frozen layers remain equal; adapted layers receive
finite gradients; interrupted/resumed training follows the same schedule. Bound memory and retain
a precise local resource limitation instead of silently widening scope or switching hardware.

**Complete:** the training adapter can train the final two `model.layer` blocks, the encoder's
final `norm`, and the identity head. All earlier encoder parameters remain frozen. The encoder
learning rate is 0.1 times the head learning rate. `CosineAnnealingLR` advances once per optimizer
step. Checkpoint v3 records and restores its state with the optimizer and model. Adapted runs require
batch size 1 and record device, precision, input size, and any step limit. Fixture evidence and
resource limits are in the M5 report.

### M6 — Export and load adapted weights

Extend bundle export/load to carry actual encoder weights, original pretrained provenance, exact
head/feature/transform recipes and file digests. Load everything from the local bundle without
network access. Support resumed-training checkpoints separately from inference bundles.

Acceptance: adapted-model logits match before and after reload; pretrained and adapted weights
cannot be confused; missing/changed encoder files fail; both feature layouts and input sizes work
through the local provider. Original materialized weights and bundles remain unchanged.

### M7 — Implement all-class and paired evaluation

Extend evaluation receipts for FACE_DOWN scores, confusion, support, source-group/slice summaries,
paired provider decisions and explicit failed/unusable/missing cases. Include raw top-1, top-3,
coverage and per-frame/per-recording reports. Accept retained Gemini receipts with exact request
identities; do not run live Gemini calls in this implementation milestone.

Acceptance: small fixtures reproduce metrics and denominators; side-bypassed outcomes are excluded
from classifier-credit metrics; confidently wrong back predictions are visible; unsupported classes
stay unmeasured; labels and input information never leak between provider/target views.

**Complete:** frozen and adapted runs use evaluation schema v2, which emits support and confusion
entries for all 25 visual classes, including unmeasured classes. It reports raw top-1/top-3, coverage, and per-class metrics, with
source-lineage-group, recording, frame, card-side, and crop-policy summaries. Optional retained
Gemini receipts require an exact sample ID, crop digest, and request identity. Paired output retains
classified, failed, unusable, side-bypassed, and missing outcomes. Side-bypassed rows do not receive
classifier credit. No live provider request is made. See the M7 report for fixture evidence and
limits.

### M8 — Implement confidence calibration contracts

Add scalar temperature fitting on an explicitly supplied calibration view, reliability and
precision/coverage reports, and bounded review-threshold selection. Version calibration and score
metadata, including face-down confidence, in export/load and stored provider outcomes. Preserve
ranked candidates and the separation from legal card identity. Do not add a default review or
promotion policy; 0088 selects its policy on reserved data.

Acceptance: positive temperature preserves class ranking; missing/overlapping calibration inputs
fail; T=1 retains uncalibrated behavior; fit/export/reload scores agree; thresholds cannot silently
discard candidates or manufacture a new positive UNKNOWN class. Tests cover face-down outputs and
reviewer corrections with confidence metadata retained.

### M9 — Verify and publish the recipe handoff

Run a tiny local train/resume/export/reload/classify lifecycle using all 25-class fixture targets.
Exercise frozen and adapted encoder routes, both feature layouts, 384-pixel input and calibration.
Publish commands, dependency/asset identities, resource results and software limitations.

Acceptance: 0088 can invoke every declared recipe and collect evaluation receipts without new
training implementation. A toy fit establishes software capability only; no real-data accuracy,
FACE_DOWN generalization, Gemini parity, promotion or completed corpus claim follows.

## 4. Verification

Run focused transform, sampler/resume, augmentation, gradient, checkpoint, export, evaluator and
provider contract tests plus relevant Python/API checks. Use existing local optional dependencies
and materialized licensed assets. Numerical MPS checks use declared tolerances; CPU fixtures verify
schedule invariants. Each milestone has an independently reviewable artifact and finite smoke work.
