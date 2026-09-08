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

- `doko data`: `status`, `validate`, `resilience-baseline`, `resilience-comparison`,
  `complete-video`, `adopt-evidence`, `holdout seal`, `impact`, and `source retire`.
- `doko model`: `status`, `compare`, `improve`, `promote`, and `evaluate-system`.
- `doko reconstruct`: `round`.

Run `mise exec -- uv run doko <command> --help` for a top-level command or
`mise exec -- uv run doko data <command> --help` for a nested command. Operations owns data
lifecycle, model operations, resilience checks, and reconstruction orchestration. Use the
[recording workspace](../web/README.md#local-development) for recording-pipeline review.

M0 provides strict local contracts and read-only inspection for model-improvement campaigns.

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
