# Epic 0076 M0 frame-complete calibration candidates

## Result

Automatic calibration now checks each selected observation's projected full-card outline against
the source frame. If any corner falls outside the frame, the processor records `frame_boundary`,
removes the observation from the fit and holdout population, and repeats the fit. The processor
recipe schema is now v5. The occlusion eligibility checks are unchanged.

The new regression case uses a detector polygon that is fully inside the frame but whose projected
full-card outline crosses the left edge. The candidate is rejected and is absent from both the fit
and holdout IDs.

## Frozen 0075 comparison

Reproduce the comparison from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0076-m0-baseline.json
```

The before-and-after comparison used the same frozen manifest digest:
`dd5509857ef69fbf391700623dea77b9780feeed0f9e77821d67ee9236627132`.

| Measure | Before | After |
| --- | ---: | ---: |
| Retained local results | 24 | 24 |
| Local results published | 0 | 0 |
| Selected local candidates | 748 | 708 |
| `frame_boundary` rejections | 470 | 510 |
| Local results with fewer selected candidates | — | 15 / 24 |
| Mean fit median boundary error | 1.263 px | 1.229 px |
| Mean fit P90 boundary error | 2.360 px | 2.263 px |
| Fit outlier count | 64 | 39 |
| Mean held-out median boundary error | 2.705 px | 2.431 px |
| Mean held-out P90 / short-side fraction | 0.1312 | 0.1164 |
| Runs passing held-out boundary gate | 4 / 24 | 5 / 24 |
| Runs passing spatial coverage gate | 18 / 24 | 9 / 24 |
| Mean / maximum local call time | 2.490 s / 7.788 s | 3.307 s / 8.236 s |

The boundary fit errors improve on average, and one more result passes the held-out boundary gate.
The spatial coverage gate passes on nine fewer results because the processor removes observations
near the image boundaries. The runtime remains below the frozen 10-second limit. All 24 local runs
still fail publication because they have no independent full-card outlines. Their boundary errors
measure fit consistency against detector output, not true card-outline accuracy.

The ten frozen known-geometry synthetic cases have unchanged candidate counts and outline metrics.
The new regression case covers an inset detector polygon whose full-card projection leaves the
frame. All ten frozen synthetic runs remain repeatable.

## Verification

- Calibration and calibration-refinement tests: 35 passed.
- Ruff lint and formatting checks pass for the changed Python files.
- The frozen comparison completed for all 24 local revisions and ten synthetic cases.
- `git diff --check` passes.
