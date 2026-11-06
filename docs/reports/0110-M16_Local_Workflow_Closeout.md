# 0110 M16 — Local workflow and operator handoff

## Result

The mixed-recording fixture workflow uses one local Job Manager. A six-stage parent for
`recording-1` runs with one scheduler slot. An independent leaf for `recording-2` runs between
parent stages. The fixture verifies that the parent releases its slot while it waits for a child.
It also verifies one active handler at a time.

Other focused fixtures cover queue move conflicts and restart order, queued cancellation, parent
cancellation while a child runs, restart after child acceptance, failed-stage history, and explicit
parent retry with verified completed-stage reuse. The browser workflow covers exact result links,
history paging, reload, back and forward navigation, disconnection recovery, hidden-page polling,
and the desktop and narrow Jobs drawer.

## Ownership

| Concern | Owner |
| --- | --- |
| Acceptance, durable records, idempotency, queue order, recovery, and cancellation | `JobManagerService`, `JobManager`, and `JobScheduler` |
| Producer validation, resource claims, execution, and publication | Registered participants in `event_jobs.py`, `visible_card_jobs.py`, `proposed_card_scene_jobs.py`, `visual_identity_jobs.py`, `observation_jobs.py`, `round_analysis_jobs.py`, `automated_pipeline_jobs.py`, and `calculation_jobs.py` |
| Processor and analysis outputs, provenance, review, and maintained references | Their domain stores and APIs |
| Browser job state, lifecycle actions, history, and exact result navigation | `JobStateProvider`, the shared `/api/jobs` client, `JobsDrawer`, and `/jobs/{id}` |
| Input selection and validation before launch | Existing domain launch forms |

Every in-scope asynchronous producer is registered with the shared manager. The remaining frame
worker pools are inside visible-card and visual-identity handlers. They use the CPU claim passed by
the scheduler. The local scheduler uses one processing slot and one CPU permit. The fixture does
not use cloud services, a phone, full training, or sealed evaluation.

## Operator handoff

1. Start work from its existing recording or analysis form. The form validates and freezes its exact
   inputs, then returns a manager job ID.
2. Open **Jobs** in the persistent application header to see queued, active, and recent failed work.
   Open a job row for its steps, failure details, and exact result links.
3. Cancel, retry, or reorder work from the shared job controls. Reorder conflicts return current
   queue state. Retry creates a new linked attempt and keeps the previous result and failure.
4. Use the domain workspace to select, review, or apply a result. Job completion does not change a
   maintained reference or apply a counterfactual correction.
5. After a backend restart, inspect interrupted leaves and parent groups in Jobs. Retry interrupted
   work explicitly. Do not treat an interrupted job as successful.

Provider calls that cannot stop mid-call finish before cancellation takes effect. The manager keeps
the resource claim until the handler stops. Local fixtures verify this behavior; this milestone did
not measure live model memory or inference time.

## Changes and verification

- Migrated producer tests from removed per-run status and retry routes to `/api/jobs` and exact
  result routes. Added nullable `job_id` to strict processor result schemas and regenerated browser
  API types.
- Enforced the single CPU permit in visible-card and visual-identity inner worker pools. The
  scheduler fixture proves one active worker across mixed recordings.
- Updated stale session-preflight expectations to match generated recording context. Corrected
  existing formatting, lint, and browser Blob test setup so repository checks are reproducible.
- The 135 focused backend producer and Job Manager tests passed, including queue, restart,
  cancellation, parent retry, result publication, and exact inputs.
- `ruff check .` and `ruff format --check .` passed.
- Web `npm run check` passed: typecheck, lint, formatting, generated API verification, and all 179
  Vitest tests.
- `npx playwright test tests/e2e/jobs.spec.ts` passed (4 tests).
- Focused job browser and production build checks passed.
- No cloud, phone, model training, or sealed evaluation ran.

## Closure

M0–M16 are complete. Launch forms retain their domain-specific input choices. All lifecycle
operations use the shared manager and Jobs UI. Domain stores remain authoritative for outputs and
review decisions.
