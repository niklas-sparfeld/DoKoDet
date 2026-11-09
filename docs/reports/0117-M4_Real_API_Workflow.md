# Epic 0117 M4: real API workflow

**Review status:** M4 remains incomplete. `read_published_revision` walks parent links from node HEAD; normal frozen-input and selected-edit reads therefore traverse history. The final sanity review requires bounded durable publication authority and a no-parent-traversal growth check before completion.

Date: 2026-11-09

## Result

Added recording-state HTTP routes for first snapshot publication, current-state reads, explicit
snapshot selection with HEAD compare-and-swap, exact snapshot reads, and edits to selected event
working content. The app creates the snapshot store and selected-working editor under its isolated
operations root. The routes do not fall back to old selection pointers or expose general history
traversal. Exact revision reads still verify publication reachability from node HEAD.

The disposable-storage test uses the real app, HTTP routes, node revision store, review service,
edit service, and copy-on-edit protection. It creates and selects an event revision, then freezes
its snapshot ID, HEAD version, exact revision address, and digest. It changes current selection to
a different event revision before running the deterministic producer adapter. The adapter reopens
the frozen snapshot and exact revision, checks recording and content identity and digest, then
derives output by changing the input event end time. The output follows the frozen original even
after current selection changes. A mismatched selected reference and a mismatched stored digest
both fail before output publication.

Two reviewers save different decisions against the same immutable generated revision. After
accepted downstream use, the selected-working editor copies and edits that generated revision. It
publishes the copy as the new generated selection, keeps the decoy completed reference selected,
and leaves both independent review records attached to the original output. Review work does not
become the completed reference. The PUT state route rejects a body recording ID that differs from
the path ID.

Fail-fast guards replace the legacy exact-selection reader and writer, full node-history and
catalog scans, global revision search, and old workspace/status discovery methods with errors for
the entire workflow. The same guards stay active after app restart. User-facing exact revision reads
verify that the requested revision is reachable from the current node head by following its parent
links; they reject an orphan revision without materializing a full history list. The proof checks a
reader paused between revision creation and HEAD publication, and verifies that accepted-use
publication waits until the revision is reachable. A simulated crash leaves an orphan that neither
an exact published read, review creation, nor historical accepted-use request can read. Edit retry
also refuses to delete an orphan that has persisted review or accepted-use records. The proof checks
exact saved content, frozen inputs, stale and cross-recording update rejection, older snapshot
access, and state and revision reads after restart.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_workflow.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_edits.py backend/tests/test_pipeline_node_edit_api.py backend/tests/test_pipeline_node_reviews.py backend/tests/test_pipeline_node_uses.py` — 70 passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/app.py backend/src/dokodetector_backend/recording_state_api.py backend/src/dokodetector_backend/recording_state_working_editor.py backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/pipeline_node_reviews.py backend/src/dokodetector_backend/pipeline_node_uses.py backend/src/dokodetector_backend/pipeline_node_edit_api.py backend/tests/test_recording_state_workflow.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_edits.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/app.py backend/src/dokodetector_backend/recording_state_api.py backend/src/dokodetector_backend/recording_state_working_editor.py backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/pipeline_node_reviews.py backend/src/dokodetector_backend/pipeline_node_uses.py backend/src/dokodetector_backend/pipeline_node_edit_api.py backend/tests/test_recording_state_workflow.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_edits.py` — passed.
- `npm run generate:api` — passed; regenerated `web/src/api/openapi.ts`.
- `npm run verify:api` — passed; generated client matches the OpenAPI contract.
- `git diff --check` — passed.

The test emits one existing Starlette `httpx` deprecation warning. It does not affect the result.
No browser check applies: M4 adds backend routes and generated types, with no web consumer.

## Limits

The deterministic producer is a test adapter that writes through the production immutable node
store. M4 does not convert production processor launch, catalog, or workspace writers. Exact
published-revision checks follow only the requested revision's parent chain; they do not run the old
full-history enumeration API. M5 will add explicit historical metadata discovery. Broad conversion
remains gated on that work and the later migration and activation milestones.
