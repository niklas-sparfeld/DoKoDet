# CardEventNet

CardEventNet detects meaningful visible card-state changes. A detected event triggers a new
table-state evaluation. Every generated proposal uses the generic event type
`card_state_changed`; it does not claim a card play, a card side, or another gameplay meaning.

Run the commands below from the repository root. Use
`mise exec -- uv run --project card_event_net cardevent ...` for the CardEventNet CLI.

## First hop

From the repository root:

- Owned source: `src/cardevent/`.
- Tests: `tests/`.
- Public CLI: `mise exec -- uv run --project card_event_net cardevent --help`.
- Boundary: read source videos and selected evidence, then emit event proposals for the recording
  pipeline.
- Local checks:

  ```bash
  mise exec -- uv run --project card_event_net pytest
  mise exec -- uv run --project card_event_net ruff check card_event_net/src card_event_net/tests
  mise exec -- uv run --project card_event_net ruff format --check card_event_net/src card_event_net/tests
  ```

Use the [repository documentation route](../README.md#documentation-route) for architecture, work
state, shared contracts, and repository intake. Use the [CardEventNet data and model
lifecycle](../docs/CardEventNet_DataAndModelLifecycle.md) for component-specific model work.

## Current state

New annotations and caches use the full frame. They do not require a selected ROI. New training
runs and Python inference require the preprocessing identifier `full_frame_letterbox_v1`. Legacy
ROI annotations still load, but their geometry does not control preprocessing.

Frozen campaign runs use a disposable view created by the operations project. Build it with
`doko data cardevent materialize`, then pass the view to `prepare`, `train`, `evaluate`, or
`diagnose` with `--dataset-view`. The view supplies the videos, V2 annotations, split, and cache
under `.runtime/cardevent/datasets/<dataset-version-id>/`; it is derived input, not a source or
annotation authority. Training checkpoints and evaluation reports retain the view's dataset,
split, source, event-reference, materializer, preprocessing, code, and environment identity.

When a campaign prepares a frozen view, it selects only the development partitions:

```bash
  mise exec -- uv run --project card_event_net cardevent prepare --dataset-view <view> --partition train val
```

Preparing `test` is a separate explicit action. The M5 campaign does not prepare or evaluate that
partition.

The checked-in Core ML model and the iOS probe still use the legacy ROI contract. Do not combine
them with a new full-frame checkpoint. [Plan 0013](../docs/plans/5-closed/0013-CardEventNet_FullFrameInput.md)
tracks the remaining retraining and iOS migration.

This repo has the model, annotation, inference, evaluation, hard-negative, and Core ML export
pipeline:

- project metadata
- config loading
- device selection
- annotation schema and validation
- video metadata reading
- OpenCV annotation tool
- 10 fps cached frame extraction
- causal 8-frame dataset sampling
- positive, negative, ignored, and confirmed-hard-negative label states
- deterministic video-level and session-aware train/val/test splits
- temporally consistent training transforms
- MobileNetV3-Small spatial backbone
- causal Conv1D temporal head
- two-stage freeze and fine-tune training
- timestamped checkpoints and run metadata
- full-video causal inference at 8 Hz
- threshold-independent peak extraction and temporal suppression
- exact validation threshold selection from candidate-peak scores
- event recall, precision, false/hour, and latency metrics
- probability and threshold plots
- classical cached-frame motion baseline
- hard-negative mining from false triggers on training videos
- optional repeated hard-negative sampling during training
- fixed-shape Core ML export with optional PyTorch parity verification
- saved validation streams for decoder-only evaluation
- test and lint setup

## Supported CLI

The retained `cardevent` commands are `annotate`, `extract-evidence`, `prepare`, `make-split`,
`split`, `train`, `infer`, `evaluate`, `transition-diagnostics`, `diagnose`, `baseline`,
`mine-hard-negatives`, `export-coreml`, `ingest`, and `inspect-dataset`. Run
`mise exec -- uv run --project card_event_net cardevent <command> --help` for one command.

CardEventNet owns source-video intake, event annotation, proposal generation, model training, and
model evaluation. It does not own recording-pipeline review or table-observation dataset assembly.
Use the [recording workspace](../web/README.md#local-development) for pipeline review.

The annotation tool stores one JSON file per source video in `.runtime/cardevent/annotations/` by
default. New files use annotation V2 and contain saved events without geometry. Every event uses
the single active type
`card_state_changed`. It records a persistent card-related table-state change that can justify
another table observation. Uncertain, ignored, and proposed annotations are excluded. Use the
repository's [labeling guidelines](../docs/CardEventNet_LabelingGuidelines.md) for event,
timestamp, close-event, and hard-negative decisions.

Without an explicit annotation directory, the tool writes disposable annotations below
`.runtime/cardevent/annotations/`. It never writes annotations into a recording bundle or the
legacy `card_event_net/data` tree.

Annotation controls:

```text
SPACE   mark a card-state change, or keep the event at the same timestamp
W / S   jump to the previous or next saved event
, / .   move the selected event one frame backward or forward
U       mark the selected event or selected proposal uncertain
N / B   jump to next or previous model proposal
C       toggle before/after comparison
P       pause or play
A / D   seek backward or forward about 250 ms
J / L   seek backward or forward about 2 s
BACKSPACE or X  remove the selected event
Q       save and exit
```

The selected saved event follows the current video timestamp. The overlay shows its timestamp and
the card-state-change label.

## Setup

If `uv` is not available yet, run `mise install` first so the toolchain from `mise.toml` is ready.

```bash
uv sync --project card_event_net
```

Core ML export is optional and requires macOS:

```bash
mise install
uv sync --project card_event_net --extra coreml
```

The project pins Python 3.13, PyTorch 2.7.0, torchvision 0.22.0, and coremltools 9.0.
These versions provide the native macOS Core ML modules and a tested PyTorch converter.

## Annotation

Run the annotator against a canonical recording source:

```bash
mise exec -- uv run --project card_event_net cardevent annotate \
  data/intake/recordings/<recording-id>/videos/<video-id>.mov
```

The tool shows the event definition at startup. You can label a new video immediately. You can
quit and reopen the same video later. Existing events stay in the JSON file.

Review model candidates with an inference JSON file:

```bash
mise exec -- uv run --project card_event_net cardevent annotate \
  data/intake/recordings/<recording-id>/videos/<video-id>.mov \
  --proposals data/intake/recordings/<recording-id>/predictions/<proposal-run-id>.json
```

The annotator does not save model proposals automatically. Press `Space` to confirm one at the
current timestamp. Press `U` to save it as uncertain instead. Use a new annotation directory when
you need to preserve the source version.

## Extract evidence from reviewed annotations

Create source-resolution evidence packages around reviewed `card_state_changed` timestamps:

```bash
mise exec -- uv run --project card_event_net cardevent extract-evidence \
  --videos-dir <explicit-video-directory> \
  --annotations-dir <explicit-annotation-directory> \
  --manifest <explicit-v1-manifest> \
  --split <explicit-historical-split> \
  --partition train val \
  --out .runtime/cardevent/outputs/annotation-evidence-v1
```

The command extracts the six target offsets `[-800, -400, -100, 150, 400, 700] ms` by default. Use
`--target-offset-ms 0` for the exact reviewed event frame used by the first TableEvidenceAnalyzer
visible-card baseline. Repeat the option to select several offsets. The command includes card-state
events whose confidence is absent or `confirmed`. It excludes uncertain, ignored, proposed, and
non-card-state events.

Each output package contains a `cardevent-evidence/v2` manifest and source-resolution JPEGs. The
root `extraction-manifest.json` records source-video, annotation, event, session, split,
configuration, and digest lineage. The example excludes the test partition. Annotation-derived
packages are local derived artifacts. This command does not put them into repository intake or
label their visual card identities.

Use `--video-id IMG_0654 IMG_0655` to extract a subset. The command refuses to replace an existing
output directory. Use a new versioned directory for another run.

## Evidence-package boundary

Accepted evidence packages remain immutable repository intake and showcase artifacts. They are not
an alternate CardEventNet review or table-observation dataset route. Use the [data lifecycle](../docs/Data_Lifecycle.md)
and [repository intake contract](../docs/Repository_Intake_Contract.md) for package layout,
enrollment, and intake state. A pending upload is not visible to a data task. An event proposal is
not a reviewed event and does not create a training label.

## Review a shared training recording

The backend stores each accepted recording once in the repository intake. CardEventNet reads the
canonical video and proposal files from that bundle. It does not copy them into
`card_event_net/data/raw/` or complete metadata in a second command. Review proposals with:

```bash
mise exec -- uv run --project card_event_net cardevent annotate \
  data/intake/recordings/<recording-id>/videos/<video-id>.mov \
  --proposals data/intake/recordings/<recording-id>/predictions/<proposal-run-id>.json \
  --annotations-dir .runtime/cardevent/annotations
```

For the local end-to-end gate, generate a short saved-video recording with the macOS simulator
client, then upload it with the durable recording queue:

```bash
swift run --package-path ../ios CardEventProbeLocalPipeline simulate-recording \
  --input-video path/to/saved-video.mov --root /tmp/cardevent-recording
swift run --package-path ../ios CardEventProbeLocalPipeline upload-recording \
  --root /tmp/cardevent-recording/training --server http://127.0.0.1:8000
```

## Runtime workspace and frozen training views

Direct-file commands use `.runtime/cardevent/` for annotations, caches, splits, and outputs by
default. These paths are disposable. Source videos remain in `data/intake/recordings/`; the
runtime workspace is not a second source authority.

For model work, materialize a frozen shared dataset first:

```bash
mise exec -- uv run --project operations doko data cardevent materialize \
  --repository-root . \
  --dataset data/operations/cardevent-datasets/<dataset-version-id>
```

Prepare and train from that view:

```bash
mise exec -- uv run --project card_event_net cardevent prepare \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id> \
  --partition train val
mise exec -- uv run --project card_event_net cardevent train \
  --config card_event_net/configs/base.yaml \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id>
```

Evaluate or diagnose the same view and checkpoint:

```bash
mise exec -- uv run --project card_event_net cardevent evaluate \
  --checkpoint <best.pt> \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id> \
  --partition val
mise exec -- uv run --project card_event_net cardevent diagnose \
  --checkpoint <best.pt> \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id>
```

The view supplies the source links, V2 annotations, split, and cache. Do not use
`card_event_net/data/raw`, `card_event_net/data/annotations`, `card_event_net/data/splits`, or
`card_event_net/data/outputs` as implicit campaign inputs. Those paths are migration-era data and
remain only until the reviewed legacy retirement step.

For one-off inference, pass a canonical recording video and an explicit runtime cache:

```bash
mise exec -- uv run --project card_event_net cardevent infer \
  --checkpoint <best.pt> \
  --video data/intake/recordings/<recording-id>/videos/<video-id>.mov \
  --cache-dir .runtime/cardevent/inference-cache \
  --out .runtime/cardevent/outputs/predictions.json
```

## Core ML export

Export a trained checkpoint on macOS:

```bash
mise exec -- uv run --project card_event_net cardevent export-coreml \
  --checkpoint <best.pt> \
  --out CardEventNet.mlpackage
```

Export accepts only a checkpoint with `full_frame_letterbox_v1` preprocessing. The package records
this identifier in its user-defined metadata. It has one fixed input named `clips` with shape
`[1, 8, 3, 224, 224]`. Input values must be ImageNet-normalized `float32` values. The output is
one raw logit named `logit`.
The v1 package also uses float32 computation to keep the converted logit close to PyTorch.
The command runs a deterministic PyTorch/Core ML parity check by default. Use
`--skip-parity` only when the Core ML prediction runtime is not available.

The current local workflow is:

```bash
mise install
mise exec -- uv run --project operations doko data cardevent materialize \
  --repository-root . \
  --dataset data/operations/cardevent-datasets/<dataset-version-id>
mise exec -- uv run --project card_event_net cardevent prepare \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id> \
  --partition train val
mise exec -- uv run --project card_event_net cardevent train \
  --config card_event_net/configs/base.yaml \
  --dataset-view .runtime/cardevent/datasets/<dataset-version-id>
mise exec -- uv run --project card_event_net cardevent export-coreml \
  --checkpoint <best.pt> \
  --out CardEventNet.mlpackage
```
