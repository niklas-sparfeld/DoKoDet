# Epic 0075 M3 validated fit candidates

## Result

The calibration processor and run contracts are now v3. A successful finite fit produces a
run-scoped `CalibrationFitCandidate` with source revision, recipe digest, transforms, card size,
fit digest, observation receipts, and optional size-reference lineage. The candidate has its own
digest. It is separate from `TablePlaneCalibration` and cannot be published by
`CalibrationRevisionStore`.

Validation now compares held-out detector boundaries with the projected full-card outline. It
records symmetric median, P90, and worst distances in source pixels and as fractions of projected
card short side. Each usable observation records its quality weight, residual, and fit decision.
Validation also groups boundary errors into the image center and view edges.

Absolute size and area bias use only explicit, independent full-card outlines for held-out cards.
The caller supplies those outlines separately from detector polygons and names their source
revision. At least two held-out outlines must be available. Median short-side and area bias must
each be within 2%. Without enough independent outlines, the size gate is `unavailable` and fails
publication. With outlines, the gate reports measured bias and fails when either limit is exceeded.

The proposal processor returns a failed run with its fit candidate and measurements when a gate
fails. It does not create proposed scenes or publish a calibration from that candidate. Existing
v2 calibration run manifests remain readable. New runs use the v3 run contract and produce new
digests. The backend also stores the failed calibration run and processor-result digest in the
failed processor run metrics. The run API returns these metrics, so a failed candidate survives
the operations-to-backend boundary.

## Frozen M0 comparison

Reproduce the comparison from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0075-m3-baseline.json
```

| Measure | M3 result | M0 baseline |
| --- | ---: | ---: |
| Local results published / failed | 0 / 24 | 14 / 10 |
| Failed local runs with an inspectable fit candidate | 24 / 24 | 0 / 10 |
| Mean / maximum local call time | 2.521 s / 7.947 s | 0.801 s / 1.701 s |
| Maximum synthetic call time | 0.613 s | 0.114 s |
| Synthetic repeat digests match | 10 / 10 | 10 / 10 |

The frozen local results have no independent full-card outlines. All 24 therefore fail the absolute
size-reference gate. Fifteen also fail held-out boundary validation, five fail spatial coverage,
one fails the candidate-count gate, and one fails fit geometry. The measured local run time remains
below the 10-second limit. Real-data outline acceptance remains unavailable until independent
outlines for the frozen source frames exist.

The independent synthetic outlines support publication on nine of ten cases. The deliberately
shrunken masks fail the absolute-size gate:

| Case | Median held-out boundary | P90 / short side | Median short-side bias | Median area bias | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Clean isolated | 0.112 px | 0.00302 | +0.24% | +0.71% | Pass |
| Repeated stationary | 0.109 px | 0.00440 | +0.13% | +0.42% | Pass |
| Edge of view | 0.071 px | 0.00398 | +0.33% | +0.14% | Pass |
| 2 px boundary noise | 0.697 px | 0.06661 | +0.46% | +1.07% | Pass |
| Uniform 10% shrink | 3.283 px | 0.06722 | −9.77% | −18.77% | Fail |

The selector rejects the pile overlap, partial card, weak mask, oversized outliers, and clipped card
in their frozen synthetic cases. All ten synthetic results have identical repeated run digests.

## Verification

- Geometry, calibration, calibration-refinement, scene-initialization, and proposed-scene tests pass.
- The backend proposal service test confirms that a failed run keeps its fit candidate and source
  revision lineage in persisted run metrics, with no proposal revision published.
- Ruff lint passes. Ruff format checks pass for all edited lines. A whole-file format check reports
  pre-existing formatting differences elsewhere in two backend modules; those unrelated lines were
  left unchanged.
- The frozen comparison passes the local and synthetic runtime limits and all identifiable synthetic
  gates. Real-data acceptance remains pending independent outlines.
- The v2 run contract round-trips through the immutable calibration revision store.
- `git diff --check` and local Markdown-link checks pass.
