# Local detector and virtual-card review findings

Date: 2026-11-03

## Purpose and limits

This report records an interactive local review of RF-DETR visible-card proposals. It provides
development cases for later detector and proposed-card-scene work. The observations are not reviewed
reference labels, an accuracy measurement, a model promotion decision, or a new training campaign.
The user reviewed the cases in the recording workspace. The measurements below describe the named
saved outputs. They do not establish general thresholds.

The named new runs and revisions are untracked local pipeline artifacts at the time of this report.
The model bundles and detector response cache are also local artifacts. Retain or restore those
artifacts to reproduce the comparisons. The IDs and image hashes below identify the exact inputs;
they do not make the artifacts available in a fresh clone. Do not replace the selected maintained
references or the frozen [0096 review queue](0096-M4_Human_Review_Queue.md) with these cases.

## Models and local review option

The local RF-DETR SegMedium bundle used for the new runs is the 0092 M4 final refit. Its bundle
digest is `05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`. Its checkpoint
SHA-256 is `80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`. It supports
`visible_card` and `card_pile`. The [0092 M4 report](0092-M4_Final_Refit.md) records training
lineage and the limits of in-sample monitoring. The earlier candidate's sealed evaluation does not
measure the final-refit weights.

The older run `visible_cards-run-c16a61a6-1ea` used the historical
`local-rfdetr-cascade-0070` provider. It used a coarse-to-fine workflow and did not predict piles.
Its request does not record exact bundle or checkpoint hashes. The historical default bundle path
is evidence of intended configuration, not proof of the loaded weights. The old and new runs on
`game-2026-08-20-01-001` used the same event revision and presentation timestamps, but their saved
JPEG hashes differ.

During this review, a local `local-rfdetr-crop-review` option was added in the worktree. It uses the
0092 bundle on full frames and qualifying enlarged crops, prefers an unambiguous matched crop mask,
and retains the full-frame pile proposals. It is an experimental review option, not a quality
claim. Its implementation and other local work were uncommitted when this report was written; verify
the current code and run identity before reuse. Its wider crop routing and preference for crop masks
need review on more than the cases below.

## Review cases

### Crop scale and mask quality

- Recording: `game-2026-08-20-01-001`.
- Event input: `reference-events-e22b24bde3ef35a56ab930873b2200cc`.
- Compare `visible_cards-run-c16a61a6-1ea`, `visible_cards-run-624e9b21-05b`,
  `visible_cards-run-4d801c27-2ec`, and `visible_cards-run-crop-review-20261103`.
- New-run frame hashes: `event-000012` =
  `7613e1a353f3fd27cefde9c32279f60e2a2f71f73420f320771986fa98e4fb53`; `event-000034` =
  `454b77a903dbfb7adc032f6eda0c9f2db6ad875b8e6e1d9d7bdfcb5a9bfc289b`.

The user found the older cascade's boundaries cleaner on these four-card frames. A diagnostic used
the exact saved new-run images and the same 0092 weights to force crop inference. Its crop masks
looked cleaner at overlaps. The previous fine-frame rule skipped these clusters because the
smallest detected cards exceeded its 54-pixel size limit. The crop-review run changed card geometry
on 41 of 49 frames compared with `visible_cards-run-4d801c27-2ec`; both runs produced 145 card
proposals and 28 pile proposals, and all pile geometries matched. Counts are not quality metrics.
Inspect the experimental output before deciding on a general routing or crop-selection rule.

### Merged visible cards across event frames

- Recording: `game-2026-08-20-01-001`; event input as above.
- Review `event-000019` and `event-000020` in
  `visible_cards-run-crop-review-20261103` and the old cascade run.
- New-run image hashes: `event-000019` =
  `b6c2c14950c31eadff7a11d6ee759603370da0e57d52b19d6a70dcfde28a2f2e`; `event-000020` =
  `c9605d400bc8a9f51459e129fc20a84fb770f7e2874f2fe46ca9c5dd6ed48bc3`.

The 0092 full-frame output separates two upper cards in `event-000019` but merges them in
`event-000020`. The crop output also merges them. The older cascade separates them in the latter
frame. Four targeted 0092 crop probes did not reliably recover two complete masks. This is an
instance-separation case. It is not evidence that a different crop size can never help.

