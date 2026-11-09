# Epic 0118 M2: accepted-loss recovery copy

Date: 2026-11-09

## Result

The accepted-loss migration stage still matches its recorded snapshot and current active node
store. It remains necessary recovery evidence. Do not expire or remove it. No safe expiry date or
bounded recovery window is established.

## Current root and owner

The selected checkout does not contain `data/operations-recovery`. The canonical main-worktree
source is present at
`/Users/niklas.sparfeld/Developer/doko_detector/data/operations-recovery/0108-m10-20261105/migration-stage-accepted-loss`.
Its owner uid is 501. Its filesystem device matches the active
`data/operations/pipeline-nodes` root and both are owned by uid 501. This confirms the local root,
not an independent backup. The accepted-loss package remains on the same volume as its active
replacement.

`scripts/verify_0115_recovery.py` passed against the main worktree data and runtime roots. The
current accepted package has 2,086 resources and 34,414 manifest file records. Its snapshot digest
is `c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`, and its plan digest is
`9bf7bd2979ff3d20026e8509ed6f41b172e1fba8c4aab1002e395fd0bb68febc`. The active node-store
manifest is 27,654 files and 1,700,808,685 logical bytes, digest
`7152b452c98bec2b0e512f8a5e5a9126f861566107fe242b635cfc01989100c7`. These equal the prior M1
verification values.

## References, pins, and human work

The M9 uncertainty audit for this exact package snapshot found 1,565 candidate resources (835
revisions, 594 runs, and 136 selections) with zero unresolved candidate references. It mapped all
156 uncertainty records. The 137 item-history records and 13 calibration intermediate-history
records remain in the package. Three explicitly lost revision IDs are referenced only by
non-candidate calibration revisions; candidate resources have no references to those losses. Keep
the three tracked automated-run records identified by the audit. Do not treat a clean candidate
reference graph as proof that the unresolved histories are disposable.

The current recovery verifier matched all 150 maintained-draft, independent-review, and
calibration-draft resources to 441 files and 145,675,545 logical bytes in the active node store.
Their embedded bytes and staged bytes match. M1 previously restored a selected review and the
IMG_0097 run chain into a disposable service root, verified exact revision and run reads, and
restarted the API twice with the same snapshot and node-store digests. It also verified review
decisions and the selected IMG_0637 dependency chain. M2 did not repeat that API exercise; its
package and active-store digests are unchanged from that recorded rehearsal. These checks cover
selected dependencies, not a full-corpus restore.

The dependency roots include the active node store, source recordings, model source, selected
runtime bundle, exact migrated revisions and runs, and retained review/calibration records. The
M1 recovery report records the tested IMG_0097 run chain, selected revision IDs, a 50-item review,
and preserved draft decisions. The 0115 M9 audit also confirms candidate references resolve to
preserved package resources. Current process pins outside these recorded roots were not inspected.

## Size and restore procedure

For the current package directory, a file walk measured 36,453 files and 2,723,760,411 logical
bytes. `du -sk` reported 2,737,828 KiB of path allocation. Summed `st_blocks` reported
2,803,535,872 allocated bytes. These are different accounting views; APFS shared extents and
unique physical allocation were not measured. The clone and source are on the same device, so the
clone's allocation does not establish physical space required for an independent restore.

The M2 disposable rehearsal made an APFS clone at `/tmp/0118-m2-recovery-stage` and ran the
package verifier against the clone. It passed with the same snapshot, 2,086 resources, 34,414
manifest file records, and `activation_ready=true`. The separate current-root recovery verifier
confirmed the active node store and retained review bytes. The M1 API restart evidence above
covers reads after restoration for the same exact snapshots. No full package copy or full-corpus
service restore was attempted. The temporary clone is disposable and is removed after this report.

## Retention decision and limits

The creator is the 0115 lineage migration and recovery tooling. The package is consumed by the
recovery verifier and explicit migration/import readers. The active node store is the replacement
for migrated pipeline authority, but it does not erase the package's role as recovery evidence for
the preserved histories and recorded losses. No independent off-volume copy is confirmed.

No expiry condition is justified. Keep the package until a separately verified recovery source
covers its exact dependencies and human work, all unresolved history has an explicit disposition,
and the owner declares a recovery window. This is a prerequisite description, not an expiry date
or removal authorization. Do not apply cache expiry rules. The 0115 M14 storage map and M15 closure
report remain historical records and were not changed.

## Checks

- `mise exec -- uv run --project backend python scripts/verify_0115_recovery.py --data-root /Users/niklas.sparfeld/Developer/doko_detector/data --runtime-root /Users/niklas.sparfeld/Developer/doko_detector/.runtime --output /tmp/0118-m2-current-verification.json` — passed.
- APFS clone of the exact recovery stage followed by `dokodetector_backend.lineage_migration_apply._verify_package` — passed; same snapshot digest.
- Prior matching-snapshot API restore and restart evidence: `docs/reports/0115-M1_Recovery_and_Cleanup_Plan.md` and its `selected-chain-validation.json` artifact.
- `git diff --check` and changed Markdown link validation — passed.

No authoritative recovery or active data changed.
