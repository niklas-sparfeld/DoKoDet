# Epic 0110 M10: Round analysis

## Outcome

Round analysis now runs as a managed leaf job. The service no longer owns an async queue, worker,
or package executor. The shared scheduler runs one analysis at a time and analyzes evidence
packages in request order.

The job records separate `analysis` and `reconstruction` steps. It reports package and round
progress. Its accepted request keeps the recording, evidence package or table-observation
revision, round facts, rules, correction revision IDs, and search limits. Pipeline observations,
round context, and the input manifest are copied before execution.

The analysis publishes immutable input and result artifacts inside Job Manager publication
arbitration. A retry keeps the same source selections and rules. It gets a new analysis ID and new
result artifacts. A failure stores a safe domain error and the job keeps its diagnostic detail.

Cancellation stops before the next evidence package, after analysis work returns, or before
publication. The active analyzer or reconstruction call cannot be interrupted. The scheduler keeps
the worker slot until that call returns. On restart, Job Manager records an active job as
interrupted, then analysis reconciliation marks its unfinished domain record as failed.

The existing round-analysis status and result routes continue to use analysis IDs. The Jobs API
shows the managed job, its steps, exact source artifacts, results, and retry link.

## Verification

- Round-analysis API and logging tests cover success, failure, managed lifecycle, progress,
  cancellation safe stops, retry inputs, and interruption reconciliation.
- Observation pipeline integration tests cover round analysis from an accepted table-observation
  revision.
- Job API, scheduler, and storage tests cover durable acceptance, publication, cancellation,
  interruption, and retry behavior.
- Focused backend test command passed: `uv run --project backend pytest backend/tests/test_round_analysis_api.py backend/tests/test_round_analysis_logging.py backend/tests/test_observation_pipeline_api.py backend/tests/test_jobs_api.py backend/tests/test_job_scheduler.py backend/tests/test_job_store.py -q`.
- Ruff check and format check passed for all changed Python files.
