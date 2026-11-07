# 0112 M0 module map

## Snapshot and readiness

Inventory snapshot: commit `e77a831abad2d407ef4db0f18eee0e3c6797cb3c` (2026-11-07). The six
source targets and two large test targets were unchanged from `2cf915b83`; the later commit changed
0114 performance fixtures and documentation only.
The readiness gate passes. The closed 0108 M11 and 0110 M15 plans are present, and commits
`767a966f54` and `ee10f1e5bd` are in this checkout. The six selected source files remain active.
This milestone makes no code extraction.

## Recount

Physical lines at the snapshot use `wc -l`; activity counts are commits that touched each path
since 2026-11-02 00:00 Europe/Berlin through the snapshot.

| Path | Lines | Touches | M0 finding |
| --- | ---: | ---: | --- |
| `backend/src/dokodetector_backend/visual_identity_pipeline_service.py` | 2,617 | 12 | Active service. Keep crop resolution, execution, publication, and approval behind typed helpers. |
| `web/src/api/client.ts` | 1,099 | 19 | Active transport, contracts, methods, and paths. Reuse existing jobs and lineage clients. |
| `web/src/pipeline/RecordingPipelineWorkspace.tsx` | 838 | 18 | Active workspace composition and request, selection, URL, and presentation state. |
| `backend/src/dokodetector_backend/pipeline_store.py` | 1,814 | 10 | Active revision and processor-run stores. `LegacyProcessorRunStore` remains imported by migration inventory; do not remove it in M4 without tracing that caller. |
| `web/src/pipeline/RunControls.tsx` | 1,099 | 6 | Active controls, run status, option construction, and request building. Coordinate M8 with 0113. |
| `backend/src/dokodetector_backend/job_store.py` | 1,034 | 7 | Active job models, cancellation, lifecycle, persistence, and recovery. |
| `backend/tests/test_visual_identity_pipeline_api.py` | 1,778 | 12 | Active mixed HTTP and service characterization suite. |
| `web/src/pipeline/RecordingPipelineWorkspace.test.tsx` | 1,638 | 14 | Active workspace and URL integration suite. |

The former `backend/tests/test_pipeline_reference.py` is absent after 0108 M11. Do not restore
it. The retained successor checks are grouped under `test_pipeline_store.py`, node selection,
lineage, and node-review suites. The old selection and reference-store responsibilities are not
extraction targets unless a current owner is found.

Recount commands:

```sh
wc -l <the eight paths in the table>
git log HEAD --since='2026-11-02T00:00:00+01:00' --format='%h' -- <path>
```

## Owners, typed boundaries, and dependency direction

