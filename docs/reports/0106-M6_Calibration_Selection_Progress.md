# Epic 0106 M6: recording calibration selection

M6 is complete. Swift now selects and validates a recording calibration from an exact frozen
`DeviceVisibleCardRevision`. It keeps candidate decisions, quality metrics, bins, boundary evidence,
receipt digests, fit membership, held-out membership, failure codes, and publication gates.

The selector reads normalized visible-card polygons from the M2 revision. It reconstructs oriented
quadrilaterals, samples the contour boundary, estimates candidate quality, rejects overlaps and
scale outliers, applies frame/time/position/bin limits, and validates the robust table-plane fit.
It does not change the M2 revision. A failed revision or failed required gate returns diagnostics and
no calibration.

Published values use `table-plane-calibration/v1`, `card-plane-geometry/v6`, the canonical
coordinate and corner conventions, the Python recipe digest, accepted candidate receipt digests, a
deterministic calibration revision ID, and a calibration digest. The Python fixture test compares
receipt hashes, revision ID, decisions, gates, dimensions, status, and matrix behavior. The Swift
fit's matrix coefficients are not byte-identical to Python. Landmark differences stay below 0.002
table units for image-to-table and 0.2 pixels for table-to-image on the fixed fixture.

Quality values derived from M2 use its normalized, integer contour polygon. The frozen Python
fixture also exercises full mask-derived candidate metrics and boundary samples. These checks verify
implementation parity on supplied evidence; they do not qualify RF-DETR quality or replace human
review.

## Verification

- `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path ios` passed
  139 tests with one optional frozen-model parity test skipped.
- `DEVICE_VISIBLE_CARD_REFERENCE_ROOT=/Users/niklas.sparfeld/Developer/doko_detector`
  `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path ios --filter VisibleCardReferenceParityTests`
  passed all six frozen RF-DETR frames. Above-threshold masks matched with minimum IoU 0.999976;
  the known small score/box difference remains on frame 70s.
- `xcodebuild test -project ios/CardEventProbe.xcodeproj -scheme CardEventProbeAppTests` passed
  five app workflow tests on the iPhone 18 Pro simulator running iOS 27.2.
- Focused calibration tests cover Python fixture parity, direct M2 revision selection, publication,
  empty and insufficient input, changed geometry, and wrong revision lineage.
- Swift format lint and `git diff --check` pass.
