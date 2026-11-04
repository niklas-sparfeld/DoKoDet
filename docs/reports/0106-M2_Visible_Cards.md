# Epic 0106 M2: visible-card proposals on iOS

Date: 2026-11-04

## Result

M2 adds an iOS stage for event-frame extraction and RF-DETR proposals. It reads the finalized
recording, event proposal file, and capture timeline. It selects the nearest recorded presentation
time to each event peak. An equal-distance tie selects the earlier frame. A frame farther than
0.125 seconds fails that event.

The stage applies the video track transform once. It writes each transformed event frame and its
SHA-256 digest. It runs the frozen Core ML model with RGB 432×432 bilinear resize, no antialias,
and ImageNet normalization. It retains the 200 highest scoring query/class candidates, then keeps
class 0 (`visible_card`) and class 1 (`card_pile`) detections above score 0.5. It resizes mask
logits with bilinear interpolation and accepts mask pixels above zero. It stores pixel boxes,
normalized 0–1000 boxes and polygons.

The revision is written atomically to
`.device/stages/visible-cards/revision.json`. Event frames are stored under the same hidden stage
directory. The revision records the source video digest, model package and checkpoint digests,
compiled model directory digest, class map, preprocessing, thresholds, frame mapping, image
provenance, candidate outputs, detections, timings, and failures. Empty events produce a complete
empty revision. A missing frame, model error, or video error produces a retained failed revision.
An interrupted capture produces an interrupted revision.

## Frozen model comparison

The comparison used the six frozen 1920×1080 0103 frames and the checked-in Python reference. The
test checks each PNG digest against the frozen input manifest. Every frame returned 200 candidates.
The threshold-free counts below compare candidate class, score, and normalized box at the same
score rank. They do not match reordered candidates by mask.

| Frame | Rank-wise threshold-free differences | Python detections above 0.5 | iOS detections above 0.5 | Matched masks | Minimum mask IoU |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2 s | 0 | 0 | 0 | 0 | n/a |
| 8 s | 7 | 4 | 4 | 4 | 0.9999769 |
| 12 s | 3 | 2 | 2 | 2 | 1.0000000 |
| 20 s | 7 | 3 | 3 | 3 | 1.0000000 |
| 40 s | 2 | 1 | 1 | 1 | 1.0000000 |
| 70 s | 175 | 4 | 4 | 4 | 0.9999828 |

All 14 above-threshold masks matched by class at IoU ≥0.5. No threshold decision or detection
count changed. The score and box comparison passed for 13 detections. One 70-second score was
`0.9152790904` on iOS and `0.9149074554` in the Python reference. Its normalized box differences
were within `1e-4`; its score difference was outside the `1e-4` absolute and relative tolerance.
This score is close to the previously recorded CPU-only difference. The test allowed CPU and GPU
execution; it did not identify which compute unit ran the model. The RF-DETR parity gap remains.

The Python reference does not contain frozen input tensor digests. The comparison therefore checks
the source PNG bytes and dimensions, then compares model candidates and outputs. The many
threshold-free rank differences are retained as diagnostics. They do not establish additional
accepted detections or model quality.

## Reproduction

Prepare the ignored model input before the first Xcode build:

```sh
python3 scripts/0106_m2_prepare_ios_rfdetr.py
```

Run the frozen parity test from `ios/`. Set `DEVICE_VISIBLE_CARD_REFERENCE_ROOT` to a checkout
that has the ignored `.runtime/0103-m0` and `.runtime/0104-m1` inputs.

```sh
DEVICE_VISIBLE_CARD_REFERENCE_ROOT=/path/to/checkout-with-runtime \
  DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  swift test --filter VisibleCardReferenceParityTests
```

The full package suite passed 123 tests with the frozen parity test skipped when its runtime path
was not set. The explicit frozen parity test passed on the Mac. The generic iOS app build passed
with code signing disabled. Simulator tests were not run because the installed CoreSimulator is
older than the version required by Xcode. No iPhone run or model-quality claim was made.