| Milestone | Current symbols and callers | Destination and boundary | Required direction |
| --- | --- | --- | --- |
| M1 | `VisualIdentityPipelineService._build_request`, `_canonical_input_node_ref`, `canonical_input_revision`, `_freeze_crop_input`, `_reviewed_virtual_card_items`, `_validate_scene_derived_views`; `visual_identity_jobs.VisualIdentityJobParticipant` calls the service. | `visual_identity_crop_inputs.py` owns frozen request inputs and the exact revision/item/provenance result; `visual_identity_crop_sources.py` owns source revision and reviewed scene validation. Pass stores and the accepted recording source explicitly. | Service composes helpers; input/source modules do not import the service or job participant. Focused reviewed-scene and repeated source-validation tests: `backend/tests/test_visual_identity_crop_sources.py`; managed-job and same-frame proposal mapping stay in `test_visual_identity_pipeline_api.py`. |
| M2 | `_ValidatedCropContext`, `_crop_dependency_fingerprint`, `get_identity_crop_identity`, `_validated_identity_crop_outcome`, `resolve_reviewed_annotation_crops`, `resolve_reviewed_annotation_crop`, `_reviewed_crop_input_context`, `resolve_identity_crop`, `_resolve_identity_crop_from_validated`, `_validate_crop_input_provenance`, `_crop_input_provenance`, `_canonical_crop_source`, `resolve_identity_crop_browser_preview`; API routes and review consumers call public resolution methods. | `visual_identity_crop_resolution.py` accepts typed crop request/context and returns crop bytes plus identity; `visual_identity_crop_provenance.py` validates and creates typed provenance. | Resolution may use input and provenance modules; these modules do not import the service or route layer. Keep HTTP error conversion at route/service boundary. |
| M3 | `execute_job`, `_process_card`, `_process_card_timed`, classifier selection and identity, publication/failure helpers, auto-approval planning; caller is `VisualIdentityJobParticipant`. `_build_request` and crop query orchestration also remained in the service after M1/M2. | `visual_identity_classification.py` owns per-card processing and classifier selection; `visual_identity_job.py` owns execution and publication; `visual_identity_approval.py` owns approval planning; `visual_identity_request.py` owns request construction and crop-input selection; `visual_identity_crop_queries.py` owns validated crop/result reads; `visual_identity_recording_access.py` validates the accepted video. Keep `VisualIdentityPipelineService` as a thin composition root with typed entry points. | Components use explicit stores, source access, crop freezing, and classifier operations; no component imports the service. The approval planner returns a typed optional local-run request, which the service starts through the shared classification operation. JobManager owns cancellation and publication arbitration. |
| M4 | `PipelineRuntimeStorage`, `PipelineRevisionStore`, `ProcessorRunStore`, split-state codec helpers, `LegacyProcessorRunStore`; callers include `pipeline_composition`, pipeline services, `pipeline_lineage_writer`, and `lineage_migration_inventory`. | `pipeline_revision_store.py`; `processor_run_store.py`; `processor_run_codec.py`; bounded shared `pipeline_storage.py` for path, lock, JSON, and errors only where shared. Typed store operations keep existing exact revision and run result contracts. | Composition and services depend on store interfaces; stores use storage primitives and codecs. Codecs do not depend on stores. Trace and retain `LegacyProcessorRunStore` only for its current migration caller; do not make a compatibility facade. |
| M5 | `ApiError`, private `requestJson`, `readResponseBody`, `jsonHeaders`; client methods pass `RequestInit` or `AbortSignal`. | `web/src/api/transport.ts` owns typed `requestJson`, body decoding, headers, timeout, and caller abort. Keep feature response types in hand-written contract modules only when generated schemas do not already cover them. | Feature clients depend on transport and contracts; transport does not import clients or feature modules. |
| M6 | `DokoDetectorClient`, `createDokoDetectorClient`, path builders, methods, `SAMPLED_FRAME_INTERVAL_US`, `snapSampledFrameTimeUs`; callers import from `client.ts` across recordings, jobs, pipeline, review, and analysis. | Feature clients and contracts for recordings, pipeline processing, calibration, and analysis. Keep shared frame URL/sampling helpers under one explicit owner. Keep `client.ts` only as a small factory if still needed. | Feature modules use transport, their contracts, shared frame helpers, and existing jobs/lineage clients. No feature imports the aggregate factory. Generated `openapi.ts` remains generated. |
| M7 | `RecordingPipelineWorkspace`; loading and abort effects, stale-result checks, `chooseInitialStage`, `sanitizeUrlState`, `isKnownItem`, response guards, and selection commands. Callers: `recordings.tsx` and composition tests. | `useRecordingPipelineData.ts` returns typed workspace/graph state and refresh operations; `recordingPipelineSelection.ts` owns pure URL and initial-choice commands; `useRecordingPipelineSelection.ts` owns selection effects and commands; reuse `recordingPipelineUrl.ts`. | Hooks depend on feature clients and pure selection helpers; composition root depends on hooks and presentation. No second selection authority. |
| M8 | `RunControls`, `RunStatus`, `buildRunRequest`, `buildCropInputOptions`, crop formatting and `initialVisibleCardModelVariant`; caller is `RecordingWorkspaceInspector`. | `pipelineLaunchRequest.ts` owns typed payload construction, crop choices, defaults, and validation. Move surviving stage sections to `EventLaunchFields.tsx`, `VisibleCardLaunchFields.tsx`, and `VisualIdentityLaunchFields.tsx`. Keep one submission owner. | Fields depend on typed request helpers and shared jobs navigation; no private polling or duplicate lifecycle. Reconcile the same boundary with 0113 before editing. |
| M9 | `JobError` hierarchy, `CancellationToken`, Pydantic job/request/queue/intent/publication/log models, `_digest`, `_mapping_digest`, `_uuid`, and `JobManager._intents`, `_recover`, `_reconcile`, `accept`, `cancel`, `retry`, `publish`, transitions. Callers include `jobs_api`, scheduler, and job participants. | `job_models.py` owns typed records and errors; `job_recovery.py` parses/replays intents and reconciles restart state through explicit persistence operations. Keep mutation and lock ownership with `JobManager`; move `FakeParticipant` to test support only after consumer search. | Manager owns lifecycle and lock; recovery uses manager-owned persistence operations and cannot mutate outside its lock. |
| M10 | All modules and tests above; generated API and local fixture workflow. | Add bounded source/test size and import-direction checks for the explicit file list. Keep focused tests with each owner and the fixture workflow. | No helper cycles, feature-client import of aggregate root, or production import of test support. |

