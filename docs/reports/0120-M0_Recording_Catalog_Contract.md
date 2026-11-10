# 0120 M0: recording catalog contract and source map

Date: 2026-11-10. Source revision before M0: `cc450e8349f9e76f2cf4c088a49334ff29353a64`.

## Frozen list contract

The list route is `GET /v1/recordings`. It returns all accepted recordings in newest
`received_at` first order, then `recording_id` ascending. The current web caller is
`RecordingListView` in `web/src/recordings.tsx`; it renders `round_id`, `received_at`,
`session_id`, and the five pipeline stages. It navigates to `/recordings/{recording_id}` and
loads the cached thumbnail. The route is typed by `RecordingListResponse` and
`RecordingSummary` in `backend/src/dokodetector_backend/recordings_api.py` and
`web/src/api/recordingContracts.ts`.

M6 list response: keep the recording identity/display fields, `pipeline_status` with the same
five ordered stage keys, `can_start_analysis`, and `analysis_blocker`. Replace `evidence_package_ids`
with `evidence_package_count`; replace `analyses` with `analysis_count` and one nullable
`latest_analysis` using the current analysis-summary fields. Latest means maximum
`(created_at, analysis_id)`; this matches `RoundAnalysisStore.list()` newest-first order. This list
summary is bounded per recording. The explicit detail routes remain available:
`GET /v1/recordings/{recording_id}`, `GET /v1/round-analyses/{analysis_id}`,
`GET /v1/round-analyses/{analysis_id}/timeline`, and `GET /v1/evidence-packages/{package_id}`.
The first recording detail route keeps its current full detail behavior. The recording list has no
pagination today; M0 does not add it. The response remains ordered as above.

Status precedence is fixed by `_compact_stage_state`: active processor run; for analysis, active,
then any complete, then any failed; available pipeline revision; partial processor run; failed
processor run; otherwise `video-only` for events and `empty` for other stages. Processor-run
status remains the source; Job Manager state is not substituted. The analysis blocker remains clear
when an exact selected table-observation reference exists or at least one valid stored package has
valid lineage to the same recording and session. Otherwise keep
`No selected table observations or linked evidence packages are available.` Selection references
are availability hints only; analysis submission still validates the exact target.

Invalid recording bundles are omitted and logged. Invalid packages, package lineage, analyses,
nodes, or processor-run resources are omitted from their respective projections and logged; an
invalid package does not count toward the blocker. A missing or invalid selection behaves as no
selected reference. Per-recording blocker validation errors remain visible in
`analysis_blocker`. The current list has no per-record error envelope; catastrophic route errors
remain HTTP errors. Preserve these rules in M6. Empty, mixed, corrupt, status precedence and blocker
cases are retained in the current API/service tests listed below.

## Consumer and source inventory

| Catalog field or family | Current reader | Durable schema and root | Writers that must publish in the assigned adapter milestone |
| --- | --- | --- | --- |
| Recording identity and display metadata | `recordings_api.list_recordings` -> `RoundAnalysisService.recording_catalog` -> `RecordingBundleStore.list_metadata`; detail route also calls catalog | `repository-bundle/v1`, `source-record/v1`, `task-enrollment/v1`; `data/intake/recordings/<recording_id>` | `RecordingBundleStore.publish`; HTTP intake in `repository_bundle_api`; `operator_corpus_import.py`. Replay is an identical-bundle no-op. |
| Pipeline availability counts and exact blocker input | `PipelineWorkspaceService.get_statuses`; `_node_revisions_for_recordings`; `PipelineNodeSelectionStore.get_exact` | `pipeline-node/v1`, `pipeline-node-revision/v1`, `pipeline-node-publication/v1`; selection `pipeline-node-selection/v1`; `data/operations/pipeline-nodes` | `PipelineNodeStore.create/save`; `PipelineNodeTransactions` recovery; node edit/copy/restore, lineage writer, stage processors, calibration publication and imports. Selection: `update_exact`, `publish_processor_revision`, and selection migration/import. Named processor owners: `event_pipeline_service`, `observation_pipeline_service`, `visible_card_pipeline_service`, `proposed_card_scene_pipeline_service`, and `visual_identity_job`. |
| Processor-run status counts | `PipelineWorkspaceService._list_statuses_for_recordings`; currently enumerates run directories, decodes request metadata and reads state | `processor-run-request/v1`, `processor-run-state/v2`; `data/operations/pipeline/runs/<run_id>` | `ProcessorRunStore.create`, `update_state`, `complete`, `fail`, `update_progress`, `fail_non_terminal`, plus caller-driven restart/recovery paths. Progress-only writes must not change status counts. |
| Analysis count and latest summary | `RoundAnalysisService.recording_catalog` -> `RoundAnalysisStore.list_by_recording`; the latter calls global `list()` | Request `round-analysis/v1`; state `round-analysis-state/v1`; `data/operations/round-analyses/<analysis_id>` | `RoundAnalysisStore.insert/create`, `update_progress`, complete/fail transitions, and `fail_non_terminal`; API and round-analysis job/recovery callers. |
| Linked stored-package count and blocker | `RoundAnalysisService.recording_catalog` -> `EvidencePackageStore.list_metadata` and `_read_lineage` | `evidence-package-bundle/v1`, `evidence-package-record/v1`, `evidence-package-lineage/v1`; `data/intake/evidence-packages/<package_id>` | `EvidencePackageStore.publish`; HTTP intake in `api.py` and `operator_corpus_import.py`. Identical replay must not double count. |

Writers above are the finite M1–M4 source adapters. Full path and test ownership is in the source
files named in this table. Reads of detailed pipeline results, analysis timelines, package media,
and cached thumbnails remain explicit detail operations and do not enter list publication.

