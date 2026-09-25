# Fine-model full-frame prepass for visible-card detection

## Plan status

- **Summary:** Remove the RF-DETR Small card-cluster stage and use one RF-DETR SegMedium fine
  model for a full-frame prepass followed by optional card-cluster crop refinement.
- **Status:** In Progress
- **Depends on:** Completed 0048 pipeline data and execution, completed 0049 recording pipeline
  review, completed 0068 reviewed RF-DETR visible-card segmentation, and the 0071 fine-stage
  model and source-coordinate crop contracts. The 0071 coarse stage is the removal target.
- **Builds on:** `local-rfdetr-segmentation`, the reviewed `visible_card` segmentation contract,
  and the deterministic cluster-crop transforms created in 0071.
- **Outcome:** One selectable `local-rfdetr-fine-prepass` provider that runs the fine model on the
  complete source frame, derives card clusters from those fine predictions, refines those clusters
  with the same fine model, and publishes deterministic source-frame results without any coarse
  model, `card_cluster` model bundle, or cascade child bundle.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Decision

The coarse model is parked indefinitely. Do not lower its threshold, retrain it, or keep it as a
fallback. The replacement is a fine-model prepass:

1. Run the RF-DETR SegMedium visible-card model once on the complete source frame.
2. Use its `visible_card` boxes as routing proposals for deterministic card-cluster formation and
   padded square cluster crops.
3. Run the same loaded fine model on each cluster crop.
4. Prefer crop results when they refine a prepass result, retain the full-frame result when crop
   refinement is unavailable or does not supersede it, and preserve distinct overlapping cards.

This keeps the full-frame fine inference as a recall path. The crop pass is a resolution and
instance-separation refinement, not a second detector family. The two exact decision frames that
motivated this change are fixed regression cases: the full-frame fine model finds the central cards
that the configured coarse pass omitted, while crop inference gives better separation confidence
for the overlapping cards.

## Fixed scope

The epic includes:

- one fine RF-DETR model load shared by the full-frame and crop calls;
- a full-frame fine prepass with explicit prepass threshold and source-coordinate diagnostics;
- card-cluster formation from prepass `visible_card` boxes, reusing the reversible crop geometry;
- fine inference on the resulting padded square crops;
- source-frame mapping, crop-first arbitration, and duplicate reconciliation that do not suppress
  separate overlapping cards;
- a new selectable provider and one fine-model bundle contract;
- removal of coarse model loading, training, evaluation, bundle assembly, and provider wiring; and
- held-out evaluation of recall, overlap separation, false positives, crop cost, and latency.

The epic does not include:

- a new fine-model training campaign unless a measured M0 result proves the existing fine bundle
  cannot support the prepass;
- a second detector, a `card_cluster` target, or a coarse-model fallback;
- sliding windows, fixed table crops, or a multi-scale fine-model sweep;
- a default visible-card provider change or model promotion;
- changes to CardEventNet, event-frame selection, visual card identity, or game reconstruction; or
- rewriting historical 0071 reports and stored results that document the retired coarse cascade.

## Provider contract

### Frozen M0 choices

- Provider: `local-rfdetr-fine-prepass`; provider version: `local-rfdetr-fine-prepass-v1`.
- Provider schema: `local-rfdetr-fine-prepass/v1`; bundle schema: the existing
  `rfdetr-segmentation-bundle/v1` with one `RFDETRSegMedium` `visible_card` model at 432 × 432.
- Load one fine model from one bundle. Use it for both the full-frame prepass and crop refinement.
- Use a confidence threshold of `0.5` for both the prepass candidates and crop routing. Keep
  candidates whose score is greater than or equal to the threshold. Record both values in the
  manifest and raw response. Do not tune either threshold on the two fixed regression frames.
- Route every usable, finite, in-frame prepass box at or above the threshold. Assign each routed
  prediction to exactly one deterministic connected component using the existing median-shorter-side
  expansion and transitive-intersection rule. Each crop must contain the complete union box for its
  component. Keep the existing square crop, neutral padding, and reversible source-coordinate
  transform. An empty prepass produces no crops.
