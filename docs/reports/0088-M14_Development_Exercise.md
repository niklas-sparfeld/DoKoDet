# 0088 M14 development sequence exercise

Date: 2026-10-16

## Result

**Complete.** Both M12 candidates ran through the existing visual-identity provider boundary on the same frozen automatic-crop development view. This is a runtime and review-burden exercise, not an accuracy evaluation: M1 matched none of these proposals to reviewed identity samples.

The view contained 130 detector frames and 495 automatic crops from 3 recordings. The source manifest digest is `ee996b367a848ad53ff3bf5f6700ae15eef0b6e354aaa5a2d917eccaa99af87a`. No final-test recording was used.

| Candidate | Inputs | Failures | Coverage | Review | Median / p95 ms | Load ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| M3 | 495 | 0 | 215/495 (43.4%) | 280/495 (56.6%) | 54.343 / 59.437 ms | 2172.367 ms |
| M6 | 495 | 0 | 209/495 (42.2%) | 286/495 (57.8%) | 53.846 / 58.429 ms | 109.48 ms |

## Per-recording burden

| Recording | Crops | M3 review | M6 review |
| --- | ---: | ---: | ---: |
| `cardeventnet-IMG_0095` | 105 | 68 (64.8%) | 70 (66.7%) |
| `cardeventnet-IMG_0657` | 117 | 14 (12.0%) | 15 (12.8%) |
| `cardeventnet-IMG_0662` | 273 | 198 (72.5%) | 201 (73.6%) |

## Findings and limits

- All automatic crops were unmatched at M1's frozen IoU threshold. The recorded review burden is a diagnostic routing estimate: inputs below 0.90 confidence or with an inference failure need review. This does not validate 0.90 as a safe automatic-accept threshold.
- The crop request contains automatic PPM bytes and no reviewed-side label. The classifier ranks `FACE_DOWN` from pixels. The report counts face-down top predictions but has no ground truth for them, so it makes no face-down quality claim.
- Both candidates retained all 25 ranked outputs, calibrated and raw probabilities, confidence metadata, and per-input latency. The malformed-crop control raised the expected crop-contract exception for each candidate. The existing pipeline catches per-card exceptions and records a failed identity outcome. The control is outside the development denominator.
- M1 reports zero unavailable detector frames. Its 314 missing inputs are reviewed samples without a matched automatic proposal, not detector or classifier failures.
- The 495 crops span model-selection and confidence-calibration recordings. They are diagnostic development sequences and are not a held-out test. M13 remains sealed and must not be rerun.
- No candidate is selected or promoted here. M3 and M6 both continue to M15 because the observed one-recording point difference cannot justify excluding either model.

Detailed ranked outputs and timing are in the [machine-readable report](0088-M14_Development_Exercise.json). The runner is [`run_0088_m14_development_exercise.py`](../../operations/scripts/run_0088_m14_development_exercise.py).
