# Epic 0115 M9: tracked pipeline cutover

Date: 2026-11-08
Result: **M9 cutover completed. No pipeline payload was deleted.**

## Frozen activation snapshot

The activation snapshot is the exact M6 inventory subset at revision `b294ffac4b37acc233a212e079ae094b44610888`: 31,521 files and 1,701,015,169 bytes in `revisions/**`, `runs/**`, and `selections/**`. The selected candidate manifest digest is `b275daba9c75b3d3deb047a61f8b6274acca10f370391eeeb4ba75abbc780c0e`. Every current index entry and working file matched the frozen M6 path, mode, and Git blob identity. The 15 `automated-runs/**` files (88,395 bytes) are outside this snapshot and remain tracked.

The accepted-loss recovery package contains matching pipeline roots. Its verifier passed with migration snapshot `c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`. All 31,521 candidate files (1,701,015,169 bytes) matched the package byte for byte before and after cutover. The package records 835 revisions, 594 runs, and 136 selections. It also records 156 unresolved migration history items. These records and the full source files remain in the recovery package; M9 does not resolve or discard their histories.

All candidate blob IDs match the `origin/main` tree at `21a1146b0e7ca3bcbc702dc358437b6609ecf482`. A fresh GitHub clone attempt returned `Repository not found`, so this report does not claim a current off-volume restore. The verified accepted-loss package is on the same volume. Git history was not rewritten.

## Reader and writer audit

The application composes its pipeline stores from the configured `settings.operations_root`. With `DOKO_STORAGE_ROOT`, revisions, runs, and node selections use the explicit worktree root. The new test copies one exact chain into a disposable root, reads its revisions, runs, and selections there, and confirms the application root differs from the checkout's `data/operations` path. It then edits a node and saves a review through the current APIs and reads both after restart.

The remaining direct readers of repository pipeline paths are explicit migration, inventory, or repair tools: `storage_consolidation.py`, `visible_card_data_migration.py`, `lineage_migration_inventory.py`, and `repair_0100_m5.py`. The runtime has no second implicit read from these checkout paths when an isolated root is set. If the setting is absent, the M7 repository-relative defaults remain in force; M9 does not silently change that documented behavior. New isolated roots do not receive the operator corpus by default.

The M6-selected `IMG_0097` chain binds five exact revisions, two runs, and the event and visible-card selections in [the chain receipt](0115-M9_Pipeline_Cutover.artifacts/selected-chain.json). The fixture has 116 files and 8,800,068 bytes. Its file digests match the frozen M6 entries. The API test confirms the exact run input/output edges, edits a current node, saves an accepted review, restarts the app, and verifies the node content, review decision, revisions, and run edges again. Earlier M1 checks also preserve the 0097 migrated review decisions (9 accepted, 40 pending, 1 unusable; 40 scene reviews pending) through restart.

## Cutover and checkout protection

M9 removed only the three selected roots from the main Git index and added ignore rules for them. It left every local file in place. Post-cutover checks found zero tracked candidate paths, the exact 31,521 local files, and all 15 automated-run records tracked. This changes tracking; it does not reclaim local file bytes or shared Git history.

The two detached checkouts remain unchanged at `0f46b9ad2` and `b7ebf2390`. Before any future merge, save their candidate trees with `git archive <current-head> -- data/operations/pipeline/revisions data/operations/pipeline/runs data/operations/pipeline/selections`, merge, then extract the archive and compare all files with the M6 inventory. I tested this full index-drop, candidate-removal, and archive-restore sequence in disposable copies of both exact checkout revisions. Each restored 31,521 files and all 1,701,015,169 bytes with zero blob mismatches; all 15 automated-run records stayed tracked. The test archives and receipt hashes are in [the protection record](0115-M9_Pipeline_Cutover.artifacts/protection-and-restore.json). No live checkout was merged or changed.

The M1 recovery verifier passed after cutover with the same migration package, node-store digest, review records, recording, and model fingerprints. The candidate local copies still match the M6 Git blob IDs. No human review or current model bundle changed.

## Measurement

M5 measured a ready worktree at 18,670,260 / 18,673,008 KiB, with checkouts at 16.92 GiB and a 2 GiB target gap of 14.92 GiB. M9 repeats the frozen setup in two clean worktrees after cutover. The results, remaining tracked families, and updated target gap are recorded below after both setup runs.

## Checks

- `scripts/verify_0115_recovery.py` before and after cutover: passed; exact snapshot and retained records match.
- Full candidate inventory: 31,521 working Git blob hashes match M6; 31,521 files match the accepted-loss recovery package byte for byte.
- Selected chain API and restart test: passed; exact five revisions, two run edges, selections, edit, and review persisted.
- Two detached-worktree archive/restore rehearsals: passed; each restored all candidate paths exactly and retained all 15 automated-run files.
- `pytest` for pipeline API, node selection, lineage writer, node store, M9 cutover, worktree storage, and operator import: passed, 38 tests.
- Ruff check, Ruff format check, and `git diff --check`: passed after import and format fixes.
- Markdown links: pending final link pass after plan and board updates.
