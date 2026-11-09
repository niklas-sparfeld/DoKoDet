# Epic 0117 M0: post-cleanup baseline and boundary inventory

Date: 2026-11-09  
Hard-trial source revision: `fed9a15da5a9305d5811525c5588cac62e61a01c`. Boundary-profile source revision:
`2bea6053d9c7f44243343b6791c7bc4b45005e82`.
Startup first-use replay base commit: `6db1d4862fb2d4b3e00ed1e3fa0f5f96f9c89ab3`; the exact
runner file digest is in the raw replay artifact.
Machine: macOS 27.2, arm64, 12 CPUs, Python 3.13.18  
Hard fixture manifest SHA-256: `e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`

## Result

The retained 0114 hard fixture and final 0115 storage layout are present. Fresh hard workspace
requests still take about 21 seconds. The current catalog reads retained node history. The HEAD
hypothesis is supported by both the source inventory and these measurements. Continue with the
snapshot and HEAD contract in M1.

This report freezes measurement gates and a finite trial budget. The profile counts actual
`PipelineNodeStore._read_revision` calls as revision schema and content validation, and
`_get_unrecovered` calls as node-manifest validation. It separately counts each open of a complete
`revision.json` payload, payload bytes, parser calls, history records, and lineage-record scans.

## Retained fixture and cold/warm baseline

The hard-fixture validator passed all 57 assets. The three pipeline sessions ran sequentially with
fresh isolated app/data roots. Each session made one cold request and two warm requests. The runner
does not flush the operating-system file cache. All nine responses were HTTP 200, 49,286 bytes, and
had SHA-256
`845cacbc15db27837ee9ac0587ad8c0eac7ea64d11db0c7cc39a696759ae7ce1`.

| Session | Workspace cold | Workspace warm samples |
| --- | ---: | ---: |
| 1 | 21.575 s | 20.966 s, 20.916 s |
| 2 | 20.983 s | 20.559 s, 20.979 s |
| 3 | 20.561 s | 20.771 s, 21.058 s |
| Median | 20.983 s | 20.941 s |

Raw samples: [session 1](0117-M0_Post_Cleanup_Baseline.artifacts/0117-m0-session-1-pipeline.json),
[session 2](0117-M0_Post_Cleanup_Baseline.artifacts/0117-m0-session-2-pipeline.json), and
[session 3](0117-M0_Post_Cleanup_Baseline.artifacts/0117-m0-session-3-pipeline.json).

The 0114 M13 profile attributed 14.325 seconds to five `node_store.history` traversals. The current
profile on the same immutable response has 63 file reads, 38 unique paths, 586 `json.loads` calls,
and 14 domain parsers (8 visible-card and 6 visual-identity parses). It returned the same response
digest in 21.060 seconds. The repeated full JSON decodes and history traversal support the hypothesis
that normal workspace reads reconstruct more history than current-state UI needs.

## Startup baseline

The first startup capture missed the visual-identities stage-open sample. I replayed exactly three
hard-populated startup processes to add that required sample. This corrects the named measurement
defect in capture set 1. It does not add a capture set or change the frozen trial budget. Each
process used an isolated temporary root, the same hard fixture manifest, and the same recording for
catalog, workspace, and stage-open. Startup-to-useful remains process launch through health
readiness, the first recordings response, and the first workspace response. The stage-open request
is measured immediately after workspace first use.

| Process | Recordings catalog first use | Workspace first use | Visual-identities stage-open first use | Startup to useful response |
| --- | ---: | ---: | ---: | ---: |
| 1 | 3.256 s | 5.042 s | 3.251 s | 8.971 s |
| 2 | 3.279 s | 4.986 s | 3.265 s | 8.928 s |
| 3 | 3.272 s | 4.952 s | 3.268 s | 8.884 s |
| Median | 3.272 s | 4.986 s | 3.265 s | 8.928 s |

