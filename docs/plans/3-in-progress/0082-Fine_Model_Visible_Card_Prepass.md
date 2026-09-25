# Fine-model small-card instance refinement

## Plan status

- **Summary:** Remove the RF-DETR Small card-cluster stage. Use the same RF-DETR SegMedium model
  for full-frame detection and size-gated crop refinement. M3 measures small-card instance
  separation and crop cost. Card count is not a routing signal.
- **Status:** In Progress
- **Depends on:** Completed 0048 pipeline data and execution, completed 0049 recording pipeline
  review, completed 0068 reviewed RF-DETR visible-card segmentation, and the 0071 fine-stage
  model and source-coordinate crop contracts. The 0071 coarse stage is the removal target.
- **Builds on:** `local-rfdetr-segmentation`, the reviewed `visible_card` segmentation contract,
  and the deterministic cluster-crop transforms created in 0071.
- **Outcome:** The `local-rfdetr-fine-frame` provider uses one fine model on the complete source
  frame and on crops that contain a predicted small card. It keeps every full-frame candidate and
  its identity. Confident crop results can refine geometry or add a missed card. The provider uses
  no coarse model, `card_cluster` model bundle, or cascade child bundle. M4 will register it after
  M3.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Decision

### Full-frame main result with size-gated crop refinement

The first M3 comparison used an all-cluster crop pass and replacement arbitration. It did not test
the targeted crop refinement in this decision. Keep the current fine model. Do not start a new
training run in this epic.

Correction: provider v2 ran crops for every cluster and treated crop results as additions. Provider
v3 used the short side of each box. It sent 98.2% of clusters to crops, so it did not route
selectively. A v4 trial used the square root of visible-mask area. It also sent 98.2% of clusters
to crops and marked all full-frame predictions as small. A v5 trial used the longer visible-box
side, but its 20% cutoff still routed 93.6% of clusters. Keep every full-frame candidate and
identity.

Use `local-rfdetr-fine-frame` version `local-rfdetr-fine-frame-v6` with schema
`local-rfdetr-fine-frame/v6`. Keep the current 0.5 confidence threshold for full-frame and crop
inference. Use the full-frame result as the main candidate set. Estimate each predicted card's
size from the longer side of its tight visible-region box after scaling the source frame's long
edge to the 432-pixel model input. Route its cluster when at least one member is at most one eighth
of the model input (54 pixels) and the crop gives at least 1.5 times the full-frame resolution.
This measures projected card size. It does not use the number of cards as a routing signal.

The longer side avoids treating the short dimension of an ordinary card as its distance cue. The
evaluation must check cases where the full-frame model merges several cards into one large region.
The size rule may not identify those cases by itself.

Match crop results one-to-one with predictions from their source cluster when box IoU and visible-
mask IoU are both at least 0.50. Rank qualifying matches for each candidate by the lower of box IoU
and mask IoU. Accept a pair only when it is the best match for both candidates and leads each
candidate's second choice by at least 0.10. Refine a matched candidate's geometry only when crop
confidence is at least 0.05 higher. Keep the full-frame candidate and its identity. Add an unmatched
crop result only when its score is at least 0.70. Drop near-identical duplicates only when both box
IoU and visible-mask IoU are at least 0.90, always keeping the earlier main result. Do not suppress
by containment or general overlap. A failed crop leaves the full-frame result intact.

This policy preserves every full-frame candidate while letting high-confidence crop results improve
small-card geometry or add a missed instance. Crop false positives and extra split predictions can
still reduce precision, so M3 must report them with small-card and overlap results.

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
- routing by predicted card size at the 432-pixel model input, with a minimum crop scale gain;
- one-to-one source-frame matching, geometry refinement, high-confidence crop additions, and strict
  duplicate reconciliation that preserve all full-frame candidates;
- a new selectable provider and one fine-model bundle contract;
- removal of coarse model loading, training, evaluation, bundle assembly, and provider wiring; and
- held-out evaluation of small-card instance separation, overlap, false positives, crop cost, and
  latency. Card count alone is not a quality measure or routing signal.

The epic does not include:

- a second detector, a `card_cluster` target, or a coarse-model fallback;
- sliding windows, fixed table crops, or a multi-scale fine-model sweep;
- a default visible-card provider change or model promotion;
- changes to CardEventNet, event-frame selection, visual card identity, or game reconstruction; or
- rewriting historical 0071 reports and stored results that document the retired coarse cascade.

## Provider contract

### Frozen M0 choices

- Provider: `local-rfdetr-fine-frame`; provider version: `local-rfdetr-fine-frame-v6`.
- Provider schema: `local-rfdetr-fine-frame/v6`; bundle schema: the existing
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
- Keep every valid full-frame candidate in the final result. Route a cluster when at least one
  member's longer visible-box side, scaled to 432 pixels along the source frame's long edge, is at
  most 12.5% of the model input (54 pixels) and the crop provides at least 1.5 times scale.
  Record the size of every member and the crop scale gain. Do not route by cluster or frame card
  count. Match crop results one-to-one to candidates in their source cluster
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
  threshold, 12.5% model-input card-size limit, 1.5 crop scale gain, 0.50 one-to-one match thresholds,
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
transform. Use valid full-frame predictions as crop-routing proposals. Estimate each member's
projected size from the longer side of its visible-region box, scaled to a 432-pixel model input
along the source frame's long edge. Route the cluster when at least one member is at most 12.5% of
that input (54 pixels) and crop scale gain is at least 1.5. Do not use the number of cards in a
cluster or frame as a routing signal.
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

