# Epic 0115 M12: format conversion

Date: 2026-11-08
Implementation base: `f63b5bdb091a789dbce4f79a40223c7d0044b276`
Status: Complete; isolated conversion rehearsal passed

## Change

The selected `visible-region-crop/v1` PPM cache now uses the M11 `derived-view-cache/v2`
representation. It stores `content.bin.gz` with `gzip/level-1/v1`. The manifest keeps the cache
key, view kind, full identity, uncompressed content digest, and uncompressed byte length. It adds
the codec, stored-byte digest, and stored-byte length. Reads check the stored fields, decompress,
then check the original content digest and length. The reader treats the old v1 PPM entry as a
cache miss. Other v1 cache entries, including JPEG crops and previews, keep their existing format.

The shared cache implementation is used by `resolve_visible_region_crop` and the backend services
that call it, including visible-card processing and visual-identity crop queries. New selected PPM
entries use v2. The bounded [conversion tool](../../operations/scripts/convert_0115_crop_cache.py)
converts only the selected PPM crop entries to a separate destination. It rejects a destination
inside the source tree and verifies every converted entry before it reports success.

## Conversion and recovery evidence

The [rehearsal result](0115-M12_Format_Conversion.artifacts/conversion-rehearsal.json) binds the
conversion to the same 8,571-entry M11 snapshot. Its identity digest is
`6721e55f6edc3c3d1f9f0602e0c77ffc1fd553e6acee6d15a39397cd2ae70381`. The source contains
1,997,795,952 logical bytes. All 8,571 converted entries passed exact uncompressed byte, digest,
length, and identity checks. The 128-key sample digest matches M11.

The converted family uses 798,392,320 allocated bytes across exactly 17,142 files, a 61.7% drop
from the M11 baseline of 2,083,942,400 allocated bytes. Average encode and write time was 1.99 ms
per entry. Cold and warm random-read p95 were 1.58 ms and 1.60 ms. Both are under the M11 limits.
These measurements use the same local filesystem and corpus as the M11 experiment.

Interruption and recovery ran on a two-entry disposable source. An injected stop after the first
entry left the source unchanged. The partial destination did not satisfy the missing entry. A fresh
destination then converted and verified both entries. A test that altered stored gzip bytes was
rejected by the stored-byte checks. The application treated the corrupt entry as a miss and rebuilt
the crop in the cache regression test. The original selected-family snapshot digest remained
unchanged after the full rehearsal. See the [recovery summary](0115-M12_Format_Conversion.artifacts/api-and-recovery.json).

No operator cache entries were changed or removed. The converted output was disposable and kept
outside the operator cache. The captured source digest is the recovery reference for a later
activation; M12 did not activate the converted family in the operator cache.

## API and performance checks

The real backend crop-query test writes a v2 PPM entry, reads its crop through the current API,
serves the JPEG preview, and verifies that the cache manifest has the v2 codec fields. The isolated
pipeline API test edits a selected revision, saves a review, restarts the app, and reads back the
same content, review decision, and exact selections. The M12 reader rejects the selected v1 PPM
path in a focused cache test. Other cache kinds remain readable.

The current hard pipeline runner completed 70 samples across 35 cases with no failures. All 35
response status, length, and digest triples match M11. The four frozen M0 application-I/O cases
passed with zero live-root reads. The [case summaries](0115-M12_Format_Conversion.artifacts/) retain
the measured evidence.

The 57-asset 0114 hard fixture and its manifest stayed unchanged. Inventory passed with 76
registered API operations and 70 planned UI cases. The frozen 0114 qualifier passed all 179 case
budgets and 70 UI route budgets on a temporary copy of the retained corpus. The checked-in raw
corpus has stale absolute trial-log paths, so the direct qualifier invocation still fails before
validation; the temporary copy changed only those paths and left the frozen baseline untouched.

## Checks

- `mise exec -- uv run --project operations pytest operations/tests/test_derived_view.py operations/tests/test_0115_crop_cache_conversion.py -q` — PASS (18 tests).
- `mise exec -- uv run --project backend pytest backend/tests/test_0115_pipeline_cutover.py backend/tests/test_visual_identity_crop_queries.py -q` — PASS (3 tests).
- `operations/scripts/convert_0115_crop_cache.py` on the frozen operator snapshot to an isolated destination — PASS (8,571 exact entries).
- `backend/scripts/run_interactive_ui_pipeline_read_performance.py` — PASS (35 cases, 70 samples; M11 responses match).
- `backend/scripts/profile_0115_application_io.py` — PASS (four M0 cases; zero live reads).
- `materialize_interactive_ui_performance_fixtures.py --require-hard` — PASS (57 assets); `check_interactive_ui_performance_inventory.py` — PASS (76 API operations, 70 UI cases).
- `qualify_interactive_ui_performance.py` on a temporary path-rebased copy — PASS (179 cases, 70 routes). Direct checked-in invocation — FAIL on stale absolute trial-log paths, as recorded above.
- Ruff check, Ruff format check, and `git diff --check` — PASS.

The M11 cost in write time and the one-step decode for direct image inspection remain accepted.
The operation cache still contains the original v1 snapshot. A future activation must first verify
the frozen snapshot and keep its recovery reference.
