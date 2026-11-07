# Epic 0114 M10: real-process browser workflows and controlled load

Date: 2026-11-07  
Scope: isolated local Uvicorn and Vite processes, Chromium workflows, and bounded local job load.
These are preliminary samples, not a baseline or a production performance qualification.

## Result

The dedicated Playwright suite passed all seven scenarios. It ran 10 fresh contexts per scenario:
60 uncontended workflow samples and 10 controlled-load samples. The six requested workflows cover
recordings to workspace, displayed revision switching, frame and crop navigation, durable review
save, Jobs drawer and history, and job submission to visible job status. Every exact identity and
control check passed. Browser HTTP errors, failed requests other than navigation cancellations,
and timeouts fail the run. No such errors occurred.

The [raw result JSON](0114-M10_Real_Process_Browser_Samples.json) retains the full 70 request
waterfalls, response status, ETag and cache-control headers, duplicate-request counts, browser cache
events, and video-range response bytes. The [browser sample artifact](0114-M10_Real_Process_Browser_Samples.artifacts/browser-samples.json)
and process logs are also retained. The result records the starting Git commit and hashes all four
M10 runtime source files to identify the exact code used for the run.

| Scenario | Samples | Action median / p90 (ms) | Requests per context | API requests per context | Duplicate samples | Browser cache event samples |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Recordings to workspace | 10 | 489 / 490 | 181 | 11 | 10 | 10 |
| Displayed revision switch | 10 | 492 / 495 | 108–109 | 22–23 | 10 | 0 |
| Frame and crop navigation | 10 | 511 / 561 | 104 | 18 | 10 | 0 |
| Review save | 10 | 740 / 758 | 208–210 | 36–38 | 10 | 10 |
| Jobs drawer and history | 10 | 571 / 577 | 274 | 19 | 10 | 10 |
| Job submission to visible status | 10 | 2,164 / 2,203 | 212–213 | 42–43 | 10 | 10 |
| Controlled load | 10 | 2,084 / 2,135 | 234–237 | 63–66 | 10 | 10 |

The separate controlled-load scenario ran a single-flight active-job poll every 100 ms while a
deterministic 1,500 ms worker job overlapped with an item review write, workspace and history reads,
and a video range request. Each context recorded 11–12 successful polls. All ten jobs and review
writes completed. No poll, read, write, media request, or job status check failed or timed out.

## Process startup and media evidence

Startup followed the M2 ten-fresh-process protocol against the same frozen generated storage
snapshot. Each Uvicorn process had to pass liveness and readiness, return the exact recording from
the catalog, and return the same recording identity from the workspace. All ten processes passed.
Time from process launch through those probes was 974–1,113 ms (median 989 ms, p90 1,087 ms). The
Vite process returned HTTP 200 after 234 ms. These times describe this compact generated fixture
only.

The browser loaded exact-event frame and frozen identity-crop data from the real backend. The
waterfall records the media route, response ETag, and `private, max-age=31536000, immutable`
cache-control separately from Chromium CDP browser-cache events. The frame/crop workflow observed
no browser disk or service-worker cache event; other scenarios recorded browser cache events in all
ten contexts. The suite keeps these browser events separate from server response cache headers.

Twenty actual range responses were retained across frame/crop and controlled-load scenarios. Each
used `Range: bytes=0-65535`, returned HTTP 206, and consumed the full response body. The generated
64×64 recording is 1,554 bytes, so each response was `bytes 0-1553/1554`. This verifies real range
traffic and the 65,536-byte bound; it does not measure the larger hard video asset.

## Fixture and limits

The isolated fixture contains 106 files and 173,838 bytes, with manifest digest
`d7c574781dbd262be6881e3decff28bb533fa6c16a212f34baec620de739ffb6`. It is built from the small
local repository-bundle fixture through production storage and pipeline services. The browser uses
the production FastAPI app and a real Uvicorn process, the real Vite server and same-origin API
proxy, deterministic local event processing, and a deterministic local frame resolver. It contains
four review items and two exact identity revisions.

This compact fixture proves the listed local browser workflows and request paths. It does not
qualify the frozen hard-data corpus, larger video ranges, production performance, or regression
budgets. M11 must run the full endpoint and startup corpus plus these browser workflows in three
independent sessions before it freezes a baseline or enables gates. The M10 timings are preliminary.

## Checks

- `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_browser_performance.py --output docs/reports/0114-M10_Real_Process_Browser_Samples.json` — PASS; 7 Playwright scenarios, 70 contexts, 10 startup processes.
- `mise exec -- npm run typecheck` — PASS.
- `mise exec -- npm run lint` — PASS.
- `mise exec -- npm run format` — PASS.
- `mise exec -- npx prettier --check playwright.interactive-performance.config.ts tests/e2e-performance/interactive-ui-real-process.spec.ts` — PASS.
- `mise exec -- uv run --project backend ruff check backend/scripts/interactive_ui_browser_app.py backend/scripts/run_interactive_ui_browser_performance.py` — PASS.
- `mise exec -- uv run --project backend ruff format --check backend/scripts/interactive_ui_browser_app.py backend/scripts/run_interactive_ui_browser_performance.py` — PASS.

