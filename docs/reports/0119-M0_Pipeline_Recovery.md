# 0119 M0 pipeline recovery

Date: 2026-11-10. Inspected baseline: `2f0749c3`.

## Result

Cancelled-parent reconciliation searched only for cancelled children when the parent had no
persisted child link. Restart recovery can mark that child interrupted, so the stage and its input
lineage stayed stale. The lookup now accepts either terminal state and still requires one child
for the parent's exact current phase. It does not use an earlier-phase child or choose among
multiple matches.

## Persisted regressions

- A linked interrupted child restores stage status, identity, and input revision after restart.
- An unlinked interrupted child restores the same fields from persisted job and run stores. A
  second reconciliation and another reopen keep the same single persisted child; recovery does
  not accept another child.
- A cancelled child persisted before observer notification is repaired after restart. This crash
  boundary remains separate from interrupted-child recovery.
- Persisted conflicts with another same-phase child in `queued`, `failed`, or `succeeded` state
  remain ambiguous. Earlier-phase children cannot substitute for the current phase.

The parent link is cleared in the unlinked test after acceptance and cancellation, before closing
the manager. This models the persisted gap without changing acceptance behavior.

## Checks

- `uv run --project backend pytest backend/tests/test_automated_pipeline_jobs.py backend/tests/test_job_recovery.py -q` — passed, 32 tests.
- `uv run --project backend ruff check backend/src/dokodetector_backend/automated_pipeline_jobs.py backend/tests/test_automated_pipeline_jobs.py backend/tests/test_job_recovery.py` — passed.
- `uv run --project backend ruff format --check backend/src/dokodetector_backend/automated_pipeline_jobs.py backend/tests/test_automated_pipeline_jobs.py backend/tests/test_job_recovery.py` — passed.

## Limits and next work

This is local persisted recovery evidence. It does not prove a complete multi-stage service run or
the full terminal-state and queue-order matrix. M1 owns that proof. No storage, transaction,
processor, or acceptance contract changed.

## Review correction

The first review found that the lookup counted only cancelled and interrupted children. A
same-phase queued, failed, or succeeded child could therefore be hidden. The lookup now counts all
children for the exact current phase before selecting a unique child. The persisted conflict tests
and a second reopen verify this behavior. Correction turn 1 of 2; no re-planning or scope change.
