# Epic 0075 M4 failed-fit review

## Result

Failed proposed-card-scene runs now keep projected full-card outlines in their calibration
diagnostics. Generated-result review shows these outlines as dashed orange overlays beside the
detector polygons. A diagnostic panel shows candidate yield, held-out boundary distances, size and
area bias, failed gates, and links to the worst held-out frames. The panel and outlines are
read-only. They do not change the detector result, published calibration, maintained reference, or
dataset inputs.

The calibration processor recipe schema is now v4. The run envelope remains v3.

The overlay uses the projected outline that the calibration validator measured. It does not
estimate a replacement calibration in the browser. Each overlay stays linked to its detector
candidate and source frame. The panel appears only in generated-result review.

## Frozen M0 comparison

Reproduce from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0075-m4-baseline.json
```

The command checked manifest
`dd5509857ef69fbf391700623dea77b9780feeed0f9e77821d67ee9236627132`. The frozen set contains 24
completed local result revisions and ten known-geometry synthetic cases. The local inputs cover
requested-event frames, not full-video scans.

| Measure                                                |         M4 result |         M0 result |
| ------------------------------------------------------ | ----------------: | ----------------: |
| Local results published / failed                       |            0 / 24 |           14 / 10 |
| Failed local results with a fit candidate              |           24 / 24 |            0 / 10 |
| Previously failing results that now publish            |            0 / 10 |                 — |
| Previously failing results that now retain a candidate |           10 / 10 |            0 / 10 |
| Mean / maximum local calibration time                  | 2.471 s / 7.611 s | 0.801 s / 1.701 s |
| Maximum synthetic calibration time                     |           0.602 s |           0.114 s |
| Synthetic repeat-run digests match                     |           10 / 10 |           10 / 10 |

All 24 local results fail publication. Fifteen fail held-out boundary validation, five fail spatial
coverage, two lack independent absolute-size references, one has too few candidates, and one has
inconsistent geometry. Their exact source frames have no independent full-card outlines. The 14
results that published at M0 are now withheld by the absolute-size gate. This follows M3's
publication rule; detector outlines cannot provide independent evidence of their own size.

The local mean and maximum remain below the frozen ten-second limit. The maximum synthetic run
remains below the two-second limit. Nine synthetic cases pass. The uniform 10% shrink case fails
its measurable size gate with −9.77% median short-side bias and −18.77% median area bias. The fit
candidate reports this error and is not published. The pile, partial, weak-mask, outlier, and
clipped-card cases meet their frozen fit checks.

The real-data acceptance gate remains unavailable until independent full-card outlines exist for
the exact retained source frames. The frozen set also does not measure full-video coverage.

## Verification

- `operations/tests/test_card_plane_calibration.py` passes. It checks that a failed run retains
  projected candidate outlines, residuals, and digest-valid run data.
- `backend/tests/test_proposed_card_scene_pipeline.py` passes. It checks that a failed run keeps
  candidate diagnostics in stored metrics, does not publish a proposal revision, and does not
  modify its detector input.
- The M4 UI test passes. It checks diagnostic-only labeling, unavailable size evidence, worst-frame
  navigation, and the projected outline on the selected source frame.
- Web TypeScript type checking, focused ESLint, Ruff lint, Ruff format, and Prettier checks pass.
  Focused ESLint reports one existing hook-dependency warning in the workbench.
- The complete `PipelineVisibleCardEditor.test.tsx` file has 24 failures and 11 passes. The failures
  search for the alt text `Selected visible-card source frame`, while the current camera image in
  the unchanged renderer has `alt=""`. Repo-wide ESLint also reports two existing errors in the
  untouched `CardEventFrameSurface.tsx`. These checks do not fail in the M4 code paths.
- `git diff --check` passes.
