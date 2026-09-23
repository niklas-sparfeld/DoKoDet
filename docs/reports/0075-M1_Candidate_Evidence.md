# Epic 0075 M1 candidate evidence

## Result

M1 adds deterministic candidate evidence extraction and ranking to automatic table-plane
calibration. It accepts polygon, mask, and shared visible-region geometry from a local result. The
selector keeps a source revision and frame identity for each raw candidate. It records a decision
and reason, including when it cannot build a quadrilateral.

Each usable candidate now includes 64 boundary samples taken at equal distances along the observed
mask boundary. The candidate receipt records these samples and the measured quality values. This
gives M2 source-pixel boundary evidence without changing the shared fit yet.

## Selection policy

The selector measures mask-to-quadrilateral agreement, mask coverage, convexity, boundary
straightness, corner support, connected-component dominance, overlap, nearby-card distance, and
local apparent card scale. It uses confidence as one part of the quality score:

```text
geometry score = 0.30 IoU + 0.15 coverage + 0.15 convexity
               + 0.20 straightness + 0.10 corner support
               + 0.10 component dominance
quality score  = 0.85 geometry score + 0.15 detector confidence
```

The selector rejects disconnected masks, masks that touch the source-frame border, and masks with
weak quadrilateral support. It rejects a lower-ranked prediction when its quadrilateral overlaps
more than 12% of the smaller prediction. It also rejects a local size outlier when at least three
nearby candidates are available and its log apparent-size deviation is above 0.30.

Selection uses the highest quality score first, then confidence, then candidate ID. It keeps at
most four candidates per source frame, eight per one-second interval, and eight per image region.
Each cap selects the best candidate from different image regions before it fills remaining slots.
It then deduplicates by time, image region, scale, and orientation.

A full boundary near an image edge stays eligible when its mask does not touch the frame border.
Uniform shrink across all candidates remains eligible. M1 cannot distinguish that shrink from a
smaller physical card. The shared fit in M2 must resolve it from complete-card evidence and pass
the frozen size-bias gates. With the unchanged fitter, the shrink case still has median short-side
bias of -10.0379% and area bias of -19.0738%. The clean case remains within its frozen limits. The
2 px noise case has 1.752 px median boundary distance, 7.114% median area bias, and 0.07091 P90
normalized boundary distance.

## Frozen M0 evidence

The selector passed all ten synthetic cases with matching repeat-run digests. The selected and
rejected candidates include:

| Case | M1 result |
| --- | --- |
| Clean isolated cards | 12 of 12 accepted |
| Repeated stationary card | 19 accepted; repeated observations hit the region cap |
| Full cards near the view edge | 12 of 12 accepted |
| Overlapping pile | `pile-card-04b` rejected for overlap |
| Partial card | `card-04` rejected as an apparent-scale outlier |
| Weak mask | `card-05` rejected below the confidence limit |
| Uniform 10% shrink | 12 of 12 retained for the shared fit |
| 2 px boundary noise | 12 of 12 retained |
| Oversized outliers | Both outlier candidates rejected as apparent-scale outliers |
| Clipped card | `card-00` rejected at the frame border |

On the 24 frozen local RF-DETR revisions, the unchanged shared fitter published 15 results and
failed 9. M0 published 14 and failed 10. The mean and maximum calibration call times were 0.787 s
and 1.577 s. These revisions cover requested event frames, not full recordings. The improved
publication count is a local diagnostic only. Independent full-card outlines are still unavailable,
and the real-data acceptance gate remains pending.

The failed local runs still have no inspectable calibration fit candidate. M3 owns that behavior.
The current fitter also does not pass the frozen size-underestimate gate for uniformly shrunken
masks. M2 owns the shared boundary fit and those numerical geometry gates.

## Verification

- 36 focused calibration, geometry, and refinement tests passed.
- Ruff checks and format checks passed for the changed Python files.
- Python compilation passed for the calibration and geometry modules.
- The frozen evaluator produced matching digests in all 10 synthetic cases.
