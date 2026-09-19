# Coarse-to-fine visible-card detection

## Plan status

- **Summary:** Find card clusters in the full source frame, run the reviewed RF-DETR segmentation
  model at higher effective card resolution on each cluster crop, and train one model for each stage.
- **Status:** In Progress
- **Depends on:** 0048 pipeline data and execution, 0049 recording pipeline review, and the 0068
  reviewed RF-DETR training corpus, checkpoint, provider, and evaluation boundaries
- **Outcome:** One locally reproducible `local-rfdetr-cascade` provider with a detection-only
  full-frame card-cluster model, a crop-trained visible-card segmentation model, deterministic
  source-coordinate mapping, and retained end-to-end diagnostics.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — frozen cascade identities, deterministic cluster/crop transforms, and duplicate reconciliation contracts are implemented and covered by focused tests.
- **M1:** Complete — the development provider reuses one 0068 bundle for full-frame clustering and
  fine crop inference, with source-linked mapping, reconciliation, and partial diagnostics.
- **M2:** Not started — derive and materialize the full-frame card-cluster detection dataset.
- **M3:** Not started — train and bundle one RF-DETR Small full-frame card-cluster model.
- **M4:** Not started — derive and materialize the cluster-crop segmentation dataset.
- **M5:** Not started — fine-tune and bundle one RF-DETR SegMedium cluster model.
- **M6:** Not started — assemble, integrate, and verify the completed cascade provider.

## 1. Purpose

The current RF-DETR SegMedium provider reduces each complete source frame to 432 × 432 before it
separates visible-card instances. Cards close to the camera retain enough pixels and perform well.
Cards far from the camera lose boundary detail. Overlapping cards then become several approximate
segments that do not correctly separate the physical cards.

This epic implements one coarse-to-fine response. It does not re-evaluate whether full-frame
resolution is the cause and does not compare unrelated architectures.

The cascade has two learned stages:

1. A detection-only RF-DETR Small model processes the complete source frame at 512 × 512 and returns
   high-recall `card_cluster` boxes. It does not separate physical cards and does not return visible
   regions.
2. The existing RF-DETR SegMedium architecture processes each cluster crop at 432 × 432 and returns
   separate `visible_card` instances. This model starts from the selected 0068 checkpoint and is
   fine-tuned on cluster crops made from reviewed source frames.

RF-DETR Small is selected for the coarse stage because detection is cheaper than instance
segmentation, its 512 × 512 input preserves more full-frame evidence than RF-DETR Nano at 384 × 384,
and the task needs cluster coverage rather than fine geometry. No model-size sweep is part of this
epic.

## 2. Fixed scope

The epic includes:

- deterministic clustering of coarse full-frame proposals;
- padded square cluster crops with reversible source-frame transforms;
- fine segmentation on every cluster crop;
- deterministic full-frame mapping and duplicate reconciliation;
- a derived full-frame card-cluster detection dataset;
- one RF-DETR Small coarse training run;
- a derived cluster-crop instance-segmentation dataset;
- one RF-DETR SegMedium fine-tuning run; and
- one selectable backend provider that retains both model and transform identities.

The epic excludes:

- SAM or another promptable segmenter;
- fixed table crops, sliding windows, or tiling as alternate paths;
- model-size, resolution, clustering-policy, threshold, augmentation, or seed sweeps;
- synthetic-data generation or changes to epic 0070;
- visual card identity training;
- new background-only, face-down, motion, or hand-occlusion data campaigns;
- a production champion or default-provider change; and
- changes to CardEventNet, event-frame selection, or game reconstruction.

The completed cascade becomes an explicit selectable annotation and pipeline provider. Promotion or
a default change requires later evidence and is not part of this epic.

## 3. Cascade contract

### 3.1 Coarse proposals and card clusters

The initial M1 implementation uses the selected 0068 RF-DETR SegMedium bundle for the coarse pass.
It ignores the proposal polygons after it derives their tight source-frame boxes. M3 replaces only
this coarse pass with the trained RF-DETR Small `card_cluster` model. The cluster and crop algorithm
does not change between these providers.

Build card clusters as follows:

1. Keep every coarse proposal at or above the configured coarse threshold.
2. Calculate each proposal's tight source-frame box.
3. Let the reference span be the median shorter side of the retained boxes. Expand every box by one
   half reference span on all four sides.