## Smallest-authority review

The existing exact node publication receipts and selection store provide exact source authority for
one node revision and the blocker reference. They do not provide a recording list, per-recording
status counts, package linkage counts, or latest-analysis metadata. Current readers enumerate all
packages, all analyses (once per recording), all node manifests, every selected node's revision
history, and all processor-run directories. Reusing these authorities on each GET therefore cannot
meet history-independent reads. A rebuildable metadata index with source publication evidence is
necessary for the stated outcome. Recording HEAD, job queue/index changes, workspace selection
changes, and global write optimization are not prerequisites. The single shared publication
protocol is retained because these independent filesystem writes must recover a missed index update
without making a list read rescan source history. M1 must still compare its smallest implementation
with the existing filesystem outbox and locking helpers; it must not create a general transaction
framework.

The existing `RecordingHistoryOrderIndex` orders explicit snapshot, revision, and lineage history;
it does not project the list's availability/status fields or analysis/package counts. The existing
`ProcessorRunCatalog.list_statuses()` still enumerates every run directory. The SQLite
`JobProjectionIndexStore` projects Job Manager records and cannot replace processor-run status.
These are useful source patterns, not an existing catalog authority that can satisfy this route.

## Baseline and fixture

The immutable 0117 M0 hard corpus, manifest, and route measurements remain the reference in
`docs/reports/0117-M0_Post_Cleanup_Baseline.md` and its artifacts. One current catalog-only capture
was made on 2026-11-10 from source revision
`cc450e8349f9e76f2cf4c088a49334ff29353a64`, using that hard snapshot in disposable storage and the
existing 0117 read counters. It made one `GET /v1/recordings` request (HTTP 200), returned 3,212
bytes with SHA-256
`3d3ee1b06e159ceec748dbbb8acd2121d19fcf93645419a43436829493e57d5d`, and took 18.070 seconds in
this single instrumented request. It opened 119 files across 55 unique paths, decoded 737 JSON
values, enumerated 12 nodes, walked 11 node histories (14 revision records / 70,117,888 revision
bytes), validated 14 revisions and 23 node manifests, and parsed 1 event, 10 visible-card, and 3
visual-identity payloads. This is bounded drift evidence, not a latency sample or a comparison
against the three-session reference. The disposable corpus has no analysis/package/run roots, so
the current reader logged those roots unavailable; this capture does not verify populated active
work. It did not measure startup or workspace routes. Exact counters and fixture digest are in the
[capture artifact](0120-M0_Catalog_Capture.json).

`backend/tests/test_recording_catalog_growth_contract.py` retains the model-level response-size
fixture and adds a real `/v1/recordings` route fixture. It publishes real package bundles, target
node revisions, processor runs and analyses through their stores. It grows target node history and
package/analysis history from 1 to 10, while unrelated nodes, runs and analyses also grow from 1 to
10. One target recording, its latest queued analysis, five stage states and one active processor
run remain fixed. Passing assertions check those invariants and show growth in every source family.
Separate strict expected-failure assertions check route response size and source-row counters; they
fail because the list embeds package/analysis history and readers reconstruct from retained source
rows. M6 must replace the expected failures with passing bounded-read tests,
and keep the existing regression boundaries: empty/mixed and corrupt package behavior
(`backend/tests/test_round_analysis_api.py`), node selection errors and stage precedence
(`backend/tests/test_pipeline_api.py`), and run-status summaries.

The populated real-route fixture produced these source-row counts in one small and one 10x
disposable run:

| Counter | 1x | 10x |
| --- | ---: | ---: |
| Returned recordings | 1 | 1 |
| Real route response bytes | 1,096 | 4,732 |
| Pipeline node manifests enumerated | 2 | 11 |
| Target node history records read | 1 | 10 |
| Stored package metadata rows read | 1 | 10 |
| Analysis state rows read, including unrelated recordings | 2 | 20 |
| Processor-run directories enumerated | 2 | 11 |
| Returned package IDs | 1 | 10 |
| Returned analysis summaries | 1 | 10 |
| Target stage states | `active-run, empty, empty, empty, active-run` | Same |
| Target queued analysis / active processor run | 1 / 1 | 1 / 1 |

Exact counts are retained in the [growth capture artifact](0120-M0_Growth_Capture.json). This
fixture measures a route over disposable persisted services. The earlier 0117 hard-corpus
capture remains unpopulated for packages, analyses and runs; it is retained only as its separate
single-request drift capture. The new fixture supplies the populated growth evidence without a
startup or broad latency remeasurement.

## M0 checks and result

- `mise exec -- uv run --project backend pytest backend/tests/test_recording_catalog_growth_contract.py backend/tests/test_round_analysis_api.py backend/tests/test_recording_bundle_store.py backend/tests/test_pipeline_api.py::test_recording_pipeline_workspace_aggregates_persisted_stage_state backend/tests/test_pipeline_api.py::test_recording_pipeline_workspace_reports_invalid_selection_pointer -q` — passed, 31 tests and 3 strict expected failures. The passing tests include fixed route state and demonstrated growth in every source family. The expected failures are model payload size, real-route payload size, and real-route source-row bounds. One existing Starlette/httpx deprecation warning.
- `mise exec -- uv run --project backend ruff check backend/tests/test_recording_catalog_growth_contract.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/tests/test_recording_catalog_growth_contract.py` — passed.
- `git diff --check` — passed.
- Local Markdown links checked in the board, active epic, moved 0117 epic, exit report and this report; all targets exist.

M0 is discovery and contract work. No list implementation, storage contract, API cutover, or
performance claim is complete.