The user prefers any previous-frame fallback in the later virtual-card stage. A possible experiment
is to flag a region that is difficult to explain as one calibrated card, then seed competing poses
from the previous frame and compare them against current-frame evidence. Account for movement,
occlusion, and calibration validity. DINO identity scores may contribute evidence, but they do not
prove a split or geometry is correct. This temporal method is a proposal; it has not been
implemented or validated.

### Duplicates and a missed covered card

- Recording: `game-2026-08-20-01-005`; event input
  `events-events-run-f2757d1b-bfe-attempt-1`, anchored at `end_us`.
- Detector run: `visible_cards-run-5f4f8c72-78b`; review `event-000002` and `event-000003`.
- Image hashes: `event-000002` =
  `505635a9e7b5f9f022a039d70104ac326e07e64e971332ddbe5905957be75921`; `event-000003` =
  `746ecc51cf70b77fd039388dc3c99fc08aab7725758e311f51faebe4b0383db5`.

In `event-000003`, two full-frame proposals for the top card have mask IoU about 0.98. A crop
proposal also covers that card. The matching logic finds the crop match ambiguous between the two
full-frame proposals, then adds it as a new card. The user identified overlapping unwanted shapes
and a covered card that remains visible but has no separate prediction. The prior frame helps inspect
the covered card. Duplicate reconciliation and recovery of a missed card are separate problems.

### Containment and the best competing proposal

- Recording: `game-2026-09-18-01-003`; event input
  `reference-events-245d3f4a9f9cc55f2eb6cb33e6e9b31d`, anchored at `end_us`.
- Detector run: `visible_cards-run-3cec03e2-d57`; frame `event-000003`.
- Image SHA-256: `0140d11204663c7f6d712cf26b00120bf472cd101709195327ee2eb19c39b502`.

The user identified proposals 4, 5, and 6 as the same card and judged proposal 6 best. Proposals 4
and 5 are full-frame predictions; proposal 6 is a crop prediction. Mask IoU is about 0.92 for 4/5,
0.72 for 4/6, and 0.69 for 5/6. About 97–99% of each smaller mask is inside the larger mask. The
crop match was ambiguous and was added as another proposal. Do not fix ambiguity by blindly
discarding the crop proposal: here the user prefers it. Compare containment, geometry, and other
evidence, and retain candidate provenance.

### Crop-edge fragment and conflicting pile classes

- Recording, event input, and detector run: as above; frame `event-000036`.
- Image SHA-256: `629b56cdc00d4e97b213bdbb2786a2d75f31a8f41338e1dd1013a6cbe7269a24`.

Proposal 6 is a narrow crop addition with a straight lower boundary. Its crop ends at source y = 460
pixels; the proposal ends near y = 459. About 95% of its mask is inside proposal 1, while their mask
IoU is about 0.11. Crop-edge contact and containment are useful diagnostics for a possible truncated
duplicate; they do not prove that every crop-edge prediction is invalid.

Card proposal 4 has the same saved mask as pile proposal 3. Card proposal 5 has the same saved mask
as pile proposal 2. The model emitted competing card and pile classifications for those regions. The
user considers the pile detections correct here and reports that discarding cards in piles has
worked in the observed cases. Treat that as a hypothesis to test, not a universal rule: a separable
face-up card may overlap a coarse pile footprint. Use class evidence, mask identity or containment,
and reviewable alternatives. Do not infer pile contents or gameplay from a pile footprint.

The current crop-review provider saves per-prediction scores in diagnostic cache responses, but its
published card candidates have no `model_scores`. Pile confidence is saved. Restore and test
per-candidate score lineage before a later stage uses scores to compare card and pile evidence.

## Possible next work

Keep the detector revision as evidence. Investigate a preprocessing step at the start of proposed
card-scene processing, before duplicate proposals can distort calibration. Group likely duplicates
using mask IoU and containment and preserve their source IDs. After a valid table-plane calibration,
compare fixed-size, straight-edged full-card poses with the original visible regions and account for
occlusion. Visible regions can be irregular or disconnected; do not force them into rectangles or
destructively smooth away narrow visible parts. A lightly simplified boundary can be a separate fit
input if it preserves the original mask and useful evidence.

Use these examples as development cases. Add distinct overlap, partial-card, pile, crop-boundary,
and moving-card cases before selecting thresholds or making automatic suppression decisions.
Measure effects on independently reviewed examples, including false merges and false removals.
Confidence is one signal, not a substitute for geometry or human review.
