# 0106 M9 — Joint card-scene fitting

## Result

The iOS package now ports the bounded joint pose and stacking-order search from
`card_scene_joint_fit.py`. It uses a width-three, two-round beam. It supports up to eight cards.
It also refines selected visible card edges at quarter resolution. The refinement uses a 32 source
pixel occlusion margin and one-degree angle steps.

The fitter records the baseline score, final score, beam score before edge refinement, margin and
margin stage, elapsed time, and an estimated mask working set. It preserves the original pose and
order when the beam margin is below 0.005. It does not turn uncertain overlap evidence into a fixed
order. A scene with more than eight cards returns `skipped_card_limit` and keeps the input scene.

## Python comparison

The deterministic two-card edge-refinement fixture uses the same calibration, initial poses,
candidate masks, order, and movable-card constraint in Swift and Python. Both return the order
`pose-b`, `pose-a`, refine `pose-a`, and keep `pose-b` unchanged. Python keeps the refined angle at
8 degrees. Swift selects 9 degrees, a one-degree difference.

| Metric | Python | Swift | Difference |
| --- | ---: | ---: | ---: |
| Final score | 0.680252 | 0.692331 | 0.012079 |
| Beam margin | 0.064799 | 0.043022 | 0.021777 |
| Refined center x | 4.247567 | 4.222810 | 0.024756 |
| Refined center y | 3.034793 | 3.031314 | 0.003479 |
| Refined angle | 8 degrees | 9 degrees | 1 degree |

The fixture accepts a 0.03 score and margin difference, a 0.05 table-unit center difference, and a
one-degree angle difference. The existing identical-overlap fixture returns the same saved order,
no pose changes, and a zero margin in both implementations. The non-overlap scene remains
unchanged. A nine-card scene is skipped.

## Runtime and memory

The optimized Swift package test ran on the local arm64 Mac with the Release configuration. The
joint fit took 1.40 seconds in the fixture. XCTest measured 1.38 seconds and a 9,553 kB peak
physical footprint for the test process during the fit measurement. The fitter's mask-buffer
estimate for this fixture was 452,040 bytes. The peak figure includes the XCTest process and is not
an iPhone memory measurement.

The app builds for the installed iPhone 18 Pro Simulator on iOS 27.2. The joint-fit XCTest belongs
to the Swift package test target, which runs on macOS; the app test scheme does not include this
core test. This phase therefore does not claim Simulator runtime or memory results.

## Verification

- `swift test -c release --package-path ios`: 149 tests passed; one optional frozen detector parity
  test skipped because `DEVICE_VISIBLE_CARD_REFERENCE_ROOT` was unset.
- `xcodebuild build -project ios/CardEventProbe.xcodeproj -scheme CardEventProbe -destination
  'platform=iOS Simulator,id=3FB88935-F247-48C2-B856-286D15957E77' -quiet`: passed.
- `swift-format lint --strict` on the changed Swift files and `git diff --check`: passed.

This is a geometry implementation result. It does not qualify detector accuracy or production use.
