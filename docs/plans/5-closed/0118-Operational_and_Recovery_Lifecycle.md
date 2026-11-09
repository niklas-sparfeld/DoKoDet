# Operational logs and recovery lifecycle

## Plan status

- **Status:** Closed
- **Depends on:** [Epic 0115 closure](0115-Data_Cleanup.md), its [M14 storage map](../../reports/0115-M14_Maintained_Storage_Map.md), and the
  [M15 closure report](../../reports/0115-M15_Qualification_and_Closure.md) complete.
- **Closure reason:** Complete. M0–M4 audited the selected writers and dependencies. No safe
  expiry or removal policy was established, so the lifecycle scope closes with all affected data
  preserved and no cleanup code added.
- **Outcome:** Define safe, evidence-based retention and growth controls for selected operational
  logs, recovery copies, and campaign intermediates. Preserve active work, recovery evidence, and
  exact dependencies. Physical space reclaimed is not established.
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
| M2 | Specify one exact recovery-copy family's retention and restore contract, or record why no safe bounded policy is justified | Complete; [report](../../reports/0118-M2_Accepted_Loss_Recovery_Copy.md) |
| M3 | Complete a bounded, read-only search for the 24 exact historical review-state and draft dependencies of the selected campaign view; distinguish their roles from matching immutable reviewed content; record a conservative retention and restore outcome | Complete; [audit report](../../reports/0118-M3_0070_Synthetic_Training_View.md) |
| M4 | Implement and verify only the selected contracts, with preserved recovery and human-work evidence | Complete; [closure report](../../reports/0118-M4_Lifecycle_Closure.md) |

## M0 — Select exact lifecycle families

Use the 0115 storage map and existing reports as the starting point. Confirm current writers and
readers for each candidate, exact retained roots, current sizes, active pins, whether content can be
regenerated, and the tested recovery path. Choose only bounded families with clear owners. If
operational logs, recovery copies, or campaign artifacts require independent contracts, split them
into separate specification milestones before assignment. Do not remove or expire data in M0.

Checks: every selected path maps to a writer, reader, retention authority, and recovery source.
Report unknown ownership, physical-allocation limits, and unresolved dependencies explicitly.

## Execution handoff

- Run: requested 2 milestones; completed 2; 0 remain. M4 was the final planned milestone.
- Completed: M0 inventory, M1 managed-job log audit, M2 accepted-loss recovery-copy audit, M3
  bounded 0070 M5 dependency search, and M4 lifecycle closure. Detailed evidence is in the
  [M0 report](../../reports/0118-M0_Lifecycle_Family_Inventory.md),
  [M1 report](../../reports/0118-M1_Managed_Job_Log_Audit.md),
  [M2 report](../../reports/0118-M2_Accepted_Loss_Recovery_Copy.md),
  [M3 report](../../reports/0118-M3_0070_Synthetic_Training_View.md), and
  [M4 closure report](../../reports/0118-M4_Lifecycle_Closure.md).
- Changes: no safe expiry or removal policy was established. M4 adds no cleanup code and removes
  no data. Preserve all logs, the accepted-loss recovery package, the 0070 view, and known review
  and recovery roots. Logical removal and relocation are zero; allocation change and physical
  reclamation were not measured.
- Checks: the managed-job log test passed (13 tests); the current accepted-loss verifier passed
  with matching M2 snapshot and plan digests; the fresh 0070 audit verified 1,328 restored files,
  537 rows, and the established 24/24 immutable, 7/24 state, and 0/24 draft counts. Documentation
  link validation and `git diff --check` passed. See the M4 report for commands and limits.
- Decisions and limits: no removal manifest or receipt is applicable because no removal was
  authorized. Unknown dependencies fail closed. The 17 expected mutable states and all 24 exact
  drafts remain unavailable within the bounded search. No full historical review recovery,
  independent off-volume recovery, exact regeneration, or physical space reclamation is established.
- Next: none. Epic 0118 is closed with the limits above.

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

Outcome: Complete. The [M2 report](../../reports/0118-M2_Accepted_Loss_Recovery_Copy.md) records
current source ownership, the exact snapshot, preserved dependencies and human work, a disposable
package restore check, and matching prior API restart evidence. The package is on the active
store's volume, its physical APFS allocation and off-volume recovery are unknown, and uncertainty
records remain. No expiry condition is justified. No data was removed and no retention code changed.

## M3 — Bound the campaign-intermediate dependency decision

Keep the selected 0070 M5 50/50 training view as the exact campaign-intermediate family. Resolve the
known 0068 review-dependency gap with a bounded, read-only search. Use only plausible retained roots
named by the 0068 manifest, the M0/M2 reports, and existing recovery manifests: the canonical
reference root, the accepted-loss evidence root, and any other exact roots those records declare.
Do not search unrelated filesystems or worktrees. For any candidate, verify each expected state and
draft hash across all 24 recordings. Do not replace a missing historical file with a newer or
different file.

Use the applicable legacy schemas and readers to state the separate role of immutable reviewed
revision manifests/content, mutable reference state, and mutable review drafts. Explain which
training-view dependencies are established by the matching immutable content and which historical
selection or resumable review facts require the exact mutable bytes. Do not infer those mutable
facts from immutable reviewed content.

If exact state/draft dependencies are found, report their exact roots, hashes, ownership, and the
restore checks that they support. If any remain unavailable, record the precise search boundary and
missing hashes. Preserve the training view and every known review/recovery root. Do not claim full
recovery, exact regeneration, or an expiry condition. No deletion or expiry is authorized by this
milestone. Keep campaign command/output logs out of this contract unless evidence shows the same
writer and retention authority.

Checks: record every searched root and its source; verify candidate hashes against the frozen 0068
manifest; check the legacy state/draft schemas and the actual consumers that establish their role;
retain the existing 0071 reader and immutable-view verification as separate evidence. Do not perform
a recovery or regeneration action for missing mutable files. Run focused Markdown-link validation
and `git diff --check` after the plan and report updates.

Outcome: Complete as a bounded investigation. The [M3 report](../../reports/0118-M3_0070_Synthetic_Training_View.md)
selects the exact 0070 M5 50/50 view and verifies its immutable revision contents, scene receipts,
calibration links, model/run references, and restored reads. The declared-root search found the
canonical reference root absent and four recovery roots present. Each recovery root matches 7/24
expected state hashes and 0/24 expected draft hashes. The seven exact
states pass the state-only reader and their selected pointers match their immutable revisions; the
other 17 states and all drafts remain unavailable. Legacy schemas and readers establish that
immutable revision content cannot recover missing mutable state or draft work. Preserve the training
view and all available review roots; no full recovery, expiry, or deletion is authorized. Exact byte regeneration,
independent backup, live pins, off-volume recovery, and physical APFS allocation remain unknown.

## M4 — Implement selected lifecycle contracts

Implement only family contracts completed by M1, M2, and M3. Use explicit manifests and durable
receipts for any authorized removal. Preserve fail-closed behavior for unknown references. Verify
active and terminal work, concurrent readers and writers where relevant, interruption and restart,
restore or regeneration, and measured storage effects. Report logical removal, relocation, path
allocation, and physical space separately. If a safe policy cannot be established, record the limit
and close the affected scope without deleting data.