All first-use requests returned HTTP 200. Stage-open returned the same 47,943-byte response and
SHA-256 in each process. The raw corrected series, CSV, summary CSV, process logs, route list, and
fixture digest are in the
[first-use startup artifact](0117-M0_Post_Cleanup_Baseline.artifacts/0117-m0-first-use-startup.json),
[sample CSV](0117-M0_Post_Cleanup_Baseline.artifacts/0117-m0-first-use-startup.csv), and
[summary CSV](0117-M0_Post_Cleanup_Baseline.artifacts/0117-m0-first-use-startup.summary.csv).
The JSON stores the exact runner digest used for capture. The runner received formatting-only edits
after capture; they do not change its behavior.
The earlier stage-less startup JSON files remain as original capture evidence; they are superseded
for the combined first-use table.

The corrected startup-to-useful median is below the frozen 17.2-second ceiling. Keep the ceiling,
planning target, and remaining trial count unchanged. The 0117 hard cold/warm workspace trials use
`game-2026-08-20-01-001`; this startup profile uses `cardeventnet-IMG_0650`, as the existing 0114
startup profile does. The four first-use measurements above share one recording and one process
protocol, but they are not a substitute for the cold/warm workspace cases.

## Mapping to the 0114 route and case inventory

This table maps each measured 0117 boundary to its registered 0114 route budget and timed case.
The API inventory is in the [0114 M0 operation map](0114-M0_Interactive_UI_Performance_Inventory.json);
the named hard cases are in the [0114 M11 baseline](0114-M11_Performance_Baseline.json) and the
startup process profile is in the [0114 M13 hard startup capture](0114-M13_Startup_Hard.json).

| 0117 boundary | Request and 0114 route budget | 0114 timed case or exact gap |
| --- | --- | --- |
| Catalog | `GET /v1/recordings`; `api:GET:/v1/recordings` | `catalog/catalog_hard/hard`; also `startup/hard/recordings_first_use` for a fresh process. |
| Full workspace | `GET /api/recordings/{recording_id}/pipeline`; `api:GET:/api/recordings/{recording_id}/pipeline` | `pipeline/workspace_full_hard/cold` and `/warm`; also `startup/hard/workspace_first_use`. |
| Visual-identities stage-open | Same route with `?stage=visual_identities` | `pipeline/workspace_stage_visual_identities_hard/cold` and `/warm`. The new `stage_open_first_use` sample adds this route after workspace first use in each hard startup process; 0114 had no startup stage-open sample. |
| History graph | `GET /api/recordings/{recording_id}/pipeline/lineage`; `api:GET:/api/recordings/{recording_id}/pipeline/lineage` | `pipeline/lineage_hard/cold` and `/warm`. The exact revision read maps to `pipeline/revision_max_identity_payload/cold` and `/warm`. |
| Processor launch | `POST /api/jobs`; `api:POST:/api/jobs` | 0114 classifies this route under `browser/job_submission_visible_status`, but has no direct named hard API timing case for this POST. The 0117 sample is a deterministic stubbed launch diagnostic, not a comparable 0114 latency result. |
| Startup to useful response | Fresh hard-populated backend process; readiness followed by catalog and full workspace | 0114 M13 `startup_to_useful_response`, with constituent `startup/hard/recordings_first_use` and `startup/hard/workspace_first_use` samples. The 0117 corrected profile adds stage-open as a separate request and keeps startup-to-useful at workspace first use. |

This mapping identifies two coverage limits: 0114 has no startup stage-open sample, and it has no
direct hard API timing case for processor-launch POST. The corrected M0 startup replay fills the
first gap for this epic. The deterministic launch diagnostic records the second gap; it does not
claim that the browser workflow is an equivalent API timing case.

## Boundary measurements

`backend/scripts/profile_0117_workspace_reads.py` runs the real API over the retained hard fixture.
Each request is sequential and uses one disposable root. Its startup row includes ASGI lifespan,
health, catalog, and workspace first-use work. One recording has an actually empty table-observation
stage. The stale-selection case writes a missing visual-identity node/revision pointer to disposable
persisted storage and checks for `invalid_selection`. Processor launch uses a deterministic event
provider stub and returns HTTP 202. This is an in-process operation-count diagnostic using
`game-2026-08-20-01-001`; its timing values are not first-use samples. First-use acceptance uses the
fresh-process series above, with catalog, workspace, and stage-open requests on
`cardeventnet-IMG_0650`.

