# CardEventNet v1 — Implementation Plan

## Purpose

Run the commands in this document from `card_event_net/`.

Implement the first working version of **CardEventNet** for DokoDetector.

CardEventNet is **not** a playing-card recognizer. Its only job is to detect the temporal event:

> **A new card has just been played into the central trick/table area.**

The intended production pipeline is:

```text
camera
  -> low-resolution causal CardEventNet
  -> candidate event timestamp
  -> retrieve high-resolution frames around that timestamp
  -> downstream/cloud card recognition
  -> game-state validation
```

This repository implements the CardEventNet portion offline first, using prerecorded videos supplied as input. It must also make the trained model exportable to Core ML later.

The implementation should optimize for:

1. Very high event recall.
2. Reasonably low false-trigger rate.
3. Causal inference: no future frames may be needed to detect an event.
4. Small enough architecture for later iPhone inference.
5. Simple, explicit code that is easy to debug.

Do **not** add card rank/suit recognition, object detection, segmentation, player recognition, cloud APIs, or an iOS app in this implementation.

---

# 1. Required technology choices

Use exactly this basic stack unless a dependency proves impossible:

- Python 3.12+
- `uv` for environment/dependency management
- PyTorch
- torchvision
- OpenCV for the annotation UI and basic image/video operations
- NumPy
- PyYAML
- pytest
- Ruff
- matplotlib for evaluation plots only
- optional `coremltools` dependency for Core ML export on macOS

Do **not** use:

- PyTorch Lightning
- Hugging Face Trainer
- YOLO
- transformers/video transformers
- MLflow
- Weights & Biases
- Hydra
- distributed training

The project should remain understandable from ordinary Python files and PyTorch primitives.

---

# 2. Hardware/device policy

Training must work with one command on:

1. Apple Silicon through PyTorch MPS.
2. NVIDIA CUDA if later run on RunPod.
3. CPU as fallback.

Implement a single helper:

```python
def resolve_device(requested: str = "auto") -> torch.device:
    ...
```

Behavior:

```text
auto:
  CUDA available -> cuda
  else MPS available -> mps
  else -> cpu
```

Do not introduce CUDA-specific assumptions into model or dataset code.

Do not use mixed precision in v1. Correctness and portability are more important than training speed.

---

# 3. Repository structure

Create this structure:

```text
card_event_net/
├── README.md
├── IMPLEMENTATION_PLAN.md
├── pyproject.toml
├── .gitignore
├── configs/
│   └── base.yaml
├── data/
│   ├── raw/                 # ignored by git
│   ├── annotations/
│   ├── cache/               # ignored by git
│   ├── splits/
│   └── outputs/             # ignored by git
├── src/
│   └── cardevent/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── device.py
│       ├── video.py
│       ├── annotation.py
│       ├── cache.py
│       ├── sampling.py
│       ├── dataset.py
│       ├── transforms.py
│       ├── model.py
│       ├── train.py
│       ├── infer.py
│       ├── events.py
│       ├── evaluate.py
│       ├── baseline.py
│       └── export_coreml.py
└── tests/
    ├── test_sampling.py
    ├── test_events.py
    ├── test_dataset.py
    ├── test_model.py
    └── test_evaluate.py
```

Expose one CLI executable through `pyproject.toml`:

```text
cardevent
```

Use `argparse` or Typer. Prefer Typer if it does not complicate packaging.

---

# 4. Input assumptions

The implementation may assume prerecorded video files are provided by the user.

Supported inputs should include common `.mov` and `.mp4` recordings.

Example:

```text
data/raw/game01.mov
data/raw/game02.mov
data/raw/game03.mp4
```

Do not implement video upload/download or capture.

The code must never silently split one video across train and test sets.

---

# 5. Annotation format

Each video needs:

1. A normalized rectangular region of interest representing the relevant table/trick area.
2. Event timestamps for played cards.

Use JSON per source video.

Example:

```json
{
  "video": "game01.mov",
  "roi": {
    "x": 0.12,
    "y": 0.18,
    "width": 0.72,
    "height": 0.63
  },
  "events": [
    {"time_s": 73.420, "type": "card_played"},
    {"time_s": 78.810, "type": "card_played"}
  ]
}
```

Coordinates are normalized to `[0, 1]` relative to the source video frame.

Validation requirements:

- `x`, `y`, `width`, `height` must describe a valid rectangle within the frame.
- event times must be >= 0 and <= video duration.
- events must be sorted before saving.
- duplicate events less than 100 ms apart should produce a warning.

---

# 6. Event definition

Use this annotation convention everywhere:

> Event time is the first frame at which the newly played card has substantially reached its final position in the trick/table area.

The event is **not**:

- the start of the player's arm movement;
- first visibility of the card;
- release of the card;
- the moment the card becomes readable.

The annotation tool must display this definition in its help text.

---

# 7. Annotation tool

Implement:

```bash
cardevent annotate data/raw/game01.mov
```

Behavior:

1. Open video in an OpenCV window.
2. On first use, allow selecting the table ROI.
3. Play/pause video.
4. Allow scrubbing backward/forward.
5. Press a single obvious key, preferably `SPACE`, to mark a `card_played` event at the current timestamp.
6. Allow deleting the most recently created event.
7. Show current timestamp and number of events on the frame.
8. Save incrementally after every annotation change so work is not lost.
9. Resume from an existing annotation file.

Minimum controls:

```text
SPACE   mark event
P       pause/play
A/D     seek backward/forward ~250 ms
J/L     seek backward/forward ~2 s
BACKSPACE or X  remove latest event
R       redefine ROI
Q       save and exit
```

Exact key mapping may differ if OpenCV has platform-specific limitations, but document it in `README.md` and print it at startup.

Do not spend excessive effort making this UI polished. It is an internal labeling utility.

---

# 8. Video cache/preprocessing

Training should not repeatedly decode arbitrary source video formats from random positions.

Implement:

```bash
cardevent prepare \
  --videos data/raw/game01.mov data/raw/game02.mov
```

For every annotated source video:

1. Read the ROI.
2. Decode the source video sequentially.
3. Sample frames at **10 frames per second**.
4. Crop to ROI.
5. Preserve aspect ratio.
6. Letterbox/pad to a square.
7. Resize to **224 x 224**.
8. Save frames as JPEG with quality around 90, or PNG if implementation simplicity is comparable.
9. Write metadata mapping cached frame number to source timestamp.

Suggested cache layout:

```text
data/cache/game01/
├── metadata.json
└── frames/
    ├── 000000.jpg
    ├── 000001.jpg
    └── ...
```

`metadata.json` must include at least:

```json
{
  "source_video": "game01.mov",
  "cache_fps": 10.0,
  "duration_s": 1234.5,
  "frame_timestamps_s": [0.0, 0.1, 0.2]
}
```

If source decoding fails, produce an actionable error mentioning FFmpeg/OpenCV compatibility rather than silently skipping frames.

---

# 9. Causal sample definition

This is a critical requirement.

Each model sample represents a decision at time `t`.

Input:

- exactly **8 RGB frames**;
- all frames are from `<= t`;
- frames cover approximately the previous **1.4 seconds**.

Target offsets relative to `t`:

```text
[-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0] seconds
```

For each requested timestamp, select the nearest cached frame.

Never use a frame after `t`.

Tensor shape returned by the dataset:

```text
[T, C, H, W] = [8, 3, 224, 224]
```

After batching:

```text
[B, T, C, H, W]
```

---

# 10. Label semantics

For a sample ending at time `t`:

```text
positive = at least one annotated card event occurred in [t - 0.45 s, t]
```

This intentionally means:

> "A card has landed very recently."

Do not label based on future frames.

Negative candidates must initially be at least this far away from any event:

```text
no annotated event in [t - 1.8 s, t + 0.8 s]
```

This exclusion zone prevents ambiguous clips around a play from being used as clean negatives.

Generate approximately:

```text
1 positive : 3 negative
```

training samples.

Validation and test inference must **not** use this balanced sampling. They operate over complete videos at a regular inference stride.

---

# 11. Dataset split policy

Split by entire source video.

Never perform random frame-level or clip-level splitting across a source video.

Represent splits in YAML:

```yaml
train:
  - game01
  - game02
  - game03
val:
  - game04
test:
  - game05
```

Implement:

```bash
cardevent make-split data/raw/*.mov
```

If enough videos exist, choose a deterministic approximate `70/15/15` split by video count using a configured random seed.

If fewer than 3 videos exist, warn that a meaningful independent test set cannot be created and require/allow the user to edit the split manually.

The split file must be persisted and reused. Training must not silently regenerate it.

---

# 12. Data augmentation

Augmentation must preserve temporal consistency.

Do **not** independently apply random color/spatial transforms to each frame in an 8-frame clip because that creates artificial flicker that could become a shortcut feature.

Implement `ClipTransform` that samples augmentation parameters once and applies the same transform to every frame in the clip.

Initial training augmentations:

- horizontal flip, p=0.5;
- brightness jitter;
- contrast jitter;
- saturation jitter;
- small hue jitter;
- occasional Gaussian blur;
- small scale/crop perturbation if it can be applied identically to all frames.

Keep augmentation moderate.

Do not add synthetic occlusion, perspective distortion, MixUp, CutMix, or other complex augmentation in v1.

Validation/test transforms must only normalize images.

Use ImageNet normalization because the backbone uses ImageNet-pretrained weights.

---

# 13. CardEventNet architecture

Implement exactly this first model unless a torchvision API detail requires a small mechanical adjustment.

## Spatial backbone

Use:

```python
torchvision.models.mobilenet_v3_small(weights="DEFAULT")
```

Use the convolutional feature extractor and global average pooling, not the original classification output.

Each frame independently passes through the **same** backbone.

Expected conceptual flow:

```text
[B, 8, 3, 224, 224]
       |
reshape
       v
[B*8, 3, 224, 224]
       |
MobileNetV3-Small.features
       |
adaptive average pool
       |
[B*8, backbone_dim]
       |
reshape
       v
[B, 8, backbone_dim]
```

Do not instantiate one backbone per frame.

## Projection

Project each frame feature vector:

```text
backbone_dim -> 128
ReLU
Dropout(0.1)
```

Result:

```text
[B, 8, 128]
```

## Temporal head

Transpose to:

```text
[B, 128, 8]
```

Then:

```text
Conv1d(128, 64, kernel_size=3, padding=1)
ReLU
Conv1d(64, 32, kernel_size=3, padding=1)
ReLU
```

Use the temporal feature corresponding to the **last input position**:

```text
x[:, :, -1]
```

Then:

```text
Linear(32, 1)
```

Return one raw logit per sample.

Do not put sigmoid inside the model. Use `BCEWithLogitsLoss` in training and sigmoid only for probabilities during inference.

---

# 14. Model shape tests

Add unit tests that verify:

```python
input.shape == (2, 8, 3, 224, 224)
output.shape == (2,)
```

Also verify:

- backward pass runs;
- gradients reach the temporal head;
- model runs on CPU;
- if MPS exists, a smoke test may be provided but must not make CI depend on MPS.

---

# 15. Training schedule

Use a simple two-stage transfer-learning schedule.

## Stage A — temporal head warmup

Freeze all MobileNet backbone parameters.

Train projection + temporal head for:

```text
5 epochs
AdamW
learning_rate = 1e-3
weight_decay = 1e-4
```

## Stage B — fine tuning

Unfreeze the entire network.

Continue training for:

```text
15 epochs
AdamW
learning_rate = 1e-4
weight_decay = 1e-4
```

