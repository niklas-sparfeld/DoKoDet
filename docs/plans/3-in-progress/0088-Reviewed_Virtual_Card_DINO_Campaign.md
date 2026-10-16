# Reviewed virtual-card DINO quality campaign

## Plan status

- **Summary:** Train and qualify a useful local visual classifier from reviewed individual-card
  crops. Compare input resolution and a bounded sequence of model improvements against Gemini.
- **Status:** In Progress
- **Depends on:** Completed 0086 M4/M5 handoffs; completed
  [0093](../5-closed/0093-Visual_Classification_Annotation_and_Crop_Inputs.md) and
  [0094](../5-closed/0094-DINO_Training_and_Runtime_Recipes.md); completed 0043, 0085, and 0091
  identity isolation.
  No dependency on 0092 training.
- **Readiness:** M0 froze the source-group split and quality contract in the
  [campaign readiness report](../../reports/0088-M0_Campaign_Readiness.md). The user accepts the
  low `FACE_DOWN` sample size for iterative classifier work, including annotation assistance.
  Support floors remain quality-reporting limits; they do not block exploratory training. Do not
  claim face-down precision, recall, calibration, or generalization from this sample. The 0086 M5
  [source verification report](../../reports/0088-M1_Source_Verification.md) confirms that all 20
  source videos match the 0086 handoff and intake receipts byte-for-byte. M1 materialized the
  reviewed and automatic-crop views; see the [M1 report](../../reports/0088-M1_Campaign_Views.md).
  Keep the final test unopened until M13. On 2026-10-16, the user added one exploratory
  synthetic-training comparison based on the 0070 visible-region generator. This changes the
  optional M8/M9 branch only. It does not change the frozen partitions, real-only evaluation,
  formal quality gates, or fit caps.
- **Outcome:** A quality-qualified local model and its exact preprocessing and confidence policy,
  or an explicit report that the useful-model objective remains unmet.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — freeze readiness, splits, quality gates, candidates, and budgets; see the
  [readiness report](../../reports/0088-M0_Campaign_Readiness.md).
- **M1:** Complete — exact source bytes are verified; reviewed train/validation data and automatic
  development crops are materialized. No automatic crops matched reviewed cards at IoU 0.5; all
  misses remain in coverage. See the [M1 report](../../reports/0088-M1_Campaign_Views.md).
- **M2:** Complete — exact Gemini request-cache receipts cover all 209 reviewed development crops;
  the retained 0043 PoC result is reported with its historical input set and unsupported classes.
  See the [M2 reference report](../../reports/0088-M2_Reference_Comparison.md).
- **M3:** Complete — the frozen 224-pixel control reached 206/208 face-up top-1 on two selection
  groups; support limits prevent qualification. See the [M3 report](../../reports/0088-M3_224_Control.md).
- **M4:** Complete — the 384-pixel candidate scored lower and ran slower than 224. Keep 224 as
  the selected input size for later comparisons. Evidence remains exploratory. See the
  [M4 report](../../reports/0088-M4_384_Run.md).
- **M5:** Not required — skip the optional 448-pixel challenger by user decision after M4; see the
  [M5 skip record](../../reports/0088-M5_448_Skip.md).
- **M6:** Complete — pooled features corrected one more selection crop and added no errors.
  Treat this as a useful exploratory signal and keep both M3 CLS and M6 pooled features for M10;
  see the [M6 run record](../../reports/0088-M6_Pooled_Features.md).
- **M7:** Not required — the frozen candidate clears the selection target, while the independent
  source-group support gate fails. See the [M7 skip record](../../reports/0088-M7_Fine_Tuning_Skip.md).
- **M8:** Complete — built and visually reviewed seven deterministic synthetic crops from exact
  0070-to-0088 training joins. The pool covers five face-up identities in one source group. It has
  no synthetic `FACE_DOWN` example; the one real training crop remains eligible for M9. See the
  [M8 pool report](../../reports/0088-M8_Synthetic_Pool.md).
