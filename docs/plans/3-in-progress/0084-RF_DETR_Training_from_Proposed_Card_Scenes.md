# RF-DETR training from proposed card scenes

## Plan status

- **Summary:** Derive visible-card instance masks from proposed card scenes and their card poses.
  Use the eligible source frames as training input for one bounded RF-DETR campaign.
- **Status:** In Progress
- **Depends on:** 0072, 0073, 0067, and 0068 complete; 0083 complete
- **Outcome:** A frozen audit, deterministic RF-DETR segmentation materialization, and one paired
  local training and evaluation report. The report decides whether pose-derived training labels
  improve held-out real visible-card segmentation. It does not promote a provider or update a
  maintained reference.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — added a read-only audit command and froze eligible 0083 scenes, 0068 source
  groups, mask rules, and one paired RF-DETR comparison recipe.
- **M1:** Complete — materialized and verified exact source frames and deterministic COCO RLE
  card-instance masks in a disposable RF-DETR training view.
- **M2:** Not started — inspect representative mask overlays and verify the frozen materialization.
- **M3:** Not started — run one real-only control and one pose-derived-data candidate, then publish
  the locked held-out decision.

### M0 implementation evidence — 2026-09-25

- Added `doko data rfdetr-pose-derived`. The command accepts the frozen 0068 manifest and an exact
  inventory of 0083 proposal run IDs. It checks processor, calibration, source, and model lineage;
  checks each frame's pose set and stacking order; records every excluded frame; and writes one
  immutable manifest. It does not change source data or start training.
- The audit used the 0068 manifest digest
  `c057bacd2d62dc2f4473b2a31e821e8a268ba2b6834f34790a5dd6624c54022e` and the 30 final 0083
  proposal runs. Outcomes were 23 complete, five partial, and two failed. It verified source video
  bytes and lengths for all 13 training recordings with proposal runs.
- The frozen manifest is
  `data/operations/rfdetr-pose-derived-0084-m0-manifest.json`, digest
  `1505f0955f6c6427d68627be2a983f1c602fafaac502d7772595b72f816ad733`. It accepts 141 frames,
  483 card poses, and 12 0068 training source groups. It accepts no validation or sealed-test
  frames. It records 1,255 frame exclusions and two failed-run receipts. Exclusion reasons include
  418 exact-frame duplicates, 53 low-confidence pose sets, and 47 scenes with unresolved overlap
  order.
- The minimum source set is 100 frames, five source groups, and 400 candidate poses. After mask
  construction, M1 must retain at least 100 frames, five groups, and 300 visible-card masks. Each
  visible mask must contain at least 256 pixels and have a tight box at least 16 by 16 pixels.
- M1 uses rounded physical card outlines, front-to-back card occlusion, frame clipping, and COCO
  RLE masks. The RLE round-trip check must preserve holes and disconnected components. M2 must
  review hand occlusion before training.
- The paired campaign reuses the exact 0068 recipe digest
  `1bac899f2d048b95bdfc7ab7114802c79b5ea0ed0096dbb8962affba96bd8b23`. It trains two candidates
  from the same checkpoint with the same real sample count. The candidate adds one derived frame
  per real frame per epoch, sampled uniformly with replacement using seed 8404. The RF-DETR
  training seed remains 6701. The run uses the pinned package defaults, the MPS device, and a
  7,200-second budget per candidate and a 14,400-second total budget. Report the added derived-data
  compute separately. The candidate must strictly improve validation mask AP and recall over the
  control before the sealed test can run once.
- Repeated audits over unchanged inputs returned the same manifest digest. All 13 selected source
  videos passed SHA-256 and byte-length checks. The focused audit tests and Ruff checks passed.

### M1 implementation evidence — 2026-09-25

- Added `doko data rfdetr-pose-derived-materialize`. It rechecks the M0 digest, source video
  bytes, frame identities, proposal and detector revisions, calibration, pose set, and stacking
  order. It writes only under the selected disposable output path.
- The view is `data/operations/rfdetr-pose-derived-0084-m1`. It contains 141 exact JPEG frames,
  483 `visible_card` masks, and 12 training source groups. No validation or sealed-test group is
  present. The frozen mask gate passed with 141 frames and 483 masks.
