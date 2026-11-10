# Epic 0117 M6b1a: ordered queue authority

## Current review result

M6b1a remains incomplete. Final review found that startup reconciliation ignores an unlinked
interrupted child after cancellation, so stage status and lineage can remain stale. Add a persisted
restart regression for this boundary. Restore the separate cancelled-child observer-crash regression;
the latest correction replaced it. The two-correction limit stopped the run.

## Earlier correction — child completion and cancellation

Date: 2026-11-10

The job transition observer now calls `_child_is_complete` before it records a succeeded pipeline
stage as complete. If the child job succeeded but its underlying analysis or pipeline result is not
complete, the stage and run fail with the existing failure path. This prevents a crash before the
parent resumes from leaving a false complete stage. The observer now handles cancelled children,
stores cancelled stage and run status, and retains the resolved input revision IDs. The then-current restart regression covered a cancelled child. A later correction replaced that
regression; the current review requires restoring it.

Checks:

- `cd backend && uv run pytest -q tests/test_job_*.py tests/test_jobs_api.py tests/test_automated_pipeline_jobs.py` — passed, 81 tests.
- `cd backend && uv run pytest -q tests/test_job_projection_authority.py` — passed, 23 tests.
- Ruff check and format check passed for the changed backend module and tests.
- `git diff --check` — passed.

The child-completion regression uses the local run-store fixture. The initial cancellation regression
only reused its in-memory run document and did not cover a crash before the observer; correction 1/2
below adds persisted restart evidence. No API or browser contract changed. The existing
Starlette/httpx deprecation warning remains. M6b1a remains complete after this correction; the new
five-milestone run has 1 complete and 4 remaining, with 0/10 run re-plannings and 0/5 for M6b1a.
Next is M6b1b. M6b1b still owns bounded acceptance-key, sequence, and parent-step authority.

## Correction 1/2 — recover cancellation after child write

Date: 2026-11-10

Review found that a crash after the terminal child job write but before the transition observer left
the run document without cancelled stage status or input lineage. Startup reconciliation now finds
the cancelled child for the parent's current phase, resolves the stage's frozen input revisions, and
stores the cancelled stage before it finishes the run as cancelled. The regression uses
`AutomatedPipelineRunStore` on disk, crashes before the observer, reopens the job manager and run
store, then verifies cancelled parent and run state, child identity, stage status, and input lineage.

Checks: `cd backend && uv run pytest -q tests/test_automated_pipeline_jobs.py -k cancelled_child_stage` — passed.
The initial full suite count above is 81 (not the stale 79 in the prior handoff).

## Correction 2/2 — reconcile interrupted child after cancellation restart

Date: 2026-11-10

Review found a second cancellation boundary: startup converts a persisted cancelling child to
`interrupted` and its cancelling pipeline parent to `cancelled`. Reconciliation now accepts that
interrupted child for the parent's current phase, records the actual `interrupted` stage status,
preserves the child ID and resolved input revision IDs, then finishes the overall run as cancelled.
The persisted restart regression leaves both jobs cancelling, reopens the manager and run store,
checks startup's child and parent outcomes, and verifies the run and stage documents. Correction
count is 2/2; no further M6b1a correction turns remain in this run.

Check: `cd backend && uv run pytest -q tests/test_automated_pipeline_jobs.py -k interrupted_child_stage_of_cancelled_parent` — passed.

Date: 2026-11-09

## Current result

M6b1a remains incomplete after two current-run corrections. Final review found that the transition
observer can mark a succeeded child stage complete before its underlying result is complete. A
crash before the parent runs can preserve that false status. The observer also omits cancelled
children; verify cancellation status and lineage across restart. The correction limit stopped the run.

The implemented recovery work is integrated but not accepted as complete. Startup recovery reconnects an unlinked accepted
child to the parent step, and automated pipeline status recovery restores the stage's authoritative
inputs before child work resumes. Job transitions keep stage status current while the child runs.
The end-to-end evidence covers a later-stage acceptance/link crash, input lineage, completed-stage
reuse, and pipeline continuation. See the current-run completion and correction sections below.