| Boundary | HTTP | Reads | JSON loads | Nodes enumerated | History traversals / revision records | Domain parses |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Startup + first useful probes | — | 156 | 1,323 | 24 | 16 / 21 | event 1, visible 18, identity 9 |
| Recording catalog | 200 | 92 | 737 | 12 | 11 / 14 | event 1, visible 10, identity 3 |
| Full workspace | 200 | 63 | 585 | 12 | 5 / 7 | visible 8, identity 6 |
| Visual-identity stage | 200 | 63 | 333 | 12 | 5 / 7 | visible 4, identity 3 |
| Lineage graph / explicit history | 200 | 46 | 312 | 12 | 5 / 7 | visible 4, identity 3 |
| Exact immutable revision | 200 | 6 | 12 | 0 | 1 / 2 | identity 2 |
| Empty table-observation stage | 200 | 63 | 585 | 12 | 5 / 7 | visible 8, identity 6 |
| Stale selected revision | 200 | 63 | 339 | 12 | 5 / 7 | visible 4, identity 3 |
| Processor launch | 202 | 59 | 60 | 0 | 0 / 0 | none |

The instrumented profile also separates full revision payload reads from history metadata and
lineage scans. Revision validation means one call to `_read_revision`; repeated validation counts
show repeated validation of the same `(node_id, revision_id)` within that operation. The node
manifest count is `_get_unrecovered`. Lineage enumeration counts `*.json` glob calls under
`.lineage-runs`; lineage record reads count files opened there. The retained hard corpus has no
`.lineage-runs` directory, so these counts are zero for the measured operations.

| Boundary | Duration | Revision payload reads / bytes | Revision validations / repeated | Node manifest validations | Lineage enumerations / records |
| --- | ---: | ---: | ---: | ---: | ---: |
| In-process startup + first useful probes | 42.337 s | 21 / 129,596,737 | 21 / 7 | 47 | 0 / 0 |
| Recording catalog | 19.669 s | 14 / 70,117,888 | 14 / 0 | 23 | 0 / 0 |
| Full workspace | 22.680 s | 7 / 59,478,849 | 7 / 0 | 24 | 0 / 0 |
| Visual-identity stage | 16.061 s | 7 / 59,478,849 | 7 / 0 | 24 | 0 / 0 |
| Lineage graph / explicit history | 16.061 s | 7 / 59,478,849 | 7 / 0 | 17 | 0 / 0 |
| Exact immutable revision | 5.343 s | 2 / 24,019,622 | 2 / 0 | 2 | 0 / 0 |
| Empty table-observation stage | 22.636 s | 7 / 59,478,849 | 7 / 0 | 24 | 0 / 0 |
| Stale selected revision | 16.015 s | 7 / 59,478,849 | 7 / 0 | 24 | 0 / 0 |
| Processor launch | 1.739 s | 0 / 0 | 0 / 0 | 0 | 0 / 0 |

The in-process startup duration combines ASGI lifespan and three first-use probes. It is not the
independent process startup metric above. The independent medians remain the startup regression
reference. The catalog and stage durations are single instrumented requests and are diagnostic;
they do not replace the three independent cold/warm trials.

The full counter sets and read paths are in the
[boundary profile](0117-M0_Post_Cleanup_Baseline.artifacts/boundary-profile.json). The separate
[workspace decoder profile](0117-M0_Post_Cleanup_Baseline.artifacts/0117-m0-current-io.json)
records the 63-read workspace request.

The current catalog reads 14 revision records through 11 history walks for 12 enumerated nodes.
The current workspace makes five history walks and reads seven records. The stage response has the
same traversal count as the full workspace even when only one stage is requested. The exact
revision endpoint walks two revision records to return one. Processor launch reaches the API and
accepts the stubbed job; it does not walk history. Catalog, workspace, stage, and history work
therefore have separate owners for M1/M6/M7/M10.

