# Cloud training

CardEventNet uses the same `cardevent train` command on a local machine and on a
cloud GPU. This guide uses a RunPod Secure Cloud GPU Pod as one example. The
training code does not depend on RunPod.

## Persistent storage

Use a persistent or network volume. Store the repository, frame cache, and run
outputs on this volume. A pod can then stop without losing checkpoints.

The expected layout is:

```text
/workspace/
└── DoKoDet/
    └── card_event_net/
        ├── data/raw/
        ├── data/cache/
        └── data/outputs/
```

## Setup

Create a RunPod Secure Cloud GPU Pod. Start with an RTX 4090-class GPU. An RTX
5090 also works. The best worker count and batch size depend on the pod.

Run these commands on the pod:

```bash
cd /workspace
git clone https://github.com/niklas-sparfeld/DoKoDet.git
cd DoKoDet
git lfs pull

mise install
eval "$(mise activate bash)"

cd card_event_net
uv sync --frozen
```

The lock file selects the official CUDA 12.8 PyTorch index on Linux. The
PyTorch packages provide the CUDA runtime. A system CUDA toolkit is not needed.

Check the GPU before training:

```bash
uv run python - <<'PY'
import torch

print("torch:", torch.__version__)
print("cuda build:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))
PY
```

The check must report `cuda available: True`.

## Prepare the cache

Build the cache once. Keep `data/cache/` on the persistent volume.

```bash
uv run cardevent prepare --videos data/raw/*.mov
```

Some source files use another extension. Include them in the command when
needed, for example `data/raw/*.m4v`.

## Run a smoke test

Use a small smoke test before a full run:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml \
  --device cuda \
  --precision bf16 \
  --num-workers 4 \
  --max-samples 32 \
  --run-name cloud-smoke
```

This checks CUDA, BF16 autocast, the cache, validation, and checkpoint output.
Inspect `data/outputs/cloud-smoke/` after the run.

## Run training

Start a full run after the smoke test:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml \
  --device cuda \
  --precision bf16 \
  --num-workers 8 \
  --batch-size 32
```

The values `8` and `32` are starting points. They are not universal settings.
If the run succeeds and GPU memory remains available, increase the batch size.
Use `train_samples_per_s` in `metrics.jsonl` to compare settings.

Each run writes `config.yaml`, `environment.json`, `metrics.jsonl`, `last.pt`,
`best.pt`, and `summary.json`. The environment files record the CUDA build and
the GPU name when CUDA is active.

## Resume a stopped run

Pass the run directory or its `last.pt` file. Do not pass `--run-name` with
`--resume`.

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml \
  --device cuda \
  --precision bf16 \
  --num-workers 8 \
  --batch-size 32 \
  --resume data/outputs/run-YYYYMMDD-HHMMSS
```

Resume continues at the next epoch. It restores the optimizer for the active
warmup or fine-tune stage. It creates a new optimizer at the stage boundary.
The existing `best.pt` and metric rows remain part of the run.

## Evaluate and export

Use the existing evaluation commands on the pod:

```bash
uv run cardevent evaluate \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/default.yaml \
  --partition test
```

Run Core ML export on a Mac. Do not use the cloud pod for that step:

```bash
uv run cardevent export-coreml \
  --checkpoint data/outputs/run-.../best.pt \
  --out CardEventNet.mlpackage
```

Copy the checkpoint to the Mac, or access it through the same persistent
storage. Do not commit the cache or checkpoints to Git.
