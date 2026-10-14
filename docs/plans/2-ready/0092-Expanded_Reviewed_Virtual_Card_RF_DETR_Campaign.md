# Expanded reviewed virtual-card RF-DETR campaign

## Plan status

- **Summary:** Train and evaluate an RF-DETR segmentation candidate with reviewed references from at
  least 18 distinct recordings, then refit the final candidate using every eligible reviewed
  recording in the frozen campaign pool.
- **Status:** Ready
- **Depends on:** 0086 M4 current-schema detection-only handoff with completed reviewed geometry,
  visible-card masks, pile coverage, source groups, and permissions for at least 18 recordings;
  completed 0087 candidate bundle as the measured comparison baseline.
- **Readiness:** The completed [0086 M4 audit](../../reports/0086-M4_Geometry_Review_Audit.json)
  has 20 eligible current-schema recordings, above the minimum of 18. `IMG_0092` is permanently
  excluded because the surface was not flat. `IMG_0096` is temporarily deferred for calibration
  repair. M0 must independently freeze source groups, prior use, and a fresh unopened test before
  materialization or training.
- **Outcome:** A source-group-separated evaluation of an expanded real-only candidate, followed by a
  digest-pinned final bundle trained on all eligible reviewed recordings. The runtime default remains
  unchanged.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — audit the expanded pool, define the exact eligible cohort, and freeze splits,
  baseline, recipe, budgets, and gates.
- **M1:** Not started — materialize and inspect the expanded reviewed two-class data.
- **M2:** Not started — train one bounded real-only candidate on the frozen training groups.
- **M3:** Not started — evaluate validation and one fresh sealed holdout, then decide whether the
  recipe passes.
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
the exact M0/M1 lineage; the validation and sealed-test partitions remain unopened during training.

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
