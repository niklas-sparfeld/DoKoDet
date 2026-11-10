# 0122 M0 node-publication behavior

Date: 2026-11-10. Baseline: `2adb5db2` in the `f3db` worktree.

## Result

The two failures came from broad failure injection in the tests. Both patched
`pipeline_node_store.atomic_replace_json` to fail on every call. `PipelineNodeStore.save` first uses
that function to write the revision-history outbox, before it creates the revision directory.
The injected error therefore occurred before the tested HEAD replacement. The tests then expected
a revision directory that the operation had not created.

The tests now allow earlier atomic writes and fail only when the target is `n/head.json`. No
production storage or transaction behavior changed. This keeps the existing authority and recovery
rules intact.

## Observed save sequence

For both direct save and edit, the selected failure injection permits the history outbox write,
revision staging and commit, and publication of the previous HEAD revision's authority. It raises
at the atomic replacement of `head.json`, before the new revision gets publication authority.

| State | Before reopen | After reopen |
| --- | --- | --- |
| `head.json` | Points to the initial revision | Still points to the initial revision |
| Revision directory | New `revision.json` exists | Still exists as an unpublished revision |
| New revision publication authority | Absent | Absent |
| Node history | Not yet reopened | Contains only the initial revision |
| Exact read of new revision | Not authorized | Rejected by exact and published reads |

On reopen, the history outbox reconciliation sees that the new revision is neither the HEAD nor
published and drops its history intent. It does not remove the revision directory. The unchanged
HEAD and absence of publication authority prevent reads and dependent acceptance. The store does
not infer publication from a directory.

For edit retry, `PipelineNodeEdits` first attempts to recover a completed authorized revision. The
unpublished revision is not recoverable. With no dependent records, retry removes the matching
uncommitted revision and then saves the edit. When the regression test writes accepted-use and
review records for that revision before retry, cleanup raises `NodeConflict` and retains the
revision. The HEAD remains unchanged. This keeps the distinct dependent-record protection check.

## Checks

- Before correction, both focused tests failed at the orphan lookup with `StopIteration`.
- Focused regressions after correction: 2 passed.
- `test_pipeline_node_store.py`, `test_pipeline_node_edits.py`, and
  `test_pipeline_node_transactions.py`: 40 passed.
- Both existing exact-read rejection and dependent-record assertions remain covered.

## Scope decision

Keep the existing publication contract and correct the failure injection. No new publication
authority, transaction contract, recovery behavior, migration, or job-recovery change is needed.
The single M0 workflow proof is complete. The remaining scope is zero.