- **M9:** Complete — the fixed 1:1 candidate matched M6 at 208/209 selection crops, with no changed
  predictions or corrected crops. It did not improve the annotation-assistance signal. M10 compares
  M3 with M6 under the frozen rule. See the [M9 fit report](../../reports/0088-M9_Synthetic_Identity_Fit.md).
- **M10:** Complete — M6 gains 0.32 percentage points over M3 across seeds 17, 101, and 202,
  below the 1-point challenger threshold. Only two model-selection groups contribute, so the
  paired source-group uncertainty rule is insufficient and no recipe qualifies. See the
  [M10 report](../../reports/0088-M10_Finalist_Stability.md).
- **M11:** Complete — fit exploratory calibration on the reserved 105-crop, one-group view.
  Top-1 stays 83/105, while the frozen 90% confidence threshold reaches only 40% coverage. The
  confidence gate and class/group support floors fail; no face-down calibration data exists. See
  the [M11 report](../../reports/0088-M11_Confidence_Policy.md).
- **M12:** Complete — locked M3 and M6 seed-17 bundles as co-finalists, with separate calibration,
  a 25-output score contract, paired Gemini recipe, 108-crop denominator, and exact final-test
  recording. Both bundles reproduce saved model-selection predictions across all 209 crops. The
  1-point rule does not exclude either model; the final-test partition has one source group and
  cannot meet the uncertainty floor. See the [M12 lock](../../reports/0088-M12_Final_Evaluation_Lock.md).
- **M13:** Not started — execute the final test and paired Gemini comparison once.
- **M14:** Not started — exercise the locked bundle on development recording sequences.
- **M15:** Not started — publish the qualification decision and downstream handoffs.

## 1. Objective and evidence

The existing 0043 model is a proof of concept. Its retained report measured 94.02% top-1 and
98.01% top-3 on 301 validation crops across 20 identities. NINE identities and FACE_DOWN were
unmeasured. The operator reports that it works worse than Gemini. A completed run or an improvement
over that model alone does not satisfy this epic.

The [2026-10-14 crop investigation](../../reports/0088-Crop_and_Input_Size_Investigation.md)
found that all retained non-neutral pixels in 105 IMG_0095 crops
matched their decoded source-frame pixels. Native crop long sides were 316–777 pixels, with median 554. The current model uses Lanczos and a grey 224-pixel letterbox. The median resized short side
was 99 pixels, and median non-neutral model-input area was about 26%. These are development
diagnostics, not classification results or representative corpus statistics. Review JPEG previews
are a separate representation and are not the improvement objective.

Local forward checks of the existing ViT-S/16 weights succeeded at 224, 336, 384, and 448 pixels
with finite pooled features of unchanged dimension. This establishes backbone feasibility only.
0094 must deliver versioned preprocessing, training, bundle, and runtime support before these
sizes become campaign recipes.

0093 owns annotation and reusable crop preparation. It makes FACE_DOWN review available before
0086 M5 completes and removes the PoC training exclusions. 0094 owns reusable training and runtime
capabilities, including fine-tuning and confidence calibration. This epic consumes those tested
capabilities and runs the measured campaign. It does not implement them during long training runs.

## 2. Readiness, authority, and splits

Use completed reviewed individual-card geometry and human visual classifications. The current
recording pool uses a deck without NINE cards. Train and evaluate 20 face-up identities plus
FACE_DOWN, for 21 positive visual classes. The operator confirmed on 2026-10-15 that NINE samples
will not exist in this pool for years. Do not require, synthesize, or claim NINE support in this
campaign. Keep NINE in the game card vocabulary; any future NINE-capable classifier needs a
separately versioned data and model decision. UNKNOWN and identity-unusable evidence are not
positive classes.
Piles and consumed member proposals have no individual identity crops or targets; use the
[0091 handoff](../../reports/0091-Pile_Region_Capability_Handoff.md).

