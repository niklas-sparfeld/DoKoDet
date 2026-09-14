# CardEventNet campaign recipes

`0063-m5-validation.yaml` is the bounded validation recipe for epic 0063 M5. It uses the frozen
CardEventNet dataset and the validation partition only. It declares one CPU/FP32 candidate, one
seed, the current full-frame decoder settings, a 60-minute compute budget, one failure allowance,
the `card-event-net-v1` gates, and `runtime/v1` Core ML compatibility.

Run or resume it from the repository root:

```bash
mise exec -- uv run --project operations doko model improve card-event-net \
  --repository-root . \
  --recipe experiments/cardevent/0063-m5-validation.yaml \
  --device cpu \
  --precision fp32
```

The campaign materializes the frozen dataset below `.runtime/cardevent/`, then writes its
validation comparison and diagnostics below `data/model-campaigns/`. It does not read the sealed
test partition or the system holdout during M5. The test and Core ML export remain M6 actions.

The recipe baseline digest is the digest of the supplied
`card_event_net/CardEventNet.mlpackage` bundle. The local `data/model-registry.json` must contain
the current champion entry with this digest before the command can run. If that champion is not a
loadable CardEventNet training checkpoint, the campaign records the incompatibility and ends with
`human_review_required`; it does not replace the champion.