These are one-request operation counts, not a full catalog-size growth result. The catalog can
scale with the returned recording list. M1 must preserve compact job-state projection and ensure
only selected current data participates in workspace growth.

## Deterministic growth fixture

`backend/tests/test_0117_workspace_growth_fixture.py` uses the real `PipelineNodeStore` and workspace
revision projection. It fixes selected current content and an independent sibling review, then grows
history from 2 to 20 revisions and unrelated recordings from 1 to 10. The stage markers retain an
empty table-observation stage and stale visual-identity selection. It creates an empty persisted
`.lineage-runs` directory and measures its enumeration separately. It asserts exact selected
content, sibling identity, node enumeration, history traversal count, payload reads and bytes,
revision validation calls, domain parser calls, lineage enumeration, and request elapsed time.

The fixture keeps the two current-recording `history` method calls fixed, while revision payload
reads, revision validations, and parser calls grow from 3 to 21. Payload bytes grow from 1,353 to
9,077. The measured projection duration grows from 2.282 ms to 11.523 ms. Node enumeration grows
from 3 to 12, and the empty lineage directory is enumerated once in each case with zero records.
The API profiler separately checks real persisted empty and stale state. The fixture does not claim
that unrelated recordings cost zero metadata enumeration; the workspace currently enumerates 12
nodes before filtering.

## Reader, writer, and schema inventory

This is the active reader/writer boundary that M1 replaces. Paths below are relative to the
worktree. The local data roots can be redirected by `DOKO_STORAGE_ROOT`; the authoritative roots
and recovery limits are in the [0115 M14 map](0115-M14_Maintained_Storage_Map.md).