Audit exact frame/card matching, source permission, geometry, annotation, crop and calibration
digests, independent recordings, and available deck/back designs. Count distinct source groups
and repeated card views as well as crops. Balance training exposure without changing the natural
evaluation distribution. Missing positive class evidence needs reviewed data; synthetic rendering
cannot invent support for a class with no eligible contributor.

Use current source-exclusion guards and 0086 recording dispositions. Its completed M4 handoff
does not certify identity coverage. Permanently excluded source digests remain excluded under
renamed IDs; deferred recordings need an explicit updated readiness receipt before enrollment.

M0 must freeze source-group-separated training, model-selection, confidence-calibration, and final
test views. Respect prior split assignments and evaluate prior use before assigning a final test.
The 0043 validation data is diagnostic, not an unopened final test. Sealed RF-DETR and system-holdout
groups stay out of development and component selection. If independent data or class support is
insufficient, publish exact gaps and limit the claims. The user accepts under-supported exploratory
training to improve the classifier for annotation assistance. Do not split adjacent frames to
manufacture independence or present exploratory results as quality qualification. Keep the final
test sealed until M13.

M1 prepares two evaluation conditions: reviewed visible-region crops and automatic runtime crops
from an exact declared provider. Match automatic crops to reviewed cards through a frozen geometric
association rule, with ambiguous and unmatched cases recorded separately. Keep labels out of
association and crop production. Retain missing detections and transform failures in the complete
pipeline coverage report. Reviewed oracle_visible_region and generated predicted_visible_region
remain distinct origins even when their image transforms match.

For classifier evaluation, do not supply reviewed card-side labels that bypass the model.
FACE_DOWN must be predicted from pixels. Report independently supplied side decisions separately.
The model predicts a visual classification, not a legal card assignment or gameplay state.

## 3. Quality contract

The working targets are at least **98% top-1 on human-readable face-up cards** and a deficit of
at most **one percentage point to Gemini** on the same eligible population. M0 must record the
readability authority, justified minimum support, uncertainty rules, and per-class/slice floors
before fitting. These are campaign targets, not promises that the current corpus can certify them.
M0 may propose a different operational target only with an explicit recorded user decision.

Also freeze FACE_DOWN precision and recall, the false-FACE_DOWN rate on face-up cards, confident
error limits, usable prediction coverage, and local latency/memory limits. Report top-3, macro F1,
confusion, per-recording errors, and frames with all supported individual classifications correct.
Do not use the shared fixture profile's 90% accuracy or one-example support as proof of readiness.

Use human-reviewed targets for both Gemini and DINO. Declare the Gemini model, prompt, decoding,
input information, retry/failure rules, request count, and spend cap. Reuse receipts only when exact
request and crop identities match. A same-source-crop comparison and a workflow comparison with
different provider inputs are separate conditions. Never use Gemini predictions as ground truth.

Report intervals and source-group variation beside point estimates. State when support is too weak
to establish a small difference. Top-3 success or rejecting most difficult cards cannot replace
correct top-1 predictions and useful coverage. Confidence calibration cannot change the raw
top-1 accuracy used by the main gate. Oracle-only success cannot certify automatic inference.

## 4. Bounded candidate ladder

M0 froze the sequential ladder. On 2026-10-16, the user explicitly added one exploratory synthetic
training comparison because local fits are short and even one additional correct crop can help
annotation. This amendment authorizes only the one M8 pool and one M9 fit below. It does not change
M0 splits, evaluation data, formal quality gates, or the fit caps. Do not run a Cartesian product of
sizes, features, fine-tuning, and synthetic mixtures. All candidates use 0094 training mechanics.
Keep the real exposure and checkpoint-selection rule fixed; report extra synthetic compute.

