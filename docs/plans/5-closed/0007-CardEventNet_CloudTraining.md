# CardEventNet Cloud Training — Implementation Plan

## Plan status

- **Summary:** Extend CardEventNet training for reproducible single-GPU cloud execution
- **Status:** Closed
- **Closure reason:** Complete

## Purpose

Extend the existing `card_event_net` training pipeline so that the same code can train:

- locally on Apple Silicon;
- on CPU for tests;
- on a Linux CUDA machine;
- on an ephemeral cloud GPU such as a RunPod RTX 4090 or RTX 5090.

Do not create a separate cloud trainer.

The normal entry point must remain:

    cardevent train

Cloud execution is a deployment environment for the existing training pipeline.

The implementation must remain provider-neutral. RunPod is the first documented example, not a runtime dependency.

---

# 1. Current implementation

Build on the existing implementation.

Important current behavior:

- `device.py` already supports `auto`, `cuda`, `mps`, and `cpu`.
- `train.py` already implements the complete two-stage training schedule.
- training already writes `last.pt` and `best.pt`;
- checkpoints already contain model and optimizer state;
- `summary.json` already records Git, Python, PyTorch, and torchvision versions;
- `train` already accepts explicit cache, annotation, output, and device paths;
- raw videos are stored through Git LFS;
- annotations and splits are Git-tracked;
- `data/cache/` and `data/outputs/` are generated and ignored.

Do not replace these mechanisms.

Known cloud-training limitations:

1. Linux PyTorch installation does not explicitly select a CUDA build suitable for Blackwell.
2. `DataLoader` always uses `num_workers=0`.
3. host-to-GPU copies do not use pinned memory or non-blocking transfer.
4. training and validation always use FP32.
5. interrupted training cannot resume.
6. `metrics.jsonl` is recreated for every run.
7. `config.yaml` and final environment metadata are only completed after successful training.
8. run metadata does not identify the actual CUDA GPU.
9. there is no documented cloud workflow.

---

# 2. Scope

Implement:

1. reproducible CUDA dependency installation;
2. efficient single-GPU data loading;
3. optional BF16 training on CUDA;
4. resumable training;
5. better runtime metadata;
6. a documented RunPod workflow;
7. automated tests that do not require a GPU.

Do not implement:

- distributed training;
- DDP;
- multi-GPU support;
- PyTorch Lightning;
- W&B or MLflow;
- Kubernetes;
- RunPod API integration;
- automatic cloud provisioning;
- automatic GPU selection by price;
- Docker images unless a concrete need appears during implementation;
- a new dataset storage format;
- S3 or other object-storage integration.

One fast GPU is more than sufficient for CardEventNet at this stage.

---

# 3. Make the PyTorch lock CUDA-safe

Files:

    card_event_net/pyproject.toml
    card_event_net/uv.lock

Keep the existing versions:

    torch==2.7.0
    torchvision==0.22.0

Do not upgrade PyTorch as part of this work. Keeping the current versions avoids unnecessarily changing the tested Core ML conversion environment.

Configure `uv` so that:

- macOS continues to obtain the normal macOS PyTorch packages;
- Linux obtains PyTorch and torchvision from the official CUDA 12.8 index.

Conceptually:

    [[tool.uv.index]]
    name = "pytorch-cu128"
    url = "https://download.pytorch.org/whl/cu128"
    explicit = true

    [tool.uv.sources]
    torch = [
      { index = "pytorch-cu128", marker = "sys_platform == 'linux'" },
    ]
    torchvision = [
      { index = "pytorch-cu128", marker = "sys_platform == 'linux'" },
    ]

Use the exact syntax supported by the pinned `uv` version.

Regenerate `uv.lock`.

Acceptance:

On macOS:

    uv sync --frozen
    uv run pytest
    uv run ruff check .

must continue to work.

On a Linux CUDA machine:

    uv sync --frozen

must install a CUDA-enabled PyTorch build.

On an RTX 5090, this diagnostic must succeed:

    uv run python -c \
      "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name())"

and `torch.cuda.is_available()` must be true.

Do not require a system CUDA toolkit for normal training. Use the CUDA runtime supplied through the PyTorch packages and the NVIDIA host driver.

---

# 4. Add explicit training runtime options

The existing experiment config should continue to describe the model and normal training schedule.

Add runtime overrides to `cardevent train` rather than introducing a second cloud-specific trainer.

