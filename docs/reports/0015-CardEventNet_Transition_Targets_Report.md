# CardEventNet transition targets report

## Status

Complete. The experiment passed validation. It is not the new default because the final test
showed a large device-domain gap.

## Scope and provenance

- Base checkpoint: `data/outputs/run-20260825-162656/best.pt`.
- Experiment split: `data/splits/batch-2026-08-24.yaml`.
- Annotations: `data/annotations-val-reviewed`.
- Cache: `data/cache`, preprocessing `full_frame_letterbox_v1`.
- Training did not use a hard-negative manifest.
- V1 run: `run-20260825-225353`.
- V2 run: `run-20260825-235429`.

The controlled label changes were:

| Setting | Base | Transition experiment |
| --- | ---: | ---: |
| Positive window | 0.45 s | 0.25 s |
| Post-event exclusion end | 1.80 s | 0.35 s |
| Pre-event exclusion | 0.80 s | 0.10 s |

V2 also sets `model.temporal_head: full_clip_v2`. It uses valid temporal convolutions over all
eight causal frame features. V1 remains the default for missing configuration values and old
checkpoints.

## Sampling

The V2 run selected 12,283 samples: 3,078 positive and 9,205 ordinary negative. The effective
positive fraction was 25.06%. The eligible population had 3,078 positive, 17,080 ordinary
negative, and 2,198 ignored timestamps. Only `IMG_0095` and `IMG_0096` could not reach the
requested 1:3 negative-to-positive ratio.

## Validation selection

The validation threshold was 0.3442875146865845. The selection rule was
`target_recall_lowest_false_events_per_hour` with a 98% recall target.

| Run | Recall | Precision | F1 | False events/hour | Emission p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline `162656` | 98.04% | 67.20% | 79.74% | 926.28 | 0.23 / 0.59 s |
| V2 `235429` | 98.43% | 85.96% | 91.77% | 311.29 | 0.24 / 0.43 s |

V2 passed all validation gates. Of 945 eligible post-event tail samples, 72 (7.62%) were at or
above the selected threshold. The baseline had 855 of 945 (90.48%). At the 131 reviewed
validation hard-negative timestamps, V2 was at or above the threshold 20 times. The baseline was
at or above it 123 times.

## Final test result

The final test run used the frozen validation threshold. It did not select a threshold from test
data.

| Partition | Recall | Precision | F1 | False events/hour | Emission p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Validation | 98.43% | 85.96% | 91.77% | 311.29 | 0.24 / 0.43 s |
| Test | 78.02% | 68.27% | 72.82% | 349.40 | 0.22 / 0.49 s |

The four old iPhone SE videos, `IMG_2777` through `IMG_2780`, are 73.57% of the test duration.
They contain 201 of 455 events, 67 of 100 misses, and 144 of 165 false detections. Their combined
recall was 66.67%, precision was 48.20%, F1 was 55.95%, and false-event rate was 414.45 per hour.
The other five staged test videos had 87.01% recall, 91.32% precision, 89.11% F1, and 168.29 false
events per hour.

This is a material device-domain gap. It prevents promotion of the V2 configuration as the
general default. The result is confirmation only because historical test artifacts already exist.
No threshold or model tuning followed this test run.

## Decision and follow-up

Keep the transition configurations as reproducible experimental configurations. Keep the default
configuration unchanged. Keep the old iPhone SE videos as a named out-of-domain regression suite,
not as most of the primary in-domain score. If iPhone SE support is a product requirement, collect
independent device sessions and use a device-aware train, validation, and test design. Start a new
experiment for that work; do not reuse this test result for model selection.

The implementation includes sampling reports, saved-stream transition diagnostics, and the V2
full-clip head. Evaluation diagnostics now use a filename derived from the evaluation report, so a
test run cannot overwrite the validation diagnostic.

The experimental V2 checkpoint exported to
`data/outputs/run-20260825-235429/CardEventNet-v2.mlpackage`. Its deterministic Core ML parity
check passed with a maximum absolute error of `1.62125e-05`.
