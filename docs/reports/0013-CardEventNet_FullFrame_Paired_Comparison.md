# CardEventNet full-frame paired comparison

## Result

Do not replace the ROI model with this checkpoint. The full-frame run meets the 0.98 aggregate
validation recall target, but it has more false events and lower worst-video recall than the locked
ROI run.

This is a paired preprocessing diagnostic on `data/splits/new.yaml`. It is not a session-isolated
generalization result. The old test partition was not evaluated again.

## Locked comparison

Both runs use the same split, labels, seed, input size, temporal sampling, model architecture, and
decoder configuration. The input preprocessing is the intended difference.

| Validation metric | ROI baseline | Full frame | Change |
|---|---:|---:|---:|
| Recall | 0.9875 | 0.9813 | -0.0062 |
| Precision | 0.7822 | 0.7169 | -0.0653 |
| F1 | 0.8729 | 0.8285 | -0.0444 |
| False events | 44 | 62 | +18 |
| False events/hour | 436.26 | 614.73 | +178.47 (+40.9%) |
| Maximum F1 | 0.8795 | 0.8298 | -0.0497 |
| Worst-video recall | 0.950 | 0.925 | -0.025 |
| Median timestamp error | 0.062 s | 0.088 s | +0.026 s |

The corrected full-frame emission latency is 0.213 seconds at p50 and 0.468 seconds at p95. The
legacy report did not include confirmation delay. Adding its locked 0.125-second delay gives an
inferred ROI p50 emission latency of 0.187 seconds. This inferred value is for comparison only.

The selected threshold changed from 0.967 for ROI input to 0.058 for full-frame input. This large
calibration shift is consistent with weaker event scores after the cards become smaller in the
input. It does not by itself identify the cause of each error.

## Per-video result

| Video | ROI recall | Full recall | ROI false events | Full false events |
|---|---:|---:|---:|---:|
| `IMG_0639` | 1.000 | 0.925 | 7 | 15 |
| `IMG_0657` | 0.950 | 1.000 | 15 | 17 |
| `IMG_0642` | 1.000 | 1.000 | 7 | 7 |
| `IMG_0643` | 1.000 | 1.000 | 15 | 23 |

All three full-frame misses are in `IMG_0639`. Two are complete misses near 56.55 and 58.81
seconds. One is a near miss near 65.56 seconds. `IMG_0643` has the largest false-event count.
`IMG_0657` and `IMG_0643` also contain many false candidates with model probability above 0.99.
These candidates can be missing state-change annotations. Do not train them as hard negatives
until a human reviews them.

## Run artifacts

- Run: `card_event_net/data/outputs/full-frame-20260823/paired-new-v1`
- Best epoch: 9, fine-tune epoch 4
- Preprocessing: `full_frame_letterbox_v1`
- Device: MPS, FP32
- Checkpoint SHA-256:
  `f5a27964006ae03238535fc7a814c6530baf4a9e996c05d0958a3881134e9049`
- Checkpoint size: approximately 12 MB
- Source commit recorded by the run: `990ee5f0e281f94c5a42e72931c61f7a1d98dcb0`

The generated run directory is local and ignored by git. Preserve it or archive it before deleting
local training outputs.

## Human review queue

The deterministic validation queue is in
`card_event_net/data/outputs/full-frame-20260823/paired-new-v1/review-val.json`. It contains:

- 62 unmatched model candidates;
- 3 missed annotations, all in `IMG_0639`;
- 5 low-confidence matches;
- 8 sampled empty intervals.

All 78 items have status and outcome `unreviewed`. The queue SHA-256 is
`316dad637447d1c407c5ee25e96681d2f184389c0cada8aa82b9f82794a83901`.
The queue is a local ignored artifact. No review outcome has been inferred or applied.

For each inspected item, set `status` to `reviewed` and select one documented `outcome`. For a new
`confirmed_positive`, also set `event_type` to the class from the labeling guide. For
`annotation_timestamp_corrected`, set `timestamp_s` to the corrected time. Leave uncertain items
unchanged. After review, create a new annotation version with:

```bash
uv run cardevent apply-review \
  --queue data/outputs/full-frame-20260823/paired-new-v1/review-val.json \
  --annotations-dir data/annotations \
  --out-dir data/annotations-full-frame-review-v1 \
  --reviewer REVIEWER_NAME \
  --videos-dir data/raw
```

The command rejects inconsistent review status, preserves all source annotations, validates the
new version, and writes a change summary and a separate hard-negative file.

## Commands

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/new.yaml \
  --output-dir data/outputs/full-frame-20260823 \
  --run-name paired-new-v1 \
  --cache-dir data/cache \
  --annotations-dir data/annotations \
  --device mps

uv run cardevent evaluate \
  --checkpoint data/outputs/full-frame-20260823/paired-new-v1/best.pt \
  --split data/splits/new.yaml \
  --partition val \
  --cache-dir data/cache \
  --annotations-dir data/annotations \
  --out data/outputs/full-frame-20260823/paired-new-v1/evaluation-val.json \
  --device mps

uv run cardevent diagnose \
  --checkpoint data/outputs/full-frame-20260823/paired-new-v1/best.pt \
  --split data/splits/new.yaml \
  --cache-dir data/cache \
  --annotations-dir data/annotations \
  --out data/outputs/full-frame-20260823/paired-new-v1/diagnostics.json \
  --device mps

uv run cardevent review-queue \
  --checkpoint data/outputs/full-frame-20260823/paired-new-v1/best.pt \
  --split data/splits/new.yaml \
  --partition val \
  --out data/outputs/full-frame-20260823/paired-new-v1/review-val.json \
  --cache-dir data/cache \
  --annotations-dir data/annotations \
  --device mps
```

## Decision and next gate

Keep the full-frame contract in Python, but do not export this checkpoint or remove the ROI from
iOS yet. First review the failure queue and correct missing state-change annotations. Give priority
to `IMG_0639`, `IMG_0643`, and `IMG_0657`. Then rerun the paired validation comparison once with
the corrected annotation version.

Do not use the old test partition for this work. After annotation review, confirm the generated
session metadata and run a development check on the provisional session-isolated split. A new
independent held-out session is still required for the final test.
