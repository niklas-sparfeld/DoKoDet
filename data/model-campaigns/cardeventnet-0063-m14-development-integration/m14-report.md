# CardEventNet M14 development integration lock

- Campaign: `cardeventnet-0063-m14-development-integration`
- Source campaign: `cardeventnet-0063-m9-hard-negative-ablation`
- Decision: `accepted_development_baseline`
- Production promotion eligible: `False`
- Integration lock: `data/model-campaigns/cardeventnet-0063-m14-development-integration/integration-lock.json`

The M9 hard-negative checkpoint is accepted as a development baseline for downstream table-observation and game-reconstruction measurement. It remains separate from the production champion and is not a promotion decision.

## Fixed configuration

- Checkpoint: `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt`
- Threshold: `0.4271905720233917`
- Decoder: `{'algorithm': 'causal_peak', 'peak_confirmation_s': 0.125, 'min_event_gap_s': 0.625, 'event_match_tolerance_s': 0.75}`
- Successor validation dataset: `{'dataset_sha256': 'f76a398ba06c483349ce3314935823a51601a4600aa5e426ac4f22dca43fd65e', 'digest': '00a59b5fcd210d23c569727f98453c77237bb2c2ae71ebfc0a69e9abf8e807ee', 'id': 'cardeventnet-interval-dataset-00a59b5fcd210d23c569', 'materialization_manifest_digest': 'e83a136b61d3149f76f90a090ad15b04fa4aea56ae4b00d89ab76276f6d06538', 'materialized_view': '.runtime/cardevent/datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569', 'path': 'data/operations/cardevent-datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569', 'split_digest': '939ecbcfa22d3658c966c383d24368f29ee915e4aa02be820fe2bf8f6f2c8fa0', 'split_id': 'cardeventnet-interval-split-939ecbcfa22d3658c966', 'split_sha256': '9459cf6566db27ec131ee9f0d8543f8a49e6cdea7ae1bb442ae3106011a99caf'}`

## Known failed production gates

- `stable_end_matches`: 49 >= 60 failed
- `confirmed_no_event_triggers`: 25 <= 20 failed
- `event_presence_recall`: 0.893548 >= 0.98 failed

## Operator order

1. Run the one-time sealed-test command in `sealed-test-handoff.json` once.
2. After it exits, run the Core ML export command with parity enabled in `export-parity-handoff.json`.
3. Stop. M15 validates the outputs; no command in M14 promotes the model.

Sealed-test handoff: `data/model-campaigns/cardeventnet-0063-m14-development-integration/sealed-test-handoff.json`
Export/parity handoff: `data/model-campaigns/cardeventnet-0063-m14-development-integration/export-parity-handoff.json`
