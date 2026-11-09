# Epic 0117 M5a: shared history authority

Date: 2026-11-09

## Result

M5a adds a durable per-recording history authority and an immutable metadata-item store in
`backend/src/dokodetector_backend/recording_history_store.py`. A writer persists the complete
metadata item in a journal with its expected authority sequence. Under the per-recording process
lock, recovery publishes the item file, advances the authority, and clears the journal. Every
history read first recovers a pending journal. A retry with the same item key and exact metadata is
idempotent. Reuse of that key for different metadata is a conflict.

The store separates `snapshots`, `revisions`, `candidates`, and `lineage_edges`. Resource items
name their collection in the typed contract. Each item file stores its exact reference or edge
metadata and assigned sequence. The store does not read resource payloads. The generation pointer
changes only after a staged rebuild is complete. A rebuild assigns a deterministic sequence from
the proven source metadata and publishes one new active generation. The cursor contract now pins
that generation. A cursor from an earlier generation fails with an expired-cursor error.

The active generation is derived history metadata. Source payloads must be durable before a writer
publishes an item here. This milestone does not connect the store to snapshot, node revision, or
lineage publishers, and it does not expose history APIs. Those adapters and API traversal belong to
M5b and later conversion milestones. No result payload or selected-state authority moves into this
store.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_history_store.py backend/tests/test_recording_state_contract.py` — passed, 27 tests.
- Store tests cover sequence assignment, duplicate retries, conflicting item-key reuse, all four
  publication crash boundaries, restart recovery, deterministic rebuild, generation-based cursor
  expiration, a rebuild restart boundary, two-process publication, and corrupt-journal rejection.
- Contract tests cover required history cursor generation and prohibit that field on catalog/job
  cursors. They also check that resource items match their page collection.
- Ruff check and format check passed for the changed backend files and tests.
- `git diff --check` passed.

No API generation or browser check applies. The store is not yet wired to production history
readers or source publishers, so this result proves the storage boundary and its recovery behavior,
not runtime discovery completeness.
