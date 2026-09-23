# Epic 0075 M0 calibration baseline

## Evaluation set

The [frozen manifest](../../operations/fixtures/card-plane-calibration-v1/manifest.json)
records 24 exact local RF-DETR result revisions, their model and recording IDs, coverage kind,
manifest and content paths, and content digests. It includes 16 cascade revisions and 8 visible-card
segmentation revisions. All are completed `requested-event-frames` results, not full-video scans.
The local revision files must be present under `data/operations/pipeline/revisions/` to rerun the
comparison.

The synthetic cases use a known projective table plane. The evaluator scores only candidate IDs
held out from fitting against their generated full-card outlines. It reports symmetric sampled
boundary distance, signed short-side and area bias, and separate center and view-edge results. The
manifest freezes clean, repeated, edge, overlap, partial, weak-mask, 10 percent shrink, 2 pixel
noise, oversized-outlier, and clipped-card cases.

The retained local result files contain detector polygons and source-frame digests. They do not
contain independent full-card outline annotations for these exact frames. Real-data outline
acceptance therefore remains pending. The retained event-frame results also do not measure
full-recording coverage.

## Reproduction

Run from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py
```

The command reads the frozen manifest and retained revision files. It writes JSON to stdout and
does not modify the source results. Use `--output /tmp/card-plane-baseline.json` to save the report.
It checks manifest identities and canonical content digests before evaluating a revision. Synthetic
results run twice and report whether their run digests match.

## Current results

| Measure | Current baseline |
| --- | ---: |
| Local revisions | 24 |
| Published / failed | 14 / 10 (41.7% failed) |
| Failed with an inspectable fit candidate | 0 / 10 |
| Mean / max calibration call time | 0.801 s / 1.701 s |
| Synthetic cases with matching repeat-run digests | 10 / 10 |
| Max synthetic calibration call time | 0.114 s |

Across the 24 revisions, the processor read 5,425 raw candidates. It produced 2,559 geometry
candidates, 1,809 confidence-qualified candidates, and 1,353 deduplicated accepted candidates.

The local failures are 6 `insufficient_spatial_coverage`, 2 `held_out_alignment_failed`, and 2
`inconsistent_card_geometry`. Current timing covers `calibrate_recording`; it excludes file reading
and report serialization.

The following rows name the exact result revisions. The manifest also records each content digest.

| Revision ID | Variant | Result |
| --- | --- | --- |
| `visible-cards-visible_cards-run-1dddb5bf-6ba-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-27060560-229-attempt-1` | segmentation | failed: insufficient spatial coverage |
| `visible-cards-visible_cards-run-28eb5188-145-attempt-1` | segmentation | published |
| `visible-cards-visible_cards-run-2af2f63e-cdb-attempt-1` | segmentation | published |
| `visible-cards-visible_cards-run-35cf69dd-525-attempt-1` | segmentation | failed: insufficient spatial coverage |
| `visible-cards-visible_cards-run-588e9a26-75c-attempt-1` | segmentation | failed: insufficient spatial coverage |
| `visible-cards-visible_cards-run-5bd52a7b-3ba-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-6e3c895f-a46-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-6e44ce5b-753-attempt-1` | cascade-0070 | failed: held-out alignment |
| `visible-cards-visible_cards-run-71630e52-d48-attempt-1` | segmentation | failed: inconsistent card geometry |
| `visible-cards-visible_cards-run-7b9b84c7-2ab-attempt-1` | cascade-0070 | failed: held-out alignment |
| `visible-cards-visible_cards-run-7cdf2fae-eae-attempt-1` | cascade-0070 | failed: insufficient spatial coverage |
| `visible-cards-visible_cards-run-850d55f6-925-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-c341e308-722-attempt-1` | cascade-0070 | failed: inconsistent card geometry |
| `visible-cards-visible_cards-run-c3eb3a19-d42-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-c70927c4-e49-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-cdf105b9-7b2-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-da5c860a-42a-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-eef8737c-1f8-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-f678d010-5a3-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-f95a2f96-e89-attempt-1` | segmentation | failed: insufficient spatial coverage |
| `visible-cards-visible_cards-run-fa13cf76-df3-attempt-1` | segmentation | failed: insufficient spatial coverage |
| `visible-cards-visible_cards-run-mpsfix5-20260922-attempt-1` | cascade-0070 | published |
| `visible-cards-visible_cards-run-mpsfix6-20260922-attempt-1` | cascade-0070 | published |

The local evaluator found regional holdouts in 18 revisions for each region. This table summarizes
the legacy composite score only; the real results have no independent full-card outlines.

| Region | Held-out observations | Revisions with observations | Median of revision medians | Largest per-revision maximum |
| --- | ---: | ---: | ---: | ---: |
| Center | 213 | 18 | 11.146 | 95.293 |
| View edges | 97 | 18 | 62.659 | 260.109 |

The synthetic geometry gives an independent regional measurement:

| Synthetic case | Region | Held-out outlines | Median boundary | P90 boundary / short side |
| --- | --- | ---: | ---: | ---: |
| clean isolated | center | 1 | 0.0155 px | 0.00034 |
| clean isolated | view edges | 2 | 0.0074 px | 0.00019 |
| edge of view | center | 1 | 0.0072 px | 0.00021 |
| edge of view | view edges | 2 | 0.0059 px | 0.00024 |

| Synthetic case | Held-out observations | Median boundary | P90 boundary / short side | Median short-side bias | Median area bias |
| --- | ---: | ---: | ---: | ---: | ---: |
| clean isolated | 3 | 0.0074 px | 0.00031 | 0.0001% | 0.0003% |
| repeated stationary | 6 | 0.0092 px | 0.00031 | 0.0003% | 0.0005% |
| edge of view | 3 | 0.0072 px | 0.00025 | -0.0001% | -0.0001% |
| 10% shrink | 3 | 3.365 px | 0.06799 | -10.0379% | -19.0738% |
| 2 px boundary noise | 3 | 1.752 px | 0.07091 | 2.0102% | 7.1136% |

The current candidate selector rejects `pile-card-04b` for overlap, `card-05` for low confidence,
and `card-00` at the frame boundary. The fit rejects partial `card-04`. It accepts both oversized
false predictions in the outlier case and assigns neither a fit rejection. The false predictions
are `outlier-card-04` and `outlier-card-09`.

The legacy held-out alignment score is also reported for local revisions. It combines geometric
shape and vertex-distance terms, so it is not a pure pixel error and is not used as a frozen gate.

## Frozen acceptance gates

The manifest stores the exact gate values. Later calibration changes must meet these gates on the
same cases:

- Clean cards: median held-out boundary distance at most 1 px, P90 distance divided by card
  short-side length at most 0.02, and absolute median area bias at most 2%.
- Shrunken masks: absolute median short-side bias at most 2%, at least 80% lower than the measured
  10.0379% baseline bias; absolute median area bias at most 2%.
- View edge: P90 normalized boundary distance at most 0.03 and no more than 0.01 above the clean
  case.
- 2 px boundary noise: median boundary distance at most 2 px, P90 normalized distance at most
  0.08, and absolute median area bias at most 10%.
- Pile, partial, weak, clipped, and oversized false predictions must be rejected or given zero fit
  weight as specified in the manifest.
- Every synthetic run digest must match its repeated run. A local calibration call must take at
  most 10 s; a synthetic calibration call must take at most 2 s.
- Real-data acceptance stays pending until independent full-card outlines exist for frozen source
  frames.

The clean and edge limits leave room for measured image noise while preventing a material loss of
geometry. The shrink gate requires a reduction from the current measured 10.0379% signed median
short-side bias. Runtime limits are above current measurements and apply only to calibration calls.
