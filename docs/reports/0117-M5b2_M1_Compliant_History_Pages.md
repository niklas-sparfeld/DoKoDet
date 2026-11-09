# Epic 0117 M5b2: M1-compliant history pages

Date: 2026-11-09

## Result

M5b2 exposes typed metadata pages at `/state/history`, `/revisions`, `/candidates`, and
`/lineage-edges`. Pages use M5b1's collection-specific immutable order roots and frozen authority
sequence. Continuation keys are canonical JSON arrays of the complete stable key. New publications
cannot enter a cursor's frozen membership, including when their keys sort before the cursor.

Opaque cursors use HMAC-SHA256 with a durable, private 32-byte key under the operations history
root. The key and local digest record are atomically published with mode `0600` and synced to disk.
An independent authority record lives beside the history root. It holds the established key digest
and is also atomically published with mode `0600`. New history publishers establish both records
before writing history. The independent authority repairs a lost local digest record only when the
key still matches. A missing key, changed key, or missing independent authority with existing
history returns HTTP 500. The API never replaces an established key. Restore the exact key and
authority from backup to preserve cursors. For legacy history, call
`bootstrap_cursor_integrity_key_for_existing_history()` explicitly; it preserves an available key.
If no key remains, bootstrap requires `invalidate_existing_cursors=True`, which starts a new cursor
authority and invalidates all prior cursors. A crash during initial key setup is recoverable: before
history publication, restart completes the same key's local digest and independent authority.
Cursor continuation binds
recording, collection, the normalized empty-filter digest, history generation, frozen sequence,
complete last key, and page size. A valid cursor from a prior generation returns HTTP 410. Invalid
input and cursor binding failures return 422. Persisted authority, index, or requested item
corruption returns HTTP 500. Unknown recording IDs return 404 before key creation or history
initialization. The routes return only indexed metadata; they do not open content payloads. Exact
revision reads remain on their direct resource routes. M5c still owns source publisher coverage and
durable-to-index crash-gap reconciliation, so complete source discovery is not claimed.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_history_api.py backend/tests/test_recording_history_store.py backend/tests/test_recording_history_order_index.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_workflow.py` — passed, 71 tests.
- `mise exec -- uv run --project backend ruff check ...` and `ruff format --check ...` — passed for changed backend files and tests.
- `cd web && npm run generate:api && npm run verify:api` — passed; OpenAPI includes all four typed routes.
- API tests cover stable collection order, frozen traversal across restart with a later earlier-sorting insert, signed cursor tampering and request binding, page-size bounds, generation expiry, lineage continuation, and persisted item corruption mapping.
- Correction 1/2 tests cover private file modes, atomic key publication, actual process death between key and state publication, restart, established-key loss and restoration, corrupt key state, unknown recordings with no side effects, simultaneous earlier- and later-sorting revisions, exact lineage endpoints, and bounded API metadata reads over 64 revisions with payload access disabled.
- Correction 2/2 tests cover process death after key, local marker, and independent authority publication; local marker loss and key replacement; loss of all three authority files after cursor issuance; authority loss with existing history; and explicit legacy bootstrap with key preservation or cursor invalidation.
- M5b1 tests cover bounded index-node and metadata reads at 256 items. The page implementation does not call payload readers.
- `git diff --check` and local Markdown link checks — passed.
