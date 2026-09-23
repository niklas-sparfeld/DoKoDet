# Epic 0078 M0 automatic calibration without a size reference

## Result

Automatic calibration no longer requires independent full-card outlines. The fitted source-image
scale is the automatic estimate. Candidate count, temporal and spatial diversity, fit quality,
and held-out boundary checks still decide publication. The processor version is v9.

When independent outlines are supplied for an evaluation, the processor still reports short-side
and area bias. Those metrics are optional diagnostics. They are not publication gates. Failed-run
review labels this check as an optional size comparison.
The reference input digest is part of the immutable calibration revision ID, so runs with and
without optional comparison data can both be stored.

## Frozen comparison

Reproduce the comparison from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0078-no-size-gate.json
```

Both runs used frozen manifest digest
`dd5509857ef69fbf391700623dea77b9780feeed0f9e77821d67ee9236627132`.

| Measure | Before M0 | After M0 |
| --- | ---: | ---: |
| Retained local results | 24 | 24 |
| Published local calibrations | 0 | 4 |
| Results passing held-out boundary gate | 6/24 | 6/24 |
| Results passing spatial coverage gate | 9/24 | 9/24 |
| Results passing fit quality gate | 22/24 | 22/24 |
| Results failing spatial coverage first | 14 | 14 |
| Results failing held-out boundaries first | 5 | 5 |
| Results blocked only by missing size reference | 4 | 0 |
| Mean / maximum local call time | 3.776 s / 13.071 s | 3.756 s / 12.791 s |

The inspected `visible-cards-visible_cards-run-f678d010-5a3-attempt-1` still fails spatial
coverage and held-out boundaries. Removing the size gate does not change its calibration status.
The four newly published revisions are `5bd52a7b-3ba`, `7b9b84c7-2ab`, `c341e308-722`, and
`cdf105b9-7b2` (all `visible-cards` runs with `attempt-1`).

All ten frozen synthetic cases now publish. The known 10% shrink case still reports a failed
optional size comparison: short-side bias is below -8% and area bias is below -15%. Without an
independent outline, the automated process cannot detect a uniform scale bias from its own fitted
cards. The published calibration is therefore the best estimate supported by its selected and
held-out detector evidence, not a confirmed physical-size measurement.

## Verification

- A detector-only calibration and proposed card scene complete without independent outlines.
- A known uniform shrink reports size bias but does not block publication.
- Focused calibration, proposal, and failed-run review checks pass.
- Ruff and web static checks pass for changed files.
- The frozen comparison completed for 24 local revisions and ten synthetic cases.
- The full `PipelineVisibleCardEditor.test.tsx` file still has 24 failures in frame-loading and
  editing cases (for example, a missing source-frame image). Its focused calibration diagnostic
  case passes. Those failures do not exercise the size gate.
