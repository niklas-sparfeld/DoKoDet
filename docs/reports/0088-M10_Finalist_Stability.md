# 0088 M10 finalist stability

Date: 2026-10-16

## Decision

**Outcome: inconclusive.** The equal-weight mean face-up top-1 was 98.56% for M3 and 98.88% for M6, a +0.32 percentage-point change. The M6 gain is below the frozen 1-point challenger threshold. The paired source-group bootstrap interval is unavailable because only two independent model-selection groups contribute; M0 requires at least three. M6 therefore does not pass the challenger rule. M3 also cannot qualify because the frozen evaluation support floors fail. Keep the M3 seed-17 checkpoint as the control anchor for any later diagnostic work; this is not a qualified model selection or promotion.

M3 seed 17 remains the exact control checkpoint: SHA-256 `6d9234b35ab30e881b96db5baf67cd7e6f71a137478796e4c14af03afe16936a`. The final test remains unopened.

## Fit and aggregate results

All four additional fits completed the frozen eight epochs, 4,792 steps, MPS fp32, batch-1 recipe. Each used the same 599 training crops and 209 model-selection crops. There were no timeouts or skipped fits.

| Seed | M3 face-up top-1 | M6 face-up top-1 | M3 all-crop top-1 | M6 all-crop top-1 |
| ---: | ---: | ---: | ---: | ---: |
| 17 | 206/208 (99.04%) | 207/208 (99.52%) | 207/209 | 208/209 |
| 101 | 205/208 (98.56%) | 205/208 (98.56%) | 206/209 | 206/209 |
| 202 | 204/208 (98.08%) | 205/208 (98.56%) | 205/209 | 206/209 |

Across seeds 17, 101, and 202, M3 scored 615/624 correct face-up predictions (98.56%). M6 scored 617/624 (98.88%). Top-3 was 208/208 for every fit. The single `FACE_DOWN` model-selection crop was correct in all six fits; this one crop does not establish face-down precision, recall, calibration, or generalization.

Paired face-up outcomes over the three seeds were 614 correct for both recipes, one correct only for M3, three correct only for M6, and six wrong for both. M6 corrected one `SPADES_ACE` crop at seed 17, one `SPADES_QUEEN` crop at seed 101, and one `SPADES_ACE` crop at seed 202. It also regressed a different `SPADES_ACE` crop at seed 101. The aggregate change is two additional correct predictions across 624 seed-crop outcomes, or 0.32 percentage points. Errors were limited to `SPADES_ACE` for M6. M3 also had one `SPADES_QUEEN` error at seed 101. No class declined by more than two points in the three-seed mean.

## Per-class results

The mean column is the equal-weight mean count across the three seeds over the fixed per-class support. Wilson 95% intervals use the seed-17 checkpoint predictions, which are the exact control and challenger checkpoints retained for comparison; these intervals describe crop-count uncertainty and do not establish source-group generalization.

| Class | Crops per seed | M3 mean correct | M6 mean correct | M3 seed 17 Wilson 95% | M6 seed 17 Wilson 95% |
| --- | ---: | ---: | ---: | ---: | ---: |
| CLUBS_ACE | 9 | 9/9 | 9/9 | 9/9 (70.1–100.0%) | 9/9 (70.1–100.0%) |
| CLUBS_JACK | 11 | 11/11 | 11/11 | 11/11 (74.1–100.0%) | 11/11 (74.1–100.0%) |
| CLUBS_KING | 10 | 10/10 | 10/10 | 10/10 (72.2–100.0%) | 10/10 (72.2–100.0%) |
| CLUBS_QUEEN | 12 | 12/12 | 12/12 | 12/12 (75.8–100.0%) | 12/12 (75.8–100.0%) |
| CLUBS_TEN | 13 | 13/13 | 13/13 | 13/13 (77.2–100.0%) | 13/13 (77.2–100.0%) |
| DIAMONDS_ACE | 10 | 10/10 | 10/10 | 10/10 (72.2–100.0%) | 10/10 (72.2–100.0%) |
| DIAMONDS_JACK | 7 | 7/7 | 7/7 | 7/7 (64.6–100.0%) | 7/7 (64.6–100.0%) |
| DIAMONDS_KING | 8 | 8/8 | 8/8 | 8/8 (67.6–100.0%) | 8/8 (67.6–100.0%) |
| DIAMONDS_QUEEN | 9 | 9/9 | 9/9 | 9/9 (70.1–100.0%) | 9/9 (70.1–100.0%) |
| DIAMONDS_TEN | 11 | 11/11 | 11/11 | 11/11 (74.1–100.0%) | 11/11 (74.1–100.0%) |
| HEARTS_ACE | 8 | 8/8 | 8/8 | 8/8 (67.6–100.0%) | 8/8 (67.6–100.0%) |
| HEARTS_JACK | 10 | 10/10 | 10/10 | 10/10 (72.2–100.0%) | 10/10 (72.2–100.0%) |
| HEARTS_KING | 10 | 10/10 | 10/10 | 10/10 (72.2–100.0%) | 10/10 (72.2–100.0%) |
| HEARTS_QUEEN | 12 | 12/12 | 12/12 | 12/12 (75.8–100.0%) | 12/12 (75.8–100.0%) |
| HEARTS_TEN | 10 | 10/10 | 10/10 | 10/10 (72.2–100.0%) | 10/10 (72.2–100.0%) |
| SPADES_ACE | 8 | 5.33/8 | 5.67/8 | 6/8 (40.9–92.9%) | 7/8 (52.9–97.8%) |
| SPADES_JACK | 12 | 12/12 | 12/12 | 12/12 (75.8–100.0%) | 12/12 (75.8–100.0%) |
| SPADES_KING | 15 | 15/15 | 15/15 | 15/15 (79.6–100.0%) | 15/15 (79.6–100.0%) |
| SPADES_QUEEN | 12 | 11.67/12 | 12/12 | 12/12 (75.8–100.0%) | 12/12 (75.8–100.0%) |
| SPADES_TEN | 11 | 11/11 | 11/11 | 11/11 (74.1–100.0%) | 11/11 (74.1–100.0%) |
## Source-group variation and runtime

