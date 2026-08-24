# CardEventNet data and model lifecycle

This guide is for data contributors. Run all commands from `card_event_net/`.

```text
source video -> manifest and index -> annotations, cache, and split -> model run
     -> validation and diagnostics -> human review -> new annotation version
     -> retrained model -> held-out test -> optional Core ML export
```

Keep the raw videos unchanged. Keep each annotation version in a separate directory. Use the
same split when you compare model runs. Do not use the test partition to select a model,
threshold, or training change.

## 1. Register source videos

First, record the session, game, capture context, source, and usage permission in an operator
metadata YAML file. The [video metadata guide](CardEventNet_VideoMetadata.md) defines the fields
and controlled values. Put shared values under `defaults`. Put video-specific values under
`videos`, keyed by the source file stem, such as `game01`.

```bash
uv run cardevent ingest data/raw \
  --operator-metadata data/operator-metadata.yaml \
  --manifest data/datasets/batch-2026-08-24/manifest.yaml \
  --index data/datasets/batch-2026-08-24/ingestion-index.json \
  --artifact-dir data/datasets/batch-2026-08-24/previews

uv run cardevent inspect-dataset \
  data/datasets/batch-2026-08-24/ingestion-index.json \
  --duplicate-status near_duplicate
```

Check the generated metadata and duplicate findings. Fix operator metadata and run ingestion
again when necessary. Do not edit technical probe results by guesswork. See
[plan 0008, phase 2](plans/0008-CardEventNet_TrainingDataImprovements.md#phase-2-build-ingestion-and-dataset-indexing-tooling)
for the ingestion artifact contract.

## 2. Annotate and prepare the dataset

Annotate every accepted video. Follow the
[labeling guidelines](CardEventNet_LabelingGuidelines.md) for event type and time decisions.

```bash
uv run cardevent annotate data/raw/game01.mov
uv run cardevent prepare --videos data/raw/*
uv run cardevent split \
  --manifest data/datasets/batch-2026-08-24/manifest.yaml \
  --group-by session_id \
  --out data/splits/batch-2026-08-24.yaml
```

`prepare` creates the frame cache. `split` keeps one recording session in one partition. It also
rejects a real game that crosses partitions. Treat the manifest, annotation directory, cache,
and split as one data version.

## 3. Train a model

Start with a small local check. Remove `--max-samples` for the full run.

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/batch-2026-08-24.yaml \
  --max-samples 32
```

Each run directory contains its config, environment, checkpoints, metrics, plots, and selected
validation threshold. The [CardEventNet README](../card_event_net/README.md#training) describes
the run artifacts and resume options.

## 4. Evaluate and diagnose

Evaluate validation data first. Then compare training and validation behavior. Use the missed
and false event timestamps to decide what needs human review.

```bash
uv run cardevent evaluate \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/batch-2026-08-24.yaml \
  --partition val

uv run cardevent diagnose \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/batch-2026-08-24.yaml
```

You can also generate training-only hard-negative candidates:

```bash
uv run cardevent mine-hard-negatives \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/batch-2026-08-24.yaml
```

These outputs are candidates, not corrected ground truth. A person must review ambiguous model
and annotation cases.

## 5. Review and publish new labels

Create a deterministic queue, review its source frames, and apply complete decisions to a new
annotation directory.

```bash
uv run cardevent review-queue \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/batch-2026-08-24.yaml \
  --partition val \
  --out data/outputs/run-.../review-val.json

uv run cardevent review \
  --queue data/outputs/run-.../review-val.json \
  --out data/reviews/review-val-alex.json \
  --videos-dir data/raw \
  --annotations-dir data/annotations \
  --reviewer alex

uv run cardevent apply-review \
  --queue data/reviews/review-val-alex.json \
  --annotations-dir data/annotations \
  --out-dir data/annotations-val-reviewed \
  --videos-dir data/raw \
  --dry-run
```

Check the dry-run summary. Then remove `--dry-run` to write the new version. Review the training
queue next, and apply it on top of `data/annotations-val-reviewed`. The result is
`data/annotations-next`. The [review workflow](CardEventNet_ReviewWorkflow.md) gives the complete
validation-first and training-second sequence. It also explains hard-negative isolation.

## 6. Retrain and lock the result

Build a separate cache for the new labels. Then train with the same split and the reviewed
training hard negatives.

```bash
uv run cardevent prepare \
  --videos data/raw/* \
  --annotations-dir data/annotations-next \
  --cache-dir data/cache-next

uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/batch-2026-08-24.yaml \
  --annotations-dir data/annotations-next \
  --cache-dir data/cache-next \
  --hard-negative-manifest data/annotations-next/training-hard-negatives.json
```

Repeat validation, diagnostics, and review only when the result justifies another data change.
After all choices are fixed, run the held-out test once:

```bash
uv run cardevent evaluate \
  --checkpoint data/outputs/run-next/best.pt \
  --split data/splits/batch-2026-08-24.yaml \
  --partition test
```

If the model passes the agreed gates, export it for the app. See the
[Core ML export guide](../card_event_net/README.md#core-ml-export).
