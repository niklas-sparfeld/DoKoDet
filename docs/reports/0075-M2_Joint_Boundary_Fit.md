# Epic 0075 M2 joint boundary fit

## Result

M2 replaces the repeated-quadrilateral approximation with one shared homography and a fixed
`1.0 × 1.5` card shape. The fit uses uniformly sampled source-image boundaries, per-observation
weights, robust reweighting, and deterministic spatially separated starts. It keeps the best finite
fit when a quality gate fails and returns no candidate only when it has no usable boundary or no
finite transform.

Automatic calibration passes M1 boundary samples and quality scores to the fit. Anchor refinement
uses the same solver and passes each selected anchor once with its existing contribution weight.
Pinned-anchor conflict checks remain in refinement. The geometry algorithm version is now
`card-plane-geometry/v2`.

The solver pins one high-weight card to set table origin and rotation. It uses a fixed-size shared
homography system and independent per-card pose blocks. A Schur-complement step solves the shared
transform without building one dense matrix for all card poses. The solver uses at most three
spatially separated starts and eight iterations per fit, with finite projection checks and fixed
line-search limits.

## Frozen M0 comparison

Reproduce the evaluation from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0075-m2-baseline.json
```

The evaluator read all 24 frozen local RF-DETR revisions and ten known-geometry cases. Its report
identified algorithm `card-plane-geometry/v2`.

| Measure | M2 result | M0 baseline |
| --- | ---: | ---: |
| Local results published / failed | 16 / 8 | 14 / 10 |
| Mean / maximum local call time | 2.461 s / 8.117 s | 0.801 s / 1.701 s |
| Maximum synthetic call time | 0.608 s | 0.114 s |
| Synthetic repeat digests match | 10 / 10 | 10 / 10 |
| Failed local runs with an inspectable fit candidate | 0 / 8 | 0 / 10 |

Failed local runs still have no retained fit candidate. M3 owns that behavior. Real outline
acceptance remains pending because the frozen local results have no independent full-card outlines.

The identifiable synthetic gates pass:

| Case | Median held-out boundary | P90 / short side | Median short-side bias | Median area bias | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Clean isolated | 0.112 px | 0.00302 | +0.24% | +0.71% | Pass |
| Repeated stationary | 0.109 px | 0.00440 | +0.13% | +0.42% | Pass |
| Edge of view | 0.071 px | 0.00398 | +0.33% | +0.14% | Pass |
| 2 px boundary noise | 0.697 px | 0.06661 | +0.46% | +1.07% | Pass |

Selection rejected the overlapping pile candidate, the partial card as an apparent-scale outlier,
the weak mask below its confidence threshold, both oversized outliers as apparent-scale outliers,
and the clipped card at the frame border. The repeated-stationary case kept 19 observations and
applied the position-bin cap to five more. All ten synthetic run digests matched their repeated
runs.

## Uniform shrink limit

The frozen `shrink-10-percent` case scales every observed card mask by 0.90. The solver fits those
boundaries consistently: its median in-fit boundary distance is 0.00343 of a card short side. The
independent synthetic outlines expose the remaining error: held-out median boundary distance is
3.280 px, median short-side bias is −9.77%, and median area bias is −18.77%.

This result is not recoverable from those masks alone. The same pixels can describe incomplete masks
on standard cards or complete smaller cards under a different camera/table scale. The inputs contain
no absolute size reference to choose between them. A regression test records this scale ambiguity.
Do not add a fixed 10% correction: that would break exact clean data and would guess at a value that
is not present in real inputs. Keep the absolute-size gate pending independent full-card outlines or
another explicit size reference, and make M3 fail that gate when the evidence is unavailable.

## Verification

- 35 focused geometry, calibration, and anchor-refinement tests passed.
- Ruff lint and formatting checks passed for the changed formatted files. The refinement module
  passes Ruff lint; its file has older unrelated formatting differences that were left untouched.
- Six synthetic-planar tests passed. Two tests fail because this worktree has no deck-scan
  directory or 0068 source manifest.
- 85 local Markdown links in the changed epic, board, and report resolve.
- `git diff --check` passed.
- The frozen M0 evaluator passed the clean, edge, noise, repeatability, and runtime limits. The
  uniform-shrink absolute-size gate remains unavailable for the input-only reason above.
