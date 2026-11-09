# Epic 0117 M3: atomic HEAD publication

Date: 2026-11-09

## Result

Added compare-and-swap publication to
[`RecordingStateSnapshotStore`](../../backend/src/dokodetector_backend/recording_state_store.py).
`initialize` publishes the first verified snapshot at HEAD version 1. `publish` validates the
expected HEAD version, reads the already durable immutable snapshot, derives the compact summary,
then writes one per-recording prepared journal. The operation atomically replaces HEAD, atomically
replaces the matching summary, and marks the journal committed. HEAD, summary, and journal are
separate files; readers take the same per-recording process lock and recover before reading. The
lock combines a thread lock with the existing local-process `flock` pattern.

The node transaction journal is not suitable for this boundary. It publishes node revisions and
legacy node-selection pointers. Recording-state publication has different files and authority. M3
uses the existing atomic JSON replacement primitive, but keeps its own small journal and recovery
contract.

## Recovery and authority

A durable `prepared` journal is the commit decision. Recovery validates its recording, HEAD,
summary, and referenced immutable snapshot, then repeats the HEAD and summary replacements and marks
the journal committed. Repeating recovery is safe. A crash after the committed marker needs no work.
Crash injection covers every journal, HEAD, and summary replacement boundary.

Snapshots written before publication can be orphaned. They remain immutable and directly readable,
but do not establish current state. M3 does not delete them or infer HEAD from predecessor links,
selection files, or history. A missing HEAD returns `RecordingHeadNotFound`; corrupt HEAD or its
selected snapshot remains a typed corruption failure. A stale or corrupt summary can be rebuilt
only from the verified current HEAD and snapshot. Summary timestamps do not establish freshness.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py` — 33 passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/recording_state_store.py backend/tests/test_recording_state_publication.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/recording_state_store.py backend/tests/test_recording_state_publication.py` — passed.
- `git diff --check` — passed.

The publication tests start two processes with the same expected version. One advances HEAD and one
gets a stale conflict. A separate reader process repeatedly checks that HEAD, selected snapshot,
and summary always agree during publication. Stale expected versions are rejected. Four interrupted
write points (`journal_prepared`, `head`, `summary`, and `journal_committed`) are reopened with a new
store instance; recovery leaves HEAD version 2 and the summary at the exact same snapshot/version.
An orphan-snapshot test confirms that a stored snapshot alone does not create current state.

No API route, generated schema, or web code changed, so API generation and browser checks do not
apply. This milestone proves the local file publication store, not API behavior, retained-data
conversion, or activation.
