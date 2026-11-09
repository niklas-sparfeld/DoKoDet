# Epic 0117 M4: real API workflow

Date: 2026-11-09

## Result

Added recording-state HTTP routes for first snapshot publication, current-state reads, explicit
snapshot selection with HEAD compare-and-swap, and direct reads by exact snapshot ID. The app
creates the snapshot store under its isolated operations root. The route does not discover history
or fall back to old selection pointers.

The disposable-storage test uses the real app, HTTP routes, node revision store, review service,
edit service, and copy-on-edit protection. It creates and selects an event revision, then freezes
its snapshot ID, HEAD version, exact revision address, and digest. It changes current selection to
a different event revision before running the deterministic producer adapter. The adapter reopens
the frozen snapshot and exact revision, checks recording and content identity and digest, then
derives output by changing the input event end time. The output follows the frozen original even
after current selection changes. A mismatched selected reference and a mismatched stored digest
both fail before output publication.

Two reviewers save different decisions against the same immutable generated revision. After
accepted downstream use, an edit creates a separate copy. The next snapshot selects that edited
working revision as completed reference and preserves both the generated pointer and independent
review records. The PUT route rejects a body recording ID that differs from the path ID.

Fail-fast guards replace the legacy exact-selection reader and writer, full node-history and
catalog scans, global revision search, and old workspace/status discovery methods with errors for
the entire workflow. The same guards stay active after app restart. Exact revision reads and the
existing editor/review services use direct revision addresses. Edit recovery checks only the exact
revision and its parent chain; it does not enumerate the node catalog or materialize full history.
The proof checks exact persisted content, frozen inputs, stale and cross-recording update rejection,
older snapshot access, and state and revision reads after restart.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_workflow.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_edits.py backend/tests/test_pipeline_node_edit_api.py backend/tests/test_pipeline_node_reviews.py backend/tests/test_pipeline_node_uses.py` — 68 passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/app.py backend/src/dokodetector_backend/recording_state_api.py backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/pipeline_node_reviews.py backend/src/dokodetector_backend/pipeline_node_uses.py backend/src/dokodetector_backend/pipeline_node_edit_api.py backend/tests/test_recording_state_workflow.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/app.py backend/src/dokodetector_backend/recording_state_api.py backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/pipeline_node_reviews.py backend/src/dokodetector_backend/pipeline_node_uses.py backend/src/dokodetector_backend/pipeline_node_edit_api.py backend/tests/test_recording_state_workflow.py` — passed.
- `npm run generate:api` — passed; regenerated `web/src/api/openapi.ts`.
- `npm run verify:api` — passed; generated client matches the OpenAPI contract.
- `git diff --check` — passed.

The test emits one existing Starlette `httpx` deprecation warning. It does not affect the result.
No browser check applies: M4 adds backend routes and generated types, with no web consumer.

## Limits

The deterministic producer is a test adapter that writes through the production immutable node
store. M4 does not convert production processor launch, catalog, or workspace writers. M5 will add
explicit historical metadata discovery. Broad conversion remains gated on that work and the later
migration and activation milestones.
