# Visible-card training-data improvement

## Plan status

- **Summary:** Review and correct exact-event card boxes, then measure whether the corrected data
  improves the local visible-card detector.
- **Status:** Blocked
- **Depends on:** Plan 0037 must produce the first pseudo-label dataset, detector recipe, bundle,
  and end-to-end result
- **Builds on:** Plans 0020, 0022, and 0027 review, dataset, and lineage contracts
- **Outcome:** Produce the first reviewed visible-card localization dataset and measured evidence
  about which data addition improves detection.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Purpose

Improve training data before changing the model. Keep the plan 0037 RF-DETR Large variant,
pretrained checkpoint, preprocessing, training recipe, confidence threshold, and seed fixed for the
first comparison. Run full training on the declared RunPod CUDA environment. Training wall time is
not a selection metric.

Use the plan 0037 Gemini configuration to propose boxes for reviewed `card_played` events at exact
offset `0 ms`. Reuse each existing cached result. A person must review the visible-card boxes before
they become reference or training labels. Review can accept, move, resize, add, or remove a box.
Preserve the original Gemini result beside the corrected version.

This plan measures visible-card localization only. It does not label visual card identity, select a
played card, or change game reconstruction.

## 2. Dataset design

Build three distinct sets with source-lineage-safe partitions:

1. **Teacher set:** Gemini pseudo-labels for the reviewed seed frames. Preserve the frozen plan 0037
   subset and use the same provider request for added frames.
2. **Reviewed seed set:** corrected boxes on usable `0 ms` frames from reviewed events.
3. **Reviewed challenge set:** false proposals, empty frames, occlusion, human-hand overlap, glare,
   blur, and small-card cases. Keep this set out of training until its evaluation role is frozen.

Exclude the sealed system holdout. Split by session or stricter source-lineage group. Do not split
nearby frames from one recording across train and validation.

Target the first reviewed seed set at 100 usable frames from at least five sessions, with no session
supplying more than 40%. If the repository cannot meet this target, publish the measured coverage
gap and continue with a smaller explicitly limited experiment.

## 3. Review contract

For each exact-event frame, the reviewer must decide frame usability and then review every visible
physical card:

- `GOOD`: the frame can supply visible-card localization labels;
- `BAD`: the frame is not usable for this task;
- accepted, corrected, added, and removed boxes;
- face-up, face-down, or unknown side when it can be reviewed;
- failure tags for small card, occlusion, human hand, blur, glare, crop boundary, and duplicate.

A box traces the axis-aligned extent of the visible card region. Do not infer the hidden part of an
occluded card. A `BAD` frame is not an empty negative. An empty negative requires an explicit review
that no physical card is visible.

Each decision records reviewer, source-frame digest, Gemini result digest, box version, review time,
and source-lineage group. Save each decision immediately and resume without repetition.

## 4. Evaluation

Use corrected boxes in the frozen validation and challenge sets. Report:

- box average precision at IoU 0.50 and from 0.50 through 0.95;
- instance recall at declared score and IoU thresholds;
- false and duplicate proposals per frame;
- empty-frame false-positive rate;
- usable-crop recall;
- results by session, table setup, side, visible-card count, and failure tag;
- median and p95 local inference latency.

Latency is descriptive in this data experiment. The comparison must not prefer worse detection
only because it trains faster. If inference becomes an operational problem, evaluate speed and
quality as separate axes in a later bounded model experiment.

Compare paired predictions from the same frozen validation frames. Do not use validation metrics to
edit labels or thresholds after the comparison begins.

## 5. Delivery milestones

### M0 — Add box correction review

- Extend the existing visible-card review path with box accept, move, resize, add, and remove
  actions.
- Keep the Gemini proposal immutable and store corrections as a new review artifact.
- Add fixtures for overlapping cards, an empty frame, an occluded card, and a bad frame.

Acceptance:

- the queue resumes after every saved decision;
- corrected artifacts keep full source and teacher lineage;
- `BAD` and reviewed-empty decisions remain distinct;
- malformed or incomplete reviews cannot enter a dataset.

### M1 — Freeze the reviewed seed and challenge sets

- Run a 20-frame pilot and freeze the review wording before the main pass.
- Review the available exact-event corpus and publish coverage by source group and failure tag.
- Freeze train, validation, and challenge manifests before model comparison.

Acceptance:

- all labels in the reviewed manifests have complete review provenance;
- partitions have no source-lineage overlap;
- the system holdout is absent;
- the report states whether the 100-frame and five-session targets were met.

### M2 — Measure corrected labels

Train two candidates with the exact plan 0037 recipe and seed. Use the same training-frame
membership for both candidates:

1. Gemini pseudo-labels for those frames;
2. corrected reviewed boxes for those frames.

Evaluate both on the same reviewed validation and challenge sets. Do not change architecture,
augmentation, resolution, epochs, thresholds, or seed in this comparison.

Acceptance:

- both candidates consume frozen dataset and split digests;
- one machine-readable comparison contains paired sample predictions and all declared metrics;
- the result states whether correction improved, harmed, or did not clearly change localization;
- no candidate is promoted.

### M3 — Add one targeted data round

- Select one failure category from the M2 report, not from test or system-holdout results.
- Add a bounded review batch for that category. Prefer unused source groups.
- Retrain with the reviewed seed set plus this one addition and compare on the unchanged validation
  and challenge sets.

Acceptance:

- the selection reason names one measured failure and a fixed item budget;
- new samples have complete review and lineage records;
- the report isolates the effect of the added data;
- further work is proposed as a new bounded recipe rather than an open-ended loop.

## 6. Unblocking and completion

Move this epic to Ready after plan 0037 records its completed bundle, recipe, dataset digest, and
end-to-end result. Complete this epic after M3 publishes the reviewed datasets and comparison. A
quality improvement is desirable but is not required. Clear evidence that the data change did not
help is also a valid outcome.
