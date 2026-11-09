# Epic 0117 M2: immutable snapshot store

Date: 2026-11-09

## Result

Added `RecordingStateSnapshotStore` under
[`recording_state_store.py`](../../backend/src/dokodetector_backend/recording_state_store.py).
It resolves the configured operations root and stores snapshots under
`recording-state/snapshots/{recording_id}/{snapshot_id}`. One atomically published immutable
directory contains canonical snapshot bytes and compact per-stage metadata. Snapshot metadata
stores the recording and snapshot identity, the SHA-256 of the canonical stored snapshot, and the
generated and completed-reference state for each slot.

Writes validate the M1 Pydantic snapshot contract before publication. Repeating an identical put
is idempotent. Reads address one recording and snapshot directly, validate canonical bytes, schema,
content-derived snapshot identity, requested path identity, stored digest, and compact metadata.
Missing snapshots and corrupt content return distinct typed errors. Existing content is never
overwritten. This store does not read or write HEAD, select state, enumerate nodes, or traverse
predecessors.

Review correction 1: revalidate a detached model dump on every `put`. Pydantic models permit
nested and identity mutation after construction, so validating the supplied instance only at its
original construction was insufficient. Regression tests mutate both a nested resource digest and
the snapshot ID after construction; both are rejected before any snapshot directory is published.
This keeps the existing idempotent duplicate and immutable-storage behavior.

## Verification

`backend/tests/test_recording_state_store.py` verifies isolated-root resolution, exact selected
resource-reference round-trip, compact stage metadata, duplicate identity, typed missing/corrupt
behavior, recording isolation, direct reads, and rejection of post-construction mutation. Its
history-growth case stores 11 linked snapshots and observes exactly two file reads for a lookup,
both within the requested snapshot directory.

Checks passed:

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_store.py backend/tests/test_recording_state_contract.py` — 25 passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/recording_state_store.py backend/tests/test_recording_state_store.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/recording_state_store.py backend/tests/test_recording_state_store.py` — passed.
- `git diff --check` — passed.

No API, generated schema, or browser contract changed. M2 does not prove HEAD publication, crash
recovery, concurrent HEAD updates, or API read behavior; M3 owns publication and those checks.
