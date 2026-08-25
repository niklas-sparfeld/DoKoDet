# CardEventNet

CardEventNet detects meaningful visible card-state changes. A detected event triggers a new
table-state evaluation.

Run the commands below from `card_event_net/`.

Data contributors can start with the short
[data and model lifecycle](../docs/CardEventNet_DataAndModelLifecycle.md).

## Current state

New annotations and caches use the full frame. They do not require a selected ROI. New training
runs and Python inference require the preprocessing identifier `full_frame_letterbox_v1`. Legacy
ROI annotations still load, but their geometry does not control preprocessing.

The checked-in Core ML model and the iOS probe still use the legacy ROI contract. Do not combine
them with a new full-frame checkpoint. [Plan 0013](../docs/plans/0013-CardEventNet_FullFrameInput.md)
tracks the remaining retraining and iOS migration.

This repo has the model, annotation, inference, evaluation, hard-negative, and Core ML export
pipeline:

- project metadata
- config loading
- device selection
- annotation schema and validation
- video metadata reading
- OpenCV annotation tool
- 10 fps cached frame extraction
- causal 8-frame dataset sampling
- positive, negative, ignored, and confirmed-hard-negative label states
- deterministic video-level and session-aware train/val/test splits
- temporally consistent training transforms
- MobileNetV3-Small spatial backbone
- causal Conv1D temporal head
- two-stage freeze and fine-tune training
- timestamped checkpoints and run metadata
- full-video causal inference at 8 Hz
- threshold-independent peak extraction and temporal suppression
- exact validation threshold selection from candidate-peak scores
- event recall, precision, false/hour, and latency metrics
- probability and threshold plots
- classical cached-frame motion baseline
- hard-negative mining from false triggers on training videos
- optional repeated hard-negative sampling during training
- fixed-shape Core ML export with optional PyTorch parity verification
- saved validation streams for decoder-only evaluation
- test and lint setup

The annotation tool stores one JSON file per source video in `data/annotations/`. New files use
annotation V2 and contain saved events without geometry. Existing V1 files with an ROI load, and
the next edit saves them as V2. Event types are `card_played`, `trick_cleared`, `card_moved`,
`card_removed`, `card_returned`, `multiple_cards_dropped`, and `anomalous_state_change`.
Use the repository's [labeling guidelines](../docs/CardEventNet_LabelingGuidelines.md) for class,
timestamp, close-event, and hard-negative decisions.

Annotation controls:

```text
1-7     select event type
SPACE   add an event, or change the event type at the same timestamp
W / S   jump to the previous or next saved event
, / .   move the selected event one frame backward or forward
E       set the selected event to the selected type
T       cycle the selected event type
U       mark the selected event or selected proposal uncertain
N / B   jump to next or previous model proposal
C       toggle before/after comparison
P       pause or play
A / D   seek backward or forward about 250 ms
J / L   seek backward or forward about 2 s
BACKSPACE or X  remove the selected event
Q       save and exit
```

The selected saved event follows the current video timestamp. The overlay shows its timestamp and
type.

## Setup

If `uv` is not available yet, run `mise install` first so the toolchain from `mise.toml` is ready.

```bash
uv sync
uv run cardevent --help
uv run pytest
uv run ruff check .
```

Core ML export is optional and requires macOS:

```bash
mise install
uv sync --extra coreml
```

The project pins Python 3.13, PyTorch 2.7.0, torchvision 0.22.0, and coremltools 9.0.
These versions provide the native macOS Core ML modules and a tested PyTorch converter.

## Annotation

Run the annotator from `card_event_net/`:

```bash
uv run cardevent annotate data/raw/IMG_0090.mov
```

The tool shows the event definition at startup. You can label a new video immediately. You can
quit and reopen the same video later. Existing events stay in the JSON file.

Review model candidates with an inference JSON file:

```bash
uv run cardevent annotate data/raw/IMG_0090.mov --proposals predictions.json
```

The annotator does not save model proposals automatically. Press `Space` to confirm one at the
current timestamp. Press `U` to save it as uncertain instead.

For queue-based visual review, use `cardevent review`. See the
[CardEventNet review workflow](../docs/CardEventNet_ReviewWorkflow.md) for the full validation
and training process.

## Cache and split

Prepare the annotated videos from `card_event_net/`:

```bash
uv run cardevent prepare --videos data/raw/*.mov
uv run cardevent make-split data/raw/*.mov
```

The cache stores 224 x 224 JPEG frames in `data/cache/<video>/`. It also stores the source
timestamp for every cached frame in `metadata.json`. The cache is ignored by Git.

`prepare` skips a complete cache that matches the source video, cache frame rate, and frame size.
Use `--force` to rebuild matching caches:

```bash
uv run cardevent prepare --videos data/raw/*.mov --force
```

The split file is `data/splits/default.yaml`. It uses video names without their file extension.
It is not replaced when it already exists. Use `--force` only when you want to create a new split.

For independent-session validation, create a dataset manifest that follows the
[V1 video metadata guide](../docs/CardEventNet_VideoMetadata.md), then make a session-aware split:

```bash
uv run cardevent split --manifest data/dataset-manifest.yaml --group-by session_id \
  --out data/splits/session-aware.yaml
```

The command keeps all videos from one session in the same partition.

## Training