- **M0:** Complete — freeze the one-model provider, base-preserving arbitration, crop transforms,
  thresholds, and exact-frame regression fixtures. M3 supersedes the original v3 size metric.
- **M1:** Complete — add the shared fine-model pass with selective size-based crop routing, one-to-one
  geometry refinement, high-confidence additions, strict duplicate checks, crop fallback, and
  focused tests.
- **M2:** Complete — remove coarse training, bundle, CLI, registry, configuration, and active UI
  surfaces. Keep cluster geometry under neutral names and keep historical evidence readable.
- **M3:** Complete — provider v6 routes on projected card length at 12.5% of the 432-pixel input.
  It routes 56.4% of clusters and lowers crop cost. It preserves full-frame recall, but does not
  improve small-card or overlap recall. The new provider stays non-default. See the [v6 evaluation
  report](../../reports/0082-M3_One_Eighth_Size_Refinement_Evaluation.json), the [v3 refinement
  report](../../reports/0082-M3_Fine_Frame_Refinement_Evaluation.json), the [v4 area-metric
  trial](../../reports/0082-M3_Size_Gated_Refinement_Evaluation.json), and the [v5 20% long-side
  trial](../../reports/0082-M3_Long_Side_Size_Refinement_Evaluation.json).
- **M4:** Next — register provider v6 as a selectable non-default option and migrate active
  references. Keep 0071 as the closed, superseded implementation record.

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

### M3 — Validate current-model small-card refinement

- Use the current reviewed fine-model bundle. Do not train a new model for this epic.
- Compare the full-frame main result with size-gated crop refinement on source-linked reviewed cards
  across small projected sizes, central and edge positions, single-card frames, and overlapping
  cards. The far-field location group is informative, but card size and instance separation define
  the routing question.
- Report full-frame and final recall for cards at or below the routing size, crop additions and
  false positives, likely merged predictions, split duplicates, crop failures, routed and skipped
  clusters, crop area, and latency separately.
- Check whether the full-frame model merges more than one reviewed card into one region. This is a
  known case where an area-only router may not see a small individual card.
- Do not remove crop inference based only on total card count or aggregate recall. Use the reviewed
  small-card and overlap results and measured cost to set the provider's selectable behavior.

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

#### M3 v3 refinement evaluation — 2026-09-25

- Evaluated provider v3 with the reviewed 0068 checkpoint on 104 sealed-test frames and 51
  source-linked, human-corrected frames from IMG_0644. IMG_0644 is outside the model's training and
  validation recordings. The combined set has 155 frames and 437 reviewed card regions across four
  recordings.
- On the sealed set, full-frame inference matched 228/292 cards (78.08%), with 56 false proposals
  and 2 duplicate proposals. Refinement matched the same 228/292 cards, with 61 false proposals and
  4 duplicate proposals. The overlapping-card subset stayed at 149/210 matches. Its mean polygon
  IoU rose from 0.8932 to 0.8969, but refinement added no card recall there.
- The provider refined 45 full-frame geometries. Thirty-nine had higher IoU against their matched
  reviewed region. It added 45 crop predictions: 3 matched regions already matched by full-frame
  results, 8 were false, 33 were inside reviewed ignore regions, and 1 was a strict duplicate. The
  provider removed no full-frame candidate. Crop refinement added no card recall on the sealed set.
- The far-field subset has 6 frames and 24 cards, all from IMG_0646. It stayed at 14/24 matches,
  with no geometry refinements or crop additions. IMG_0644 adds frame-edge and overlap cases, but no
  cards in the top third. This does not meet the far-field coverage requirement.
- The current 96-pixel routing rule sent 216 of 220 clusters to crops (98.2%). The median sum of
  crop-area ratios was 0.2345 per frame. On MPS, median prepass latency was 191 ms, crop latency
  was 147 ms, total latency was 465 ms, and total latency p95 was 876 ms. This routing is too broad
  to validate rare far-cluster behavior or its cost.
- Repeated runs produced identical geometry. The full-frame pass and final result intersect both
  exact central-card regression fixtures. These support regions are regression checks, not reviewed
  ground truth.
- The evaluation excludes unfinished IMG_0650, IMG_0652, IMG_0653, IMG_0654, IMG_0656, and IMG_0671
  drafts. It does not establish background-only precision. No model training was performed.
- The source digests, per-frame metrics, crop decisions, timing, and repeated-run digests are in
  [the v3 refinement report](../../reports/0082-M3_Fine_Frame_Refinement_Evaluation.json). It is
  historical evidence. The current evaluation script runs provider v6 and writes the linked v6
  report by default.

