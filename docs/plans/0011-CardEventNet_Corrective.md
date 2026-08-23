# CardEventNet Corrective Implementation Plan

## Plan status

- Summary: Improve annotations and training, implement improved tooling
- Status: In Progress

## Goal

Make CardEventNet’s labels, event decoder, threshold calibration, and diagnostics agree with the product definition:

> A positive event is any meaningful visible card-state change that should trigger a new table-state evaluation.

Implementation should happen before collecting a large additional dataset or changing the model architecture.

## Phase 1: Preserve and characterize the current behavior

### Code changes

Add a regression fixture representing the problematic score pattern found in this run:

- Four card plays roughly one second apart
- Sustained elevated scores between plays
- A trick-clearing event
- Nearby hand motion
- Quiet background

Add tests capturing the current failure:

- Raising the threshold can currently create more decoded events.
- Nearby plays can be merged into one event.
- An unmet recall target is silently saved as though calibration succeeded.
- BF16 probabilities are heavily quantized around 0.99.

Save validation probability streams as diagnostics so decoders and thresholds can be re-evaluated without rerunning the neural network.

Suggested artifact:

```text
run-.../
  validation-streams/
    epoch-001.json.gz
    ...
    epoch-020.json.gz
```

Each stream should contain:

- Video identifier
- Decision timestamps
- Float32 logits
- Float32 probabilities
- Ground-truth events and types
- Annotation-version hash

### Acceptance gate

The existing checkpoint can be decoded repeatedly with different decoder implementations without performing inference again.

---

## Phase 2: Expand the event annotation schema

### Code changes

Extend the annotation event types beyond `card_played`:

```text
card_played
trick_cleared
card_moved
card_removed
card_returned
multiple_cards_dropped
anomalous_state_change
```

Keep the current JSON format backward compatible. Existing `card_played` annotations must continue loading unchanged.

Add optional fields:

```json
{
  "time_s": 17.2,
  "type": "trick_cleared",
  "confidence": "confirmed",
  "notes": null
}
```

Support an `ignore` or `uncertain` annotation for cases where the human cannot determine an exact event.

Update annotation validation to reject:

- Unknown event types
- Negative or out-of-range timestamps
- Duplicate events within a small configurable tolerance
- Missing confidence for model-proposed annotations

### Annotation-interface changes

Add:

- Keyboard shortcuts for event type selection
- Editing an event’s type
- Moving an event timestamp
- Deleting an event
- Marking a candidate uncertain
- Jumping to the previous or next model proposal
- Before/after frame comparison

Model proposals must never be written as confirmed ground truth automatically.

### Human work

Review the existing 27 videos and add at least:

- Every trick-clearing event
- Withdrawn cards
- Repositioned cards
- Accidental state changes
- Ambiguous cases

Start with the four validation videos, especially `IMG_0639`, before reviewing the complete training set.

### Acceptance gate

A full 40-card game has all meaningful state changes annotated, normally including approximately ten trick-clearing events.

---

## Phase 3: Introduce three-way temporal labels

The current system has a training/validation contradiction:

- Training excludes transition frames.
- Validation treats those same frames as negative.

### Code changes

Replace binary time classification during dataset construction with:

```text
positive
negative
ignore
```

Derive the states as follows:

- `positive`: inside the configured response window after a confirmed event
- `ignore`: close to an event, but outside the defined positive window
- `negative`: sufficiently far from every confirmed event
- `confirmed_hard_negative`: manually reviewed negative, allowed inside an otherwise ignored region

Update `DatasetSample` to carry the label state or a loss mask.

Training loss should use:

- Positive samples
- Clean negative samples
- Confirmed hard negatives
- No ignored samples

Validation loss should also exclude ignored samples. Event-level inference and evaluation should still process the full timeline.

Report these counts for every run:

- Positive samples
- Clean negatives
- Confirmed hard negatives
- Ignored transition samples
- Effective positive fraction

Warn when the requested positive-to-negative ratio cannot be reached. This run requested 1:3 but produced approximately 39.5% positives instead of 25%.

### Tests

Add tests proving:

- Ignored samples do not affect BCE loss.
- Transition samples have the same status in training and validation.
- Confirmed hard negatives override the automatic ignore region.
- Hard negatives cannot overlap confirmed positive windows.
- Unattainable sampling ratios generate an explicit diagnostic.

### Acceptance gate

Training and validation loss use identical label semantics.

---

## Phase 4: Replace connected-component event decoding

The current decoder clusters all above-threshold samples connected by gaps of at most 0.6 seconds. Low thresholds can therefore merge several plays, while high thresholds split them again.

### Code changes

Separate decoding into three explicit stages:

1. Candidate peak extraction
2. Temporal suppression
3. Score-threshold acceptance

Candidate peaks must be computed independently of the operating threshold.

A recommended implementation:

- Detect temporal local maxima.
- Confirm a peak after one subsequent sample or a bounded score-drop period.
- Preserve the peak timestamp as the event timestamp.
- Apply non-maximum suppression using a configurable minimum event gap.
- Apply the acceptance threshold only after the candidate set is fixed.

Rename or deprecate `merge_window_s` in favor of clearer settings:

```yaml
inference:
  peak_confirmation_s: 0.125
  min_event_gap_s: 0.6
```

Support the old configuration temporarily by mapping `merge_window_s` to `min_event_gap_s` with a deprecation warning.

For online inference, report two notions of latency:

- Event timestamp error
- Actual emission latency caused by peak confirmation

### Tests

Add synthetic tests for:

- Four plays one second apart
- A broad single peak
- A flat-topped peak
- Noisy fluctuations around one event
- Two peaks inside the suppression window
- Two peaks outside the suppression window
- Irregular sample timestamps
- Empty streams
- Boundary peaks at the beginning and end

Add the central property test:

> For a fixed probability stream, increasing the threshold must never increase the number of accepted events.

### Acceptance gate

The threshold/event-count curve is monotonic on both synthetic data and the saved streams from this run.

---

## Phase 5: Improve event matching

The current greedy matching processes ground-truth events sequentially. Dense events can produce avoidable or order-sensitive matches.

### Code changes

Replace greedy matching with an order-preserving optimal matcher using dynamic programming.

The matching objective should be:

1. Maximize the number of matched events.
2. Minimize total absolute timestamp error.
3. Use deterministic tie-breaking.

Continue enforcing one-to-one matching and the configured tolerance.

Add optional subtype-aware evaluation:

- Primary metric: any state-change event
- Secondary metrics: per event subtype

### Tests

Cover:

- Two predictions competing for two nearby ground-truth events
- One prediction between two events
- Equal-distance ties
- Dense four-card sequences
- Predictions just inside and outside tolerance
- Deterministic results regardless of input order

### Acceptance gate

Matching achieves the maximum possible true-positive count for every test fixture.

---

## Phase 6: Repair threshold calibration

### Code changes

Convert logits to float32 before sigmoid during:

- Training validation
- Offline inference
- Test evaluation
- Diagnostic stream generation

Prefer saving raw float32 logits alongside probabilities.

Replace the fixed 0.01–0.99 threshold grid with thresholds derived from the unique candidate-peak scores. This produces the exact event-level precision/recall curve without missing useful operating points.

Threshold selection should behave as follows:

- If one or more thresholds reach target recall, choose the one with the lowest false-events/hour.
- If none reach the target, choose the maximum-F1 fallback.
- Record the maximum attainable recall separately.

Persist:

```json
{
  "target_recall": 0.98,
  "target_recall_met": false,
  "maximum_attainable_recall": 0.62,
  "selection_reason": "fallback_max_f1"
}
```

Print a prominent warning when the target is not met.

Update checkpoint ranking:

- Prefer epochs that meet target recall.
- Among those, minimize false events/hour.
- If no epoch meets the target, rank by maximum event F1 rather than raw recall alone.

### Tests

Add tests for:

- Target reached by multiple thresholds
- Target reached by exactly one threshold
- Target unreachable
- Scores above 0.99
- Equal candidate scores
- Backward loading of old `threshold.json` files
- Float32 sigmoid when the model ran under BF16 autocast

### Acceptance gate

No output file can be mistaken for having reached the recall target when it did not.

---

## Phase 7: Correct validation loss and model selection

### Code changes

Report several independent validation measurements:

```text
validation_labeled_loss
validation_event_recall
validation_event_precision
validation_event_f1
validation_false_events_per_hour
validation_emission_latency
validation_timestamp_error
```

Do not use loss over ignored transition frames.

Add configurable early stopping using the calibrated event metric:

```yaml
training:
  early_stopping:
    metric: validation_event_f1
    patience: 3
    min_delta: 0.005
```

Retain the best checkpoint and stop unnecessary fine-tuning. In the analyzed run, the best checkpoint occurred on the first fine-tuning epoch while later training loss continued falling.

### Acceptance gate

Checkpoint selection is based on a valid event-level operating point, and training terminates when validation behavior stops improving.

---

## Phase 8: Build the human review queue

**Current state:** Implemented. `cardevent review-queue` creates deterministic, unreviewed
candidates. `cardevent apply-review` requires explicit human outcomes, validates the result, and
writes a complete annotation version without changing the source directory. The first full-frame
validation queue has 78 items. A new confirmed positive requires an explicit semantic event type.
A separate training queue has 278 items across 19 videos. Human review is still required before
the acceptance gate passes.