| Stage | Candidate                                                | Entry and decision                                                                                                                                                                              |
| ----- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M3    | 224 pixels, frozen encoder, CLS linear head, real only   | Fresh control using current reviewed data and corrected training mechanics.                                                                                                                     |
| M4    | 384 pixels, otherwise matched to M3                      | Required first resolution challenger. Select size on the frozen selection view.                                                                                                                 |
| M5    | 448 pixels, otherwise matched                            | Optional if the M0 native-detail and measured resource gates pass. The exact trigger is fixed before fitting.                                                                                   |
| M6    | CLS plus mean patch features, frozen encoder             | One challenger at the selected size. Averaged grey patches may hurt; retain the control if it does.                                                                                             |
| M7    | Final two encoder blocks and final normalization adapted | Optional if the best frozen model misses the declared target and independent data and resource gates pass. Freeze optimizer, learning-rate ratio, regularization, stopping and epoch cap at M0. |
| M9    | One fixed 1:1 real-plus-synthetic mixture                 | User-authorized exploratory candidate. Use only eligible training-only identity-labeled contributors through the 0070 renderer. Keep real exposure fixed; no mixture sweep.                         |

M0 must fix numerical fit and wall-time budgets, batch-size fallback rules, seeds, optimizer and
learning-rate choices. A finite budget is not permission for further undeclared candidates. There
are at most six primary fits and four additional finalist fits in M10. Each training milestone
runs at most one primary fit and retains a resumable checkpoint. Define conditional gates before
M3, including the allowed development diagnostics and the stop outcome when no candidate qualifies.

Use source-image masked visible-region crops as the campaign default. Keep Lanczos as the initial
resampler. 0093's bounded decoder/filter diagnostics can propose one shared fidelity change before
the candidate recipes are frozen. Larger input resolution does not require table geometry.
Do not make full-card rectification a mandatory input. 0093 records its pixel-use benefit and
geometry risks; a new runtime rectified policy needs a separate implemented and verified handoff
and an explicit plan revision before fitting. Do not add it informally after observing failures.

Synthetic validation and test data are prohibited. Synthetic training cutouts, backgrounds and
labels must trace to eligible training-only reviewed contributors, including card backs. Preserve
visible-pixel support and apply the same crop/preprocessing policy as real data. Record M8/M9 as
not required with a reason when assets or a selected gap are absent. Use existing compatible
rendering only; a missing renderer capability is an explicit skip, not new implementation in a fit.

## 5. Delivery milestones

### M0 — Freeze readiness and the campaign contract

Audit the 0086, 0093, and 0094 receipts, class/group support, prior evaluation use, pretrained assets,
and local resource feasibility. Freeze data partitions, targets, candidate ladder, conditional gates,
Gemini recipe/cost cap, seed rules, fit budgets, quality gates, and exact CLI commands.

Acceptance: deterministic readiness report and immutable recipe; all 21 positive-class requirements
are explicit; protected data is excluded; insufficient support is a named blocker. No fitting or
final-test predictions occur. This milestone does not guarantee that a quality target will pass.

### M1 — Materialize the campaign views

Use 0093 to materialize the exact reviewed training crops and labels. Materialize the frozen
reviewed and automatic-crop development evaluation views and association/exclusion receipts.
Record the unopened final-test membership without rendering or scoring it during development.

Acceptance: cold/warm digests match; no unreviewed predictions become targets; back crops are
included; source/card/frame mismatches fail; missing automatic inputs remain in coverage counts.

### M2 — Establish the reference results

Run or reuse the bounded Gemini development comparison and retained PoC predictions under their
compatible input contracts. Report unsupported PoC classes, failures, input differences, and cost.
Produce the initial human-labeled confusion and error examples.

Acceptance: paired rows reproduce; labels are independent of predictions; all 21-class coverage
and provider failures are explicit; the final test remains unopened.

**Result:** The exact Gemini cache supplied one result for each of 209 M1 model-selection crops.
It reached 203/208 face-up top-1 (97.60%) and had no provider failures. No new requests or spend
were incurred. The single FACE_DOWN result is exploratory only. The retained 0043 PoC evaluation
has 301 rows and 94.02% top-1, but uses a different historical validation set. The current loader
rejects its bundle as an obsolete uncalibrated smoke format, so no fresh same-crop PoC predictions
were made. Do not compare the Gemini and PoC point estimates as a paired model ranking. See the
[M2 reference report](../../reports/0088-M2_Reference_Comparison.md) and its machine-readable
[paired rows](../../reports/0088-M2_Reference_Comparison.json).

