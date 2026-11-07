# Epic 0114 M0: interactive UI route and startup inventory

Date: 2026-11-07
Scope: M0 inventory only. No performance timings or fixes were selected.

## Route inventory

`0114-M0_Interactive_UI_Performance_Inventory.json` records all 75 FastAPI OpenAPI operations
found by constructing the app with the local POC analyzer, plus one UI media URL that has no
registered backend route. Each row has a method, route, classification, caller, planned scenario,
fixture tier, cache mode, and budget key. The inventory checker fails for an unclassified row, a
duplicate, a new or removed registered API operation, or a UI path with no scenario.

Coverage groups include:

- Catalog, recording detail, analysis creation and reads, timeline, counterfactuals, observations,
  thumbnails, source video, and evidence frames.
- Pipeline workspace and lineage, stage and result reads, selections, comparisons, derived frame
  and identity-crop media, calibration edits, run submission/status, and node/review edits.
- Frame review queue and save, job polling/history/detail/logs, submission, cancellation, retry,
  and queue movement.
- The remaining registered evidence and pending-video intake operations and health probes, each
  explicitly classified as non-web or infrastructure.

The exact methods and route templates are in the JSON inventory. Query and payload variants are
planned in M2–M4; the inventory does not claim that they have executable cases yet.

### UI route registration discrepancy

`web/src/visualIdentities/PipelineNodeVisualIdentityEditor.tsx` sets a video source at
`/api/recordings/{recording_id}/video`. This path is not registered by the FastAPI app or present
in generated OpenAPI. The backend has `/v1/repository-bundles/{recording_id}/video` instead. The
route remains classified as a UI media case with a registration gap. M2/M4 must resolve the
contract before timing it. Do not treat this 404/registration uncertainty as a performance result.

### Browser trace sample

Ran `npx playwright test jobs.spec.ts --trace on` in `web/` (4 tests passed). The bounded trace
files are under ignored `web/test-results/jobs-*/trace.zip`. Captured browser requests confirmed
the Jobs drawer and history scenarios use `GET /api/jobs`, job details use
`GET /api/jobs/{job_id}`, logs use `GET /api/jobs/{job_id}/logs`, and the application also loads
`GET /v1/recordings`. The tests intercept API responses, so this is call-path evidence only; it is
not real-backend latency evidence. M5 must add and run an isolated real-backend browser profile.

## Startup and first-use map

The normal process path is the `dokodetector-backend` console entry point in
`backend/pyproject.toml`, which calls `dokodetector_backend.server:run`:

1. `server.run` configures logging, resolves `Settings`, discovers Bonjour host/address when not
   configured, enters the optional Bonjour advertiser, then calls Uvicorn with
   `dokodetector_backend.app:create_app` and `factory=True`.
2. Uvicorn imports and constructs the app. Synchronous factory work creates storage and service
   objects, validates configured processors, creates lazy analyzer/provider configuration,
   composes pipeline services and job handlers, and calls event-pipeline interrupted-run recovery.
   This work precedes lifespan and is a separate startup interval.
3. FastAPI lifespan starts `JobManagerService` (manager ownership, publication reconciliation,
   scheduler) and the pipeline event, visible-card, and visual-identity services, then logs
   `backend_started`. Shutdown stops services in reverse order. Uvicorn allows 30 seconds for
   graceful shutdown; the server limits concurrent HTTP requests to 40.
4. `/health/live` proves only that the process answers. `/health/ready` creates and tests required
   filesystem roots, checks read/write access, and verifies atomic replacement in the runtime
   root. It does not prove a representative UI route works. Startup qualification must therefore
   time readiness and then the first successful `/v1/recordings` plus a workspace response.
5. The first useful response can still pay lazy provider, catalog, filesystem, source-video, or
   derived-view work. M2 must time first use separately from process readiness.

### Planned process profiles and isolation

Use three isolated profiles after M1 freezes fixture contents: empty storage; hard populated
storage; and deterministic interrupted-job recovery. Give each fresh process a temporary,
profile-specific settings root for evidence, operations, repository intake, pending videos, and
pipeline data. Never point a profile at the developer's live roots. Disable Bonjour, bind to
loopback on an OS-assigned free port, and retain the exact launch command and environment.
Materialize fixtures before the startup clock starts. Keep measured request setup and fixture
cleanup outside the timed interval.

The process runner must start a process group, poll `/health/live` for liveness and `/health/ready`
for readiness with a finite deadline, then require successful recordings and workspace responses.
On success or failure, send SIGTERM, wait up to 30 seconds, then kill the process group and assert
that it exited. Retain stdout/stderr and the exit result. A timeout, failed probe, failed useful
request, or surviving process is a failed sample, not an omitted measurement. These are M2 runner
requirements, not implemented process tooling in M0.

## Checks and baseline

- `npx playwright test jobs.spec.ts --trace on` — PASS, 4 tests; trace evidence is mocked and
  bounded as described above.
- `mise exec -- uv run --project backend python backend/scripts/check_interactive_ui_performance_inventory.py`
  — PASS, all registered OpenAPI operations classified, one unregistered UI video URL recorded.
- Existing unrelated changes were present in the worktree during this inventory. No repository-wide
  backend or web baseline suite was run, so no unrelated test baseline is claimed here.

## Handoff

M0 closes with a checked API-operation inventory, one explicit UI/backend video-route discrepancy,
browser request traces, startup phase map, probe definitions, and process isolation/cleanup
requirements. M1 is next: inventory hard local data metadata, select exact examples, and freeze
generated fixtures. Do not promote the mocked browser traces into backend timing results.