Add:

    --batch-size N
    --num-workers N
    --precision {fp32,bf16}

Behavior:

- `--batch-size` defaults to `training.batch_size`.
- `--num-workers` defaults to `0`.
- `--precision` defaults to `fp32`.

This preserves current local behavior unless the user explicitly opts into faster CUDA settings.

Represent the resolved values with a small internal dataclass, for example:

    TrainingRuntimeOptions

Include at least:

    batch_size
    num_workers
    pin_memory
    precision

`pin_memory` can be resolved automatically:

    CUDA -> true
    otherwise -> false

Do not expose a CLI flag unless it proves useful.

Persist the resolved runtime options in checkpoints and `summary.json`.

The effective batch size must therefore be recoverable even when it overrides `configs/base.yaml`.

---

# 5. Improve the DataLoader for CUDA

Modify `_make_loader()` in:

    src/cardevent/train.py

It currently uses:

    DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=0,
    )

Extend it to accept the resolved runtime options.

When `num_workers > 0`:

- use that worker count;
- enable `persistent_workers`;
- use a small `prefetch_factor`, initially `2`.

When CUDA is used:

- enable `pin_memory`.

When pinned memory is enabled, transfer tensors with:

    tensor.to(device, non_blocking=True)

Keep the current behavior on CPU and MPS.

Do not introduce a new dataset implementation.

The current dataset reads individual cached JPEG frames through OpenCV. First determine whether multiple workers are sufficient before considering LMDB, WebDataset, tar archives, or other cache formats.

Add deterministic worker seeding for Python and NumPy because `ClipTransform` uses Python's `random` module.

Exact bit-for-bit reproducibility across worker counts is not required.

---

# 6. Add BF16 CUDA training

Support:

    --precision bf16

only when training on CUDA.

Fail early with an actionable error if BF16 is requested and CUDA/BF16 support is unavailable.

Use PyTorch autocast around model forward and loss calculation.

Conceptually:

    with torch.autocast(
        device_type="cuda",
        dtype=torch.bfloat16,
        enabled=runtime.precision == "bf16",
    ):
        logits = model(clips)
        loss = criterion(logits, labels)

Use the same precision mode during validation.

Do not convert model parameters permanently to BF16.

Do not add FP16 or `GradScaler` in this phase. BF16 is sufficient for the intended modern NVIDIA GPUs and keeps the implementation simpler.

Checkpoints must remain normal PyTorch model state dictionaries and must continue to load for FP32 inference and Core ML export.

Tests must verify that the FP32 path remains unchanged without requiring CUDA.

---

# 7. Add training throughput measurements

Measure wall-clock duration for every training epoch.

Add fields to `metrics.jsonl`:

    train_duration_s
    train_samples_per_s

Optionally also record validation duration:

    validation_duration_s

Log a concise line such as:

    epoch=6 stage=finetune loss=... recall=... false/hour=... samples/s=...

This provides enough information to determine whether a 5090 is actually faster than a cheaper GPU and whether the input pipeline is the bottleneck.

Do not add a separate benchmarking framework.

---

# 8. Record the actual execution environment

Create environment metadata when the run starts.

Add a helper that returns information such as:

    hostname
    platform
    python_version
    torch_version
    torchvision_version
    git_commit
    device
    cuda_version
    cudnn_version
    gpu_name
    gpu_count
    gpu_total_memory

CUDA-specific values must be nullable when CUDA is unavailable.

Write:

    <run>/environment.json

before the first epoch.

Also include the relevant fields in the final `summary.json`.

Do not shell out to `nvidia-smi` for information PyTorch can provide directly.

Keep `_git_commit()` or refactor it into the environment helper.

---

# 9. Make runs resumable

This is required before recommending interruptible cloud instances.

Extend:

    cardevent train

with:

    --resume PATH

`PATH` may point to:

- a run directory containing `last.pt`; or
- directly to a checkpoint.

When `--resume` is used:

1. do not create a new run directory;
2. load the existing model state;
3. restore optimizer state when continuing the same training stage;
4. continue from the next epoch;
5. append to `metrics.jsonl`;
6. preserve the existing `best.pt`;
7. continue best-checkpoint selection using the previous best metrics.

The normal non-resume path must continue creating a new timestamped or named directory.

Reject invalid combinations such as:

    --resume ... --run-name ...

Validate that the resumed checkpoint is compatible with:

