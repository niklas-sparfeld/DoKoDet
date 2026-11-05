# Epic 0108 M10 migration reconciliation

Date: 2026-11-05

## Result

The inventory found no blocking conflicts. It covers 2,086 resources and 34,414 files from the
operations, evidence-package, and recording-video snapshots. The staged package contains 2,086
resource records and verifies all 34,414 file records. It stages 2,692,535,595 bytes and retains
51 recording videos as digest-checked external references.

The inventory digest is
`c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`. The verified stage is at
`data/operations-recovery/0108-m10-20261105/migration-stage-accepted-loss`. The full recovery
snapshot is at `data/operations-recovery/0108-m10-20261105/operations`.

This result means the staged data is internally consistent and has no unresolved mappings. It does
not mean that runtime readers or writers use the staged package. No active store or runtime pointer
has changed. The workspace still uses the legacy stores for its content summary.

## Declared lost inputs

The user declared these three detector revision IDs lost. The inventory preserves each ID on the
dependent calibration revision, sets its target to null, and records `availability: lost`:

| Recording | Lost revision ID |
| --- | --- |
| IMG_0096 | `visible-cards-visible_cards-run-2c989303-99c-attempt-1` |
| IMG_0648 | `visible-cards-visible_cards-run-09ec3415-0ff-attempt-1` |
| IMG_0654 | `visible-cards-visible_cards-run-a839023f-e3f-attempt-1` |

The IMG_0096 draft's missing calibration revision is retained as an exact embedded scene copy. Its
calibration ID and digest match.

## Scope and evidence

| Root | Files | Resources or use |
| --- | ---: | --- |
| Operations | 32,168 | 1,903 resources, including revisions, runs, drafts, reviews, calibration, observations, and analysis |
| Evidence packages | 2,195 | 183 validated evidence packages |
| Recording videos | 51 | Digest-checked external references |

The inventory validates automated-run request digests, coordinator stage request digests, evidence
package manifests, analysis package references, and historical revision formats. It retains the
three processor-run IDs that have no separate run record inside their complete coordinator stage
records. The inventory marks these as `processor_run_record_not_separate` uncertainties.

Other uncertainties record 137 item histories and 13 intermediate draft histories that the old
stores did not retain. These do not remove current content or source IDs. The root `.DS_Store` file
is recorded as ignored filesystem metadata and remains in the staged file inventory.

The earlier stage at `data/operations-recovery/0108-m10-20261105/migration-stage` remains unchanged.
The accepted-loss stage has a plan digest that binds it to the three declared lost IDs. An
independent package verification passed.

## Changes and verification

The inventory now recognizes all files in each evidence-package directory, validates package
manifests, separates automated-run IDs from coordinator IDs, and retains embedded stage IDs without
inventing links to separate records. It also classifies the declared lost inputs and treats
filesystem metadata as recorded ancillary data.

Focused checks passed:

- `mise exec -- uv run --project backend pytest backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py -q` — 24 passed
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`

## Remaining M10 work

Import the verified resources into the runtime node and lineage stores. Then verify migrated
processor results, drafts, reviews, scenes, and analyses through the workspace, switch runtime
readers and writers, and verify that restart keeps the new store active. Keep the recovery and
staging packages until that cutover passes. M10 remains in progress.