4. Connect two proposals when their expanded boxes intersect. Each transitive connected component
   is one card cluster.
5. Calculate the tight union box of the original, unexpanded member boxes.
6. Add one half reference span of context on all four sides.
7. Expand the result to a square around its center. Preserve out-of-frame space with neutral RGB
   `(128, 128, 128)` padding instead of shifting or distorting the crop.

The recipe must define deterministic rounding and behavior for a single proposal, equal coordinates,
frame-edge crops, and no coarse proposals. It must reject non-finite or out-of-frame input geometry.
Every cluster records its member proposals, source box, padded square box, crop dimensions, scale,
padding, and forward and inverse coordinate transforms.

The reference span is calculated once per frame. A large merged coarse proposal can therefore form
one useful cluster even when its instance geometry is poor. Nearby proposals form one crop so that
the fine model sees the complete overlap relationship.

### 3.2 Fine results and reconciliation

Run the fine provider independently on each cluster crop. Preserve all connected polygon components
of each returned instance. Map points, masks, boxes, and normalization metadata back to the exact
source frame before creating pipeline candidates.

Square crops can overlap after context expansion. Reconcile only near-identical mapped predictions:
two results are duplicates when both their tight-box IoU and visible-mask IoU are at least `0.90`.
Keep the result with the higher fine-stage confidence. Use the stable cluster ID and proposal order
as tie-breakers. Do not suppress two overlapping cards merely because they share many pixels.

The final result retains:

- both model bundle identities;
- the cascade and crop-recipe versions;
- the coarse proposals and confidence values;
- every cluster and coordinate transform;
- fine results before source mapping;
- duplicate-reconciliation decisions;
- final source-frame candidates; and
- coarse, crop, fine, mapping, and total latency.

An unavailable stage produces an unavailable result with its completed diagnostics. Do not silently
fall back to the old full-frame output.

## 4. Training data and model choices

### 4.1 Full-frame card-cluster model

Derive the `card_cluster` targets from completed reviewed visible-card references in the frozen 0068
partitions. Use each reviewed card's complete visible-region tight box as an input to the same fixed
connected-component rule in section 3.1. Store the tight union of the unexpanded member boxes as one
detection target. Do not create one target per physical card for this model.

Only frames with complete visible-card review coverage can supply cluster targets. Exclude frames
with visible-card ignore regions or ineligible outcomes because they do not prove complete cluster
coverage. Do not require background-only frames for this event-frame locator.

Train exactly one detection-only `RFDETRSmall` model from its official pretrained checkpoint with
one class, `card_cluster`, at 512 × 512. Freeze the package version, checkpoint digest, seed, recipe,
augmentation, optimizer, split, threshold-selection rule, and resource bound before the real run.
Select the highest confidence threshold that meets the frozen reviewed-card crop-containment recall
floor on validation. This is threshold calibration for the one provider, not a model comparison.

The coarse report must include cluster recall, reviewed-card crop-containment recall, missed cards,
extra clusters, clusters per frame, crop area relative to source area, and coarse latency. A crop
contains a reviewed card only when the complete reviewed visible region fits inside the crop after
source-coordinate rounding.

### 4.2 Cluster-crop segmentation model

Build training and validation cluster crops from reviewed targets, not from coarse model predictions.
Use the exact runtime crop and transform implementation. Apply one frozen crop perturbation policy
for coarse-location tolerance. Translation and scale perturbations must keep every assigned reviewed
visible region complete inside the crop. Include all reviewed card instances that fall inside the
cluster. Preserve multi-polygon visible regions.

Fine-tune exactly one `RFDETRSegMedium` model at 432 × 432 from the selected 0068 checkpoint. Keep
the 0068 package version and one `visible_card` class. Freeze the seed, training recipe, crop
perturbation, augmentation, optimizer, threshold, checkpoint-selection rule, and resource bound
before training. Do not train another full-frame segmentation baseline in this epic.

The fine report must include mask AP 0.50:0.95, instance recall, duplicate predictions, exact
card-count frames, and overlapping-target separation. For each reviewed pair whose tight boxes overlap,
the separation metric records whether two distinct predictions match the two reviewed visible
regions at the frozen IoU threshold. Also report the source-pixel width and height represented by one
fine-model input pixel so that effective resolution remains explicit.

### 4.3 Partition and authority rules

