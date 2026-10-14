# 0092 M2 expanded reviewed RF-DETR training

Date: 2026-10-14

## Result

M2 is complete. The one frozen candidate trained on the 16 M0 training recordings with the M1
materialization. Training and metric collection completed in about 3 hours and 9 minutes. The
validation partition was used only for the frozen training rule. The sealed-test partition was not
opened.

The first finalization attempt wrote the exported weights and bundle, then failed because the
two-class bundle validator did not recognize the frozen 0092 campaign receipt. The runner had not
attached that receipt to the bundle. The finalization-only recovery verified the M0 and M1 lineage,
the completed training and metrics stages, and the matching checkpoint hashes. It then attached the
existing receipt and validated the repaired bundle. It did not call the trainer or change any
checkpoint bytes.

| Item | Evidence |
| --- | --- |
| Run | `.runtime/rfdetr-segmentation-0092` |
| M0 manifest digest | `bd452cc3f904007ed481af1f13b56e3910374c0d9392dfbf42de900379e741fa` |
| M1 materialization digest | `9fa0992bccab325a8fbadecb9bf375fbb783ea3b943a10e56b52cca92248e942` |
| Exported checkpoint SHA-256 | `7cf0d649bdb2d4a488a8035961a43e05fdc4f5e458a11721b007f71f501e292c` |
| Bundle | Two-class `visible_card` and `card_pile`; frozen 0092 M0 receipt present |
| Bundle digest | `d480a2b8a3b853befccc3c223e450c42611290ccf176c44703ce1b64a02a7a69` |
| Sealed test | Unopened |

The complete training logs, metrics, resource telemetry, checkpoints, and staged training data stay
under `.runtime`. This milestone does not evaluate the candidate or authorize promotion. M3 owns
validation and the one fresh sealed-test evaluation.

## Recovery command

```sh
mise exec -- uv run --project table_evidence_analyzer table-analyzer \
  finalize-rfdetr-segmentation-campaign \
  --dataset-dir .runtime/rfdetr-segmentation-0092-m1 \
  --manifest docs/reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json \
  --pretrained-checkpoint .runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt \
  --output-dir .runtime/rfdetr-segmentation-0092 \
  --device mps
```
