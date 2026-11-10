# 0117 supersession and exit

Date: 2026-11-10. Inspected implementation: `99b79d59`.

## Decision

Close 0117 as Superseded. Cancel its remaining execution loop. Deliver the catalog before more
workspace architecture work. Repair known recovery defects separately. This is a planning change;
it does not activate a storage format, revert code, or claim a performance improvement.

The original plan already contained 17 milestones. Twelve subsequent replans added storage and
transaction prerequisites. Repeated run resets allowed the same milestone to receive more
corrections without a new architectural decision. The latest run accepted zero of five milestones.
Local corrections reduced defects but did not bring the catalog or workspace cutover forward.

The decisive unnecessary dependency was M6b1a/M6b1b before catalog conversion. The actual catalog
stage status reads `ProcessorRunStore` through
`PipelineWorkspaceService._list_statuses_for_recordings`. It does not consume the new Job Manager
projection. A bounded catalog read does not require bounded job acceptance or queue mutation.
The replacement catalog must preserve processor-run status semantics rather than substitute job
state. Job mutation cost remains visible in qualification, but is not a new optimization target.

## Delivery order and boundaries

1. [0119 — Pipeline recovery defects](../plans/5-closed/0119-Pipeline_Recovery_Defects.md): two
   milestones to close the known cancellation/link gaps and retain the restart regressions.
2. [0120 — Recording catalog performance](../plans/2-ready/0120-Recording_Catalog_Performance.md):
   bounded metadata reads and one real `/recordings` cutover. No recording HEAD adoption, job
   scheduler rewrite, processor-input migration, or startup optimization.
3. [0121 — Current workspace reads](../plans/1-backlog/0121-Current_Workspace_Reads.md): deferred
   workspace delivery. Use existing exact selections; separate explicit history loading. Audit
   the unused aggregate recording HEAD before deciding its disposition. Do not make a full
   selection-authority migration a condition of faster reads.

0119 owns defects in the integrated job/pipeline code even if they predate the queue change.
0120 and 0121 fix defects introduced by their own implementations. A newly discovered defect in
another subsystem gets a separate epic with a reproducer and a narrow dependency only if it blocks
the selected workflow. Do not import general cleanup, acceptance optimization, or lifecycle work.

## Integrated work: keep, freeze, remove

| Work at supersession | Disposition | Owner and check |
| --- | --- | --- |
| M0 measurements and hard fixture | Keep immutable evidence; no current speed claim | 0120 compares the same corpus and records any baseline drift |
| Exact node publication authority and transaction recovery, M4a/M4b | Keep | 0120/0121 exercise exact reads with ancestry discovery disabled |
| History authority, ordered index, source outboxes and paging, M5 | Keep; reuse for explicit history | 0121 verifies independent review switching, paging and restart |
| Snapshot/recording HEAD store and experimental working editor, M2/M3/M4c | Freeze; do not convert more producers | 0121 M0 inventories actual consumers and retained state; M3 removes unused runtime exposure if no consumer requires it |
| Job authority and active-job SQLite index, M6a/M6b1 | Keep; no new catalog dependency | 0119 runs journal/queue regressions; jobs APIs retain ownership |
| Integrated queue authority and pipeline recovery changes, M6b1a | Keep provisionally; repair known defects | 0119 requires persisted restart and normal execution evidence |
| Unimplemented bounded acceptance, M6b1b | Cancel | No implementation or new epic without a measured user-workflow problem |
| Disabled job-page submission, M6b | Keep disabled; remove obsolete leftovers with consumer audit | 0121 M3; do not enable it to satisfy a discarded contract |
| Original M9–M15 processor/publication migration and startup program | Cancel as delivery requirements | Preserve existing exact input and selection behavior; new measured problems need separate scope |

## Revert assessment

Do not bulk-revert 0117 or the M6b1a commit range. The queue and active-job index now share the
versioned job journal and SQLite transaction. A bulk revert is another runtime storage conversion,
and would discard valid recovery fixes. No inspection evidence establishes that as the smaller
safe change. 0119 therefore makes bounded repairs in place.

If the finite 0119 recovery matrix exposes a broken authority design rather than a local defect,
stop that epic and record a selective rollback proposal: exact commits and dependent callers,
persisted schema conversion, retained job/intent/queue inventory, disposable rehearsal, and restart
proof. Do not revert a journal reader independently of its writer or delete retained jobs.

Unused experimental recording-state APIs may be removed by 0121 after a consumer and data audit.
Remove runtime wiring and obsolete tests/contracts together; retain user data and exact historical
addressability. This is selective removal, not permission to discard the whole 0117 implementation.

## Execution control

No new worker loop starts with this planning commit. Each replacement starts at M0 under the normal
single-milestone workflow. No automatic reset of exhausted correction limits. Two successive
attempts that expose prerequisites or fail to reduce scope require a stop and a concrete scope
decision. Do not add nested milestone suffixes or displace qualification beyond a run limit.
If a planned milestone proves too large, revise its epic before implementation and keep the
user-authorized run bound. Do not expand a catalog or workspace acceptance criterion into global
write-path optimization. Record latency and write overhead separately.
