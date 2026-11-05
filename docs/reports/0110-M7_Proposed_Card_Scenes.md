# 0110 M7: Proposed Card Scenes

## Result

Proposed card scene processing now runs as a leaf job in the shared Job Manager. Acceptance
freezes the exact generated visible-card revision and processor request. The manager creates the
processor run before dispatch. The handler reports progress, checks cancellation at safe processor
boundaries, validates the output revision, and publishes it through manager arbitration.

The processor keeps its existing calibration and scene behavior. Valid empty and pile-only frames
remain successful results. Partial coverage remains a partial processor run, while the job records
that execution succeeded. Failed diagnostics stay on the processor run. Cancelled work cannot
publish a completed proposal revision.

The proposal editor submits and retries jobs through `/api/jobs`. It reads active lifecycle status
from the job API and uses the proposed-scene domain API for history and result data. The older
feature launch and retry routes remain manager-backed for existing callers until the API cleanup in
M15. The proposal service no longer owns an executor or restart recovery loop.

## Verification

- Proposed-scene, coordinator, and automated-worker backend tests passed: 22 tests.
- Ruff lint and format checks passed for changed backend files.
- Proposal editor command and API client tests passed: 20 tests.
- Web typecheck is blocked by existing uncommitted changes in `RecordingWorkspaceShell.tsx` at
  lines 361 and 399 (`t_us` does not match `PipelineUrlState`, which uses `tUs`).
- `test_pipeline_api.py` has one unrelated route-inventory failure. The current pipeline router has
  eight entries, while the test expects seven. The other 18 tests passed.