## Historical result from the previous run

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

Commits `323a021c` and `1a6fc590` were integrated in the previous run. Review did not accept M6b1a.
At that time, two defects remained:

- A crash after the parent enters `waiting` but before the first child is accepted leaves the parent
  waiting permanently.
- A restart during a later wait can requeue the parent based on an old terminal child while the
  current child remains queued.

Recovery then needed durable evidence that identified the current wait and its child transition.
Those defects were resolved in the current run.

Startup recovery calls `JobRecovery.rebuild_queue()` and rebuilds the parent-child state from durable
jobs and intents. Until repair completes, queue reads fail closed. The old `queue.json` is imported
once to retain its ordering, then removed and the directory is synced after successful repair.
Ordinary acceptance still scans intents for idempotency, sequence allocation, and parent-step
uniqueness. M6b1b owns those reads and their transaction. Scheduler candidate discovery and startup
repair still enumerate the full queue or intent set; M6b2 owns bounded active-job pages.

## Historical checks from the previous run

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
a restart during a later wait with an earlier succeeded child and a current queued child, and a crash
after a later child commits before its parent link and stage document write. Startup reconciliation
restores the stage's exact input lineage and queued state. Child state transitions update the stage
status while it runs and preserve input lineage on completion. The end-to-end test verifies reuse of
the completed later stage.

Checks in this run:

- `cd backend && uv run pytest -q tests/test_job_*.py tests/test_jobs_api.py tests/test_automated_pipeline_jobs.py` — passed, 79 tests.
- `cd backend && uv run pytest -q tests/test_job_projection_authority.py` — passed, 23 tests, including 20/200 sibling growth, 20/200 unrelated-job growth, concurrent readers, journal recovery, and queue integrity cases.
- Ruff check and format check passed for the changed backend modules and job tests.

The test client reports the existing Starlette/httpx deprecation warning. No API or browser contract
changed. Acceptance still scans intents, and scheduler and startup recovery still enumerate queue and
intent sets. The current five-milestone run has M6b1a complete, four remaining, 0/10 total
re-plannings (0/5 for M6b1a), and correction count 2/2. The next milestone is M6b1b. The previous
run's two-correction limit does not apply to this run.

## Correction 1/2

Review found a crash gap after child acceptance commits and before the parent step stores the child
ID. Recovery now restores that ID from the exact intent matching the parent's current phase before it
checks the child's state. It restores the link for both queued and terminal children. If the child is
still uncommitted, recovery retains the link and wait while it completes acceptance. A conflicting
link or multiple intents for one phase still fails closed with a diagnostic.

The regression `test_restart_recovers_unlinked_child_and_completes_pipeline` crashes at the durable
child acceptance commit, restarts the manager, verifies the parent link, dispatches the child to
succeeded, and verifies the pipeline completes without creating a duplicate child. The terminal-child
recovery test now starts with an unlinked accepted child and checks link restoration for succeeded,
failed, interrupted, and cancelled outcomes.

## Correction 2/2

The child-link crash also occurs before `_set_stage` writes the pipeline run document. On restart, the
run document therefore lacked the stage input revisions and child ID. Startup reconciliation now
rebuilds that stage row from the parent phase, linked child job, and completed prior-stage results.
It records `queued` status before dispatch. Job state transitions notify the registered participants;
the pipeline participant records `running` when the child starts and preserves the same input lineage
when it completes or fails. Resumed parent processing also writes the authoritative inputs when it
copies a child's terminal status, so `_reuse_completed_stage` can validate the saved inputs.

The regression crashes on acceptance commit for the second pipeline stage, after the first stage has
completed. After restart it checks the second stage's exact input revision, child ID, and queued status;
then it checks `running` status and input lineage during child execution. After completion it verifies
that `_reuse_completed_stage` returns the existing child and that parent processing advances to the
next stage. The current run has 2/2 correction turns, 0/10 total re-plannings, and M6b1b remains next.
