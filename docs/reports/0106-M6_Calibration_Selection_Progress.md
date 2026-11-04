# Epic 0106 M6: recording calibration selection progress

This report records an incomplete M6 implementation. The Swift package now has a deterministic
recording-level selector around the M5 fit candidate. It checks recording dimensions and source
transform identity, confidence, held-out geometry, time, position, and orientation diversity. It
returns an in-memory calibration only when its gates pass. It does not write a calibration
revision.

## Verification

- The synthetic twelve-card case publishes a finite transform and preserves the visible-card
  revision identifier and frame dimensions.
- Empty input does not publish. Changed frame geometry throws an explicit input error.
- All Swift package tests pass: 134 passed, one optional RF-DETR parity test skipped in the
  full-suite invocation because the reference root was not set.
- The optional RF-DETR parity test was then run with
  `DEVICE_VISIBLE_CARD_REFERENCE_ROOT=/Users/niklas.sparfeld/Developer/doko_detector` and passed
  all six frozen frames. Above-threshold masks matched every reference mask with minimum IoU
  greater than 0.9999. One small frame-70s score and box difference remained; the test accepts it.
- The iOS app test scheme built and ran on the iPhone 18 Pro simulator with iOS 27.2.
- Swift format lint and `git diff --check` passed.

## Remaining M6 work

This is not the `card_plane_calibration.py` port and does not meet M6 acceptance yet. The Python
selector derives candidate quality and boundary samples from segmentation masks, applies frame,
overlap, scale, and grouped-bin filters, and records candidate receipts, diagnostics, schema
versions, digests, and publication lineage. The current Swift selector receives already formed
quadrilaterals and uses confidence as its fit weight. It does not produce those diagnostics or
serialized revisions.

The fixed Python calibration fixture publishes after it rejects `candidate-011` during quality
selection. The current Swift test does not reproduce that decision or compare the published matrix
with Python. Complete those parity gaps before marking M6 complete or using this output downstream.
