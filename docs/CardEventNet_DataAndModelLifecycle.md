# CardEventNet data and model lifecycle

Run commands from the repository root. Shared source and review data have one canonical owner:

```text
data/intake/recordings/       immutable recording bundles and source videos
data/operations/              imported annotations, references, splits, and dataset versions
data/model-campaigns/         checkpoints, reports, and campaign lineage
.runtime/cardevent/           disposable annotations, caches, materialized views, and outputs
```

`card_event_net/data` was the legacy migration input. The repository tree is retired. New commands
must not use it as an implicit source, annotation, split, cache, or model-output root.

## Review a canonical recording

The backend stores each accepted video once below `data/intake/recordings/`. CardEventNet reads
that source and writes temporary annotation work below `.runtime/cardevent/annotations/`:

```bash
mise exec -- uv run --project card_event_net cardevent annotate \
  data/intake/recordings/<recording-id>/videos/<video-id>.mov \
  --annotations-dir .runtime/cardevent/annotations
```

Proposal JSON remains in the recording bundle and is passed explicitly with `--proposals`.
Annotation files are evidence for later review. They do not complete a maintained event
reference by themselves.

## Freeze a training view

Import the legacy corpus only through the operations migration:

```bash
mise exec -- uv run --project operations doko data cardevent audit \
  --repository-root . \
  --legacy-root /path/to/legacy/card_event_net/data
mise exec -- uv run --project operations doko data cardevent migrate \
  --repository-root . \
  --legacy-root /path/to/legacy/card_event_net/data \
  --operator <name>
```

The migration verifies source digests, publishes canonical recording bundles, and preserves
legacy annotations and other artifacts below `data/operations/cardeventnet-imports/`. It does not
delete the supplied legacy copy.

Freeze and materialize the active dataset through operations:

```bash
mise exec -- uv run --project operations doko data cardevent materialize \
  --repository-root . \
  --dataset data/operations/cardevent-datasets/<dataset-version-id>
```

The materialized view below `.runtime/cardevent/datasets/` is the only input for a current
training campaign. It contains linked source videos, generated V2 annotations, the approved split,
and a rebuildable frame cache.

## Prepare, train, and evaluate

```bash
mise exec -- uv run --project card_event_net cardevent prepare \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id> \
  --partition train val

mise exec -- uv run --project card_event_net cardevent train \
  --config card_event_net/configs/base.yaml \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id>

mise exec -- uv run --project card_event_net cardevent evaluate \
  --checkpoint <best.pt> \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id> \
  --partition val
```

The model campaign stores durable checkpoints and reports below `data/model-campaigns/`. Git tracks
selected PyTorch checkpoints with Git LFS. The materialized view and all direct-file caches remain
disposable. Do not train from the legacy split, annotation, or output paths.

## One-off inference

Pass the canonical source video and an explicit runtime cache:

```bash
mise exec -- uv run --project card_event_net cardevent infer \
  --checkpoint <best.pt> \
  --video data/intake/recordings/<recording-id>/videos/<video-id>.mov \
  --cache-dir .runtime/cardevent/inference-cache \
  --out .runtime/cardevent/outputs/predictions.json
```

The backend uses the same runtime cache boundary. It accepts an explicit
`CARD_EVENT_CHECKPOINT_PATH` or the digest-checked integration contract below
`data/model-campaigns/`; it does not search `card_event_net/data/outputs`.

## Legacy tree status

The repository's `card_event_net/data` tree was retired after the migration receipt passed source
parity, all legacy artifacts had a preserved destination or an explicit obsolete disposition, and
active consumers were checked. The former `card_event_net/data/cache/` directory was rebuildable
runtime state and was not shared data.