- the supplied config;
- the supplied split;
- model architecture.

A different device is allowed.

For example, training may start on a 4090 and resume on a 5090.

Do not require that the checkpoint's saved `"device"` matches the current device.

---

# 10. Resume correctly across the two training stages

The current schedule is:

    warmup:
        5 epochs
        frozen backbone
        own AdamW optimizer

    finetune:
        15 epochs
        unfrozen backbone
        new AdamW optimizer

Resume must understand the stage boundary.

Store enough state in new checkpoints to identify:

    global_epoch
    stage
    stage_epoch

For older checkpoints that contain only `epoch` and `stage`, infer `stage_epoch` from the configured schedule when practical.

Cases:

### Interrupted during warmup

Restore:

- model;
- warmup optimizer;
- epoch position.

Continue the remaining warmup epochs.

Then create the normal fresh finetune optimizer.

### Interrupted during finetune

Restore:

- model;
- finetune optimizer;
- epoch position.

Continue the remaining finetune epochs.

### Last checkpoint already completed all configured epochs

Fail clearly instead of silently starting another training cycle.

---

# 11. Preserve best-checkpoint state when resuming

On resume, inspect the existing `best.pt`.

Restore:

    best_metrics
    best_epoch
    best_stage
    best_rank

using the existing `_checkpoint_rank()` logic.

Do not reset model selection when a run resumes.

If `best.pt` does not exist but `last.pt` is valid, use the last checkpoint as the initial best candidate and log a warning.

Do not require `summary.json`, because an interrupted run may never have written it.

---

# 12. Write run metadata before training starts

Currently final metadata is primarily produced after training succeeds.

Change the lifecycle:

Immediately after creating a new run:

    config.yaml
    environment.json

must exist.

Then training may create/update:

    metrics.jsonl
    last.pt
    best.pt

At successful completion:

    summary.json

is written.

An interrupted run must therefore still contain enough information to understand and resume it.

Use atomic replacement where practical for small metadata files.

---

# 13. Keep cloud data handling simple

Do not add an object-storage abstraction yet.

The current repository already provides:

    data/raw/          Git LFS
    data/annotations/ normal Git
    data/splits/      normal Git
    data/cache/       generated, ignored
    data/outputs/     generated, ignored

Use this structure for the first cloud workflow.

On persistent cloud storage:

1. clone the repository;
2. fetch Git LFS objects;
3. build `data/cache/` once;
4. keep `data/cache/` and `data/outputs/` on persistent storage;
5. reuse them across GPU pods.

Do not commit generated frame caches.

Do not commit checkpoints.

---

# 14. Document RunPod as the first cloud example

Add:

    card_event_net/CLOUD_TRAINING.md

Keep it short.

Document a RunPod GPU Pod workflow.

Recommended topology:

    RunPod Secure Cloud GPU Pod
        |
        +-- persistent /workspace
              |
              +-- DoKoDet/
                    +-- Git checkout
                    +-- card_event_net/data/raw
                    +-- card_event_net/data/cache
                    +-- card_event_net/data/outputs

Use a persistent/network volume so terminating the compute instance does not remove caches or checkpoints.

The document should contain the complete workflow.

Example outline:

    cd /workspace

    git clone https://github.com/niklas-sparfeld/DoKoDet.git
    cd DoKoDet

    git lfs pull

    # install/use the toolchain declared by mise.toml
    mise install
    eval "$(mise activate bash)"

    cd card_event_net

    uv sync --frozen

