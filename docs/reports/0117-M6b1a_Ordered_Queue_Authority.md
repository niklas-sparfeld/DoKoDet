# Epic 0117 M6b1a: ordered queue authority

Date: 2026-11-09

## Result

Complete after correction 2/2. The active-job SQLite store now owns ordered queue groups, queued
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
