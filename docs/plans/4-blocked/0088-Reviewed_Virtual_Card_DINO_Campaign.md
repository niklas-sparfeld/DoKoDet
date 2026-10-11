# Reviewed virtual-card DINO campaign

## Plan status

- **Summary:** Freeze identity crops from corrected virtual-card references and train a separate
  bounded DINOv3 identity campaign with one measured synthetic-data addition.
- **Status:** Blocked
- **Depends on:** 0086 completed geometry and identity handoff; completed 0043 and 0085
- **Blocker:** Reviewed identity coverage and the virtual-card training crop contract are not frozen.
- **Outcome:** Reproducible identity crops, measured real and synthetic candidates, and a retained
  local identity bundle decision.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — freeze crop, class, split, baseline, recipe, budget, and gates.
- **M1:** Not started — implement preparation from reviewed virtual-card inputs.
- **M2:** Not started — inspect real crops and prepare the synthetic addition.
- **M3:** Not started — train and evaluate the corrected-real-only candidate.
- **M4:** Not started — train and compare the fixed synthetic mixture.
- **M5:** Not started — export, verify, and publish the identity decision.

## 1. Current evidence and boundaries

The 0043 frozen-encoder candidate trained on 552 real crops and measured 94.02% top-1 accuracy on
301 validation crops across 20 identities. Four NINE identities and FACE_DOWN were unmeasured.
The candidate remains a development baseline, not evidence for unsupported classes.

0085 supports reviewed virtual-card crop inputs for inference. The current campaign preparation
requires `predicted_visible_region`, while reviewed geometry defaults to `oracle_visible_region`.
Adapt the preparation contract explicitly; do not relabel reviewed geometry as detector output.

This campaign does not depend on the new RF-DETR candidate. It trains from completed reviewed
geometry and labels. RF-DETR training belongs to [0087](0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md).
Model promotion and productive campaign UI remain in
[0044](../1-backlog/0044-Productive_Local_Identity_Model_Operations.md).

## 2. Campaign rules

M0 must choose and freeze one crop policy. Default to the existing source-image masked visible-region
crop from the completed virtual-card input. If perspective rectification is selected, specify its
transform, visible-pixel mask, orientation ambiguity, fill policy, and inference integration before
implementation. Do not invent pixels for hidden card surfaces or use full-card outlines as visible
evidence. Do not select the crop policy from validation results.

Match identities to exact reviewed card and frame IDs. Retain calibration, scene derivation, geometry,
crop, and source digests. Exclude identity-unusable and failed crops with receipts. Define class
eligibility from measured support before training, including FACE_DOWN and absent NINE identities.
Keep visual classification separate from legal card identity. Machine predictions are not targets.

Reuse the DINOv3 frozen-encoder trainer as the initial recipe. Freeze pretrained files, head,
transform, optimizer, seed, stopping and checkpoint rules, budgets, numerical gates, and baseline
comparison before training. Do not add encoder fine-tuning or an architecture sweep in this epic.

Use the 0086 source groups, with campaign-specific exclusions. Freeze at most one corrected-real-only
candidate and one real-plus-synthetic candidate. Retain the 0043 baseline; compare on unchanged
compatible validation data where possible and state any changed evaluation contract. Keep real
exposure equal between new candidates and report added synthetic compute separately.

Synthetic identity crops must trace to eligible training-only reviewed card cutouts and labels,
backgrounds, and geometry. Reuse synthetic scene rendering where practical, then apply the same
crop policy used for real inputs. Do not inherit detector campaign ratios or assume segmentation
gains imply identity gains. Missing synthetic class support must be explicit.

Review prior evaluation usage before freezing a test. Use an unopened eligible test only under a
locked decision; label previously observed data as diagnostic evaluation. System-holdout groups
must not contribute crops, synthetic assets, training, or component selection.

## 3. Delivery milestones

### M0 — Freeze the identity campaign contract

Audit reviewed reference pairs, class and source coverage, existing split assignments, pretrained
assets, and evaluation history. Choose the crop policy and freeze candidates, sampling, budget, and
gates. Define top-1, top-3, macro F1, per-class support, confusion, latency, and supported occlusion
and usability slices. Record unsupported classes and minimum support required to proceed.

Acceptance: deterministic readiness and immutable recipe; no undeclared class claims; protected
groups excluded; crop and test decisions fixed before fitting; exact gaps block preparation.

### M1 — Prepare reviewed virtual-card crops

Extend the campaign preparation boundary to consume completed reviewed virtual-card input lineage
and its declared crop policy. Reuse exact-frame resolution and inference crop derivation. Remove
obsolete preparation assumptions instead of adding an implicit fallback. Materialize an immutable
real crop inventory and human-reviewed targets.

Acceptance: training and inference reproduce the same crop bytes for identical inputs; cold and
warm digests match; stale calibration or derivation, mismatched cards, and changed source bytes fail;
unreviewed inputs cannot become targets. Add focused contract and lineage regression tests.

### M2 — Inspect crops and materialize synthetic input

Inspect real crop contact sheets by recording, class, visibility, and exclusion reason. Generate one
fixed training-only synthetic pool, apply the same crop policy, and inspect class and occlusion
coverage. Smoke-load both training views with finite tensors and canonical targets.

Acceptance: inspected digests match the frozen views; hidden and human-hand pixels are handled by
the declared mask policy; synthetic labels retain reviewed contributor lineage; validation contains
only real evidence; incomplete support is reported before training.

### M3 — Train the real-only candidate

Run one resumable corrected-real-only candidate with the frozen recipe. Retain checkpoints,
environment, timings, crop and target digests, and real validation predictions. Compare with the
retained baseline under the declared compatible evaluation conditions.

Acceptance: checkpoint selection uses only frozen validation; aggregate and per-class metrics
reproduce; changed crop or data conditions are explicit; no test, promotion, or extra candidate.

### M4 — Measure the synthetic mixture

Train the one declared mixture. Compare against corrected-real-only on identical real validation
crops and supported slices. Retain sampling exposure, compute, confusion, and failure examples.

Acceptance: report improved, harmed, or inconclusive outcomes; absent classes stay unmeasured;
no ratio or augmentation tuning follows observed validation failures.

### M5 — Export and publish the decision

Lock the selected bundle or retained baseline. Run an eligible sealed test once only if the frozen
gate and authorization permit it. Verify bundle file digests, reload parity, inference crops,
ranked output contract, local smoke, and latency. Publish class limits and an explicit promotion
recommendation without changing the champion or default.

Acceptance: retained predictions reproduce the report; bundle and crop policy are usable together;
0089 and 0090 receive an exact model and policy decision even if new training does not improve
quality; 0044 can later reuse the report for promotion gates.

## 4. Verification

Run focused crop contract, split, source integrity, preparation, resume, evaluation, export, and
runtime tests. Run applicable Python static checks and deterministic materialization checks.
Keep training independent from browser operation and cloud infrastructure.
