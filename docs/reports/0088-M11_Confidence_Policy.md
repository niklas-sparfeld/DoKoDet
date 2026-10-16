# 0088 M11 confidence policy

Date: 2026-10-16

## Decision

**Outcome: exploratory calibration only; confidence and quality gates fail.** The frozen M3 seed-17
control remains the diagnostic candidate. Its positive scalar temperature is `0.6080362924`. The
calibration view contains 105 reviewed face-up crops from one source group (`IMG_0095`). It contains
no `FACE_DOWN` crop. The 20 face-up class support counts range from 2 to 8, below M0's minimum of
10 crops in 3 groups per class.

Temperature scaling preserves ranking. Raw and calibrated top-1 both scored 83/105 (79.05%) on
this reserved group. This is much lower than M3's 206/208 on model selection and does not qualify
the classifier. The calibration view has one source group, so it cannot establish reliability or
confidence-policy generalization.

The bounded 99% precision-target search selected a review-routing threshold of `0.815743`. It
selected 55/105 crops (52.38%) at 55/55 observed precision. At the frozen 0.90 threshold, 42/105
crops (40.00%) were selected at 42/42 observed precision. The observed precision meets the 99%
target, but coverage is below M0's 90% minimum. These results do not meet the frozen confidence
gate. The selected threshold is an exploratory artifact; it is not a default review policy.

No crop was predicted as `FACE_DOWN` among the 105 face-up calibration crops. The maximum raw
`FACE_DOWN` probability was 0.00556; after calibration it was 0.000632. The view has zero true
`FACE_DOWN` examples, so it cannot measure confidence on true back-design crops or face-down recall.

## Calibration and confidence results

| Measure | Raw | Calibrated |
| --- | ---: | ---: |
| Top-1 | 83/105 (79.05%) | 83/105 (79.05%) |
| Negative log likelihood | 0.88257 | 0.75985 |
| Expected calibration error, 10 fixed bins | 0.20277 | 0.05321 |
| Top-1 confidence at least 0.90 | 13/105 selected; 13/13 correct (12.38% coverage) | 42/105 selected; 42/42 correct (40.00% coverage) |
| False `FACE_DOWN` predictions on face-up crops | 0/105 | 0/105 |

The calibration artifact reports ten fixed-width reliability bins. Calibrated bins with support are:

| Confidence range | Crops | Mean confidence | Accuracy |
| --- | ---: | ---: | ---: |
| 0.2–0.3 | 2 | 0.2925 | 0.0% |
| 0.3–0.4 | 9 | 0.3587 | 33.3% |
| 0.4–0.5 | 11 | 0.4601 | 45.5% |
| 0.5–0.6 | 7 | 0.5592 | 71.4% |
| 0.6–0.7 | 8 | 0.6518 | 62.5% |
| 0.7–0.8 | 10 | 0.7448 | 80.0% |
| 0.8–0.9 | 16 | 0.8491 | 93.8% |
| 0.9–1.0 | 42 | 0.9655 | 100.0% |

The bounded review-threshold selection targets 99% precision, applies only to human-review routing,
and preserves all ranked candidates. Its selected threshold is `0.815743`, with 55/105 coverage and
55/55 observed precision. A threshold result on one source group is descriptive only.

## Support by identity

| Identity | Correct / support | Identity | Correct / support |
| --- | ---: | --- | ---: |
| CLUBS_ACE | 6/6 | DIAMONDS_ACE | 6/6 |
| CLUBS_JACK | 1/5 | DIAMONDS_JACK | 0/2 |
| CLUBS_KING | 3/3 | DIAMONDS_KING | 2/3 |
| CLUBS_QUEEN | 0/6 | DIAMONDS_QUEEN | 3/6 |
| CLUBS_TEN | 5/5 | DIAMONDS_TEN | 4/4 |
| HEARTS_ACE | 5/6 | SPADES_ACE | 4/4 |
| HEARTS_JACK | 6/6 | SPADES_JACK | 6/7 |
| HEARTS_KING | 5/5 | SPADES_KING | 5/7 |
| HEARTS_QUEEN | 5/7 | SPADES_QUEEN | 5/5 |
| HEARTS_TEN | 4/4 | SPADES_TEN | 8/8 |

The table reports diagnostics on the reserved group. It does not satisfy class support floors.
`FACE_DOWN` is absent from this view.

## Reproduction and integrity

- Candidate: M3 frozen-encoder, CLS, 224-pixel, seed 17.
- Run: `.runtime/dinov3-identity-0088/results/224-cls/run.json` (`dinov3-m1-1792131997`).
- Source checkpoint SHA-256: `6d9234b35ab30e881b96db5baf67cd7e6f71a137478796e4c14af03afe16936a`.
- Calibration view: `.runtime/dinov3-identity-0088/m11-confidence-calibration/calibration-view.json`;
  105 rows; SHA-256 `33fb5430be32ef1f844a6252c71c44ecca4692c2595234079baaa8eb01a819be`.
- Calibration artifact: `.runtime/dinov3-identity-0088/m11-confidence-calibration/calibration.json`;
  SHA-256 `17a1c01f29172fabd3e2f6478f9e7b26e8df5cc07919016a52524208f671ae1a`.
- The exported calibrated bundle records the same calibration digest and source checkpoint digest.
  Its bundle digest is `e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87`.
- Reloaded calibrated inference reproduced the raw logits and raw probabilities exactly for all 105
  crops. Calibrated and raw top-1 predictions were identical for all 105 crops.
- The view uses only M0's reserved `confidence_calibration` partition. No model-selection or final-test
  crop was used to fit the temperature or choose the review threshold. The final test remains sealed.

Runtime bundles and calibration views are ignored local artifacts. This report retains their
identifying digests. No code or final-test data changed.
