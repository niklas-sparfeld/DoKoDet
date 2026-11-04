# Epic 0106 M5: robust table-plane fit

M5 adds a deterministic Swift fit candidate from weighted card-boundary samples. It optimizes the
shared projective transform and per-card table poses with bounded damped least squares and a Huber
loss. It reports per-observation residuals, inliers, rejected observations, fit quality, and the
convergence reason. It refits after it rejects an outlier.

The fit validates quadrilaterals, boundary samples, weights, and finite transforms. It rejects empty
input and invalid weights. The result is a candidate only. M6 owns recording-level selection and
publication gates.

## Python fixture parity

The fixed fixture uses nine projected cards under one perspective transform. The Swift homography
matches the Python `fit_table_plane` result within `1e-5` per matrix entry. The median normalized
boundary residual matches within `1e-4`. Both accept all nine observations and pass the fit-quality
gate. A second fixture shrinks one observed boundary; the fit rejects observation 4 and refits the
remaining eight observations.

## Verification

- Focused table-plane geometry tests: 8 passed.
- Full iOS Swift package tests: 131 passed, 1 optional RF-DETR reference parity test skipped because
  `DEVICE_VISIBLE_CARD_REFERENCE_ROOT` was not set.
- Xcode app tests passed on the iPhone 18 Pro simulator with iOS 27.2.
- `swift-format lint --strict` passed for the fit implementation and tests.
- `git diff --check` passed.
