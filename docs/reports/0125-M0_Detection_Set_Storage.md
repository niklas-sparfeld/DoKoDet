# 0125 M0: Detection-set storage

## Result

M0 adds an immutable detection-set version store and save/open API under each recording folder.
The API accepts exact source-frame identities, frame-local objects, separately identified polygon
segments in source-image pixels, card-side facts, pile and ignore regions, empty examined frames,
and optional exact event references with content digests. It rejects invalid source identity,
missing event evidence, invalid geometry, duplicate IDs, and version overwrite. A staged directory
and atomic rename publish each version. Save and open do not change `Recording HEAD`.

The recording-both fixture API test saved and reopened this content after constructing a new app
against the same persisted root. It covered a direct frame, an event-linked frame, one visible card
with two disconnected segments, pile and ignore geometry, and an empty examined frame. A raised
publication error still verifies cleanup of ordinary failures. A separate child process exited
after the staged version was synced and before rename. A new store instance could not open that
partial version; the staging directory remained unpublished. Geometry tests reject a polygon with
non-zero signed area whose edges self-intersect. Existing shared validators check signed area only,
so this local check preserves their contract and closes the invalid geometry case for detections.

## Verification

- `mise exec -- uv run --project backend pytest backend/tests/test_detection_set_api.py backend/tests/test_event_set_store.py -q` — passed, 7 tests.
- `mise exec -- uv run --project backend ruff check ...` — passed for changed backend source and tests.
- `mise exec -- uv run --project backend ruff format --check ...` — passed for changed backend source and tests.
- `npm run generate:api` — passed; regenerated `web/src/api/openapi.ts`.
- `npm run verify:api` — passed.
- `npm run typecheck`, `npm run lint`, and `npm run format` — passed.
- `git diff --check` — passed.

## Limits and next proof

The detector, browser editor/review, version selection, downstream consumers, retained-data
conversion, and qualification remain unchanged. The first complete user workflow remains M1. M1
must freeze its detector and browser API/client owners before edits, then prove detector save,
browser segment edit, and exact reopen after restart with the same contract.
