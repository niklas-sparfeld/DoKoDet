# Fine-model full-frame visible-card detection

## Plan status

- **Summary:** Remove the RF-DETR Small card-cluster stage. Use the same RF-DETR SegMedium model
  for full-frame detection and far-cluster crop refinement.
- **Status:** In Progress
- **Depends on:** Completed 0048 pipeline data and execution, completed 0049 recording pipeline
  review, completed 0068 reviewed RF-DETR visible-card segmentation, and the 0071 fine-stage
  model and source-coordinate crop contracts. The 0071 coarse stage is the removal target.
- **Builds on:** `local-rfdetr-segmentation`, the reviewed `visible_card` segmentation contract,
  and the deterministic cluster-crop transforms created in 0071.
- **Outcome:** The `local-rfdetr-fine-frame` provider uses one fine model on the complete source
  frame and on selected far-cluster crops. It keeps every full-frame candidate and its identity.
  Confident crop results can refine geometry or add a missed card. The provider uses no coarse
  model, `card_cluster` model bundle, or cascade child bundle. M4 will register it after M3.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Decision

### Full-frame main result with far-cluster crop refinement

The first M3 comparison used an all-cluster crop pass and replacement arbitration. It did not test
the targeted far-cluster refinement in this decision, and the held-out set had only six far-field
frames. Keep the current fine model. Do not start a new training run in this epic.

Correction: provider v2 ran crops for every cluster and treated crop results as additions. Provider
v3 routes only far clusters and uses matched crop predictions to refine full-frame geometry. It
keeps every full-frame candidate and identity. Do not use the v2 result policy.

Use `local-rfdetr-fine-frame` version `local-rfdetr-fine-frame-v3` with schema
`local-rfdetr-fine-frame/v3`. Keep the current 0.5 confidence threshold for full-frame and crop
inference. Use the full-frame result as the main candidate set. Route a cluster to crop inference
when its median card span is at most 96 pixels at the 432-pixel model input and the crop gives at
least 1.5 times the full-frame resolution. This targets small, far-away cards and skips crops that
give little scale benefit.

Match crop results one-to-one with predictions from their source cluster when box IoU and visible-
mask IoU are both at least 0.50. Rank qualifying matches for each candidate by the lower of box IoU
and mask IoU. Accept a pair only when it is the best match for both candidates and leads each
candidate's second choice by at least 0.10. Refine a matched candidate's geometry only when crop
confidence is at least 0.05 higher. Keep the full-frame candidate and its identity. Add an unmatched
crop result only when its score is at least 0.70. Drop near-identical duplicates only when both box
IoU and visible-mask IoU are at least 0.90, always keeping the earlier main result. Do not suppress
by containment or general overlap. A failed crop leaves the full-frame result intact.

This policy preserves every full-frame candidate while letting high-confidence crop results improve
far-cluster geometry or add a missed card. Crop false positives and extra split predictions can
still reduce precision, so M3 must report them.

The coarse model is parked indefinitely. Do not lower its threshold, retrain it, or keep it as a
fallback. The replacement is a fine-model prepass:

1. Run the RF-DETR SegMedium visible-card model once on the complete source frame.
2. Use its `visible_card` boxes as routing proposals for deterministic card-cluster formation and
   padded square cluster crops.
3. Run the same loaded fine model on each cluster crop.
4. Keep full-frame predictions as the main result. Use one-to-one crop matches to refine geometry,
   then add high-confidence unmatched crop predictions.

This keeps the full-frame fine inference as a recall path. The crop pass is a resolution and
instance-separation refinement, not a second detector family. The two exact decision frames that
motivated this change are fixed regression cases: the full-frame fine model finds the central cards
that the configured coarse pass omitted, while crop inference gives better separation confidence
for the overlapping cards.

## Fixed scope

The epic includes:

- one fine RF-DETR model load shared by the full-frame and crop calls;
- a full-frame fine pass with explicit threshold and source-coordinate diagnostics;
- card-cluster formation from prepass `visible_card` boxes, reusing the reversible crop geometry;
- fine inference on the resulting padded square crops;
- selective routing for small clusters when crops provide a useful scale increase;
- one-to-one source-frame matching, geometry refinement, high-confidence crop additions, and strict
  duplicate reconciliation that preserve all full-frame candidates;
