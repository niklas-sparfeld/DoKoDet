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

The import is active at `data/operations/pipeline-nodes`. It contains 835 validated processor data
nodes, 594 processor runs, and five analysis runs. The imported analysis records retain exact
observation revisions, evidence-package digests, and input/result artifact digests. The processor
writer loads the imported legacy-revision map, so new runs reuse migrated nodes.

The importer also writes all 136 migrated selections to
`data/operations/pipeline-nodes/.migrated-selections`. Each non-empty selection points to the exact
imported node and revision. An audit matched every selection pointer to the legacy map and checked
that each target node has the expected recording and content type. The workspace still reads its
selection state from the legacy store; runtime reader cutover remains open.

The graph store also preserves the 126 maintained drafts, 13 calibration drafts, and 11
independent review packages under `.migrated-records`. Each record contains the original staged file
bytes as Base64 with its SHA-256 digest and the mapped node revision for each retained revision
reference. An audit compared every stored file byte for byte with the verified stage and checked the
mapped references. Workspace readers still use the legacy stores.

The existing operations stores remain in place. Workspace summaries, selections, maintained
drafts, calibration drafts, and independent review records still use their existing readers. M10
is not complete until the draft and review readers use the migrated records and restart checks
confirm the intended content and decisions. The recovery snapshot and verified migration package
remain available for recovery.

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
independent package verification passed. The active node store has
`data/operations/pipeline-nodes/.migration-import.json` and
`data/operations/pipeline-nodes/.legacy-revision-map.json`, both bound to the snapshot digest.

The importer changes v1 event labels to the current `card_state_changed` content contract and
stores the original labels in revision metadata. It upgrades the retained v1 scene and identity
contracts for node validation. The original bytes remain in the staging package and recovery
snapshot.

## Changes and verification

The inventory now recognizes all files in each evidence-package directory, validates package
manifests, separates automated-run IDs from coordinator IDs, and retains embedded stage IDs without
inventing links to separate records. It also classifies the declared lost inputs and treats
filesystem metadata as recorded ancillary data.

Focused checks passed:

- `mise exec -- uv run --project backend pytest backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py -q` — 24 passed
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/lineage_migration_inventory.py backend/src/dokodetector_backend/lineage_migration_apply.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_lineage_migration_apply.py`
- `mise exec -- uv run --project backend pytest backend/tests/test_lineage_migration_import.py backend/tests/test_pipeline_lineage_writer.py -q` — 3 passed
- Ruff check and format check passed for the importer, lineage writer, and focused tests.
- The local import reported 835 nodes, 594 processor runs, and five analysis runs. The active
  writer loaded all 835 legacy revision mappings and resolved a migrated event revision to its
  imported node.
- `mise exec -- uv run --project backend pytest backend/tests/test_lineage_migration_import.py -q` — 1 passed
- Ruff check, Ruff format check, and `git diff --check` passed for the selection importer and test.
- The local importer reported 136 selections. An audit verified every non-empty pointer against
  the imported legacy map and its target node manifest.
- The local importer reported 126 maintained drafts, 13 calibration drafts, and 11 independent
  review packages. An audit verified all 441 stored files byte for byte and checked retained
  revision references against the legacy map.

## Remaining M10 work

Switch workspace summaries, selections, maintained drafts, calibration drafts, and independent
reviews to the imported nodes and review records. Verify results, coverage, exact inputs, and
restart behavior through the workspace. Keep the recovery and staging packages until those checks
pass. M10 remains in progress.
