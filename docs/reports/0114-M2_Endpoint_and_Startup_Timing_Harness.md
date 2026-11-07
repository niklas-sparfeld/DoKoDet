# Epic 0114 M2: endpoint and startup timing harness

Date: 2026-11-07
Scope: reusable controlled HTTP and isolated process timing; no baseline gate.

## Harness

`backend/scripts/run_interactive_ui_performance.py` exports raw JSON and CSV samples. Each record
contains a stable case name, cold trial number, elapsed nanoseconds, HTTP status, response byte
count, response SHA-256, pass state, and error detail. Run metadata records the local machine,
Python version, fixture identity, warmup count, repeat count, timeout, cache policy, process command,
and process cleanup result.

The controlled HTTP mode calls the real FastAPI app through an in-process ASGI transport. It starts
and stops app lifespan services for every batch. It runs five warmups, then 30 measured requests
for each endpoint case in each of three independent batches. Each batch has fresh application
services and operations storage. The runner enforces a per-request `asyncio` timeout.

The isolated process mode starts ten fresh backend process groups per profile on loopback ports. It
uses separate temporary roots, disables Bonjour and hostname discovery, and waits for liveness,
readiness, the recordings response, and (for hard storage) a workspace response. It then reads the
full JSON jobs response. The hard profile also reads a 65,536-byte media range. The runner streams
each response to completion and records its first-byte and completion times, byte count, and digest.
A timeout or non-2xx probe fails the sample. The runner sends SIGTERM, waits up to 30 seconds, then
sends SIGKILL and confirms the process group exited. stdout and stderr go to a retained per-process
log.

The hard storage profile copies only the selected `cardeventnet-IMG_0650` intake bundle and links
the frozen pipeline, calibration, and related assets into the isolated root. The interrupted
recovery profile creates a valid queued job through `JobManager`, moves it to `running`, then
requires process startup recovery to return it as `interrupted`. The empty profile has no seeded
recordings or jobs. Media reads request bytes 0–65,535 and fail if the server returns more than
65,536 bytes.

The comparator is advisory. It reports fixture or machine mismatches, invalid response samples, and
candidate samples more than 20% slower than the baseline case median. M6 will decide whether to use
it as a regression gate. The M2 CLI does not fail a measurement run because of a comparator warning.

## Sample measurements

These are implementation checks on one local machine, not a qualified baseline. Machine metadata
and every sample are in the raw files.

The table reports medians and p90 values from the raw exports. Each controlled HTTP row has three
batches with 30 measured requests per batch. Each startup row has ten fresh processes. These are
checks on one local machine, not a qualified baseline.

| Profile and case | Samples | Median | p90 |
| --- | ---: | ---: | ---: |
| Controlled hard, `GET /api/jobs` | 30 per batch | 0.619–0.620 ms | 0.640–0.651 ms |
| Controlled hard, video range completion | 30 per batch | 463.68–464.14 ms | 465.01–465.68 ms |
| Empty startup to first useful response | 10 | 0.590 s | 0.703 s |
| Empty startup, `GET /api/jobs` first byte / completion | 10 | 0.946 / 0.957 ms | 0.981 / 0.995 ms |
| Hard startup to first useful workspace | 10 | 8.226 s | 8.610 s |
| Hard startup, recordings response | 10 | 3.048 s | 3.119 s |
| Hard startup, workspace response | 10 | 4.481 s | 4.782 s |
| Hard startup, `GET /api/jobs` first byte / completion | 10 | 1.323 / 1.335 ms | 1.388 / 1.400 ms |
| Hard startup, media range first byte / completion | 10 | 58.317 / 58.387 ms | 59.068 / 59.135 ms |
| Interrupted recovery, recovered job response | 10 | 0.956 ms | 1.011 ms |

All 90 controlled requests per case and all startup requests returned valid responses. The media
range returned exactly 65,536 bytes in all 10 loopback processes. The raw samples include one
record per controlled HTTP request, including warmups. JSON files include per-batch endpoint and
per-profile startup distributions; separate summary CSVs contain the same distributions. The JSON
exports link to retained per-process stdout/stderr logs.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_performance_runner.py`
  — PASS, 8 tests. Includes real JSON reads, full response timing, process cleanup after a
  timeout, interrupted-job recovery, slowdown detection, profile mismatch, and invalid response.
- `mise exec -- uv run --project backend ruff check backend/scripts/run_interactive_ui_performance.py backend/tests/test_interactive_ui_performance_runner.py`
  — PASS.
- `mise exec -- uv run --project backend ruff format backend/scripts/run_interactive_ui_performance.py backend/tests/test_interactive_ui_performance_runner.py`
  — PASS.
- Controlled HTTP CLI: five warmups plus 30 measured requests per case in three batches — PASS.
- Startup CLI: ten fresh process launches each for empty, hard populated, and interrupted recovery
  profiles — PASS. All exported samples are successful. No latency budget or regression gate was
  enabled.

Raw samples:

- [Controlled HTTP JSON](0114-M2_Controlled_HTTP_Samples.json),
  [raw CSV](0114-M2_Controlled_HTTP_Samples.csv),
  [distribution CSV](0114-M2_Controlled_HTTP_Samples.summary.csv)
- [Empty startup JSON](0114-M2_Empty_Startup_Samples.json),
  [raw CSV](0114-M2_Empty_Startup_Samples.csv),
  [distribution CSV](0114-M2_Empty_Startup_Samples.summary.csv)
- [Hard startup JSON](0114-M2_Hard_Startup_Samples.json),
  [raw CSV](0114-M2_Hard_Startup_Samples.csv),
  [distribution CSV](0114-M2_Hard_Startup_Samples.summary.csv)
- [Interrupted recovery JSON](0114-M2_Recovery_Startup_Samples.json),
  [raw CSV](0114-M2_Recovery_Startup_Samples.csv),
  [distribution CSV](0114-M2_Recovery_Startup_Samples.summary.csv)

The JSON exports link to each retained backend stdout/stderr log under the matching
`*.artifacts/` directory. Each startup profile has ten logs, one for each fresh process.
