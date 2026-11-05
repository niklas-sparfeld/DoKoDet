# Epic 0108 M10 migration reconciliation

Date: 2026-11-05

## Result

The local source snapshot is consistent, but it is not ready for activation. The refreshed
inventory found 1,903 resources and three blocking conflicts. No active store was changed, and no
runtime pointer or reader was switched.

The inventory snapshot digest is
`d85acd8ca675e3c6fade359359416bda1e3d49a436397d2e895a75c0052c4909`. The full recovery snapshot
is at `data/operations-recovery/0108-m10-20261105/operations`. A separate migration snapshot
contains the declared operation stores. The 51 referenced video files remain in a separate
read-only snapshot. Four source references whose recorded `.m4v` names were absent resolve to
`.mov` files with matching byte lengths and SHA-256 digests.

## Blocking findings

| Finding | Count | Evidence |
| --- | ---: | --- |
| Calibration revisions refer to missing detector revisions | 3 | Exact input revision IDs are absent from the operation snapshot. |

The missing inputs are `visible-cards-visible_cards-run-2c989303-99c-attempt-1` for IMG_0096,
`visible-cards-visible_cards-run-09ec3415-0ff-attempt-1` for IMG_0648, and
`visible-cards-visible_cards-run-a839023f-e3f-attempt-1` for IMG_0654. They are detector inputs to
the corresponding calibration revisions. No exact copies occur in the declared operation snapshot.
The IMG_0096 draft's missing calibration revision was recovered from an embedded scene copy. Its
calibration ID and digest match, so the inventory records that scene as evidence.

Migration-only readers now validate and retain known v1 proposal and visual-identity records and
historical calibration digests without changing their bytes or geometry. This cleared the prior
78 proposal-schema, 47 calibration-format, 20 draft-digest, and two dangling-calibration findings.
The plan still reports `activation_ready: false` because of the three missing detector inputs.
The isolated stage contains 1,903 resources and 32,219 file records. It verifies 2,064,827,899
staged bytes and keeps 51 referenced video files as digest-checked external references. It is not an
active store.

Other uncertainty records describe history fields that the old stores did not record and two
evidence-package references that need validation. They do not clear the blocking conflicts.

## Changes and verification

The inventory groups observation and analysis artifacts by their stored identity, parses processor
runs with the owning store, and checks observation IDs against each resource's own path. It retains
the source content schema and bytes for historical revision formats. Staging verified every copied
file against its declared digest and verified the external media references without copying them.

Focused checks passed:

- `mise exec -- uv run --project backend pytest backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py -q`
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`

## Required next work

Recover the three exact detector revisions from a backup, or document why they cannot be recovered
and choose an explicit archive representation for their unresolved input references. Rebuild the
plan from the same immutable snapshot after resolution. Do not activate while any blocking conflict
remains.
