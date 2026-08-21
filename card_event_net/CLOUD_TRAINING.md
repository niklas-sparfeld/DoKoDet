# Cloud training

CardEventNet uses the same `cardevent train` command locally and on a cloud GPU.

This guide uses a RunPod GPU Pod as the concrete example. The training code itself does not depend on RunPod.

## Storage layout

Keep persistent data on the RunPod network volume under `/workspace`.

Recommended layout:

    /workspace/
    └── DoKoDet/
        └── card_event_net/
            ├── data/raw/
            ├── data/annotations/
            ├── data/splits/
            ├── data/cache/
            └── data/outputs/

Use the persistent volume for:

- the Git repository;
- raw videos;
- annotations and splits;
- the canonical prepared cache;
- checkpoints and run outputs.

Do not train directly from the network-volume cache when local pod storage is available.

The cache contains many small JPEG files. Copy it to local pod storage before training.

---

## Initial pod setup

Install Git LFS, `rsync`, and `uv`:

    apt-get update && apt-get install -y git-lfs rsync
    git lfs install

    pip install uv

CardEventNet requires Python 3.12 or 3.13.

Let `uv` install Python 3.12 if necessary:

    uv python install 3.12

Clone the repository:

    cd /workspace

    git clone https://github.com/niklas-sparfeld/DoKoDet.git
    cd DoKoDet

    git lfs pull

Enter CardEventNet and install its locked dependencies:

    cd card_event_net

    uv sync --frozen --python 3.12

On Linux, the project selects the official CUDA 12.8 PyTorch packages.

A separate system CUDA toolkit is not required.

---

## Verify CUDA

Before training:

    uv run python - <<'PY'
    import torch

    print("torch:", torch.__version__)
    print("CUDA build:", torch.version.cuda)
    print("CUDA available:", torch.cuda.is_available())

    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
        print("BF16:", torch.cuda.is_bf16_supported())
    PY

The important results are:

    CUDA available: True
    BF16: True

for normal BF16 cloud training.

You can also inspect the GPU continuously:

    watch -n 1 nvidia-smi

---

## Prepare the frame cache

The cache only needs to be generated once.

Keep the canonical cache on the persistent network volume:

    /workspace/DoKoDet/card_event_net/data/cache

For example:

    uv run cardevent prepare \
      --videos data/raw/game01.mov data/raw/game02.mov

Include all relevant source videos.

The prepared cache is generated data and must not be committed to Git.

---

## Copy the cache to local pod storage

Training repeatedly reads thousands of small JPEG files.

RunPod network volumes can be considerably slower for this workload than the pod's local filesystem.

Before training, copy the prepared cache to `/tmp`:

    rm -rf /tmp/cardevent-cache
    mkdir -p /tmp/cardevent-cache

    rsync -a --delete --info=progress2 \
      data/cache/ \
      /tmp/cardevent-cache/

The trailing `/` after `data/cache/` is intentional. It copies the contents of the cache into:

    /tmp/cardevent-cache/

Verify the copy:

    du -sh data/cache
    du -sh /tmp/cardevent-cache

Optionally inspect the filesystems:

    df -h /workspace /tmp

The `/tmp/cardevent-cache` copy is disposable.

If the pod is destroyed, rebuild it from the canonical cache with `rsync`.

Do not copy `data/outputs` to `/tmp`. Keep checkpoints persistent.

---

## Check available CPUs

DataLoader workers still perform JPEG decoding.

Check the number of CPUs available to the pod:

    nproc

Use `htop` while training if needed:

    htop

A reasonable starting point is:

    --num-workers 8

On pods with more CPU capacity, compare 8 and 16 workers using actual training throughput.

---

## Smoke test

Run a small training job before starting a full run:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --cache-dir /tmp/cardevent-cache \
      --annotations-dir data/annotations \
      --output-dir /workspace/DoKoDet/card_event_net/data/outputs \
      --device cuda \
      --precision bf16 \
      --num-workers 8 \
      --batch-size 64 \
      --max-samples 64 \
      --run-name cloud-smoke

This verifies:

- the local cache;
- CUDA;
- BF16;
- DataLoader multiprocessing;
- validation;
- checkpoint output.

The resulting run is stored persistently at:

    /workspace/DoKoDet/card_event_net/data/outputs/cloud-smoke

---

## Full training

