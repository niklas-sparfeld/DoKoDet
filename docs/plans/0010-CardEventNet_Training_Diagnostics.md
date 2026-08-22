## Implementation plan: CardEventNet training diagnostics

## Plan status

- Summary: Improve CardEventNet training diagnostics
- Status: Done

### Goal

Make every training run answer these questions without manual calculation:

1. Is the model actually capable of high event recall at *some* threshold?
2. What precision / false-event cost is required to achieve that recall?
3. Is the model overfitting train versus validation?
4. Are failures spread across the validation set or concentrated in particular videos?
5. Which concrete events are being missed or falsely detected?
6. Which epoch is genuinely the best checkpoint for the downstream candidate-detector use case?

Do **not** change the CardEventNet architecture as part of this work.

---

## Phase 1 — Remove the hard-coded 0.5 checkpoint criterion

### 1. Refactor event evaluation into shared code

Training and `evaluate.py` should use the same implementation for:

- probability stream → events
- event matching
- aggregate metrics
- per-video metrics
- threshold search

Do not maintain a separate simplified evaluator inside `train.py`.

A sensible structure is something like:

```text
cardevent/
  evaluation.py
    ScoredVideo
    evaluate_streams()
    select_threshold()
    ...
```

Both training and the existing `evaluate` CLI consume it.

The current evaluator already has most of this code. 

### 2. During validation, infer probabilities only once

For each epoch:

```text
model
  ↓
validation videos
  ↓
probability streams
  ↓
├── validation BCE loss
├── metrics @ 0.5
├── threshold sweep
├── selected operating point
└── per-video metrics
```

Do not rerun the neural network for every threshold.

Threshold evaluation operates entirely on the saved probability streams and should therefore be cheap.

### 3. Expand the threshold sweep

The current evaluation grid is:

```python
0.10, 0.15, ... 0.95
``` 


That is too coarse for diagnosis, particularly because your target recall is already configured as **0.98**. 

Use initially:

```text
0.01 .. 0.99, step 0.01
```

99 event-decoding passes over four validation videos are negligible compared with inference.

Do not search using test data.

---

## Phase 2 — Improve epoch metrics

Keep the existing fixed-0.5 metrics because they're useful for seeing calibration changes, but rename them explicitly.

Each epoch's `metrics.jsonl` should contain approximately:

```json
{
  "train_loss": 0.123,
  "val_loss": 0.987,

  "validation_fixed_threshold": 0.5,
  "validation_fixed_recall": 0.31,
  "validation_fixed_precision": 0.77,
  "validation_fixed_false_events_per_hour": 149,

  "validation_selected_threshold": 0.17,
  "validation_selected_recall": 0.94,
  "validation_selected_precision": 0.58,
  "validation_selected_false_events_per_hour": 320,

  "validation_max_f1": 0.71,
  "validation_max_f1_threshold": 0.28,

  "validation_recall_min_video": 0.70,
  "validation_recall_median_video": 0.95,
  "validation_recall_max_video": 1.0
}
```

Exact names aren't important; clear semantics are.

### 4. Add F1 as a diagnostic, not the primary target

For every threshold:

```text
F1 = 2 × precision × recall / (precision + recall)
```

Report:

- maximum event F1
- threshold producing maximum F1

But **do not select the production threshold primarily by F1**.

CardEventNet is a candidate detector, so the existing idea is better:

> achieve target recall first; among thresholds satisfying it, minimize false events/hour.

The current `_threshold_rank()` already follows essentially that policy. 

### 5. Rank `best.pt` using calibrated validation performance

This is the key behavioral change.

Currently:

```text
epoch
 → evaluate at threshold 0.5
 → _checkpoint_rank()
 → best.pt
```

Change it to:

```text
epoch
 → sweep validation thresholds
 → select best operating point for target_recall
 → rank epoch using that result
 → best.pt
```

Use the existing configured:

```yaml
metrics:
  target_recall: 0.98
``` 


Ranking should remain:

1. checkpoints capable of reaching target recall beat those that cannot;
2. if several reach it, lowest false events/hour wins;
3. then highest precision;
4. if none reaches it, highest recall wins;
5. then lowest false events/hour.

That makes `best.pt` mean:

> the checkpoint best suited to the actual CardEventNet role.

rather than:

> whichever epoch happened to be best calibrated around 0.5.

---

## Phase 3 — Persist detailed per-epoch diagnostics

Don't put everything into `metrics.jsonl`.

Add something like:

```text
run-.../
  metrics.jsonl
  epochs/
    epoch-001.json
    epoch-002.json
    ...
```

Each epoch detail file contains:

```text
selected threshold
all threshold candidates
overall metrics
per-video metrics
```

Per-video data should at least contain:

```text
video
event count
detected count
missed count
false count
recall
precision
false/hour
latency p50/p95
```

The existing standalone evaluator already calculates most of this. 

### 6. Add useful aggregate per-video statistics

Report in the normal epoch log:

```text
val recall:       94.4%
val worst video:  IMG_xxxx — 70.0%
val median video: 97.5%
```

This prevents aggregate metrics from hiding:

```text
video A 100%
video B 100%
video C 98%
video D 35%
```

which is a very different problem from:

```text
A 82%
B 85%
C 80%
D 83%
```

---

## Phase 4 — Add train-vs-validation diagnostics

Do **not** run full training-set event inference every epoch by default. With 19 training videos that wastes GPU time and doesn't help checkpoint selection.

Instead add a diagnostic command:

```bash
uv run cardevent diagnose \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/default.yaml
```

It should:

1. determine the threshold from **validation only**;
2. evaluate the complete train partition using that threshold;
3. evaluate validation using that threshold;
4. report both side-by-side.

Example:

```text
                         train       val
Recall                   99.2%      43.1%
Precision                 96.1%      61.2%
False events/hour           8.2     183.4
```

Then explicitly compute:

```text
recall generalization gap
precision generalization gap
```

This is the fastest way to distinguish:

### Case A — overfitting

```text
train recall: 99%
val recall:   40%
```

→ data/generalization problem.

### Case B — underfitting / representation / decoder problem

```text
train recall: 55%
val recall:   40%
```

→ simply collecting similar data is unlikely to solve it.

### Case C — calibration problem

```text
at 0.5:       recall 30%
best threshold: recall 95%, acceptable FP
```

→ network is substantially better than current training logs suggested.

---

## Phase 5 — Generate a failure-review manifest

Extend event matching so diagnostic output can identify the actual unmatched events, not merely their counts.

For every video record:

```json
{
  "missed_events": [
    {
      "ground_truth_time_s": 18.42,
      "max_probability_near_event": 0.11
    }
  ],
  "false_events": [
    {
      "predicted_time_s": 31.25,
      "probability": 0.91
    }
  ]
}
```

Also distinguish useful categories mechanically where possible:

```text
missed completely:
  model probability remains low

near miss:
  strong peak exists but falls outside event tolerance

merged event:
  two ground-truth events correspond to one prediction cluster

false positive:
  prediction has no matching annotation
```

That **merged-event** category matters because your current decoder merges above-threshold samples within `0.6 s`, while your underlying task can contain closely spaced plays. 

A decoder failure should not be mistaken for a neural-network failure.

---

## Phase 6 — Improve plots

Keep the existing probability plots. They're already useful. 

Add two run-level plots.

### Precision/recall operating curve

```text
x = recall
y = precision
one point per threshold
mark selected target-recall threshold
mark max-F1 threshold
```

### Recall / false-events curve

```text
x = recall
y = false events/hour
```

This is more useful for CardEventNet than a classical ROC curve.

Also add one training-history plot:

```text
epoch → train loss
epoch → validation loss

epoch → calibrated validation recall
epoch → calibrated validation precision
epoch → calibrated FP/hour
epoch → selected threshold
```

The selected threshold itself is useful: if it moves from `0.6 → 0.3 → 0.08`, you can immediately see calibration changing even when ranking quality remains similar.

---

## Phase 7 — Preserve the existing standalone evaluation workflow

After training:

```bash
cardevent evaluate --partition val
cardevent evaluate --partition test
```

should continue working.

The validation threshold must remain persisted in `threshold.json`, and test evaluation must **never optimize its own threshold**. The repo already follows this rule. 

Ideally training can write `threshold.json` for `best.pt` automatically at completion so that:

```text
train
 → best.pt
 → validation-calibrated threshold.json
```

are one coherent artifact.

---

# Tests / acceptance criteria

Add tests demonstrating that:

- threshold selection can choose values below `0.10`;
- threshold selection never reads test annotations;
- `best.pt` selection uses calibrated metrics rather than metrics at `0.5`;
- probability inference happens once per validation video per epoch, not once per threshold;
- per-video metrics aggregate correctly;
- F1 calculation handles zero predictions;
- missed and false event timestamps are reported correctly;
- two nearby real events merged into one prediction are identifiable as such;
- train diagnostics use the validation-selected threshold;
- test evaluation always uses the persisted validation threshold;
- existing resume/checkpoint behavior remains deterministic.

Do not add early stopping yet. With the dataset still small, retaining every epoch's diagnostic trajectory is more useful than shaving a few training epochs.

---

# Human workflow after implementation

This should become the routine after every meaningful dataset/model change.

## 1. Train normally

Run the full 19/4 split.

Ignore the test set.

During training, only watch for gross problems:

```text
train loss
val loss
calibrated recall
calibrated FP/hour
worst-video recall
```

Do **not** decide whether the model is good from precision/recall at `0.5`.

---

## 2. Look at the best checkpoint's validation operating curve

First question:

> **Can this model reach 98% validation recall at any reasonable threshold?**

Your decision tree is:

### Cannot even reach ~80% recall

Something substantial is wrong.

Proceed immediately to train-vs-val diagnostics.

### Reaches 90–95%, but only with huge false-positive rate

The model sees much of the correct signal, but discrimination is weak.

Review false positives and hard negatives.

### Reaches 98% with tolerable false-positive rate

The candidate detector is doing its intended job.

Do not keep tweaking the training model just because precision isn't beautiful.

---

## 3. Run train-vs-val diagnostics

### Train ≫ validation

For example:

```text
train 99%
val   65%
```

Interpretation:

**generalization problem.**

Next actions:

- inspect whether one visual setup dominates failures;
- collect more *different* sessions;
- improve augmentation if failures correspond to something augmentable;
- avoid adding another ten nearly identical videos.

### Train and validation both poor

For example:

```text
train 70%
val   60%
```

Interpretation:

**model / labels / event representation / decoder problem.**

Do **not** immediately record more videos.

Investigate architecture and event semantics.

### Both strong

Proceed toward test evaluation.

---

# 4. Examine recall per validation video

With four validation videos, actually read all four rows.

Look specifically for:

```text
100 / 98 / 95 / 35
```

versus:

```text
83 / 80 / 85 / 82
```

For the first case, ask what is unique about the bad video:

- camera angle
- table geometry
- player
- hand occlusion
- lighting
- card position
- camera movement
- play speed
- ROI quality

That tells you what new training material is valuable.

---

# 5. Review misses before false positives

For CardEventNet, false negatives are more important.

Start with perhaps the **20 lowest-confidence missed plays**.

For each missed event, classify manually:

```text
A — annotation wrong
B — ordinary clean play
C — occluded play
D — very fast / motion blurred
E — card overlaps existing trick
F — rapid consecutive plays
G — unusual lighting / shadows
H — ROI/camera problem
I — other
```

Don't spend time making this taxonomy sophisticated initially. A note or small table is enough.

The important result is whether one category dominates.

---

# 6. Inspect merged events separately

If the network produces a good probability response for two close plays but `merge_window_s=0.6` converts them into one event, **do not add training data to fix that**.

That's a decoder problem.

Example:

```text
real:        10.10    10.48
prob peaks:  10.12    10.50
decoded:     10.12
```

The network has succeeded.

Experiment with event decoding / merge behavior independently.

This diagnostic could become particularly important for your Doppelkopf footage.

---

# 7. Then review false positives

Take the highest-confidence false detections.

Categorize:

```text
collecting a trick
hand crossing table
card handling without playing
dealing
shuffling
score sheet / objects
lighting / shadows
camera movement
annotation actually missing
other
```

For genuine false positives on **training videos**, use the existing hard-negative mining pipeline. 

If one semantic category dominates, deliberately record negative footage containing it.

---

# 8. Decide the next experiment from the evidence

Use this rule:

| Observation | Next action |
|---|---|
| Train excellent, val poor | More diverse data |
| One val video catastrophic | Collect data resembling that condition |
| Train and val poor | Architecture / target semantics |
| Peaks correct but events merged | Event decoder |
| High recall, many specific false positives | Hard negatives |
| Good PR curve, poor @0.5 | Calibration only |
| Labels look wrong during review | Fix annotations first |
| All validation strong | Test |

Only change **one major variable per experiment**.

---

# 9. Keep the four test videos sealed

This matters now that the dataset is becoming large enough to take evaluation seriously.

Do not repeatedly look at test performance while:

- tuning thresholds;
- changing augmentation;
- selecting epochs;
- changing merge windows;
- choosing architecture.

All of those decisions belong to train + validation.

Once you have a model you would genuinely consider advancing:

```bash
uv run cardevent evaluate \
  --checkpoint .../best.pt \
  --partition test
```

Then accept the result as an estimate of generalization.

If you subsequently make decisions based on those four test videos, they have effectively become validation data. At that point, record a new future test set.

---

## What I expect this will tell us

With your current logs, my first experiment after implementing this would specifically ask:

> At thresholds from `0.01–0.99`, what is the **maximum recall epoch 1/9/13 can achieve**, and how many false events/hour does 90%, 95%, and 98% recall cost?

That single result will distinguish “bad calibration” from “model doesn't generalize” much more cleanly than the current `~30% recall @ 0.5` figures.

I would implement these diagnostics **before making the RGB/frame-difference architectural change**. Otherwise you won't have a sufficiently good measurement system to tell whether the new architecture actually improved anything.