# 0112 cleanup handoff

## Result

Epic 0112 M0–M10 is complete. The cleanup moved the selected behavior into bounded owners and
added an automated check for the explicit owner and focused-test list. This is a source-ownership
result. No agent speed gain was measured or is claimed.

## Before and after sizes

The before counts are the M0 inventory. The after counts are physical lines at M10. The size guard
also checks every extracted module and focused test in its explicit list.

| Original target | Before | M10 owner or owners | After |
| --- | ---: | --- | ---: |
| `visual_identity_pipeline_service.py` | 2,617 | `visual_identity_pipeline_service.py` | 412 |
| `client.ts` | 1,099 | aggregate factory in `client.ts` | 21 |
| `RecordingPipelineWorkspace.tsx` | 838 | workspace composition in same file | 476 |
| `pipeline_store.py` | 1,814 | retired; revision/run owners include `pipeline_revision_store.py` and `processor_run_store.py` | 635 / 619 |
| `RunControls.tsx` | 1,099 | submission composition in same file | 489 |
| `job_store.py` | 1,034 | lifecycle owner in same file | 499 |
| `test_visual_identity_pipeline_api.py` | 1,778 | HTTP contract suite in same file | 244 |
| `RecordingPipelineWorkspace.test.tsx` | 1,638 | workspace suites by loading, selection, and presentation | 671 / 727 / 566 |
| `RunControls.test.tsx` | 1,301 | event/visible-card and visual-identity suites plus shared builders | 548 / 665 / 89 |

The old `pipeline_store.py` no longer exists. Its retained storage responsibilities have focused
owners; the M4 report records the complete owner sizes and the migration-only legacy reader.

## Owner and import map

- **Visual identity:** `visual_identity_pipeline_service.py` composes typed crop-input, crop-source,
  crop-resolution, provenance, classification, job, approval, request, query, and recording-access
  modules. Helpers do not import the composition service. Crop tests stay with the source,
  resolution, job, and query owners.
- **Pipeline persistence:** `pipeline_revision_store.py`, `processor_run_store.py`, codecs, catalog,
  reader, and storage primitives own separate revision and processor-run concerns. The legacy run
  reader is limited to migration inventory and the offline repair tool.
- **API:** `client.ts` composes feature clients. Feature clients depend on transport, contracts,
  shared frame helpers, and jobs/lineage clients. They do not import the aggregate factory.
- **Workspace:** `RecordingPipelineWorkspace.tsx` composes data and selection hooks. Selection and
  URL helpers own their logic; request ownership stays scoped to the recording and request.
- **Launch UI:** `RunControls.tsx` submits requests. `pipelineLaunchRequest.ts` builds typed payloads;
  stage forms and retained-run presentation have focused owners. The shared Job Manager remains the
  only scheduling and publication authority.
- **Jobs:** `job_store.py` owns lifecycle mutations and its lock. `job_models.py` owns records,
  `job_persistence.py` owns durable operations, and `job_recovery.py` owns intent replay and restart
  reconciliation through manager-owned operations. Production imports no test support.
- **Size and import guard:** run `python scripts/check_0112_boundaries.py`. The explicit paths and
  budgets live in that script. It checks selected roots at 500 lines, extracted production owners at
  700 lines, focused tests at 800 lines, feature-client imports, visual-identity cycles, and
  production imports of test support. Generated `openapi.ts` is excluded.

Three examples show the files needed for a change:

1. Crop validation: `backend/src/dokodetector_backend/visual_identity_crop_sources.py` and
   `backend/tests/test_visual_identity_crop_sources.py`.
2. Launch payloads: `web/src/pipeline/pipelineLaunchRequest.ts` and
   `web/src/pipeline/RunControlsVisualIdentity.test.tsx`.
3. Restart recovery: `backend/src/dokodetector_backend/job_recovery.py` and
   `backend/tests/test_job_recovery.py`.

## Checks and results

- `python scripts/check_0112_boundaries.py` — passed; every explicit path exists and meets its
  budget, with no prohibited import direction or helper cycle. A post-close review found that the
  first guard version selected files using the source directory suffix, so it did not inspect
  backend Python modules. The corrected scanner parses backend imports and scans all production
  `.ts` and `.tsx` modules under `web/src`, including dynamic imports and adjacent `*TestFixtures`
  modules. It skips test files and test-only directories.
- `mise exec -- uv run --project backend pytest -q scripts/test_0112_boundaries.py` — 3 passed.
  The regressions prove that backend `test_support`, static adjacent fixture imports, and dynamic
  fixture imports outside `api/` and `pipeline/` are rejected.
