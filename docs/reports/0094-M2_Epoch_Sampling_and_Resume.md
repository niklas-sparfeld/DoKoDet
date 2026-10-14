# Epic 0094 M2 epoch sampling and resume verification

Date: 2026-10-14. This report records the M2 sampler and checkpoint changes. The fixture checks
show software reproducibility. They do not measure model quality or campaign performance.

## Implemented

- Training recipes declare `class_source_weighted_with_replacement` and a per-epoch sample budget.
  Campaign recipes use the frozen train-split size as that budget.
- The sampler assigns balanced class quotas for each epoch, then weights crops to balance source
  frames within each class. A stable seed and epoch determine the ordered schedule.
- Run records and checkpoints retain the ordered sample IDs, class and source-frame exposure,
  schedule digest, and next-sample cursor.
- Checkpoint v2 binds the sampler settings to the frozen semantic config. Resume regenerates and
  checks the interrupted epoch schedule before it continues.
- The campaign recipe writer declares the sampling policy so later runs cannot select it from an
  ambient default.

## Verification

- All tests in `test_dinov3_training.py`, `test_dinov3_bundle.py`, and
  `test_dinov3_bundle_contract.py` passed with the configured project environment. They cover seed
  and epoch variation, recorded class/source exposure, interruption and resume, matching ordered
  receipts, and equal final model and optimizer state.
- `operations/tests/test_dinov3_identity_campaign.py`: 7 passed.
- Ruff checks for the changed training and campaign modules passed.
- `git diff --check` passed.

The smoke fixture is intentionally small. It confirms deterministic software behavior only.
