# Epic 0114 M6 — Job history and polling reads

## Result

M6 adds focused speed and correctness coverage for job history, detail/status, logs, and the
calibration-preview read used by the UI. The cases use disposable storage and valid production
`Job` and `Intent` models. Timed requests do not submit jobs, mutate job state, or add simulated
work. Fixture setup creates one successful calibration-preview job through the normal local job
service before measuring its read.

The job history fixture has six jobs for the target recording and unrelated jobs around them. The
runner compares 12-record and 300-record histories. Both return the same six target IDs, in the
expected newest-first order, across two three-item pages. The first page returns a cursor. The
second page has no cursor, contains no duplicate IDs, and reaches the exact expected end of the
filtered history.

The UI read coverage includes successful history, detail/status, log, and calibration-preview
responses; a missing job detail; missing logs; and a calibration-preview read against a non-preview
job. The latter returns the named `calibration_preview_unavailable` conflict.

## Preliminary samples

[`0114-M6_Job_Read_Samples.json`](0114-M6_Job_Read_Samples.json) retains 15 full-response samples
from controlled ASGI HTTP requests. Seven named reads ran against each history size, plus one
successful calibration-preview read. All response statuses, JSON bodies, and page checks passed.
The samples record monotonic request duration, status, response byte count, and response digest.
The slowest named request was the first history page at about 37.3 ms with 300 jobs; the matching
request took about 7.4 ms with 12 jobs. These are single preliminary samples, not a baseline,
regression gate, or stable latency estimate. App setup is outside the request clock. Job completion
time and writes are not measured.

## Verification

- `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_job_read_performance.py --output docs/reports/0114-M6_Job_Read_Samples.json` — passed; 15 samples and both pagination checks passed.
- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_read_performance.py -q` — passed; 4 tests.
- `mise exec -- uv run --project backend ruff check backend/scripts/run_interactive_ui_job_read_performance.py backend/scripts/run_interactive_ui_read_performance.py backend/tests/test_interactive_ui_read_performance.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/scripts/run_interactive_ui_job_read_performance.py backend/scripts/run_interactive_ui_read_performance.py backend/tests/test_interactive_ui_read_performance.py` — passed.
- `mise exec -- uv run --project backend python backend/scripts/check_interactive_ui_performance_inventory.py` — passed; 76 registered API operations classified, one documented UI URL gap, and 70 planned UI cases.

The test client emits an existing Starlette deprecation warning for its `httpx` integration. It does
not fail the checks. Sample latency varies with the local run and must not be used to rank or gate
future changes until M9 establishes the repeated baseline protocol.
