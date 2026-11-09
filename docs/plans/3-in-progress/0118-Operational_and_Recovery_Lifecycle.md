# Operational logs and recovery lifecycle

## Plan status

- **Status:** In Progress
- **Depends on:** [Epic 0115 closure](../5-closed/0115-Data_Cleanup.md), its [M14 storage map](../../reports/0115-M14_Maintained_Storage_Map.md), and the
  [M15 closure report](../../reports/0115-M15_Qualification_and_Closure.md) complete.
- **Outcome:** Define safe, evidence-based retention and growth controls for selected operational
  logs, recovery copies, and campaign intermediates. Preserve active work, recovery evidence, and
  exact dependencies.
- **Origin:** Epic 0115 deferred these independent writer families from M13 so its cache policies
  can close on their own recovery and concurrency evidence. See the [0115 M13 report](../../reports/0115-M13_Growth_Bounds.md).

## Scope and retention rules

This epic owns lifecycle decisions for operational logs, recovery copies, and campaign
intermediates that remain after 0115. It does not reopen 0115 or change its closed milestones.
Do not infer that a file is disposable from its age, size, path, or a completed job state.

Preserve active-job logs, data needed for restart or recovery, pinned provider responses, original
recordings, human review work, current model bundles, and exact dependencies needed by active work.
Treat campaign logs and copied training materializations as separate writer families when their
owners or retention rules differ. Keep unresolved references and uncertain recovery paths intact.
Relocation is not reclaimed space. Record physical allocation only when directly measured.

## Milestones

| Milestone | Observable result / commit boundary | State |
| --- | --- | --- |
| M0 | Inventory exact log, recovery-copy, and campaign-intermediate writers; identify retention roots, recovery evidence, and a small candidate scope | Complete; [report](../../reports/0118-M0_Lifecycle_Family_Inventory.md) |
| M1 | Specify the managed-job operational-log family's retention and recovery contract, or record why no safe bounded policy is justified | Complete; [report](../../reports/0118-M1_Managed_Job_Log_Audit.md) |
| M2 | Specify one exact recovery-copy family's retention and restore contract, or record why no safe bounded policy is justified | Not started |
| M3 | Specify one exact campaign-intermediate family's retention and restore contract; keep it separate from recovery copies | Not started |
| M4 | Implement and verify only the selected contracts, with preserved recovery and human-work evidence | Not started |

## M0 — Select exact lifecycle families

Use the 0115 storage map and existing reports as the starting point. Confirm current writers and
readers for each candidate, exact retained roots, current sizes, active pins, whether content can be
regenerated, and the tested recovery path. Choose only bounded families with clear owners. If
operational logs, recovery copies, or campaign artifacts require independent contracts, split them
into separate specification milestones before assignment. Do not remove or expire data in M0.

Checks: every selected path maps to a writer, reader, retention authority, and recovery source.
Report unknown ownership, physical-allocation limits, and unresolved dependencies explicitly.

## Execution handoff

- Run: requested 4 milestones; completed 2; 2 remain in this run. M0–M4 are planned; this run
  stops at four completed milestones even if work remains.
- Completed: M0 inventory and family selection; M1 managed-job log audit. See the
  [M0 report](../../reports/0118-M0_Lifecycle_Family_Inventory.md) and
  [M1 report](../../reports/0118-M1_Managed_Job_Log_Audit.md).
- Changes: M1 found an existing 1,000-entry rolling window, no per-entry byte bound, and no
  independent log restore source. It freezes no new expiry or size policy and preserves all log
  files. M0 selected the accepted-loss migration stage for M2, subject to current-root revalidation.
  Campaign intermediates remain a separate M3 family.
- Checks: `mise exec -- uv run --project backend pytest -q backend/tests/test_job_recovery.py`
  passed (13 tests). M1 added a deterministic case for active and terminal logs, concurrent append
  and read, and restart. Exact source and current-root evidence are in the M1 report. No stored data
  was changed or deleted.
- Decisions and limits: current configured `data/operations/jobs` is absent in this checkout.
  The active process root, live job set, log sizes, pins, expiry authority, and independent recovery
  source remain unknown. The existing rolling window is code behavior, not evidence that older
  entries are disposable. Off-volume recovery and physical APFS allocation remain unknown.
- Next: M2 must revalidate the selected recovery snapshot, its owner and exact references, and
  rehearse restore in disposable storage. Preserve the candidate if any source or reference is
  uncertain.

## M1 — Specify operational-log retention

Select one exact operational-log writer family. Define active and terminal states, expiry conditions,
size bounds if supported by evidence, concurrent append/read behavior, and recovery requirements.
Preserve logs needed to diagnose or recover active work. Do not include campaign command/output logs
unless M0 shows they share the same owner and contract.

Checks: deterministic lifecycle cases cover active work, terminal work, concurrent access, and
restart. Do not implement until the contract and acceptance evidence are frozen.

Outcome: Complete. The [M1 report](../../reports/0118-M1_Managed_Job_Log_Audit.md) records the
exact writer and readers, the existing 1,000-entry rolling window, atomic append/read behavior,
restart behavior, and why no safe expiry or new size policy is justified. A focused test covers
active and terminal records, concurrent appends and reads, and restart. No data was removed and no
retention code was changed.

## M2 — Specify recovery-copy retention

Use the accepted-loss migration stage selected in M0 only after confirming that its current snapshot,
owner, references, and root match the recorded evidence. Record its creator, dependency and pin
roots, reconstructability, expiry condition, and restore procedure. Keep the copy until its
replacement is verified and the declared recovery window ends. Do not apply cache expiry rules.

Checks: rehearse the selected restore in disposable storage. Verify exact retained human work,
dependencies, and restart reads. Record logical bytes, path allocation, and physical allocation
separately when available. If the current root or recovery source cannot be confirmed, document the
limit and do not specify expiry.

## M3 — Specify campaign-intermediate retention

Select one exact campaign materialization family. Record its creator, campaign and source manifests,
dependency and pin roots, reconstructability, expiry condition, and restore or regeneration
procedure. Keep campaign command/output logs out of this contract unless evidence shows the same
writer and retention authority. Keep compact provenance when removing reproducible materializations.

Checks: rehearse restore or regeneration in disposable storage. Verify exact source and review
dependencies, model/run references, and restart reads. Record logical bytes, path allocation, and
physical allocation separately when available. If one campaign contains independent writer or
recovery contracts, split its specification before implementation.

## M4 — Implement selected lifecycle contracts

Implement only family contracts completed by M1, M2, and M3. Use explicit manifests and durable
receipts for any authorized removal. Preserve fail-closed behavior for unknown references. Verify
active and terminal work, concurrent readers and writers where relevant, interruption and restart,
restore or regeneration, and measured storage effects. Report logical removal, relocation, path
allocation, and physical space separately. If a safe policy cannot be established, record the limit
and close the affected scope without deleting data.
