# Epic 0117 M1: recording state contracts

Date: 2026-11-09  
Contract revision: recorded in the M1 commit.

## Decision

M1 defines the versioned backend data contracts in
[`recording_state_contract.py`](../../backend/src/dokodetector_backend/recording_state_contract.py).
They are contract-only. They do not add a store, API route, migration, or second authority.
The next milestones implement and activate them in sequence.

`recording-state-snapshot/v1` contains all seven fixed slots: events, visible cards, table-plane
calibration, virtual scenes, visual identities, table observations, and reconstruction results.
Each slot has separate `generated` and `completed_reference` selections. Each selection is
explicitly empty, selected, or stale. A stale selection keeps its exact resource and names why it
is stale. Dependencies use exact resource kind, identity, schema, and SHA-256. Pipeline revisions
also name node and revision IDs. Calibration and reconstruction use their own resource kinds;
they are not forced into pipeline nodes. The snapshot ID is `rs_` plus the SHA-256 of canonical
UTF-8 JSON with sorted keys and no whitespace, excluding `snapshot_id` itself. The predecessor
is optional history metadata and is not a read dependency.

Independent pipeline, visible-card, and frame-review work is referenced separately from generated
and completed-reference slots. Creating output, completing review, inspecting a historical
revision, and browser navigation do not select state. Autosave can advance only the currently
selected working node under existing edit semantics. Explicit selection or restoration creates a
new snapshot and advances HEAD with `expected_head_version`; a failed compare-and-swap retains the
output and reports a conflict. A stale downstream result remains addressable and is never relabeled
current or replaced with a result from another branch.

## HEAD, summary, and failure contracts

`recording-head/v1` is the sole current-state authority: recording ID, monotonically increasing
version, and one snapshot ID. The head is not a job status record. A reader sees either a complete
old or complete new value. Publication stores and validates the immutable snapshot before the
compare-and-swap of HEAD. M3 owns storage ordering, locks, cross-process concurrency, and crash
testing.

`recording-state-summary/v1` is rebuildable derived metadata. It is usable only when its recording,
HEAD version, snapshot ID, and snapshot digest all match the authoritative HEAD and immutable
snapshot. Summary creation time alone never proves freshness. On mismatch, a reader can derive a
new summary from a verified snapshot and publish it conditionally against the same HEAD version.
Each slot keeps separate `generated` and `completed_reference` states in this compact summary.
If HEAD or its snapshot is missing/corrupt, isolate that recording and return a typed failure; do
not repair, replace, or infer selected state from old pointers. An offline audit can inspect history.

`recording-state-error/v1` fixes safe error codes for uninitialized, conflict, corrupt/missing state
or resource, and invalid/expired/oversized pagination. HTTP mapping: 404 for missing recording or
resource, 409 for stale HEAD version, 410 for expired cursor, 422 for invalid input, and 500 for
corrupt persisted authority. A 500 identifies the recording and repair/audit action without
returning stored payloads.

Compact analysis, package, and job metadata contain IDs, schema, status, update times, and content
digests where available. They do not contain result payloads, package files, job event histories,
lineage, or all analysis revisions. The current-state summary contains no analysis, package, or job
lists. Catalog metadata uses separate single-collection pages with a maximum page size of 100 and
a stable upper bound. Counts can be returned without embedding the items.

`job-projection-authority/v1` is the Job Manager's durable cross-process authority marker. It has a
stable manager ID, durable epoch, and monotonic sequence. Every durable job state transition
advances the sequence. `recording-job-projection/v1` carries the observed epoch and sequence and at
most 20 active job summaries. It reports the active count and uses a cursor for further items.
Before serving it, a reader compares both authority values with the current durable marker; a
mismatch means the projection is stale and must be rebuilt from the Job Manager's authoritative
records before it is returned. The sequence and epoch survive process restart. A restarted manager
validates its marker and records, rebuilds missing projections, and never treats an old timestamp as
proof of freshness. A job cursor pins the same epoch and sequence, so a later state transition cannot
shift an existing page. HEAD does not own or validate job status.

## API and pagination shapes

These are the M1 API shapes for M5–M11; routes are not implemented in M1.

| Operation | Shape and contract |
| --- | --- |
| Current recording/catalog | Existing recording row plus a compact state summary; no revision payload, node history, analysis history, or package content scan. Paginate returned recordings if the existing list exceeds the selected response bound. |
| Current workspace | `GET /api/recordings/{recording_id}/pipeline` returns the authoritative snapshot ID/version and stage states. It does not follow predecessors. A stage-open response resolves only that slot's exact selected resource and its declared dependencies. |
| Explicit state | `GET /api/recordings/{recording_id}/state` returns HEAD and its verified snapshot. `PUT /api/recordings/{recording_id}/state` uses `RecordingHeadUpdate` for explicit selection or restore with expected version. Historical inspection stays on history/revision routes. |
| History/candidates/lineage | `GET /api/recordings/{recording_id}/state/history`, `/revisions`, `/candidates`, and `/lineage-edges` return typed `RecordingHistoryPage` items. Snapshot entries carry snapshot ID, digest, and predecessor. Resource entries carry exact resource refs. Edge entries carry exact source and target keys for revision, run, or artifact endpoints plus edge kind and role. Cursor binds recording, collection, normalized-filter digest, upper bound, last stable key, and page size. Results sort by a collection-specific immutable key (snapshot ID, exact resource kind/ID, or edge endpoint tuple); maximum page size is 100. Cursor is opaque, integrity-protected, and pins the first-page upper bound so later inserts do not shift pages. Metadata pages do not parse content. |
| Catalog metadata | `/analyses`, `/packages`, and `/jobs` return one bounded `CatalogMetadataPage` collection at a time. Each page has at most 100 compact items and a continuation cursor; no response embeds an unbounded list. Job pages use `RecordingJobProjection` and validate its authority epoch and sequence against the current durable Job Manager marker. |
| Exact resource | Existing exact revision route plus calibration/reconstruction resource routes validate the address and content digest when content is opened. No ancestry traversal is implicit. |
| Processor start | Existing run/job start contracts gain `SnapshotFrozenProcessorInputs`; the durable request stores snapshot ID/version and every resolved input reference. Select-on-completion is explicit and carries expected HEAD version. Retry reuses frozen inputs. |

