# 0088 M12 final evaluation lock

Date: 2026-10-16

## Decision

**Outcome: locked for one final evaluation.** The candidate is the M3 seed-17 frozen CLS model with the M11 scalar temperature calibration. M6 did not pass the frozen challenger rule, and M3 remains an exploratory control because its support floors fail. This lock does not qualify the model.

The exact exported bundle has digest `e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87` and source checkpoint SHA-256 `6d9234b35ab30e881b96db5baf67cd7e6f71a137478796e4c14af03afe16936a`. The copied M12 bundle passed the 0094 bundle loader. Its files match the M11 export byte for byte. A direct replay of all 209 frozen model-selection crops matched the saved M3 checkpoint predictions: zero top-1 or probability mismatches, with maximum raw-probability difference 4.60e-7. The M11 report also records reloaded inference parity on all 105 calibration crops. No final-test crop or prediction was opened. The standard evaluation CLI could not start because the historical M3 campaign manifest lacks per-crop metadata; the direct replay used the validated dataset and crop cache.

## Candidate and score contract

- Run: `dinov3-m1-1792131997`; frozen DINOv3 ViT-S/16 encoder, CLS linear head, 224-pixel input.
- Training recipe digest: `5c33ba7c11f5769a82bf274db1ecd7f0f9a4b5fab0e355daec64fc707761607f`; data digest `c206c665f22fbe30b7343961d8555dad4bbec25b4420da836478a04f15e817ab`; split digest `753eb5c2d39eec031109fec59bdc2d66a028be2e5a50969ad441826fcaec8d87`. The encoder is frozen. Its pretrained weight digest is `4610ad75edef83e75afdebf162d148dc628045ea6cbb83d67d4708c709c4f91d`.
- Preprocessing: RGB; aspect-preserving Lanczos resize; center letterbox with RGB `(128, 128, 128)`; normalization mean `[0.485, 0.456, 0.406]` and standard deviation `[0.229, 0.224, 0.225]`. Transform digest: `954760e7d8d840f72c682de22b989caae1a9c28d46760409b626718cfc112f42`.
- Supported input is one canonical 8-bit RGB P6 PPM crop from the reviewed visible-region path. Piles, consumed pile members, unreviewed automatic crops, and identity-unusable evidence are excluded.
- The output has 25 fixed labels. The campaign evaluates these 21 labels: face-up identities plus `FACE_DOWN`. The four NINE outputs stay in the ranked output map and count as errors on this campaign. Do not remove them or renormalize scores.
- Rank by `softmax(logits / 0.6080362924)`; retain raw probabilities and logits. Predict `FACE_DOWN` from pixels. DINO has no `UNKNOWN` output.
- Use the calibrated 0.90 confidence gate for final reporting: error rate at most 1%, coverage at least 90%. The M11 threshold `0.815743` is exploratory and is not a default routing or abstention threshold. No calibration refit is allowed after this lock.

The bundle is in `.runtime/dinov3-identity-0088/m12-final-lock/candidate-bundle`; the machine-readable lock contains its digest and per-file hashes.

## Locked test and Gemini comparison

The only final-test member is `cardeventnet-IMG_0659`, source group `source-group-3840f6e17e00e1e4`, source video SHA-256 `77493bb970f30f302e442e41ae476157f820dfa979da23654bd5a70c22d3d64e`. M0 recorded 108 positive crops. M1 verified the source bytes but did not resolve frames, materialize crops, or score the test. M13 must materialize this frozen recording once and confirm exactly 108 eligible crops before it makes any prediction. If the count or source digest differs, stop without scoring and record the mismatch.

Pair both systems on the same reviewed native PPM crop bytes. Gemini is `gemini-3.8-flash` with the exact M0 prompt and response schema, one request per crop, no automatic retries, at most 250 requests, and a USD 10.00 cap. The Gemini config and classifier implementation hashes are recorded in the lock. Provider failures, missing crops, and unusable predictions stay in the denominator. A wrong label, `UNKNOWN`, an unsupported NINE output, or a failed prediction counts as incorrect for a supported positive target.

The frozen set contains one source group and cannot meet M0's three-group uncertainty floor. Report the final result as insufficient for generalization even if point metrics meet a threshold. Apply all frozen M0 gates and report `top_3`, `macro_f1`, `per_class_confusion`, `per_recording_and_source_group_results`, `confident_errors`, `usable_prediction_coverage`, `all_supported_cards_correct_per_frame`, `grouped_uncertainty`, `local_latency_and_peak_memory`. Do not tune after viewing predictions.

## M13 handoff

Run the locked command from the JSON lock. The implementation must resolve the final reviewed crops, verify the source digest and 108-crop membership, then evaluate DINO and Gemini on the same crop bytes. The final crop membership remains sealed at the recording-level assignment until M13 resolves it. M13 must use the locked bundle, preprocessing, confidence policy, Gemini recipe, denominator, and qualification rules. It may run this final evaluation once. Any resolved membership mismatch cancels scoring; there is no retry against a changed population.

Lock digest: `09c662ef8e7f3dd227991a3eb7f6c485343f19a244ba3f532fc097fa32c9be9e`. The full contract and verification receipt are in the [machine-readable lock](0088-M12_Final_Evaluation_Lock.json).
