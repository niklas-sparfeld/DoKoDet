# DokoDetector model operations

M0 provides strict local contracts and read-only inspection for model-improvement campaigns.

```bash
doko model status
doko model status --format json
doko model compare <campaign-id>
```

The default paths are `data/model-registry.json` and `data/model-campaigns/`. Use
`--model-registry` and `--campaign-root` to inspect a fixture or another checkout. These commands
do not train, export, promote, or modify campaign and registry files.

M1 adds a resumable CardEventNet campaign runner:

```bash
doko model improve card-event-net --recipe experiments/cardevent/example.yaml
```

The runner writes the resolved recipe, champion and candidate validation evaluations,
`comparison.json`, `report.md`, `lock.json` when a candidate is recommended, and exact command
logs under `data/model-campaigns/<campaign-id>/`. It runs validation only. Use the fixture backend
for the local clean-room exercise:

```bash
doko model improve card-event-net \
  --recipe fixtures/model-improvement/v1/recipe-cardevent.json \
  --repository-root fixtures/model-improvement/v1/valid \
  --model-registry registry.json \
  --campaign-root /tmp/doko-model-campaigns \
  --runner fixture \
  --max-samples 2
```

Run the same command again to resume the campaign. Completed candidates are not run again.
