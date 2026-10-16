# 0088 M13 final evaluation

Date: 2026-10-16

## Result

**Complete.** The one-time paired comparison scored all 108 eligible reviewed crops from
`cardeventnet-IMG_0659`. Both locked candidates ran on every crop, and Gemini made 108 requests.
There were no Gemini provider failures. Estimated Gemini cost was USD 0.0992.

| Candidate | Top-1 | Face-up top-1 | Top-3 | Macro F1 | Confidence coverage at 0.90 | Local p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| M3 seed 17, CLS | 83/108 (76.85%) | 82/107 (76.64%) | 102/108 (94.44%) | 0.7965 | 46/108 (42.59%), 0 errors | 155.721 ms |
| M6 seed 17, CLS plus mean patch | 86/108 (79.63%) | 85/107 (79.44%) | 104/108 (96.30%) | 0.8341 | 41/108 (37.96%), 0 errors | 61.842 ms |
| Gemini 3.8 Flash | 78/108 (72.22%) | 78/107 (72.90%) | — | 0.7244 | — | — |

M6 classified three more crops correctly than M3 on this recording. Both are better than Gemini
on the paired top-1 point estimate: M3 by 4.63 percentage points and M6 by 7.41 points. This is
descriptive evidence from the locked comparison; it does not qualify either model.

## Frozen quality gates

- **Face-up accuracy:** M3 reached 76.64% and M6 reached 79.44%, below the 98% gate.
- **Confidence policy:** both candidates had zero errors among predictions at or above 0.90, but
  their 42.59% and 37.96% coverage are below the 90% gate.
- **Local latency:** M3 p95 was 155.721 ms, above the 100 ms limit. M6 p95 was 61.842 ms, within
  the limit.
- **Model load:** M3 loaded in 2.495 seconds and M6 in 0.126 seconds, within the 10-second limit.
- **Peak memory:** 810,598,400 bytes, or 2.36% of the 32 GiB physical memory, within the limit.
- **Usable prediction coverage:** both DINO candidates returned usable predictions for all crops.
  Gemini usable coverage was 87.96%; its provider failure count was zero. Gemini `UNKNOWN` outputs
  lower usable coverage and count as incorrect.
- **`FACE_DOWN`:** the test has one face-down crop. Both DINO candidates classified it correctly;
  Gemini did not. This support cannot establish face-down quality.
- **Source-group uncertainty:** all 108 crops come from one source group. The frozen three-group
  minimum is unmet, so the comparison cannot establish generalization.
- **All supported cards correct per frame:** M3 24/44; M6 24/44; Gemini 23/44.

Top-3, class confusion, per-class support, confidence errors, all predictions, and per-request
Gemini cost are in the
[machine-readable result](0088-M13_Final_Evaluation.json). Its SHA-256 is
`db86b51e08372c51ee3e05ce4c9adb1362e45691de046c8f7323894eb9ba8522`, matching the runtime
receipt. The source digest and the 108-crop membership match the M12 lock. Both candidate bundles
were evaluated; neither was removed based on the M10 percentage-point rule.

## Qualification

M13 is complete. Neither candidate meets the frozen face-up accuracy and confidence coverage
gates. The local latency gate also fails for M3. The result has insufficient source-group and
face-down support for generalization claims. M15 will publish the overall qualification decision
and downstream handoffs. Do not tune or rerun against this final test.

## Reproduction and provenance

The one-time runner is
[`run_0088_m13_final_evaluation.py`](../../operations/scripts/run_0088_m13_final_evaluation.py).
The runtime result records lock digest `a2abb823959a430b11fd95d389d02522538476f1101613466a592363095ec2f2`,
108 Gemini requests, and the final result digest above. The locked bundles are M3
`e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87` and M6
`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`.