- Each COCO annotation uses uncompressed column-major RLE. The verifier decodes every mask and
  checks its pixel digest, area, tight box, category, split, and proposal, calibration, frame, and
  source-group lineage. The `materialization.json` digest is
  `229ecbbb1b05684dfe7a7d71b3e89e77d57d65f6552a41fcd1f057fd2ba6a114`.
- The exclusion receipt carries all 1,257 M0 exclusions and failed-run receipts. M1 excluded no
  scenes, hidden cards, or below-minimum masks. It records 167 partially occluded cards with full,
  occluded, and visible pixel counts. M2 still requires human review for hand occlusion.
- Cold and warm runs produced the same M1 digest. The materialization tests cover rounded corners,
  clipping, front-to-back overlap across three cards, disconnected and enclosed areas, empty masks,
  changed source bytes, RLE round trips, lineage, and cold/warm reproducibility. All eight focused
  tests and Ruff checks passed.

## 1. Purpose

Epic 0083 runs visible-card detection and proposed card scene generation for a supplied recording
list. This epic tests whether those scene poses provide useful extra training input for the local
RF-DETR visible-card segmentation model.

For each eligible source frame, project the rounded outline of each card pose into the original
frame. Use the scene's card stacking order to remove pixels hidden by cards in front. The result is
one visible-card mask per card, with a box derived from that mask. Train and evaluate one frozen
candidate against the existing human-reviewed RF-DETR corpus.

Proposed scenes and their generated labels remain processor-derived data. They do not become
maintained references or reviewed targets. Use human-reviewed references for validation and the
sealed test. Preserve the generated-label origin in the campaign manifest and every materialized
annotation.

## 2. Campaign rules

### 2.1 Eligible input

M0 must audit completed 0083 visible-card and proposed-card-scene runs. Every accepted frame must
retain the exact source frame, visible-card input revision, proposal output revision, calibration
revision and digest, and model and recipe lineage. Re-read the source frame and verify its recorded
digest before materialization.

Use only source groups assigned to the 0068 training partition. Do not use a validation or sealed-
test recording, session, source asset, video, digest, table setup, calibration input, or proposal
output to create training images or labels. Freeze the group assignment from the 0068 manifest.
Stop if the 0083 output contains no eligible training groups.

Exclude a frame when its calibration or pose result fails the frozen quality gate, when the card
stacking order has a contradiction or an unresolved edge that changes an overlapping mask, or
when a non-card occluder such as a hand covers a projected card and no reviewed occluder mask can
remove those pixels. Apply minimum visible-pixel and card-size rules fixed in M0. Record every
excluded scene and reason.

If an exact source frame already appears in the 0068 reviewed training materialization, keep its
reviewed target in the real-only corpus and exclude the duplicate frame from the pose-derived
addition. The audit may compare both masks as a diagnostic. It must not give the same image two
different training targets.

### 2.2 Mask construction

Build one full-card binary mask per pose by projecting the shared rounded physical card outline
through that scene's exact table-plane calibration. Do not use the rectangular pose corners as the
segmentation boundary. Clip the mask to the source-frame bounds.

The stacking order is front-to-back. A card earlier in the order removes its pixels from every
card behind it. Apply that rule to full rounded masks to produce each final visible mask. Preserve
disconnected visible components. Derive each tight box from the final mask. Exclude fully hidden or
below-threshold cards with a receipt; do not turn an empty generated frame into reviewed background
evidence.

Use the existing RF-DETR `visible_card` instance-segmentation class. M0 must choose a COCO mask
encoding that round-trips the generated binary masks, including disconnected regions and enclosed
occlusions. A polygon conversion that fills an occlusion hole is not acceptable.

### 2.3 Paired training decision

Freeze one deterministic dataset manifest, source-group policy, train-only pose-derived sample
selection, real-to-derived sampling ratio, RF-DETR model and package, pretrained checkpoint, input
resolution, seed, augmentation, optimizer, stopping rule, device, resource budget, and acceptance
thresholds before training. Keep the real training samples and their exposure count the same in
both candidates. Report extra derived-data compute separately.

Train exactly two candidates from the same pretrained checkpoint:

1. **Control:** the frozen 0068 human-reviewed training partition.
2. **Pose-derived addition:** the same real samples plus the frozen 0083 pose-derived training
   frames.