Use:

```python
BCEWithLogitsLoss()
```

because the training manifest is already approximately balanced 1:3.

Default batch size:

```text
16
```

Make batch size configurable.

Do not use a scheduler unless training is clearly unstable. Keep v1 simple.

Set deterministic/random seeds for Python, NumPy, and PyTorch where practical.

---

# 16. Training command

Implement:

```bash
cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml
```

The training run must output to a timestamped or named run directory:

```text
data/outputs/run-YYYYMMDD-HHMMSS/
├── config.yaml
├── metrics.jsonl
├── best.pt
├── last.pt
└── summary.json
```

Save at least:

- epoch;
- train loss;
- validation loss;
- validation event recall;
- validation false events/hour;
- validation precision;
- learning rate.

Select `best.pt` using validation event behavior, not ordinary clip classification accuracy.

Initial ranking criterion:

1. Prefer checkpoints with event recall >= 0.98.
2. Among those, choose lowest false-events/hour.
3. If no checkpoint reaches 0.98 recall, choose highest recall, with false-events/hour as tie-breaker.

Do not evaluate against the test split during model selection.

---

# 17. Offline inference

Implement:

```bash
cardevent infer \
  --checkpoint data/outputs/.../best.pt \
  --video data/raw/game05.mov \
  --out predictions.json
```

Offline inference must mimic future live inference.

Decision timestamps:

```text
8 decisions per second
stride = 0.125 s
```

At every time `t`, construct the causal 8-frame sample ending at `t` and produce:

```json
{
  "time_s": 73.625,
  "probability": 0.982
}
```

Keep raw per-timestamp probabilities available for debugging.

---

# 18. Convert probabilities into discrete events

The network produces a probability stream. Multiple adjacent timestamps will often be positive for one real play.

Implement a separate deterministic post-processing function:

```python
def probabilities_to_events(
    samples: list[ProbabilitySample],
    threshold: float,
    merge_window_s: float = 0.6,
) -> list[DetectedEvent]:
    ...
```

Algorithm:

1. Keep samples where `probability >= threshold`.
2. Consecutive above-threshold samples separated by no more than `merge_window_s` belong to one cluster.
3. Emit one event per cluster.
4. Event timestamp is the timestamp of the highest-probability sample in that cluster.
5. Event probability is that maximum probability.

Write thorough unit tests for this function.

Do not hide this logic inside model inference.

---

# 19. Threshold selection

Threshold is a validation-set hyperparameter, not a hard-coded truth.

Implement validation threshold search over at least:

```text
0.10, 0.15, 0.20, ... 0.95
```

For every candidate threshold compute event metrics across the entire validation set.

Select threshold using:

1. event recall >= 0.98 if possible;
2. minimum false events/hour among thresholds satisfying that recall;
3. otherwise maximum recall, with false events/hour as tie-breaker.

Persist selected threshold in `summary.json` and/or beside the checkpoint.

Test evaluation must use that persisted validation-selected threshold.

---

# 20. Event-level evaluation

Do not report ordinary frame/clip accuracy as the primary metric.

Ground-truth and predicted events are matched one-to-one.

A prediction is considered eligible to match a ground-truth event if:

```text
abs(predicted_time - ground_truth_time) <= 0.75 seconds
```

Use greedy nearest-time one-to-one matching, or another deterministic matching method that produces the obvious one-to-one result.

Report:

```text
real events
detected true events
missed events
false events
event recall
event precision
false events/hour
latency median
latency p95
```

Latency:

```text
predicted event timestamp - ground truth timestamp
```

Negative latency is allowed because the visual action can permit a trigger slightly before the annotation's landing-frame convention.

Also generate:

- probability-over-time plot for each evaluated video;
- ground-truth markers on the plot;
- predicted-event markers;
- precision/recall or threshold tradeoff plot for validation.

Use matplotlib only.

---

# 21. Evaluation command

Implement:

```bash
cardevent evaluate \
  --checkpoint data/outputs/.../best.pt \
  --split data/splits/default.yaml \
  --partition test
```

Example human-readable output:

```text
Videos:             2
Duration:           1.42 h
True events:        192
Detected:           189
Missed:             3
False detections:   7
Recall:             98.44%
Precision:          96.43%
False/hour:         4.93
Latency p50:        0.25 s
Latency p95:        0.61 s
Threshold:          0.40
```

Also save the machine-readable result as JSON.

---

# 22. Classical baseline

Implement one deliberately simple non-ML baseline so model performance has context.

Use the same cached frames and ROI.

A reasonable baseline score is average absolute pixel difference between successive sampled frames, optionally averaged across the 8-frame input window.

Expose:

```bash
cardevent baseline --split data/splits/default.yaml --partition val
```

Tune its event threshold using the same validation logic and evaluate using the same event matcher.

Do not over-engineer this baseline.

Its purpose is to answer:

> Does the neural model materially outperform trivial motion detection?

---

# 23. Hard-negative mining

Implement this only after the first complete train/infer/evaluate loop works.

Add:

```bash
cardevent mine-hard-negatives \
  --checkpoint ... \
  --split data/splits/default.yaml
```

Behavior:

1. Run inference over training videos.
2. Find predicted events that are not within the event matching window of a real annotation.
3. Store their timestamps in a hard-negative manifest.
4. On subsequent training runs, sample these negatives at a higher rate than ordinary negatives.

Do not automatically modify ground-truth annotations.

Hard-negative examples are expected to include:

- hands moving over the table;
- reaching for cards;
- adjusting already-played cards;
- sweeping up a trick;
- drinks or objects entering the ROI;
- lighting changes;
- camera shake.

---

# 24. Configuration

`configs/base.yaml` should contain all important experiment constants.

Suggested initial contents:

```yaml
seed: 42

input:
  size: 224
  cache_fps: 10.0
  clip_offsets_s: [-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0]
  inference_stride_s: 0.125

labels:
  positive_window_s: 0.45
  negative_past_exclusion_s: 1.8
  negative_future_exclusion_s: 0.8
  negative_to_positive_ratio: 3

model:
  backbone: mobilenet_v3_small
  pretrained: true
  feature_dim: 128
  temporal_hidden_1: 64
  temporal_hidden_2: 32
  dropout: 0.1

training:
  batch_size: 16
  warmup_epochs: 5
  finetune_epochs: 15
  warmup_lr: 0.001
  finetune_lr: 0.0001
  weight_decay: 0.0001
  device: auto

inference:
  merge_window_s: 0.6

metrics:
  event_match_tolerance_s: 0.75
  target_recall: 0.98
```

Validate config values at startup and fail early on invalid values.

---

# 25. Core ML export

This is the final phase, after PyTorch inference/evaluation works.

Implement:

```bash
cardevent export-coreml \
  --checkpoint data/outputs/.../best.pt \
  --out CardEventNet.mlpackage
```

Requirements:

- fixed model input shape: `[1, 8, 3, 224, 224]`;
- model output: one raw logit or one probability; prefer raw logit if conversion remains straightforward;
- use `coremltools` only on supported macOS environments;
- make it an optional dependency so Linux/RunPod training does not require Core ML packages.

Add a conversion verification script/test:

1. Generate a deterministic sample tensor.
2. Run PyTorch model.
3. Run converted Core ML model if possible.
4. Verify outputs are numerically close within a reasonable tolerance.

Do not implement Swift/iOS integration yet.

---

# 26. High-resolution evidence package interface

Although cloud recognition is out of scope, define the data structure that CardEventNet will eventually hand downstream.

For now, offline inference may write this metadata only:

```json
{
  "event_time_s": 73.625,
  "probability": 0.982,
  "source_video": "game05.mov",
  "recommended_evidence_offsets_s": [-0.8, -0.4, -0.1, 0.15, 0.4, 0.7]
}
```

