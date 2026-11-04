# Epic 0106 M4: deterministic calibration seed

M4 adds the deterministic `initial_image_to_table` seed selection to the iOS package. It orders
each input quadrilateral, tests both short-edge orientations, maps each seed card to the canonical
table-plane card rectangle, and selects the transform with the lowest median card residual.

The API returns the homography, selected observation and orientation, and median residual. This is
only an initializer for later fitting. It does not use boundary samples, refine the homography,
select calibration candidates, or publish a recording calibration.

## Fixture parity

The frozen fixture contains four projected cards under one perspective transform. Swift selected
observation 0 and orientation 0. The matrix matched the Python OpenCV seed within `2e-6`; the median
residual matched within `2e-6`. Python uses a float32 perspective solve, while the iOS initializer
uses a float64 linear solve. Both produced the same candidate decision.

Empty input and malformed quadrilaterals return explicit errors.

## Verification

- Focused geometry tests: 5 passed.
- Full Swift package tests: 128 passed, 1 optional RF-DETR reference parity test skipped because
  `DEVICE_VISIBLE_CARD_REFERENCE_ROOT` was not set.
- `swift-format lint --strict` passed for the changed Swift source and tests.
- `git diff --check` passed.

M5 adds the robust boundary fit. M6 adds recording-level candidate selection and publication gates.