#### M3 v4 area-size routing trial — 2026-09-25

- Evaluated `local-rfdetr-fine-frame-v4` with the reviewed 0068 checkpoint on the same 155 reviewed
  frames, 437 card regions, and four recordings.
- The square-root visible-mask-area metric still routed 216 of 220 clusters (98.2%). It put all
  495 full-frame predictions below the 86.4-pixel cutoff. This metric did not separate small
  projected cards from the rest of the reviewed set.
- Full-frame and refined recall both matched 358/437 regions. Crop inference added no recall and
  increased false proposals from 69 to 77 and duplicates from 2 to 6. Median total latency was
  496 ms and p95 was 948 ms on MPS.
- The v4 metric is rejected. Provider v5 uses the longer side of each visible-region box as the
  projected card-size estimate. This is an evaluation revision, not a model change. See the
  [v4 area-metric trial report](../../reports/0082-M3_Size_Gated_Refinement_Evaluation.json).

#### M3 v5 20% long-side routing trial — 2026-09-25

- Evaluated provider v5 with the reviewed 0068 checkpoint on 155 reviewed frames and 437 card
  regions from four recordings.
- The longer visible-box side was at or below 86.4 pixels for 421/495 full-frame candidates.
  Because routing triggers when any member of a cluster is small, it sent 206/220 clusters (93.6%)
  to crops. The reviewed targets below the same cutoff were 351/437.
- Full-frame and refined recall both matched 358/437 regions overall. For the 351 below-cutoff
  targets, both matched 294. Crop inference added no recall and increased false proposals from 69
  to 77 and duplicates from 2 to 6. It refined 45 geometries; 39 had higher polygon IoU. The
  provider removed no full-frame candidate.
- Median crop-area ratio was 0.2186 per frame. Median total latency was 493 ms and p95 was 941 ms
  on MPS. Repeated output was deterministic.
- The 20% cutoff is too broad. Provider v6 tests a 12.5% cutoff (54 pixels). See the
  [v5 long-side trial report](../../reports/0082-M3_Long_Side_Size_Refinement_Evaluation.json).

#### M3 v6 one-eighth long-side evaluation — 2026-09-25

- Evaluated provider v6 with the reviewed 0068 checkpoint on 155 reviewed frames and 437 card
  regions across four recordings. The longer visible-box side cutoff was 54 pixels at the 432-pixel
  model input. The cutoff is an exploratory routing choice selected from these size and cost
  measurements. The result is not a final promotion gate.
- The provider routed 124/220 clusters (56.4%) and skipped 96. The median crop-area ratio fell to
  0.0344 per frame. On MPS, median crop latency was 73 ms, median total latency was 298 ms, and
  total latency p95 was 698 ms.
- Full-frame and final results both matched 358/437 reviewed regions (81.9%). The 101 reviewed
  regions at or below 54 pixels had 81 matches before and after crop refinement. The overlap group
  matched 198/273 regions both before and after refinement.
- Crop inference refined 43 full-frame geometries; 37 had higher polygon IoU. It added 40
  candidates: 1 matched a reviewed region, 5 were false, 33 were in reviewed ignore regions, and
  1 was a duplicate. The provider removed no full-frame candidate. Overall false proposals rose
  from 69 to 74 and duplicates rose from 2 to 4.
- The six top-third frames still had 14/24 matches and no crop changes. They are all from IMG_0646.
  Small-card targets at or below 54 pixels were spread across IMG_0644 (38), IMG_0646 (61), and
  IMG_0648 (2). Other reviewed targets were above the cutoff.
- Both exact central-card support regions intersected the full-frame and final results. They are
  regression fixtures, not reviewed ground truth. Repeated output was deterministic, with geometry
  digest `85b46110457f11993accfa1d06cd17c475ed9e7d6643db7194b12063f19069a1`. The report SHA-256
  is `5658f22c1e31306865b59e4e3ccd1c37cdd2095eb0f67126a45b3e5772cab2b2`.
- This evaluation completes M3's size-routing and cost comparison. It does not show improved card
  recall or overlap separation. Keep provider v6 selectable but non-default, and do not promote it
  from these results.

#### M3 acceptance criteria

- The full-frame result intersects both exact central-card regression support regions. These regions
  are not reviewed ground truth.
- Use the existing reviewed fine-model checkpoint on held-out source recordings. No new model
  training is required.
- Every full-frame candidate remains represented in the output. Crop refinement can change its
  geometry, but it cannot delete the candidate.
- The provider routes from each predicted card's longer visible-box side scaled to the 432-pixel
  model input. It does not route from the number of cards in a frame or cluster.
- The report gives a separate full-frame and final result for reviewed cards at or below the size
  threshold, and records overlap separation, split duplicates, crop additions, crop false positives,
  routed and skipped clusters, crop area, latency, and deterministic output.
- The report lists reviewed sample counts by size and recording. It reports top-third far-field
  coverage as a limitation, without using that location-only count as a proxy for small-card size.

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