| Resource and schema | Active readers and paths | Active writers and paths | Verification command |
| --- | --- | --- | --- |
| Recording bundle: `recording-video/v1`, source-record, initial-task-enrollment | `recordings_api.list_recordings` / `get_recording`; `RoundAnalysisService.recording_catalog`; `RecordingBundleStore.list_metadata` / `get_metadata`; `EventPipelineService.get_recording_source`. Reads `data/intake/recordings/<recording_id>/{manifest.json,source-record.json,initial-task-enrollment.json}`. Routes: `GET /v1/recordings`, `GET /v1/recordings/{recording_id}`, workspace GET. | Intake publication through `RecordingBundleStore.publish`; `operator_corpus_import.py`; `POST /v1/recordings/{recording_id}/round-analyses` writes analysis state, not the bundle. | `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_bundle_store.py backend/tests/test_round_analysis_api.py` |
| Evidence package and round analysis: `evidence-package/v1`, `round-analysis/v1`, package lineage | `RoundAnalysisService.recording_catalog`; `RoundAnalysisStore.list_by_recording`; `EvidencePackageStore.list_metadata`; `RoundAnalysisService._read_lineage`. Reads `data/intake/evidence-packages/<id>/` and `data/operations/round-analyses/<analysis_id>/`. Route: `GET /v1/recordings`. | `RoundAnalysisService` / `RoundAnalysisStorage` create, progress, complete, and publish counterfactual records through `POST /v1/recordings/{recording_id}/round-analyses`. | `mise exec -- uv run --project backend pytest -q backend/tests/test_round_analysis_api.py backend/tests/test_round_analysis_storage.py backend/tests/test_round_analysis_store.py` |
| Node manifest, HEAD, revision, publication authority: `pipeline-node/v1`, `pipeline-node-revision/v1`, `pipeline-node-publication/v1` | Existing runtime readers remain `PipelineNodeStore._get_unrecovered`, `list_nodes`, `history`, `_read_revision`, `read_published_revision`, and `read_revision_record`; the exact readers still walk parent links until later cutover. The new `read_authorized_revision` reads the exact revision plus `publications/<revision_id>/authority.json`, or the exact current HEAD if its receipt is missing after a crash. Only the private edit-recovery helper can inspect an unpublished raw revision. Reads use `data/operations/pipeline-nodes/<node_id>/{manifest.json,head.json,revisions/<revision_id>/revision.json,publications/<revision_id>/authority.json}`. Routes: workspace, lineage, and exact revision GET. | `PipelineNodeStore.create` writes the initial revision, HEAD, and authority in one staged node directory. `PipelineNodeStore.save` writes the revision, ensures authority for the prior HEAD, atomically replaces HEAD, then records authority for the new revision under the per-node process lock. `PipelineNodeTransactions` applies the same order while recovering its prepared journal. Existing writers inherit these paths: `PipelineLineageWriter`, stage processors, calibration refinement, node edit/copy/restore, and migration/import helpers. | `mise exec -- uv run --project backend pytest -q backend/tests/test_0117_workspace_growth_fixture.py backend/tests/test_pipeline_api.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py` |
| Generated/completed selection: `pipeline-node-selection/v1` | `PipelineNodeSelectionStore.get_exact`; workspace, catalog, stage services. Reads `data/operations/pipeline-nodes/.pipeline-node-selections/<recording_id>/<content_type>.json`; stage GET selection routes. | `PipelineNodeSelectionStore.update_exact`; matching stage PUT routes; editor/review publication. | `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_api.py::test_recording_pipeline_workspace_reports_invalid_selection_pointer` |
| Lineage request/run/accepted-use: `pipeline-lineage-request/v1`, `pipeline-lineage-run/v1`, `pipeline-accepted-use/v1` | `PipelineLineage.snapshot`; `RecordingPipelineWorkspaceService._node_revisions_for_recordings` / `_lineage_runs_by_output`. Reads `.lineage-requests/<run_id>.json`, `.lineage-runs/<run_id>.json`, and `.accepted-uses/<run_id>.json`. Route: pipeline lineage GET. | `PipelineLineage.start`, `PipelineLineageWriter`, stage processor publishers write request, terminal, and accepted-use records. | `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_lineage.py backend/tests/test_pipeline_lineage_writer.py` |
| Reviews and drafts: `pipeline-review/v1`, `visible-card-review/v1`, `frame-review-workflow/v1` | `PipelineNodeReviews`, `VisibleCardReviewStore`, frame-review workflow, lineage draft projection; node review GET route. Reads `.review-records/<node_id>/<review_id>.json`, visible-card reviews, and `data/operations/frame-review-queues/`. | Node review POST routes; visible-card/frame-review APIs and draft stores. | `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_api.py backend/tests/test_lineage_draft_projection.py backend/tests/test_frame_review_lineage_target.py` |
| Calibration: `table-plane-calibration/v1`, `table-plane-calibration-refinement/v1` | `CalibrationRefinementService`, calibration API. Reads calibration revisions, drafts and candidates under `data/operations/`; calibration GET routes. | Calibration-refinement POST, PUT, `/discard`, `/apply`; service publishes calibration and refinement records. | `mise exec -- uv run --project backend pytest -q backend/tests/test_calibration_refinement_service.py backend/tests/test_pipeline_api.py` |
| Processor request/output/job: `processor-run-request/v1`, `automated-pipeline-run/v1`, Job Manager schemas | Stage GET APIs; `AutomatedPipelineRunService.read`; Job Manager status. Reads `data/operations/pipeline/runs/<run_id>/`, job records, and stage outputs. Routes: `GET /api/jobs/{job_id}`, pipeline run and stage GET. | `POST /api/jobs`; `POST /api/recordings/{recording_id}/pipeline/runs`; stage POST routes; durable job manager and processor stores. | `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_run_api.py backend/tests/test_pipeline_api.py backend/tests/test_jobs_api.py backend/tests/test_job_store.py` |
| Startup and recovery | App lifespan and durable job recovery read configured operations roots before `/health/ready`; first-use probes then read catalog, workspace, and stage-open. | Job recovery marks interrupted work and durable stores publish run/job transitions. No lifecycle retention writer is moved from 0118. | `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile hard_populated --startup-processes 3 --timeout 180 --include-stage-first-use --output /tmp/0117-startup.json` |

The M14 storage map names local retained roots and recovery authority. M15 closed the selected cleanup
scope; it did not close operational lifecycle work. Do not move 0118 lifecycle writers into this
epic unless they conflict directly with the recording-state contract.

