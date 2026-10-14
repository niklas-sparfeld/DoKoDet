# 0087 M3 real-only training

Date: 2026-10-14

## Result

M3 completed the one frozen corrected-real-only candidate. RF-DETR stopped after epoch 15 by its
locked patience-8 rule. Training took 6,503.74 seconds, below the 7,200-second budget. The run used
the two-class map `1=visible_card`, `2=card_pile` and the MPS device.

The candidate passed the available aggregate validation comparisons against the pinned pretrained
checkpoint. It improved visible-card mask AP and recall, pile recall, total false predictions, and
empty prediction rate. Duplicate detections did not increase. False predictions shifted by class:
visible-card false predictions rose from 0 to 2, while pile false predictions fell from 20 to 0.
This is a validation result, not a model promotion. M5 owns the bundle decision and any sealed-test
use.

| Validation metric | Pretrained baseline | Corrected-real-only candidate |
| --- | ---: | ---: |
| Visible-card mask AP 50:95 | 0.000000 | 0.870065 |
| Visible-card recall | 0.000000 | 0.961165 |
| Card-pile mask AP 50:95 | 0.000000 | 0.958076 |
| Card-pile recall | 0.000000 | 1.000000 |
| False predictions | 20 | 2 |
| Visible-card false predictions | 0 | 2 |
| Card-pile false predictions | 20 | 0 |
| Duplicate predictions | 0 | 0 |
| Empty prediction rate | 0.500 | 0.000 |

The candidate also has visible-card mask AP50 0.960198 and pile mask AP50 1.000000. It made 101
visible-card and 36 pile predictions for 103 visible-card and 36 pile targets across 40 validation
frames.

## Frozen inputs and retained outputs

- M0 manifest digest: `a14ae7c3b96408c652ee7e1d78fc1bc209c9771bf5a70ef26432114a2acd2114`.
- M0 file SHA-256: `0e5013f49eb4862e29e924fc00a61790790be9296d6dadfa55354536beff5357`.
- Frozen recipe SHA-256: `6084c6e50b493279917fad7fb09a8b6a7273c6828a5f2961b701dba6e82fad74`.
- M1 materialization digest: `cc0891f04f8e9e4a59790e9f3eac52d91bdaeaf85b43a5a84a7aa563de119e29`.
- Staged dataset subset digest: `4a624e175c32005893e1230b67cd2c20e87b22fefcda75acc3a68d673459856b`.
- Training run ID: `rfdetr-0087-m3-training-1791956655`.
- Run record: `.runtime/rfdetr-segmentation-0087-m3-training/run.json`.
- Candidate bundle: `.runtime/rfdetr-segmentation-0087-m3-training/bundle`.
- Candidate checkpoint SHA-256: `d89c5502b3ff01ed673c2ba04e0a8168c9d1efe3d99c064dcafefdc314aea3fa`.
- Bundle digest: `018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9`.
- Validation report: `.runtime/rfdetr-segmentation-0087-m3-validation/report.json`.
- Baseline prediction SHA-256: `acea76ca5488b8b032caa9da97c9faa6c10375254799647ffc46f816852b6c25`.
- Candidate prediction SHA-256: `a6253c64e1b113cf5b0d23ad93dfb8e0e0b84a68a8d24b4473e11a50ade3b955`.

The evaluation used the 40-frame validation partition only. It did not read the sealed-test
partition. The validation report retains both prediction sets and records the M0, M1, checkpoint,
and bundle digests. Replaying the evaluation command verifies and reuses these artifacts without
running inference again.

The run used Python 3.13.15, RF-DETR 1.9.4, PyTorch 2.13.0, torchvision 0.28.0, and Supervision
0.30.9 on macOS arm64. RF-DETR retained `checkpoint_best_total.pth`. The runtime memory guard
cleared the MPS cache after validation and retained memory telemetry.

## Scope and limits

The frozen manifest contains only three completed reviewed references: one training recording,
one validation recording, and one sealed-test recording. Thus M3 trained on `IMG_0095` only. The
broader 22-recording development pool still needs completed reviewed references and a new M0 split
before it can enter training. Correcting the historical stage-use metadata does not supply those
labels or remove source-group separation.

There is no paired retraining control. The baseline is the pinned pretrained checkpoint with its
90-class head reinitialized to the frozen two-class map. It is not the prior 0068 candidate. The
measured result describes this fine-tune against that baseline on the frozen 0087 validation
recording; it does not isolate the effect of training-data scale or generalize across recordings.

The M1 view does not separately tag ordinary trick overlap, human-hand regions, or pile edges.
Those slices remain unavailable. The validation report records zero card targets near piles. The
sealed test has no pile targets, and it remains unopened. No test, runtime-default change, or bundle
promotion occurred.

## Reproduce

From the repository root, run training with the frozen manifest and the pinned checkpoint:

```sh
mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  train-rfdetr-segmentation-campaign \
  --dataset-dir .runtime/rfdetr-segmentation-0087 \
  --manifest docs/reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json \
  --pretrained-checkpoint .runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt \
  --output-dir .runtime/rfdetr-segmentation-0087-m3-training \
  --device mps
```

Then run the validation-only evaluator:

```sh
mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  evaluate-rfdetr-segmentation-campaign \
  --dataset-dir .runtime/rfdetr-segmentation-0087 \
  --manifest docs/reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json \
  --pretrained-checkpoint .runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt \
  --candidate-bundle .runtime/rfdetr-segmentation-0087-m3-training/bundle \
  --output-dir .runtime/rfdetr-segmentation-0087-m3-validation \
  --device mps
```
