# Epic 0098 M2 identity diagnostics

This report summarizes the frozen M1 outputs. Confidence and prediction counts are diagnostic; they do not measure correctness.

## Coverage

- 26 recordings; 2994 frozen crops; 2994 stored outcomes.
- Classified: 2913; face-down: 81; unusable: 0; failed: 0; unprocessed: 0.
- M0 contains 197 zero-crop frames. Five upstream failures and three protected recordings remain outside this batch.
- Crop geometry succeeded for every M1 input. There were no crop or classifier failures.

## Prediction diagnostics

- Top-ranked probability across 2913 classified outcomes: min 0.172297, median 0.953710, mean 0.827077, p90 0.998116, max 0.999939.
- Top-1 minus top-2 margin across 2913 outcomes: min 0.000044, median 0.928521, mean 0.749925, p90 0.997132, max 0.999892.
- Per-recording run duration from the M1 polling record: min 29.231s, median 48.612s, mean 69.201s, p90 154.720s, max 190.873s. This is not per-crop inference latency.
- Peak sampled batch RSS: 1120518144 bytes. Per-recording RSS and per-crop latency were not recorded.
- Top-1 class counts:
  - `CLUBS_ACE`: 162
  - `CLUBS_JACK`: 116
  - `CLUBS_KING`: 239
  - `CLUBS_QUEEN`: 126
  - `CLUBS_TEN`: 123
  - `DIAMONDS_ACE`: 139
  - `DIAMONDS_JACK`: 120
  - `DIAMONDS_KING`: 173
  - `DIAMONDS_QUEEN`: 128
  - `DIAMONDS_TEN`: 125
  - `HEARTS_ACE`: 183
  - `HEARTS_JACK`: 137
  - `HEARTS_KING`: 156
  - `HEARTS_QUEEN`: 157
  - `HEARTS_TEN`: 155
  - `SPADES_ACE`: 116
  - `SPADES_JACK`: 117
  - `SPADES_KING`: 186
  - `SPADES_QUEEN`: 128
  - `SPADES_TEN`: 127

## Reviewed identity comparisons

- Valid exact pairs: 0.
- Inspected 2497 saved human reference outcomes.
- 2026 M1 predictions share exact frame metadata with at least one saved human outcome. None share the full card, frame, geometry, and crop lineage.
- No accuracy value is reported. A reviewed label was not transferred by timestamp or approximate geometry.
- M6 training-overlap outcomes and non-training outcomes are separate in the machine-readable report.

## Per-recording coverage and lineage

| Recording | Training overlap | Crops | Classified | Face-down | Unusable | Failed | Unprocessed | Confidence p50 | Margin p50 | Run seconds | Exact reviewed pairs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5a1f4037-d8ad-48da-9950-2ed2272811a5 | no | 179 | 178 | 1 | 0 | 0 | 0 | 0.941749 | 0.908969 | 190.873 | 0 |
| cardeventnet-IMG_0091 | no | 99 | 99 | 0 | 0 | 0 | 0 | 0.855499 | 0.797708 | 165.559 | 0 |
| cardeventnet-IMG_0095 | no | 109 | 109 | 0 | 0 | 0 | 0 | 0.785521 | 0.692295 | 147.241 | 0 |
| cardeventnet-IMG_0096 | no | 135 | 135 | 0 | 0 | 0 | 0 | 0.666782 | 0.524284 | 162.199 | 0 |
| cardeventnet-IMG_0097 | yes | 101 | 101 | 0 | 0 | 0 | 0 | 0.775250 | 0.667431 | 103.135 | 0 |
| cardeventnet-IMG_0636 | yes | 99 | 99 | 0 | 0 | 0 | 0 | 0.983404 | 0.974565 | 47.613 | 0 |
| cardeventnet-IMG_0637 | yes | 100 | 100 | 0 | 0 | 0 | 0 | 0.980636 | 0.972520 | 35.568 | 0 |
| cardeventnet-IMG_0638 | yes | 100 | 99 | 1 | 0 | 0 | 0 | 0.984436 | 0.976506 | 42.732 | 0 |
| cardeventnet-IMG_0639 | yes | 99 | 99 | 0 | 0 | 0 | 0 | 0.972011 | 0.953843 | 37.421 | 0 |
| cardeventnet-IMG_0640 | yes | 100 | 100 | 0 | 0 | 0 | 0 | 0.976542 | 0.962297 | 48.166 | 0 |
| cardeventnet-IMG_0642 | no | 99 | 99 | 0 | 0 | 0 | 0 | 0.954617 | 0.927747 | 33.559 | 0 |
| cardeventnet-IMG_0643 | yes | 103 | 102 | 1 | 0 | 0 | 0 | 0.974088 | 0.964135 | 48.459 | 0 |
| cardeventnet-IMG_0644 | no | 208 | 200 | 8 | 0 | 0 | 0 | 0.910892 | 0.852444 | 139.785 | 0 |
| cardeventnet-IMG_0645 | no | 106 | 105 | 1 | 0 | 0 | 0 | 0.824004 | 0.743159 | 29.790 | 0 |
| cardeventnet-IMG_0650 | yes | 71 | 71 | 0 | 0 | 0 | 0 | 0.993613 | 0.989634 | 29.231 | 0 |
| cardeventnet-IMG_0651 | yes | 102 | 101 | 1 | 0 | 0 | 0 | 0.990824 | 0.986447 | 35.563 | 0 |
| cardeventnet-IMG_0652 | no | 102 | 102 | 0 | 0 | 0 | 0 | 0.981141 | 0.971920 | 62.488 | 0 |
| cardeventnet-IMG_0653 | yes | 98 | 98 | 0 | 0 | 0 | 0 | 0.993782 | 0.990690 | 52.432 | 0 |
| cardeventnet-IMG_0655 | yes | 104 | 104 | 0 | 0 | 0 | 0 | 0.990927 | 0.984529 | 48.764 | 0 |
| cardeventnet-IMG_0657 | no | 103 | 102 | 1 | 0 | 0 | 0 | 0.988103 | 0.982055 | 57.390 | 0 |
| cardeventnet-IMG_0658 | yes | 100 | 100 | 0 | 0 | 0 | 0 | 0.986787 | 0.980197 | 31.281 | 0 |
| cardeventnet-IMG_0661 | no | 109 | 106 | 3 | 0 | 0 | 0 | 0.975097 | 0.963550 | 49.107 | 0 |
| cardeventnet-IMG_0662 | no | 98 | 98 | 0 | 0 | 0 | 0 | 0.969446 | 0.949058 | 37.701 | 0 |
| game-2026-09-18-01-001 | no | 165 | 142 | 23 | 0 | 0 | 0 | 0.627462 | 0.487056 | 56.473 | 0 |
| game-2026-09-18-01-002 | no | 161 | 134 | 27 | 0 | 0 | 0 | 0.502249 | 0.287424 | 61.052 | 0 |
| game-2026-09-18-01-003 | no | 144 | 130 | 14 | 0 | 0 | 0 | 0.666013 | 0.471560 | 45.642 | 0 |

## Reproduction

Run the report builder from the repository root with the retained primary pipeline store:

```sh
mise exec -- uv run --project operations python operations/scripts/build_0098_m2_identity_diagnostics.py \
  --pipeline-store /Users/niklas.sparfeld/Developer/doko_detector/data/operations/pipeline
```

The builder verifies each M1 output content digest before it writes either report.
