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

Before an advance, publication verifies the exact snapshot currently selected by HEAD. A missing or
corrupt current snapshot blocks the update; a new valid target cannot replace that damaged state.
The publication journal records the previous HEAD and expected version. Recovery validates that a
new publication advances the version by exactly one, that the previous HEAD matches the recorded
expected version, and that the complete journal summary equals the summary derived from the verified
immutable snapshot. A committed journal that does not match current HEAD is a typed corruption
failure. It also proves the recording was initialized: removing HEAD cannot make `initialize` create
a new authority.

## Recovery and authority

A durable `prepared` journal is the commit decision. Recovery validates its recording, expected and
new HEAD versions, summary, and referenced immutable snapshot, then repeats the HEAD and summary
replacements and marks the journal committed. Repeating recovery is safe. A crash after the committed
marker needs no work. A spawned process calls `os._exit(72)` immediately after each successful durable
journal, HEAD, or summary replacement. This proves restart recovery after process death at those
boundaries. It does not simulate process death during `atomic_replace_json` itself; the helper's
atomic replacement behavior is covered by the existing filesystem primitive and not newly tested
here.

Snapshots written before publication can be orphaned. They remain immutable and directly readable,
but do not establish current state. M3 does not delete them or infer HEAD from predecessor links,
selection files, or history. A missing HEAD returns `RecordingHeadNotFound`; corrupt HEAD or its
selected snapshot remains a typed corruption failure. A stale or corrupt summary can be rebuilt
only from the verified current HEAD and snapshot. Summary timestamps do not establish freshness.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py` — 38 passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/recording_state_store.py backend/tests/test_recording_state_publication.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/recording_state_store.py backend/tests/test_recording_state_publication.py` — passed.
- `git diff --check` — passed.

The publication tests start two processes with the same expected version. One advances HEAD and one
gets a stale conflict. The concurrent reader signals readiness only after a successful initial
read. The writer waits for reader observations of the old state and every successive published
version (1 through 8), so the test cannot pass without reads spanning the updates. Each observation
checks that HEAD, selected snapshot, and summary agree. Stale expected versions are rejected. Four
process deaths (`journal_prepared`, `head`, `summary`, and `journal_committed`) are reopened with a
new store instance; recovery leaves HEAD version 2 and the summary at the exact same snapshot/version.
Tests reject a valid-shape but incorrect prepared-journal summary. Tests also reject publication when
the current snapshot is missing or corrupt and reject initialization or publication after HEAD is
removed despite committed publication evidence. An orphan-snapshot test confirms that a stored
snapshot alone does not create current state.

No API route, generated schema, or web code changed, so API generation and browser checks do not
apply. This milestone proves the local file publication store, not API behavior, retained-data
conversion, or activation.
