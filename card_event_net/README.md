# CardEventNet

CardEventNet detects the moment when a card has just landed in the trick area.

Run the commands below from `card_event_net/`.

## Current state

This repo now has the phase-4 model and training pipeline:

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
`metrics.jsonl`, `best.pt`, `last.pt`, and `summary.json`. The best checkpoint uses validation
event recall and false events per hour for ranking.

Use `--max-samples 32` for a fast local training sanity check. This limits the samples used from
each training and validation video. A normal run uses all samples.
