# CardEventNet

CardEventNet detects the moment when a card has just landed in the trick area.

Run the commands below from `card_event_net/`.

## Current state

This repo now has the phase-7 model, inference, evaluation, hard-negative, and Core ML export
pipeline:

- project metadata
- config loading
- device selection
- annotation schema and validation
- video metadata reading
- OpenCV annotation tool
- 10 fps cached ROI frame extraction
- causal 8-frame dataset sampling
- positive and clean-negative label windows
- deterministic video-level train/val/test splits
- temporally consistent training transforms
- MobileNetV3-Small spatial backbone
- causal Conv1D temporal head
- two-stage freeze and fine-tune training
- timestamped checkpoints and run metadata
- full-video causal inference at 8 Hz
- probability-to-event clustering
- validation threshold selection
- event recall, precision, false/hour, and latency metrics
- probability and threshold plots
- classical cached-frame motion baseline
- hard-negative mining from false triggers on training videos
- optional repeated hard-negative sampling during training
- fixed-shape Core ML export with optional PyTorch parity verification
- test and lint setup

The annotator stores one JSON file per source video in `data/annotations/`.
It remembers the ROI and the saved events.

Startup controls:

```text
SPACE   mark a card_played event
P       pause or play
A / D   seek backward or forward about 250 ms
J / L   seek backward or forward about 2 s
BACKSPACE or X  remove the latest event
R       redefine the ROI
Q       save and exit
```

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

The tool shows the event definition at startup. On first use, select the ROI in the OpenCV
window, then save. You can quit and reopen the same video later. Existing events stay in the
JSON file.

## Cache and split

Prepare the annotated videos from `card_event_net/`:

```bash
uv run cardevent prepare --videos data/raw/*.mov
uv run cardevent make-split data/raw/*.mov
```

The cache stores 224 x 224 JPEG frames in `data/cache/<video>/`. It also stores the source
timestamp for every cached frame in `metadata.json`. The cache is ignored by Git.

The split file is `data/splits/default.yaml`. It uses video names without their file extension.
It is not replaced when it already exists. Use `--force` only when you want to create a new split.

## Training

Train from the prepared cache and the persisted video split:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml
```

Runs are stored in `data/outputs/run-YYYYMMDD-HHMMSS/`. Each run contains `config.yaml`,
`environment.json`, `metrics.jsonl`, `epochs/`, `best.pt`, `last.pt`, and `summary.json`.
Training selects a validation threshold for each epoch. It reports fixed-0.5 metrics,
calibrated metrics, maximum F1, and worst/median/best video recall. The best checkpoint uses
the calibrated validation target-recall ranking. It also writes `threshold.json`,
`training-history.png`, and operating curves in `diagnostics/`.

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

Run causal inference for one prepared video. The JSON file contains one probability for every
0.125 second decision timestamp:

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

Each evaluation writes JSON metrics, one probability plot per video, and a threshold tradeoff
plots. It also writes precision/recall and recall/false-event operating curves. The report
includes event recall, precision, F1, false events per hour, and latency p50/p95.

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

The package has one fixed input named `clips` with shape `[1, 8, 3, 224, 224]`. Input values
must be ImageNet-normalized `float32` values. The output is one raw logit named `logit`.
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
