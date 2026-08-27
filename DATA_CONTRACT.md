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
