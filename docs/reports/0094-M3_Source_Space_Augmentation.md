# Epic 0094 M3 source-space augmentation

Date: 2026-10-14.

## Change

- Bumped the frozen augmentation contract to v2. It declares source-crop coordinates, transform
  bounds, mask handling, deterministic random keys, and disabled mirrors.
- Added per-operation random streams derived from seed, epoch, sample ID, and operation.
- Added source-space rotation, brightness, contrast, Gaussian blur, and edge crop before the shared
  resolution-aware letterbox transform.
- Added paired visible-mask transforms. Rotation expands the canvas with stable grey image fill and
  zero mask fill. Cropping rejects views that retain less than 95% of source mask support.
- Training samples can carry visible-mask bytes. Invalid, empty, or misaligned masks fail training;
  they do not change the target to `FACE_DOWN`.

## Verification

- The standalone augmentation fixture passed. It checks deterministic replay, epoch variation,
  aligned image/mask geometry, disabled mirrors, and rejection of empty and mismatched masks.
- Ruff lint and formatting checks passed for the changed Python files.
- The existing training test module skipped during collection because PyTorch is not installed in
  this local environment. The pure Pillow augmentation tests do not need PyTorch.
- `git diff --check` passed.

## Limitation

The generic crop-cache format does not persist visible-mask files. The sampler therefore uses the
declared full-source-crop mask when the crop loader has no mask bytes. A campaign caller that has an
exact reviewed mask can pass it through `LoadedCrop.visible_mask_bytes`; wiring the reviewed DINO
campaign cache to persist and load those masks remains necessary before campaign fits can claim
mask-constrained augmentation.
