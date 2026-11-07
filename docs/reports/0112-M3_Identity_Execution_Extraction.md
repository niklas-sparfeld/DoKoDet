# Epic 0112 M3 identity execution extraction

## Result

M3 moved visual identity request creation, crop queries, classification, job execution,
recording-source checks, and approval planning into focused owners. The service is now a 411-line
composition root. Its public methods delegate to typed components, and it starts any planned local
approval run through the existing shared `JobManager` path.

The approval planner returns a typed plan with an optional local run request. The service composes
that request into the shared classification start operation. The planner does not retain a service
callback. This keeps the dependency direction from the service to components and avoids a helper
that closes over the composition root.

## Owner map and sizes

| Owner | Lines | Responsibility |
| --- | ---: | --- |
| `visual_identity_pipeline_service.py` | 411 | Typed service entry points and component composition |
| `visual_identity_classification.py` | 426 | Classifier selection, identity, bounded concurrency, per-card processing |
| `visual_identity_job.py` | 383 | Managed execution, failure recording, exact output publication |
| `visual_identity_request.py` | 472 | Request construction, crop-input selection and freezing coordination |
| `visual_identity_crop_queries.py` | 394 | Validated crop, result, and preview reads |
| `visual_identity_approval.py` | 220 | Retained-result comparison and authority-guarded approval planning |
| `visual_identity_recording_access.py` | 94 | Accepted recording source and video path access |
| `visual_identity_pipeline_errors.py` | 9 | Shared visual identity pipeline error types |

The service was 1,905 lines at the M3 base. The mixed API test was 1,306 lines. The focused HTTP
suite is now 244 lines; all new modules are below 700 lines and all focused test files are below
800 lines. No extracted production component imports the service.

## Behavior evidence

- `test_visual_identity_candidates_are_bounded_and_ordered` preserves bounded ordered
  classification behavior.
- The managed-job fixture verifies exact crop provenance and finite candidate probabilities whose
  normalized scores sum to one.
- `test_identity_cancellation_wins_at_publication_arbitration` requests cancellation immediately
  before the existing manager publication arbitration. The job ends cancelled, records the
  cancellation failure, and does not publish a result or advance the generated selection.
- Retry and restart tests retain the existing shared manager recovery path. Managed execution has
  one scheduler and one publication authority.
- Auto-approval remains comparison planning. The service starts missing local work through its
  existing managed classification entry point, and review decisions remain outside the planner.

## Verification

Focused tests passed:

```sh
mise exec -- uv run --project backend pytest -q \
  backend/tests/test_visual_identity_pipeline_api.py \
  backend/tests/test_visual_identity_crop_queries.py \
  backend/tests/test_visual_identity_job.py \
  backend/tests/test_visual_identity_classification.py \
  backend/tests/test_visual_identity_approval.py \
  backend/tests/test_visual_identity_request.py \
  backend/tests/test_visual_identity_crop_sources.py \
  backend/tests/test_visual_identity_crop_resolution.py
```

Result: 17 passed. Pytest reports the existing Starlette `httpx` deprecation warning.

`ruff check` passed for all changed production and test Python files. `ruff format --check` passed
for the same files. Physical line counts are listed above; the crop-query suite has 707 lines, the
largest focused test file, within its 800-line budget. An import check found no service imports in
the extracted production modules.
