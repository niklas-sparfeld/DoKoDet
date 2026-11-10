# Node-publication test discrepancy

- **Status:** Ready
- **Depends on:** None.
- **Outcome:** Establish and test the expected behavior when a pipeline-node save fails before publication, and resolve two existing tests that currently expect unpublished revision directories.
- **Owner:** `PipelineNodeStore`, `PipelineNodeEdits`, node publication and transaction tests.
- **Origin:** 0119 M1 broad-suite acceptance gap, reproduced on main at `28642242`.

## Evidence and boundary

The tests `test_interrupted_head_update_does_not_publish_revision` and
`test_retry_does_not_delete_orphan_with_dependent_records` both fail at `next(...)` because the
failed save leaves no additional directory under `revisions/`. The tests expect an orphan. Current
node publication uses staged writes and transaction recovery. Inspect the failure injection point,
save order, cleanup rules, and publication authority before deciding whether the implementation or
the assertions are wrong. Do not assume either side is correct from the two failures alone.

This epic does not change pipeline job recovery, migrate node storage, add publication authority,
or weaken exact-read guarantees. If evidence shows an independent storage-authority defect beyond
these failed-save cases, record a separate bounded follow-up with its own reproducer.

## M0 — Reconcile failed-save behavior and tests

Trace both test operations through `PipelineNodeStore.save` and `PipelineNodeEdits.edit`, including
staging cleanup, HEAD publication, authority records, and recovery after reopening the store.
Determine whether failed writes must preserve an orphan or clean up the staged revision. Make the
smallest source or test correction supported by that contract. Retain assertions for unchanged
HEAD, history, unpublished-read rejection, and dependent records where applicable.

Checks: both focused regressions; all `backend/tests/test_pipeline_node_store.py`,
`backend/tests/test_pipeline_node_edits.py`, and `backend/tests/test_pipeline_node_transactions.py`;
affected Ruff and format checks. Record exact failure injection and durable filesystem state before
and after reopening.

Commit boundary: one focused contract correction, retained regressions, evidence report, and board
update. Stop if behavior remains ambiguous or requires a new publication or transaction contract.
