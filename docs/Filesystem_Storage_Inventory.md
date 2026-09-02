# Filesystem storage inventory

This inventory is the M0 baseline and M4 completion record for epic 0046. It names the former SQL
tables, their field owners, their query consumers, and the canonical filesystem representation
that replaces each SQL read or write. The former SQL model and database are removed.

## Canonical resource roots

| Resource | Canonical root | Summary document | Mutability |
| --- | --- | --- | --- |
| Pending video | `data/incoming/videos/<upload_id>/` | `manifest.json` (`pending-video/v1`) | Mutable until intake |
| Recording bundle | `data/intake/recordings/<recording_id>/` | `manifest.json` (`repository-bundle/v1`) | Immutable after commit |
| Evidence package | `data/intake/evidence-packages/<package_id>/` | `manifest.json` (`evidence-package-bundle/v1`) | Immutable after commit |
| Operations data | `data/operations/` and its concrete store subdirectories | Each concrete store's `state.json` or named JSON document | Mutable or immutable per store |
| Table observation | `.runtime/table-observations/<observation_id>/` | `observation.json` (`table-observation/v1`) | Immutable after commit |
| Round analysis | `.runtime/round-analyses/<analysis_id>/` | `state.json` (`round-analysis-state/v1`) | State mutable; `input.json` and `result.json` immutable |

The backend resolves IDs below the configured root, validates the complete resource, and only then
returns it from a catalog. A directory with a staging prefix, a symlink, missing members, invalid
JSON, a failed digest, or an unsupported schema is not a valid resource.

## SQL tables and field ownership

### `evidence_packages` and `evidence_frames` (`0001_initial`)

Canonical owner: `data/intake/evidence-packages/<package_id>/`. Summary: `manifest.json`.
The original evidence metadata is `evidence-manifest.json`; package permission and lineage data
remain in `package-record.json`, `initial-task-enrollment.json`, and `lineage.json`.

| SQL field | Canonical value or derived value |
| --- | --- |
| `evidence_packages.package_id` | `manifest.json.package_id`, also `evidence-manifest.json.package_id` |
| `schema_version` | `evidence-manifest.json.schema_version` |
| `session_id` | `evidence-manifest.json.session.session_id` |
| `event_sequence` | `evidence-manifest.json.session.event_sequence` |
| `event_time_ms` | `evidence-manifest.json.event.event_time_ms` |
| `manifest_json` | Exact bytes of `evidence-manifest.json` |
| `manifest_sha256` | Digest of those canonical bytes |
| `package_fingerprint` | Deterministic digest of all bundle member paths, lengths, and digests |
| `state` | `manifest.json.state` |
| `received_at` | Earliest `initial-task-enrollment.json.enrollments[].created_at_utc` |
| `evidence_frames.part_name` | One `evidence-manifest.json.frames[]` entry |
| `target_offset_ms` | Frame entry `target_offset_ms` |
| `actual_offset_ms` | Frame entry `actual_offset_ms` |
| `session_elapsed_ms` | Frame entry `session_elapsed_ms` |
| `captured_at_utc` | Frame entry `captured_at_utc` |
| `content_type` | Frame entry `content_type` |
| `byte_length` | Frame entry `byte_length`, verified against `frames/<part_name>.jpg` |
| `sha256` | Frame entry `sha256`, verified against `frames/<part_name>.jpg` |
| `relative_path` | Canonical `frames/<part_name>.jpg` path |

Former SQL reads and consumers:

| SQL query behavior | Backend consumers |
| --- | --- |
| Insert package and frames; enforce package ID and `(session_id, event_sequence)` uniqueness | `api.py` upload route through `EvidencePackagePersister` |
| Get package by ID | `api.py`, `analyzer_runner.py`, `round_analysis_service.py`, `round_analysis_timeline.py` |
| List packages by intake order | `round_analysis_service.py` |
| Get package by logical event | `api.py` upload conflict handling |
| Delete package | `api.py` explicit deletion and persistence compensation |
| Find first/all stored packages without an analyzer observation | `analyzer_runner.py` |
| Get/list observation rows linked to a package | `api.py`, `analyzer_runner.py`, `round_analysis_timeline.py` |
| Insert/delete observation metadata and enforce `(package_id, analyzer_name, analyzer_version)` uniqueness | `TableObservationPersister`, analyzer runner, tests |
| Rebuild package and observation rows by scanning canonical files | `app.py` startup |

