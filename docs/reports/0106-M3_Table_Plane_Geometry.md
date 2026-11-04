# Epic 0106 M3: table-plane geometry primitives

Date: 2026-11-04

## Result

M3 adds portable geometry primitives to the iOS package. It defines the frozen card aspect ratio,
source-pixel/table-plane coordinate system, corner order, and angle convention. It applies and
inverts validated 3×3 homographies, orders quadrilateral corners, calculates card edge vectors and
geometry residuals, and projects fixed card poses into the source image.

The implementation rejects non-finite input points, malformed or singular transforms, invalid card
dimensions and rotations, degenerate quadrilaterals, and projected points at infinity. An empty
point list maps to an empty list. These types do not publish calibration or scene results.

The fixture `ios/CardEventProbeTests/Fixtures/table_plane_geometry_v1.json` was generated from the
Python `card_plane_geometry.py` implementation. It freezes projected points, inverse results, corner
ordering, card pose vectors, residuals, and projected card corners. The Swift tests compare these
results at tight numerical tolerances and cover invalid inputs.

## Verification

- `swift test --filter DeviceCardPlaneGeometryTests`: 3 passed.
- Full `swift test`: 126 passed, 1 optional RF-DETR parity test skipped because its runtime
  reference path was not set, 0 failures.

M3 provides the mathematical base for calibration. It does not establish recording calibration,
scene quality, or iPhone runtime performance. M4 ports the recording-wide fit and its publication
gates.
