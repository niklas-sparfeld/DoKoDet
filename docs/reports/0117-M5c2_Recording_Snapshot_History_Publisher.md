# Epic 0117 M5c2: recording snapshot history publisher

Date: 2026-11-09

## Result

M5c2 connects `RecordingStateSnapshotStore.put` to the `snapshots` collection in the recording
history index. The source of record is the immutable snapshot directory committed by the snapshot
store. The history item uses the exact snapshot ID as its stable item key and includes the content
digest and predecessor snapshot ID.

The store holds its per-recording process lock while it writes and replays a single pending
outbox entry. The entry is durable before a new snapshot directory is committed. It records the
exact history item and compact stage metadata, with a digest over the complete outbox record. After
the snapshot directory commits, replay checks the committed `metadata.json` against that exact
intent. It does not read or parse `snapshot.json`. The history store assigns the publication
sequence and publishes idempotently. The outbox is removed only after history publication and the
parent directory is synced.

Replay can name only one recording's outbox. If that intent has no committed source directory,
replay checks the exact snapshot history address before it clears the intent. If history already
contains that item, a missing source is corruption and the intent remains. If no published item
exists, the missing source proves that staging did not commit, and replay clears the intent. If the
source directory or metadata is corrupt, does not match the exact intent, or uses a symlink, replay
fails closed and keeps the intent. Replay also uses `lstat` to require `snapshot.json` to be a
regular file. It does not read the payload. A history page first validates that
the recording exists, then replays its snapshot intent. A page request does not scan snapshots or
read their payloads. A later exact snapshot read still validates the payload bytes and digest.

An exact `put` of an existing snapshot also queues publication. This supports a named writer retry
without a history scan. Old snapshots that have no pending intent are not discovered by listing
storage; retained-state conversion remains part of M12.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py backend/tests/test_recording_history_store.py backend/tests/test_recording_history_api.py backend/tests/test_recording_state_workflow.py` — passed.
- Crash/restart tests stop after outbox commit before source commit, after source commit, and after history publication. They verify zero entries for the uncommitted source, one exact entry after source commit, and idempotent retry after history commit.
- Two processes publish separate snapshots for one recording. Both exact items are present at history sequence two.
- A real history API request recovers a simulated durable snapshot-to-index gap. The test rejects every snapshot payload read during that recovery. Separate child-process tests prove restart recovery at each boundary.
- Corrupt outbox/source identity remains pending and does not advance history authority.
- Correction 1/2 checks the exact bounded history item before it clears a missing source. If a
  committed history item exists, replay fails closed and retains the intent. Tests also reject a
  missing, symlinked, or non-regular payload path without reading payload bytes.
- Ruff check, Ruff format check, `git diff --check`, and `npm run verify:api` — passed.
- The OpenAPI schema did not change. Browser checks do not apply because no web consumer changed. The backend has no configured type-check command.

## Limits and next work

This publisher covers immutable recording snapshots written through `RecordingStateSnapshotStore`.
It does not discover snapshots from retained storage. M12 must rehearse existing authority and
history state. M5c3 still must connect pipeline lineage runs and edges. Candidate collection
meaning remains unresolved; M5 discovery remains incomplete.
