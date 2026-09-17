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

`0063-m8-interval-validation.yaml` is the bounded single-axis recipe for epic 0063 M8. It keeps
the M5 architecture, full causal clip, decoder, seed, and budget fixed. Its `baseline_checkpoint`
is the loadable M5 `best.pt`; the registry champion remains the application baseline.

Prepare the operator handoff without starting training:

```bash
mise exec -- uv run --project operations doko model improve card-event-net \
  --repository-root . \
  --recipe experiments/cardevent/0063-m8-interval-validation.yaml \
  --preflight
```

The preflight writes `handoff.json` below the deterministic campaign directory. The handoff has
the exact manual and resume commands, expected artifacts, M7 data digests, and train/validation
sample estimates. It does not read the sealed test partition, system holdout, or a hard-negative
manifest, and it does not start the campaign.

After the operator completes the M8 command, review its artifacts without starting another model
command:

```bash
mise exec -- uv run --project operations doko model review-card-event-net \
  cardeventnet-0063-m8-interval-validation-df1dddc98bbb \
  --repository-root .
```

The review validates the checkpoint and data lineage, compares the M5 checkpoint and M8 candidate
on the same validation references, and writes `m9-review.json`, `m9-report.md`, and
`m9-hard-negative-candidates.json` below the campaign directory. The candidate manifest uses only
the training partition, excludes interval and label-exclusion regions, and remains
`training_input: false` until human review. The review never reads the sealed test partition.

Publish the read-only M10 timing-review handoff after the operator-run hard-negative ablation:

```bash
mise exec -- uv run --project operations doko model review-card-event-net-timing \
  cardeventnet-0063-m9-hard-negative-ablation \
  --repository-root .
```

This validates the M9 ablation evaluation and saved validation streams against the M7 dataset and
reference revisions. It writes `m10-timing-review.json`, `m10-operator-review.json`, and
`m10-report.md`. It does not change a maintained reference or read sealed test data.
