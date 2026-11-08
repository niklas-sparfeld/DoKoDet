# Epic 0115 M9: tracked pipeline cutover

Date: 2026-11-08
Result: **M9 cutover completed. No pipeline payload was deleted.**

## Frozen activation snapshot

The activation snapshot is the exact M6 inventory subset at revision `b294ffac4b37acc233a212e079ae094b44610888`: 31,521 files and 1,701,015,169 bytes in `revisions/**`, `runs/**`, and `selections/**`. The selected candidate manifest digest is `b275daba9c75b3d3deb047a61f8b6274acca10f370391eeeb4ba75abbc780c0e`. Every current index entry and working file matched the frozen M6 path, mode, and Git blob identity. The 15 `automated-runs/**` files (88,395 bytes) are outside this snapshot and remain tracked.

The accepted-loss recovery package contains matching pipeline roots. Its verifier passed with migration snapshot `c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`. All 31,521 candidate files (1,701,015,169 bytes) matched the package byte for byte before and after cutover. The package records 835 revisions, 594 runs, and 136 selections. It also records 156 unresolved migration history items. These records and the full source files remain in the recovery package; M9 does not resolve or discard their histories.

All candidate blob IDs match a fresh shallow GitHub clone at `21a1146b0e7ca3bcbc702dc358437b6609ecf482`. Its sparse checkout restored all 31,521 candidate files (1,701,015,169 bytes), and every restored blob matched M6. The independent restore took 33.56 seconds. The local accepted-loss package also matches every candidate file. Git history was not rewritten.

## Reader and writer audit

The application composes its pipeline stores from the configured `settings.operations_root`. With `DOKO_STORAGE_ROOT`, revisions, runs, and node selections use the explicit worktree root. The test copies one exact chain into disposable storage and points `DOKO_REPOSITORY_ROOT` to an empty checkout. It asserts the checkout has no `data/operations/pipeline/revisions`, `runs`, or `selections` paths before the API workflow starts. The API test creates its node from the exact selected visible-card revision loaded from the copied chain, edits one geometry point, saves a review for that output's event, and reads the saved revision and decision after restart. It also re-reads all five legacy revisions, both run edges, and both selections and confirms their fingerprints did not change. This ties the edit/review/restart to the selected output; it does not use a synthetic event node.

The remaining direct readers of repository pipeline paths are explicit migration, inventory, or repair tools: `storage_consolidation.py`, `visible_card_data_migration.py`, `lineage_migration_inventory.py`, and `repair_0100_m5.py`. The runtime has no second implicit read from these checkout paths when an isolated root is set. If the setting is absent, the M7 repository-relative defaults remain in force; M9 does not silently change that documented behavior. New isolated roots do not receive the operator corpus by default.

The M6-selected `IMG_0097` chain binds five exact revisions, two runs, and the event and visible-card selections in [the chain receipt](0115-M9_Pipeline_Cutover.artifacts/selected-chain.json). The fixture has 116 files and 8,800,068 bytes. Its file digests match the frozen M6 entries. The selected visible-card content digest is `ac0cebdf2eb3d53921738c6a818fc252e5cb63929e25efa8ee439ab2b790e765`, the same digest returned for the exact selected revision by the M1 API recovery check. M1 also preserves the migrated 0097 decisions (9 accepted, 40 pending, 1 unusable; 40 scene reviews pending) through restart. M1's event payload digest differs from the current M9 legacy `cardeventnet-events-img_0097` payload; M1 evidence supports the visible-card review and its own migrated event state, not byte identity for that candidate event payload. The M9 test now directly exercises edit/review/restart on the exact selected visible-card content while old checkout paths are absent.

## Uncertainty and dependency audit

The [uncertainty dependency audit](0115-M9_Pipeline_Cutover.artifacts/uncertainty-dependency-audit.json) maps every one of the 156 accepted-loss package uncertainty records to its resource and exact relative identity. The 137 item-history records belong to 11 independent reviews and 126 maintained drafts. The 13 intermediate-history records belong to calibration drafts. These 150 resources have explicit references to revisions or runs in the selected pipeline family. The three `processor_run_record_not_separate` records map to three separate `automated-runs/coordinator-runs/*.json` files; all three files are still tracked, as are all 15 automated-run files. The audit resolves all candidate-family references to package resources, with zero unexplained references.