### M3 — Train the fresh 224-pixel control

Run the single frozen real-only control with 0094's reproducible sampling and augmentation.
Retain checkpoints, environment, timing, data/recipe digests, and selection predictions.

Acceptance: resume and reload reproduce predictions; class and source exposure is recorded;
checkpoint selection uses only the declared development view.

**Result:** The eight-epoch fit completed in 996.7 seconds. The reloaded best checkpoint reproduced
its 209 selection predictions exactly. It scored 206/208 face-up top-1 and 209/209 top-3. The exact
paired Gemini result was 203/208 face-up top-1. Only two source groups contribute, and each class
misses the three-group support floor. `FACE_DOWN` support remains one training crop and one selection
crop; these results are for iterative annotation assistance, not quality qualification. See the
[M3 report](../../reports/0088-M3_224_Control.md).

### M4 — Train the 384-pixel challenger

Run one real-only candidate differing from M3 only in the declared resolution-related settings.
Compare paired classification, difficult slices, memory, and crop-to-prediction latency.

Acceptance: measured size decision and exact model/transform pair; gains and regressions reported;
larger size is not selected from appearance alone.

**Result:** The matched eight-epoch run completed with seed 17. It scored 204/208 face-up top-1
and 205/208 top-3, below M3's 206/208 and 208/208. Median crop-to-prediction latency was 97.9 ms,
compared with 38.7 ms at 224 pixels. Keep 224 as the selected input size for later comparisons.
The report includes paired Gemini results, source-slice outcomes, memory measurements, and exact
runtime reproduction evidence. Only two source groups contribute, so this does not qualify quality
or generalization. `FACE_DOWN` remains exploratory under the accepted sample-size decision. See the
[M4 report](../../reports/0088-M4_384_Run.md).

### M5 — Run the conditional 448-pixel challenger

**Result:** Not required. After reviewing M4, the user chose to skip the optional 448-pixel
comparison and continue with M6. M4's 384-pixel candidate scored below 224 pixels and had 2.43x
the mean crop-to-prediction latency. This is a scope decision based on M4; it is not a measurement
of 448-pixel quality. See the [M5 skip record](../../reports/0088-M5_448_Skip.md).

Acceptance: one candidate or one explicit skip; no additional sizes or test-based choice.

### M6 — Compare pooled features

Run one CLS-plus-mean-patch linear-head candidate at the selected size. Compare with the existing
CLS control at that size on identical selection cases.

Acceptance: feature/head layout is exact and reloadable; no additional layer/head search; retain
the control when the improvement is harmed or inconclusive under the declared decision rule.

**Result:** The 224-pixel pooled-feature candidate reached 207/208 face-up top-1, compared with
206/208 for CLS. It fixed one CLS error and introduced no new errors. This one-crop gain is useful
for exploratory annotation assistance, but it does not establish a stable improvement. Keep both
M3 CLS and M6 pooled features as candidates for M10's additional-seed comparison. Keep the M0
threshold for formal qualification; do not use it alone to discard a useful exploratory candidate.
The exported bundle reproduced all 209 checkpoint predictions. See the
[M6 run record](../../reports/0088-M6_Pooled_Features.md).

### M7 — Run conditional targeted fine-tuning

Apply the M0 gate and run one bounded adapted-encoder candidate, or record why it is not required.
Use 0094's tested gradient, optimizer, checkpoint, and adapted-weight export path.

Acceptance: only declared blocks change; fit stays within budget; validation regressions and
overfitting are reported; no wider encoder unfreezing or pretrained-model sweep.

