# Epic 0117 M0: post-cleanup baseline and boundary inventory

Date: 2026-11-09  
Measured source revision: `fed9a15da5a9305d5811525c5588cac62e61a01c`  
Machine: macOS 27.2, arm64, 12 CPUs, Python 3.13.18  
Hard fixture manifest SHA-256: `e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`

## Result

The retained 0114 hard fixture and final 0115 storage layout are present. Fresh hard workspace
requests still take about 21 seconds. The current catalog reads retained node history. The HEAD
hypothesis is supported by both the source inventory and these measurements. Continue with the
snapshot and HEAD contract in M1.

This report freezes measurement gates and a finite trial budget. The profile measures observable
file opens and decoders. It does not count every schema validation call inside domain code. It
counts node enumeration and history records through the actual store methods. Treat decoder calls
as a lower bound on validation work, not as a complete validation counter.

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

The 0114 M13 profile attributed 14.325 seconds to five `node_store.history` traversals. The current
profile on the same immutable response has 63 file reads, 38 unique paths, 586 `json.loads` calls,
and 14 domain parsers (8 visible-card and 6 visual-identity parses). It returned the same response
digest in 21.060 seconds. The repeated full JSON decodes and history traversal support the hypothesis
that normal workspace reads reconstruct more history than current-state UI needs.

## Startup baseline

Three new hard-populated backend processes used isolated temporary roots. No benchmark overlapped
these trials. Startup means process launch through health readiness, the first recordings response,
and the first workspace response.

| Session | Recordings first use | Workspace first use | Startup to useful response |
| --- | ---: | ---: | ---: |
| 1 | 3.098 s | 4.667 s | 11.267 s |
| 2 | 3.227 s | 5.485 s | 9.603 s |
| 3 | 3.107 s | 4.668 s | 8.336 s |
| Median | 3.107 s | 4.668 s | 9.603 s |

Startup MAD is 1.267 seconds. Session 1 spent 3.500 seconds in the first health-live probe. This is
startup noise, not a workspace latency change. Keep the first useful response in the regression
gate so deferring the same work to the first request cannot appear as a startup gain.

## Boundary measurements

`backend/scripts/profile_0117_workspace_reads.py` runs the real API over the retained hard fixture.
Each request is sequential and uses one disposable root. Its startup row includes ASGI lifespan,
health, catalog, and workspace first-use work. One recording has an actually empty table-observation
stage. The stale-selection case writes a missing visual-identity node/revision pointer to disposable
persisted storage and checks for `invalid_selection`. Processor launch uses a deterministic event
provider stub and returns HTTP 202.

| Boundary | HTTP | Reads | JSON loads | Nodes enumerated | History traversals / revision records | Domain parses |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Startup + first useful probes | — | 156 | 1,323 | 24 | 16 / 21 | event 1, visible 18, identity 9 |
| Recording catalog | 200 | 92 | 737 | 12 | 11 / 14 | event 1, visible 10, identity 3 |
| Full workspace | 200 | 63 | 585 | 12 | 5 / 7 | visible 8, identity 6 |
| Visual-identity stage | 200 | 63 | 333 | 12 | 5 / 7 | visible 4, identity 3 |
| Lineage graph / explicit history | 200 | 46 | 312 | 12 | 5 / 7 | visible 4, identity 3 |
| Exact immutable revision | 200 | 6 | 12 | 0 | 1 / 2 | identity 2 |
| Empty table-observation stage | 200 | 63 | 585 | 12 | 5 / 7 | visible 8, identity 6 |
| Processor launch | 202 | 59 | 60 | 0 | 0 / 0 | none |
| Stale selected revision | 200 | 65 | 339 | 12 | 5 / 7 | visible 4, identity 3 |

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
empty table-observation stage and stale visual-identity selection. It asserts exact selected content,
sibling identity, node enumeration, history traversal count, and returned revision count.

The fixture keeps the two current-recording `history` method calls fixed, while records read grow
from 3 to 21 and node enumeration grows from 3 to 12. This directly shows that current projection
work follows retained history even with fixed current content. The API profiler separately checks
real persisted empty and stale state. The fixture does not claim that unrelated recordings cost zero
metadata enumeration; the workspace currently enumerates 12 nodes before filtering.

## Reader, writer, and schema inventory