## Dependency checks by operation

| Operation | Required checks |
| --- | --- |
| Catalog/current workspace summary | HEAD schema, recording identity, referenced snapshot ID and canonical digest, summary-to-HEAD version/digest. No full result or history validation. |
| Workspace stage status | Snapshot schema/identity and exact reference shape; compare each result's recorded dependency references with selected upstream references to report stale. Do not parse result payloads merely to show status. |
| Stage open / edit | Verify selected resource content digest and schema; verify exact required upstream resource identities/digests used by that content. Edit also compare the working node revision expected by the writer. Never use timestamps as validity proof. |
| Explicit history or catalog metadata page | Validate cursor integrity, recording, collection, filters, bound and stable key; validate metadata identity only. Fetching a page does not parse all history or content. Job pages also compare the projection epoch and sequence with Job Manager authority and rebuild on mismatch. |
| Exact historical resource | Verify requested ID, schema and content digest. Return missing/corrupt as typed failure; do not choose a replacement. |
| Processor start / retry | Verify snapshot authority, all exact input addresses and digests, processor contract/config; persist frozen references. Retry reuses these references even after HEAD changes. |
| Output publication | Verify output resource and its exact dependency manifest. Do not move HEAD unless launch recorded explicit selection intent; then CAS against expected version. |
| Summary repair | Verify HEAD and immutable snapshot, derive summary, CAS publication against observed HEAD version. Never infer from a stale summary or scan old history. |

## Consumer and replacement inventory

The M0 report has the active schema and file-level reader/writer inventory. This M1 map fixes the
replacement owner and boundary for each consumer family:

| Consumer / current owner | M2–M13 replacement | Verification boundary |
| --- | --- | --- |
| `recordings_api.list_recordings`, `RecordingBundleStore`, `RoundAnalysisService.recording_catalog`, `EvidencePackageStore`, `RoundAnalysisStore` | Compact recording summary plus package/analysis metadata and Job Manager projection | Catalog response parity, no revision payloads or full histories, metadata growth and API tests |
| `RecordingPipelineWorkspaceService`, `PipelineNodeStore`, `PipelineNodeSelectionStore` | Snapshot/HEAD current reads; exact resources on stage open; explicit paged history | Existing workspace output semantics, exact selected IDs, empty/stale cases, 10x growth |
| `PipelineLineage`, lineage requests/runs/accepted-use stores | Explicit bounded lineage/history requests; no current-state discovery through ancestry | Stable cursor completeness and exact historical addressing |
| Stage APIs and review/draft stores (`pipeline_stage_api`, node/visible-card/frame review) | Selected working-state writes publish a new snapshot; independent review references remain separate | Generated/reference separation, review sibling isolation, edit/reload/restart |
| Calibration refinement and calibration APIs | Typed calibration revision in its own slot with exact source references | Calibration dependency and digest checks; preserve base revision |
| Round-analysis/reconstruction service and routes | Typed reconstruction resource plus compact analysis record | Exact analysis result and source dependencies; full result only on explicit open |
| Pipeline run, processor, orchestration, stage processors | Frozen snapshot inputs; conditional explicit output selection | HEAD movement during run, retry, failure/cancel and select-on-completion conflict |
| Job Manager | Separate `job-projection-authority/v1` and bounded `recording-job-projection/v1` with stable epoch/sequence | Cross-process authority comparison, stale projection rebuild, completion and restart |
| App startup, storage setup and recovery | Isolated-root snapshot/HEAD authority and offline audit/recovery tooling | No old runtime fallback after activation; recovery and corrupt-record isolation |
| Web recordings list, workspace, stage editors, history/lineage links | Compact current summary, exact stage opens, explicit state switch and bounded history | Browser reload retains inspected lineage without silently selecting it |

No compatibility fallback or migration path is added by this contract milestone. M12/M13 must
convert retained data and prove recovery before removing the old runtime path.

## Checks and limits

`mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_contract.py`
passed 14 contract tests: canonical identity validation, all empty slots, stale references,
independent reviews, generated/reference separation in snapshot and summary, specialized resource
kinds, typed snapshot/resource/lineage-edge history, bounded catalog pages, job projection authority
and restart validation, compare-and-swap request, frozen processor inputs, and compact metadata.
The tests validate contracts;
they do not claim storage, API, crash, or runtime behavior. API generation and browser checks do not
apply because M1 adds no route or web change.