- a new selectable provider and one fine-model bundle contract;
- removal of coarse model loading, training, evaluation, bundle assembly, and provider wiring; and
- held-out evaluation of recall, overlap separation, false positives, crop cost, and latency.

The epic does not include:

- a second detector, a `card_cluster` target, or a coarse-model fallback;
- sliding windows, fixed table crops, or a multi-scale fine-model sweep;
- a default visible-card provider change or model promotion;
- changes to CardEventNet, event-frame selection, visual card identity, or game reconstruction; or
- rewriting historical 0071 reports and stored results that document the retired coarse cascade.

## Provider contract

### Frozen M0 choices

- Provider: `local-rfdetr-fine-frame`; provider version: `local-rfdetr-fine-frame-v3`.
- Provider schema: `local-rfdetr-fine-frame/v3`; bundle schema: the existing
  `rfdetr-segmentation-bundle/v1` with one `RFDETRSegMedium` `visible_card` model at 432 × 432.
- Load one fine model from one bundle. Use it for both the full-frame pass and cluster crops.
- Use a confidence threshold of `0.5` for full-frame candidates and crop detections. Keep
  candidates whose score is greater than or equal to the threshold. Record both values in the
  manifest and raw response. Do not tune either threshold on the two fixed regression frames.
- Route every usable, finite, in-frame full-frame box at or above the threshold. Assign each routed
  prediction to exactly one deterministic connected component using the existing median-shorter-side
  expansion and transitive-intersection rule. Each crop must contain the complete union box for its
  component. Keep the existing square crop, neutral padding, and reversible source-coordinate
  transform. An empty full-frame result produces no crops.
- Keep every valid full-frame candidate in the final result. Route small clusters only when the crop
  gives a useful scale increase. Match crop results one-to-one to candidates in their source cluster
  at box and mask IoU of at least 0.50. Rank matches by the lower IoU. Accept a pair only when it is
  the best match for both candidates and leads each candidate's second choice by at least 0.10.
  Refine geometry only when crop confidence is at least 0.05 higher; keep the full-frame identity.
  Add unmatched crop results only at score 0.70
  or higher. Remove a duplicate only when box and mask IoU are both at least 0.90, keeping the main
  result. A crop failure leaves full-frame candidates unchanged.
- Reject non-finite, degenerate, or out-of-frame model geometry deterministically. A bad candidate
  does not invalidate other valid candidates. A malformed source frame fails the item.
- Use the two fixed JPEGs in
  [`tests/fixtures/visible_card_fine_prepass/`](../../../table_evidence_analyzer/tests/fixtures/visible_card_fine_prepass/)
  as exact model inputs. Their frame hashes link them to `game-2026-09-18-01-003` and the two event
  times below. The expected regions are regression support regions copied from a direct local fine
  model result. They are not reviewed reference geometry or ground truth.
- Record `full_frame`, `clusters`, `refinement`, `arbitration`, `mapping`, `reconciliation`, and
  `timing` sections in the raw response. Include model and bundle identity, the 0.5 inference
  threshold, 96-pixel far-cluster size limit, 1.5 crop scale gain, 0.50 one-to-one match thresholds,
  0.10 ambiguity margin, 0.05 confidence gain, 0.70 unmatched-crop threshold, and strict 0.90
  duplicate threshold. Record
  source-frame dimensions and digest, cluster-to-full-frame attribution, crop transforms, per-crop
  outcome, and final proposal provenance. Do not emit coarse-stage names or identities.
- Freeze comparison fields as visible-card recall, central-card recall, overlapping-card separation,
  merged-plus-split duplicates, false positives, crop count, crop-area ratio, prepass latency, crop
  latency, total latency, and deterministic output digest. Report prepass misses, crop failures, and
  arbitration errors separately.

### Full-frame fine pass

The provider decodes one complete source frame and runs the fine segmentation model at its declared
model input size. It keeps the model's visible-card polygons, tight derived boxes, scores, masks,
and source-frame dimensions. They remain the main candidates. A crop can refine a candidate's
geometry, but it cannot remove the candidate or change its identity. Record routing and matching
rules in the manifest and measure them against held-out reviewed cards.

When the full-frame pass returns no usable predictions, the provider returns an empty result and
does not run crop inference. It must report this as valid negative evidence.

### Prepass-derived card clusters

