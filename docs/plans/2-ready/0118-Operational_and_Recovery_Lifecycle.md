# Operational logs and recovery lifecycle

## Plan status

- **Status:** Ready
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
| M0 | Inventory exact log, recovery-copy, and campaign-intermediate writers; identify retention roots, recovery evidence, and a small candidate scope | Not started |
| M1 | Specify one selected operational-log family's retention and recovery contract, or record why no safe bounded policy is justified | Not started |
| M2 | Specify one selected recovery-copy or campaign-intermediate family's retention and restore contract, or split independent families before implementation | Not started |
| M3 | Implement and verify only the selected contracts, with preserved recovery and human-work evidence | Not started |

## M0 — Select exact lifecycle families

Use the 0115 storage map and existing reports as the starting point. Confirm current writers and
readers for each candidate, exact retained roots, current sizes, active pins, whether content can be
regenerated, and the tested recovery path. Choose only bounded families with clear owners. If
operational logs, recovery copies, or campaign artifacts require independent contracts, split them
into separate implementation milestones before assignment. Do not remove or expire data in M0.

Checks: every selected path maps to a writer, reader, retention authority, and recovery source.
Report unknown ownership, physical-allocation limits, and unresolved dependencies explicitly.

## M1 — Specify operational-log retention

Select one exact operational-log writer family. Define active and terminal states, expiry conditions,
size bounds if supported by evidence, concurrent append/read behavior, and recovery requirements.
Preserve logs needed to diagnose or recover active work. Do not include campaign command/output logs
unless M0 shows they share the same owner and contract.

Checks: deterministic lifecycle cases cover active work, terminal work, concurrent access, and
restart. Do not implement until the contract and acceptance evidence are frozen.

## M2 — Specify recovery-copy or campaign retention

Select one exact family. Record its creator, dependency and pin roots, reconstructability, expiry
condition, and restore procedure. Keep recovery copies until the replacement is verified and the
declared recovery window ends. Keep compact provenance when removing reproducible campaign
materializations. Do not apply cache expiry rules to recovery or campaign data.

Checks: rehearse the selected restore or regeneration path in disposable storage and verify exact
retained human work and dependencies. Split this milestone if M0 selects independent families.

## M3 — Implement selected lifecycle contracts

Implement only the family contracts completed by M1 and M2. Use explicit manifests and durable
receipts for any authorized removal. Preserve fail-closed behavior for unknown references. Verify
interruption, restart, concurrency where relevant, restore, and measured storage effects. Report
logical removal, relocation, and physical space separately. If a safe policy cannot be established,
record the limit and close the affected scope without deleting data.