Verify CUDA:

    uv run python - <<'PY'
    import torch
    print("torch:", torch.__version__)
    print("cuda build:", torch.version.cuda)
    print("cuda available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("gpu:", torch.cuda.get_device_name(0))
    PY

Prepare the cache once:

    uv run cardevent prepare --videos data/raw/*.mov

Run a short smoke test:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --device cuda \
      --precision bf16 \
      --num-workers 4 \
      --max-samples 32 \
      --run-name cloud-smoke

Then run real training:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --device cuda \
      --precision bf16 \
      --num-workers 8 \
      --batch-size 32

Do not present these worker count or batch-size values as universally optimal.

Document that the user should increase batch size after the first successful run if GPU memory permits.

Resume example:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --device cuda \
      --precision bf16 \
      --num-workers 8 \
      --batch-size 32 \
      --resume data/outputs/run-...

After training, use the existing evaluation commands.

Core ML export still runs on the Mac, not on RunPod.

---

# 15. Do not add Docker yet

Do not create a custom Docker image in this phase.

The repository already pins:

- Python through `mise.toml`;
- `uv`;
- Python dependencies through `uv.lock`;
- the Linux CUDA PyTorch distribution through the new `uv` configuration.

That is sufficient for the first RunPod workflow.

Add Docker only later if repeated pod setup becomes a material problem or if training becomes part of an automated service.

---

# 16. Tests

Add or extend tests around the new behavior.

## Runtime options

Verify:

- config batch size is used by default;
- CLI batch size overrides it;
- default worker count is zero;
- explicit worker count is propagated;
- CUDA implies pinned memory;
- CPU/MPS do not use pinned memory.

Do not require real CUDA for these unit tests.

## Precision

Verify:

- FP32 remains the default;
- BF16 is rejected on non-CUDA devices;
- precision metadata is persisted.

Keep actual CUDA autocast as a cloud smoke test rather than a CI requirement.

## Checkpoints

Verify new checkpoints contain:

    model_state
    optimizer_state
    epoch
    stage
    stage_epoch
    config
    split
    runtime
    metrics

Existing inference/evaluation checkpoint loading must continue to work.

## Resume

Create a small test setup using the existing training fixtures.

Verify:

1. stop after an early epoch;
2. resume from `last.pt`;
3. previous metric rows remain;
4. training continues at the next epoch;
5. completed epochs are not rerun;
6. the existing best checkpoint participates in later best-checkpoint selection;
7. config/split incompatibility fails early.

Avoid depending on pretrained model downloads in tests.

---

# 17. Verification

Local verification:

    cd card_event_net

    uv sync --frozen
    uv run pytest
    uv run ruff check .

Run the existing small CPU/MPS training smoke test.

Verify that existing:

    infer
    evaluate
    baseline
    mine-hard-negatives
    export-coreml

continue to load checkpoints produced by the changed trainer.

Cloud verification requires one real NVIDIA GPU.

Run:

    uv sync --frozen

Confirm CUDA detection.

Then:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --device cuda \
      --precision bf16 \
      --num-workers 4 \
      --max-samples 32 \
      --run-name cuda-smoke

Acceptance requires:

- CUDA is used;
- BF16 autocast works;
- training finishes;
- validation finishes;
- `last.pt` exists;
- `best.pt` exists;
- `environment.json` identifies the GPU;
- metrics contain timing/throughput;
- the resulting checkpoint can be evaluated.

Then interrupt a longer training run after at least one completed epoch and resume it.

Verify that no completed epoch is repeated.

---

# 18. Performance follow-up

Do not optimize further until the first cloud run provides measurements.

For one representative training run, compare:

    num_workers = 0
    num_workers = 4
    num_workers = 8

and at least two batch sizes.

Use `train_samples_per_s` as the primary throughput measurement.

If a fast GPU remains under-utilized after multi-worker loading, investigate the cached-JPEG input path next.

Possible later optimization:

    CachedFrameStore
        -> bounded per-worker decoded-frame LRU cache

because neighboring causal clips reuse many of the same cached frames.

Do not implement this preemptively.

Do not change to LMDB/WebDataset unless profiling shows that filesystem/JPEG decoding remains a significant bottleneck.

---

# 19. GPU selection

Do not encode a required GPU model into the software.

Minimum target:

    one modern NVIDIA CUDA GPU

For the current MobileNetV3-Small model, start with an RTX 4090-class instance.

Use an RTX 5090 when:

- it is readily available;
- the price difference is acceptable;
- profiling shows that training is GPU-bound after fixing the DataLoader.

The pipeline must work unchanged on either GPU.

Do not add H100/A100-specific functionality.

---

# 20. Completion criteria

This phase is complete when:

1. the existing macOS workflow still works;
2. `uv sync --frozen` installs an RTX-5090-compatible PyTorch build on Linux;
3. the ordinary `cardevent train` command trains on CUDA;
4. CUDA training supports optional BF16;
5. the DataLoader can use multiple workers and pinned memory;
6. every run records the actual GPU/runtime environment;
7. an interrupted run can resume from `last.pt`;
8. outputs survive pod replacement when the repository/data directory is on persistent storage;
9. a RunPod user can follow `CLOUD_TRAINING.md` from clone to completed training without undocumented setup;
10. no RunPod-specific Python dependency exists in CardEventNet.
