# DokoDetector data contract

This document defines the shared data contract for source data and dataset versions. The typed
Python models live in `card_event_net/src/cardevent/data_contract.py`.

## Layers

The lifecycle has these layers:

```text
source -> annotations -> reviews -> dataset versions -> derived artifacts -> runs
```

The layers have different meaning.

- A source asset is immutable bytes. A source record stores its SHA-256 digest and byte length.
- An annotation set stores human claims about source evidence. It is not ground truth until review.
- A review records the decision and reviewer identity. A review does not edit source bytes.
- A dataset version freezes eligible entries and their source, annotation, review, and transform
  versions.
- A derived artifact records how it came from a source frame or other accepted input.

## Identifiers

Use the semantic identifiers defined by the data foundation plan:

```text
source_asset_id, session_id, game_id, round_id, recording_id, video_id,
evidence_package_id, event_id, frame_id, annotation_set_id, review_id,
dataset_version, split_version, derived_artifact_id, training_run_id, model_bundle_id
```

An identifier is operator-owned semantic data. It is not a local path and it is not a content
digest. A SHA-256 digest identifies bytes. Do not derive a session identity from a filename,
timestamp, recording UUID, or dataset partition.

## Source records

`source-record/v1` records:

- `source_asset_id`, `sha256`, and `byte_length`;
- media type, original filename, and acquisition method;
- session, recording, video, game, round, and table setup facts when known;
- content type, source permission, and explicit allowed uses;
- retention state and known notes.

The allowed uses are explicit: `train`, `validation`, `test`, or `evaluation`. A staged activity
has no invented game or round. Source records reject path-like identifiers and invalid SHA-256
digests.

The CardEventNet V1 adapter accepts a complete `DatasetRecord` plus measured byte length and SHA-256
metadata. It preserves the V1 session, game, content type, table setup, source permission, and file
facts. It requires allowed uses from the caller because the old manifest does not contain that
field.

## Lineage

`lineage/v1` stores directed edges from a parent to a derived child. The supported path is:

```text
session -> recording
source asset -> recording -> evidence package -> frame -> crop
evidence package -> annotation set -> crop
```

The `crop_from_frame` edge must record both its source frame and transform. A lineage graph can
walk from a crop to its immutable source asset. Cycles and duplicate edges are invalid.

## Eligibility

`eligibility/v1` uses these states:

```text
intake, annotating, review_required, reviewed, eligible, excluded, retired
```

An eligible item must name an annotation set and review, have `review_state: reviewed`, and state
an intended use that is present in its allowed uses. Excluded data must state a reason. Permission
and review state remain nested in dataset exports.

## Dataset versions

`dataset-version/v1` freezes eligible entries. Each entry contains:

- the source asset and source SHA-256;
- annotation-set and review identifiers;
- an eligibility snapshot;
- the target schema and transform version;
- session, game, table-setup, and source-lineage group keys;
- an inclusion reason.

The version also records the task, target schema, allowed-use filter, declared leakage groups,
deck and card-set versions, transform version, creation revision, and dirty-state marker.

The `dataset_version_digest` is the SHA-256 of canonical JSON. Object keys are sorted. Entries and
set-like fields are sorted for the digest. The semantic dataset identifier and creation timestamp
are not included in the digest. Therefore, equivalent inputs produce the same digest while a
different dataset identifier can still name the version in an operator workflow.

Serialization is strict. Unknown fields, unknown schema versions, missing required fields, changed
source digests, and ineligible dataset entries fail validation. Existing CardEventNet V1 manifests
remain valid through their existing loader and the explicit adapter.

## Local fixture

`card_event_net/tests/fixtures/data_contract/contract.json` links one session, recording, evidence
package, frame, annotation set, and crop to `source-video.bin`. Its test checks the source bytes,
lineage trace, permission, review state, export round trip, and deterministic dataset digest.

## Table-observation review

M2 adds table-observation-annotation/v1 for one annotation set. An annotation set keeps the human
event review separate from visual card evidence. It can contain several observed cards, each with
frame boxes, visibility, quality tags, newly-visible, active-area, movement, occlusion, and optional
card-tracklet fields. A visible card does not assert that a card was played.

Import accepted local evidence manifests as draft table observations:

```bash
uv run cardevent vision-import \
  ../fixtures/evidence/v2/example-complete/manifest.json \
  --out-dir data/table-observations
```

Use vision-review to inspect all frames in a local frame directory. The viewer writes a separate
table-observation-review/v1 artifact. Use vision-apply-review to create a new annotation directory.
The source annotation, evidence manifest, and review artifact are read only. The apply directory
contains the reviewed annotation, a copy of the review, and a table-observation-apply-receipt.json.

## M3 dataset assembly

The TableEvidenceAnalyzer identity-crop dataset is assembled from reviewed table-observation
annotations. One identity-usable frame observation becomes one manifest entry. The entry stores
the source frame, observed-card identifier, box, visual card identity, quality tags, source digest,
annotation set, review, transform, and leakage groups.

The assembler accepts only active source assets whose explicit allowed uses match the requested
filter. Draft annotations, missing reviews, missing source lineage, non-identifiable cards, and
sources outside the filter stay in explicit `unassigned` or `excluded` output. A false event
proposal can still contribute a visible-card sample. Its event decision is not a card label.

Build and validate a dataset with these commands:

```bash
uv run cardevent dataset-build \
  --annotations data/table-observations \
  --reviews data/table-observation-reviews \
  --sources data/sources.json \
  --lineage data/lineage.json \
  --dataset-version-id table-evidence-20260827 \
  --out data/datasets/table-evidence.json

uv run cardevent dataset-split \
  --dataset data/datasets/table-evidence.json \
  --split-version-id table-evidence-split-20260827 \
  --out data/datasets/table-evidence-split.json

uv run cardevent dataset-validate \
  --dataset data/datasets/table-evidence.json \
  --sources data/sources.json \
  --lineage data/lineage.json \
  --annotations data/table-observations \
  --reviews data/table-observation-reviews \
  --split data/datasets/table-evidence-split.json
```

The split uses connected session, game, table-setup, and source-lineage groups. It uses the
canonical `validation` partition name. A group cannot cross `train`, `validation`, `test`, or
`unassigned`. The dataset digest and split digest make later validation independent of local paths.

`dataset-build` writes `coverage.json`, `coverage.md`, and `assembly.json` beside the requested
report directory. Coverage includes event decisions, visible-card identities, visibility and
quality tags, crop sizes, selected frames, snippets, tracklets, source metadata, and every
unassigned or excluded item. These reports guide data collection. They do not rebalance a sealed
evaluation set.

## M4 lifecycle receipts

`lifecycle-receipt/v1` records one immutable data operation. It contains semantic references for
inputs, outputs, and dependencies. A reference has a kind, an operator-owned identifier, and an
optional content digest. Source references use the source SHA-256. Dataset and split references use
their version digests.

The supported receipt types are:

```text
source_import
evidence_import
annotation_application
dataset_creation
split_creation
training_run
retirement
```

The normal operator flow is documented in [Data_Lifecycle.md](docs/Data_Lifecycle.md). The
commands write receipts as follows:

- `ingest` writes a source import receipt beside the ingestion index;
- `vision-import` writes `table-observation-import-receipt.json` in its output directory;
- `vision-apply-review` keeps the table-observation apply receipt and nests the lifecycle receipt;
- `dataset-build` writes `dataset-creation-receipt.json` beside its reports;
- `dataset-split` writes a receipt beside the split file;
- `training-receipt` expands a dataset and split into all source, annotation, and review versions used;
- `retire-source` writes a new source-record state and reports affected derived artifacts and runs.

Receipts do not make source bytes mutable. They do not promote draft annotations. A retirement
operation changes only the source-record version and identifies downstream objects that need review.
It can use `deletion_requested` for a pending permission withdrawal or `retired` for a completed
withdrawal.

## Training recording bundle

Plan 0019 uses the versioned schemas in:

- `schemas/training-recording/recording-manifest-v1.schema.json` for the complete recording bundle;
- `schemas/training-recording/device-predictions-v1.schema.json` for device proposals and raw
  probability samples.

The small bundle in `fixtures/training-recording/v1/recording-fixture-001/` is the cross-component
contract fixture. Its video and prediction bytes are immutable inputs. The manifest records their
lengths and SHA-256 digests. Device predictions are provenance and event proposals, not human
annotations or training labels.