The other three records are declared lost calibration inputs: their calibration revisions name missing visible-card revision IDs `visible-cards-visible_cards-run-2c989303-99c-attempt-1`, `visible-cards-visible_cards-run-09ec3415-0ff-attempt-1`, and `visible-cards-visible_cards-run-a839023f-e3f-attempt-1`. The migration manifest records each loss explicitly. No selected-family revision, run, or selection references these IDs. The three calibration revision files and all uncertainty records remain in the accepted-loss package. This audit did not restore, edit, or delete operator data. The M6 condition for an unresolved dependency does not apply to the selected candidate paths: each candidate reference resolves, and the three known missing inputs have no candidate consumer. No candidate path was restored to tracking.

## Cutover and checkout protection

M9 removed only the three selected roots from the main Git index and added ignore rules for them. It left every local file in place. Post-cutover checks found zero tracked candidate paths, the exact 31,521 local files, and all 15 automated-run records tracked. This changes tracking; it does not reclaim local file bytes or shared Git history.

The two detached checkouts remain unchanged at `0f46b9ad2` and `b7ebf2390`. Before any future merge, save their candidate trees with `git archive <current-head> -- data/operations/pipeline/revisions data/operations/pipeline/runs data/operations/pipeline/selections`, merge, then extract the archive and compare all files with the M6 inventory. I tested this full index-drop, candidate-removal, and archive-restore sequence in disposable copies of both exact checkout revisions. Each restored 31,521 files and all 1,701,015,169 bytes with zero blob mismatches; all 15 automated-run records stayed tracked. The test archives and receipt hashes are in [the protection record](0115-M9_Pipeline_Cutover.artifacts/protection-and-restore.json). No live checkout was merged or changed.

The M1 recovery verifier passed after cutover with the same migration package, node-store digest, review records, recording, and model fingerprints. The candidate local copies still match the M6 Git blob IDs. No human review or current model bundle changed.

## Measurement

M9 repeated the frozen setup in two clean worktrees at commit `b7098c782`. Create-to-ready took 16.85 seconds in A and 15.71 seconds in B, against the 30-second target. Each checkout used 1,693,656 KiB; each explicit state root used 40 KiB. The 1,693,696 KiB ready total is 403,456 KiB below the 2 GiB target. These are path allocations. Shared `.git` bytes and APFS clone accounting are separate.

The combined setup and selected API tests passed in both worktrees. Worktree A also ran the storage contract test with a fresh second state root. Worktree B's 13-file state manifest did not change. After cutover, zero intake recording paths and zero pipeline revision/run/selection paths are tracked; 15 automated-run idempotency paths remain tracked. The complete measurement receipt is in [ready-worktree-measurements.json](0115-M9_Pipeline_Cutover.artifacts/ready-worktree-measurements.json).

## Checks

- `scripts/verify_0115_recovery.py` before and after cutover: passed; exact snapshot and retained records match.
- Full candidate inventory: 31,521 working Git blob hashes match M6; 31,521 files match the accepted-loss recovery package byte for byte.
- Selected chain API and restart test: passed with old checkout roots physically absent; edit and review use the exact selected visible-card revision. The test re-reads exact revisions, run edges, and selections after restart.
- Uncertainty dependency audit: passed; all 156 records mapped, candidate references have zero unresolved targets, and all three automated-run records remain tracked.
- Two detached-worktree archive/restore rehearsals: passed; each restored all candidate paths exactly and retained all 15 automated-run files.
- `pytest` for pipeline API, node selection, lineage writer, node store, M9 cutover, worktree storage, and operator import: passed, 38 tests.
- Correction rerun: `cd backend && uv run pytest tests/test_0115_pipeline_cutover.py tests/test_pipeline_api.py tests/test_pipeline_run_api.py tests/test_pipeline_store.py tests/test_pipeline_node_edit_api.py tests/test_pipeline_node_store.py tests/test_pipeline_node_selection_store.py tests/test_worktree_storage_contract.py tests/test_operator_corpus_import.py -q`: passed, 63 tests. Ruff check and format check for the changed M9 test passed.
- `uv run --project backend python scripts/verify_0115_recovery.py --data-root data --runtime-root .runtime --output /tmp/0115-m9-correction-recovery-verification.json`: passed; snapshot `c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`, 2,086 resources, and 150 retained review/draft resources matched.
- Ruff check, Ruff format check, and `git diff --check`: passed after import and format fixes.
- Markdown path and anchor links in the changed plan, board, and report: passed (219 links).

One supplemental API test attempt reused worktree A's already populated state root and hit the expected existing-node conflict. The rerun used a fresh root and passed; the registered M9 setup test runs each clean worktree with its own fresh root.