## Budgets and focused checks

All six selected roots: at most 500 physical lines each. Every new production module: at most 700
lines. Every focused test file: at most 800 lines. Do not compress code to pass these limits. The
M3 service split and M4 store split need several bounded owners; a single catch-all helper would
fail the budget intent.

Use these selectors after each relevant move:

```sh
mise exec -- uv run --project backend pytest -q backend/tests/test_visual_identity_pipeline_api.py
mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_store.py backend/tests/test_pipeline_node_selection_store.py backend/tests/test_pipeline_lineage.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_pipeline_node_uses.py
mise exec -- uv run --project backend pytest -q backend/tests/test_job_store.py backend/tests/test_jobs_api.py backend/tests/test_job_scheduler.py
cd web && npm test -- --run src/api/client.test.ts src/pipeline/RecordingPipelineWorkspace.test.tsx src/pipeline/RunControls.test.tsx
```

M10 also runs backend Ruff lint/format; web typecheck, ESLint, Prettier, generated API verification,
the focused browser checks, and a local fixture flow from exact selected input through managed
identity execution, publication, reload, and result inspection. The browser checks cover workspace
selection, launch, and shared job navigation.

## Behavior gates and current evidence

| Gate | Existing selector or exact gap |
| --- | --- |
| Proposed-scene pose IDs map to detector IDs | `test_proposed_virtual_card_identity_run_reopens_and_previews_after_restart`; keep exact same-frame pose-to-detector identity and source lineage assertions with M1/M2. |
| Frozen crop revision and provenance | `test_visual_identity_reuses_run_source_validation_for_each_card`, `test_proposed_virtual_card_identity_run_reopens_and_previews_after_restart`, and `test_visual_identity_pipeline_uses_generated_geometry_and_restarts`. |
| Finite, normalized identity probabilities | `test_visual_identity_classification_runs_as_a_managed_job` reads persisted outcomes and asserts finite probabilities that sum to one. |
| Cancellation versus publication | `test_identity_cancellation_wins_at_publication_arbitration` requests cancellation after classification completes but before the shared manager's publication arbitration. It verifies no result revision or selection advance is published. |
| Restart recovery and retry | `test_visual_identity_pipeline_uses_generated_geometry_and_restarts`, `test_visual_identity_pipeline_retry_resumes_retained_items`, `test_proposed_virtual_card_identity_run_reopens_and_previews_after_restart`, `test_restart_recovery_uses_compact_status_catalog`, and parameterized `test_acceptance_recovers_each_write`. The first three are split between `test_visual_identity_crop_queries.py` and `test_visual_identity_job.py`. |
| Exact node input selection | `RunControls.test.tsx`: “defaults to reviewed upstream input and permits an exact historical revision”, “lists exact proposed scene revisions and requires a choice when several exist”, and “preselects one crop input and requires an explicit choice when several exist”. API-level identity request checks are in `test_visual_identity_classification_runs_as_a_managed_job`. |
| Stale workspace responses | `RecordingPipelineWorkspace.test.tsx` covers stale explicit lineage and optimistic selection conflict. Source uses abort controllers for workspace and graph requests, but no test specifically resolves an older recording response after a switch. Add a race characterization in M7 before moving loading state. |
| Browser timeout and caller abort | `client.test.ts` now covers caller abort forwarding and reason propagation. `requestJson` contains an optional timeout branch, but no caller supplies `timeoutMs`; no public timeout behavior exists to characterize. Keep that as an explicit M5 gap unless a live timeout caller is found. |

## M0 checks and limits

Passed:

- `mise exec -- uv run --project backend pytest -q backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_pipeline_store.py backend/tests/test_job_store.py backend/tests/test_jobs_api.py backend/tests/test_pipeline_run_api.py` — 45 passed.
- `cd web && npm test -- --run src/api/client.test.ts src/pipeline/RecordingPipelineWorkspace.test.tsx src/pipeline/RunControls.test.tsx` — 45 passed after adding caller-abort characterization.
- `cd web && npm run typecheck` — passed.
- `cd web && npx prettier --check src/api/client.test.ts` — passed.

The backend run reports an installed Starlette deprecation warning for `httpx` in its test client.
No source behavior changed. Timeout is not configured by a client call. Three behavior gaps are
carried to M3, M7, and M9 above; they do not authorize extraction to skip those checks.
