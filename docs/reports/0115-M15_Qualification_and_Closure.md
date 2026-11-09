# Epic 0115 M15: qualification and closure

Date: 2026-11-08
Source revision before this report: `32303a7e6`

## Result

The revised 0115 scope is complete. M15 ran the essential combined checks for the selected cache
policies, checked the maintained storage map, and verified retained data in the current local
checkout. The [verification summary](0115-M15_Qualification_and_Closure.artifacts/recovery-verification.json)
binds this check to recovery snapshot `c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`.
It validated 2,086 migration resources, 150 retained drafts/reviews/calibrations across 441 exact
files, four representative recording files, the raw model source, and the runtime model bundle.
No retained data changed.

This closes the revised cleanup and selected cache-policy scope. It does not close every original
M0 goal or assert that all remaining growth risks are bounded. The independent lifecycle work for
operational logs, recovery copies, and campaign intermediates moves to [Epic 0118](../plans/5-closed/0118-Operational_and_Recovery_Lifecycle.md).

## Frozen M0 targets and outcomes

| M0 target | Outcome | Evidence and limit |
| --- | --- | --- |
| Conditional recovery-tree candidate: 24.1 GiB and 142,746 files | **Unmet; superseded by dependency evidence.** | M3 removed only 51 exact duplicate recovery videos (14,516,434,567 logical bytes). The recovery tree was not safe to remove wholesale. Its directory allocation fell by 14,176,268 KiB. The measured free-space samples fell by 1,488 KiB immediately and 14,740 KiB at the later sample; they do not prove physical space reclaimed. |
| Fresh worktree ready within 30 seconds and at most 2 GiB allocated | **Met by the post-cutover M9 measurement.** | Two clean worktrees took 16.85 s and 15.71 s. Each used 1,693,696 KiB including its explicit state root, 403,456 KiB below the target. These are path allocations; shared `.git` and APFS clone accounting are separate. M15 did not repeat this successful setup measurement. |
| Frozen application I/O ceilings and exact 0114 fixture behavior | **Met by M11/M12 evidence at those recorded revisions.** | Four frozen M0 cases met their read/parse ceilings with zero live-root reads. M12 ran 35 hard pipeline cases / 70 samples with exact response tuples, then passed the 0114 qualifier on a temporary path-rebased corpus copy: 179 case budgets and 70 UI routes. M13 and M15 ran focused checks for the cache paths changed in those milestones. M15 did not rerun the broad 0114 checks under the revised closure scope. |
| Four exact agent lookups within 10 lines and 764 output bytes | **Not remeasured after M14.** | M0 recorded 4/4 exact results at the frozen limit. M14 added exact lookup commands to the storage map; it did not measure new agent output or token cost. |

The 24.1 GiB figure was a conditional upper bound for dependency review, not a promised saving or
an approval to delete the root. The later audit established a much smaller safe removal set. Marking
that original bound unmet does not weaken the M3 deletion safeguards or turn the remaining tree
into a cleanup target.

The read/parse ceilings establish no-regression behavior for the named cases at their recorded
revisions. They do not measure an application speedup. The lookup baseline does not measure lower
agent context or token use.

## Measured storage effects

- M3 removed 51 files totaling 14,516,434,567 logical bytes. The `0108-m10-20261105` directory
  allocation fell from 25,308,296 KiB to 11,132,028 KiB. The volume free-space samples did not show
  a gain, so physical space reclaimed is **not established**.
- M4 removed two unused COCO manifests totaling 3,171,322 logical bytes; the recorded directory
  allocation was 3,096 KiB lower after the plan, receipt, and lock files were written. This is not a
  volume free-space measurement.
- M12's isolated conversion of 8,571 PPM cache entries used 798,392,320 allocated bytes versus
  2,083,942,400 bytes in its frozen source snapshot, a 61.7% reduction. It preserved exact
  uncompressed bytes and identity, but did not activate the converted output in the operator cache.
  It is a compression rehearsal result, not reclaimed source-volume space.
- M8/M9 changed Git tracking for intake and legacy pipeline paths. Their local files stayed in the
  main checkout and became ignored; 15 automated-run records stayed tracked. Tracking changes are
  not physical deletion or relocation.
- M10 removed no Git or LFS objects. The Git garbage report, shared object packs, and local LFS
  remain. A read-only M10 audit observed 372 KiB less available space, which is filesystem
  variation and not attributed to this work.
- M13 enforces logical budgets for selected cache families. Pinned entries, metadata, filesystem
  overhead, and other cache roots remain outside those budgets. M15 did not measure current cache
  bytes or claim that the configured limits already reduced them.
- No application latency gain, agent search-output reduction, context reduction, or token saving was
  measured in M15.

## Essential integrated checks

All checks ran at the current code revision with the repository's configured `mise` tools.

- `mise exec -- uv run --project operations pytest -q operations/tests/test_derived_view.py operations/tests/test_0115_crop_cache_conversion.py` — passed.
- `mise exec -- uv run --project table_evidence_analyzer pytest -q table_evidence_analyzer/tests/test_visible_cards.py table_evidence_analyzer/tests/test_card_classification.py` — passed.
- `mise exec -- uv run --project backend pytest -q backend/tests/test_visible_card_pipeline_api.py backend/tests/test_interactive_ui_media_performance.py` — passed.
- `mise exec -- uv run --project backend python scripts/verify_0115_recovery.py --data-root data --runtime-root .runtime --output /tmp/0115-m15-recovery-verification.json` — passed against the real retained local roots; digest and exact counts are in the linked summary artifact.
- Read-only check of the nine local roots named in the storage map, plus its authority/cache/shared-input/recovery distinctions — passed.
- Focused Ruff check and format check passed for the cache implementation and test modules in `operations`, `backend`, and `table_evidence_analyzer`.
- Markdown paths and anchors for the storage map, moved epic, board, and dependent plans passed. `git diff --check` passed.

Prior M13/M12 evidence remains part of qualification and is not presented as a new M15 run. The
direct checked-in 0114 qualifier still encounters stale absolute trial-log paths; the recorded
temporary copy changes only those paths and passes. The M13 broad package Ruff check also reported
two existing findings in untouched files: `table_observation.py:187` (line length) and
`test_visible_card_fine_prepass_fixtures.py:1` (import order). The M13 focused provider test still
records `test_factory_converts_interrupted_round_analysis_to_failed` returning `queued` instead of
`failed`. Follow-up owners are the table-observation module maintainer, fine-prepass fixture
maintainer, and backend managed-job recovery owner, respectively. These are outside the changed
cache paths and do not fail the focused M15 checks.

## Remaining risks and follow-up

- The accepted-loss recovery set is on the source volume. Off-volume disaster recovery and unique
  physical allocation remain unverified.
- The selected cache budgets exclude pinned bytes and metadata. Cache sweeping occurs on access or
  writes; an idle cache has no background sweeper.
- Operational logs, recovery-copy expiry, and campaign-intermediate lifecycle have no new bounds.
  Epic 0118 owns their exact-writer inventory and recovery decisions.
- Git/LFS ownership and a stable safe-prune set remain unresolved. No prune or history rewrite is
  authorized by this closure.
- Some historical processed inputs retain useful provenance but are not byte-for-byte
  reconstructable. No full-run reproducibility claim is made.

## Closure decision

Close the revised 0115 scope because its selected cleanup, isolated-storage, format, cache, map, and
recovery checks are complete. The original broad recovery-tree and physical-space goals remain
unmet or unmeasured as stated above. The remaining lifecycle work is owned by 0118, and bounded
recording workspace reads/startup work is owned by 0117. This closure does not claim that either
follow-up is complete.
