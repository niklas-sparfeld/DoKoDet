# Epic 0117 M4: real API workflow

Date: 2026-11-09

## Result

Added recording-state HTTP routes for first snapshot publication, current-state reads, explicit
snapshot selection with HEAD compare-and-swap, and direct reads by exact snapshot ID. The app
creates the snapshot store under its isolated operations root. The route does not discover history
or fall back to old selection pointers.

The disposable-storage test uses the real app, HTTP routes, node revision store, review service,
edit service, and copy-on-edit protection. It creates an event revision, selects it as a completed
reference, then runs a deterministic producer stub from an exact frozen input. It selects the
generated revision while retaining the input reference. Two reviewers save different decisions
against that same immutable revision. After accepted downstream use, an edit creates a separate
copy. The next snapshot selects that edited working revision as completed reference and preserves
both the generated pointer and independent review records.

The proof uses the exact snapshot and revision reads. It does not call the old selection store or
history traversal. The legacy node-selection root remains absent. It checks exact persisted
content, frozen inputs, stale HEAD rejection, older snapshot access, and state and revision reads
after app restart.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_workflow.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py` — 40 passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/app.py backend/src/dokodetector_backend/recording_state_api.py backend/tests/test_recording_state_workflow.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/app.py backend/src/dokodetector_backend/recording_state_api.py backend/tests/test_recording_state_workflow.py` — passed.
- `npm run generate:api` — passed; regenerated `web/src/api/openapi.ts`.
- `npm run verify:api` — passed; generated client matches the OpenAPI contract.
- `git diff --check` — passed.

The test emits one existing Starlette `httpx` deprecation warning. It does not affect the result.
No browser check applies: M4 adds backend routes and generated types, with no web consumer.

## Limits

The deterministic producer is a test adapter that writes through the production immutable node
store. M4 does not convert production processor launch, catalog, workspace, or review writers. M5
will add explicit historical metadata discovery. Broad conversion remains gated on that work and
the later migration and activation milestones.
