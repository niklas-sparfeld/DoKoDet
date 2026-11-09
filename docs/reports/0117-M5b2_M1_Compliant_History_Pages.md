# Epic 0117 M5b2: M1-compliant history pages

Date: 2026-11-09

## Result

M5b2 exposes typed metadata pages at `/state/history`, `/revisions`, `/candidates`, and
`/lineage-edges`. Pages use M5b1's collection-specific immutable order roots and frozen authority
sequence. Continuation keys are canonical JSON arrays of the complete stable key. New publications
cannot enter a cursor's frozen membership, including when their keys sort before the cursor.

Opaque cursors use HMAC-SHA256 with a durable, private 32-byte key under the operations history
root. The key and a digest state record are atomically published with mode `0600`, then synced to
disk. New history publishers establish the key before writing history. On legacy history with no
key-state record, the first access creates a key and records its digest. After that marker exists,
a missing key or a digest mismatch returns HTTP 500. Recovery requires restoring the exact key from
backup; the API never replaces an established key. A crash after key publication but before its
state record is safe: restart records the digest for that same key. Cursor continuation binds
recording, collection, the normalized empty-filter digest, history generation, frozen sequence,
complete last key, and page size. A valid cursor from a prior generation returns HTTP 410. Invalid
input and cursor binding failures return 422. Persisted authority, index, or requested item
corruption returns HTTP 500. Unknown recording IDs return 404 before key creation or history
initialization. The routes return only indexed metadata; they do not open content payloads. Exact
revision reads remain on their direct resource routes. M5c still owns source publisher coverage and
durable-to-index crash-gap reconciliation, so complete source discovery is not claimed.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_history_api.py backend/tests/test_recording_history_store.py backend/tests/test_recording_history_order_index.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_workflow.py` — passed, 65 tests.
- `mise exec -- uv run --project backend ruff check ...` and `ruff format --check ...` — passed for changed backend files and tests.
- `cd web && npm run generate:api && npm run verify:api` — passed; OpenAPI includes all four typed routes.
- API tests cover stable collection order, frozen traversal across restart with a later earlier-sorting insert, signed cursor tampering and request binding, page-size bounds, generation expiry, lineage continuation, and persisted item corruption mapping.
- Correction 1/2 tests cover private file modes, atomic key publication, actual process death between key and state publication, restart, established-key loss and restoration, corrupt key state, unknown recordings with no side effects, simultaneous earlier- and later-sorting revisions, exact lineage endpoints, and bounded API metadata reads over 64 revisions with payload access disabled.
- M5b1 tests cover bounded index-node and metadata reads at 256 items. The page implementation does not call payload readers.
- `git diff --check` and local Markdown link checks — passed.
