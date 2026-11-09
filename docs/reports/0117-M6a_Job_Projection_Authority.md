# Epic 0117 M6a: durable Job Manager authority

Date: 2026-11-09

## Result

Complete. The Job Manager now stores a durable `job-projection-authority/v1` value with a stable
manager ID, epoch, and increasing sequence. Every write of `job.json` uses one journaled update
that records the old and new job digests and authority values. Readers recover a prepared update
under the Job Manager lock before reading a job. Startup recovers a pending update before normal
job recovery.

The transition journals are stored at
`data/operations/jobs/recording-projections/job-transition.json`. A process crash can leave this
file present. Startup either finishes the exact prepared write or fails closed if the saved digest
does not match the old or new job record. The authority is stored at
`data/operations/jobs/recording-projections/authority.json`.

## Writer inventory

All production job record writes now converge on `JobPersistence._write_job`:

| Writer | Path into shared transaction |
| --- | --- |
| Initial acceptance and acceptance recovery | `JobPersistence._finish_intent` |
| Progress, waiting state, and worker failure | `JobScheduler` calls `JobManager._write_job` |
| Inline API handler failure | `jobs_api` calls `JobManager._write_job` |
| Explicit progress updates and lifecycle transitions | `JobManager` methods call `_write_job` |
| Result record before terminal transition | `JobManager.publish` calls `_write_job` |
| Restart reconciliation | `JobRecovery` receives `JobPersistence._write_job` |

There is one `atomic_replace_json` call for `job.json`, inside the authority transaction. Log,
queue, intent, and publication files keep their existing separate contracts. This milestone does
not add per-recording job projections or change selection-on-completion.

## Atomicity and restart behavior

The existing exclusive `owner.lock` prevents a second process from owning the Job Manager. Its
thread `RLock` now also protects job reads and writes. The writer persists a prepared transaction,
replaces the job record, advances authority, and removes the transaction in that order. Each JSON
replacement uses the existing fsync and atomic-rename helper; transaction removal syncs its
directory. Recovery accepts only the recorded old or new job digest and authority generation. It
finishes either side idempotently and rejects unrelated values.

The test suite injects a failure after each of the four durable boundaries, restarts the manager,
and verifies the job and authority sequence. It also verifies that a concurrent reader waits for a
writer and sees the completed state, that authority identity survives restart, and that a second
manager cannot claim the same root.

## Checks

- `mise exec -- uv run --project backend pytest -q backend/tests/test_job_projection_authority.py backend/tests/test_job_*.py backend/tests/test_jobs_api.py backend/tests/test_pipeline_api.py backend/tests/test_calculation_jobs.py backend/tests/test_recording_state_contract.py` — passed. One Starlette/httpx deprecation warning remains from the baseline test client.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/job_projection_authority.py backend/src/dokodetector_backend/job_persistence.py backend/src/dokodetector_backend/job_store.py backend/tests/test_job_projection_authority.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/job_projection_authority.py backend/src/dokodetector_backend/job_persistence.py backend/src/dokodetector_backend/job_store.py backend/tests/test_job_projection_authority.py` — passed.
- `rg -n "job\\.json|_write_job\\(" backend/src/dokodetector_backend/job* backend/src/dokodetector_backend/jobs_api.py backend/src/dokodetector_backend/job_scheduler.py` — all write calls converge on `JobPersistence._write_job`.
- `git diff --check` — passed.

No generated API or browser check applies. M6a changes no HTTP or web contract.

## Limits and handoff

M6a proves durable job authority transitions. It does not implement compact per-recording job
projections, metadata pages, analysis/package readers, or catalog conversion. Those remain required
in M6b–M6d. The current run remains capped at 14 milestones: 8 complete, 6 remain. Next is M6b.
M6a replan count is 0/5; run replan count is 4/10. M10–M16 are now outside this run.