**Result:** Not required under the frozen M0 gate. M6 reached 207/208 face-up top-1 (99.52%) on
the model-selection view, above the 98% target. The source-group support gate also fails: only two
groups contribute, and the required three evaluation groups per class are not available. M7
requires both a frozen candidate that misses the target and passing independent-data support.
Neither condition is met, so no encoder fine-tuning fit was started. This is a conditional skip,
not a finding that fine-tuning would not help annotation assistance. See the
[M7 skip record](../../reports/0088-M7_Fine_Tuning_Skip.md).

### M8 — Build the synthetic identity-crop pool

Use the 0070 visible-region generator for deterministic cutout placement, compositing, and visible
masks. Add only the small adapter needed to turn rendered instances into DINO identity crops. Join
each source cutout to a reviewed 0088 training identity through exact source asset, frame, item, and
crop lineage. Do not infer a class from the 0070 `visible_card` segmentation label. Reject any
contributor or background outside the frozen 0088 training groups. Keep validation and final-test
pixels, labels, geometry, and source groups out of pool creation.

Render one deterministic synthetic appearance per eligible reviewed training crop. This keeps the
pool size bounded by the reviewed real training set. Preserve the source identity label and
visible-support mask. Use an eligible 0088 training background when one is available; otherwise use
a fixed neutral canvas with no source pixels. The renderer may vary placement, scale, and the
existing 0070 appearance effects. Keep the original real crop in the pool. Use only card sides and
identities with exact reviewed training contributors. Synthetic copies retain their original source
group and do not add class support or independent groups. `FACE_DOWN` may be augmented only from an
eligible reviewed training example; copies cannot repair support floors or qualify back-design
generalization. Inspect a contact sheet and label/mask overlays before freezing the pool.

Acceptance: one immutable pool with exact source and rendered-crop lineage, deterministic output
digests, class/side/source-group inventory, and visual review; or a precise skip receipt if the
identity join or source permissions fail. Evaluation stays real. No new renderer, label inference,
or pool tuning from M9 results.

**Result:** Complete. Seven of 165 0070 cutouts joined uniquely to reviewed 0088 training crops by
source recording digest, decoded frame digest, event item, and reviewed identity lineage. The pool
uses the 0070 renderer on a fixed neutral canvas and contains the seven original real crops, their
synthetic PPM crops, rendered appearances, and visible masks. All seven are face-up. The one real
`FACE_DOWN` training example stays in the real set; no compatible 0070 cutout exists, so no
synthetic face-down crop was created. The pool was visually checked and rebuilt twice with the same
manifest digest. See the [M8 pool report](../../reports/0088-M8_Synthetic_Pool.md).

**Plan amendment:** The earlier [M8 skip record](../../reports/0088-M8_Synthetic_Pool_Skip.md)
correctly records the original frozen-gate decision. The user later authorized one bounded
exploratory comparison. This amendment supersedes that skip as the campaign decision; it does not
change the report's historical record. See the [M8/M9 experiment plan](../../reports/0088-M8_M9_Synthetic_Identity_Experiment.md).

### M9 — Train the conditional synthetic candidate

Consume M8's inspected pool, or its skip receipt. If eligible samples exist, run one 224-pixel
CLS-plus-mean-patch frozen-encoder fit with seed 17, eight epochs, and the M0 optimizer, device,
precision, augmentation, and checkpoint-selection settings. Sample one synthetic crop for each real
crop draw while preserving the M6 real draw count; report the additional steps, wall time, and
memory. Run at most one fit.

Compare against M6 on the unchanged real model-selection crops. Report absolute correct-crop counts,
the identities of corrected and regressed crops, results by recording/source group, and latency.
Treat a net gain of one or more correct crops without an inference-limit regression as a useful
annotation-assistance signal; do not require a one-percentage-point gain. Synthetic samples do not
count toward support floors or quality qualification. No final-test access, mixture tuning, or pool
changes during the fit. If M8 skips, publish an explicit not-required receipt.