| Recipe | `IMG_0657` group, across seeds | `IMG_0662` group, across seeds |
| --- | ---: | ---: |
| M3 | 343/348 (98.56%) | 272/276 (98.55%) |
| M6 | 345/348 (99.14%) | 272/276 (98.55%) |

`IMG_0657` is `source-group-9d6d4824b53bc4a9`; `IMG_0662` is
`source-group-d4543cb23cc73b35`. The two groups do not meet M0's three-group minimum. Report
group variation as insufficient; do not calculate or claim a qualifying bootstrap interval.
Per-class evaluation support also fails the frozen floor. M0 requires at least 10 evaluation crops
per class across three groups; the one `FACE_DOWN` crop and classes from only two groups remain
exploratory.

The matched seed-17 bundle benchmark measured M3 mean/p95 crop latency at 41.54/47.92 ms and M6 at 43.26/49.26 ms. Both are below the 100 ms limit. The M10 fits use the same 224-pixel architectures, so this reports the existing matched recipe benchmark; additional-seed bundle latency was not remeasured.

## Run receipts

| Recipe | Seed | Run ID | Training seconds | Best checkpoint SHA-256 | Validation prediction SHA-256 | Derived manifest digest |
| --- | ---: | --- | ---: | --- | --- | --- |
| M3 | 101 | dinov3-m1-1792150493 | 1009.09 | `7c5d36bd859eecd119daeac94c3c08ee4a33a21fc890b7544528476a1cae979e` | `d4e791f6e49b9b553c493c7929dcaef77f64f4a86ebe6e56ece72a65ab57be53` | `4b5d8f991ab17a8d1ab4534bd43f59f893345c7dfeee4eeae4c025f7ae3de0a0` |
| M3 | 202 | dinov3-m1-1792151505 | 976.73 | `76e0500a84abda0e568184489abb706c6f9bf07ae8befbcea83d134b9390b927` | `58caaa3faa09178f155e7be54b3beb4dbd03734d3e21a1797c3aebb49003ebc2` | `3b0be6f3cb3a1137f0d2c54d83476107aaf6e17a5c75b7962c510d99e5976864` |
| M6 | 101 | dinov3-m1-1792152485 | 968.91 | `400c88c9122ddef2d0488d85af8f34484a1855eb3e56aef10bb8b3d3307f1d47` | `0a75428f24e0858ac4ef7bae9bd7339f291b9bcca6a91d6de5a57461fe2b5873` | `879ad14727333d00e727be82f1aeff830e4efbc47606076667d67c9daeb6f56f` |
| M6 | 202 | dinov3-m1-1792153456 | 916.15 | `6d9f4f7af26980cecdaafe0dd44f4fc766b257cdf380eb5be611416cc9e45b0c` | `3408ec6609f01e4026259c3b50e40d00b5a97e54a97543e2f2c286442a751030` | `b0803494b38d0da5a740b0db45b5fcb8af6b2eeac31395016dca89edac9ddfdf` |

The M3 seed-17 checkpoint and M6 seed-17 checkpoint digests are recorded in the M3 and M6 reports. The four additional-seed manifests derive only the seed and campaign receipt from the frozen M1/M6 inputs. The dataset, split, crop inventory, class labels, evaluation crops, training recipe, and checkpoint-selection metric stayed fixed. No final-test data or new Gemini requests were used.

## Reproduction

The four run directories are under `.runtime/dinov3-identity-0088/results/m10-m3-seed-101`, `.runtime/dinov3-identity-0088/results/m10-m3-seed-202`, `.runtime/dinov3-identity-0088/m6-224-cls-mean-patch/m10-m6-seed-101`, and `.runtime/dinov3-identity-0088/m6-224-cls-mean-patch/m10-m6-seed-202`. Each contains `run.json`, `checkpoint-best.pt`, `checkpoint-last.pt`, and `predictions-validation.json`. Runtime files are ignored and are not committed; this report records their digests.

M10 uses the seed aggregation rule recorded in the active 0088 plan. The next milestone is M11. Use the M3 seed-17 checkpoint only as an exploratory calibration control unless later evidence supports a different decision; do not describe it as quality-qualified.
