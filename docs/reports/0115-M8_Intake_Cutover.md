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
bundle root, and no existing command assembles a bundle from raw video plus tracked metadata. A
disposable proof for `cardeventnet-IMG_0641` copied the unchanged tracked manifest, source record,
and task enrollment into a temporary bundle, added the exact 159,644,121-byte raw video from the
sibling corpus, and passed all manifest digest checks. The current operator importer then copied
that bundle into a separate `DOKO_STORAGE_ROOT`. The real app returned HTTP 200 for
`GET /v1/recordings/{recording_id}` and `GET /v1/repository-bundles/{recording_id}` before and
after app restart. The video endpoint returned bytes with the expected SHA-256. The sibling source
hash was unchanged. Exact details are in
[`single-recording-restore.json`](0115-M8_Intake_Cutover.artifacts/single-recording-restore.json).

This proves the canonical bundle and API path for one matched recording, with its metadata still
tracked. It does not prove the other 42 matches, restore the 15 missing originals, or create an
independent copy of metadata. No new persistence or API contract was needed for this one-off proof.
A repeatable materializer for the sibling raw-media layout would be a new tool contract; plan that
work before implementation. The M5 fixture workflow alone does not prove access to operator media.

## Checkout protection and cost

All registered worktrees were inspected without changing them. The main checkout has the candidate
intact. The two iOS worktrees have 239 and 226 files under the candidate path; one is locked while
initializing. The `.codex/worktrees/6203` checkout has staged repository-wide deletions outside
`data/intake/recordings`; its intake index and working directory both still contain 239 files, and
there are no staged intake changes or in-progress Git operation markers. Its unrelated staged state
must remain untouched. No cutover checkout or merge rehearsal was run, so preservation of intake
files in those existing worktrees after they later merge an untracking commit remains unproven.

For a media-only subset, the independent raw source and tracked metadata can restore one standard
bundle through the existing importer; this did not require a new API or storage schema. A future
selection could untrack only exact verified video paths while keeping all metadata and the 15
unverified videos tracked. However, the same video paths remain present in the existing checkouts.
There is no tested mechanism that preserves those per-checkout copies through a later merge without
changing their state. The available external raw source can restore a copy, but using it after a
merge would not prove that each checkout was protected before the merge. The staged worktree is not
locked or running a Git operation, but its unrelated staged changes prohibit using it for rehearsal.
The iOS worktree locked as `initializing` also cannot be treated as an available rehearsal target.
No bounded subset currently meets every M8 gate.

Current measurements are separate: the main intake checkout occupies about 15 GiB; shared `.git`
occupies about 31 GiB, including about 17 GiB in `.git/lfs`. `git count-objects -vH` reports 11.35
GiB in Git packs and 2.65 GiB of temporary garbage. M10 owns Git/LFS maintenance; M8 did not remove
or rewrite history. These are current filesystem measurements, not savings or unique-allocation
claims.

## Checks

- `git ls-files -s -- data/intake/recordings`: 239 entries; activation digest recorded above.
- `git lfs fsck --objects`: passed for the local object store; this is not independent restore proof.
- External source check: 43 of 58 video originals matched exact length and SHA-256; 15 were missing.
- Disposable restore: one matched original was combined with exact tracked metadata, passed canonical bundle validation, imported through the existing CLI, and read by the real app before and after restart. The video API returned the expected SHA-256.
- `DOKO_STORAGE_ROOT=/private/tmp/doko-0115-m8-state mise exec -- uv run --project backend pytest backend/tests/test_worktree_storage_contract.py backend/tests/test_operator_corpus_import.py -q`: 3 passed. This exercises fixture import and API read/write/restart with the old mutable path disabled; it does not read the 43 operator recordings.
- No activation or checkout/merge protection rehearsal was performed. One standard-bundle restore passed, but coverage of the other recordings and protection of existing checkout copies remain open.

## Decision and next step

Keep all 239 intake paths tracked for now. The 43 verified raw originals can form a service-readable
bundle when combined with tracked metadata; the 15 unresolved videos and all metadata must remain
tracked. There is no bounded selection that passes checkout protection today. Before resuming M8,
coordinate with the owners of the registered worktrees to settle a copy-preservation procedure,
wait for the initializing checkout to finish, and clear or otherwise protect the unrelated staged
worktree state without agent changes to it. Then rehearse the selected video-path merge in disposable
storage and confirm that every existing checkout copy remains recoverable without overwriting local
work. No main operator data or existing worktree state was changed.