**Result:** Complete. One seed-17 fit used 599 real plus 599 paired synthetic draws per epoch for
eight epochs (9,584 optimizer steps, 863.86 seconds). Its best checkpoint reached 208/209 top-1,
matching M6 exactly on all 209 predictions. No crop was corrected or regressed. A matched timing
check measured M9 p95 at 44.684 ms versus M6 at 44.775 ms. The synthetic candidate adds no useful
selection signal, so M10 keeps M3 and M6 as its finalists. See the [M9 fit report](../../reports/0088-M9_Synthetic_Identity_Fit.md).

### M10 — Check finalist stability

Run the two leading eligible recipes at the two additional M0 seeds, at most four fits. If only
one recipe is eligible, run two fits. If M9 yields a net gain of at least one correct crop without
regressions on the fixed real selection view, compare M9 and M6. Otherwise, compare M3 and M6. This
milestone adds no implementation or new recipe choices.
Use the frozen seed-aggregation rule and grouped uncertainty report to choose the recipe and exact
checkpoint. Do not choose an unusually lucky seed after inspecting the final test.

**M10 aggregation rule:** The M0 readiness report freezes the additional seeds and candidate
selection thresholds, but it does not define how to aggregate seed results. Before inspecting M10
predictions, compare each recipe by the equal-weight mean of its seed-17, seed-101, and seed-202
face-up model-selection top-1 results. Apply the M0 challenger rule to the aggregated comparison
and report the two additional-seed results separately. If a recipe is selected, carry its seed-17
checkpoint forward; do not select the highest-scoring seed checkpoint. This rule prevents one
unusually favorable additional seed from deciding the candidate. Report source-group uncertainty as
insufficient when fewer than three groups contribute, as required by M0.

**Current finalists:** M3's 224-pixel CLS control and M6's 224-pixel CLS-plus-mean-patch candidate.
M9 can replace M3 in the M10 comparison only under its predeclared real-selection rule above.
Compare seed stability, per-class errors, runtime, and the M0 uncertainty rules before selecting
one recipe.

Acceptance: seed and source-group sensitivity are visible; fit cap is respected; the exact finalist
selection rule reproduces. Small unsupported gains remain inconclusive.

**Result:** Complete. All four additional fits at seeds 101 and 202 finished within the two-hour
cap. Across seeds 17, 101, and 202, M3 averaged 98.56% face-up top-1 and M6 averaged 98.88%, a
0.32-point gain. This is below the 1-point threshold. Only two source groups contribute, so the
paired bootstrap interval is unavailable under M0's three-group minimum. The evaluation support
floors also fail, so neither recipe is quality-qualified. Record the decision as inconclusive and
keep M3 seed 17 as the diagnostic control checkpoint for later confidence-policy work. See the
[M10 report](../../reports/0088-M10_Finalist_Stability.md). The final test remains unopened.

### M11 — Fit the confidence policy

Use only reserved calibration data and 0094's scalar temperature/threshold tools. Measure
confidence reliability, selective precision versus coverage, and face-down confidence errors.

Acceptance: raw top-1 is unchanged by calibration; the confidence policy has its own digest;
thresholds do not hide failure of the main accuracy or coverage gates; no final-test fitting.

**Result:** Complete. M3 seed 17 was calibrated on the reserved 105-crop `IMG_0095` group. The
fitted temperature is 0.6080 and reduces NLL from 0.8826 to 0.7599; raw and calibrated top-1 both
remain 83/105 on this view. At calibrated top-1 probability 0.90, precision is 42/42 but coverage
is only 40%, below M0's 90% gate. The optional 99% precision-target review threshold is 0.8157 and
covers 55/105 crops. The view has one group, class support below the frozen floors, and no
`FACE_DOWN` crop. Treat the calibration and threshold as exploratory; they do not qualify a model
or set a review default. Reloaded inference reproduced raw logits and probabilities exactly. The
final test remains sealed. See the [M11 report](../../reports/0088-M11_Confidence_Policy.md).

### M12 — Export and lock the final evaluation

