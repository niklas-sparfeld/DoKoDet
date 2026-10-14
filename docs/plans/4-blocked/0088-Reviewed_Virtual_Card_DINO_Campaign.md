# Reviewed virtual-card DINO quality campaign

## Plan status

- **Summary:** Train and qualify a useful local visual classifier from reviewed individual-card
  crops. Compare input resolution and a bounded sequence of model improvements against Gemini.
- **Status:** Blocked
- **Depends on:** 0086 M4 geometry review and M5 identity handoff; completed
  [0093](../5-closed/0093-Visual_Classification_Annotation_and_Crop_Inputs.md) and
  [0094](../3-in-progress/0094-DINO_Training_and_Runtime_Recipes.md); completed 0043, 0085, and 0091
  identity isolation.
  No dependency on 0092 training.
- **Blocker:** Complete reviewed class coverage and campaign inputs are not available. The 0093
  software handoff is complete, but the current eligible development snapshot has no positive
  annotation crops. The 0094 recipe handoff is not complete.
- **Outcome:** A quality-qualified local model and its exact preprocessing and confidence policy,
  or an explicit report that the useful-model objective remains unmet.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — freeze readiness, splits, quality gates, candidates, and budgets.
- **M1:** Not started — materialize reviewed and automatic-crop evaluation views.
- **M2:** Not started — establish the paired Gemini and PoC reference results.
- **M3:** Not started — train one fresh 224-pixel real-only baseline.
- **M4:** Not started — train one matched 384-pixel candidate.
- **M5:** Not started — run the declared 448-pixel comparison if its entry gate passes.
- **M6:** Not started — compare CLS plus mean patch features at the selected resolution.
- **M7:** Not started — run one targeted fine-tuning candidate if its entry gate passes.
- **M8:** Not started — prepare the bounded synthetic pool if its entry gate passes.
- **M9:** Not started — train the one fixed synthetic mixture, or record its skip.
- **M10:** Not started — verify the two leading recipes with additional seeds.
- **M11:** Not started — fit and assess the confidence policy on reserved data.
- **M12:** Not started — export and lock the exact candidate and final evaluation recipe.
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

Use completed reviewed individual-card geometry and human visual classifications. Include all
24 face-up identities and FACE_DOWN where the back is positively visible. Do not retain the
PoC's hard-coded NINE exclusions. UNKNOWN and identity-unusable evidence are not positive classes.
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
insufficient, publish exact gaps and keep the campaign blocked; do not split adjacent frames to
manufacture independence or silently lower the target after seeing results.

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

Freeze this sequential ladder at M0. Do not run a Cartesian product of sizes, features, augmentation,
fine-tuning, and synthetic mixtures. All candidates share the reviewed data and 0094 training
mechanics. Keep real exposure and checkpoint selection comparable; record extra compute separately.

| Stage | Candidate                                                | Entry and decision                                                                                                                                                                              |
| ----- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M3    | 224 pixels, frozen encoder, CLS linear head, real only   | Fresh control using current reviewed data and corrected training mechanics.                                                                                                                     |
| M4    | 384 pixels, otherwise matched to M3                      | Required first resolution challenger. Select size on the frozen selection view.                                                                                                                 |
| M5    | 448 pixels, otherwise matched                            | Optional if the M0 native-detail and measured resource gates pass. The exact trigger is fixed before fitting.                                                                                   |
| M6    | CLS plus mean patch features, frozen encoder             | One challenger at the selected size. Averaged grey patches may hurt; retain the control if it does.                                                                                             |
| M7    | Final two encoder blocks and final normalization adapted | Optional if the best frozen model misses the declared target and independent data and resource gates pass. Freeze optimizer, learning-rate ratio, regularization, stopping and epoch cap at M0. |
| M9    | One fixed real-plus-synthetic mixture                    | Optional only for an M0-declared support or robustness gap with eligible training-only assets. Use the selected representation; no mixture sweep.                                               |

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

Acceptance: deterministic readiness report and immutable recipe; all 25 positive-class requirements
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

Acceptance: paired rows reproduce; labels are independent of predictions; all 25-class coverage
and provider failures are explicit; the final test remains unopened.

### M3 — Train the fresh 224-pixel control

