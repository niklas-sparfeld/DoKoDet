# Pipeline recovery defects

- **Status:** Ready
- **Depends on:** Integrated job and pipeline implementation at `99b79d59`; 0117 is closed.
- **Outcome:** Recover the current pipeline stage, child identity, and exact input lineage after
  cancellation and interrupted child acceptance. Retain all distinct crash regressions.
- **Origin:** [0117 exit decision](../../reports/0117-Supersession_and_Exit.md).

## Scope and defect evidence

`JobRecovery.recover` converts a cancelling child to `interrupted` and its cancelling parent to
`cancelled`. Link repair later processes only waiting parents. If acceptance committed before the
parent stored the child ID, the cancelled-stage fallback in
`AutomatedPipelineJobHandler._reconcile_cancelled_stage` searches only cancelled children. The
unlinked interrupted child is omitted. Stage state and input lineage can remain stale.

Commit `a2fc9731` replaced `test_cancelled_child_stage_keeps_lineage_after_restart` with the
interrupted-child case. Both boundaries need separate tests. This is a defect repair epic, not a
queue performance or acceptance-authority epic. Preserve dispatch order, exact frozen requests,
publication verification and cancellation semantics. Do not change storage formats unless a
reproducer proves a local repair cannot satisfy them.

## Milestones

| Milestone | Result | Status |
| --- | --- | --- |
| M0 | Exact current-child cancellation recovery and additive persisted regressions | Not started |
| M1 | Finite recovery matrix and real service closeout | Not started |

## M0 — Repair the current-child lookup

Start with a failing test that leaves the accepted current child unlinked, cancels both jobs, and
reopens the real job and pipeline run stores. Repair exact current-phase child discovery for
cancelled and interrupted outcomes. Preserve ambiguity rejection for multiple/conflicting children;
an earlier terminal child cannot substitute for the current phase. Restore the separate crash after
cancelled-child persistence and before observer notification. Do not replace existing crash tests.

Checks: both linked and unlinked current children, cancelled and interrupted outcomes, exact child
ID and input lineage after restart, repeated recovery, earlier-phase child isolation, no duplicate
acceptance. Run job recovery and automated pipeline tests, affected Ruff checks and format.
Commit boundary: local recovery fix, additive regressions, evidence and board update.

## M1 — Verify and close

Freeze a finite matrix of the existing boundaries: wait before child acceptance; acceptance before
parent link/stage write; child terminal write before observer; parent queue-delta publication; and
cancellation restart. Reuse existing passing tests for unchanged boundaries. Add only missing
combinations relevant to M0. Include succeeded, failed, interrupted and cancelled terminal outcomes,
current versus earlier phase, input lineage, completed-stage reuse and repeated restart.

Run a real Job Manager and `AutomatedPipelineRunStore` with deterministic processor handlers and
disposable persisted data. Complete one multi-stage run and cancel/restart another. Verify exact
inputs, status, durable results and queue order. Run all backend job/API/pipeline tests plus authority
and queue tests, lint and format. No hardware, training, or full application performance campaign.
Commit boundary: finite matrix evidence, any local missing regression, closure and board move.
When M1 passes, move 0120 from Blocked to Ready in the same commit, update its status and board
entry, and mechanically repair links to its new location. Do not start 0120 automatically.

Close Complete only when the known gaps and retained tests pass together. A new unrelated defect
gets a separate epic. If the repair reveals a broken journal/queue authority design, stop and use
the selective rollback requirements in the exit decision; do not create an endless correction loop.

## Execution handoff

Planning only. No implementation started. Next: M0. No inherited 0117 run or correction budget.
