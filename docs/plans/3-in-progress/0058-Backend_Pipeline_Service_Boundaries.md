# Backend pipeline service boundaries

## Plan status

- **Summary:** Separate clear backend pipeline responsibilities so one stage, reference, or
  workspace change does not require the complete pipeline service and API surface.
- **Status:** In Progress
- **Depends on:** 0053 discovery complete
- **Outcome:** Backend pipeline code has explicit service, contract, route, and store ownership.
  A stage, reference, comparison, or workspace change has one focused service and test entry.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Complete — traced service construction, state ownership, HTTP ownership, consumers, and
  focused checks. M3–M4 are ready for one `gpt-5.6-luna` phase each.
- **M1:** Complete — split pipeline HTTP schemas and routes by workspace, generated stage,
  derived view, comparison, and maintained reference while preserving one mounted API surface.
  Focused route inventory and generated-client verification cover the unchanged public contract.
- **M2:** Complete — moved event execution, comparison, and recording-workspace composition into
  responsibility-named modules. The workspace now receives a public recording-source provider,
  and direct service tests cover comparison and workspace behavior.
- **M3:** Not started — split maintained-reference commands into common lifecycle coordination and
  content-specific edit and coverage handlers.
- **M4:** Not started — make pipeline store ownership and application wiring explicit, then remove
  obsolete compatibility imports and prove the final module boundaries.

## M0 evidence and current ownership

The 0053 baseline records eight pipeline-named backend files with 7,450 lines. The current source
confirms three high-context boundaries:

- At M0, `pipeline_service.py` had 1,525 lines. It owned `EventPipelineService`,
  `PipelineComparisonService`, and `RecordingPipelineWorkspaceService`. Event execution owned
  lifecycle transitions. Comparison read immutable run and revision state. Workspace composition
  read selected revisions, maintained-reference state, and round-analysis summaries. These were
  separate responsibilities with no required shared mutable service state.
- `pipeline_reference_service.py` has 1,586 lines. It owns common reference lifecycle commands as
  well as event, visible-card, and visual-identity edits, coverage, correction impact, and
  publication. `PipelineReferenceStore` remains the sole owner of mutable reference bytes;
  `PipelineRevisionStore` remains the owner of immutable data revisions; and
  `PipelineSelectionStore` remains the owner of selected revisions.
- At M0, `pipeline_api.py` had 1,118 lines. It defined all pipeline HTTP response and request
  models and mounted workspace, event, visible-card, visual-identity, observation, derived-view,
  comparison, and maintained-reference routes from one router. The existing stage services already
  owned visible card, visual identity, and observation execution.

At M0, `app.py` constructed shared pipeline stores once, injected them into every service, started
and stopped the four execution services, and mounted one pipeline router. Tests imported the stores
and reference service directly. Other backend services consumed the stores directly. No other
production code imported the event, comparison, or workspace service classes except application
construction. The web client consumes generated OpenAPI, so route paths, operation schemas,
response bodies, and error semantics are public contracts even when their Python modules move.

The focused checks are `test_pipeline_api.py`, `test_pipeline_comparison_api.py`,
`test_pipeline_reference.py`, `test_visible_card_pipeline_api.py`,
`test_visual_identity_pipeline_api.py`, `test_observation_pipeline_api.py`, and
`test_local_pipeline.py`. The latter also verifies the local HTTP path and restart behavior.

## M1 evidence

`pipeline_api.py` is now the one aggregate router. It includes focused workspace, generated-stage
and derived-view, comparison, and maintained-reference routers in the existing order. HTTP models
live with their route area. Shared run, reference, and recording-ID translation lives in
`pipeline_api_contracts.py`. Routes read services from `request.app.state`; they do not construct
stores or services.

The route inventory test proves the four focused module boundaries. The named pipeline API tests
pass except for two pre-existing fixture failures in visual identity and round-analysis behavior.
`web` API verification produces no generated-client diff.

## M2 evidence

`event_pipeline_service.py`, `pipeline_comparison_service.py`, and
`pipeline_workspace_service.py` now own event execution, deterministic comparison, and
read-only workspace composition. Shared pipeline service errors live in
`pipeline_service_errors.py`. The old combined `pipeline_service.py` module and its direct
consumer imports are removed.

`EventPipelineService.get_recording_source` is the public source dependency injected into the
workspace service. Workspace composition no longer calls an event-service private method.
Direct comparison and workspace calls are covered beside the API tests. The M2 focused suite has
16 passing tests; full backend Ruff lint and formatting checks for the touched files pass.

## Target module ownership

Keep `pipeline_store.py` and `pipeline_reference_store.py` as storage boundaries. Do not create a
generic pipeline base class or a new data contract. Use direct dependencies that already exist:

| Module area | Owns | Must not own |
| --- | --- | --- |
| Stage services | One processor stage lifecycle and its run inputs and outputs | HTTP translation, reference editing, workspace assembly |
| Comparison service | Deterministic comparison of retained runs and revisions | Run lifecycle, selection changes, HTTP models |
| Workspace service | Read-only recording pipeline summary and stage blockers | Processor lifecycle, reference mutation, analysis execution |
| Reference lifecycle service | Common draft, completion, revision, selection, and conflict flow | Content-specific edit validation or coverage rules |
| Reference content handlers | Event, visible-card, or visual-identity payload validation, edits, coverage, and impact | Store writes outside the lifecycle service |
| Route modules | Pydantic HTTP models, request parsing, response translation, and error mapping | Pipeline state or domain validation duplicated from a service |
| Application composition | One store instance, explicit service construction, lifecycle registration, and router inclusion | Pipeline behavior |

