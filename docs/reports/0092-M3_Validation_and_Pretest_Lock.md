# 0092 M3 validation and sealed-test decision

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

The single sealed evaluation completed after the lock was verified. The retained report is
`.runtime/rfdetr-segmentation-0092-m3-sealed-test/report.json`. Its baseline is the pinned pretrained
checkpoint named in M0. It verified the same M2 bundle and checkpoint hashes as the pretest lock.

| Sealed metric | Pinned pretrained baseline | 0092 candidate |
| --- | ---: | ---: |
| Visible-card mask AP 50:95 | 0.000000 | 0.794444 |
| Visible-card recall | 0.000000 | 0.959514 |
| Card-pile mask AP 50:95 | 0.000000 | 0.473179 |
| Card-pile recall | 0.000000 | 0.533333 |
| False detections | 63 | 19 |
| Duplicate detections | 0 | 1 |
| Empty-prediction rate | 0.326087 | 0.000000 |

| Sealed recording | Visible-card targets | Candidate visible-card recall | Pile targets | Candidate pile AP / recall |
| --- | ---: | ---: | ---: | --- |
| `cardeventnet-IMG_0656` | 133 | 0.992481 | 0 | No pile targets |
| `cardeventnet-IMG_0660` | 114 | 0.921053 | 105 | 0.473179 / 0.533333 |

Both recordings pass the frozen nonzero visible-card recall condition. The sealed gate passes, so
the decision is `selected_selectable_candidate`. The measured pile metrics cover the one recording
with pile targets; they do not establish broader pile performance. The candidate produced 17 visible
card-to-pile confusions at mask IoU 0.50 and 17 visible-card fragments inside piles. Its recall for
six cards near piles was 1.0; the pretrained baseline recall was 0.0.

Inference took 492.589 ms per frame for the pretrained baseline and 2,647.981 ms per frame for the
candidate on MPS. Model load took 3,997.774 ms and 532.105 ms, respectively. M4 must report this
latency for the final refit. No latency threshold was frozen in M0. The provider registry keeps
`gemini` as the default and lists the exact 0092 bundle as selectable.

The baseline and candidate predictions and provider registry passed their recorded SHA-256 checks.
The sealed report SHA-256 is
`fcf6f6c3e522e41f54f194d27ba77b596d2747ad8b8d99cf43b3395bab327302`. The test was opened once.
Do not rerun it or use these recordings as a fresh holdout.

| Runtime artifact | SHA-256 |
| --- | --- |
| `sealed-test-baseline-predictions.json` | `6ed41079d72f3d0674d1f6e54f7fce0cbf82851828813fd83faccdb9c1380c53` |
| `sealed-test-candidate-predictions.json` | `d739aa3c36672bbeeb319767ffe853e9ac10f077b77fe2807b58a985dd1b7aae` |
| `provider-registry.json` | `4b75f05df94340bf9f368ae6a7d7fe8e13b43b8af157c8d2c18b35cc35c49e5f` |