Run the single frozen real-only control with 0094's reproducible sampling and augmentation.
Retain checkpoints, environment, timing, data/recipe digests, and selection predictions.

Acceptance: resume and reload reproduce predictions; class and source exposure is recorded;
checkpoint selection uses only the declared development view.

### M4 — Train the 384-pixel challenger

Run one real-only candidate differing from M3 only in the declared resolution-related settings.
Compare paired classification, difficult slices, memory, and crop-to-prediction latency.

Acceptance: measured size decision and exact model/transform pair; gains and regressions reported;
larger size is not selected from appearance alone.

### M5 — Run the conditional 448-pixel challenger

Evaluate the predeclared entry gate. Run one matched candidate if eligible; otherwise record a
not-required receipt with the gate evidence. Apply the same resolution selection rule as M4.

Acceptance: one candidate or one explicit skip; no additional sizes or test-based choice.

### M6 — Compare pooled features

Run one CLS-plus-mean-patch linear-head candidate at the selected size. Compare with the existing
CLS control at that size on identical selection cases.

Acceptance: feature/head layout is exact and reloadable; no additional layer/head search; retain
the control when the improvement is harmed or inconclusive under the declared decision rule.

### M7 — Run conditional targeted fine-tuning

Apply the M0 gate and run one bounded adapted-encoder candidate, or record why it is not required.
Use 0094's tested gradient, optimizer, checkpoint, and adapted-weight export path.

Acceptance: only declared blocks change; fit stays within budget; validation regressions and
overfitting are reported; no wider encoder unfreezing or pretrained-model sweep.

### M8 — Prepare the conditional synthetic pool

Apply the M0 gate. Use existing compatible rendering to materialize and inspect the one declared
training-only synthetic pool. Validate card-back contributors, labels, masks and source groups.
If the assets, renderer capability or declared gap are absent, publish an explicit skip receipt.
This milestone does not implement a new renderer or train a model.

Acceptance: immutable inspected pool and exact contributor/crop lineage, or a precise skip reason;
all evaluation remains real; no synthetic support claim for absent reviewed classes.

### M9 — Train the conditional synthetic candidate

Consume M8's inspected pool and frozen mixture recipe, or its skip receipt. Run at most one fit at
the selected representation, with real exposure fixed and synthetic compute reported separately.

Acceptance: a reproducible paired real-data comparison or an explicit not-required receipt; no
mixture/augmentation tuning from observed failures and no preparation changes during the fit.

### M10 — Check finalist stability

Run the two leading eligible recipes at the two additional M0 seeds, at most four fits. If only
one recipe is eligible, run two fits. This milestone adds no implementation or new recipe choices.
Use the frozen seed-aggregation rule and grouped uncertainty report to choose the recipe and exact
checkpoint. Do not choose an unusually lucky seed after inspecting the final test.

Acceptance: seed and source-group sensitivity are visible; fit cap is respected; the exact finalist
selection rule reproduces. Small unsupported gains remain inconclusive.

### M11 — Fit the confidence policy

Use only reserved calibration data and 0094's scalar temperature/threshold tools. Measure
confidence reliability, selective precision versus coverage, and face-down confidence errors.

Acceptance: raw top-1 is unchanged by calibration; the confidence policy has its own digest;
thresholds do not hide failure of the main accuracy or coverage gates; no final-test fitting.

### M12 — Export and lock the final evaluation

Export the exact finalist, preprocessing, adapted-weight provenance where applicable, all-class
score contract, confidence policy, and supported inputs. Lock final-test commands, Gemini recipe,
failure denominator and qualification rules before viewing final predictions.

Acceptance: bundle digest/reload and training/inference parity pass; exact checkpoint and test
membership are locked; no refitting on selection, calibration, or final-test data after this lock.

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

[0089](0089-Virtual_Card_Algorithm_Edge_Cases.md) owns later reproduced geometry/integration fixes.
[0090](0090-Local_End_to_End_Recording_Pipeline.md) owns full pipeline coordination.
[0044](../1-backlog/0044-Productive_Local_Identity_Model_Operations.md) owns registry promotion,
default changes, productive campaign UI, and rollback. Their diagnostic work can consume a failed
0088 decision; that does not make the identity model quality-qualified.
