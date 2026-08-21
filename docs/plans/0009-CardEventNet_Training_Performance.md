# CardEventNet Training Performance — Implementation Plan

## Plan status

- Summary: Remove CPU preprocessing bottlenecks and improve GPU utilization
- Status: Done

## Purpose

The current cloud training pipeline is CPU-bound.

`CausalClipDataset` currently:

1. reads eight JPEG frames;
2. converts BGR to RGB;
3. creates uint8 tensors;
4. converts them to FP32;
5. applies training augmentation;
6. applies ImageNet normalization;
7. returns the resulting FP32 clip to the DataLoader.

Only after this work does `train.py` copy the batch to CUDA or MPS.

On a fast GPU this leaves the GPU waiting for DataLoader workers.

Change the pipeline to:

    JPEG read/decode
      -> uint8 [B, T, C, H, W]
      -> transfer to selected device
      -> augmentation on selected device
      -> normalization on selected device
      -> model

This must remain device-neutral:

    CUDA -> augmentation on CUDA
    MPS  -> augmentation on MPS
    CPU  -> augmentation on CPU

Do not introduce a separate CUDA training path.

Run all commands in this plan from `card_event_net/`.

---

# 1. Keep the dataset responsible only for data loading

Modify:

    src/cardevent/dataset.py

`CausalClipDataset` must stop applying `ClipTransform`.

Remove the `transform` constructor argument and the stored transform.

Current conceptual behavior:

    read JPEGs
      -> stack uint8 clip
      -> ClipTransform
      -> return FP32 normalized clip

New behavior:

    read JPEGs
      -> stack uint8 clip
      -> return uint8 clip

`__getitem__()` must return:

    clip:  [T, C, H, W], torch.uint8
    label: scalar torch.float32

For the normal configuration:

    [8, 3, 224, 224]

Do not change:

- frame selection;
- causal sampling;
- cached JPEG format;
- OpenCV decoding;
- RGB channel order;
- label semantics.

The DataLoader workers should primarily perform file I/O and JPEG decoding.

---

# 2. Make `ClipTransform` batch-aware

Modify:

    src/cardevent/transforms.py

Keep `ClipTransform` as the common preprocessing implementation.

It must support:

    [T, C, H, W]

and:

    [B, T, C, H, W]

The 4D form is useful for inference and unit tests.

The 5D form is the normal training path.

Input may be uint8.

Output must be normalized FP32.

Conceptually:

    uint8
      -> float32 / 255
      -> augmentation if training
      -> ImageNet normalization
      -> float32

Do not perform augmentation under BF16 autocast.

---

# 3. Preserve temporal augmentation consistency

This requirement must not change.

For one clip:

    [T, C, H, W]

sample augmentation parameters once and apply exactly the same parameters to all T frames.

Different clips within a batch must still receive independently sampled augmentation parameters.

For example:

    clip 0:
        flip=true
        brightness=1.08
        contrast=0.94

    clip 1:
        flip=false
        brightness=0.91
        contrast=1.04

Within clip 0, all eight frames use the first configuration.

Do not sample random parameters independently per frame.

Preserve the current augmentation distribution:

- horizontal flip;
- brightness jitter;
- contrast jitter;
- saturation jitter;
- small hue jitter;
- occasional Gaussian blur.

Preserve ImageNet normalization.

---

# 4. Avoid frame-by-frame transform execution

The current `ClipTransform` loops over each frame and invokes torchvision operations separately.

Remove this frame loop.

At minimum, apply an operation to the complete clip:

    [T, C, H, W]

because torchvision/PyTorch tensor operations can process the temporal dimension as a leading dimension.

For batched training, prefer operations over:

    [B, T, C, H, W]

where practical.

Per-clip random parameters make some transforms harder to vectorize across B.

Implement the simplest correct device-side version first.

A temporary Python loop over B is acceptable if each iteration processes the complete:

    [T, C, H, W]

clip on the selected device.

Do not retain a loop over individual frames.

After implementation, profile before introducing custom vectorized color-space operations.

Correctness and identical temporal semantics are more important than eliminating every Python loop in this phase.

---

# 5. Move transforms after device transfer

Modify:

    src/cardevent/train.py

