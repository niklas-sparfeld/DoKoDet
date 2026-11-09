# Epic 0117 M4c: real API workflow

Date: 2026-11-09

## Result

M4c adapts the disposable real-API workflow to M4a node revision publication authority and M4b
bounded transaction recovery. The workflow uses the real FastAPI app, recording-state services,
node revision store, review service, edit service, and disposable operations storage.

The deterministic producer reads the exact frozen event revision through
`read_authorized_revision`. Review creation and listing, accepted-use validation, edit reads,
selected-working edits, and the exact revision HTTP route also use publication authority. The test
replaces `read_published_revision`, which traverses revision parents, with a failure. It also fails
if old exact selection reads or writes, node/history discovery, or workspace/status discovery runs.

The test seeds 25 committed transaction journals before exercising the workflow. It records reads
made by coordinated recovery and confirms that exact revision reads open no committed journal.
It repeats the proof after app restart. M4b remains responsible for recovering one journal named
by the pending locator; committed journals remain available for direct transaction-ID replay.

The workflow creates and selects an event revision, freezes the snapshot ID, HEAD version, exact
revision address, and digest, then moves current selection before deterministic production. The
producer uses the frozen source. Identity and digest mismatches fail before output publication.
Two reviewers save independent decisions against the generated revision. Accepted downstream use
protects that content. The first selected edit creates a copy, updates generated selection, and
preserves the separate completed reference and both review records. The test also checks exact
persisted content, stale and cross-recording update rejection, older snapshot access, and reads
after restart.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_node_*.py backend/tests/test_recording_state_workflow.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py` — passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/pipeline_node_reviews.py backend/src/dokodetector_backend/pipeline_node_uses.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/recording_state_working_editor.py backend/src/dokodetector_backend/pipeline_node_edit_api.py backend/tests/test_recording_state_workflow.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/pipeline_node_reviews.py backend/src/dokodetector_backend/pipeline_node_uses.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/recording_state_working_editor.py backend/src/dokodetector_backend/pipeline_node_edit_api.py backend/tests/test_recording_state_workflow.py` — passed.
- `git diff --check` — passed.

The test run emits the existing Starlette/httpx deprecation warning. No API schema or browser
consumer changed, so API generation and browser checks do not apply.

## Limits

The producer is a deterministic test adapter that writes through the immutable node store. M4c
does not convert production processor launch, catalog, or workspace readers. M5 owns historical
metadata discovery. M12 must rehearse publication authority and pending-journal state for retained
data before M13 changes those readers.