Use the existing deterministic connected-component layout and reversible source-coordinate
transform. Use valid full-frame predictions as crop-routing proposals. Route a cluster only when its
median card span is at most 96 pixels at the model input size and crop scale gain is at least 1.5.
The layout must preserve its behavior for one prediction, nearby overlapping predictions,
frame-edge boxes, neutral padding, non-finite geometry, and an empty full-frame result.

The provider must record which full-frame predictions created each card cluster. A cluster is an
image-processing unit only. It does not assert a pile, trick, card play, or other gameplay
relationship.

### Refinement and arbitration

Run the same fine model on each routed cluster. Map all crop polygons, masks, and boxes back to the
exact source frame before matching.

Use this result policy:

- keep every valid full-frame candidate and its identity in the final result;
- match crop candidates one-to-one within their source cluster when box and mask IoU are both at
  least 0.50;
- rank matches by the lower of box IoU and mask IoU;
- accept a pair only when it is the best match for both candidates and leads each candidate's second
  choice by at least 0.10;
- refine matched geometry only when crop confidence is at least 0.05 higher;
- add unmatched crop candidates only when confidence is at least 0.70;
- drop a duplicate only when both box IoU and mask IoU are at least 0.90, keeping the earlier main
  result; and
- use stable cluster order, proposal order, and prediction ID for deterministic matching. Do not
  suppress candidates by containment or general overlap.

The raw response must distinguish `full_frame`, `clusters`, `refinement`, `arbitration`, `mapping`,
`reconciliation`, and `timing`. It must not expose `coarse`, `coarse_bundle`, or a `card_cluster`
model identity.

## Milestone status

- **M0:** Complete — freeze far-cluster routing, one-to-one refinement, base-preserving arbitration,
  thresholds, and exact-frame regression fixtures.
- **M1:** Complete — add the shared fine-model pass with selective far-cluster routing, one-to-one
  geometry refinement, high-confidence additions, strict duplicate checks, crop fallback, and
  focused tests.
- **M2:** Complete — remove coarse training, bundle, CLI, registry, configuration, and active UI
  surfaces. Keep cluster geometry under neutral names and keep historical evidence readable.
- **M3:** In Progress — the initial comparison tested all-cluster replacement and had only six
  far-field frames. It does not test the targeted refinement algorithm. Evaluate that algorithm
  with the current fine model on a representative challenge set; no new model training is in scope.
  The provider keeps every full-frame candidate and selectively refines small clusters. See the
  [initial M3 comparison report](../../reports/0082-M3_Fine_Frame_Sealed_Test_Comparison.json).
- **M4:** Blocked — register the current-model refinement provider and migrate active references
  after M3 evaluates the algorithm, while keeping 0071 as the closed, superseded implementation
  record.

## Delivery milestones

### M0 — Freeze the fine-prepass contract

- Inspect the 0071 provider, bundle, crop layout, reconciliation, and diagnostics before editing.
- Add exact source-frame JPEG fixtures for `event-000010` at `t_us=38141669` and `event-000012` at
  `t_us=54483336`. Record their source video digest, frame identity, image digest, and the central
  fine-model regression support regions in the fixture manifest.
- Define far-cluster routing, one-to-one refinement, crop-addition threshold, strict duplicate rule,
  failure fallback, provider name, schema version, response and manifest fields.
- Define the comparison report fields: visible-card recall, central-card recall, overlapping-card
  separation, merged-plus-split duplicates, false positives, crop count, crop-area ratio,
  prepass latency, crop latency, total latency, and deterministic output digest.

#### M0 acceptance criteria

- The contract contains no coarse model, coarse threshold, `card_cluster` training target, or
  second model bundle.
- The two exact frames are reproducible test inputs with source-linked expected outcomes. The
  fixture contract check passes, and the outcome regions are explicitly marked as regression support,
  not reviewed ground truth.
- The arbitration policy can fall back to a successful full-frame result when crop inference fails.
- The contract preserves separate overlapping cards and rejects invalid geometry deterministically.

### M1 — Implement the shared fine-model prepass and refinement

- Refactor the current 0071 provider so one loaded RF-DETR SegMedium model runs on the full source
  frame first and then on prepass-derived cluster crops.
- Reuse or rename the generic coordinate and crop helpers. Remove coarse-specific constructor
  paths, model-size assumptions, and raw response fields.
