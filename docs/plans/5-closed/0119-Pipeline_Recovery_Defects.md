# Pipeline recovery defects

- **Status:** Closed
- **Depends on:** Integrated job and pipeline implementation at `99b79d59`; 0117 is closed; 0122 M0 resolved the node-publication test discrepancy.
- **Outcome:** Recover the current pipeline stage, child identity, and exact input lineage after
  cancellation and interrupted child acceptance. Retain all distinct crash regressions.
- **Origin:** [0117 exit decision](../../reports/0117-Supersession_and_Exit.md).
- **Closure reason:** Complete.

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
| M0 | Exact current-child cancellation recovery and additive persisted regressions | Complete |
| M1 | Finite recovery matrix and real service closeout | Complete |

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

### M1 execution result

The persisted service proof, finite recovery matrix, and resumed full-suite checks are recorded in
the [M1 evidence report](../../reports/0119-M1_Recovery_Matrix.md). The broad backend job/API/
pipeline suite now passes after [0122](0122-Node_Publication_Test_Discrepancy.md) corrected the
failure injection in the two baseline tests. The authority and queue suite, Ruff checks, format
check, and diff check also pass. The M1 acceptance criteria are complete. No recovery authority
defect or additional scope was found.

## Execution handoff

### Goal and progress

- Original outcome: recover the current pipeline stage, child identity, and exact input lineage
  after cancellation and interrupted child acceptance. Retain all distinct crash regressions.
- Non-goals: queue performance, acceptance redesign, and storage format changes.
- Final closure check: M1 recovery matrix and real service closeout pass with all retained crash
  regressions.
- First complete workflow: persisted cancellation and restart. M0 proves the local recovery path;
  M1 is scheduled to prove the full Job Manager and run-store workflow.
- Initial plan: 2 milestones. Current: 2 of 2 complete, 0 remain. No new owners or contracts.

### M0 result

- Change: cancelled-stage reconciliation now finds the unique child for the exact current phase
  when recovery records it as either `cancelled` or `interrupted`. Multiple matches remain
  ambiguous and are rejected.
- Regressions: linked interrupted child; unlinked interrupted child with restart, repeated
  reconciliation, another reopen, and a one-child count; cancelled child persisted before observer
  notification. Persisted same-phase competitors in queued, failed, and succeeded states are all
  rejected. Earlier-phase isolation remains covered. The distinct crash cases remain separate.
- Checks: `uv run --project backend pytest backend/tests/test_automated_pipeline_jobs.py
  backend/tests/test_job_recovery.py -q` passed (32 tests); affected Ruff check and format check
  passed. Evidence: [M0 recovery report](../../reports/0119-M0_Pipeline_Recovery.md).
- Limits: stage recovery has persisted local-store coverage. Full real service workflow and the
  finite status/input matrix remain for M1.

### Run and scope history

- Earlier run: requested 2 milestones, completed 1, remaining 1. Resumed run: requested 1,
  completed 1, remaining 0.
- Re-planning: M0 0/5; run 0/10. Correction turns used: 1/2. Review found that filtering out
  queued and other non-cancelled outcomes before counting could hide a conflicting same-phase
  child. The lookup now counts every child for the exact parent phase before selecting one.
  No inherited 0117 correction budget.
- M1 accounting: 0/5 re-plannings; correction turn 1/2 checked exact input revisions in each
  child request, saved result and run-stage record, and queue publication plus dispatch order.
  The real service proof and finite matrix pass. Run re-plannings are 0/10; M0 correction turns
  remain 1/2 and M1 correction turns remain 1/2.
- Scope decision: keep the bounded local fix in existing authority. No new storage, transaction,
  processor contract, or stronger guarantee was added. 0122 resolved the independent test
  discrepancy without production changes.
- Next: 0119 is closed. Epic 0120 is Ready; do not start it in this run. Stop if future work finds
  a broken authority design; use the rollback assessment in the 0117 exit decision.
