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
- `operations/tests/test_dinov3_identity_campaign.py`: 7 passed.
- Ruff checks and `git diff --check`: passed.
- The full training/export/runtime integration modules were skipped because PyTorch is not
  installed. Transformers is also absent. The local materialized DINOv3 weights are not present at
  `data/models/dinov3-vits16-pretrain-lvd1689m`, so a batch-one real-backbone latency and memory
  smoke could not run on this host.

M1 remains in progress until the real local-backbone smoke can run with the declared optional
runtime and materialized licensed weights. No model weights were downloaded or modified.
