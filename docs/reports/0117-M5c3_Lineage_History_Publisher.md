# Epic 0117 M5c3: pipeline lineage history publisher

Date: 2026-11-09

## Result

`PipelineLineage.finish` now publishes terminal run edges to the recording's `lineage_edges`
history collection. The committed lineage run remains the source of record. Each `used` or
`produced` relationship gets a deterministic key from its exact endpoints, edge kind, and role.
The history item stores only exact endpoint metadata; it does not read revision payloads.

Before the terminal run is committed, the writer atomically stores a per-recording outbox with
the exact edge items and a digest of the terminal record. It commits the run, publishes items
idempotently through `RecordingHistoryStore`, then removes and syncs the outbox. A history page
replays only the named recording's outbox. Recovery validates the outbox digest and the exact
committed run. If the run is absent, it checks each exact history address before clearing the
intent. An already-published edge without its source, malformed intent, source mismatch, or
symlink fails closed.

The recording history API does not change. Candidate collection semantics remain unresolved and
this work does not publish candidates. Legacy lineage runs without an outbox remain for M12
retained-state rehearsal.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_lineage.py backend/tests/test_pipeline_lineage_writer.py backend/tests/test_recording_history_api.py backend/tests/test_recording_history_store.py` — 65 passed after correction 1/2.
- A simulated stop after terminal source commit and before index publication leaves the outbox;
  explicit replay publishes the exact edge once and clears it. Repeating replay is safe.
- Two spawned processes publish different terminal runs for one recording; both exact edges remain
  addressable. The history store serializes item publication under its per-recording lock.
- `mise exec -- uv run --project backend ruff check ...` — passed for the three changed Python
  files.
- `mise exec -- uv run --project backend ruff format --check ...` — passed.
- `cd web && npm run verify:api` — passed. No OpenAPI schema changed.
- `git diff --check` — passed. Browser and type checks do not apply: there is no web consumer
  change, and the backend has no configured type checker.

## Correction 1/2

An identical terminal-run retry now recovers the pending outbox and republishes the exact items
from the committed run before it returns success. A retry detects a corrupt intent instead of
bypassing it. Recovery rejects non-regular run source files before reading them, so a FIFO cannot
block the reader. Tests cover a stop before source commit, partial publication of a two-edge run,
idempotent retry, corrupt intent and mismatched source, missing source after partial publication,
non-regular source rejection, and real history API recovery after source commit.

## Limits and next work

M5c3 publishes terminal run edges. It does not discover old lineage sources that lack intents.
M5 discovery remains incomplete until the persisted meaning and source of `candidates` are decided.
Do not alias candidates to revisions or embedded proposals. M12 owns retained-state conversion and
must rehearse the publisher authority and recovery state before M13 cutover.
