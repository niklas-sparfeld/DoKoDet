# 0088 M12 final evaluation lock

Date: 2026-10-16

## Decision

**Outcome: locked for one final evaluation with two candidates.** Compare M3 seed-17 and M6 seed-17 on the same final crops, once, with Gemini paired on those crops. M3 is the frozen control; M6 is the pooled-feature co-finalist. The 1-point rule and uncertainty test do not establish that M6 is better with two selection groups, and they do not exclude it from final comparison. The locked test has one group, so neither candidate can establish generalization.

Both exact bundles passed the 0094 loader and match their source checkpoint digests. M3 retains bundle `e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87`; M6 retains bundle `a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`. Direct replay matched the saved predictions for all 209 model-selection crops for each candidate. There were no top-1 or probability mismatches. The maximum raw-probability differences were 4.60e-7 for M3 and 4.23e-7 for M6. M11 records M3 calibration replay on all 105 calibration crops. M6’s calibrated reload reproduced logits exactly on all 105 calibration crops. No final-test crop or prediction was opened. The standard evaluation CLI could not start because the historical M3 campaign manifest lacks per-crop metadata; direct replay used the validated dataset and crop cache.

## Candidate and score contract

| Candidate | Frozen recipe | Checkpoint SHA-256 | Bundle digest | Temperature |
| --- | --- | --- | --- | ---: |
| M3 control | `224-cls`, seed 17 (`dinov3-m1-1792131997`) | `6d9234b35ab30e881b96dbbaf67cd7e6f71a137478796e4c14af03afe16936a` | `e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87` | 0.6080362924 |
| M6 co-finalist | `224-cls-mean-patch`, seed 17 (`dinov3-m1-1792139547`) | `ff560c5a4e2fff70f7e6ab0ff0cef6e7fa8cab8bbdfbcd25af4c569ee4bdfb1a` | `a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79` | 0.6487642659 |

Both use a frozen DINOv3 ViT-S/16 encoder, 224-pixel input, and the same pretrained weight digest `4610ad75edef83e75afdebf162d148dc628045ea6cbb83d67d4708c709c4f91d`. M3 uses a CLS linear head. M6 uses CLS plus mean-patch features and a linear head. The machine-readable lock records each recipe, dataset, split, preprocessing, and file digest.
- Preprocessing: RGB; aspect-preserving Lanczos resize; center letterbox with RGB `(128, 128, 128)`; normalization mean `[0.485, 0.456, 0.406]` and standard deviation `[0.229, 0.224, 0.225]`. Transform digest: `954760e7d8d840f72c682de22b989caae1a9c28d46760409b626718cfc112f42`.
- Supported input is one canonical 8-bit RGB P6 PPM crop from the reviewed visible-region path. Piles, consumed pile members, unreviewed automatic crops, and identity-unusable evidence are excluded.
- The output has 25 fixed labels. The campaign evaluates these 21 labels: face-up identities plus `FACE_DOWN`. The four NINE outputs stay in the ranked output map and count as errors on this campaign. Do not remove them or renormalize scores.
- For each model, rank by `softmax(logits / its locked temperature)`; retain raw probabilities and logits. Predict `FACE_DOWN` from pixels. DINO has no `UNKNOWN` output.
- Apply the calibrated 0.90 confidence gate to both models for final reporting: error rate at most 1%, coverage at least 90%. The optional M3 threshold `0.815743` and M6 threshold `0.823586` are exploratory and are not default routing or abstention thresholds. No calibration refit is allowed after this lock.

The M3 bundle is in `.runtime/dinov3-identity-0088/m12-final-lock/candidate-bundle`; the M6 bundle is in `.runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle`. The machine-readable lock lists both digests and all file hashes.

## Candidate-specific calibration

M6 was calibrated on the same reserved 105-crop `IMG_0095` view. Its own temperature is `0.6487642659`; NLL changed from 0.85635 to 0.76271 and 10-bin ECE is 0.08716. At the fixed 0.90 confidence threshold, it selects 41/105 crops (39.05% coverage) at 41/41 observed precision. The optional 99% precision routing threshold is 0.823586 and covers 57/105 at 57/57 observed precision. This policy is exploratory: the view has one source group, lacks `FACE_DOWN`, and fails the 90% coverage gate. It is not a default threshold. The M3 and M6 temperatures are candidate-specific and remain locked.

## Locked test and Gemini comparison

The only final-test member is `cardeventnet-IMG_0659`, source group `source-group-3840f6e17e00e1e4`, source video SHA-256 `77493bb970f30f302e442e41ae476157f820dfa979da23654bd5a70c22d3d64e`. M0 recorded 108 positive crops. M1 verified the source bytes but did not resolve frames, materialize crops, or score the test. M13 must materialize this frozen recording once and confirm exactly 108 eligible crops before it makes any prediction. If the count or source digest differs, stop without scoring and record the mismatch.

Pair M3, M6, and Gemini on the same reviewed native PPM crop bytes. Gemini is `gemini-3.8-flash` with the exact M0 prompt and response schema, one request per crop, no automatic retries, at most 250 requests, and a USD 10.00 cap. The Gemini config and classifier implementation hashes are recorded in the lock. Provider failures, missing crops, and unusable predictions stay in the denominator. A wrong label, `UNKNOWN`, an unsupported NINE output, or a failed prediction counts as incorrect for a supported positive target.

The frozen set contains one source group and cannot meet M0's three-group uncertainty floor. Report the final result as insufficient for generalization even if point metrics meet a threshold. Apply M0’s candidate quality gates and report the original 1-point challenger result as selection evidence only. Do not use that result to exclude M3 or M6. Report `top_3`, `macro_f1`, `per_class_confusion`, `per_recording_and_source_group_results`, `confident_errors`, `usable_prediction_coverage`, `all_supported_cards_correct_per_frame`, `grouped_uncertainty`, `local_latency_and_peak_memory`. Do not tune after viewing predictions.

## M13 handoff

Run the locked command from the JSON lock. The implementation must resolve the final reviewed crops, verify the source digest and 108-crop membership, then evaluate DINO and Gemini on the same crop bytes. The final crop membership remains sealed at the recording-level assignment until M13 resolves it. M13 must execute both locked model bundles in the same run; the 1-point selection-view rule cannot remove either candidate. M13 must use the locked bundle, preprocessing, confidence policy, Gemini recipe, denominator, and qualification rules. It may run this final evaluation once. Any resolved membership mismatch cancels scoring; there is no retry against a changed population.

Lock digest: `a2abb823959a430b11fd95d389d02522538476f1101613466a592363095ec2f2`. The full contract and verification receipt are in the [machine-readable lock](0088-M12_Final_Evaluation_Lock.json).
