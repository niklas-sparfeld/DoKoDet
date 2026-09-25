# Fine-model full-frame prepass for visible-card detection

## Plan status

- **Summary:** Remove the RF-DETR Small card-cluster stage and use one RF-DETR SegMedium fine
  model for a full-frame prepass followed by optional card-cluster crop refinement.
- **Status:** Ready
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

- **M0:** Ready — freeze the fine-prepass contract, result arbitration, threshold policy, and
  exact-frame regression fixtures.
- **M1:** Ready — replace the runtime provider with the shared fine-model prepass and crop
  refinement path.
- **M2:** Ready — remove coarse training, bundle, CLI, registry, configuration, and active UI
  surfaces while retaining generic crop geometry and historical evidence readability.
- **M3:** Ready — run the focused and held-out comparison and record the decision metrics.
- **M4:** Ready — register the replacement provider and migrate active references while keeping
  0071 as the closed, superseded implementation record.

## Delivery milestones

### M0 — Freeze the fine-prepass contract

- Inspect the 0071 provider, bundle, crop layout, reconciliation, and diagnostics before editing.
- Add exact source-frame fixtures for `event-000010` at `t_us=38141669` and `event-000012` at
  `t_us=54483336`. Assert that the central visible cards are present in the full-frame fine
  prepass and remain present in the final result.
- Define the prepass threshold, crop-routing threshold semantics, crop coverage rule, arbitration
  behavior, failure fallback, provider name, schema version, and manifest fields.
- Define the comparison report fields: visible-card recall, central-card recall, overlapping-card
  separation, merged-plus-split duplicates, false positives, crop count, crop-area ratio,
  prepass latency, crop latency, total latency, and deterministic output digest.

#### M0 acceptance criteria

- The contract contains no coarse model, coarse threshold, `card_cluster` training target, or
  second model bundle.
- The two exact frames are reproducible test inputs with source-linked expected outcomes.
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