Train from the prepared cache and the persisted video split:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml
```

Runs are stored in `data/outputs/run-YYYYMMDD-HHMMSS/`. Each run contains `config.yaml`,
`environment.json`, `metrics.jsonl`, `epochs/`, `best.pt`, `last.pt`, and `summary.json`.
Training uses the same label semantics for training and validation. Ignored transition samples do
not affect BCE loss. It reports label-state counts, effective positive fraction, validation loss,
event recall, precision, F1, false events per hour, timestamp error, and target-recall status.

`labels.positive_window_s` is the positive interval after an event.
`labels.negative_past_exclusion_s` ends the post-event exclusion interval.
`labels.negative_future_exclusion_s` is the pre-event exclusion duration.
The positive window must not extend past the post-event exclusion interval.

The transition-label experiment uses `configs/transition-label-v1.yaml`. It writes `sampling.json`
before the first epoch. This file separates all eligible labels from selected training samples.

Training selects a validation threshold for each epoch. It uses the target-recall operating point
when possible. If target recall is impossible, it selects the maximum-F1 fallback and records the
failure. The best checkpoint uses this event-level ranking. Early stopping uses the configured
event metric. Each run writes `threshold.json`, `training-history.png`, operating curves, and
`validation-streams/epoch-*.json.gz` files.

Use runtime overrides for a CUDA run:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml \
  --device cuda \
  --precision bf16 \
  --num-workers 4 \
  --batch-size 32
```

The default precision is `fp32`, the default worker count is zero, and pin memory is enabled
only for CUDA. The worker count and batch size depend on the machine. If a run stops, resume
from its directory or `last.pt`:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml \
  --resume data/outputs/run-...
```

See [CLOUD_TRAINING.md](CLOUD_TRAINING.md) for the complete persistent-storage and RunPod
workflow.

Use `--max-samples 32` for a fast local training sanity check. This limits the samples used from
each training and validation video. A normal run uses all samples.

## Inference and evaluation

Run causal inference for one prepared video. The JSON file contains float32 logits and
probabilities for every 0.125 second decision timestamp:

```bash
uv run cardevent infer \
  --checkpoint data/outputs/run-.../best.pt \
  --video data/raw/IMG_0097.mov \
  --out predictions.json
```

Evaluate the validation partition. This selects a threshold from validation event behavior and
saves it beside the checkpoint in `threshold.json`:

```bash
uv run cardevent evaluate \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/default.yaml \
  --partition val
```

Evaluate the test partition after validation. The command uses the persisted validation
threshold. If it is missing, the command selects it from validation first. It never uses test
events to select the threshold:

```bash
uv run cardevent evaluate \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/default.yaml \
  --partition test
```

Each evaluation writes JSON metrics, one probability plot per video, a validation stream, and
threshold tradeoff plots. It also writes precision/recall and recall/false-event operating curves.
Threshold candidates use unique decoded peak scores, not a fixed probability grid. The report
includes event recall, precision, F1, false events per hour, latency p50/p95, target-recall
status, maximum attainable recall, and the selection reason.

Evaluation writes a diagnostics file beside each evaluation report. For example,
`evaluation-val.json` writes `evaluation-val-transition-diagnostics.json`. It measures
probabilities from 0.50 through 1.00 seconds after each event, excluding the 0.10 seconds before
the next event. Supply reviewed validation hard negatives for nearest-stream score diagnostics:

```bash
uv run cardevent evaluate \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/default.yaml \
  --partition val \
  --reviewed-hard-negative-manifest data/annotations-val-reviewed/validation-hard-negatives.json
```

Compare train and validation behavior at a validation-selected threshold:

```bash
uv run cardevent diagnose \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/default.yaml
```

The diagnostics JSON contains train and validation metrics, generalization gaps, per-video
metrics, and missed/false event timestamps. It does not use the test partition.

Run the simple motion baseline with the same event evaluator:

```bash
uv run cardevent baseline \
  --split data/splits/default.yaml \
  --partition val
```

## Hard-negative mining

Mine false triggers from the training videos after a first evaluation run:

```bash
uv run cardevent mine-hard-negatives \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/default.yaml
```

The command writes `data/outputs/hard-negatives.json`. It uses the validation threshold
saved next to the checkpoint. Pass `--threshold` if that file does not exist. The manifest
contains only false-trigger timestamps from training videos. It does not change annotations.

Use the manifest in a later training run:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml \
  --hard-negative-manifest data/outputs/hard-negatives.json
```

Each mined timestamp is repeated three times by default. This gives hard negatives a higher
sampling rate than ordinary negatives. Change `training.hard_negative_repeat` in the config
to use a different repeat count of two or more.

## Core ML export

Export a trained checkpoint on macOS:

```bash
uv run cardevent export-coreml \
  --checkpoint data/outputs/run-.../best.pt \
  --out CardEventNet.mlpackage
```

Export accepts only a checkpoint with `full_frame_letterbox_v1` preprocessing. The package records
this identifier in its user-defined metadata. It has one fixed input named `clips` with shape
`[1, 8, 3, 224, 224]`. Input values must be ImageNet-normalized `float32` values. The output is
one raw logit named `logit`.
The v1 package also uses float32 computation to keep the converted logit close to PyTorch.
The command runs a deterministic PyTorch/Core ML parity check by default. Use
`--skip-parity` only when the Core ML prediction runtime is not available.

The complete workflow is:

```bash
uv sync
uv run cardevent annotate data/raw/game01.mov
uv run cardevent prepare --videos data/raw/*.mov
uv run cardevent make-split data/raw/*.mov
uv run cardevent train --config configs/base.yaml --split data/splits/default.yaml
uv run cardevent evaluate --checkpoint <best.pt> --split data/splits/default.yaml --partition test
uv run cardevent infer --checkpoint <best.pt> --video data/raw/game05.mov --out predictions.json
uv run cardevent export-coreml --checkpoint <best.pt> --out CardEventNet.mlpackage
```