## Frozen budgets and finite trials

The frozen M0 gates use the original three-session startup medians retained in the stage-less
startup artifacts: 9.603 seconds startup-to-useful, 3.107 seconds recordings first use, and 4.668
seconds workspace first use. The corrected replay fills the missing stage-open sample. It does not
replace the frozen gate inputs or change any threshold. Noise uses the 0114 method:
`max(3 × 1.4826 × MAD, category floor)`. The floor is 2 ms for JSON and 25 ms for startup. The
no-regression ceiling adds 20% of the reference plus the noise allowance. The rounded ceilings are:

| Case | Frozen reference | Noise allowance | Frozen no-regression ceiling | M16 planning target |
| --- | ---: | ---: | ---: | ---: |
| Hard workspace cold | 20.983 s | 1.878 s | 27.1 s | 16.0 s median |
| Hard workspace warm | 20.941 s | 0.344 s | 25.5 s | 16.0 s median |
| Hard startup to useful response | 9.603 s | 5.632 s | 17.2 s | 8.0 s median |
| Hard recordings first use | 3.107 s | 0.176 s | 3.9 s | 2.5 s median |
| Hard workspace first use | 4.668 s | 0.025 s | 5.7 s | 3.6 s median |

Planning targets are measured goals. The no-regression ceilings are gates, not speedup claims.
Structural gates are zero pipeline payload reads and history walks for the catalog; no implicit
history traversal for the current workspace; no payload/parser growth when history and unrelated
recordings grow 10x with current content fixed; and complete, duplicate-free paged history.

The hard corpus run limit is three non-overlapping capture sets. One set has three independent
sessions, each with one cold and two warm workspace samples and one fresh startup process. Use set 1
as the M0 baseline. M16 may run at most two new hard capture sets for candidate qualification. Do not
repeat a set after a pass without a code change or a named measurement defect. Each HTTP request and
process retains a 180-second timeout. The separate 0114 route/browser suite remains unchanged; its
57 hard assets, 76 API operations, 70 UI route keys, and seven browser/load scenarios stay reserved.

## Checks and limits

- Hard fixture validator: `materialize_interactive_ui_performance_fixtures.py --require-hard` — passed, 57 assets.
- 0114 route inventory checker — passed: 76 registered API operations, one documented UI URL gap, and 70 planned UI cases.
- 0117 boundary profiler — passed all eight HTTP cases, with empty/stale response assertions; output in the linked artifacts.
- Growth fixture, first-use runner, and focused API tests — passed; include the 10x counters, deterministic processor launch, and persisted empty/stale state.
- Focused Ruff check and format check — passed for the profile, startup runner, and both tests.
- First-use startup replay — three fresh hard-populated processes passed catalog, workspace, and
  visual-identities stage-open requests. Each sample uses the same recording in the same process.

Revision validation counts cover the actual store method that checks revision schema, identity,
canonical content, and digest. `_get_unrecovered` counts node-manifest validation. The profiler does
not count each lower-level JSON field check separately. The empty and stale API cases use persisted
disposable state. No production performance change or speedup is claimed in M0.

## Reproduction

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard
mise exec -- uv run --project backend python backend/scripts/profile_0117_workspace_reads.py --output /tmp/0117-boundaries.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_pipeline_read_performance.py --warmups 0 --repeats 2 --batches 1 --timeout 180 --case workspace_full_hard --output /tmp/0117-session-pipeline.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile hard_populated --startup-processes 1 --timeout 180 --output /tmp/0117-session-startup.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile hard_populated --startup-processes 3 --timeout 180 --include-stage-first-use --output /tmp/0117-first-use-startup.json
mise exec -- uv run --project backend pytest -q backend/tests/test_0117_workspace_growth_fixture.py backend/tests/test_pipeline_run_api.py backend/tests/test_pipeline_api.py::test_recording_pipeline_workspace_aggregates_persisted_stage_state backend/tests/test_pipeline_api.py::test_recording_pipeline_workspace_reports_invalid_selection_pointer
```