Select by the unchanged 0068 validation partition. Run the 0068 sealed test once, only if the
candidate passes the validation gate. Report the established mask AP, mask AP50, box AP, recall,
false detection, duplicate detection, and empty prediction metrics, with per-recording and
overlap-related slices where support exists. Do not tune from validation or sealed-test failures.

Any result is a valid campaign outcome. Keep the resulting bundle as an experiment. This epic does
not promote a provider, change a default, claim reviewed quality for generated labels, or start a
parameter or data-ratio sweep.

## 3. Delivery milestones

### M0 — Freeze the input and campaign contract

- Audit the completed 0083 runs and the 0068 frozen manifest without changing either.
- Resolve exact source frames, proposal scenes, calibration, visible-card input revisions, and
  model lineage. Verify their digests and source permissions.
- Assign every eligible proposal to the 0068 training source groups. Find and exclude exact-frame
  duplicates of the reviewed real training view.
- Freeze scene, pose, order, occluder, minimum-size, mask-encoding, sampling, RF-DETR, resource,
  and comparison rules from sections 2.1–2.3.
- Write one immutable manifest with accepted scenes, excluded scenes, group assignments, counts,
  and exact lineage before materialization or training.

Acceptance:

- repeated audits over unchanged inputs produce the same manifest digest;
- no validation or sealed-test source contributes pixels, geometry, calibration, or labels to the
  derived training view;
- every accepted scene has a valid source digest, calibration lineage, complete pose set, and
  unambiguous order for each pair of overlapping cards;
- all ineligible and duplicate frames have item-level exclusion receipts; and
- the audit stops before training if the eligible source set cannot meet the frozen minimum.

### M1 — Materialize the pose-derived segmentation view

- Extract and verify each exact original source frame selected by M0.
- Project rounded card masks, apply front-to-back occlusion and frame clipping, preserve visible
  components, and derive tight boxes.
- Write a disposable COCO training view with one `visible_card` instance per eligible visible
  card, exact generated-label lineage, and the frozen M0 digest.
- Retain hidden-card, occluded-card, invalid-mask, and excluded-frame receipts. Do not write to
  maintained references or processor output stores.

Acceptance:

- cold and warm materialization produce identical image, annotation, exclusion, and lineage
  digests;
- decoded trainer masks reproduce the source-derived masks exactly under the frozen encoding;
- each box is the tight box of its decoded visible mask, and each annotation traces to its frame,
  card pose, proposal revision, calibration digest, and source group;
- no real validation or sealed-test group appears in the view; and
- fixtures cover rounded corners, front-over-back overlap, three-card order, disconnected
  components, enclosed occlusions, frame clipping, empty masks, and changed source bytes.

### M2 — Inspect and verify the training view

- Produce contact sheets that overlay masks and card IDs on the exact source frames.
- Include isolated cards, multiple overlap depths, rounded corners, frame edges, hand-occluded
  frames excluded by M0, and fully hidden cards.
- Review the scene eligibility and mask overlays before training. Record the sample selection,
  review result, and any required exclusions.
- Run one deterministic RF-DETR materialization smoke check that loads masks through the pinned
  trainer path and confirms finite segmentation targets.

Acceptance:

- reviewed overlays show card pixels assigned to the topmost card and no hidden pixels assigned
  to a card behind it;
- rounded corners, visible disconnected pieces, and clipping match the generated binary masks;
- the inspected view digest equals the M1 manifest digest; and
- any discovered defect stops training until a corrected manifest and materialization are frozen.

### M3 — Run the paired RF-DETR campaign

- Train the real-only control and the pose-derived addition from the same pinned pretrained
  checkpoint and frozen recipe.
- Retain checkpoint bundles, logs, environment facts, per-frame predictions, and exact input and
  output digests.
- Evaluate both candidates on the unchanged 0068 validation partition. If the M0 gate passes, run
  the sealed test once.
- Publish a decision report with aggregate and per-recording metrics, pose-derived data counts,
  exclusions, mask review evidence, resource use, and any supported overlap slices.

Acceptance:

- the paired runs use identical real input, model, recipe, seed, and checkpoint-selection rule;
- retained predictions reproduce every reported metric;
- the report states whether the validation gate passed and, if run, reports one sealed-test result;
- generated labels remain separate from reviewed references and test targets; and
- no provider registration or default change occurs.