- `mise exec -- uv run --project backend pytest -q backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_visual_identity_approval.py backend/tests/test_visual_identity_classification.py backend/tests/test_visual_identity_crop_queries.py backend/tests/test_visual_identity_crop_resolution.py backend/tests/test_visual_identity_crop_sources.py backend/tests/test_visual_identity_job.py backend/tests/test_visual_identity_request.py backend/tests/test_pipeline_store.py backend/tests/test_pipeline_node_selection_store.py backend/tests/test_pipeline_lineage.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_pipeline_node_uses.py backend/tests/test_job_store.py backend/tests/test_jobs_api.py backend/tests/test_job_scheduler.py backend/tests/test_job_recovery.py backend/tests/test_job_publication.py` — passed.
- The real local fixture path passed in
  `test_visual_identity_pipeline_uses_generated_geometry_and_restarts` and
  `test_visual_identity_classification_runs_as_a_managed_job`. The tests select exact node input,
  run managed identity processing, verify publication and output lineage, restart the app, and
  inspect the retained result.
- The M4 storage and migration consumer suite passed:
  `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_store.py backend/tests/test_pipeline_node_selection_store.py backend/tests/test_pipeline_lineage.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_pipeline_node_uses.py backend/tests/test_pipeline_node_reviews.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_pipeline_run_api.py backend/tests/test_pipeline_comparison_api.py backend/tests/test_pipeline_vision_comparison_api.py backend/tests/test_proposed_card_scene_pipeline.py backend/tests/test_event_recovery_catalog.py backend/tests/test_job_store.py backend/tests/test_jobs_api.py backend/tests/test_job_scheduler.py backend/tests/test_repair_0100_m5.py`.
- The M9 job consumer suite passed (45 tests):
  `mise exec -- uv run --project backend pytest -q backend/tests/test_visual_identity_job.py backend/tests/test_calculation_jobs.py backend/tests/test_automated_pipeline_jobs.py backend/tests/test_proposed_card_scene_pipeline.py backend/tests/test_round_analysis_logging.py backend/tests/test_pipeline_api.py`.
- `mise exec -- uv run --project backend ruff check backend/src backend/tests scripts/check_0112_boundaries.py`
  and `mise exec -- uv run --project backend ruff format --check backend/src backend/tests scripts/check_0112_boundaries.py`
  — passed (215 files formatted).
- In `web/`, `npm test -- --run src/api/client.test.ts src/api/transport.test.ts src/api/analysisClient.test.ts src/api/calibrationClient.test.ts src/api/pipelineProcessingClient.test.ts src/api/recordingsClient.test.ts src/pipeline/RecordingPipelineWorkspace.test.tsx src/pipeline/RecordingPipelineWorkspaceSelection.test.tsx src/pipeline/RecordingPipelineWorkspacePresentation.test.tsx src/pipeline/useRecordingPipelineData.test.tsx src/pipeline/useRecordingPipelineSelection.test.tsx src/pipeline/RunControlsEventAndVisibleCard.test.tsx src/pipeline/RunControlsVisualIdentity.test.tsx` — 13 files and 87 tests passed.
- `npm run typecheck`, `npm run lint`, `npm run format`, and `npm run verify:api` — passed. API verification regenerated OpenAPI into a temporary file and matched the checked-in generated client.
- `npx playwright test tests/e2e/pipeline-cutover.spec.ts tests/e2e/job-start-actions.spec.ts -g 'opens fresh accepted video|starts a fact-complete pipeline|job start actions fixture'` — 4 browser checks passed for recording selection, launch, and shared Jobs navigation.
- Exact launch-suite parity check — passed; all 19 original test names occur once across the two new suites.
- `git diff --check` and local Markdown-link checks for the moved epic, board, 0113 reference, and handoff — passed.

An initial broader browser run also selected two unrelated assertions in
`pipeline-lineage-workspace.spec.ts`; those failed because the fixture did not expose the expected
lineage editor and comparison selector. The focused M10 browser checks above passed. Backend tests
reported the existing Starlette `httpx` deprecation warning. Playwright logged expected proxy errors
for fixture requests without a backend; its routed tests passed. Browser API routes are mocked, so
they verify UI behavior only. The backend fixture test covers persisted processing and restart.

## Limits

No cloud service, phone, training job, sealed evaluation, production deployment, or performance
benchmark was used. The checks show fixture correctness and source boundaries. They do not qualify
production behavior or demonstrate speed gains.
