# Local visual card identity quality proof

## Plan status

- **Summary:** Train and compare bounded DINOv3 identity candidates on reviewed real crops before
  any local classifier becomes productive or replaces Gemini.
- **Status:** Blocked
- **Depends on:** Plans 0041 and 0042 complete, plus reviewed real identity data from enough
  source-lineage groups to freeze development partitions
- **Builds on:** Plans 0028 and 0038 comparison, candidate-lock, crop-policy, and promotion-gate
  mechanics
- **Outcome:** Freeze one reviewed identity corpus, train at most two declared DINOv3 ViT-S/16
  candidates, compare them with Gemini and the current champion on identical evidence, and either
  lock one local candidate or publish a precise data or model gap. No backend default changes.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — measure coverage and freeze train, validation, and challenge data.
- **M1:** Not started — train the bounded local candidate set.
- **M2:** Not started — compare identity and composed crop behavior on unchanged data.
- **M3:** Not started — calibrate, lock at most one candidate, and publish the proof report.

## 1. Purpose

Determine whether the local model is actually useful before adding routine training controls or
changing the backend default. Separate classifier quality from detector and crop failures. Use
reviewed human identities as the reference and use Gemini only as a paired baseline.

## 2. Evidence and coverage

Freeze three source-lineage-safe partitions:

1. **Train:** reviewed identity-usable `raw_rectangular` crops for classifier fitting.
2. **Validation:** reviewed cards that reproduce all three frozen crop-policy conditions for
   candidate, threshold, calibration, and crop-policy decisions.
3. **Challenge:** reviewed glare, blur, occlusion, small-card, perspective, contamination, and
   difficult deck-design cases used for failure measurement, not fitting.

Exclude test and the system holdout. Split by session or a stricter source-lineage group. Do not put
nearby crops, physical cards, or source frames from one lineage group in different partitions.

Target at least 20 train crops and 5 validation crops for each of the 24 visual card identities,
with at least five sessions and two table setups overall. No one session can supply more than 40%
of either partition. Record a coverage gap instead of weakening the rule silently. Scope every
candidate to the declared deck designs represented by reviewed training and validation data.

## 3. Fixed candidate recipe

Keep the DINOv3 ViT-S/16 architecture, 224 x 224 transform, target map, pretrained weights, and
input crop contract from plan 0041 fixed. Train both candidates with the `raw_rectangular` policy
selected by plan 0042. This is the current runtime-aligned baseline. Train at most these two
candidates:

1. frozen encoder plus linear head; and
2. the same model with only the last two encoder blocks and the head trainable.

Use one declared seed, optimizer family, augmentation policy, epoch budget, and early-stopping rule.
The partial fine-tune is a bounded capacity check. Do not add another backbone, head, loss, input
size, or search after seeing validation results.

## 4. Evaluation

Evaluate every candidate, Gemini, and the current champion on the same immutable crops. Report:

- top-1 and top-3 accuracy, macro F1, per-identity support, and confusion;
- accuracy by session, table setup, deck design, side, crop policy, and failure tag;
- high-confidence errors and duplicate-identity cases;
- expected calibration error, negative log likelihood, and reliability bins;
- selective accuracy and coverage across frozen rejection thresholds;
- median and p95 CPU and MPS inference latency and bundle size;
- Gemini latency, retry, token, and estimated cost data; and
- paired prediction rows with complete crop and classifier lineage.

Run a composed comparison after crop-only evaluation:

```text
reviewed visible region -> frozen crop policy -> identity classifier
local detector proposal -> same crop policy -> identity classifier
```

This separates identity errors on trusted geometry from localization and crop contamination. Keep
the raw derived-box, oracle visible-region mask, and conservative rejection policies from plan 0038
fixed. The reviewed visual card identity stays constant across the three deterministic conditions.
Treat `oracle_visible_region` as an upper bound that can justify later segmentation work, not as a
deployable policy. Treat `conservative_box_only` as a selective-coverage measurement, not as a way
to remove difficult reviewed labels. Do not tune labels or crop policies from validation
predictions after the freeze.

## 5. Decision rules

Before evaluation, define hard validity gates and non-inferiority limits through the plan 0028
identity-capability gate profile. At minimum, require:

- complete class and source-group support or an explicit blocked result;
- no critical per-identity collapse;
- declared minimum top-1 and macro-F1 results on validation and challenge;
- an acceptable high-confidence error rate at the selected coverage;
- finite local latency and a validated self-contained bundle; and
- stable ranked-candidate output through the table-observation adapter.

The report ends with one of:

```text
lock_local_candidate
collect_more_reviewed_data
revise_crop_policy_in_a_new_epic
revise_model_recipe_in_a_new_epic
keep_current_classifier
```

Do not promote, change the backend default, or start another experiment from sealed-test feedback.

## 6. Delivery milestones

### M0 — Freeze reviewed identity data

- Add coverage, partition, crop-policy, and exclusion reports over completed plan 0042 reviews.
- Freeze train, validation, and challenge manifests with immutable digests.
- Record source-lineage, class, deck-design, table-setup, and failure-tag coverage.

Acceptance:

- every included label has complete human review and source lineage;
- partitions have no source-lineage overlap and exclude the system holdout;
- all crop bytes and policies reproduce from their source artifacts;
- every reviewed identity remains identical across its reproducible crop-policy conditions;
- the report states every unmet support target; and
- candidate configuration cannot change the frozen membership.

### M1 — Train the bounded candidates

- Resolve one plan 0028 campaign with at most the two declared candidates.
- Train on explicit MPS, with CPU contract tests and complete failure records.
- Export and validate every successful candidate bundle.

Acceptance:

- both candidates use identical data, target, `raw_rectangular` training crops, seed, and evaluation
  contracts;
- runs record pretrained, dataset, split, configuration, code, environment, and checkpoint digests;
- failed or interrupted runs remain resumable and visible;
- no undeclared candidate enters the campaign; and
- training completes in a declared local time budget or reports the measured feasibility gap.

### M2 — Compare crop and composed quality

- Evaluate candidates, Gemini, and the champion on identical validation and challenge items.
- Run the three frozen crop-policy conditions.
- Run the local-detector composed path without changing detector or classifier settings.
- Write machine-readable paired predictions and a concise report.

Acceptance:

- every aggregate metric can be reproduced from sample rows;
- classifier, localization, crop, and unusable-input failures remain separate;
- oracle improvement reports a segmentation opportunity and does not select an unreproducible
  runtime policy;
- conservative-policy results report both accuracy and retained coverage and do not remove reviewed
  labels from the frozen corpus;
- per-identity and worst-group results cannot be hidden by aggregate accuracy;
- validation and challenge predictions do not alter labels or data membership; and
- no test or system-holdout data selects a candidate.

### M3 — Calibrate and lock at most one candidate

- Select one rejection threshold and calibration transform from validation only.
- Re-evaluate the chosen fixed settings on the unchanged challenge set.
- Apply the frozen gate profile and lock at most one local candidate.
- Publish the proof report and the next bounded decision.

Acceptance:

- the selected bundle records calibration, threshold, coverage, and all input digests;
- the machine-readable comparison determines the recommendation;
- a failed gate produces a data or recipe gap, not a hidden exception;
- a locked candidate remains unpromoted and is not the backend default; and
- the report gives a direct entry condition for plan 0044 or one new corrective epic.

## 7. Verification

Run dataset, split, lifecycle, training, evaluation, bundle, runtime, and report-reproduction
checks. Repeat the selected candidate evaluation from the exported bundle. Record local MPS
feasibility and CPU compatibility. Keep the system holdout sealed.