Route modules can export their own `APIRouter`. A small pipeline router package can include them in
the current order. The application still includes exactly one pipeline router. Keep canonical and
hidden legacy route declarations unchanged. Do not change OpenAPI operation IDs, paths, models,
status codes, or error bodies.

## Delivery milestones

### M1 — Route and HTTP contract modules

Move only HTTP models, request parsing, response translation, and route declarations out of
`pipeline_api.py`. Create focused route modules for workspace, generated stages and derived views,
comparison, and maintained references. Keep shared response adapters in one deliberately named
contract helper only when two or more route modules use them. Each route receives its service from
`request.app.state`; it must not construct a store or service. Include the route modules through a
single pipeline router so application registration and generated OpenAPI remain unchanged.

Add or update API contract tests for the route inventory and representative success, validation,
conflict, unavailable, and result-not-ready responses for every moved route area. Run:

```bash
cd backend
uv run pytest tests/test_pipeline_api.py tests/test_pipeline_comparison_api.py \
  tests/test_pipeline_reference.py tests/test_visible_card_pipeline_api.py \
  tests/test_visual_identity_pipeline_api.py tests/test_observation_pipeline_api.py
uv run ruff check .
uv run ruff format --check .
cd ../web
npm run generate-api
npm run check
git diff --exit-code -- web/src/api/openapi.ts
```

### M2 — Execution, comparison, and workspace services

Move `EventPipelineService`, `PipelineComparisonService`, and
`RecordingPipelineWorkspaceService` from `pipeline_service.py` into responsibility-named modules.
Move only helpers used by one destination module with it. Extract a small shared helper module only
for immutable run or revision serialization used by more than one service. Do not let workspace
composition call event-service private methods; inject the recording source dependency it needs.
Keep the existing stage-service public methods and constructor behavior. Remove the former combined
service module after its remaining direct consumer imports change.

Add direct service tests for comparison and workspace boundaries where API tests currently provide
the only coverage. Run:

```bash
cd backend
uv run pytest tests/test_pipeline_service.py tests/test_pipeline_api.py \
  tests/test_pipeline_comparison_api.py tests/test_local_pipeline.py
uv run ruff check .
uv run ruff format --check .
```

### M3 — Maintained-reference lifecycle and content handlers

Keep `PipelineReferenceService` as the single command facade while it coordinates stored drafts,
immutable completed revisions, selected completion, concurrency conflicts, and timestamps. Move
the event, visible-card, and visual-identity command parsing, content mutations, coverage checks,
and downstream-impact calculations into content-specific handlers. A handler returns validated
content and declared effects; only the lifecycle facade writes through a store. Keep reference
revision and conflict semantics unchanged, including independent references for each content type.

Extend direct reference tests so each handler proves its content-specific coverage and correction
rules, and lifecycle tests prove publication and restart behavior. Run:

```bash
cd backend
uv run pytest tests/test_pipeline_reference.py tests/test_pipeline_api.py \
  tests/test_visible_card_pipeline_api.py tests/test_visual_identity_pipeline_api.py \
  tests/test_observation_pipeline_api.py
uv run ruff check .
uv run ruff format --check .
```

### M4 — Store composition and final boundary proof

Make `app.py` declare pipeline construction in one small composition helper: create shared stores
once, construct every service from explicit dependencies, register lifecycle-managed execution
services, and include the aggregate router. Keep application state keys stable during this epic.
Move a store only when its methods have one clear owner; otherwise retain the two existing store
modules. Delete superseded imports, re-export shims, and tests made obsolete by the final direct
imports. Do not change filesystem layout or persisted JSON.

Run the complete backend suite, formatting and lint checks, then regenerate and verify the web API:

```bash
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
cd ../web
npm run generate-api
npm run check
git diff --exit-code -- web/src/api/openapi.ts
```

## Acceptance criteria

- A change to one stage execution, comparison, workspace summary, reference content type, or route
  area requires reading its focused module and test area, not a combined pipeline file.
- Stores retain their current single-write ownership. Services do not duplicate request validation,
  revision validation, or persisted-state transitions.
- `create_app` is the only construction root for runtime pipeline stores and services. Dependency
  direction stays routes to services to stores; no service imports a route module.
- Existing HTTP and OpenAPI contracts are byte-for-byte unchanged after regeneration.
- Restart, selection, immutable lineage, derived-view, maintained-reference, visual identity, and
  local pipeline behavior remain covered by the named tests.

## Exclusions and overlap

Do not change HTTP, OpenAPI, persistence, processor, review, or failure semantics. Do not move
analyzer or game rules into the backend. Preserve 0051 visual identity and derived-view behavior.
Coordinate generated web API checks with the web verification boundary. Epic 0056 owns decisions to
remove superseded review or data interfaces. Epic 0057 owns operations package boundaries. This
epic only moves the current backend implementation around their unchanged contracts.