### `table_observations` (`0002_table_observations`)

Canonical owner: `.runtime/table-observations/<observation_id>/observation.json`. The observation
document is both the immutable summary and the complete value. Its digest and relative path are
derived from the file. `created_at` is the one new filesystem state field required by the store;
M2 must persist it without changing the analyzer observation contract.

| SQL field | Canonical value or derived value |
| --- | --- |
| `observation_id` | `observation.json.observation_id`, matched to the directory ID |
| `package_id` | `observation.json.source.package_id` |
| `schema_version` | `observation.json.schema_version` |
| `analyzer_name` | `observation.json.analyzer.name` |
| `analyzer_version` | `observation.json.analyzer.version` |
| `status` | `observation.json.status` |
| `calibration` | `observation.json.calibration` |
| `observation_json` | Exact canonical bytes of `observation.json` |
| `observation_sha256` | Digest of those canonical bytes |
| `relative_path` | `table-observations/<observation_id>/observation.json` |
| `created_at` | UTC modification time of the committed immutable `observation.json` file |

The uniqueness rule remains `(package_id, analyzer_name, analyzer_version)` until plan 0047.

### `training_recordings` (`0003_training_recordings`)

This migration has no active model, repository, API route, or runtime query. It represents the
superseded training-recording contract. Do not import its SQL-only rows. The legacy fixture
counterpart is `fixtures/training-recording/v1/<recording_id>/manifest.json` plus its prediction
JSON, but new runtime code uses the accepted recording-bundle contract.

| SQL field | Legacy fixture value or M4 disposition |
| --- | --- |
| `recording_id` | Legacy `manifest.json.recording_id`; current `repository-bundle` manifest ID |
| `schema_version` | Legacy `manifest.json.schema_version`; current bundle manifest schema |
| `session_id` | Legacy `manifest.json.session_id`; current bundle manifest/source record |
| `video_id` | Legacy `manifest.json.video_id`; current bundle manifest/source record |
| `started_at_utc`, `ended_at_utc`, `duration_s` | Legacy recording manifest capture facts; current bundle video facts are read from the source asset/probe |
| `manifest_json`, `manifest_sha256` | Legacy recording manifest bytes and digest; current bundle `manifest.json` bytes and digest |
| `video_byte_length`, `video_sha256`, `video_relative_path` | Legacy `video` descriptor and video member; current bundle `files.video` and its member |
| `predictions_byte_length`, `predictions_sha256`, `predictions_relative_path` | Legacy `predictions` descriptor and prediction member; current bundle proposal-generator run descriptors and members |
| `recording_fingerprint` | Derived digest of the complete canonical recording bundle |
| `state` | Legacy manifest state; current bundle `manifest.json.state` |
| `received_at` | Legacy enrollment timestamp; current bundle earliest task-enrollment timestamp |
| `derived_state` | No current owner; derived by the concrete operations store when needed |
| `dataset_record_byte_length`, `dataset_record_sha256`, `dataset_record_relative_path` | No current owner; obsolete SQL-only derived state |
| `candidate_queue_byte_length`, `candidate_queue_sha256`, `candidate_queue_relative_path` | No current owner; obsolete SQL-only derived state |

M4 removes this obsolete migration and its dependency. No compatibility import is planned.

### `repository_bundles` (`0004_repository_bundles`)

Canonical owner: `data/intake/recordings/<recording_id>/`. Summary: `manifest.json`.
`source-record.json`, `initial-task-enrollment.json`, `predictions/*.json`, and the declared video
are validated members of the same immutable bundle.

| SQL field | Canonical value or derived value |
| --- | --- |
| `recording_id` | `manifest.json.recording_id`, matched to the directory ID |
| `source_asset_id` | `manifest.json.source_asset_id` |
| `video_id` | `manifest.json.video_id` |
| `session_id` | `manifest.json.session_id` |
| `source_sha256` | `manifest.json.source_sha256` and declared video digest |
| `manifest_sha256` | Digest of canonical `manifest.json` bytes |
| `source_record_sha256` | Digest of `source-record.json` |
| `task_enrollment_sha256` | Digest of `initial-task-enrollment.json` |
| `proposal_run_ids_json` | Proposal run IDs and descriptors in `manifest.json.files.proposal_generator_runs` |
| `bundle_fingerprint` | Deterministic digest of all bundle member paths, lengths, and digests |
| `state` | `manifest.json.state` |
| `received_at` | Earliest `initial-task-enrollment.json.enrollments[].created_at_utc` |

