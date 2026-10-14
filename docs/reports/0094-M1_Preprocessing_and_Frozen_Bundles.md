# Epic 0094 M1 preprocessing and frozen bundle verification

Date: 2026-10-14. This report records the M1 software implementation and local verification. It
does not claim model quality or campaign performance.

## Implemented

- Identity configs use `dinov3-identity-config/v2` and declare one explicit frozen CLS recipe with
  input size 224, 384, or 448.
- Preprocessing uses the declared Lanczos letterbox size, stable RGB 128 fill, and pinned
  normalization. Its digest covers the transform version and full processor config.
- Training and inference pass the resolved size to the same crop transform. The output records its
  size, shape, pixel digest, and processor digest.
- Frozen bundles use `dinov3-identity-bundle/v3`. Their manifest and linear head record the recipe,
  target-map, and transform digests. Bundle loading rejects digest or head/recipe mismatches.
- Campaign preflight records the resolved recipe and checks the new config contract.

## Verification

- `test_local_identity.py` and `test_dinov3_bundle_contract.py`: 25 passed. The fixtures cover all
  three sizes, finite CHW values, deterministic pixels, config round trips, and model-free bundle
  reload and digest rejection.
- The full `test_dinov3_bundle.py` and `test_dinov3_training.py` suites passed in the configured
  project environment. They exercise train, export, reload, evaluation, and runtime with injected
  fixture encoders.
- `operations/tests/test_dinov3_identity_campaign.py`: 7 passed.
- Ruff checks and `git diff --check`: passed.
- The local materialized weights and existing accepted license record passed all three declared
  file-digest checks. No pretrained file or source config was changed.
- Batch-one MPS smoke at 384 pixels passed with feature shape `(1, 384)` and finite values. After
  one warm-up forward, the measured forward took 19.77 ms. MPS reported 84.93 MiB current allocated
  and 146.69 MiB driver allocated after the measured forward.

The timing and memory values are feasibility evidence for this host only. They do not measure
classifier quality or claim campaign performance.
