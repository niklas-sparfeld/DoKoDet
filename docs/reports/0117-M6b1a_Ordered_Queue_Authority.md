# Epic 0117 M6b1a: ordered queue authority

Date: 2026-11-09

## Result

Incomplete after correction 2/2 review. The active-job SQLite store owns ordered queue groups, queued
child membership, parent-child sequence and state, and the queue revision. A
`job-record-transition/v3` journal binds the queue delta to the existing M6a job update. One SQLite
transaction publishes the active-job index and queue state before job authority advances. Recovery
validates and replays the combined
state idempotently. It rejects mismatched job, queue, child, or authority values.

Ordinary `JobManager.transition()` no longer reads all intents, loads all jobs, or rebuilds the queue.
It updates one job's group or child membership. Starting a job uses a point queue lookup and an
indexed query for the first queued child. Dependency checks use an ordered parent-child index and
read only the target intent plus the first prior child that is not succeeded. Parent cancellation
reads children for that parent only. Queue readers serialize with job writers. Explicit queue moves
use a SQLite transaction and keep the current group and child order. The parent waiting-to-queued
transition now journals its tail position with the state change. Startup recovery uses that same
transition when a child terminal write committed before the parent transition began. Recovery now
matches the normal child transition: a cancelled child cancels its waiting parent; succeeded, failed,
or interrupted children queue it. Recovery checks terminal children even when another child remains
queued. If several are terminal, it uses the latest durable `updated_at`, with acceptance sequence as
the tie-breaker.

Commits `323a021c` and `1a6fc590` are integrated. Review did not accept M6b1a. Two defects remain:

- A crash after the parent enters `waiting` but before the first child is accepted leaves the parent
  waiting permanently.
- A restart during a later wait can requeue the parent based on an old terminal child while the
  current child remains queued.

Recovery needs durable evidence that identifies the current wait and its child transition. M6b1a stays
incomplete until that contract and its recovery checks are implemented.

Startup recovery calls `JobRecovery.rebuild_queue()` and rebuilds the parent-child state from durable
jobs and intents. Until repair completes, queue reads fail closed. The old `queue.json` is imported
once to retain its ordering, then removed and the directory is synced after successful repair.
Ordinary acceptance still scans intents for idempotency, sequence allocation, and parent-step
uniqueness. M6b1b owns those reads and their transaction. Scheduler candidate discovery and startup
repair still enumerate the full queue or intent set; M6b2 owns bounded active-job pages.

## Checks

- Focused job and pipeline suite: passed. This covers journal crash boundaries and replay, queue and
  parent/child order, legacy repair, queue corruption, scheduler dispatch, cancellation, restart,
  and API job flows. Queue growth tests create 20 and 200 children, make `_intents()` and `list_jobs()`
  fail if called during transition, record exactly two target-intent reads, and verify indexed child
  and dependency queries.
- Correction 1/2 crash checks passed for both a crash after the child terminal commit and a crash
  after the parent queue delta commit but before authority advance. Restart leaves the parent queued
  after the unrelated group, with matching durable SQLite positions.
- Correction 2/2 restart checks passed after a cancelled child commit with its parent still waiting.
  The same test covers succeeded, failed, and interrupted children with another child still queued;
  only cancellation cancels the parent, and all other terminal states queue it.
- Growth checks passed at 20 and 200 siblings plus 20 and 200 unrelated jobs and intents across 1
  and 10 unrelated recordings. Each child transition read only its target intent twice, and the dependency
  query plan used `parent_children_pending_dependency`.
- The concurrent reader/writer check passed: job and queue readers wait for the journaled writer to
  advance authority, then read the committed state.
- Ruff check and format check on changed Python files: passed.
- Web OpenAPI verification, typecheck, and Vitest: passed (46 files, 243 tests).
- Playwright jobs and job-start-actions: passed (6 tests).
- `git diff --check`: passed.
- All backend job and jobs API tests: passed (72 tests).
- The local API test client reports the existing Starlette/httpx deprecation warning.

No HTTP or web contract changed. M6b1a does not claim bounded acceptance or bounded scheduler
candidate enumeration. See M6b1b and M6b2 for those remaining boundaries.

## Resumed run completion

Date: 2026-11-09

The current run resolved both wait-recovery defects. `AutomatedPipelineJobHandler` now writes the
current phase and pending step before it transitions the parent to `waiting`. Startup recovery
resolves only the intent whose `parent_step_id` matches that phase. If the wait has no child intent,
recovery requeues the parent so it can accept the stage. If the matching intent is still uncommitted,
recovery leaves the parent waiting while it completes acceptance. A terminal child from an earlier
phase cannot release the current wait. The recovery path re-reads intents after completing pending
acceptance intents, so it uses current durable intent state.

Regression evidence covers a crash after the parent enters `waiting` before its first child exists,
and a restart during a later wait with an earlier succeeded child and a current queued child. Existing
terminal-child crash recovery now names the current phase child.

Checks in this run:

- `cd backend && uv run pytest -q tests/test_job_*.py tests/test_jobs_api.py tests/test_automated_pipeline_jobs.py` — passed, 78 tests.
- `cd backend && uv run pytest -q tests/test_job_projection_authority.py` — passed, 23 tests, including 20/200 sibling growth, 20/200 unrelated-job growth, concurrent readers, journal recovery, and queue integrity cases.
- `cd backend && uv run ruff check src/dokodetector_backend/job_recovery.py src/dokodetector_backend/automated_pipeline_jobs.py tests/test_job_recovery.py tests/test_job_scheduler.py` — passed.
- `cd backend && uv run ruff format --check src/dokodetector_backend/job_recovery.py src/dokodetector_backend/automated_pipeline_jobs.py tests/test_job_recovery.py tests/test_job_scheduler.py` — passed.

The test client reports the existing Starlette/httpx deprecation warning. No API or browser contract
changed. Acceptance still scans intents, and scheduler and startup recovery still enumerate queue and
intent sets. The current five-milestone run has M6b1a complete, four remaining, and 0/10 total
re-plannings (0/5 for M6b1a). The next milestone is M6b1b. The previous run's two-correction limit
does not apply to this run.
