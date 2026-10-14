# 0092 M3 validation and pretest lock

Date: 2026-10-14

## Validation result

The saved M2 candidate passed the frozen validation gates against the digest-pinned 0087
candidate. The evaluator used all 98 reviewed validation frames. It did not read the sealed-test
partition. The baseline and candidate prediction artifacts remain under
`.runtime/rfdetr-segmentation-0092-m3-validation`.

| Metric | 0087 baseline | 0092 candidate |
| --- | ---: | ---: |
| Visible-card mask AP 50:95 | 0.708178 | 0.845030 |
| Visible-card recall | 0.885185 | 0.974074 |
| Card-pile mask AP 50:95 | 0.294028 | 0.790570 |
| Card-pile recall | 0.482759 | 1.000000 |
| False detections | 82 | 27 |
| Duplicate detections | 0 | 0 |
| Empty-prediction rate | 0.000000 | 0.000000 |

| Validation recording | Visible-card AP / recall, 0087 → 0092 | Pile AP / recall, 0087 → 0092 | False detections, 0087 → 0092 |
| --- | --- | --- | ---: |
| `cardeventnet-IMG_0651` | 0.717953 / 0.929577 → 0.842641 / 0.964789 | 0.000000 / 0.000000 → 0.923306 / 1.000000 | 76 → 24 |
| `cardeventnet-IMG_0658` | 0.689497 / 0.835938 → 0.846873 / 0.984375 | 0.604440 / 1.000000 → 0.643996 / 1.000000 | 6 → 3 |

The evaluator took 490.98 seconds on MPS. It retained prediction files and their SHA-256 values
in `report.json`. The report records that human-hand and ordinary-overlap labels are unavailable.
The corpus has no reviewed empty-background frames.

## Locked pretest decision

The M0 validation gates pass for both classes. The sealed partition has 92 retained frames, 247
visible-card targets, and 105 pile targets. These values exceed the frozen minimums of 30 frames,
100 visible-card targets, and 30 pile targets. Both sealed recordings retain permission for test and
evaluation use.

The pretest lock is [0092-M3_Pretest_Decision.json](0092-M3_Pretest_Decision.json). Its SHA-256 is
`6bc4f1294be50db0cb5f8c894387f938c22d9552464a121a13b3d33a39dca0a4`. It pins the campaign
manifest, repaired M2 run receipt, M3 validation report, and bundle manifest. It allows one sealed
evaluation of the pinned pretrained baseline and the 0092 candidate. It selects the candidate only
if every sealed recording has nonzero visible-card recall. `gemini` remains the runtime default.

At this report revision, the sealed evaluation has not run. Do not rerun it after a completed report
exists.
