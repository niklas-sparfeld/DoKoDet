# CardEventNet M12 timing-response handoff

- Campaign: `cardeventnet-0063-m12-timing-response`
- Source M11 campaign: `cardeventnet-0063-m9-hard-negative-ablation`
- Selected response: `interval_endpoint_focus_v1`
- M11 selected no decoder, so this is the single interval-aware fallback response.
- Sealed test read: `false`
- System holdout read: `false`
- Training started: `false`

## Response contract

The response keeps the M9 checkpoint architecture, causal eight-frame clip, full-clip temporal head, decoder, threshold-selection procedure, seed, device, precision, hard-negative manifest, and source partition policy. It changes only the stable-end positive timing window:

| Setting | M9 baseline | M12 response |
| --- | ---: | ---: |
| `labels.positive_window_s` | 0.250 s | 0.125 s |
| `labels.negative_past_exclusion_s` | 0.350 s | 0.350 s |
| interval interior | ignored | ignored |
| decoder | current causal peak | current causal peak |

The interval interior is never relabeled as an ordinary or hard negative. Point events, close valid events, stable-end anchors, and causal emission remain separate validation checks in M13.

## Declared M13 validation gates

| Metric | Gate |
| --- | --- |
| `stable_end_matches` | ≥ 60 |
| `confirmed_no_event_triggers` | ≤ 20 |
| `duplicate_detections_per_reviewed_change` | ≤ 32 |
| `causal_emission_delay_p95_s` | ≤ 0.75 |
| `event_presence_recall` | ≥ 0.98 |

## Operator commands

M12 prepares these commands and stops. The operator starts the bounded command, with a fixed wall-clock budget of 12 hours, and resumes it only with the command below when required.

Materialize the successor view and prepare only train and validation caches:

```bash
mise exec -- uv run --project operations doko data cardevent materialize --repository-root . --dataset data/operations/cardevent-datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569/dataset.json --output .runtime/cardevent/datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569
mise exec -- uv run --project card_event_net cardevent prepare --dataset-view .runtime/cardevent/datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569 --partition train val
```

Start training once:

```bash
mise exec -- uv run --project card_event_net cardevent train --config data/model-campaigns/cardeventnet-0063-m12-timing-response/interval-endpoint-focus-v1.yaml --output-dir data/model-campaigns/cardeventnet-0063-m12-timing-response/runs --run-name candidate-interval-endpoint-focus-v1 --seed 42 --dataset-view .runtime/cardevent/datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569 --device mps --precision fp32 --hard-negative-manifest data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/reviewed-hard-negatives.json
```

Resume from the last checkpoint if the bounded run stops:

```bash
mise exec -- uv run --project card_event_net cardevent train --config data/model-campaigns/cardeventnet-0063-m12-timing-response/interval-endpoint-focus-v1.yaml --seed 42 --dataset-view .runtime/cardevent/datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569 --device mps --precision fp32 --hard-negative-manifest data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/reviewed-hard-negatives.json --resume data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/last.pt
```

After training completes, evaluate validation and write diagnostics:

```bash
mise exec -- uv run --project card_event_net cardevent evaluate --checkpoint data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/best.pt --dataset-view .runtime/cardevent/datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569 --partition val --out data/model-campaigns/cardeventnet-0063-m12-timing-response/validation-evaluation.json --device mps
mise exec -- uv run --project card_event_net cardevent diagnose --checkpoint data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/best.pt --dataset-view .runtime/cardevent/datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569 --out data/model-campaigns/cardeventnet-0063-m12-timing-response/diagnostics.json
```

Do not read the sealed test partition, system holdout, or export in M12. M13 must validate output completeness and lineage before reading the validation metrics.

## Expected completion artifacts

- `data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/config.yaml`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/environment.json`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/sampling.json`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/best.pt`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/last.pt`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/runs/candidate-interval-endpoint-focus-v1/summary.json`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/validation-evaluation.json`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/validation-evaluation-transition-diagnostics.json`
- `data/model-campaigns/cardeventnet-0063-m12-timing-response/diagnostics.json`

M12 did not start or monitor the long-running command.