Export the exact finalist, preprocessing, adapted-weight provenance where applicable, all-class
score contract, confidence policy, and supported inputs. Lock final-test commands, Gemini recipe,
failure denominator and qualification rules before viewing final predictions.

Acceptance: bundle digest/reload and training/inference parity pass; exact checkpoint and test
membership are locked; no refitting on selection, calibration, or final-test data after this lock.

**Result:** Complete. Locked M3 seed 17 and M6 seed 17 as co-finalists. Their bundle digests are
`e5495203…ac87` and `a6c1aa2a…4ed79`; candidate-specific temperatures are `0.6080362924` and
`0.6487642659`. The M0 one-point challenger rule does not exclude M6 from final comparison. Both
reloaded MPS bundles matched all 209 saved model-selection predictions with no top-1 or probability
mismatches. M6's calibrated bundle also reproduced logits on all 105 calibration crops. Its
confidence gate reaches 39% coverage at 0.90 confidence, below the 90% requirement. The standard
evaluation CLI could not use the historical M3 campaign manifest because it lacks per-crop metadata;
direct replay used the verified dataset and crop cache. Locked Gemini `gemini-3.8-flash`, the M0
prompt and response schema, one request per crop, no retries, USD 10 cap, and a 108-crop denominator.
Final membership is the verified `IMG_0659` source recording, with crop materialization deferred to
M13. One source group cannot meet M0's three-group uncertainty floor. See the
[M12 lock](../../reports/0088-M12_Final_Evaluation_Lock.md) and
[machine-readable contract](../../reports/0088-M12_Final_Evaluation_Lock.json).

### M13 — Execute the final test once

Run the locked local candidate and paired Gemini reference on the unopened eligible test. Retain
all predictions, failures, group/slice metrics, confidence results, and costs.

Acceptance: one digest-backed final result; no tuning or repeated test after seeing errors. A failed
quality gate produces an unmet-objective decision, not an automatic request for more candidates.

### M14 — Exercise development recording sequences

Run the locked bundle through the existing local identity pipeline on a small frozen development
batch using automatic crop inputs. Verify face-down recognition without reviewed-side shortcuts,
failure handling, ranked outputs, confidence metadata, latency, and per-recording review burden.

Acceptance: real inference works with the exported policy; upstream limits and classifier errors
are separated; diagnostic recordings are not reported as a new held-out test. No new coordinator,
temporal smoothing, gameplay inference, default-provider switch, or promotion UI is added.

### M15 — Publish the qualification decision

Publish the selected bundle and a pass, fail, or insufficient-evidence result against every frozen
gate. Include systematic confusions, Gemini disagreements, unsupported conditions, resource costs,
and whether the useful-model objective has been achieved.

Acceptance: 0089/0090 receive exact diagnostic model and policy decisions; 0044 receives a
quality-qualified promotion recommendation only when gates pass. If quality is unmet or unmeasured,
record that outcome explicitly and do not close this epic as Complete. Any further campaign needs
a separate bounded plan; do not run indefinitely or claim a retained PoC satisfies this objective.

## 6. Verification and ownership

Use the focused contract and runtime checks delivered by 0093/0094, deterministic materialization,
resume/reload checks, exact prediction receipts, protected-split validation, and local smoke runs.
Each fit is resumable and can run without browser activity or new hardware. Publish resource
preflight before executing a long job. Broad code changes discovered during a fit return to a
supporting implementation milestone instead of being mixed with the campaign result.

[0089](../4-blocked/0089-Virtual_Card_Algorithm_Edge_Cases.md) owns later reproduced geometry/integration fixes.
[0090](../4-blocked/0090-Local_End_to_End_Recording_Pipeline.md) owns full pipeline coordination.
[0044](../1-backlog/0044-Productive_Local_Identity_Model_Operations.md) owns registry promotion,
default changes, productive campaign UI, and rollback. Their diagnostic work can consume a failed
0088 decision; that does not make the identity model quality-qualified.
