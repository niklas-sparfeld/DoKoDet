# Epic 0117 M5b2: M1-compliant history pages

Date: 2026-11-09

## Result

M5b2 exposes typed metadata pages at `/state/history`, `/revisions`, `/candidates`, and
`/lineage-edges`. Pages use M5b1's collection-specific immutable order roots and frozen authority
sequence. Continuation keys are canonical JSON arrays of the complete stable key. New publications
cannot enter a cursor's frozen membership, including when their keys sort before the cursor.

Opaque cursors use HMAC-SHA256 with a durable, private 32-byte key under the operations history
root. They bind recording, collection, the normalized empty-filter digest, history generation,
frozen sequence, complete last key, and page size. A valid cursor from a prior generation returns
HTTP 410. Invalid input and cursor binding failures return 422. Persisted authority, index, or
requested item corruption returns HTTP 500. The routes return only indexed metadata; they do not
open content payloads. Exact revision reads remain on their direct resource routes. M5c still owns
source publisher coverage and durable-to-index crash-gap reconciliation, so complete source
discovery is not claimed.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_history_api.py backend/tests/test_recording_history_store.py backend/tests/test_recording_history_order_index.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_workflow.py` — passed, 57 tests.
- `mise exec -- uv run --project backend ruff check ...` and `ruff format --check ...` — passed for changed backend files and tests.
- `cd web && npm run generate:api && npm run verify:api` — passed; OpenAPI includes all four typed routes.
- API tests cover stable collection order, frozen traversal across restart with a later earlier-sorting insert, signed cursor tampering and request binding, page-size bounds, generation expiry, lineage continuation, and persisted item corruption mapping.
- M5b1 tests cover bounded index-node and metadata reads at 256 items. The page implementation does not call payload readers.
- `git diff --check` and local Markdown link checks — passed.