- Keep full-frame predictions as the initial result. A successful crop can replace or split a
  prepass candidate only within its source cluster. Map crop geometry to source coordinates before
  arbitration. Suppress a prepass candidate only when the union of that cluster's mapped crop masks
  covers at least 75% of its visible-mask pixels. Treat crop output as a set: retain each distinct
  crop prediction, including overlapping cards. Do not suppress predictions by box overlap alone.
  Reconcile duplicates only when both box IoU and visible-mask IoU are at least 0.90, or when mask
  containment and box containment are both at least 0.75 and the smaller box is at most 95% of the
  larger box. Use score, stable cluster order, proposal order, and prediction ID as tie-breaks. Keep
  unmatched prepass candidates.
  If a crop fails or cannot run, keep that cluster's prepass candidates and report the partial failure.
- Reject non-finite, degenerate, or out-of-frame model geometry deterministically. A bad candidate
  does not invalidate other valid candidates. A malformed source frame fails the item.
- Use the two fixed JPEGs in
  [`tests/fixtures/visible_card_fine_prepass/`](../../../table_evidence_analyzer/tests/fixtures/visible_card_fine_prepass/)
  as exact model inputs. Their frame hashes link them to `game-2026-09-18-01-003` and the two event
  times below. The expected regions are regression support regions copied from a direct local fine
  model result. They are not reviewed reference geometry or ground truth.
- Record `prepass`, `clusters`, `refinement`, `arbitration`, `mapping`, `reconciliation`, and
  `timing` sections in the raw response. Include model and bundle identity, both 0.5 thresholds, the
  0.75 crop-coverage threshold, the 0.90 duplicate-IoU threshold, source-frame
  dimensions and digest, cluster-to-prepass attribution, crop transforms, per-crop outcome, and final
  proposal provenance. Do not emit coarse-stage names or identities.
- Freeze comparison fields as visible-card recall, central-card recall, overlapping-card separation,
  merged-plus-split duplicates, false positives, crop count, crop-area ratio, prepass latency, crop
  latency, total latency, and deterministic output digest. Report prepass misses, crop failures, and
  arbitration errors separately.

### Full-frame fine prepass

The provider decodes one complete source frame and runs the fine segmentation model at its declared
model input size. It keeps the model's visible-card polygons, tight derived boxes, scores, masks,
and source-frame dimensions. The prepass threshold is a routing and candidate threshold, not a
coarse cluster threshold. Its value and selection rule must be recorded in the provider manifest
and measured against held-out reviewed cards.

When the prepass returns no usable predictions, the provider returns an empty result and does not
run crop inference. It must report this as valid negative evidence, not as a coarse-stage failure.

### Prepass-derived card clusters

Use the existing deterministic connected-component layout and reversible source-coordinate
transform, but rename its proposal and diagnostic fields so they describe fine prepass predictions.
The layout must preserve the current behavior for one prediction, nearby overlapping predictions,
frame-edge boxes, neutral padding, non-finite geometry, and an empty prepass.

The provider must record which prepass predictions created each card cluster. A cluster is an
image-processing unit only. It does not assert a pile, trick, card play, or other gameplay
relationship.

### Refinement and arbitration

Run the same fine model on every prepass-derived cluster. Map all crop polygons, masks, and boxes
back to the exact source frame before reconciliation.

Use this result policy:

- the full-frame prepass is the initial candidate set and the fallback for a crop that fails or is
  unavailable;
- a successful crop refinement supersedes the prepass representation for the same card or refined
  cluster, including a merged prepass result that is separated into multiple crop results;
- crop results may add a separately visible card that the prepass merged into the same cluster;
- retain unmatched prepass candidates only when the crop result does not cover or supersede them;
  do not emit a merged prepass candidate together with its split crop children; and
- use stable source geometry, model provenance, and deterministic tie-breaks. Do not use generic
  high overlap alone to suppress two physically overlapping visible cards.

The raw response must distinguish `prepass`, `clusters`, `refinement`, `arbitration`, `mapping`,
`reconciliation`, and `timing`. It must not expose `coarse`, `coarse_bundle`, or a `card_cluster`
model identity.

