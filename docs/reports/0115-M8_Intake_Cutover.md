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

This proves the canonical bundle and API path for one recording restored from the sibling raw corpus.
The remote proof below covers a second recording with a proposal file. Both use the existing bundle
schema and importer; no new persistence or API contract was needed. No reusable materializer was
created. The M5 fixture workflow alone does not prove access to operator media.

## Independent backup and checkout rehearsal

A shallow clone of GitHub `origin/main` at `21a1146b0e7ca3bcbc702dc358437b6609ecf482` contains the
same Git blob for every one of the 239 intake paths as local `HEAD`. The sibling raw corpus verifies
43 media originals by exact size and SHA-256. I fetched the remaining 15 originals from remote LFS
into the disposable clone; all 15 objects match their manifest sizes and SHA-256 values. Thus the
candidate's metadata and other ordinary Git files have an independent remote Git copy, 43 original
videos have an independent local copy, and the other 15 original videos have verified remote LFS
copies.

I restored `94bf648d-9f13-43e4-977a-700b64b67b90` using its remote metadata, remote LFS video, and
proposal-generator file. The canonical bundle passed the existing importer. The real app returned
HTTP 200 for the recording and bundle endpoints before and after restart; the video endpoint
returned the expected digest. No new persistence or API contract was needed.

A disposable merge rehearsal removed only that video's tracked path. Before the merge, it saved the
exact file to an independent backup. The merge preserved an unrelated staged deletion and an
untracked file. After the merge, restoring the saved video produced the exact digest as an untracked
file. This is a usable preservation procedure, but it requires a pre-merge backup and a post-merge
restore in each checkout that must retain a local copy.

Exact remote hashes, restore results, rehearsal state, and checkout inspection are in
[`remote-and-rehearsal.json`](0115-M8_Intake_Cutover.artifacts/remote-and-rehearsal.json).

## Checkout protection and cost

All registered worktrees were inspected without changing them. The main checkout has 239 tracked
candidate entries and no candidate changes. The first iOS worktree also has 239 tracked entries and
no candidate changes. The `.codex/worktrees/6203` checkout has 239 tracked entries and no candidate
changes; its unrelated staged deletions remain untouched.

The second iOS worktree is locked as `initializing`. Its Git directory has an `index.lock`, all 239
candidate paths are staged for deletion, and 226 candidate files are present as untracked files. The
selected 94bf video is present with the exact expected digest but is staged deleted and untracked.
This is an active operation on the same intake family. Do not merge into, clean, or otherwise modify
that checkout. Git metadata does not expose its owner. Coordinate with its owner and wait for the lock
and staged operation to finish before cutover. No bounded cutover can meet the all-worktree gate while
that operation remains active.

The disposable procedure proves that a selected video can be restored after a merge while preserving
unrelated staged and untracked work. It does not authorize changing the active iOS worktree. That
checkout has all intake paths staged for deletion and an index lock, so no bounded subset can be
integrated safely until its owner confirms the operation is complete. The `.codex/worktrees/6203`
checkout has unrelated staged changes only; its intake remains clean. Do not modify either checkout.

Current measurements are separate: the main intake checkout occupies about 15 GiB; shared `.git`
occupies about 31 GiB, including about 17 GiB in `.git/lfs`. `git count-objects -vH` reports 11.35
GiB in Git packs and 2.65 GiB of temporary garbage. M10 owns Git/LFS maintenance; M8 did not remove
or rewrite history. These are current filesystem measurements, not savings or unique-allocation
claims.

## Checks

- `git ls-files -s -- data/intake/recordings`: 239 entries; activation digest recorded above.
- `git lfs fsck --objects`: passed for the local object store; this is not independent restore proof.
- Independent source checks: 43 local originals and 15 remote LFS originals match exact size and SHA-256; all 239 remote Git blobs match the activation tree.
- Disposable restore: one matched original was combined with exact tracked metadata, passed canonical bundle validation, imported through the existing CLI, and read by the real app before and after restart. The video API returned the expected SHA-256.
- Remote restore: one bundle with a proposal file was rebuilt from remote Git metadata and LFS, imported through the existing CLI, and read by the real app before and after restart.
- Disposable merge rehearsal: the selected media file was removed from the index by a test merge, then restored from an exact backup. An unrelated staged deletion and untracked file stayed unchanged.
- `DOKO_STORAGE_ROOT=/private/tmp/doko-0115-m8-state mise exec -- uv run --project backend pytest backend/tests/test_worktree_storage_contract.py backend/tests/test_operator_corpus_import.py -q`: 3 passed. This exercises fixture import and API read/write/restart with the old mutable path disabled; it does not read the 43 operator recordings.
- No live checkout or merge was performed. The procedure is proven in a disposable repository, but applying it to all registered checkouts is blocked by the locked iOS worktree's staged changes and `index.lock`.

## Decision and next step

Keep all 239 intake paths tracked for now. Independent backup identities match the full candidate,
and API restore/readback passed on two representative bundles. The existing importer and canonical
bundle schema support the bounded restore without a new storage contract. Do not change tracking
while the initializing iOS worktree has an active index lock and staged intake deletions. Coordinate
with its owner, wait until the operation ends, verify its candidate copy and status, then apply the
tested backup/merge/restore procedure to each checkout that must retain local copies. No main operator
data or existing worktree state was changed.

## Current run recheck

On 2026-11-08, read-only inspection found the registered
`ios-ea2238c1-eaa1-46e6-a9bc-ebd15fdbb3d4` checkout still marked `locked`. Its `.git/index.lock`
exists, all 239 `data/intake/recordings/**` entries are staged for deletion, and 226 candidate paths
are present as untracked files. `lsof` returned no lock owner. No owner/status channel is available
in this run. The locked checkout was not modified. M8's all-worktree protection gate remains unmet,
so this run leaves all intake paths tracked and M8 incomplete. Resume only after the operation ends
and the checkout's candidate status and retained copies can be verified.
