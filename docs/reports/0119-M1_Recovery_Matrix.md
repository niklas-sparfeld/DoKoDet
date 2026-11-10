# 0119 M1 recovery matrix and closeout attempt

Date: 2026-11-10. M1 implementation checkout before this evidence: `1a1fb617`.

## First M1 attempt result

The M1 service proof is implemented as an additive test in
`backend/tests/test_automated_pipeline_jobs.py`. It uses a real `JobManager`,
`AutomatedPipelineRunService`, and `AutomatedPipelineRunStore` with disposable files and
deterministic child handlers. One six-stage run completes. A second run is cancelled while its
child is active, both stores close, and a new manager recovers the child as interrupted and the
parent as cancelled. A new run-store instance confirms durable status, child identity and exact
input lineage. Each deterministic child request includes the exact input revision IDs passed by
the stage planner. The test compares those request IDs with both the saved result inputs and the
durable run-stage inputs. It records the queue after each child acceptance, checks that the new
child is the parent group's queue head and only dispatchable job, and confirms execution followed
the declared stage order. All six stage results and downstream revision references are durable.

The required backend job/API/pipeline suite does not pass. Two node-publication tests fail because
they expect an unpublished revision directory after failed saves. Both fail at `next(...)` with
`StopIteration`. The same two tests fail on the unmodified pre-M1 main revision `28642242`, so these
failures are baseline evidence and are outside the 0119 source boundary. Epic
[0122](../plans/5-closed/0122-Node_Publication_Test_Discrepancy.md) owns their investigation.
M1 remains incomplete and blocked. No 0120 work is authorized by this result.

## Finite recovery matrix

| Boundary or state | Retained evidence | Result |
| --- | --- | --- |
| Parent waits before child acceptance | `test_waiting_parent_without_current_child_is_requeued_after_restart` in `test_job_recovery.py` | Pass; parent is requeued. |
| Child acceptance commits before parent link/stage write | `test_restart_recovers_unlinked_child_and_completes_pipeline`; job acceptance crash-boundary tests | Pass; accepted child is linked and retained in parent queue group. |
| Child terminal write precedes observer notification | `test_cancelled_child_persisted_before_observer_recovers_after_restart` | Pass; cancelled stage is repaired after restart. |
| Parent queue-delta publication and order | New real workflow checks each accepted child becomes the parent group's queue head and only dispatchable job; `test_child_acceptance_recovers_in_parent_group`, `test_parent_queue_tail_reorder_recovers_with_parent_transition`, `test_waiting_parent_group_keeps_children_and_order_after_restart`, and `test_queue_moves_revision_and_restart` | Pass; current-stage queue publication and retained queue order survive recovery. |
| Cancellation and restart | M0 interrupted and cancelled persistence tests; new real service workflow | Pass; current child identity, stage outcome and lineage are restored. |
| Succeeded child | New real service workflow; six durable stage result IDs and complete run status | Pass. |
| Failed child and completed-stage reuse | `test_parent_retry_reuses_verified_completed_stage_and_keeps_failed_history`; `test_later_stage_recovery_restores_lineage_status_and_reuse` | Pass; completed work is reused and failed history remains. |
| Interrupted and cancelled child | `test_unlinked_interrupted_child_recovers_exact_stage_and_inputs_after_restart`; `test_cancelled_child_persisted_before_observer_recovers_after_restart` | Pass; both crash boundaries remain distinct. |
| Current versus earlier phase and ambiguity | `test_cancelled_stage_reconciliation_rejects_earlier_or_ambiguous_children`; persisted competitor tests | Pass; earlier and conflicting same-phase children do not substitute. |
| Input lineage and repeated restart | Unlinked interrupted-child recovery test; new completed workflow | Pass; exact revisions survive repeated recovery/reopen. |

The matrix adds no queue, acceptance, storage, processor, or authority contract. It found no
evidence of a job journal or queue authority design defect.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_automated_pipeline_jobs.py -q` — passed, including the new real service test.
- `mise exec -- uv run --project backend pytest backend/tests/test_job_recovery.py backend/tests/test_job_scheduler.py backend/tests/test_job_publication.py backend/tests/test_job_projection_authority.py backend/tests/test_jobs_api.py backend/tests/test_automated_pipeline_jobs.py backend/tests/test_automated_pipeline_run.py backend/tests/test_pipeline_run_api.py -q` — passed.
- Required broad suite: `mise exec -- uv run --project backend pytest backend/tests/test_job*.py backend/tests/test_jobs_api.py backend/tests/test_pipeline*.py backend/tests/test_automated_pipeline*.py -q` — failed only at `test_pipeline_node_edits.py::test_retry_does_not_delete_orphan_with_dependent_records` and `test_pipeline_node_store.py::test_interrupted_head_update_does_not_publish_revision`.
- Baseline reproduction at main `28642242`: the two focused tests above fail with the same `StopIteration` at the orphan lookup.
- Broad suite with those two tests deselected — passed: `mise exec -- uv run --project backend pytest backend/tests/test_job*.py backend/tests/test_jobs_api.py backend/tests/test_pipeline*.py backend/tests/test_automated_pipeline*.py -q --deselect=tests/test_pipeline_node_edits.py::test_retry_does_not_delete_orphan_with_dependent_records --deselect=tests/test_pipeline_node_store.py::test_interrupted_head_update_does_not_publish_revision`. This does not satisfy M1's full-suite acceptance check.
- Ruff check, Ruff format check, and `git diff --check` for the changed test — passed.

## Resumed verification and closure

After 0122 M0, the following checks were rerun from checkout revision `9d695999`:

- `mise exec -- uv run --project backend pytest backend/tests/test_job*.py backend/tests/test_jobs_api.py backend/tests/test_pipeline*.py backend/tests/test_automated_pipeline*.py -q` — passed, including both corrected node-publication tests. Pytest reported one existing Starlette/httpx deprecation warning.
- `mise exec -- uv run --project backend pytest backend/tests/test_job_projection_authority.py backend/tests/test_job_store.py backend/tests/test_job_recovery.py backend/tests/test_job_scheduler.py backend/tests/test_job_publication.py -q` — passed.
- `mise exec -- uv run --project backend ruff check backend/tests/test_automated_pipeline_jobs.py backend/tests/test_job_recovery.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/tests/test_automated_pipeline_jobs.py backend/tests/test_job_recovery.py` — passed.
- `git diff --check` — passed.

The M1 workflow proof and finite recovery matrix above remain the same. Together with these
checks, all M1 acceptance criteria pass. No authority or queue defect was found. No new owner,
storage, transaction, processor or authority contract was added. This run requested 1 milestone,
completed 1, and has 0 remaining; run re-plannings are 0/10 and M1 re-plannings remain 0/5.
Correction history is unchanged: M0 1/2 and M1 1/2. The earlier run requested 2 milestones,
completed 1 and had 1 remaining.

## Status and next step

M1 is complete. The broad backend job/API/pipeline suite and authority/queue suite pass, and the
persisted multi-stage completion plus cancellation/restart workflow verifies exact inputs, durable
results and queue order. Epic 0119 is Closed; 0120 is Ready and was not started in this run.
