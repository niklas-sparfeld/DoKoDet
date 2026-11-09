# Epic 0118 M0: lifecycle family inventory

Date: 2026-11-09

## Result

M0 mapped managed-job logs as an M1 audit target, selected one exact recovery-copy family for M2,
and identified campaign intermediates as a separate M3 specification. It changed no stored data.
The family map distinguishes
current checkout observations from dated 0115 measurements. Current ignored job and recovery roots
are absent from this detached checkout, so their current size, active pins, and live recovery state
are unknown.

## Exact family map

| Family and exact path pattern | Writer and reader | Retention authority | Recovery source and evidence | Current observation and decision |
| --- | --- | --- | --- | --- |
| Managed-job logs: `<operations_root>/jobs/<job-id>/logs.json`; default operations root is `data/operations` | `JobPersistence.append_log` writes; `JobPersistence.logs` reads. The job API exposes paged log reads. `JobManager` sets the `jobs/` root. | No expiry authority or pin model found. Keep-all is the current safe rule; the operations-root owner must authorize a future change. | No independent restore source is known. `JobManager` repairs intents, queue, and job state but does not reconstruct a deleted `logs.json`. Tests cover job/queue recovery, but no log restore path was found. | M1 is an audit target, not a selected retention family. In this checkout `data/operations/jobs` is absent; size, file count, active jobs, and backup status are unknown. M1 can conclude that no safe bounded policy is justified if it cannot establish an exact recovery source. No log deletion is authorized. |
| Accepted-loss migration recovery stage: `data/operations-recovery/0108-m10-20261105/migration-stage-accepted-loss/` | 0115 migration/recovery tooling creates and verifies the package; `scripts/verify_0115_recovery.py` and migration readers consume it. | 0115 accepted-loss snapshot and migration evidence govern its retention. Active node records, preserved reviews/calibrations, unresolved declared losses, and exact references remain protected. | This package is the tested recovery source. M15 verified 2,086 migration resources and 34,414 file records against snapshot digest `c8979c9a…`; M1 rehearsed selected API restores from it in disposable storage. Both reports state the copy is on the source volume. | Selected as one exact M2 recovery-copy candidate, conditional on rechecking current ownership and dependencies. The root is absent in this checkout. The 0115 M0 historical parent tree measured 24.1 GiB / 142,746 files; this is not a current size or safe-removal quantity. No expiry is authorized. |
| Campaign command logs and copied training materializations: individual campaign-owned roots, not one shared root | `cardevent_campaign.py` and `table_evidence_campaign.py` create per-campaign `logs/commands.json` and named command output logs. Materialization writers include `rfdetr_segmentation_materialization.py`, `rfdetr_pose_derived_materialization.py`, and campaign-specific materializers; validators and training entry points read manifests and payloads. | Each campaign's frozen selection, run, bundle, review, and dependency manifests govern retention. No shared expiry authority was found. | A valid recovery source depends on each materialization's source manifest, split, digest, exact source inputs, and any active model/run references. Some completed runs retain distinct checkpoints and manifests; reconstructability is not established for all inputs. | M3 must select one exact campaign family before policy work. Current `data/model-campaigns` is 16,808 KiB (path-level `du -sk`), but it is not the materialization root and includes many campaign records. `.runtime` is 402,944 KiB total, mixed with active runtime assets and caches. No exact family-level current size or complete pin inventory is established. Do not treat campaign logs as managed-job logs. |

## Bounded source evidence

- `backend/src/dokodetector_backend/job_persistence.py` defines append and paged read behavior for
  `logs.json`; `job_store.py` places the store under `operations_root/jobs`.
- `backend/src/dokodetector_backend/job_recovery.py` documents restart recovery for jobs and queue
  records. `backend/tests/test_job_recovery.py` covers those paths. Neither defines log restoration.
- `operations/src/doko_operations/cardevent_campaign.py` and
  `table_evidence_campaign.py` write distinct command logs and stdout/stderr files beneath
  campaign roots. Materialization modules and their validators have separate exact writers and
  readers, so these are not one retention family.
- The 0115 M14 map and M15 report are the source of the recovery package's historical verification.
  M15 explicitly says the recovery copy is on the same volume and off-volume recovery is unverified.
- The 0115 M4 report records distinct completed 0070 experiment outputs and an active 0092 M4 bundle
  reference. These dependencies prevent a generic age- or completion-based campaign expiry rule.

## Current size and physical-allocation limits

Read-only checks in this checkout returned:

```text
data/operations/jobs                 absent
data/operations-recovery              absent
data/operations/pipeline              120 KiB
data/model-campaigns                  16,808 KiB
.runtime                              402,944 KiB
```

The runtime total is mixed; it is not attributed to campaign materializations. The historical
0115 sizes refer to a different checkout and date. `du` reports path allocation, not unique APFS
allocation. Shared clones, physical reclamation, and off-volume backup were not measured. No
current active pin or exact recovery copy was inferred from missing roots.

## Decision and next work

M1 audits managed-job logs. It must inspect the actual configured operations root and distinguish
active jobs from terminal jobs. It must identify a real restore source and test it before any
retention policy. If logs have no independent recovery source, keep them and record the policy limit.

M2 owns only the accepted-loss migration stage. Recheck current snapshot identity, exact active
references, retained human work, restore source, and a disposable restore before specifying expiry.
The 24.1 GiB historic parent-tree size is not permission to remove that tree.

M3 owns campaign intermediates as a family separate from command/output logs. First choose one
campaign and exact materialization root. Preserve pinned model bundles, review work, source
recordings, and dependencies. Split campaign logs into another milestone if their owner or
recovery contract differs.

No data was deleted or expired. Current size and live recovery unknowns remain open acceptance
limits for the next milestones.

## Checks

- Source cross-reference: checked `JobPersistence`, `JobManager`, job recovery tests, campaign
  command log writers, materialization writers, 0115 M14/M15, and the 0115 M4 runtime report.
- Root inspection: read-only `ls`, `find`, and `du -sk` for the exact roots listed above; missing
  roots and mixed runtime accounting are recorded explicitly.
- Markdown links: validated epic, board, and report links after the epic moved to In Progress.
- `git diff --check`: passed.
