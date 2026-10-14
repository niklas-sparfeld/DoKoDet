# Epic 0094 M5 targeted encoder adaptation

Date: 2026-10-14. This report records the bounded adaptation implementation. It does not claim
model quality or pretrained-model feasibility.

## Implemented

- Training supports the `last_two_blocks` recipe. It unfreezes only the final two encoder blocks,
  the final normalization layer, and the 25-class identity head. Earlier encoder parameters stay
  frozen.
- The encoder learning rate is 0.1 times the head learning rate. `CosineAnnealingLR` advances once
  per optimizer step.
- Checkpoint v3 stores model, optimizer, scheduler, sampling, progress, and random state. Resume
  rejects a different encoder recipe or other frozen input.
- Adapted training requires batch size 1. Run records include device, precision, input size, step
  limit, trainable encoder parameter names, optimizer groups, and scheduler budget.

## Verification

- The DINOv3 training, bundle, bundle-contract, and local-identity suites passed: **51 passed**.
- Fixtures verify the exact trainable parameter set, finite gradients in selected encoder layers,
  unchanged frozen parameters, and matching model and scheduler states after interrupted resume.
- Ruff lint and format checks and `git diff --check` passed.
- Verification used a generated CPU encoder fixture. It did not train the materialized pretrained
  encoder or measure its memory use. The adapted recipe caps batch size at 1; local memory and
  throughput feasibility remain unmeasured.
