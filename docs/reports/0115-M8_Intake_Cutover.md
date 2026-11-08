# Epic 0115 M8: tracked intake cutover assessment

Date: 2026-11-08

Activation revision: `969d9a6159dbdc412de8b605c12d7fdf06ff626c`
Result: **M8 incomplete. Tracking is unchanged.**

## Activation snapshot

The frozen candidate remains `data/intake/recordings/**`. The activation inventory in
[`activation-inventory.json`](0115-M8_Intake_Cutover.artifacts/activation-inventory.json) records
all 239 index entries, their Git blob IDs, current byte sizes, and the current index digest
`23eabc8abbb482fbe8565cc7a7b48614b9b2a5ec687e9f885b1ef262b7f18d8f`. It also records all 58
recording identities and checks for independent source media.

The sibling local corpus at
`/Users/niklas.sparfeld/Developer/doko_detector-local-data/card_event_net/data/raw` has 43 files.
All 43 match an intake source record's original filename, byte length, and SHA-256. The other 15
recordings have no matching file in that source directory. It contains raw video only; it has no
independent copy of the 181 tracked non-video intake files. Those files include each bundle's
manifest, source record, and task enrollment. The current intake remains the only verified complete
copy of those metadata files.

The M5 importer expects complete repository bundles. The sibling raw-media directory is not a
bundle root, and no supported command restores those 43 originals into a service-readable bundle.
The existing fixture workflow proves the storage-root contract, but it does not prove access to the
operator corpus after the checkout intake path is disabled. The cutover consumer and metadata
restore gates therefore remain open.

## Checkout protection and cost

All registered worktrees were inspected without changing them. The main checkout has the candidate
intact. The two iOS worktrees have 239 and 226 files under the candidate path; one is locked while
initializing. The `.codex/worktrees/6203` checkout has staged repository-wide deletions, including
intake files. Its pre-existing staged state must remain untouched. No checkout or merge rehearsal
was run because no tracking change was safe to rehearse against that state.

Current measurements are separate: the main intake checkout occupies about 15 GiB; shared `.git`
occupies about 31 GiB, including about 17 GiB in `.git/lfs`. `git count-objects -vH` reports 11.35
GiB in Git packs and 2.65 GiB of temporary garbage. M10 owns Git/LFS maintenance; M8 did not remove
or rewrite history. These are current filesystem measurements, not savings or unique-allocation
claims.

## Checks

- `git ls-files -s -- data/intake/recordings`: 239 entries; activation digest recorded above.
- `git lfs fsck --objects`: passed for the local object store; this is not independent restore proof.
- External source check: 43 of 58 video originals matched exact length and SHA-256; 15 were missing.
- `DOKO_STORAGE_ROOT=/private/tmp/doko-0115-m8-state mise exec -- uv run --project backend pytest backend/tests/test_worktree_storage_contract.py backend/tests/test_operator_corpus_import.py -q`: 3 passed. This exercises fixture import and API read/write/restart with the old mutable path disabled; it does not read the 43 operator recordings.
- No activation, checkout, or merge rehearsal was performed. The existing staged-deletion worktree and missing usable bundle restore leave this gate unresolved.

## Decision and next step

Keep all 239 intake paths tracked. Preserve the 43 verified raw originals and all existing worktree
state. Do not treat the raw-media matches as proof that the service can use them. Before retrying
M8, define and test a supported restore workflow that combines an exact independent original with
the retained metadata, resolve the 15 missing originals or keep their paths tracked, then rehearse
checkout and merge protection for every existing worktree. No main operator data was changed.
