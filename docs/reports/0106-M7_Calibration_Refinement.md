# Epic 0106 M7: calibration refinement preview

M7 is complete. Swift now calculates an immutable calibration preview from a frozen refinement
draft. The draft binds anchors to the base calibration revision and digest, the visible-card
revision and digest, and source-frame digests. A stale base calibration or mismatched frame digest
blocks the preview. The preview returns a candidate fit, fit and alignment measures, gate results,
and the unchanged base lineage. It does not write or replace the base calibration.

Anchor selection follows the Python contract. It excludes ineligible and excluded anchors, checks
pinned conflicts, deduplicates by temporal and spatial bins, ranks operator state, weight class,
confidence, and ID, and caps contributions by source frame and table region. The preview checks the
minimum anchor count, fit residual, held-out alignment change, and reviewed and proposed scene
displacement limits.

The frozen Python fixture covers the eligible anchors, weighted candidate fit, five gate values,
mapped image landmarks, and duplicate-anchor selection. The Swift mapped landmarks differ from the
Python fixture by at most 0.1 table units. The measured difference on this fixture is about 0.078
table units. The residual and held-out alignment gates pass. The fixture also covers a blocked
insufficient-anchor result. Separate tests cover stale calibration lineage and verify that the base
calibration digest stays unchanged after a preview.

This is calculation evidence. It does not qualify detector quality or accept a proposed calibration
for downstream use. Scene displacement is returned for review; a preview does not update stored
scenes.

## Verification

- `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path ios` passed
  144 tests with one optional frozen-model parity test skipped.
- Focused `DeviceRecordingCalibrationTests` passed 13 tests.
- `xcodebuild test` on the booted iPhone 18 Pro simulator passed the app test scheme.
- `swift-format lint --strict` and `git diff --check` passed.
