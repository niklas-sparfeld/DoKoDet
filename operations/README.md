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

M2 promotes a locked candidate only after an explicit confirmation. It runs the sealed test once,
checks Core ML export, runtime loading, parity, and the iOS input fixture, then updates the app
bundle and the component registry with compensation on failure:

```bash
doko model promote <campaign-id> \
  --candidate <candidate-id> \
  --confirm
```

Use `--runner fixture` for the local clean-room promotion. A successful retry reads the existing
promotion receipt and issues no new test, export, or registry command.

M3 adds the bounded TableEvidenceAnalyzer campaign adapter. It consumes explicit plan 0020
dataset, split, and sample-artifact files, then runs validation-only train, evaluate, and export
commands:

```bash
doko model improve table-evidence-analyzer \
  --recipe fixtures/model-improvement/v1/recipe-table-analyzer.json \
  --repository-root <repository> \
  --model-registry <registry.json> \
  --dataset <dataset.json> \
  --split <split.json> \
  --artifacts <artifact-index.json> \
  --runner fixture \
  --campaign-root <campaign-root>
```

The campaign records the `identity_candidates` capability, `table-observation/v1` output
contract, runtime compatibility, group support, and the validation comparison. It is scoped to
oracle-crop identity classification. It does not claim complete table analysis or use the test
partition.

M4 promotes a locked TableEvidenceAnalyzer candidate only when the resolved recipe authorizes a
sealed test. It evaluates the test partition once, exports and validates the portable bundle,
loads it through the training-free runtime interface, checks the plan 0006 observation fixture,
retains the former champion, and atomically updates only the analyzer registry entry:

```bash
doko model promote <campaign-id> \
  --repository-root <repository> \
  --model-registry <registry.json> \
  --campaign-root <campaign-root> \
  --runner fixture \
  --confirm
```

The promotion receipt records the old and new bundle digests. A repeated confirmed invocation
reads the receipt and does not rerun the test or export.
