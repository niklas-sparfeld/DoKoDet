# Epic 0114 M9: media routes and cache behavior

Date: 2026-11-07  
Scope: named real-backend media route cases and server-side derived media cache behavior. These are
single-run preliminary measurements, not a baseline.

## Coverage

The M9 coverage check reconciles the inventoried UI media routes:

| Case | Method and route | Result |
| --- | --- | --- |
| Evidence frame | `GET /v1/round-analyses/{analysis_id}/evidence-packages/{package_id}/frames/{part_name}` | 200; exact frame bytes and response digest retained |
| Evidence video snippet | `GET /v1/evidence-packages/{package_id}/video-snippet` | 200; stored snippet bytes and digest retained |
| Recording video | `GET /v1/repository-bundles/{recording_id}/video` | 200; source bytes and digest retained |
| Bounded video range | Same route with `Range: bytes=0-65535` | 206; full response body consumed and retained |
| Recording thumbnail | `GET /v1/repository-bundles/{recording_id}/thumbnail` | Cold and warm 200; body and ETag match |
| Derived event frame | `GET /api/recordings/{recording_id}/pipeline/derived-views/exact-event/{requested_time_us}` | Cold and warm 200; body and ETag match |
| Identity crop preview | `GET /api/recordings/{recording_id}/pipeline/derived-views/identity-crops/{revision_id}/{item_id}?preview=browser` | Cold and warm 200; exact response digest retained |

M3 already measures the repository bundle identity response. M4 measures the proposed crop-input
identity read. The coverage check fails if an inventoried media route is absent from these cases or
those prior named suites.

The UI URL `/api/recordings/{recording_id}/video` remains unregistered. Its 404 is checked as an
explicit boundary, not counted as a media response or timing result.

## Cache and persistence checks

The tests request derived event frames and identity crop previews cold and warm, then check exact
ETags and content hashes. A second completed identity run creates a different immutable identity
revision; its crop is read from the new revision path. A saved item review is then read through the
same immutable crop identity. The review does not change crop bytes, so the same body remains valid.
After app restart, the saved revision's crop is readable with the same response digest. These checks
cover revision-keyed identity and restart persistence; they do not claim a new identity revision must
change crop bytes.

Thumbnail route and cache behavior use the real API handler and cache store. The test injects a
small deterministic thumbnail renderer because the local repository video fixture is not decodable.
It verifies one cold generation and a warm cache hit. The renderer's generation time is not a
performance result.

## Samples and checks

The [raw sample JSON](0114-M9_Media_Samples.json) has 13 named complete-response samples with
status, monotonic elapsed nanoseconds, byte count, SHA-256, ETag, and content type. It uses the
FastAPI `TestClient` transport and disposable fixture storage. The local source recording fixture is
55 bytes; its range response is therefore below the 65,536-byte cap. M11 must exercise the frozen
hard video asset and full qualification range protocol before any range transfer budget is frozen.

- `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_media_performance.py --output docs/reports/0114-M9_Media_Samples.json` — PASS, 3 tests; 13 samples.
- `mise exec -- uv run --project backend ruff check backend/scripts/run_interactive_ui_media_performance.py backend/tests/test_interactive_ui_media_performance.py` — PASS.
- `mise exec -- uv run --project backend ruff format backend/scripts/run_interactive_ui_media_performance.py backend/tests/test_interactive_ui_media_performance.py` — PASS.
- `mise exec -- uv run --project backend python backend/scripts/check_interactive_ui_performance_inventory.py` — PASS, 76 registered API operations classified, one unregistered UI URL, 70 planned UI cases.

The sample timings are not a baseline. M10 adds real-process Playwright and bounded load. M11 runs
the complete corpus in three independent sessions and freezes budgets and regression gates.
