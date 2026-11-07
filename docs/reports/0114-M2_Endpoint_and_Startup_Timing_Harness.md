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
and stops app lifespan services for every invocation, uses one warmup by default, then records
repeated requests with an `asyncio` timeout. The isolated process mode starts a fresh backend process
group on a loopback OS-selected port. It uses separate temporary roots for every trial, disables
Bonjour, and waits for liveness, readiness, the recordings response, and (for hard storage) a
workspace response. It records each phase. A timeout or non-2xx probe fails the sample. The runner
sends SIGTERM, waits up to 30 seconds, then sends SIGKILL and confirms the process group exited.
stdout and stderr go to a retained per-trial log.

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

| Profile and case | Trials | Observed time |
| --- | ---: | ---: |
| Hard controlled HTTP, `GET /api/jobs` | 3 | 0.67, 0.78, 0.73 ms |
| Hard controlled HTTP, bounded video range | 3 | 505.71, 507.51, 509.18 ms; 65,536 bytes each |
| Empty startup, useful recordings response | 3 | 1.02, 1.11, 1.08 ms |
| Hard startup, recordings response | 1 | 3.03 s |
| Hard startup, workspace response | 1 | 4.76 s |
| Interrupted-job startup recovery | 3 | 0.93, 1.01, 0.94 ms |

The hard startup run reached the first useful workspace response 8.39 seconds after process launch.
The raw file separates liveness and readiness from those first-use requests. The hard startup result
has one trial; it is evidence that the scenario runs, not a stable estimate. The raw exports include
startup logs by path for diagnosis.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_performance_runner.py`
  — PASS, 7 tests. Includes real JSON reads, startup to useful response, process cleanup after a
  timeout, interrupted-job recovery, slowdown detection, profile mismatch, and invalid response.
- `mise exec -- uv run --project backend ruff check backend/scripts/run_interactive_ui_performance.py backend/tests/test_interactive_ui_performance_runner.py`
  — PASS.
- `mise exec -- uv run --project backend ruff format backend/scripts/run_interactive_ui_performance.py backend/tests/test_interactive_ui_performance_runner.py`
  — PASS.
- Hard controlled HTTP, empty startup, hard startup, and interrupted recovery CLI runs — PASS; all
  exported samples in these runs are successful. No latency budget or regression gate was enabled.

Raw samples:

- [Controlled HTTP JSON and CSV](0114-M2_Controlled_HTTP_Samples.json)
- [Empty startup JSON and CSV](0114-M2_Empty_Startup_Samples.json)
- [Hard startup JSON and CSV](0114-M2_Hard_Startup_Samples.json)
- [Interrupted recovery JSON and CSV](0114-M2_Recovery_Startup_Samples.json)

The JSON exports link to each retained backend stdout/stderr log under the matching
`*.artifacts/` directory. The hard startup trial has one log. Empty and interrupted recovery each
have three.
