# Epic 0114 M5: pipeline run and result reads

Date: 2026-11-07

## Coverage

The pipeline read runner now has named speed and correctness cases for all 17 M5 inventory
operations. Its executable coverage check compares the cases with the M5 operation set in the M0
inventory. The cases cover stage run lists, run selections, proposed-crop inputs, automated run
detail, all five stage result routes, and the on-demand comparison route.

The runner uses the real application, HTTP handlers, production stores, validation, and response
serialization in disposable storage. It seeds one valid event processor run and output revision,
an exact selected pointer, a completed reference revision, a second event run for comparison, and
one automated pipeline run document. It checks exact run, result revision, selected node and
revision, comparison side, and reference identities. Other stage lists and selections cover valid
empty states. Missing result cases cover each stage. Missing run and comparison input cases check
their exact error codes. The runner does not write review records or read derived media.

The hard fixture contains no retained stage run or result records. The successful result case uses
a deterministic generated event result. The other four stage result routes have executable speed
and correctness cases for their missing-run responses. No large hard result payload was available.

## Preliminary samples

The retained export contains 20 process-cold requests: 20 passed their correctness checks. Each
case has one request, no warmups, and one batch. These samples are preliminary and are not a
baseline. The OS filesystem cache was not flushed.

| Case | Response time | Response bytes |
| --- | ---: | ---: |
| Exact event run list | 24 ms | 1,164 |
| Exact event result | 18 ms | 2,044 |
| Exact automated run detail | 10 ms | 1,500 |
| Valid empty stage lists | 16–19 ms | 51 each |
| Proposed-crop inputs | 554 ms | 53 |
| Exact event comparison | 20.44 s | 3,980 |
| Missing runs, results, and comparison inputs | 11–18 ms | 111–121 |

The comparison route is the slowest named read. These single samples do not establish a stable
tail estimate or a budget. No baseline gate is active.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_pipeline_read_performance.py` — PASS, 7 tests.
- Ruff check and format check for the runner and focused tests — PASS.
- `mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard` — PASS, 57 hard assets validated.
- `mise exec -- uv run --project backend python backend/scripts/check_interactive_ui_performance_inventory.py` — PASS, 76 registered operations classified.
- M5 preliminary runner — PASS, 20/20 samples correct.

Raw samples: [pipeline run read samples](0114-M5_Pipeline_Run_Read_Samples.json).
