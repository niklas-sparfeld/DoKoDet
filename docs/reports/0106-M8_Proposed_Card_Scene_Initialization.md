# Epic 0106 M8: Proposed card scene initialization

Date: 2026-11-05

## Result

The iOS core now builds calibration-backed scene proposals for every input frame. Each result keeps
the visible-card revision, its digest, the calibration revision and digest, and the source frame
digest. A stale detector revision or mismatched frame size blocks the run.

The initializer maps detector polygon points to table coordinates and fits a fixed-card rectangle
with a minimum-area search. It rejects candidates whose rectangle aspect ratio is outside the
configured gate. A frame keeps successful poses when another candidate fails. Empty frames,
detector failures and partial frames have separate outcomes.

For overlapping poses, the initializer compares visible polygon area inside the projected overlap.
It keeps weak relations as uncertain evidence. It does not assign a front-to-back relation when the
support difference is below the gate.

## Python comparison

The fixed fixture [proposed_card_scene_python_v1.json](../../ios/CardEventProbeTests/Fixtures/proposed_card_scene_python_v1.json)
uses a calibration and two overlapping full-card polygons from the Python initializer. The iOS
result matches the Python frame outcome and uncertain order decision. Pose centers are within 0.03
table units, angles are within 0.7 degrees, and fit residuals and overlap support are within 0.02 of
the fixture values.

The initializer uses polygon geometry and a minimum-area rectangle. It does not port the Python
pixel-mask scoring, occlusion refit or joint pose search. It can mark clipped or otherwise
non-rectangular candidates unsupported. M9 owns bounded joint fitting for overlapping scenes.
These outputs remain proposals and do not qualify the detector.

## Verification

- `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path ios`: 147 passed, 1 optional frozen-model parity test skipped.
- Three focused proposed-scene tests passed for Python fixture parity, empty and failed frames, partial candidates, ambiguous overlap and stale detector lineage.
- `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun swift-format lint --strict` passed on the changed Swift files.
- `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild test -quiet -project ios/CardEventProbe.xcodeproj -scheme CardEventProbeAppTests -destination 'platform=iOS Simulator,id=3FB88935-F247-48C2-B856-286D15957E77'` passed on the iPhone 18 Pro Simulator (iOS 27.2).