Current filesystem store consumers:

- `RecordingBundleStore.get(recording_id)` serves the recording bundle API, recording detail,
  CardEvent review source loading, development split input, visible-card preparation, and
  round-analysis validation.
- `RecordingBundleStore.list()` serves recording catalogs, round-analysis recording selection,
  and development split discovery.
- `RecordingBundleStore.publish(...)` handles upload publication, replay, and conflict handling
  without writing a database row.
- The app does not rebuild a recording index at startup. Direct valid bundle changes are visible on
  the next store read or catalog refresh.

The `repository_bundles` SQL table and its migration are removed. Runtime recording reads and
writes use only the canonical bundle.

### `round_analyses` (`0005_round_analyses`, replaced by M3)

Canonical owner: `.runtime/round-analyses/<analysis_id>/`. Immutable `input.json` and `result.json` artifact
members remain in the directory. M3 adds the mutable validated `state.json` as the lifecycle
summary and complete replacement for this table.

| SQL field | Filesystem owner |
| --- | --- |
| `analysis_id`, `recording_id`, `round_id`, `session_id` | `state.json` identity and request fields |
| `request_json`, `request_sha256` | Canonical request copy and digest in `state.json` or its immutable input artifact |
| `state`, `total_evidence_packages`, `completed_evidence_packages` | Mutable `state.json` lifecycle fields |
| `result_status`, `result_json` | Validated `state.json` terminal projection and immutable `result.json` |
| `error` | Mutable `state.json` terminal failure field |
| `input_artifact_id`, `input_artifact_sha256` | `state.json` reference to immutable input artifact |
| `result_artifact_id`, `result_artifact_sha256` | `state.json` reference to immutable result artifact |
| `created_at`, `started_at`, `completed_at` | UTC timestamps in `state.json` |

Former SQL reads and consumers:

- `get()` serves round-analysis API status, timeline, counterfactual validation, and worker state
  checks.
- `list_by_recording()` serves recording detail and the recording catalog.
- `create()`/`insert()` serve the round-analysis API and idempotent request replay.
- `update_progress()`, `mark_complete()`, and `mark_failed()` serve the analysis worker.
- `fail_non_terminal()` runs during app startup to preserve the restart failure rule.

Filesystem consumers after M3:

- `RoundAnalysisStore` owns `state.json` creation, validation, idempotent replay, lifecycle
  transitions, recording lookup, artifact-gated completion, and restart recovery.
- `RoundAnalysisService`, the round-analysis API, recording detail, and recording catalogs read
  analysis state from `RoundAnalysisStore`. No round-analysis API path reads a database.

M2 filesystem consumers:

- `EvidencePackageStore.get/list/get_by_logical_event/list_pending` validate package bundles and
  derive package and frame metadata directly from their canonical members.
- `TableObservationStore.get/list/list_for_package/get_for_analyzer` validate observation files and
  derive observation metadata directly from the canonical document.
- Package and observation publication stages complete directories and uses one atomic rename. No
  SQL row or compensation delete is part of the write path.

## Non-SQL stores

Pending videos and operations data use filesystem stores. The concrete operations stores remain
separate: CardEvent review, CardEvent development split, visible-card review batches, visual card
identity review batches, and the other `data/operations` documents do not share a generic resource
schema.

## M0 query and authority rules

1. A catalog scan validates canonical files on each refresh. An optional process-local cache can
   retain only derived paths and summary values.
2. A write stages all members, validates the complete staged directory, syncs it, and publishes it
   with one same-parent rename.
3. A mutable JSON update validates a temporary sibling file, syncs it, and atomically replaces the
   old document.
4. Startup recovery does not delete source or completed artifacts. Abandoned staging paths are
   ignored and reported for cleanup.
5. No SQL value, database file, durable index, or hidden metadata copy is required to find or read a
   valid resource. M4 verifies that the backend starts, passes filesystem readiness, and rebuilds
   all catalogs from canonical files after restart.
