# DokoDetector model operations

## First hop

From `operations/`:

- Owned source: `src/doko_operations/`.
- Tests: `tests/`.
- Public CLI: `mise exec -- uv run doko --help`.
- Boundary: own repository data lifecycle, model operations, and reconstruction orchestration;
  backend and other components consume these operations.
- Local checks:

  ```bash
  mise exec -- uv run pytest
  mise exec -- uv run ruff check .
  mise exec -- uv run ruff format --check .
  ```

Use the [repository documentation route](../README.md#documentation-route) for architecture, work
state, shared contracts, and component boundaries. This guide owns the `doko` command details.

## Supported CLI

The retained `doko` commands are grouped by owner:

- `doko data`: `status`, `validate`, `cardevent audit`, `cardevent migrate`, `cardevent readiness`, `cardevent freeze`, `resilience-baseline`,
  `resilience-comparison`, `complete-video`, `adopt-evidence`, `holdout seal`, `impact`, and
  `source retire`.
- `doko model`: `status`, `compare`, `improve`, `promote`, and `evaluate-system`.
- `doko reconstruct`: `round`.

Run `mise exec -- uv run doko <command> --help` for a top-level command or
`mise exec -- uv run doko data <command> --help` for a nested command. Operations owns data
lifecycle, model operations, resilience checks, and reconstruction orchestration. Use the
[recording workspace](../web/README.md#local-development) for recording-pipeline review.

M0 provides strict local contracts and read-only inspection for model-improvement campaigns.

Epic 0063 M0 provides a read-only audit of the legacy CardEventNet tree. It records every source,
annotation, review, split, manifest, cache, and output path with its digest, intended disposition,
and destination. It reconciles these paths with shared recording bundles, event revisions,
maintained references, development assignments, system holdouts, and model campaigns. Annotation
presence is separate from maintained-reference completion:

```bash
doko data cardevent audit --repository-root . --legacy-root card_event_net/data
doko data cardevent audit --repository-root . --format json
```

The audit does not migrate, repair, or delete data. Its JSON output is deterministic and includes
the `remaining_imports` list and item-level discrepancies for M1.

M1 migrates the complete readable legacy source corpus into shared recording bundles. It retains
the original annotation bytes and metadata under `data/operations/cardeventnet-imports/`, publishes
unreviewed event revisions, and creates draft maintained references. A parity receipt is written
only after source count, byte length, and source digest checks pass:

```bash
doko data cardevent migrate \
  --repository-root . \
  --legacy-root card_event_net/data \
  --operator <name>
```

The operation is resumable and a completed invocation is a no-op. Missing annotations remain
explicit draft gaps. The command does not certify review or remove the legacy tree.

M2 provides a read-only human-review queue over the shared CardEventNet recordings. It separates
missing annotations from imported annotations that still need a person to review the complete
source video. Each queued item includes the recording-workspace route, review progress, and
secondary eligibility blockers:

```bash
doko data cardevent readiness --repository-root .
doko data cardevent readiness --repository-root . --format json
```

After the operator completes the queued reviews, write an integrity-checked readiness receipt in
one explicit operation. The receipt does not change the report or certify any review by itself:

```bash
doko data cardevent readiness --repository-root . --operator <name>
```

Use `--receipt <path>` to select a different receipt path. The recording workspace completes a
maintained event reference only after every event has a decision and the person records full-source
coverage. An empty event reference is valid when the person reviewed the complete recording and
confirmed that it contains no card-state changes.

M3 freezes one immutable dataset version only when readiness, source metadata, event revisions, and
the active group-safe split pass validation. The command seals the test partition before training
and writes `dataset.json`, `split.json`, `coverage.json`, and a freeze receipt below
`data/operations/cardevent-datasets/<dataset-version-id>/`:

```bash
doko data cardevent freeze --repository-root . --operator <name>
doko data cardevent freeze --repository-root . --operator <name> --format json
```

The command returns the exact missing inputs and writes no dataset when the freeze is blocked.

```bash
doko model status
doko model status --format json
doko model compare <campaign-id>
```

The default paths are `data/model-registry.json` and `data/model-campaigns/`. Use
`--model-registry` and `--campaign-root` to inspect a fixture or another checkout. These commands
do not train, export, promote, or modify campaign and registry files.

## Visible-region identity resilience baseline

M0 freezes the crop, corruption, classifier, budget, metric, and decision-gate contract. It scans
accepted recording bundles and completed maintained references, then reports sample-linked coverage.
It does not classify validation crops or modify source data:

```bash
doko data resilience-baseline --format json \
  --output data/operations/visible-region-identity-resilience-m0.json
```

The command exits with `1` when the paired-reference coverage gate is not met. It requires paired
completed maintained visible-card and visual identity references from at least two source-lineage
groups and the frozen validation sample minimum before validation classification is allowed.

M2 provides the shared deterministic crop boundary used by the later paired run. It supports raw,
predicted-region, oracle, and generated or reviewed neighboring-region exclusion conditions. It
keeps source geometry immutable, records exclusion decisions, and generates seeded corruptions with
source and output geometry digests. It does not classify crops or change the runtime default.

M3 provides the guarded paired comparison boundary. It keeps `classified`, `unusable`, and
`failed` outcomes in their required denominators, reports actual Gemini regions separately from
synthetic corruptions, calculates paired recovery and harm, and writes item-level row artifacts for
local inspection:

```bash
doko data resilience-comparison \
  --manifest data/operations/visible-region-identity-resilience-m0.json \
  --rows data/operations/visible-region-identity-resilience-m3-rows.json \
  --output data/operations/visible-region-identity-resilience-m3
```

The command stops before classification when the M0 coverage gate is false. It does not tune or
change the configured identifier.

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

## CardEventNet frozen trainer views

The CardEventNet campaign consumes a frozen dataset from shared operations data. Materialize its
disposable trainer view before a direct local run:

```bash
mise exec -- uv run --project operations doko data cardevent materialize \
  --repository-root . \
  --dataset data/operations/cardevent-datasets/<dataset-version-id>
```

The view is written below `.runtime/cardevent/datasets/<dataset-version-id>/`. It contains linked
source videos, generated V2 annotations, the trainer split, a cache directory, and a digest-backed
`materialization.json`. Pass the view to CardEventNet commands:

```bash
mise exec -- uv run --project card_event_net cardevent prepare --dataset-view <view>
mise exec -- uv run --project card_event_net cardevent train \
  --config card_event_net/configs/base.yaml \
  --dataset-view <view>
mise exec -- uv run --project card_event_net cardevent evaluate \
  --checkpoint <best.pt> --dataset-view <view> --partition val
```

The campaign runner materializes the frozen dataset and passes only `--dataset-view` to
prepare/train/evaluate/diagnose and hard-negative mining. It records the dataset, split, source,
event-reference, materializer, preprocessing, code, and environment identity in campaign run
artifacts. It does not use `card_event_net/data` as an implicit campaign input.

## Epic 0063 M5 validation campaign

The checked-in M5 recipe runs one bounded CPU/FP32 candidate against the current champion on the
frozen validation partition:

```bash
mise exec -- uv run --project operations doko model improve card-event-net \
  --repository-root . \
  --recipe experiments/cardevent/0063-m5-validation.yaml \
  --device cpu \
  --precision fp32
```

The runner prepares only `train` and `val` caches for campaign selection. It never evaluates the
sealed `test` partition or the system holdout. Repeat the same command to resume completed work.
The campaign retains the resolved recipe, command logs, champion and candidate evaluations,
diagnostics, comparison, and candidate run references below `data/model-campaigns/`.

M5 adds a read-only composed evaluation on the plan 0027 system holdout. Both component campaigns
must have a candidate lock. Pass the frozen dataset and split manifests for each component:

```bash
doko model evaluate-system <cardevent-campaign> <table-campaign> \
  --holdout-registry data/operations/system-holdout-registry.json \
  --cardevent-dataset <cardevent-dataset.json> \
  --cardevent-split <cardevent-split.json> \
  --table-dataset <table-dataset.json> \
  --table-split <table-split.json>
```

The command also checks the locked reconstruction configuration and the local game-engine fixture.
It writes a separate system report under `data/model-system-evaluations/`. It does not update a
component campaign, start a candidate, or change the champion registry. Use `--runner` only through
the fixture path in local tests; `--fail-boundary event`, `--fail-boundary observation`, and
`--fail-boundary reconstruction` exercise report attribution.

## Round reconstruction harness

The local harness reconstructs one round from explicit round setup and stored
`table-observation/v1` documents. It does not stream, query the backend, or infer round membership.
Run it from the `operations` directory:

```bash
cd operations
mise exec -- uv run --no-sync doko reconstruct round \
  --request /path/to/round-request.json
```

The request file is strict JSON. Relative observation paths and `output_root` are resolved from the
request file's parent directory, so the command does not depend on the current working directory.
Backend callers use the same orchestration through
`doko_operations.round_reconstruction_execution.run_round_reconstruction_values(request, source_paths, output_root)`. The
validated request supplies stable source labels and search limits; the explicit paths identify the
stored observation files and artifact root.
The following is a complete request shape:

```json
{
  "schema_version": "round-reconstruction-run/v1",
  "run_id": "example-round-01",
  "round_setup": {
    "game_id": "game-01",
    "round_id": "game-01-round-01",
    "ruleset": {"name": "doko-normal", "version": "v1"},
    "deck_variant": "doko-40-v1",
    "active_players": ["player-01", "player-02", "player-03", "player-04"],
    "dealer": "player-04",
    "first_trick_leader": "player-01"
  },
  "observation_paths": [
    "observations/observation-001.json",
    "observations/observation-002.json"
  ],
  "search": {
    "max_missing_plays": 1,
    "max_hypotheses": 256,
    "max_search_nodes": 250000
  },
  "output_root": "artifacts/round-reconstruction"
}
```

Each observation path must identify an unchanged, valid `table-observation/v1` document. A
backend-persisted document is normally at
`<runtime-root>/table-observations/<observation-id>/observation.json`. The request must contain at
least one unique path. Observations must use one session, have unique observation IDs, strictly
increasing `session.event_sequence` values, and nondecreasing `observed_at_ms` values. The request
order is preserved; invalid order is reported instead of sorted. The three search limits are
required: `max_missing_plays` is nonnegative, and `max_hypotheses` and `max_search_nodes` are
positive.

The command publishes `<output_root>/<run_id>/` with these files:

| File | Contents |
| --- | --- |
| `input.json` | Canonical `round-reconstruction-input/v1` assembled from the setup and observations. |
| `result.json` | Canonical `round-reconstruction-result/v2` with `schema_version`, `run_id`, `operations_version`, the canonical request SHA-256, ordered `sources`, requested `search` limits, engine `status`, scored per-action hypothesis explanations, `focused_decisions`, and `diagnostics`. |

Each `sources` entry records the request path, observation ID, exact source byte length, and
source-byte SHA-256. The artifacts contain no absolute paths, timestamps, host data, or generated
confidence values. The source observations are not rewritten or copied. A clean rerun with the same
request content and source bytes produces byte-identical artifacts.

All four engine outcomes—`resolved`, `ambiguous`, `incomplete`, and `impossible`—use exit code `0`.
The command prints the artifact directory and status. Invalid request or source data, grouping or
ordering errors, an existing target directory, and other publication failures use exit code `2`
with one error on standard error. A failed run does not leave its final artifact directory, and an
existing directory is never replaced.

For an `ambiguous` result, inspect `focused_decisions` first. It lists the smallest decisions that
differ between retained reconstruction hypotheses. Use `jq` to inspect those decisions together
with the relevant hypothesis summaries:

```bash
jq '{status, focused_decisions,
     hypotheses: [.hypotheses[] | {
       gameplay, source_observation_ids, missing_play_indices, actions, total_score,
       score_breakdown
     }]}' \
  artifacts/round-reconstruction/example-round-01/result.json
```
