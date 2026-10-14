# Expanded reviewed virtual-card RF-DETR campaign

## Plan status

- **Summary:** Train and evaluate an RF-DETR segmentation candidate with reviewed references from at
  least 18 distinct recordings, then refit the final candidate using every eligible reviewed
  recording in the frozen campaign pool.
- **Status:** In Progress
- **Depends on:** 0086 M4 current-schema detection-only handoff with completed reviewed geometry,
  visible-card masks, pile coverage, source groups, and permissions for at least 18 recordings;
  completed 0087 candidate bundle as the measured comparison baseline.
- **Readiness:** M0 froze 20 eligible current-schema recordings and 20 source groups. `IMG_0092`
  remains permanently excluded because the surface was not flat. `IMG_0096` remains deferred for
  calibration repair. The fresh validation and sealed-test groups have no prior campaign evaluation
  use. See the [M0 readiness report](../../reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Readiness.md).
- **Outcome:** A source-group-separated evaluation of an expanded real-only candidate, followed by a
  digest-pinned final bundle trained on all eligible reviewed recordings. The runtime default remains
  unchanged.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-10-14) — froze 20 eligible source groups, the fresh source-group holdouts,
  the 0087 candidate baseline, one real-only recipe, budgets, and quality gates.
- **M1:** Complete (2026-10-14) — materialized and inspected 874 frames and 2,714 reviewed masks.
- **M2:** Complete (2026-10-14) — the candidate trained on the frozen M0/M1 inputs. Finalization
  reused the saved checkpoint after the missing 0092 receipt was added and the bundle validated.
  See the [M2 report](../../reports/0092-M2_Expanded_Reviewed_RF_DETR_Training.md).
- **M3:** Complete (2026-10-14) — the saved candidate passed the frozen validation gates and the
  one sealed evaluation. The candidate is selectable. See the
  [M3 report](../../reports/0092-M3_Validation_and_Pretest_Lock.md).
- **M4:** Not started — refit the selected recipe on all eligible reviewed recordings and publish
  the exact final bundle.

## 1. Scope and evidence

[0087](../5-closed/0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md) showed that the model can learn
from reviewed visible-card masks and coarse pile regions, but its only training recording was
`IMG_0095`. `IMG_0097` was the validation recording and `IMG_0654` was the sealed-test recording.
That test was opened in 0087. Do not call it a fresh holdout or use it to claim independent
evaluation in this campaign.

The [0086 inventory](../3-in-progress/0086-Reviewed_Virtual_Card_Corpus.md) contains 22 development
candidates with `project_use` permission. Previous
stage-use metadata can reflect an old split and must not replace the original source permission.
Permission alone does not make a recording a training target. Each included recording needs a
completed current-schema reference, valid geometry, reviewed visible-card masks, pile coverage, and
source-group lineage.

This campaign targets at least 18 distinct recording groups. M0 must list every candidate and its
exact inclusion or exclusion reason. If fewer than 18 recordings have complete eligible references,
do not lower the threshold or train a small candidate. Keep this epic blocked and send the missing
review work to 0086. Do not use drafts, proposals, or incomplete references to reach the count.

Keep this effort separate from 0088 identity training, 0089 algorithm fixes, and 0090 pipeline
composition. Do not add synthetic data or sweep recipes in this campaign. The selected 0087 bundle
is the comparison baseline; also report the pinned pretrained baseline where the frozen recipe
requires it.

## 2. Campaign rules

Freeze permissions, exact completed reference revisions, source groups, prior evaluation use,
train/validation/test membership, minimum support, checkpoint and recipe, compute budget, quality
gates, and final-refit policy before training. Keep source groups disjoint across the evaluation
partitions. Choose a fresh sealed-test recording that has not been opened by 0087 or another
campaign. Report when distinct session or table-setup coverage is unavailable.

