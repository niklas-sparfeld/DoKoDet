# Epic 0115 M10: Git and LFS maintenance decision

Date: 2026-11-08
Result: **No Git or LFS object was removed.** Current evidence does not define a safe, stable
cleanup set.

## Scope and observed state

The main checkout was clean at `b42cafa35e051c569bdfb47beffd34a6f1169445` before this report.
It is 107 commits ahead of `origin/main`. The two registered detached worktrees were also clean:

| Checkout | HEAD | State |
| --- | --- | --- |
| Main | `b42cafa35e051c569bdfb47beffd34a6f1169445` | `main`, 107 commits ahead of `origin/main` |
| iOS worktree | `0f46b9ad25f3a3bf111b2f56cf0bf6f74395fcd3` | Detached, clean |
| Worktree `6203` | `b7ebf2390f1cec1406aea0819c797f6da1869c4e` | Detached, clean |

The M9 archive and restore rehearsal remains the verified recovery route for the two detached
worktrees. Their commits are not named by a normal branch. Do not remove either worktree or assume
that the remote alone preserves its working files. M9 also verified a shallow remote clone for the
selected pipeline files; this does not verify all local Git or LFS objects.

No Git maintenance process, Git/LFS lock, or LFS temporary file was present during inspection. The
repository has seven packfiles totaling 12,189,554,531 bytes (reported as 11.35 GiB), and Git reports
10 garbage files totaling 2.65 GiB. These exact temporary files account for the garbage report:

| File | Bytes | Modification time (local) |
| --- | ---: | --- |
| `.git/objects/pack/tmp_pack_ePlspv` | 630,325,260 | 2026-09-16 19:31:06 |
| `.git/objects/pack/tmp_pack_J6j9sG` | 305,266,700 | 2026-09-16 22:43:06 |
| `.git/objects/pack/tmp_pack_Z72vur` | 293,994,508 | 2026-09-15 21:22:24 |
| `.git/objects/pack/tmp_pack_WTsmJO` | 325,451,788 | 2026-09-16 17:17:59 |
| `.git/objects/pack/tmp_pack_4IHpNX` | 309,592,076 | 2026-09-16 23:08:41 |
| `.git/objects/pack/tmp_pack_jksQ5Z` | 486,408,204 | 2026-09-17 01:23:06 |
| `.git/objects/pack/tmp_pack_AMGH1P` | 419,430,412 | 2026-09-15 21:07:18 |
| `.git/objects/93/tmp_obj_x0Mf8Z` | 58,535,936 | 2026-09-15 16:31:55 |
| `.git/objects/73/tmp_obj_nrWnN3` | 167,936 | 2026-10-15 15:12:15 |
| `.git/objects/a8/tmp_obj_b9FUs3` | 23,662,592 | 2026-09-15 16:24:08 |

`git fsck --full --connectivity-only` exits successfully, but reports dangling commits, trees, and
blobs. The repository also has 336 `refs/codex/...` references, two backup refs, `refs/original`, a
stash, and other refs. These refs and dangling objects make a broad prune unsafe without exact
ownership and recovery mapping. No pack temporary or unreachable object was removed.

## LFS state and decision

`.git/lfs/objects` contains 771 files and uses 17,627,216 KiB (reported as 16.8 GiB); the LFS cache
uses 4 KiB. `git lfs ls-files --all --long` lists 63 pointers. `git lfs prune --dry-run` reported 64
retained objects. Two separate `git lfs prune --dry-run --verify-remote --verbose` checks returned
different candidate hashes (`5abad8f866625b3dc24f1106f2cbc359f639ed7e5c3f20d48228702e124563ba`
at 5,617,631 bytes and
`fb770328cfb44f597943a0b1ebb0eec3d8c67aa1cdda60a193941dd3edf49f5f` at 458 KiB), while neither
showed a remote verification error. `git lfs status` also reports an empty-file LFS object
pending push. The candidate set is not stable across dry runs, and a pending push is explicit local
work. No LFS object was pruned.

The LFS prune tool can verify candidate availability at the remote, but this observation does not
establish a frozen, complete object-to-ref map for safe deletion. Recheck this after pending pushes
are resolved and the candidate set can be captured consistently. Keep local LFS storage and Git
history costs separate from per-worktree checkout size. No history rewrite or forced update is
proposed.

## Commands and checks

- `git worktree list --porcelain`; `git -C <worktree> status --short --branch`: three clean checkouts.
- `ps -axo pid,ppid,command`; lock-file search under `.git`: no active Git/LFS operation or lock.
- `git count-objects -vH`: seven packs, 10 garbage files, 2.65 GiB reported garbage.
- `git fsck --full --connectivity-only`: exit 0; dangling objects reported, no integrity error.
- `git lfs env`, `git lfs ls-files --all --long`, `git lfs prune --dry-run`, and
  `git lfs prune --dry-run --verify-remote --verbose`: LFS inventory and dry-run only.
- `git lfs status`: one LFS object pending push.
- `df -k .`: free-space samples varied by 208 KiB during inspection; no storage operation occurred,
  so no reclaimed-space claim is made.

## Follow-up

Do not manually delete the temporary pack/object files or run a broad prune based on the garbage
label. Before any future operation, map the exact Git object IDs to refs, reflogs, worktree HEADs,
and Codex snapshots; capture and verify the LFS prune candidate list and remote availability; then
record pre/post object counts, integrity checks, recovery proof, and free-space samples. The M9
worktree archive procedure is specific to the detached worktrees and does not authorize general
history or LFS cleanup.
