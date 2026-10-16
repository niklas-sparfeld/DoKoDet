# 0092 M4 final refit

Date: 2026-10-16

## Status

M4 is complete. The final refit finished 40 epochs on MPS at 2026-10-16 21:29 local time. It
resumed from saved checkpoints after two earlier process stops. It did not restart from the
pretrained weights. The interrupted-attempt receipts, metrics, memory traces, checkpoints, and
logs remain under `.runtime/rfdetr-segmentation-0092-m4`.

The run receipt records `status: completed` and all stages as complete. Its duration is 82,881.607
seconds. The trainer selected `checkpoint_best_total.pth`, with SHA-256
`80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`. Its weights differ from the
pinned pretrained checkpoint.

The exported bundle passed the RF-DETR segmentation bundle loader. Its digest is
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`, and its checkpoint SHA-256
matches the run receipt. The manifest SHA-256 is
`826ccba533531c62a2059be5889b9c48aa44800df5d216997575a238c37f5816`. The M4 provider registry is
`.runtime/rfdetr-segmentation-0092-m4/provider-registry.json`. It lists the final bundle as
selectable and keeps `gemini` as the default. It points to the completed M3 sealed-test decision;
its SHA-256 is `d71ec98b494af4529bcd969dd621752903359a5a81b4d559c54779c18584d4c4`. The M3 registry
and sealed-test artifacts remain unchanged.

## Frozen lineage

The final refit used all 20 eligible M0 recordings, with 874 retained training frames and 2,714
reviewed masks. The M4 view digest is
`af5d8feb6487169484ab9c821b2c0ac8f43f55dd584c9b2a06b16991982e93b9`. It references the unchanged M1
materialization digest
`9fa0992bccab325a8fbadecb9bf375fbb783ea3b943a10e56b52cca92248e942` and the frozen M0 manifest
SHA-256 `418cc1488056b38fbafe69fdee30ddf5225b2e8a06b258f9eec6cac1536479cb`. The run receipt,
runtime view, and bundle agree on the M4 digest. Rebuilding the view produced the same digest.

The saved M2 run, checkpoint, and M3 evaluation artifacts remain intact. The sealed evaluator was
not run again. M3's measured quality and sealed-test results describe the pre-refit candidate, not
these final weights.

The trainer requires a validation loader. M4 used the same all-recording set for in-sample
monitoring. These values do not measure generalization and do not establish final-refit quality.
At epoch 40, the saved metrics report:

| In-sample metric | Value |
| --- | ---: |
| Detection mAP 50:95 | 0.919534 |
| Segmentation mAP 50:95 | 0.903115 |
| EMA segmentation mAP 50:95 | 0.917146 |
| Recall | 0.996493 |

## Bundle inference and latency

The bundle loaded and ran through `LocalVisibleCardSegmentationProvider` on MPS. A smoke inference
on an M4 training frame from `cardeventnet-IMG_0095` returned one visible-card proposal.

For a small timing sample, the provider loaded in 2,266.483 ms. Eight sequential frames from that
same recording had a median inference latency of 100.665 ms per frame, with a range of 92.012 to
283.698 ms. The first call is included. This small sample is not a benchmark. M0 set no latency
threshold, and these measurements do not imply a quality result.

The M3 latency in [the M3 report](0092-M3_Validation_and_Pretest_Lock.md) measured the
pre-refit candidate under its own evaluation. It is not a direct comparison with this eight-frame
smoke sample.

The training command keeps the legacy `rfdetr-segmentation-m3-training` run ID prefix. The M0
campaign ID, M4 output path, M4 dataset digest, and bundle digest identify this run as the final
refit. The generated receipt was not edited.

## Reproduction

Rebuild the isolated M4 view with:

```sh
mise exec -- uv run --project operations python operations/scripts/prepare_0092_m4_refit.py \
  --repository-root . \
  --source .runtime/rfdetr-segmentation-0092-m1 \
  --output .runtime/rfdetr-segmentation-0092-m4-view \
  --manifest docs/reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json
```

The rebuilt view must have digest
`af5d8feb6487169484ab9c821b2c0ac8f43f55dd584c9b2a06b16991982e93b9`. The completed training
command and arguments are in `run.json`. Do not rerun the refit or sealed evaluator.