Do not actually upload anything.

Optionally implement extraction of those source-resolution evidence frames to disk for manual inspection:

```bash
cardevent extract-evidence \
  --video data/raw/game05.mov \
  --predictions predictions.json \
  --out data/outputs/evidence/
```

This extraction must use the original source video, not the 224x224 training cache.

---

# 27. Tests

At minimum implement tests for:

## Sampling

- all 8 selected frame timestamps are <= decision time;
- correct nearest-frame behavior;
- correct behavior near start of video;
- positive label window;
- negative exclusion window.

## Dataset

- correct tensor shape;
- correct label type;
- augmentations preserve same output shape;
- no train/val/test source-video overlap.

## Model

- correct input/output shapes;
- backward pass;
- pretrained backbone can be frozen/unfrozen.

## Event post-processing

- one sustained probability peak becomes one event;
- two distant peaks become two events;
- sub-threshold samples produce no event;
- cluster uses maximum-probability timestamp.

## Event matching

- exact match;
- match inside tolerance;
- no match outside tolerance;
- one prediction cannot satisfy two ground-truth events;
- false positives and misses counted correctly.

Tests should use tiny generated synthetic frames/data and must not require real user videos.

---

# 28. Logging and reproducibility

Use the standard Python `logging` module.

Every training run should record:

- git commit hash if repository is in Git;
- complete resolved config;
- Python version;
- PyTorch version;
- torchvision version;
- selected device;
- random seed;
- source video names used in each split.

Avoid building a custom experiment-management system.

---

# 29. README workflow

The final README should give this exact conceptual workflow:

```bash
# 1. Install
uv sync

# 2. Put source videos somewhere accessible
# Example: data/raw/*.mov

# 3. Annotate each video
uv run cardevent annotate data/raw/game01.mov

# 4. Build low-resolution frame cache
uv run cardevent prepare --videos data/raw/*.mov

# 5. Create or edit a video-level split
uv run cardevent make-split data/raw/*.mov

# 6. Train
uv run cardevent train --config configs/base.yaml --split data/splits/default.yaml

# 7. Evaluate
uv run cardevent evaluate --checkpoint <best.pt> --split data/splits/default.yaml --partition test

# 8. Inspect one video
uv run cardevent infer --checkpoint <best.pt> --video data/raw/game05.mov --out predictions.json

# 9. Optional after model validation
uv run cardevent export-coreml --checkpoint <best.pt> --out CardEventNet.mlpackage
```

Also document:

```bash
uv run pytest
uv run ruff check .
```

---

# 30. Implementation order

Implement in the following order. Do not jump ahead.

## Phase 1 — project skeleton

Deliver:

- `pyproject.toml`;
- package layout;
- config loading;
- device selection;
- basic CLI;
- Ruff/pytest setup.

