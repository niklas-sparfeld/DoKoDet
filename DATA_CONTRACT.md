# DokoDetector data contract

This document defines the shared data contract for source data and dataset versions. The typed
Python models live in `card_event_net/src/cardevent/data_contract.py`.

The shared repository intake bundle and independent task-enrollment contracts are documented in
[Repository Intake Contract](docs/Repository_Intake_Contract.md). They are separate from dataset
eligibility and do not treat proposal generator output as ground truth.

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

## Source intake boundary

Shared source bytes use repository-root paths. A pending upload stays outside intake until an
operator supplies complete metadata and both task enrollments:

```text
data/incoming/videos/<upload-id>/             pending upload
data/intake/recordings/<recording-id>/        complete recording bundle
data/intake/evidence-packages/<package-id>/   accepted evidence package
backend/.runtime/                             disposable backend state
```

A pending upload records its digest, byte length, media facts, and completion state. It is not a
recording, an evidence package, or an input to review or dataset assembly. An accepted evidence
package is immutable source input. Its package bytes remain available when the backend rebuilds its
SQLite index or its runtime directory is deleted.

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

## Table-observation annotation contract

The `table-observation-annotation/v1` contract describes one annotation set. An annotation set
keeps the human event review separate from visual card evidence. It can contain several observed
cards, each with frame boxes, visibility, quality tags, newly-visible, active-area, movement,
occlusion, and optional card-tracklet fields. A visible card does not assert that a card was played.

The recording pipeline owns creation, review, dataset assembly, and split validation for these
annotations. The superseded CardEventNet package import, local review, and package-backed dataset
lifecycle commands are removed. The schema remains available to the recording-pipeline contract
and its validation tests.

## Lifecycle receipts

`lifecycle-receipt/v1` records one immutable data operation. It contains semantic references for
inputs, outputs, and dependencies. A reference has a kind, an operator-owned identifier, and an
optional content digest. Source references use the source SHA-256. Dataset and split references use
their version digests.

CardEventNet supports source-import receipts at this boundary:

```text
source_import
```

The normal operator flow is documented in [Data_Lifecycle.md](docs/Data_Lifecycle.md). The
`ingest` command writes a source import receipt beside the ingestion index. Dataset, split, model
run, and source-retention records belong to the recording pipeline and operations boundaries.

Receipts do not make source bytes mutable or promote draft annotations.

## Repository intake bundle

Shared app recordings use the frozen schemas in `schemas/repository-intake/`:

- `repository-bundle-v1.schema.json` describes the complete immutable member set;
- `source-record-v1.schema.json` records source permission, retention, and collection metadata;
- `task-enrollment-v1.schema.json` records the initial independent data-task enrollments;
- `proposal-generator-run-v1.schema.json` records proposal lineage and probability output.

The replacement fixtures in `fixtures/repository-bundle/v1/` are complete bundle inputs. Their
video, source record, enrollment, and proposal bytes are immutable. The manifest records each
member length and SHA-256 digest. Proposal output is lineage-only and is not a human annotation or
training label.

Accepted evidence packages use these additional frozen schemas:

- `evidence-package-bundle-v1.schema.json` hashes the complete package member set;
- `evidence-package-record-v1.schema.json` records permission, allowed uses, retention, and source
  identity;
- `evidence-package-lineage-v1.schema.json` links the package to its parent recording and source
  asset when known.

The canonical package layout is:

```text
manifest.json
evidence-manifest.json
package-record.json
initial-task-enrollment.json
lineage.json
frames/<part-name>.jpg
video/<part-name>.mp4                  optional
```

The package record and task-enrollment documents are independent of the evidence manifest. The
enrollment document has one entry for each supported data task. A task adapter may read a package
only when its enrollment has `disposition: selected`. A selected package still needs human review
before it can enter a dataset.
