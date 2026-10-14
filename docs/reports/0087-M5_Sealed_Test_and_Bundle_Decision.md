# 0087 M5 sealed test and bundle decision

Date: 2026-10-14

## Decision

The pretest decision was locked before any sealed-test inference. It fixed the candidate bundle and
all M0, M1, and M3 input digests. It permitted one evaluation of the pretrained baseline and the
candidate. The candidate would be selected only if it passed the frozen validation gates and each
sealed-test recording had nonzero visible-card recall.

The locked decision SHA-256 is
`b386f8f403a8da30874c0cdd6a9812ba4357b7ac8e5457e2a9f613abb4379e9d`. See the
[pretest decision lock](0087-M5_Pretest_Decision.json).

The candidate passed. It is available as an explicit selectable
`local-rfdetr-segmentation` provider. `gemini` remains the default. No runtime default changed.
The frozen validation checks also passed: visible-card AP and recall improved, pile recall was
nonzero where supported, and false predictions, duplicates, and empty-frame rate were no worse than
the baseline.

## Sealed-test result

The frozen partition has 48 retained frames and 130 visible-card targets, above the M0 minimum of
30 frames and 100 targets. It has no pile targets. Both models ran once on the sealed partition.

| Metric | Pretrained baseline | Candidate |
| --- | ---: | ---: |
| Visible-card mask AP 50:95 | 0.000000 | 0.858450 |
| Visible-card mask AP50 | 0.000000 | 1.000000 |
| Visible-card recall | 0.000000 | 1.000000 |
| Predictions / targets | 35 / 130 | 130 / 130 |
| False predictions | 35 | 0 |
| Duplicate predictions | 0 | 0 |
| Empty prediction rate | 0.291667 | 0.000000 |

The candidate had nonzero recall for the only sealed-test recording, `cardeventnet-IMG_0654`. Its
recall was 1.0. Since the partition has no pile targets, this result does not validate pile quality.

## Bundle, local inference, and lineage

The exported bundle loaded through the shared RF-DETR bundle loader. Before inference, the evaluator
verified the M0 campaign manifest, M1 materialization digest, M3 run, candidate bundle manifest, and
checkpoint SHA-256 against the pretest lock. Local MPS inference completed on the baseline and
candidate.

| Timing | Pretrained baseline | Candidate |
| --- | ---: | ---: |
| Model load | 3,425.909 ms | 435.727 ms |
| Mean inference per frame | 267.462 ms | 1,311.377 ms |
| Frames | 48 | 48 |

The candidate bundle digest is
`018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9`. Its checkpoint SHA-256 is
`d89c5502b3ff01ed673c2ba04e0a8168c9d1efe3d99c064dcafefdc314aea3fa`. The bundle is retained at
`.runtime/rfdetr-segmentation-0087-m3-training/bundle` in the active campaign worktree. Use this
exact bundle for downstream work; do not substitute another checkpoint.

The machine-readable evaluation report is retained at
`.runtime/rfdetr-segmentation-0087-m5-sealed-test/report.json` (SHA-256
`04b22b3d0f36a8078dc0068d6d55f097c3a3355d3cad8de81fe710df8ca16984`). Prediction artifacts:

- Baseline: `.runtime/rfdetr-segmentation-0087-m5-sealed-test/sealed-test-baseline-predictions.json`
  (SHA-256 `3fde32a897532532d141b21213ded9632efab1ccdfb5acf6a8c486aeda1a416e`)
- Candidate: `.runtime/rfdetr-segmentation-0087-m5-sealed-test/sealed-test-candidate-predictions.json`
  (SHA-256 `4d964bf744f3f02da1b930b9e80e9fa4b21a3e740e252112807e7ffb9cfaa5d9`)
- Explicit provider registry: `.runtime/rfdetr-segmentation-0087-m5-sealed-test/provider-registry.json`
  (SHA-256 `5db0a4f1444fce0f17fe0de09bc16f26bf01c016d8feb12f8cc1552730f00ed5`)

The registry identifies the exact bundle and keeps `gemini` as default. The bundle path above is a
local artifact in this worktree, not a repository-managed model file.

## Limits and handoff

The candidate trained on one recording and was evaluated on one sealed-test recording. M2 found no
compatible synthetic pool, so no mixed candidate was trained. The source set contains no reviewed
empty-background frames. The test has no pile targets. Human-hand, ordinary-trick-overlap, and
separately tagged pile-edge slices are unavailable. The sealed test was used once and must not be
reopened as a fresh holdout.

0089 and 0090 can use the exact selected candidate bundle above, with digest
`018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9`. Retain the pinned pretrained
baseline for rollback and comparisons. Keep the runtime default unchanged.

## Reproduction

The sealed-test command requires the checked pretest lock. It replays the retained report if the
same completed output is present; it does not repeat inference.

```sh
mise exec -- uv run --project table_evidence_analyzer table-analyzer \
  evaluate-rfdetr-segmentation-sealed-test \
  --dataset-dir .runtime/rfdetr-segmentation-0087 \
  --manifest docs/reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json \
  --pretrained-checkpoint .runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt \
  --training-run .runtime/rfdetr-segmentation-0087-m3-training/run.json \
  --validation-report .runtime/rfdetr-segmentation-0087-m3-validation/report.json \
  --candidate-bundle .runtime/rfdetr-segmentation-0087-m3-training/bundle \
  --pretest-decision docs/reports/0087-M5_Pretest_Decision.json \
  --output-dir .runtime/rfdetr-segmentation-0087-m5-sealed-test \
  --device mps
```