- Map full-frame and crop predictions to source coordinates and implement the M0 refinement policy.
  Ensure a crop failure does not erase valid full-frame proposals.
- Add focused unit and provider tests for empty prepass, one card, overlapping cards, merged
  prepass plus split crop results, frame-edge padding, crop failure, duplicate crops, and stable
  repeated output.

#### M1 acceptance criteria

- The provider performs no RF-DETR Small inference and loads no coarse bundle.
- The exact event fixtures retain the central cards in the final proposals.
- Every valid full-frame candidate remains in the result. Crop geometry can refine a candidate only
  through a one-to-one match with the required confidence gain. A crop failure preserves its source
  candidate.
- Raw diagnostics identify every final proposal's prepass or crop provenance and source transform.

#### M1 validation note

The exact JPEG fixtures pass through the provider with their frozen regression-support regions as
detector inputs. This checks source-coordinate mapping and crop arbitration. The only local model
bundle available for a real inference check is an unreviewed one-epoch smoke bundle. It returns no
detections on either exact frame, so it does not establish model recall. M3 must use the reviewed
fine bundle and held-out references for that evaluation.

### M2 — Remove the retired coarse implementation

- Remove coarse card-cluster training, validation, bundle loading and assembly, coarse-only
  evaluation, and coarse-specific CLI commands and exports.
- Remove the `rfdetr-cascade-bundle` two-child manifest contract and all active coarse bundle paths.
- Remove `local-rfdetr-cascade`, its 0068/0070 variants, backend lazy-provider wiring, settings,
  run controls, and tests. Register only the new non-default fine-prepass provider for this path.
- Keep generic crop and source-coordinate code under neutral names. Keep historical 0071 reports
  and persisted pipeline results readable as historical data; do not make them active selectable
  providers.
- Search the repository for coarse provider names, `card_cluster` model identities, and stale
  cascade bundle references. Active code and user-facing controls must contain none.

#### M2 outcome

- Removed the coarse card-cluster trainer, bundle assembly and validation, materializer, provider,
  CLI commands, backend settings, exports, and Web UI variants.
- Renamed the shared cluster geometry module and its public proposal/layout types. The fine-prepass
  and fine cluster-crop tools now use generic crop and coordinate-transform names.
- Updated the proposal service to accept generated local RF-DETR revisions without depending on
  the retired cascade provider name.
- Kept 0071 reports and stored pipeline evidence as historical records. Kept the fine cluster-crop
  training and materialization tools because they do not load or train a coarse model.
- Validation passed: focused table-evidence, operations, and backend tests; the Web RunControls
  test; CLI help inspection; Ruff checks; and `git diff --check`.

#### M2 acceptance criteria

- The source tree has no executable coarse model implementation or active coarse provider entry.
- A clean local setup can load the replacement provider from one fine-model bundle.
- Historical stored results remain inspectable without reactivating the retired provider.
- Focused Python, backend, and web tests pass for the changed surfaces.

### M3 — Validate current-model far-cluster refinement

- Use the current reviewed fine-model bundle. Do not train a new model for this epic.
- Compare the full-frame main result with selective crop refinement on source-linked reviewed small,
  central, far-field, frame-edge, single-card, and overlapping-card cases. Ensure the challenge set
  represents rare far-field recordings; the initial six far-field frames are not sufficient.
- Report full-frame detections refined, crop additions, crop false positives, skipped clusters,
  crop failures, strict duplicate decisions, overlap separation, crop area, and latency separately.
- Do not remove crop inference based only on aggregate recall. Review far-field and overlap results
  and the measured cost before setting the provider's final selectable behavior.

#### M3 implementation evidence — 2026-09-25

- Used the reviewed 0068 sealed-test set: 104 source-linked frames and 292 reviewed visible-card
  polygons. The annotation digest is
  `ed25a0be6764d1d4614ad64c51f1c79840fad873cab8887ecc6d4e02f86a6296`. The model bundle digest is
  `b3deef701e26d91ebfd9d357b4ff69b45ae9360e3722de340f1044214179df29` and checkpoint digest is
  `b72462e9736d16bb975ba9c6999fe1cc4baeab8805830c3116115279170f3d4f`.
- At polygon IoU 0.5, direct full-frame inference matched 228/292 references (78.08%), with 56 false
  proposals and 2 duplicate proposals. Fine full-frame plus crop refinement matched 227/292 (77.74%),
  with 62 false proposals and no duplicate proposals. The recall difference was -0.34 percentage
  points.
