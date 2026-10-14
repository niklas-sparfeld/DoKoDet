# Epic 0094 M8: Confidence calibration

## Result

The new `calibrate-dinov3-identity` command fits a positive scalar temperature from an explicit
calibration view. The view contains one 25-class logit vector per sample, the reviewed visual target,
and source-lineage-group metadata. It identifies the DINOv3 run and exact best-checkpoint digest.
Calibration fails when the view is empty, a sample ID overlaps the frozen split, or a source group
overlaps the training data set.

The calibration artifact records its source view, checkpoint, temperature, negative log likelihood
before and after fitting, reliability bins, and precision/coverage thresholds. A review threshold is
selected only when the caller supplies a precision target. It routes predictions for human review.
The classifier keeps all ranked candidates and does not create an UNKNOWN class.

Bundle schema v5 includes the digest-checked calibration artifact. Runtime v2 reports raw and
calibrated probabilities, a versioned score record, and FACE_DOWN confidence. Positive temperature
scaling keeps class order unchanged. Temperature 1.0 keeps raw scores unchanged. Paired provider
receipt schema v2 records provider confidence and FACE_DOWN confidence as uncalibrated provider
scores. Evaluation schema v3 reports reliability and precision/coverage, and keeps provider scores
with their reviewed targets.

## Verification

Command, from the repository root:

```text
mise exec -- uv run --project table_evidence_analyzer --group training pytest -q -rA \
  table_evidence_analyzer/tests/test_dinov3_calibration.py \
  table_evidence_analyzer/tests/test_dinov3_bundle.py \
  table_evidence_analyzer/tests/test_dinov3_bundle_contract.py \
  table_evidence_analyzer/tests/test_cli.py
```

The focused fixture suite covers temperature fitting, rank preservation, empty and overlapping
calibration views, checkpoint-bound calibration, export/load score reproduction, T=1 behavior,
FACE_DOWN confidence, candidate retention, and provider score metadata alongside reviewed targets.
Result: 44 passed. Ruff check and format check pass for the changed Python files.

## Limits

The calibration view is supplied as a JSON logits receipt. This milestone does not create a new
calibration crop set or claim calibration quality on real data. It makes no default review policy or
promotion decision. The crop-cache visible-mask limitation remains unchanged. M9 will verify the
complete local train, resume, calibration, export, reload, and classify lifecycle.
