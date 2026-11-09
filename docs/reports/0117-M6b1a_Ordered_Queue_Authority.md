# Epic 0117 M6b1a: ordered queue authority

Date: 2026-11-09

## Result

Complete. The active-job SQLite store now owns ordered queue groups, queued child membership,
parent-child sequence and state, and the queue revision. A `job-record-transition/v3` journal binds
the queue delta to the existing M6a job update. One SQLite transaction publishes the active-job
index and queue state before job authority advances. Recovery validates and replays the combined
state idempotently. It rejects mismatched job, queue, child, or authority values.

Ordinary `JobManager.transition()` no longer reads all intents, loads all jobs, or rebuilds the queue.
It updates one job's group or child membership. Starting a job uses a point queue lookup and an
indexed query for the first queued child. Dependency checks use an ordered parent-child index and
read only the target intent plus the first prior child that is not succeeded. Parent cancellation
reads children for that parent only. Queue readers serialize with job writers. Explicit queue moves
use a SQLite transaction and keep the current group and child order.

Startup recovery calls `JobRecovery.rebuild_queue()` and rebuilds the parent-child state from durable
jobs and intents. Until repair completes, queue reads fail closed. The old `queue.json` is imported
once to retain its ordering, then removed and the directory is synced after successful repair.
Ordinary acceptance still scans intents for idempotency, sequence allocation, and parent-step
uniqueness. M6b1b owns those reads and their transaction. Scheduler candidate discovery and startup
repair still enumerate the full queue or intent set; M6b2 owns bounded active-job pages.

## Checks

- Focused job and pipeline suite: passed. This covers journal crash boundaries and replay, queue and
  parent/child order, legacy repair, queue corruption, scheduler dispatch, cancellation, restart,
  and API job flows. The queue transition test creates 20 children, makes `_intents()` fail if
  called, records exactly two target-intent reads, and verifies indexed child and dependency queries.
- Ruff check and format check on changed Python files: passed.
- Web OpenAPI verification, typecheck, and Vitest: passed (46 files, 243 tests).
- Playwright jobs and job-start-actions: passed (6 tests).
- `git diff --check`: passed.
- The local API test client reports the existing Starlette/httpx deprecation warning.

No HTTP or web contract changed. M6b1a does not claim bounded acceptance or bounded scheduler
candidate enumeration. See M6b1b and M6b2 for those remaining boundaries.