### Code changes

Create a command that compares model candidates with confirmed annotations:

```text
cardevent review-queue \
  --checkpoint best.pt \
  --split val \
  --out review-manifest.json
```

The queue should include:

- Unmatched model candidates
- Missed annotations
- Low-confidence matches
- Closely spaced merged-event candidates
- Model-version disagreements
- Random supposedly empty intervals

Each item should include:

- Video and timestamp
- Suggested category
- Model score
- Nearest annotation and distance
- Short before/after preview
- Review status
- Human-selected outcome

Review outcomes:

```text
confirmed_positive
confirmed_hard_negative
annotation_timestamp_corrected
ignore
unreviewed
```

Add a second command to apply reviewed decisions to a new annotation version. It must:

- Never overwrite the source annotations silently
- Produce a change summary
- Validate the result
- Preserve reviewer provenance

### Human/LLM loop

1. Tool proposes candidates.
2. Human reviews them.
3. LLM inspects disagreements and recurring patterns.
4. Tool applies confirmed decisions to a new annotation version.
5. Dataset validation runs.
6. Model retrains.
7. New failures become the next queue.

### Acceptance gate

Reported false positives and hard negatives have been human-confirmed rather than inferred from incomplete annotations.

---

## Phase 9: Add dataset and split metadata

### Code changes

Introduce a dataset manifest containing:

```text
video_id
session_id
recording_date
device
camera
resolution
frame_rate
table_setup
card_deck
annotation_version
source_permission
```

Extend split validation to prevent the same `session_id` from appearing in more than one partition.

Add a group-aware split generator:

```text
cardevent split --group-by session_id
```

Report domain composition per split.

### Human work

Assign session and setup metadata to the existing videos.

The current material contains only two iPhone 14 collection sessions. A meaningful train/validation/test split therefore requires at least one additional independent session, preferably more.

### Acceptance gate

Validation and test sessions are absent from training, and the split validator enforces this automatically.

---

## Phase 10: Expand run diagnostics

### Code changes

Every run summary should include:

- Annotation-version hash
- Dataset-manifest hash
- Event counts by subtype
- Sample counts by label state
- Session and device counts
- Whether hard negatives were actually loaded
- Number of hard negatives
- Target-recall status
- Maximum attainable recall
- Threshold-selection reason
- Decoder configuration and version
- Per-session metrics
- Per-event-type metrics
- Test metrics only when explicitly requested

Rename misleading output labels such as “calibrated validation quality” when calibration failed.

Add warnings for:

- No hard-negative manifest
- Target recall unmet
- Validation containing only one session
- Train/validation session overlap
- Severe train/validation loss divergence
- Threshold at the edge of the available score range
- Missing state-change event types

### Acceptance gate

A run folder alone contains enough information to determine whether its metrics are valid.

---

## Phase 11: Rerun sequence

### Rerun A — Decoder-only

Use the existing checkpoint and saved/raw probability streams.

Purpose:

- Verify monotonic threshold behavior
- Measure how much recall was lost to cluster merging
- Avoid conflating decoder changes with retraining

### Rerun B — Corrected validation annotations

Add trick clearings and other state changes to the four validation videos, then re-evaluate the existing checkpoint.

Purpose:

- Quantify how many reported false positives were actually positives
- Establish the corrected event count

### Rerun C — Corrected training labels

Review the training videos, introduce explicit hard negatives, and retrain with three-way temporal labels.

Purpose:

- Measure the benefit of label alignment
- Remove the current validation-loss contradiction

### Rerun D — Independent-session validation

Create a group-safe split and train again.

Purpose:

- Measure genuine session generalization

### Rerun E — Final held-out test

Run once after decoder, labels, thresholds, and model-selection rules are frozen.

Purpose:

- Produce the first defensible production-readiness estimate

---

## Recommended implementation order

1. Save/reload raw validation streams.
2. Replace the event decoder.
3. Add optimal event matching.
4. Add float32 scoring and exact threshold calibration.
5. Add explicit target-recall status.
6. Introduce positive/negative/ignore temporal labels.
7. Expand annotation event types.
8. Build the manual review queue.
9. Relabel validation videos.
10. Re-evaluate the current checkpoint.
11. Relabel training videos and add confirmed hard negatives.
12. Add session-aware manifests and splits.
13. Retrain with early stopping.
14. Evaluate the final held-out test set.

The decoder and metric corrections should come first because otherwise later data and model experiments would still be judged by unreliable measurements.
