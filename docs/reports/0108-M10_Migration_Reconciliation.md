# Epic 0108 M10 migration reconciliation

Date: 2026-11-05

## Result

The local source snapshot is consistent, but it is not ready for activation. The inventory found
1,903 resources and 147 blocking conflicts. No active store was changed, and no runtime pointer or
reader was switched.

The inventory snapshot digest is
`d85acd8ca675e3c6fade359359416bda1e3d49a436397d2e895a75c0052c4909`. The full recovery snapshot
is at `data/operations-recovery/0108-m10-20261105/operations`. A separate migration snapshot
contains the declared operation stores. The 51 referenced video files remain in a separate
read-only snapshot. Four source references whose recorded `.m4v` names were absent resolve to
`.mov` files with matching byte lengths and SHA-256 digests.

## Blocking findings

| Finding | Count | Evidence |
| --- | ---: | --- |
| Old proposed-scene revisions use `proposed-card-scene-data/v1`, which the current revision reader does not accept | 78 | These revisions have references from processor runs and other revisions. |
| Calibration revisions use unsupported historical formats | 47 | 44 use an unsupported card aspect ratio; 3 use an unsupported calibration-run schema. |
| Calibration drafts record digests that do not match their mapped calibration | 20 | The exact base calibration cannot be verified from the current draft reference. |
| Calibration references have no matching calibration revision in the snapshot | 2 | These references cannot be resolved to an exact input. |

The 125 invalid resources are referenced by 137 stored records: 77 processor runs, 29 pipeline
revisions, 20 calibration drafts, and 11 maintained drafts. Excluding these resources would break
recorded inputs or lineage. The two dangling calibration references are also unresolved. The plan
therefore reports `activation_ready: false`.

Other uncertainty records describe history fields that the old stores did not record and two
evidence-package references that need validation. They do not clear the blocking conflicts.

## Changes and verification

The inventory now groups observation and analysis artifacts by their stored identity, parses
processor runs with the owning store, and checks observation IDs against each resource's own path.
The migration staging tool can verify declared read-only media roots by digest without copying the
media into the staged package.

Focused checks passed:

- `mise exec -- uv run --project backend pytest backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py -q`
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`

## Required next work

Add migration readers and exact conversions for the referenced historical proposal and calibration
formats, or define an explicit archive representation that retains every original byte and exact
reference while keeping dependent results inspectable. Rebuild the plan from the same immutable
snapshot after those mappings exist. Do not activate while any blocking conflict remains.