A reasonable starting command is:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --cache-dir /tmp/cardevent-cache \
      --annotations-dir data/annotations \
      --output-dir /workspace/DoKoDet/card_event_net/data/outputs \
      --device cuda \
      --precision bf16 \
      --num-workers 8 \
      --batch-size 128

`8` workers and a batch size of `128` are starting points, not required settings.

Use:

    train_samples_per_s

from the run's `metrics.jsonl` when comparing settings.

Do not optimize only for the GPU utilization percentage.

---

## Monitor utilization

In another terminal:

    watch -n 1 nvidia-smi

Useful signals:

- GPU utilization;
- GPU memory use;
- power consumption;
- whether the Python process appears on the GPU.

For CPU utilization:

    htop

If `pt_data_worker` processes remain fully occupied while the GPU regularly waits, the remaining bottleneck is probably JPEG decoding.

Try additional DataLoader workers only if the pod has unused CPU capacity.

For example:

    --num-workers 16

Compare `train_samples_per_s` rather than guessing from CPU or GPU percentages.

---

## Batch size

Do not simply use the largest batch that fits into VRAM.

Batch size changes training behavior.

Start around:

    64
    128

and increase it only after comparing both throughput and model quality.

A large GPU such as an RTX 6000 may have far more VRAM than CardEventNet needs.

That is expected.

---

## Resume an interrupted run

The run outputs remain on the persistent network volume, so a new pod can resume a previous run.

First recreate the local cache:

    rm -rf /tmp/cardevent-cache
    mkdir -p /tmp/cardevent-cache

    rsync -a --delete --info=progress2 \
      data/cache/ \
      /tmp/cardevent-cache/

Then resume:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --cache-dir /tmp/cardevent-cache \
      --annotations-dir data/annotations \
      --device cuda \
      --precision bf16 \
      --num-workers 8 \
      --batch-size 128 \
      --resume /workspace/DoKoDet/card_event_net/data/outputs/run-YYYYMMDD-HHMMSS

Do not pass `--run-name` together with `--resume`.

Runtime settings such as worker count and batch size may be specified explicitly when resuming.

---

## Evaluate on the pod

Use the local cache for evaluation as well:

    uv run cardevent evaluate \
      --checkpoint /workspace/DoKoDet/card_event_net/data/outputs/run-.../best.pt \
      --split data/splits/default.yaml \
      --partition test \
      --cache-dir /tmp/cardevent-cache \
      --annotations-dir data/annotations \
      --device cuda

This avoids moving evaluation back onto the network-volume frame cache.

---

## Hard-negative mining

Hard-negative mining should also use the local cache:

    uv run cardevent mine-hard-negatives \
      --checkpoint /workspace/DoKoDet/card_event_net/data/outputs/run-.../best.pt \
      --split data/splits/default.yaml \
      --cache-dir /tmp/cardevent-cache \
      --annotations-dir data/annotations \
      --out /workspace/DoKoDet/card_event_net/data/outputs/hard-negatives.json

Keep generated manifests and other useful results on the persistent volume.

---

## Export to Core ML

Run Core ML export on a Mac, not on the cloud GPU pod.

For example:

    uv run cardevent export-coreml \
      --checkpoint data/outputs/run-.../best.pt \
      --out CardEventNet.mlpackage

Copy the checkpoint from the RunPod persistent volume to the Mac first.

---

## Starting a replacement pod

When replacing a pod, the normal setup is:

    cd /workspace/DoKoDet
    git pull
    git lfs pull

    cd card_event_net

    pip install uv
    uv sync --frozen --python 3.12

    rm -rf /tmp/cardevent-cache
    mkdir -p /tmp/cardevent-cache

    rsync -a --delete --info=progress2 \
      data/cache/ \
      /tmp/cardevent-cache/

Then start or resume training with:

    --cache-dir /tmp/cardevent-cache

The repository, canonical cache, and outputs remain on `/workspace`.

Only the local `/tmp` copy needs to be recreated.

---

## Performance workflow

When tuning a pod, change one thing at a time.

A useful sequence is:

    workers=4
    workers=8
    workers=16

then:

    batch=64
    batch=128

Record:

    train_samples_per_s

for each run.

If increasing worker count no longer improves throughput and the GPU still spends substantial time idle, profile JPEG decoding before making further changes to batch size.

The next likely optimization would be replacing the JPEG training cache with a decode-free local representation. Do not change the cache format until profiling shows that JPEG decoding is the remaining bottleneck.