# Epic 0094 M4 alternate frozen features

Date: 2026-10-14. This report records the second frozen feature layout. It does not claim model
quality or compare campaign candidates.

## Implemented

- Identity recipes now select `cls` or `cls_mean_patch`. `cls` remains the default control.
- `cls_mean_patch` concatenates the final CLS token with the mean of final spatial patch tokens.
  The mean excludes CLS and the configured register tokens. The extractor checks the token count
  against the selected input size and patch size.
- The frozen trainer sizes its linear head from the feature layout. Run records and resume
  checkpoints record the layout and head width.
- Bundle export checks the checkpoint head width against the selected layout. Bundle loading and
  local inference enforce the same contract. The local runtime uses the same feature extraction.
- Both layouts use the same transform, target map, frozen encoder, and model-free bundle validation.

## Verification

- The DINOv3 training, bundle, bundle-contract, and local-identity suites passed: **48 passed**.
- Fixtures cover distinct CLS, register, and patch values; register and CLS exclusion; head width;
  frozen encoder and trainable head behavior; all declared input sizes; and layout-aware checkpoint,
  export, reload, and inference behavior.
- Export rejects a checkpoint whose head width does not match its feature layout.
- Ruff checks, formatting, and `git diff --check` passed.
- Verification used injected fixture encoders. No pretrained weights were fitted and no quality or
  runtime-performance claim is made.