Acceptance:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run cardevent --help
```

all succeed.

## Phase 2 — annotation and video metadata

Deliver:

- video metadata reading;
- annotation schema;
- annotation validation;
- OpenCV annotation utility;
- ROI selection.

Acceptance:

A user can annotate a supplied video, quit, reopen it, and continue without losing existing events.

## Phase 3 — cache and dataset

Deliver:

- 10 fps cached ROI frame extraction;
- cached timestamp metadata;
- causal 8-frame sampler;
- labels;
- video-level split;
- temporally consistent augmentations;
- unit tests.

Acceptance:

A dataset sample has shape `[8, 3, 224, 224]`, and tests prove it never uses a future frame.

## Phase 4 — model and training

Deliver:

- MobileNetV3-Small backbone;
- temporal Conv1D head;
- freeze/unfreeze helpers;
- two-stage training loop;
- checkpointing;
- run metadata.

Acceptance:

The model can overfit a tiny subset of training samples. Add a development option such as `--max-samples 32` to make this sanity check convenient.

## Phase 5 — inference and event metrics

Deliver:

- full-video causal inference;
- probability stream;
- event clustering;
- event matching;
- threshold tuning on validation;
- event-level metrics;
- plots;
- classical motion baseline.

Acceptance:

A complete validation/test evaluation can be executed with one command and outputs both human-readable and JSON metrics.

## Phase 6 — hard-negative mining

Deliver:

- false-trigger discovery over training videos;
- hard-negative manifest;
- preferential hard-negative sampling.

Acceptance:

A training run can consume the mined manifest without changing annotations.

## Phase 7 — Core ML export

Deliver:

- optional `coremltools` dependency;
- model export;
- parity check;
- documentation.

Acceptance:

A trained checkpoint can produce a `.mlpackage` from the fixed `[1,8,3,224,224]` input.

---

# 31. Engineering constraints for the implementation agent

Follow these strictly:

1. **Do not redesign the architecture while implementing it.** Get the specified baseline working first.
2. **Do not introduce abstractions without two concrete uses.**
3. Prefer dataclasses/type hints and ordinary Python over framework magic.
4. Keep model code independent from CLI code.
5. Keep probability-to-event post-processing independent from the network.
6. Keep evaluation independent from training.
7. Never use test data to select threshold or checkpoint.
8. Never split frames from one source video across dataset partitions.
9. Never use future frames in a sample.
10. Add unit tests before or alongside behavior that is easy to get subtly wrong.
11. Every CLI command must fail with a useful error message rather than a raw `KeyError`/`IndexError` where reasonable.
12. Do not silently ignore malformed annotations or missing frames.
13. Do not optimize for performance until one complete end-to-end pipeline works.
14. Do not require RunPod, Docker, or CUDA for local development.
15. Keep Core ML optional until the PyTorch model has been evaluated successfully.

---

# 32. Initial success criteria

The implementation is technically complete when:

- prerecorded videos can be annotated;
- annotations and ROI persist;
- videos can be preprocessed into a deterministic frame cache;
- train/val/test split is video-level;
- causal training samples are generated correctly;
- MobileNetV3-Small + temporal head trains on MPS/CUDA/CPU;
- checkpoints are saved and reloadable;
- full videos can be scanned causally;
- probabilities are converted into discrete events;
- event recall, precision, false/hour, and latency are measured;
- the motion baseline uses the same evaluator;
- threshold selection uses validation only;
- test evaluation is separate;
- hard negatives can be mined;
- trained model can optionally be exported to Core ML.

Do **not** block technical completion on a specific model-quality target because the initial dataset may be too small.

The target direction for real model quality is:

```text
primary:   missed-card rate as close to zero as possible
secondary: false-event rate low enough for cloud filtering to be cheap
tertiary:  low detection latency
```

A useful early target, once enough representative data exists, is:

```text
event recall >= 98%
false events/hour <= 10
```

This is an experimental target, not a guarantee.

---

# 33. What not to build yet

Explicitly out of scope:

- card rank/suit classification;
- object detection or bounding boxes;
- card segmentation;
- OCR;
- player identification;
- game rules/game-state engine;
- Qwen or GPT vision integration;
- server/cloud upload;
- live camera capture;
- Swift/iOS application code;
- model quantization;
- ANE-specific optimization;
- video transformers;
- 3D CNNs;
- optical-flow networks.

These should be reconsidered only after event detection has measurable results on held-out real videos.

---

# 34. Expected implementation-agent behavior

Implement one phase at a time and verify each phase before moving on.

After each phase:

1. run relevant tests;
2. run Ruff;
3. repair failures;
4. summarize files changed and commands executed;
5. continue to the next phase unless blocked by missing user data or an external dependency.

Do not ask the user to make routine implementation decisions already specified by this document.

If a library API differs from the assumptions in this plan, make the smallest compatible change and document it.

If real videos are unavailable during implementation, use synthetic generated fixtures for automated tests and leave commands ready to operate on the supplied videos later.
