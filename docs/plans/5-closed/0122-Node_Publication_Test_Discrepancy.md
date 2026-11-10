# Node-publication test discrepancy

- **Status:** Closed
- **Depends on:** None.
- **Outcome:** Establish and test the expected behavior when a pipeline-node save fails before publication, and resolve two existing tests that currently expect unpublished revision directories.
- **Owner:** `PipelineNodeStore`, `PipelineNodeEdits`, node publication and transaction tests.
- **Origin:** 0119 M1 broad-suite acceptance gap, reproduced on main at `28642242`.
- **Closure reason:** Complete.

## Evidence and boundary

The tests `test_interrupted_head_update_does_not_publish_revision` and
`test_retry_does_not_delete_orphan_with_dependent_records` both failed at `next(...)` because the
failed save left no additional directory under `revisions/`. Both tests patched
`pipeline_node_store.atomic_replace_json` to fail on every call. The first call writes the revision
history outbox, before the revision directory is staged. The injected failure did not reach HEAD
publication.

The tests now allow the outbox write and revision staging, then fail only on replacement of
`head.json`. This shows that the failed operation leaves an unpublished revision directory, while
the HEAD stays unchanged and no publication authority is written for that revision. Reopening
retains the directory but drops its outbox history intent. Exact reads and dependent acceptance
reject the revision. An edit retry removes the uncommitted revision only when it has no dependent
records; otherwise it raises `NodeConflict` and retains the revision.

This epic does not change pipeline job recovery, migrate node storage, add publication authority,
or weaken exact-read guarantees. No independent storage-authority defect was found.

## M0 — Reconcile failed-save behavior and tests — Complete

Trace both test operations through `PipelineNodeStore.save` and `PipelineNodeEdits.edit`, including
staging cleanup, HEAD publication, authority records, and recovery after reopening. Correct the
failure injection to target the HEAD replacement. Retain assertions for unchanged HEAD, history,
unpublished-read rejection, and dependent records.

Checks: both focused regressions; all `backend/tests/test_pipeline_node_store.py`,
`backend/tests/test_pipeline_node_edits.py`, and
`backend/tests/test_pipeline_node_transactions.py`; affected Ruff and format checks; local link
checks after moving this epic.

Commit boundary: one focused test correction, evidence report, and board update.

## Execution handoff

- **Original outcome:** Establish and test expected failed-save behavior; resolve two existing
  failed-save tests.
- **Non-goals:** No job recovery changes, storage migration, new publication authority, weakened
  exact reads, or new transaction contract.
- **Initial plan:** One milestone. M0 was the first and final complete workflow proof.
- **Workflow proof:** The direct save and edit failure cases now inject at `head.json`; the tests
  verify the durable state before and after reopen, unchanged HEAD and history, unpublished-read
  rejection, and dependent-record retention. See the [M0 evidence report](../../reports/0122-M0_Node_Publication_Behavior.md).
- **Source owners/contracts:** Existing `PipelineNodeStore`, `PipelineNodeEdits`, and publication
  authority behavior only. No new source owner or contract.
- **Scope decision:** Keep the current behavior and narrow the test injection to the intended HEAD
  boundary. This resolves the discrepancy without production changes.
- **Counts:** Baseline focused regressions 0/2 passed; corrected focused regressions 2/2 passed;
  specified node store/edit/transaction suites 40 passed. Initial milestones 1; current remaining
  milestones 0. This run requested 1, completed 1, remaining 0. M0/run replannings: 0/5 and 0/10.
  Corrections: 0.
- **Next:** None in this epic. 0119 M1 can rerun its broader acceptance suite with these failures
  corrected.
- **Stop condition:** Met. The two regressions and all three specified test files pass; the existing
  authority and exact-read behavior remains unchanged.