Reuse the 0068 source-group partitions. Derived full-frame targets and cluster crops inherit their
source frame, reviewed revision, review coverage, partition, and source group. A source frame cannot
cross partitions through different clusters or perturbations. Derived crops are not independent
source groups and do not increase real-data coverage.

Processor output cannot become a training target. Validation can select the one checkpoint and one
coarse confidence threshold under the frozen rules. Do not use the former 0068 sealed test to tune
the cascade. A later promotion decision needs untouched real recordings that represent the
distant-card failure mode.

## 5. Delivery milestones

### M0 — Freeze the cascade and crop contracts

- Add versioned contracts for card clusters, square cluster crops, coordinate transforms,
  reconciliation decisions, and two-stage bundle identity.
- Implement the deterministic clustering, padding, crop, forward mapping, inverse mapping, and
  duplicate-reconciliation functions without loading a model.
- Add fixtures for one proposal, a merged pile proposal, nearby transitive proposals, separated
  clusters, overlapping square crops, frame-edge padding, disconnected polygons, and no proposals.
- Freeze the model classes, input sizes, cluster recipe, neutral padding, duplicate rule, package
  version, and local device choices.

Acceptance:

- repeated transforms produce byte-equivalent records;
- source-to-crop-to-source point and mask round trips stay within the declared rounding tolerance;
- a transitive proposal chain forms one cluster;
- disconnected visible-region components survive a round trip; and
- malformed geometry, stale identities, and non-invertible transforms fail before inference.


#### M0 implementation evidence — 2026-09-20

- Added the dependency-free `table_evidence_analyzer.visible_card_cascade` contract module.
- Frozen the two stages as `RFDETRSmall` at 512 × 512 for `card_cluster` and
  `RFDETRSegMedium` at 432 × 432 for `visible_card`, with RF-DETR 1.9.4, MPS as the default
  local device, neutral RGB `(128, 128, 128)` padding, and a 0.90 box-and-visible-mask IoU
  duplicate rule.
- Implemented median-shorter-side transitive clustering, square crop geometry with explicit
  out-of-frame padding, source/crop/model transforms, polygon-component-preserving mappings, and
  deterministic confidence and identity tie-breaking.
- Added eight focused tests for transitive clusters, separated and frame-edge crops, empty input,
  coordinate round trips, malformed geometry, duplicate reconciliation, stable tie-breaking, and
  stage identity validation. The focused tests and Ruff checks pass.

### M1 — Run the current model as a two-pass cascade

- Add a development cascade provider that loads the selected 0068 bundle once and uses it for both
  the full-frame coarse pass and every fine crop pass.
- Keep the coarse mask only as retained diagnostics after its tight box enters clustering.
- Batch fine crop inference where the current RF-DETR API and local resource bound permit it.
- Map and reconcile the fine proposals into the existing visible-card pipeline result contract.
- Retain one source-linked end-to-end fixture and one real local smoke result.

Acceptance:

- one request produces deterministic cluster crops and source-mapped candidates;
- the model is not reloaded for each crop;
- final candidates use full-source normalization and exact frame identity;
- stage failure and partial diagnostics remain inspectable; and
- existing `gemini`, `local`, and `local-rfdetr-segmentation` providers remain unchanged.

#### M1 implementation evidence — 2026-09-20

- Added `LocalVisibleCardCascadeProvider` as the selectable `local-rfdetr-cascade` development
  provider. It validates and loads one 0068 `RFDETRSegMedium` bundle, uses its detector boxes for
  the coarse pass, and reuses that loaded detector for each 432 × 432 fine crop. The coarse pass
  records that masks were ignored for clustering; the fine pass preserves all polygon components
  in the mapped cascade diagnostics.
- Added deterministic neutral-padded crop materialization, source-frame mapping, crop image
  digests, duplicate reconciliation, full-source normalized pipeline candidates, exact frame
  identity, stage latency, and inspectable coarse/fine failure records. The current RF-DETR API
  does not expose a safe batch path, so fine crops run sequentially under the local resource bound.
- Added three source-linked local fixture smoke tests for one-load reuse, mapped candidates,
  disconnected mask components, request identity, coarse failure, partial fine failure, and
  provider-boundary validation. The focused cascade/provider checks pass; the full analyzer suite
  passes with 198 tests and 3 skips, and Ruff passes.

### M2 — Materialize full-frame card-cluster training data

