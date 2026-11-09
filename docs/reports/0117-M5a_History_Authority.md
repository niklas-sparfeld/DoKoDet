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
publishes an item here. M5a does not connect the store to snapshot, node revision, candidate, or
lineage publishers, and it does not expose history APIs. Replan 5 assigns the bounded API pages to
M5b and source adapters plus crash-gap reconciliation to M5c. M0/M1 do not identify the persisted
source or exact meaning of the `candidates` collection; M5c must resolve that before implementation.
No result payload or selected-state authority moves into this store.

The M5a correction verifies every stored item's metadata digest and requires its sequence to be no
greater than the active authority. Rebuild reads and validates every item and the authority in the
new generation before changing the active pointer. If generation data exists without an active
pointer, a normal read or write returns corruption instead of creating empty history. An explicit
rebuild remains available when the caller can prove the source metadata.

The resumed M5a work makes initial generation staging retryable after process death. Recovery uses
the pending generation journal to identify an interrupted build and removes abandoned `.staging-*`
directories. Empty initialization then starts again. A nonempty initial rebuild reports that the
caller must retry with source metadata, because the staging journal does not contain the source
items. A rebuild over an existing active generation keeps that generation available when the new
generation was not committed. Generation data without a matching pending journal still triggers
the lost-pointer corruption check.

The retry path keeps the incomplete journal while it validates the supplied source metadata. It
replaces that journal atomically only after validation succeeds. Invalid retry input therefore
cannot turn an interrupted nonempty rebuild into empty history. A process stop after the journal
replacement still leaves a journal that requires another source-metadata retry.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_history_store.py backend/tests/test_recording_state_contract.py` — passed, 38 tests.
- Store tests cover sequence assignment, duplicate retries, conflicting item-key reuse, all four
  publication crash boundaries, restart recovery, deterministic rebuild, generation-based cursor
  expiration, a rebuild restart boundary, pre-switch generation validation, metadata-digest and
  authority-sequence corruption, missing-active-pointer rejection, two-process publication, and
  corrupt-journal rejection. The previous run added a durable generation journal and a child-process
  stop after the initial generation directory commit but before `active.json`; restart validates the
  committed directory and publishes its active pointer. The resumed run adds child-process stops
  during empty, nonempty, and replacement generation staging. Empty initialization retries
  automatically; nonempty rebuild retries with supplied source metadata; replacement rebuild leaves
  its previous active generation readable. Invalid retry input keeps the pending journal, and a
  child-process stops immediately before and after retry-journal replacement both require retry. A
  missing pointer without this journal still reports corruption.
- Contract tests cover required history cursor generation and prohibit that field on catalog/job
  cursors. They also check that resource items match their page collection.
- Ruff check and format check passed for the changed backend files and tests.
- `git diff --check` passed.

No API generation or browser check applies. The store is not yet wired to production history
readers or source publishers, so this result proves the storage boundary and its recovery behavior,
not runtime discovery completeness. The source/index crash gap remains open for M5c.
