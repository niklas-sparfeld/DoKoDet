# Epic 0117 M5b: bounded history API pages

Date: 2026-11-09

## Result

M5b adds `GET /api/recordings/{recording_id}/state/history/{collection}` for snapshots, node
revisions, candidates, and lineage edges. The route reads the M5a history authority and returns a
bounded page of metadata. It does not open referenced resource payloads. Each cursor pins the
recording, collection, page size, history generation, and the sequence boundary from the first
request. Later publications stay outside that traversal. A rebuild changes the generation and
expires an older cursor. Exact snapshot predecessor links and resource digests remain in the page
items. Direct historical revision access remains available.

The M5a store currently enumerates and validates the selected collection's metadata records to
build each page. Page response size is bounded; metadata enumeration cost still depends on the
indexed collection size. Source coverage is incomplete by design. Snapshot, revision, candidate,
and lineage publishers plus crash-gap reconciliation remain in M5c.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_history_store.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_workflow.py` — passed, 43 tests.
- Tests cover stable traversal over snapshots and revisions, a new revision published between pages, exact ancestry, cursor page-size mismatch, rebuild expiry, page bounds, corrupt metadata rejection, and metadata-only resource references.
- Ruff check and format check passed for changed Python files.
- `cd web && npm run generate:api && npm run verify:api` — passed.
- `git diff --check` passed.
- Full source discovery and durable-to-index gap recovery are not claimed; M5c owns them.