- Derive card-cluster boxes from eligible 0068 reviewed references with the M0 rule.
- Produce a deterministic COCO detection view for train and validation.
- Record every source card, reviewed geometry, derived cluster membership, exclusion, file digest,
  and partition.
- Add coverage and scale reports before training starts.

Acceptance:

- every eligible reviewed card belongs to exactly one cluster target;
- no target depends on a processor prediction;
- ignore-region, incomplete-coverage, ineligible, and cross-partition inputs are rejected or receive
  an explicit exclusion receipt;
- cold and warm materialization have equal manifests and generated-file digests; and
- COCO boxes round-trip to the reviewed source geometry and cluster record.

### M3 — Train the full-frame card-cluster model

- Add the detection-only RF-DETR Small trainer, reloadable bundle, evaluator, and resource guard.
- Freeze the real training manifest and recipe before model execution.
- Run one bounded real training campaign and select one checkpoint by the frozen validation rule.
- Calibrate the single coarse threshold against the frozen crop-containment recall floor.
- Retain source-linked missed-card and extra-cluster examples.

Acceptance:

- the emitted checkpoint differs from the pretrained checkpoint and reloads as `RFDETRSmall`;
- the bundle pins its checkpoint, class map, 512 × 512 input, recipe, data, and package identities;
- validation reports every metric in section 4.1 and satisfies the frozen containment floor;
- training and inference run on the explicit local device without silent fallback; and
- no other coarse architecture or target representation is trained.

### M4 — Materialize cluster-crop segmentation data

- Build deterministic train and validation crops from reviewed clusters with the M0 transform.
- Apply the one frozen perturbation policy while keeping all assigned visible regions complete.
- Transform every visible-region polygon component and tight box into crop coordinates.
- Produce the COCO instance-segmentation view and a contact sheet that overlays each crop target.

Acceptance:

- every crop links to its source frame, reviewed revision, cluster, transform, perturbation, and
  source group;
- no crop splits an assigned visible region or drops a polygon component;
- crop targets map back to the reviewed source geometry within tolerance;
- source-group partitions remain disjoint; and
- cold and warm materialization have equal manifests and generated-file digests.

### M5 — Train the cluster visible-card model

- Generalize the 0068 segmentation trainer to accept the M4 crop view and the selected 0068
  checkpoint as its initializer.
- Freeze the real training manifest and recipe before model execution.
- Run one bounded real fine-tuning campaign and select one checkpoint by the frozen validation rule.
- Evaluate crop-coordinate and mapped source-coordinate results with the section 4.2 metrics.
- Retain source-linked overlap-separation failures.

Acceptance:

- the selected bundle reloads as `RFDETRSegMedium` and pins its 0068 initializer;
- training consumes cluster crops and never resizes a complete source frame as a fine-stage sample;
- mapped validation results preserve card and polygon-component identity;
- the report includes overlapping-target separation and exact-card-count results; and
- no alternate segmentation architecture, size, or resolution is trained.

### M6 — Assemble and integrate the cascade provider

- Replace the M1 coarse stage with the M3 RF-DETR Small bundle.
- Replace the M1 fine stage with the M5 crop-trained RF-DETR SegMedium bundle.
- Emit one cascade bundle manifest that verifies both child bundles and the M0 recipe.
- Register `local-rfdetr-cascade` as an explicit selectable backend provider.
- Run source-linked end-to-end validation and one recording-workspace smoke flow.
- Publish a decision report with coarse misses, crop diagnostics, fine separation failures, mapped
  visible-card metrics, latency, and remaining limits.

Acceptance:

- the provider loads both bundles once and rejects any child or recipe digest mismatch;
- repeated requests over unchanged inputs produce equal clusters and final geometry;
- every final candidate maps to one retained fine result and source transform;
- end-to-end reporting separates coarse-stage misses from fine-stage instance-separation errors;
- the existing providers and maintained references remain unchanged; and
- the new provider is selectable for annotation without becoming the runtime default.

## 6. Verification

Each milestone runs focused unit and integration tests, Ruff formatting and checks, applicable type
checks, CLI help, deterministic cold/warm materialization checks, and local Markdown-link checks.
Model milestones also reload their emitted bundles and run at least one real source frame through
the exact runtime path. M6 verifies the combined provider through the backend API and recording
workspace without changing a maintained reference.