## Milestone status

- **M0:** Complete — freeze the fine-prepass contract, result arbitration, threshold policy, and
  exact-frame regression fixtures.
- **M1:** Complete — add the shared fine-model prepass and crop-refinement provider with
  deterministic source mapping, arbitration, crop fallback, and focused regression tests.
- **M2:** Complete — remove coarse training, bundle, CLI, registry, configuration, and active UI
  surfaces. Keep cluster geometry under neutral names and keep historical evidence readable.
- **M3:** Ready — run the focused and held-out comparison and record the decision metrics.
- **M4:** Ready — register the replacement provider and migrate active references while keeping
  0071 as the closed, superseded implementation record.

## Delivery milestones

### M0 — Freeze the fine-prepass contract

- Inspect the 0071 provider, bundle, crop layout, reconciliation, and diagnostics before editing.
- Add exact source-frame JPEG fixtures for `event-000010` at `t_us=38141669` and `event-000012` at
  `t_us=54483336`. Record their source video digest, frame identity, image digest, and the central
  fine-model regression support regions in the fixture manifest.
- Define the prepass threshold, crop-routing threshold semantics, crop coverage rule, arbitration
  behavior, failure fallback, provider name, schema version, response and manifest fields.
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
- Map both prepass and crop predictions to source coordinates and implement the M0 arbitration
  policy. Ensure a crop failure does not erase valid prepass proposals.
- Add focused unit and provider tests for empty prepass, one card, overlapping cards, merged
  prepass plus split crop results, frame-edge padding, crop failure, duplicate crops, and stable
  repeated output.

#### M1 acceptance criteria

- The provider performs no RF-DETR Small inference and loads no coarse bundle.
- The exact event fixtures retain the central cards in the final proposals.
- Crop results improve or match full-frame results on overlap cases without emitting merged-plus-
  split duplicates.
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

### M3 — Validate recall, separation, and cost

- Compare the direct full-frame fine provider with fine prepass plus crop refinement on the frozen
  exact frames and a held-out reviewed challenge set containing small, central, far-field, frame-
  edge, single-card, and overlapping-card cases.
- Use source-linked reviewed visible regions as the authority. Report prepass misses separately
  from crop-refinement failures and arbitration errors.
- Confirm that crop refinement adds enough overlap separation to justify its cost. If it adds no
  measured value, record that result and simplify the provider to full-frame fine only before M4.

#### M3 acceptance criteria

- Both exact central-card cases are recovered.
- The replacement meets the declared visible-card recall floor and has no unexplained regression
  against direct full-frame fine on held-out data.
- Overlapping-card separation improves or matches direct full-frame fine, with zero unexplained
  merged-plus-split duplicate cases in the frozen challenge set.
- The report records crop count, crop-area ratio, prepass latency, refinement latency, total
  latency, false positives, and deterministic repeat results.

### M4 — Register and migrate the active path

- Register `local-rfdetr-fine-prepass` as an explicit selectable, non-default provider and update
  backend settings, provider discovery, run controls, documentation, fixtures, and focused tests.
- Migrate active configuration and examples from the retired cascade provider to the replacement.
- Keep the epic board link to 0071's closed `Superseded` record and do not reopen or rewrite its
  historical implementation evidence.
- Record the final bundle digest, provider version, threshold, evaluation report, and known limits.

#### M4 acceptance criteria

- New runs can select the fine-prepass provider without any coarse bundle or coarse code installed.
- The default provider is unchanged unless a later decision explicitly promotes this provider.
- Active documentation and UI use the replacement name and semantics.
- 0071 remains a linked historical record of the superseded coarse cascade, and 0082 records the
  replacement decision and validation evidence.

## Verification

Run the focused visible-card cascade/provider, RF-DETR segmentation, backend provider-selection,
and web run-control tests. Run the repository's applicable formatting, type, and static checks for
the changed Python and web paths. Re-run the exact two event frames and the held-out challenge
report from a clean local environment. Record unrelated pre-existing failures separately.
