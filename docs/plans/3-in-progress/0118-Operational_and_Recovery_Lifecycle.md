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
| M2 | Specify one exact recovery-copy family's retention and restore contract, or record why no safe bounded policy is justified | Complete; [report](../../reports/0118-M2_Accepted_Loss_Recovery_Copy.md) |
| M3 | Specify one exact campaign-intermediate family's retention and restore contract; keep it separate from recovery copies | Complete; [report](../../reports/0118-M3_0070_Synthetic_Training_View.md) |
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

- Run: requested 4 milestones; completed 4; 0 remain in this run. M0–M4 are planned; M4 is
  outside this run's authorization.
- Completed: M0 inventory and family selection; M1 managed-job log audit; M2 accepted-loss
  recovery-copy audit; M3 0070 synthetic training-view audit. See the
  [M0 report](../../reports/0118-M0_Lifecycle_Family_Inventory.md),
  [M1 report](../../reports/0118-M1_Managed_Job_Log_Audit.md),
  [M2 report](../../reports/0118-M2_Accepted_Loss_Recovery_Copy.md), and
  [M3 report](../../reports/0118-M3_0070_Synthetic_Training_View.md).
- Changes: M1 found an existing 1,000-entry rolling window, no per-entry byte bound, and no
  independent log restore source. It freezes no new expiry or size policy and preserves all log
  files. M2 revalidated the accepted-loss package in the main worktree and a disposable APFS clone.
  Its snapshot and active node-store digests match prior recovery evidence. The source and active
  store share one volume; off-volume recovery and physical APFS reclamation remain unknown. The 156
  uncertain histories and three declared-lost revisions remain preserved, so M2 sets no expiry.
  M3 selected the 0070 M5 50/50 synthetic training view. The 0071 cluster-crop materializer reads
  it, and 0070 run and bundle references remain. Two fresh-process reads of a disposable APFS clone
  validated all 537 synthetic rows and scene receipts against the frozen manifest. Its exact
  source, review, and receipt roots remain protected. Byte regeneration and independent backup are
  unverified. No expiry is justified.
- Checks: M1's `mise exec -- uv run --project backend pytest -q backend/tests/test_job_recovery.py`
  passed (13 tests). M2's `mise exec -- uv run --project backend python
  scripts/verify_0115_recovery.py --data-root /Users/niklas.sparfeld/Developer/doko_detector/data
  --runtime-root /Users/niklas.sparfeld/Developer/doko_detector/.runtime --output
  /tmp/0118-m2-current-verification.json` passed with 2,086 resources, 34,414 manifest files,
  and snapshot `c8979c9a…`. A disposable APFS clone passed `_verify_package` with the same digest.
  M1's matching-snapshot API restore and restart reads remain the API-level rehearsal evidence.
  M3's two disposable-reader processes returned 537 rows with matching COCO and manifest digests.
  `git diff --check` and changed-link checks passed. No authoritative data changed.
- Decisions and limits: M3 sets no expiry or removal policy. Current configured
  `data/operations/jobs` is absent in this checkout.
  The active process root, live job set, log sizes, pins, expiry authority, and independent recovery
  source remain unknown. The existing rolling window is code behavior, not evidence that older
  entries are disposable. Off-volume recovery and physical APFS allocation remain unknown.
- Next: M4 may implement only policies justified by M1–M3. The 0070 view policy preserves the
  materialization and its dependencies. M4 is outside this run. Run count: requested 4; completed
  4; 0 remain.

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

## M3 — Specify campaign-intermediate retention

Select one exact campaign materialization family. Record its creator, campaign and source manifests,
dependency and pin roots, reconstructability, expiry condition, and restore or regeneration
procedure. Keep campaign command/output logs out of this contract unless evidence shows the same
writer and retention authority. Keep compact provenance when removing reproducible materializations.

Checks: rehearse restore or regeneration in disposable storage. Verify exact source and review
dependencies, model/run references, and restart reads. Record logical bytes, path allocation, and
physical allocation separately when available. If one campaign contains independent writer or
recovery contracts, split its specification before implementation.

Outcome: Complete. The [M3 report](../../reports/0118-M3_0070_Synthetic_Training_View.md) selects
the exact 0070 M5 50/50 synthetic training view. It records its creator, frozen source and review
manifests, scene receipts, 0070 run and bundle references, the 0071 consumer, storage measurements,
and a disposable clone rehearsal through the actual 0071 reader in two fresh processes. The view
remains a consumer input. Exact byte regeneration, live pins, off-volume recovery, and physical
APFS allocation remain unknown. No expiry or deletion is authorized.

## M4 — Implement selected lifecycle contracts

Implement only family contracts completed by M1, M2, and M3. Use explicit manifests and durable
receipts for any authorized removal. Preserve fail-closed behavior for unknown references. Verify
active and terminal work, concurrent readers and writers where relevant, interruption and restart,
restore or regeneration, and measured storage effects. Report logical removal, relocation, path
allocation, and physical space separately. If a safe policy cannot be established, record the limit
and close the affected scope without deleting data.