`_make_loader()` must construct `CausalClipDataset` without a transform.

Create the appropriate transforms in the training process:

    train_transform = ClipTransform(training=True)
    eval_transform = ClipTransform(training=False)

The training loop currently performs:

    clips = clips.to(
        device=device,
        dtype=torch.float32,
        non_blocking=runtime.pin_memory,
    )

Change this to preserve uint8 during transfer:

    clips = clips.to(
        device=device,
        non_blocking=runtime.pin_memory,
    )

Then:

    clips = train_transform(clips)

Then enter the existing autocast context for model execution:

    with _autocast_context(device, runtime):
        logits = model(clips)
        loss = criterion(logits, labels)

The conceptual order must be:

    DataLoader uint8
      -> H2D/MPS transfer
      -> FP32 augmentation + normalization
      -> BF16 autocast if configured
      -> model

Do not perform color augmentation in BF16.

---

# 6. Update validation the same way

Modify `_evaluate_validation()`.

Validation DataLoaders must also return uint8 clips.

For every batch:

    uint8 batch
      -> selected device
      -> ClipTransform(training=False)
      -> model

`training=False` must perform only:

- uint8 -> FP32 conversion;
- scaling to [0, 1];
- ImageNet normalization.

No random augmentation may occur during validation.

Keep existing BF16 model autocast behavior on CUDA.

---

# 7. Update all other dataset/transform consumers

