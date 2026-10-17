# Epic 0090 M2: Durable Execution

## Result

M2 verifies the coordinator's local restart and failure controls. The coordinator now validates
completed stages in order. It only makes a stage's outputs available to later stages after its
request and resolved inputs match the saved manifest. A changed request or input lineage receives a
new processor run ID. This prevents downstream work from using an old output.

An interrupted coordinator keeps the current stage request and run ID. A later invocation can
attach to that retained processor request. Completed earlier stages remain reusable. A coordinator
cancel request stops status polling and prevents later stages from starting. The current backend
worker may continue. A later invocation resumes the same request. The backend has no stage-level
cancel API in this milestone.

The CLI supports `--status --coordinator-id <id>` to read the local manifest without contacting the
backend. It supports `--cancel --coordinator-id <id>` for a running coordinator. `--rerun` creates a
new coordinator ID and fresh processor IDs for the same request file. No stage silently falls back
to a cloud provider.

## Verification

- Coordinator lifecycle tests: passed (9 tests), including interruption, cancellation and resume,
  changed upstream inputs, lineage checks, and fresh reruns.
- Existing backend restart recovery check is covered by
  `test_restart_marks_running_event_run_failed`.
- Ruff check and format: passed for the changed Python files.
- `git diff --check`: passed.
- The combined coordinator and pipeline API test run had one pre-existing inventory assertion
  failure: `test_pipeline_route_inventory_stays_in_focused_modules` expects 36 stage routes, while
  the application exposes 38. The coordinator does not add API routes. Other tests in that run
  passed.
- No model stages were run.

## Limits

Cancellation stops the local coordinator from waiting or scheduling downstream work. It does not
stop a processor that is already running in the backend. The saved run ID lets a later invocation
reattach to that work. `--rerun` intentionally starts a separate full run. Pilot execution and
quality measurement remain in M3.