Use [0091's](../5-closed/0091-Pile_Region_Feature.md) fixed class map: precise `visible_card` masks
and coarse `card_pile` regions. Preserve reviewed-card pixel priority, pile lineage, ignore and
frame-exclusion receipts, and consumed-member exclusions. Do not claim pile quality without
reviewed pile targets in the relevant partition.

The first candidate trains only on the frozen training groups. Use validation to assess the frozen
gates and open the sealed test once after a locked decision. Do not revise thresholds or recipes from
test results. If it passes, use the exact frozen recipe to refit one final candidate on every eligible
reviewed recording in the M0 pool, including the former validation and test groups. The M3 report
measures the pre-refit candidate; do not describe its metrics as a direct evaluation of the final
refit weights.

Keep the 0087 provider selectable as a rollback. Register the final expanded bundle as explicitly
selectable only when M3 permits it. Keep `gemini` as the runtime default.

## 3. Delivery milestones

### M0 — Freeze the expanded campaign

Reconcile all 22 current development candidates with the 0086 reference handoff and original source
permissions. Count completed eligible recording groups and all reviewed targets. Resolve historical
evaluation use. Select at least 18 groups, freeze source-group-separated train, validation, and fresh
sealed-test sets, and record exact exclusions. Pin the 0087 candidate bundle as the comparison
baseline. Freeze the model recipe, budget, gates, and final-refit policy.

Acceptance: at least 18 recording groups have completed references; minimum support is met in every
partition; the sealed test is fresh; no source group leaks across partitions; a deterministic manifest
pins every source, reference, recipe, and decision. Otherwise record exact missing references and
keep the campaign blocked before materialization or training.

### M0 implementation evidence — 2026-10-14

The frozen [M0 manifest](../../reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json)
contains all 22 candidate dispositions and all 20 eligible current-schema references. It assigns 16
recordings to training, two to validation, and two to a fresh sealed test. The prior 0087 validation
and sealed-test recordings are training-only. Source-group, session, table, asset, and video lineage
are disjoint across partitions. Every partition meets its frozen frame, card, and pile support.

The selectable 0087 candidate bundle and pinned pretrained checkpoint are digest-verified. The
manifest freezes one real-only candidate and the final-refit policy. M1 materialization and inspection
are complete. The [readiness report](../../reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Readiness.md)
records the exact split, support, budget basis, and reproduction commands.

### M1 implementation evidence — 2026-10-14

The deterministic [M1 report](../../reports/0092-M1_Reviewed_Mask_Materialization.md) covers 874
frames and 2,714 masks: 2,352 visible-card masks and 362 pile masks. Its materialization digest is
`9fa0992bccab325a8fbadecb9bf375fbb783ea3b943a10e56b52cca92248e942`. A warm rebuild produced the
same digest and generated-file receipts. The view retains M0 source and reference lineage, omits 35
reviewed frame exclusions and 92 ineligible outcomes, and is ready for M2.

All masks decoded at source dimensions. Overlay sheets cover all 20 recordings and include dense,
small-card, pile, and supported frame-edge examples. RF-DETR 1.9.4 loaded all three COCO partitions.
No model inference or training ran in M1.

### M2 implementation evidence — 2026-10-14

The single candidate trained from the frozen M0 manifest and M1 materialization in
`.runtime/rfdetr-segmentation-0092`. RF-DETR 1.9.4 ran on MPS with seed 6701, 40 epochs, batch size 1,
and gradient accumulation 4. Training and metrics completed in about 3 hours and 9 minutes. The
sealed-test partition was not staged. The validation partition was used only for the frozen
early-stopping rule. The exported checkpoint SHA-256 is
`7cf0d649bdb2d4a488a8035961a43e05fdc4f5e458a11721b007f71f501e292c`.

Initial bundle finalization failed because the two-class bundle omitted the frozen 0092 M0 receipt.
The finalization-only recovery verified the saved training stages, frozen M0/M1 lineage, and matching
checkpoint hashes, then repaired and validated the bundle without training. See the
[M2 report](../../reports/0092-M2_Expanded_Reviewed_RF_DETR_Training.md). The sealed test remains
unopened.

The campaign runner now accepts the 0092 materialization and verifies its frozen partition receipt.
The 0092 verifier checks the two-class recipe, checkpoint digest, budget, M1 manifest receipt, and
all three source-group partitions before training starts.

### M3 implementation evidence — 2026-10-14

The validation evaluator accepts the frozen 0087 bundle as the comparison model. For 0092, it checks
that bundle digest against M0 and assesses the frozen visible-card and pile quality gates, false
detections, duplicate detections, and empty-prediction rate. The MPS validation completed in 491
seconds. All gates pass. The [M3 report](../../reports/0092-M3_Validation_and_Pretest_Lock.md)
records aggregate and per-recording metrics. The digest-pinned
[pretest lock](../../reports/0092-M3_Pretest_Decision.json) records M0 support and authorization
checks. The single sealed evaluation ran after the lock was verified. Both sealed recordings have
nonzero visible-card recall. The pinned pretrained baseline has zero visible-card recall on this
partition. The evaluator selected the 0092 candidate as a selectable bundle and kept `gemini` as the
runtime default. The [M3 report](../../reports/0092-M3_Validation_and_Pretest_Lock.md) records the
sealed metrics, per-recording recall, artifacts, and MPS latency. M3 is complete.

The sealed partition contains pile targets in one recording. The candidate's pile recall there is
0.533333. The other recording has no pile targets. Do not use this result as a broad pile-quality
claim. Candidate MPS inference averaged 2,647.981 ms per frame. M4 must report final-refit latency.

The saved-checkpoint finalizer also repaired the persisted M2 run receipt. The run now records all
stages as complete and `training_invoked: false`; no weight changed. The sealed evaluator accepts the
0092 lock and applies the frozen 0092 gates. Focused tests and Ruff pass.

### M1 — Materialize and inspect reviewed masks

Build the expanded two-class dataset from the frozen manifest. Preserve source frames, calibration
and geometry digests, reviewed exclusions, pile coverage, and reference lineage. Inspect overlays
from every included recording and the declared risk slices. Verify deterministic materialization and
load the view through the pinned RF-DETR package.

Acceptance: cold and warm views match; decoded masks match reviewed source regions; no conflicting
same-frame targets or unsupported frames enter the view; every source group and label count matches
the manifest.

### M2 — Train one expanded real-only candidate

Train only the one frozen candidate on the M0 training groups. Retain durable logs, resources, recipe
and data digests, checkpoint selection, and exported bundle. Do not add synthetic samples or extra
candidates after observing training results.

Acceptance: training completes within its frozen budget; the candidate reloads; the bundle preserves
the exact M0/M1 lineage; validation is used only for the frozen early-stopping rule and the sealed-test
partition remains unopened during training.

### M3 — Evaluate and decide once

Compare the candidate with the selectable 0087 bundle on unchanged reviewed validation data. Include
per-recording visible-card and pile metrics, false and duplicate predictions, empty-frame rate,
confusion, fragments inside piles, recall near piles, and available overlap, human-hand, small-card,
and edge slices. Lock the decision before running the fresh sealed test. Run that test once only when
the frozen support and authorization checks pass.

Acceptance: the report records every frozen gate, per-recording coverage, retained predictions,
latency, artifacts, and limitations. Select the candidate only if the frozen gates pass; otherwise
retain 0087 as the selectable bundle and report the expanded candidate as an experiment.

### M4 — Refit on all eligible reviewed recordings

If M3 selects the expanded recipe, retrain once with all eligible reviewed recordings in the M0 pool,
including the former validation and sealed-test groups. Keep the same architecture and frozen recipe.
Verify export, bundle load, local inference, latency, and exact lineage. Do not re-evaluate or tune on
the already opened holdout.

Acceptance: the final bundle includes every eligible reviewed recording named by M0 and no excluded
or incomplete reference; its digest and training receipts are reproducible; the report distinguishes
M3 holdout evidence from the final all-recording refit; defaults remain unchanged.

## 4. Verification

Use focused split, materialization, mask, exclusion, lineage, training-resume, evaluation-replay,
bundle-load, provider, and local-inference checks. Inspect overlays for every included recording.
Keep generated datasets, runs, predictions, and bundles under `.runtime`; commit manifests and
reports, not model weights.