Search the repository for:

    CausalClipDataset(
    ClipTransform(

Review every call site.

Any code that previously relied on `CausalClipDataset` returning normalized FP32 data must explicitly apply the evaluation transform before model execution.

This includes training validation and any evaluation/inference paths using the dataset directly.

Do not move normalization into `CardEventNet` itself.

The model must continue to receive the same normalized representation as before.

Do not change Core ML model semantics.

---

# 8. Preserve pinned-memory and asynchronous transfer behavior

Keep the current CUDA behavior:

    pin_memory=True

when CUDA is selected.

Keep:

    non_blocking=True

for transfers from pinned host memory.

The important change is that the transferred clip is now uint8 instead of FP32.

For a normal image tensor this reduces host-to-device data size by approximately 4x:

    uint8   = 1 byte/value
    float32 = 4 bytes/value

Do not enable pinned memory for CPU or MPS.

---

# 9. Keep the existing BF16 implementation

Do not redesign precision handling.

The current behavior is correct:

    --precision bf16

is allowed only on CUDA devices that report BF16 support.

Keep augmentation and normalization outside autocast.

Use BF16 only for the model/loss region.

Do not add:

- FP16;
- GradScaler;
- TF32 controls;
- CUDA-specific model code.

---

# 10. Retain DataLoader multiprocessing

Keep the existing runtime options:

    --num-workers
    --batch-size
    --precision

Keep:

    persistent_workers=True
    prefetch_factor=2

when workers are enabled.

Keep worker seeding unless it becomes clearly unused.

After this change the workers still perform the expensive JPEG decode, so multiple workers remain useful.

Do not change the default worker count in this phase.

Cloud documentation should explicitly recommend setting it.

---

# 11. Preserve local macOS training

The same training code must work with:

    --device mps

The pipeline should become:

    CPU DataLoader
      -> uint8
      -> MPS
      -> ClipTransform
      -> CardEventNet

Do not add CUDA-specific augmentation libraries such as:

- NVIDIA DALI;
- Kornia CUDA-only assumptions;
- custom CUDA extensions.

Use ordinary PyTorch/torchvision tensor operations.

If an exact torchvision operation proves unsupported by MPS, first replace it with an equivalent portable PyTorch implementation.

Only fall back to CPU preprocessing for MPS if a portable implementation is not practical.

Do not silently move individual tensors between MPS and CPU inside `ClipTransform`.

---

# 12. Tests

Update dataset tests.

Verify that `CausalClipDataset`:

- returns shape `[8, 3, 224, 224]`;
- returns `torch.uint8`;
- preserves RGB ordering;
- performs no normalization;
- performs no random augmentation.

Update transform tests.

Verify:

### Evaluation transform

For uint8 input:

    [T, C, H, W]

and:

    [B, T, C, H, W]

the result is:

- FP32;
- same shape;
- correctly ImageNet-normalized.

### Temporal consistency

Use a clip containing identical frames.

With training augmentation enabled, all output frames in that clip must remain identical.

This verifies that random parameters are shared across T.

### Batch independence

Verify that separate clips can receive separate augmentation configurations.

Use an injectable/fixed RNG where necessary to make this deterministic.

### Device behavior

CPU tests are mandatory in CI.

Add optional tests that run when available:

    CUDA
    MPS

They should confirm that:

    output.device == input.device

and no implicit CPU copy occurs.

Do not require CUDA or MPS for the normal test suite.

---

# 13. Training smoke tests

Keep the existing small training fixtures.

Verify an FP32 CPU training smoke test still completes.

Verify:

- loss can be calculated;
- backward pass works;
- validation works;
- checkpoints are written;
- resulting checkpoints load through existing evaluation/inference code.

On macOS, manually smoke-test:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --device mps \
      --max-samples 32

On RunPod, smoke-test:

    uv run cardevent train \
      --config configs/base.yaml \
      --split data/splits/default.yaml \
      --cache-dir /tmp/cardevent-cache \
      --device cuda \
      --precision bf16 \
      --num-workers 8 \
      --batch-size 128 \
      --max-samples 128 \
      --run-name device-transform-smoke

---

# 14. Performance verification

Use the same prepared cache and split before and after the change.

Run from local pod storage, not directly from the network volume.

Compare:

    train_samples_per_s

from `metrics.jsonl`.

Also observe:

    watch -n 1 nvidia-smi

and:

    htop

Expected result:

- less CPU time in augmentation;
- DataLoader workers spend most of their time reading/decoding JPEGs;
- lower host-to-device bandwidth requirement;
- higher GPU utilization;
- higher samples/second.

Do not define success as 100% GPU utilization.

The primary metric is training throughput.

---

# 15. Tune worker count after the change

Once device-side transforms work, measure:

    --num-workers 4
    --num-workers 8
    --num-workers 16

depending on available pod CPU cores.

Use:

    nproc

to inspect available CPUs.

Stop increasing workers once `train_samples_per_s` no longer improves.

Do not automatically derive worker count from CPU count yet.

---

# 16. Do not increase batch size purely to fill the GPU

Batch size affects optimization behavior.

Use a practical starting point such as:

    64
    128

Benchmark larger values separately.

Do not encode an RTX-specific batch size in configuration.

The pipeline must remain usable on smaller GPUs and on MPS.

---

# 17. Keep the current JPEG cache for this phase

Do not change:

    data/cache/<video>/frames/*.jpg

in this implementation.

After device-side augmentation, profile again.

If training remains CPU-bound and DataLoader workers spend most of their time inside:

    cv2.imread
    JPEG decoding

then create a separate follow-up plan for a decode-free training cache.

Likely options include:

- memory-mapped uint8 arrays;
- another packed frame representation.

Do not introduce LMDB, WebDataset, or a custom storage layer without profiling evidence.

---

# 18. Cloud cache staging

Update:

    card_event_net/CLOUD_TRAINING.md

Document that persistent storage and training storage have different purposes.

Persistent network volume:

    repository
    raw videos
    canonical prepared cache
    annotations
    checkpoints / outputs

Local pod storage:

    temporary training copy of data/cache

Document:

    rsync -a --delete data/cache/ /tmp/cardevent-cache/

Training must then use:

    --cache-dir /tmp/cardevent-cache

while outputs remain on:

    /workspace/DoKoDet/card_event_net/data/outputs

The local cache may disappear when the pod terminates.

That is expected.

---

# 19. Completion criteria

This phase is complete when:

1. `CausalClipDataset` returns uint8 clips without augmentation.
2. Training transfers uint8 batches before preprocessing.
3. Training augmentation runs on the selected device.
4. Validation normalization runs on the selected device.
5. Temporal augmentation consistency is preserved.
6. CUDA BF16 still works.
7. MPS local training still works.
8. CPU tests still work.
9. Existing checkpoints remain compatible.
10. Core ML export behavior is unchanged.
11. Cloud training can use `/tmp/cardevent-cache`.
12. RunPod training throughput improves measurably on the same dataset.
13. No CUDA-specific training implementation is introduced.