| Resource or boundary | Active readers | Active writers | Representative schema / path | Replacement and check |
| --- | --- | --- | --- | --- |
| Recording source and catalog | `recordings_api.list_recordings`, `RoundAnalysisService.recording_catalog`, `RecordingPipelineWorkspaceService.get_statuses` | `RecordingBundleStore` intake; `RoundAnalysisStore` analysis creation | `recording-video/v1`; `data/intake/recordings/<id>/`; `data/operations/round-analyses/` | Compact recording and current-state summary; profile `/v1/recordings`; verify catalog omits revision payloads and histories. |
| Node manifests, HEAD, revisions | `PipelineNodeStore.get`, `list_nodes`, `history`, `read_revision_record`; workspace and stage APIs | `PipelineNodeStore.create`, `save`, transaction recovery | `pipeline-node/v1`, `pipeline-node-revision/v1`; `data/operations/pipeline-nodes/<node>/` | Snapshot exact references and bounded content access; verify identities, digest, ancestry, and pagination. |
| Per-content generated and completed selection | `PipelineNodeSelectionStore.get_exact`; stage APIs; workspace and recording catalog | `PipelineNodeSelectionStore.update_exact`; editor/review/selection services | `pipeline-node-selection/v1`; `.pipeline-node-selections/<recording>/<type>.json` | Snapshot separate generated/reference slots and explicit HEAD updates; verify CAS, independent reviews, empty/stale pointers. |
| Lineage runs and requests | `PipelineLineage.snapshot`, workspace `_node_revisions_for_recordings`, explicit lineage API | `PipelineLineage.start`, `PipelineLineageWriter`, processor services | `pipeline-lineage-request/v1`, `pipeline-lineage-run/v1`; `.lineage-requests/`, `.lineage-runs/` | Keep exact graph access explicit; profile graph reads and ensure normal catalog/workspace do not scan unrelated history. |
| Review drafts and coverage | `PipelineNodeReviews`, visible-card review, frame-review and lineage draft projections | Review APIs, node edit service, frame-review workflow | `pipeline-review/v1`, `frame-review-workflow/v1`; node review roots and review stores | Preserve independent review work; verify sibling reviews and durable restart. |
| Calibration and reconstruction | Calibration refinement API/service; round-analysis readers and package lineage | `CalibrationRefinementService`, `RoundAnalysisService` | `table-plane-calibration/v1`, `table-plane-calibration-refinement/v1`, `round-analysis/v1`; calibration and round-analysis roots | Inventory exact selected references in M1; verify calibration/reconstruction resources are not assumed to be ordinary nodes. |
| Processor requests, outputs, and jobs | Stage APIs, `AutomatedPipelineRunService`, Job Manager projection | Stage processor services, `PipelineLineageWriter`, Job Manager | `processor-run-request/v1`, `automated-pipeline-run/v1`; per-run and job roots | Freeze exact snapshot/input references; output publication must not change selection. Verify launch, retry, cancel, and restart. |
| Recovery and startup | backend lifespan, Job Manager recovery, storage recovery | recovery services and durable stores | M15 storage map roots; operation-specific `schema_version` | Keep M15 storage authority; verify fresh-process startup and recovery with isolated roots. |

The M14 storage map names local retained roots and recovery authority. M15 closed the selected cleanup
scope; it did not close operational lifecycle work. Do not move 0118 lifecycle writers into this
epic unless they conflict directly with the recording-state contract.

## Frozen budgets and finite trials

The M0 reference values are the three-session medians above. Noise uses the 0114 method:
`max(3 × 1.4826 × MAD, category floor)`. The floor is 2 ms for JSON and 25 ms for startup. The
no-regression ceiling adds 20% of the reference plus the noise allowance. The rounded ceilings are:

| Case | Reference | Noise allowance | No-regression ceiling | M16 planning target |
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
- 0117 boundary profiler — passed all eight HTTP cases, with empty/stale response assertions; output in the linked artifacts.
- Growth fixture and API tests — passed; includes accepted deterministic processor launch and persisted empty/stale state.
- Focused Ruff check and format check — passed for new script and test.
- Startup timings — three fresh hard-populated processes passed all first-use probes.

The profiler records repeated JSON loads and domain parsers but not every internal model validation.
The existing empty/stale API tests validate state behavior. No production performance change or speedup
is claimed in M0.

## Reproduction

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard
mise exec -- uv run --project backend python backend/scripts/profile_0117_workspace_reads.py --output /tmp/0117-boundaries.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_pipeline_read_performance.py --warmups 0 --repeats 2 --batches 1 --timeout 180 --case workspace_full_hard --output /tmp/0117-session-pipeline.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile hard_populated --startup-processes 1 --timeout 180 --output /tmp/0117-session-startup.json
mise exec -- uv run --project backend pytest -q backend/tests/test_0117_workspace_growth_fixture.py backend/tests/test_pipeline_run_api.py backend/tests/test_pipeline_api.py::test_recording_pipeline_workspace_aggregates_persisted_stage_state backend/tests/test_pipeline_api.py::test_recording_pipeline_workspace_reports_invalid_selection_pointer
```