- In 58 frames with reviewed card bounding boxes that overlap by at least 10% of the smaller box,
  direct full-frame inference matched 149/210 cards (70.95%). Crop refinement matched 148/210
  (70.48%). It added no measured overlap separation and had one fewer match.
- The crop path ran 115 crops. The median per-frame sum of crop-area ratios was 0.0925. Median
  prepass latency was 214.8 ms, median crop latency was 159.1 ms, median total latency was 498.1 ms,
  and total latency p95 was 864.3 ms on MPS.
- Both exact regression fixtures retained their central-card support region. Repeated provider runs
  produced identical proposal geometry. These fixture regions are regression support, not reviewed
  ground truth.
- After removing crop inference and duplicate suppression, `local-rfdetr-fine-frame` matched the
  direct provider's polygon metrics on every held-out frame: 228/292 (78.08%) recall, 56 false
  proposals, and 2 duplicate proposals. The 104-frame output digest is
  `b25f86926ed3d26cb8abd546aa199a12e80eb5644f2dad4d7e753e77f034448a`.
- The selected provider's measured frame groups include 37 small-card frames (87/111 recall), 21
  frame-edge frames (59/76), 6 far-field frames (14/24), 20 single-card frames (20/20), and 58
  overlapping-box frames (149/210). Central-card frames reached 184/245. Group definitions and
  frame-level metrics are in the report.
- The fine checkpoint used in this comparison was not trained on cluster crops. The comparison
  exercised the previous all-cluster crop-replacement arbitration policy, which could remove
  full-frame predictions. It does not measure the selective, one-to-one refinement algorithm now
  implemented.
- The comparison uses polygon IoU and measures the returned provider proposals. The earlier 0068
  campaign report uses mask metrics, so its recall value is not directly comparable. The 0082
  comparison does not establish background-only precision or production readiness.
- Correction: this evidence does not justify removing crop inference. The provider routes only
  small clusters that gain at least 1.5 times crop resolution. It refines one-to-one matched
  candidates only when crop confidence improves by at least 0.05. It preserves each full-frame
  candidate and adds unmatched crop candidates only at confidence 0.70 or higher. Evaluation with
  the current model remains open.
- The complete per-frame metrics and timing values are in the linked JSON report. Its SHA-256 is
  `9e6e2718ae2a41e750491bee6117b59e18a1481ef1011ad93dca9e6f2797d9c4`.

#### M3 acceptance criteria

- The full-frame result intersects both exact central-card regression support regions. These regions
  are not reviewed ground truth.
- Use the existing reviewed fine-model checkpoint on held-out source recordings. No new model
  training is required.
- Every full-frame candidate remains represented in the output. Crop refinement can change its
  geometry, but it cannot delete the candidate.
- Far-field and overlap subsets have enough reviewed cases to support a separate result. Do not use
  the current six-frame far-field subset as a crop-removal gate.
- The report records refined candidates, crop additions, strict duplicates, false positives,
  overlap separation, routed and skipped clusters, crop area, full-frame and crop latency, total
  latency, and deterministic output.

### M4 — Register and migrate the active path

- Register `local-rfdetr-fine-frame` as an explicit selectable, non-default provider and update
  backend settings, provider discovery, run controls, documentation, fixtures, and focused tests.
- Migrate active configuration and examples from the retired cascade provider to the refinement
  provider.
- Keep the epic board link to 0071's closed `Superseded` record and do not reopen or rewrite its
  historical implementation evidence.
- Record the final bundle digest, provider version, threshold, evaluation report, and known limits.

#### M4 acceptance criteria

- New runs can select the current-model fine-frame refinement provider without any coarse bundle or
  coarse code installed.
- The default provider is unchanged unless a later decision explicitly promotes this provider.
- Active documentation and UI use the replacement name and semantics.
- 0071 remains a linked historical record of the superseded coarse cascade, and 0082 records the
  replacement decision and validation evidence.

## Verification

Run the focused visible-card cascade/provider, RF-DETR segmentation, backend provider-selection,
and web run-control tests. Run the repository's applicable formatting, type, and static checks for
the changed Python and web paths. Re-run the exact two event frames and the held-out challenge
report from a clean local environment. Record unrelated pre-existing failures separately.
