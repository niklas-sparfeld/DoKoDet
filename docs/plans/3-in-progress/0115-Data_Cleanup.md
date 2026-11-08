# Data cleanup

## Plan status

- **Status:** In Progress
- **Depends on:** 0108, 0110, 0112, and 0114 complete. Use the final 0112 storage boundaries and
  0114 qualification evidence. No unmet dependency for M6.
- **Outcome:** Reduce retained disk bytes, worktree cost, application overhead from data growth,
  and agent discovery cost. Preserve useful source material and human work. Prevent regrowth.
- **Retention decision:** Confirmed by the user on 2026-11-07. Preserve original recordings, human
  review work, current model bundles, and the exact dependencies needed by active work. Old
  generated runs and migration backups are candidates after dependency checks.

## Problem and observed evidence

The repository has several storage costs. Large directories alone do not identify disposable data.
A small metadata file can keep a large dependency tree live. A file under `.runtime` can be a
required model bundle rather than a cache. Git ignore rules do not remove already tracked files.

Read-only inspection on 2026-11-07 at main revision `29bf4d4bb` found the following. The working
state was clean when inspection started. Concurrent epic work can change this baseline.
Sizes are allocated bytes reported by `du -k`, converted to GiB and rounded. These are directory
measurements, not unique physical bytes, recoverable space, or predicted savings. APFS clones,
hard links, snapshots, and LFS copies need separate accounting.

| Root or measure | Observed value | Meaning or candidate |
| --- | ---: | --- |
| `data` | 50.2 GiB | Includes source media, current operations, and recovery trees |
| `data/operations-recovery` | 30.1 GiB | 0108 M10/M11 snapshots and several staged draft trees |
| `data/operations-recovery/0108-m10-20261105` | 24.1 GiB | Largest recovery tree; compare against activated content and migration evidence |
| `data/intake` | 15.2 GiB | Source media; preserve original recordings |
| `data/operations` | 4.3 GiB | Mixed durable resource families |
| `data/operations/pipeline` | 1.6 GiB | Older persisted resources; validate surviving consumers before removal |
| `data/operations/pipeline-nodes` | 1.7 GiB | Current node storage, including revision history |
| `.runtime` | 42.6 GiB | Model campaigns, training views, caches, and derived media |
| `.runtime/pipeline/derived-views` | 6.5 GiB | Derived-view cache candidate; verify reproducible reconstruction |
| `.runtime/gemini-cache` | 2.7 GiB | Provider responses; check cost and reproducibility before treating as disposable |
| `.git` | 30.8 GiB | Shared object database, LFS objects, and worktree metadata |
| Git pack files | 11.35 GiB | History cost; deleting files in a new commit does not reclaim old objects |
| Git-reported garbage | 2.65 GiB | Temporary pack/object files; investigate active Git processes before maintenance |
| `.git/lfs` | 16.8 GiB | Local LFS storage; verify reachability and restore availability |
| Tracked files under `data` and `.runtime` | 32,044 | 31,536 are under `data/operations/pipeline` |

The current ignore rules include selected older pipeline roots but ignore `pipeline-nodes`.
Do not assume a Git checkout is a complete backup of current human work. Establish and verify
recovery before removing the older tracked representation. The auto-generated local environment
setup installs dependencies; it does not declare a data isolation or sharing contract.

Reproduce the initial measurements without parsing retained payloads:

```sh
du -k -d 1 data .runtime .git
du -k -d 1 data/operations-recovery data/operations .runtime/pipeline
git ls-files data .runtime
git count-objects -vH
git worktree list --porcelain
```

These observations do not prove an application speedup or agent token saving. Measure both.
Relevant existing evidence: [0108 M10 reconciliation](../../reports/0108-M10_Migration_Reconciliation.md)
records recovery snapshots, preserved drafts, original embedded bytes, and declared lost inputs.
The [0114 hard-data report](../../reports/0114-M1_Hard_Data_and_Fixture_Freeze.md) records current
large payloads, exact lineage fixtures, and an external content-addressed asset cache.

## Goals and boundaries

1. Reduce unique allocated bytes and retained file count. Separate live content, derived content,
   recovery copies, Git history, LFS storage, and bytes duplicated across worktrees.
2. Make a new development worktree cheap and usable. Keep ordinary tests local and self-contained.
   Make required source/model material available without copying the full developer corpus.
3. Reduce application reads, parsing, warning volume, and startup cost caused by irrelevant data.
   Reuse [0114](../5-closed/0114-Interactive_UI_Performance.md) for HTTP/browser timing and
   startup qualification. Keep generic endpoint optimization in that epic.
4. Reduce agent search output and ambiguity about authoritative data, current schemas, and useful
   examples. Provide bounded entry points that do not require reading large generated trees.
5. Improve recovery reliability and available disk headroom. Keep a tested recovery path for
   retained human work. Expire redundant recovery copies after their purpose has ended.
6. Prevent regrowth through bounded cache, log, backup, and intermediate-artifact lifetimes.

No model training, new review decisions, provider promotion, cloud service, or phone is required.
Do not change source media with lossy transcoding. Do not round geometry or discard probability
information to save bytes. Preserve exact identities, content meaning, review state, and lineage
when changing storage. Immutable digest contracts must remain valid or receive an explicit,
verified replacement contract; silently rewriting bytes behind an existing digest is invalid.
Do not preserve obsolete runtime schemas merely for compatibility. Record unresolved dependencies
rather than selecting a newer revision as a substitute. Do not reopen closed epics.

The default retention set includes drafts, independent reviews, calibrations, completed human
reviews, selected references, active jobs, pending review queues, frozen evaluation evidence, and
required model/configuration assets. Follow transitive dependencies from these retained roots.
Keep active-epic artifacts, including 0096/0098 review handoffs, 0106 exports, and 0114 hard fixtures.
A completed generated run is not automatically protected forever; retain it when the policy or a
retained dependency requires it. Missing or opaque references require investigation before deletion.
Do not open sealed test content as part of cleanup.

Git history rewriting, forced pushes, removal of another worktree, and deletion of unique retained
source/review content are outside this epic. Normal safe Git/LFS maintenance can be evaluated.
If history dominates the remaining cost, record a separate concrete proposal and its consequences.
Moving data to an archive is relocation, not reclaimed disk space on the same volume. A quarantine
must have an expiry and cannot become a permanent second corpus.

## Explicit cache and old training-input scope

Inventory caches as a separate class: decoded frames, crops, thumbnails, derived views, provider
responses, model-download caches, and project-local test/tool caches. Include external cache roots
used by this repository; shared tool caches need separate ownership checks. Report current bytes,
regeneration cost, active users, cache keys, and proposed size/expiry limits per family. A cache
label does not prove that its contents are reproducible or unused.

Inventory processed inputs to old training runs explicitly: extracted frames, resized images,
identity crops, masks and labels, synthetic scenes, assembled training/validation views, tensor or
feature caches, and copied input datasets. Follow their manifests and actual readers to distinguish
original source/review authority from disposable materializations. Include abandoned and failed
runs. Preserve split membership, source/review revision IDs, preprocessing configuration, code/model
versions, hashes, and useful metrics as compact provenance when retiring bulky input copies.

A historical provenance reference does not by itself require keeping every materialized training
input on disk. Distinguish a runtime or active-work dependency from a record of what a completed
training run consumed. A retained model bundle does not automatically pin its full training working
directory. Retain required source/review authority and compact provenance; remove reproducible
processed copies after checking active users and regeneration feasibility. Record whether exact
input bytes can be reconstructed. Do not claim full run reproducibility when they cannot. Required
unique evaluation evidence and active frozen inputs remain protected under the retention policy.

M0 must rank both classes. M4 must explicitly account for old processed training inputs, including
retained reasons for candidates it does not remove. M13 must cover cache eviction and the lifecycle
of newly created training materializations. Preserve caches needed by 0114 qualification until a
verified replacement exists; do not evict a shared asset merely because one run has ended.

## Execution and acceptance contract

Each milestone has one focused implementation-and-plan commit. Before implementation, freeze its
observable result, exact candidate/root, required commands, and commit boundary. Use one bounded
resource family or policy per milestone. If discovery requires multiple storage contracts, split
that milestone before assignment. Do not hide a new store, transaction, or conversion in cleanup.

M0 sets numeric targets from the measured inventory: reclaimable GiB and file count, worktree
creation time/incremental bytes, application read/parse counts and relevant 0114 cases, and agent
search output bytes/lines and exact-resource lookup success. Freeze targets before selecting fixes.
Do not invent a percentage from this initial scan. Report skipped or unsuccessful candidates with
reasons. A deletion receipt records manifest digest, source revision, retained roots, exact paths,
expected size, action, and observed result; full payloads stay outside agent-facing reports.

For migrations, list representative resource kinds and schema versions, all active readers and
writers, replacement owners, and verification checks. Prove one complete workflow through real
services/APIs and disposable persistence with the old path disabled before broader conversion.
Rehearse and restart. Verify content, editing, selections, review decisions, and exact dependencies.
Freeze the activation snapshot; retain minimal tested recovery evidence. Test concurrent writers
and crash recovery separately when coordinated writes change. Preserve the completed 0112 store
boundaries and 0114 fixtures; resolve ownership before changing their contracts.

## Milestone status

| Milestone | Observable result / commit boundary | State |
| --- | --- | --- |
| M0 | Storage inventory, cost baseline, retention roots, and ranked targets | Complete |
| M1 | Tested recovery of retained authority and an exact cleanup manifest | Complete |
| M2 | Bounded cleanup planner and apply mechanism | Complete |
| M3 | Retire verified redundant migration and recovery trees | Complete |
| M4 | Remove one ranked family of unused runtime intermediates | Complete |
| M5 | Specify and prove isolated worktree data access | Complete |
| M6 | Freeze cutover inventory, replacement owners, recovery evidence, and test-failure disposition | Complete |
| M7 | Make isolated development storage and setup the normal path | Complete |
| M8 | Cut over tracked intake after proving source access and recovery | Complete |
| M9 | Cut over the selected tracked pipeline family after dependency and recovery checks | Complete |
| M10 | Evaluate safe Git and LFS maintenance and record history costs | Complete |
| M11 | Measure compact storage candidates and select at most one bounded format change | Complete |
| M12 | Implement and convert the selected format family, if justified | Complete |
| M13 | Bound cache, log, and future recovery-copy growth | In Progress |
| M14 | Add compact agent discovery and data-authority guidance | Not started |
| M15 | Verify savings, workflows, performance, and recovery; close | Not started |

## Execution handoff

- **Run:** M12 is complete and M13 is in progress in this 4-milestone run. Requested: 4.
  Completed: 1. Remaining: 3. The preceding run completed M8 through M11; its count is recorded
  in the M11 report.
- **M0:** Complete in the prior run. See [the M0 report](../../reports/0115-M0_Storage_Inventory_and_Ranked_Targets.md).
- **M1:** Complete. The [M1 report](../../reports/0115-M1_Recovery_and_Cleanup_Plan.md) records ignored node data and original migrated records, representative edited and independent reviews, calibration, lineage, the hardest selected run chain, model loading, 0108 snapshot reconciliation, and path-specific cleanup candidates. No authoritative data was deleted.
- **Changes:** Added the read-only [recovery verifier](../../../scripts/verify_0115_recovery.py), validation summaries, selected-chain and video checks, a path-specific [cleanup plan](../../reports/0115-M1_Recovery_and_Cleanup_Plan.artifacts/cleanup-plan.json), and [canonical independent-review restore evidence](../../reports/0115-M1_Recovery_and_Cleanup_Plan.artifacts/independent-review-recovery.json). The accepted-loss stage remains the verified local recovery set on the source volume.
- **Checks:** IMG_0097 loopback API returned five workspace stages, seven lineage nodes, and two exact processor runs across restart. The canonical review imported as one visible-card node and one scene node, retaining 9 accepted, 40 pending, and 1 unusable decision. Node-review APIs returned 10 visible-card and 40 scene records. Edit/save/readback created a new scene revision; old revision reviews and downstream selection remained unchanged after restart. Three focused web tests passed (12 cases), and three focused backend modules passed (20 tests). All 51 recovery-video files (14,516,434,567 logical bytes) match their accepted-stage digests and protected intake copies. Disk free space was 73 GiB before and after bounded restore. Existing IMG_0637 edit/save/readback/restart and offline DINOv3 loading checks remain recorded in the report.
- **Decisions and limits:** 0108 M11 intentionally removed the legacy review-scoped HTTP routes. The supported path restores independent reviews as canonical visible-card and virtual-scene draft nodes through current workspace and node-review APIs; no new contract was added. The recovery set is local to the source volume; physical APFS allocation and full-root recovery cost are unknown. No deletion is approved. M3 must complete full recovery-tree reference checks and a recovery drill before any deletion.
- **M2:** Complete. The [M2 report](../../reports/0115-M2_Bounded_Cleanup_Tooling.md) records
  the frozen 51-file recovery-video candidate root, tool contract, and limits. The local
  [cleanup planner/apply tool](../../../scripts/cleanup_0115.py) writes dry-run plans by default;
  apply requires an explicit authorization and complete-reference declaration.
- **Changes:** Added a manifest-bound plan and apply CLI, exact file and protected-reference
  identity checks, symlink and open-file rejection, durable per-file receipts, and interruption-safe
  repeat handling. Apply takes an exclusive root lock and reloads the receipt under that lock.
  Receipt validation checks its exact candidate list and planned identities against the plan and
  current filesystem before it reports completion. Added temporary fixtures for each required
  safety case. No retained user data was changed.
- **Checks:** The focused fixture suite passed (10 tests), including receipt replacement after
  preflight, concurrent apply rejection, and three altered-receipt cases.
  Ruff check, Ruff format check, and `git diff --check` passed. The M1 manifest remains dry-run only because it does not authorize
  deletion and it records unresolved references. Its production candidate root is absent from this
  checkout, so no plan or apply ran against retained data.
- **Decisions and limits:** Apply requires `deletion_authorized`, `references_complete`, no unknown
  references, and per-candidate authorization. It checks current open files with `lsof` and fails
  closed when that check is unavailable. Apply removes only regular, single-link files under the
  selected root. M2 adds tooling only; it does not authorize or perform M3 cleanup.
- **M2 handoff:** M3 audited all recovery-tree references and completed the required recovery
  checks before retiring one exact candidate family.
- **M2 commit boundary:** The M2 tool, focused tests, report, epic, board, and handoff were grouped
  in its own focused commit.

- **M3:** Complete. The [M3 report](../../reports/0115-M3_Recovery_Tree_Retirement.md) records
  the exact reference audit, guarded retirement of 51 duplicate recovery videos, retained-content
  audit, protected originals, recovery drills, live review restart, and measured directory and
  volume changes.
- **Changes:** Retired only the 51 manifest-bound recording-video copies. Preserved the accepted-loss
  recovery stage, earlier stage, migration source, intake originals, and unknown histories. The M2
  tool now allows hard-linked protected references while retaining single-link candidate checks;
  its focused regression tests cover both cases. The [durable receipt](../../reports/0115-M3_Recovery_Tree_Retirement.artifacts/retirement-receipt.json)
  lists every removed path and digest.
- **Checks:** M2 tests passed (12); Ruff and format passed. The M1 verifier passed after apply with
  the same accepted-loss snapshot digest. The 51-file family reconstructed and hash-checked from
  intake after apply. The real backend served two representative independent-review revisions and
  50 records across restart. The pre-apply M1 evidence records an edit/save/readback/restart. A new
  post-apply edit/save/readback/restart passed in isolated storage, with prior reviews and selection
  digests intact. The exact retained-tree digest, file count, and logical bytes matched before and
  after. The M2 apply receipt reports all 51 files removed.
- **Decisions and limits:** The available volume space changed by -1,488 KiB between immediate
  pre-apply and post-apply observations, and by -14,740 KiB from pre-apply to a later sample after
  temporary drill cleanup. The 0108 root directory fell from 25,308,296 KiB to 11,132,028 KiB.
  These are measured values; no savings are predicted. The full copied-store drill
  remained too slow because of deep JSON serialization, so it was stopped in temporary storage.
  Unknown histories and unrelated uncertainty remain retained.
- **M3 next at that time:** M4 — remove one ranked family of unused runtime intermediates.
- **M3 commit boundary:** M2 tool correction, focused regression tests, M3 report and artifacts,
  epic, board, and handoff in one focused milestone commit.

- **M4:** Complete. The [M4 report](../../reports/0115-M4_Runtime_Intermediates.md) records the
  exact 0070 run and processed-input dependency audit, provenance, guarded apply, retained bundle
  probes, and postflight manifest.
- **Changes:** Retired only the two unused train/validation COCO annotation manifests from the
  highest-ranked unused processed-input family, totaling 3,171,322 bytes. Kept the split manifest,
  all 718 symlinks and their training-view targets, every checkpoint, the selected bundle, run and
  training configuration, metrics, and memory log. The provenance artifact retains split
  membership, source/review revisions, preprocessing configuration, versions, hashes, and metrics.
  The supplemental [ranked-family audit](../../reports/0115-M4_Runtime_Intermediates.artifacts/historical-training-family-audit.json)
  classifies the resumed 0092 attempts and both completed 0070 50/50 experiments.
- **Checks:** The M2 dry-run permitted exactly two frozen paths; its apply receipt records both
  removals. No writer or open file was found. The exact retained-root manifest matched before and
  after. The 0070 training-view verifier passed after apply. The retained 0070 and configured 0092
  bundles loaded; each passed two matching deterministic CPU probes. No training or provider call
  ran.
- **Decisions and limits:** The retained training view and recorded code identify the COCO input
  generation path, but byte-for-byte reconstruction was not verified. The 0070 run root remains about
  1.9 GiB because its checkpoints are distinct training states; only its selected checkpoint is
  duplicated exactly in the retained bundle. The M4 change reclaimed 3,171,322 logical bytes and
  measured 3,096 KiB less `du` allocation after the tool's plan, receipt, and lock files were
  written. This is not a volume free-space claim. The larger 50/50 experiment, active caches,
  provider responses, and 0114 fixtures remain protected for their recorded reasons. The 0092
  output remains because 0096 uses its selected bundle; its two interrupted attempts resumed the
  same run from the same checkpoint. The 50/50 control and synthetic runs remain separate completed
  experiments under an explicit `retain_as_experiment` decision. Other M0-ranked candidates and
  their retention reasons are classified in the M4 report.
- **Next:** M5 — specify and prove isolated worktree data access.
- **Commit boundary:** M4 report and provenance / before-after artifacts, this epic, and board
  update in one focused milestone commit.

- **M5:** Complete. The [M5 report](../../reports/0115-M5_Worktree_Storage_Contract.md) defines
  `DOKO_STORAGE_ROOT` and records an explicit selected-bundle copy plus API edit/save/readback/
  restart workflow. Mutable operations, intake, runtime output, and caches use one worktree-owned
  root. API uploads do not write to the source corpus.
- **Changes:** Added root resolution, the selected operator-bundle copy CLI, and focused tests. The
  API workflow copies one bundle into isolated intake, edits a compact fixture node, reads the node
  and recording asset, restarts, and repeats both reads.
- **Checks:** The fixture-backed API edit/save/readback/restart test passed in two detached
  disposable worktrees with distinct roots. Exact bundle hashes matched; the source stayed
  unchanged. Full `mise install`, backend sync, frontend install/build, and backend app
  initialization measured 26.30 / 27.09 s. Total ready allocation was 18,670,260 / 18,673,008
  KiB: 17.80 / 17.81 GiB, exceeding the M0 2 GiB target by 15.80 / 15.81 GiB. Checkout
  allocation was 16.92 GiB, or 14.92 GiB over target. M8–M9 own tracking cutover. A bounded
  app/pipeline test run passed 43 tests with one lifespan-related failure
  recorded in the report. The legacy data defaults are still active when the explicit root is absent.
- **Decisions and limits:** Explicit operator access copies selected validated bundles into the
  worktree intake. The source stays intact as the local restore copy. The create-to-ready time
  target passes; the 2 GiB worktree target remains unmet until tracking cutover. M5 does not
  relocate model bundles.
- **M5 handoff at that time:** M6 was next; M6 is complete below.
- **Commit boundary:** Storage-root and corpus-copy code/tests, M5 report, this epic, and board
  entry in one focused milestone commit.

- **M6:** Complete. The [M6 inventory and qualification report](../../reports/0115-M6_Cutover_Inventory.md)
  freezes all tracked intake and legacy pipeline paths at `b294ffac4`. Intake contains 239 files
  (15,633,971,412 bytes); legacy revisions, runs, and selections contain 31,521 files
  (1,701,015,169 bytes). Fifteen automated-run idempotency records remain a separate tracked family.
- **Changes:** Added a path/blob-ID/size inventory artifact and recorded authority, representative
  schemas, current readers/writers, replacement owners, restore dependencies, and M7–M9 gates and
  commit boundaries, with exact setup and command templates in the report's
  [Frozen setup commands for M7–M9](../../reports/0115-M6_Cutover_Inventory.md#frozen-setup-commands-for-m7m9).
  No data, tracking, or authority changed. 0112 code ownership and 0114 final
  qualification remain separate boundaries. The report records the four registered worktrees,
  including the one with staged repository-wide deletion and untracked checkout state.
- **Checks:** `git lfs fsck --objects` passed. Representative schema and owner lookups passed.
  The named M5 failure was reproduced on baseline `9f523c3` and current `b294ffac4`; both returned
  `queued` where the test expected `failed`. Commit `12bef8a6b` removed the factory's
  `fail_non_terminal()` call. The recovery owner needs to decide if this remains factory behavior
  or moves to managed-job recovery. Local links were checked.
- **Decisions and limits:** M8 owns only tracked `data/intake/recordings/**`; M9 owns tracked
  `revisions/**`, `runs/**`, and `selections/**`. Keep all 15 `automated-runs/**` records tracked.
  A local LFS integrity check is not proof of remote/off-volume restore. Later cutovers must verify
  every selected restore source and protect retained files in all worktrees. The 2 GiB target is
  still unmet; no savings claim follows from this inventory.
- **Next:** M7 — make isolated development storage and setup the normal path.
- **Commit boundary:** M6 inventory artifact, report, epic, board, and handoff only.

- **M7:** Complete. The [M7 report](../../reports/0115-M7_Isolated_Development_Setup.md) applies
  the M5 root contract to the CardEventNet runtime cache and documents the explicit per-worktree
  setup and operator import path. Existing repository defaults remain when the setting is absent;
  no operator data is redirected or copied implicitly.
- **Changes:** CardEventNet cache writes now use `Settings.evidence_root`; backend setup docs name
  every mutable root and provide clean-checkout, run, operator-import, and missing-asset behavior.
  No tracked data, tracking, or data authority changed.
- **Checks:** The M6 clean setup passed in two disposable worktrees at `15d7d105`: tool install,
  backend sync, frontend install/build, app initialization, and three API fixture tests per
  worktree. A further isolated API run left worktree B's root manifest unchanged before and after
  (`d2919607…f4f185e2`). Each API run edited, read, and re-read after restart; no old node path
  appeared. The M7 report records fixture and root digests and exact commands. Ruff, format,
  Markdown links, and `git diff --check` passed. The known M6 interrupted-round-analysis test still
  returns `queued` instead of `failed`.
- **Decisions and limits:** The operator corpus and model bundles stay at their declared paths.
  Opening operator data requires an explicit validated copy. Missing source and model assets fail
  visibly; no implicit fetch or fabricated asset is used. No M8 or M9 tracked family changed.
- **Next:** M8 — cut over only the selected tracked intake family after source and recovery proof.
- **Commit boundary:** M7 backend cache-root change and regression test, setup documentation, report,
  epic, board, and handoff in one focused commit.

- **M8:** Complete. The [M8 assessment](../../reports/0115-M8_Intake_Cutover.md) records the
  239-path activation snapshot at `c2307415300696b5c50164facaefc6b6a84c613e`. Before cutover,
  all three currently registered worktrees held the exact 239 files: 181 metadata blobs and 58
  original videos. The former initializing checkout is no longer registered and its checkout
  directory is absent; its disappearance is not counted as recovery evidence. All 43 sibling raw
  videos, 15 remote LFS videos, and 239 independent remote Git blobs were verified. The remote-only
  bundle restore and real API readback across restart remain verified. A disposable merge rehearsal
  preserved unrelated staged and untracked work and restored an exact backed-up video.
- **Changes:** Removed the 239 candidate paths from the main Git index and added an ignore rule.
  The main operator corpus remains present and ignored. The two other registered worktrees were not
  updated; their tracked copies remain exact. No pipeline path or source bytes changed. The activation
  inventory and current recovery/worktree audit are in the M8 report artifacts.
- **Checks:** All three pre-cutover worktrees had exact candidate files, metadata blob IDs, and video
  sizes and SHA-256 values. The sibling raw and remote LFS source audits passed; all remote Git
  candidate blobs match. After cutover, `git ls-files` lists zero intake paths and the main files
  remain present. The focused M5 worktree storage and operator corpus importer tests pass (3 tests)
  with a fresh `DOKO_STORAGE_ROOT`. The disposable merge/restore rehearsal, remote bundle API
  restore/readback across restart, `git lfs fsck --objects`, and `git diff --check` pass. An initial
  test attempt used a non-empty temporary root and hit the expected existing-node conflict; rerunning
  with a fresh root passed.
- **Decisions and limits:** The old worktree removal is not used as backup proof. The main checkout
  still has the full operator corpus, so M8 changes Git tracking but does not reclaim its local file
  bytes or rewrite history. The other registered worktrees remain at their original revisions.
- **Commit boundary:** Intake index removal, ignore rule, updated M8 inventory and assessment, epic,
  board, and handoff in one focused milestone commit. No pipeline tracking, source bytes, history, or
  Git/LFS object maintenance changed.

- **M9:** Complete. The [M9 report](../../reports/0115-M9_Pipeline_Cutover.md) freezes 31,521
  revision, run, and selection paths at activation digest `b275daba9c75b3d3deb047a61f8b6274acca10f370391eeeb4ba75abbc780c0e`.
- **Changes:** Removed only those paths from the main index and ignored them. All local payloads
  remain in place and match the activation snapshot. The separate 15 automated-run idempotency
  records remain tracked. Added a fixture-backed isolated-root API test for an exact five-revision,
  two-run chain, two selections, edit, review, and restart.
- **Checks:** The accepted-loss recovery package verifier passed before and after cutover. Its full
  31,521-file pipeline copy matches the source byte for byte. The corrected M9 API/restart test runs
  with an empty repository root and absent checkout pipeline paths. It edits and reviews the exact
  selected visible-card output and re-reads all five revisions, both run edges, and both selections
  after restart. The uncertainty audit maps all 156 records; candidate dependencies resolve, the
  three missing inputs are declared lost and unused by the selected family, and all 15 automated-run
  files remain tracked. The M1 event digest differs from the current M9 event payload, so M1 is cited
  only for the matching visible-card revision and preserved review decisions. The pipeline, node,
  worktree-storage, and importer suites passed (38 tests). Two disposable checkout protection
  rehearsals restored all 31,521 files exactly. The correction rerun passed 63 focused backend tests,
  and the read-only recovery verifier passed with the same migration snapshot. Current worktree setup
  timing and allocation are in the M9 report.
- **Decisions and limits:** No data file or Git history was deleted. The recovery package is on the
  same volume. A fresh shallow GitHub clone restored and verified all 31,521 candidate files. The operator corpus is not copied to new isolated roots by default. Existing
  detached worktrees remain unchanged; use the tested archive/restore procedure before a future
  merge. Two fresh worktrees pass the 2 GiB ready-allocation target by 403,456 KiB; M15 must repeat
  final measurement.
- **Commit boundary:** The pipeline index removal, ignore rules, exact chain test fixtures, M9
  evidence, epic, board, and handoff form one focused milestone commit.

- **M10:** Complete. The [Git and LFS maintenance report](../../reports/0115-M10_Git_and_LFS_Maintenance.md)
  records current worktree refs, temporary objects, LFS status, history cost, integrity results,
  and the reason no objects were removed.
- **Changes:** No Git or LFS object was changed. The report captures ten temporary object files
  totaling 2,852,835,412 bytes, exact ref names and target IDs, 70,456 unreachable objects, 771 local
  LFS objects, and the pending LFS push object. The current-audit artifact records matching before
  and after Git state and actual free-space samples.
- **Checks:** All three worktrees were clean. No Git/LFS process or lock was present.
  `git fsck --full --connectivity-only` exited 0 and reported dangling objects. Four LFS
  remote-verified dry runs returned different exact candidates; `git lfs status` showed a pending
  push. The read-only before/after audit preserved refs, unreachable counts, temporary objects, and
  pack counts; available volume space changed from 81,133,948 KiB to 81,133,576 KiB. No prune ran.
  The M9 archive/restore rehearsal remains the specific recovery evidence for detached worktrees.
- **Decisions and limits:** Do not delete temporary objects or prune LFS from this inspection.
  Exact ownership for dangling objects is unresolved, and the LFS candidate set was not stable.
  Reconcile Git refs/reflogs/worktree HEADs and obtain a stable LFS candidate and remote-availability
  inventory before any future maintenance. No history rewrite is proposed.
- **Next:** M11 — benchmark up to two storage alternatives for one ranked large resource family.
- **Commit boundary:** M10 report, epic status and handoff, and board update form one focused commit.

- **M11:** Complete. The [format experiment report](../../reports/0115-M11_Format_Experiment_and_Decision.md)
  records two lossless alternatives for one M0-ranked derived-view crop family and selects gzip
  level 1 for M12. The machine-readable [format benchmark](../../reports/0115-M11_Format_Experiment.artifacts/format-benchmark.json)
  contains aggregate metrics only.
- **Changes:** Added a repeatable, read-only
  [format benchmark](../../../backend/scripts/benchmark_0115_derived_crop_cache_formats.py).
  Corrected the application-I/O profiler to create the same exact disposable calibration,
  event-run, comparison, and automated-run resources as the established pipeline performance
  runner. The hard fixture manifest and live data remain unchanged.
- **Checks:** All 8,571 selected PPM crop entries round-trip byte for byte under gzip levels 1 and 6.
  Gzip level 1 reduces allocated bytes by 61.7%; cold/warm random-read p95 remains below 3 ms.
  All 35 hard pipeline scenarios pass with zero live-root reads and exact response checks. The four
  frozen M0 counter cases meet their read/parse ceilings. The 57-asset fixture and the full 0114
  baseline qualifier pass; the latter uses a temporary copy with stale absolute log paths rebased.
  Ruff, format, and diff checks pass.
- **Decisions and limits:** M12 is justified for only `visible-region-crop/v1` PPM cache entries.
  M12 uses `derived-view-cache/v2`, gzip level 1, `content.bin.gz`, and separate stored-byte
  digest/length fields. Preserve the existing uncompressed content digest/length, cache key, and
  identity. Freeze M12 at >=55% allocated-byte reduction, <=3 ms cold/warm random-read p95,
  <=4 ms average store/encode/write time per entry, and exact byte/identity checks. Keep the v1
  snapshot until isolated conversion, restart, interruption, corruption, and recovery checks pass.
  The full pipeline performance runner's prior M5 hard fixture omitted six exact resources; the
  profiler now seeds those resources in disposable storage using existing runner helpers.
- **Next:** M13 — bound cache, log, and future recovery-copy growth.
- **Commit boundary:** M11 report and artifacts, profiler and benchmark tools, epic/handoff, and
  board update form one focused commit.
- **M12:** Complete. The [format conversion report](../../reports/0115-M12_Format_Conversion.md)
  records the selected gzip cache implementation, full 8,571-entry isolated conversion, exact
  identities, interruption and corruption recovery, API and restart checks, and same-corpus
  performance results.
- **Changes:** The crop-cache reader now verifies `derived-view-cache/v2` stored-byte fields,
  decompresses the selected PPM crop family, and checks the original content digest and length.
  It rejects v1 PPM entries as misses; other v1 cache kinds keep their current format. The bounded
  [converter](../../../operations/scripts/convert_0115_crop_cache.py) writes only to a separate
  destination and verifies every converted entry.
- **Checks:** All 8,571 entries converted and restored exactly, retaining the M11 identity digest
  and 128-key sample. The rehearsal used 798,392,320 allocated bytes across 17,142 files (61.7%
  below M11), averaged 1.97 ms per entry for encode/write, and measured 1.63/1.57 ms cold/warm
  random-read p95. Two backend API modules passed (3 tests); focused cache modules passed (18).
  The current 35-case hard pipeline run passed 70 samples and matched all M11 response digests.
  Four M0 I/O cases passed with no live reads. The 0114 hard fixture, inventory, and rebased-copy
  qualification passed (57 assets, 76 API operations, 179 case budgets, 70 route budgets).
- **Decisions and limits:** The conversion used a disposable destination. The original operator
  cache was not modified. Its post-rehearsal digest equals the frozen M11 digest and is the recovery
  reference for any later activation. The direct 0114 qualifier still fails on stale absolute log
  paths in the retained raw corpus; a temporary copy with only those paths rebased passed without
  changing the baseline or checked-in evidence.
- **Commit boundary:** M12 implementation, focused tests, conversion and qualification evidence,
  report, epic/handoff, and board update form one focused milestone commit.
- **Current run result:** M12 complete; this run has completed 1 of 4 requested milestones and
  has 3 remaining.
- **M13 package 1:** The bounded runtime derived-view cache is implemented. See the
  [M13 growth-bounds report](../../reports/0115-M13_Growth_Bounds.md) for exact package boundaries,
  limits, and the retained [0114 media samples](../../reports/0115-M13_Growth_Bounds.artifacts/0114-media.json).
- **Changes:** Direct SHA-256-keyed runtime `DerivedViewCache` entries use a 30-day idle expiry and
  an 8 GiB unpinned logical-byte budget. Exact-key reads still regenerate missing or stale views.
  Explicit `.pin` markers protect pinned entries. New entries publish by atomic rename. Replacement
  uses a temporary backup, a process and thread lifecycle lock, and pending-state recovery to
  restore the old entry or retain the new one after interruption.
  The separate `sampled-frames` writer, durable roots, and external 0114 hard-fixture cache are
  outside this eviction policy.
- **Checks:** 28 derived-view tests, one crop-cache conversion regression, 18 visible-card and
  identity crop API tests, Ruff and format checks, 57 hard assets, 76 API operations, 70 planned UI
  cases, and the 13-case 0114 media suite passed. All 13 media response tuples match the retained
  0114 M9 sample. See the M13 report for hot/cold timings and limits.
- **Decisions and limits:** M13 remains incomplete. The 8 GiB policy bounds only direct
  digest-keyed entries in the derived-view root. `SampledFrameResolver` now has its own bounded
  policy under `sampled-frames`; package 3 covers the provider-response cache, then operational
  logs and recovery/campaign families. Pinned entries are excluded from the package 1 budget. No
  operator cache or retained human work was changed.
- **Next:** M13 package 3 — provider-cache replay, cost, budget, and expiry; completed below.
- **Commit boundary:** The cache writer contract and backend wiring, focused tests, 0114 evidence,
  report, epic/handoff, and board update form package 1's focused commit. It did not complete M13.

- **M13 package 2:** The sampled-frame cache now has its own 2 GiB JPEG-byte limit, 30-day idle
  expiry, and 2,048-frame per-recording/transform limit. Its writer shares the parent
  `derived-views/.lifecycle.lock` with package 1. The manifest binds video SHA-256 and byte length,
  decoder version, and transform version. See the [package 2 evidence](../../reports/0115-M13_Growth_Bounds.md#package-2-sampled-frame-cache)
  and [sampled-frame cold/warm result](../../reports/0115-M13_Growth_Bounds.artifacts/sampled-frame-cold-warm.json).
- **Changes:** Added complete JPEG decode validation, regeneration of truncated frames, atomic
  manifest publish, and recovery after interruption during pruning. Independent processes share the
  lifecycle lock; eviction waits for an active cache reader. Backend
  sampled-frame requests enable the policy; source, review, model, and hard-fixture roots remain
  outside it.
- **Checks:** 36 operations derived-view tests and 16 visible-card API tests passed, including
  cross-process eviction and interrupted-prune recovery. Ruff check,
  Ruff format, and `git diff --check` passed. The 13-case 0114 media suite passed and all response
  status/length/digest tuples match M9. Sampled-frame cold/warm API responses both returned HTTP 200
  with the same digest and frame time; the local samples were 121.97/2.79 ms. These are one-run
  timings on a generated 1-second, 64x64 video.
- **Decisions and limits:** M13 remains incomplete. The sampled-frame limit covers JPEG frame bytes;
  manifests and lifecycle lock files are outside its 2 GiB count. Idle expiry runs on cache access,
  with no background sweep. A cache miss regenerates from the accepted source video. No operator
  cache or retained human work was changed.
- **Next:** M13 package 3 — inspect provider-cache replay and cost behavior before setting its
  independent budget and expiry.
- **Commit boundary:** Sampled-frame retention, backend wiring, tests, 0114 evidence, report,
  epic/handoff, and board update form one package commit. The run remains at 1/4 milestones
  complete and 3/4 remaining because M13 is not complete.

- **M13 package 3:** The shared `.runtime/gemini-cache` lifecycle now enforces a 180-day idle
  expiry and 4 GiB logical-byte budget. The report records active writers/readers, request replay
  behavior, and the policy limits. It measured 18,655 JSON files and 2.697 GiB before applying
  the new policy.
- **Changes:** Added thread/process locking for cache reads, writes, and pruning; hourly expiry
  sweeps, oldest-first unpinned eviction, and `.json.pin` protection. Writes preserve pinned
  response bytes when a provider/classifier version changes. Backend visible-card
  responses and Gemini identity responses share the lifecycle. The 209 exact responses needed by
  the 0088 M2 cache-only replay are pinned; their request keys, crop digests, response digests,
  byte sizes, and recorded costs are in the [pin manifest](../../reports/0115-M13_Growth_Bounds.artifacts/provider-cache-pins.json).
- **Checks:** 30 provider/classifier tests and 16 backend construction/integration tests passed;
  Ruff, Ruff format, and `git diff --check` passed. Tests used fake providers; no paid Gemini
  request was made. The full `backend/tests/test_app.py` has a separate failure in
  `test_factory_converts_interrupted_round_analysis_to_failed` (`queued` instead of `failed`);
  its focused repeat also failed. See the [M13 report](../../reports/0115-M13_Growth_Bounds.md)
  for exact evidence and the package limits.
- **Decisions and limits:** The M2 replay depends on 209 exact provider receipts. These files are
  protected from overwrite, automatic expiry, and eviction. Other cache entries can be recreated through
  provider requests, which can incur cost. The 4 GiB budget excludes pinned files and metadata;
  expiry runs on access and there is no background sweeper. M13 remains incomplete.
- **Next:** M13 package 4 — select one operational-log writer family and preserve active-job and
  recovery evidence. Package 5 and combined M13 checks remain. The run still has 1/4 milestones
  complete and 3/4 remaining.
- **Commit boundary:** Provider-cache lifecycle and backend wiring, focused tests, M2 replay pin
  evidence, report, epic/handoff, and board status form one focused package commit.

## M0 — Inventory and rank

Build a bounded metadata inventory for the main checkout, registered worktrees, and relevant shared
asset locations. Record logical/allocated bytes, file counts, largest files, extensions, tracked/LFS/
ignored state, and links/clones where observable. Keep shared `.git` bytes separate from per-worktree
bytes. Inspect actual worktree creation/data setup paths before attributing cost to `.runtime`.
Use stat and path summaries first; parse representative exact manifests per resource family only.
Hash duplicate candidates after size/path filtering instead of hashing all videos and checkpoints.

Map durable authority, derived views, model weights, campaign intermediates, provider caches, logs,
recovery snapshots, and obsolete representations. Identify readers/writers and pending work that
pins each candidate. Do not classify from directory name, age, or absence of a current UI link.
Record schema/size samples, embedded binary/Base64 content, repeated revision payloads, duplicate
media/crops/checkpoints, and restore/recompute cost. Identify untracked authoritative resources.

Checks: repeat the inventory with stable inputs; explain volatile differences. Measure a disposable
worktree create-to-ready cycle, incremental bytes, and baseline agent lookup tasks. Use current
0114 fixtures for relevant app cases; freeze a minimal local baseline if its full suite is not yet
ready. Publish numeric targets, retained roots, ranked candidates, and commands in one report.

## M1 — Recovery and exact cleanup plan

Establish recoverability for the retained authority, especially ignored current node/review data.
Prefer one verified recovery set plus compact manifests over another full repository copy.
Restore representative retained recordings, edited and independent reviews, calibration, lineage,
and model loading into disposable storage. Include the hardest retained dependency chain.
Reconcile 0108 activation and draft-stage snapshots with their current replacements, including
original bytes that exist only in migration packages. Restore the selected independent review
through the canonical draft and scene-node migration already used by 0108 M11. Use the current
recording workspace, exact revision, edit, and node-review APIs. Do not recreate the retired
review-scoped HTTP contract. Preserve separate review identities, exact input lineage, scene facts,
review decisions, and downstream selection.

Checks: real service/API reads, edit/save/readback, exact dependency and digest validation, restart,
and restored review state through canonical node content and revision-bound review records. Produce
a path-specific deletion plan with retained/excluded reasons, unknown references, recovery
location, disk-space needs, and recovery expiry conditions. Do not mark unique data redundant from
file counts or a successful directory copy.

## M2 — Safe bounded cleanup mechanism

Add a small local planner/apply tool for the selected cleanup roots. Default to dry-run. Bind apply
to the frozen manifest and check paths, hashes or declared file identities, retained references,
and current writer state again. Reject changed candidates, escapes through symlinks, and unknown
references. Do not mutate a family while jobs or editors write to it. Record a compact durable
receipt and make interrupted/repeated application safe. Avoid a generic storage framework.

Checks: temporary fixtures for dry-run, protected dependencies, stale plan, path escape, active
writer, interrupted apply, and repeated apply. Verify no writes outside the selected fixture roots.
Run focused tests, lint, formatting, and applicable types. This commit implements tooling only.

## M3 — Recovery-tree retirement

Apply the verified plan to redundant 0108 recovery/staging trees, one snapshot family at a time.
Retain required unique originals and the recovery set proved in M1. Preserve historical report
links by documenting retired physical locations in the new report; do not rewrite closed epics.

Checks: exact retained-content audit before/after, recovery drill, live restart and representative
review workflows. Record removed paths and measured volume free-space change as well as directory
size change. A 30.1 GiB candidate root is not a promised 30.1 GiB saving.

## M4 — Runtime intermediates

Remove the highest-ranked unused training/materialization/intermediate family from M0. Protect
configured models, iOS export inputs, provider responses needed for replay, and pending work.
Use exact provenance to distinguish duplicate datasets/checkpoints from distinct experiments.
Do not rerun expensive training or paid providers merely to prove that cleanup was safe.

Checks: load retained bundles and run a bounded deterministic local probe; resolve retained
campaign and review dependencies; compare manifests and storage before/after. Record remaining
families as measured follow-ups rather than extending this milestone indefinitely.

## M5 — Worktree storage contract and complete proof

Specify code/compact-fixture storage, immutable shared assets, isolated mutable operations, and
per-worktree caches. Choose the smallest practical layout from measurements. Shared immutable
assets may use links or content-addressed storage; never hard-link mutable review/job files.
Do not silently point development/test writers at the main checkout's human data. Provide an
explicit way to open the operator corpus and a reproducible compact fixture path for normal tests.
Include local restore availability when moving media/models out of ordinary Git checkout.

Checks: create two disposable worktrees with the old data path disabled. Complete one real API
workflow in each, edit/save/restart, and prove write isolation and exact asset identity. Test missing
assets and ordinary clean-checkout setup. Measure create-to-ready time and incremental bytes.
This milestone owns any new storage-location contract and its first complete replacement workflow.

## M6 — Cutover inventory and qualification plan

Freeze exact tracked intake and pipeline candidate families, paths, counts, sizes, source revision,
retained roots, and their current authority. Inspect representative persisted resource kinds and
schema versions. List active readers and writers, replacement owners and paths, exact dependency
checks, and restore sources. Include current human work, active epics, model bundles, fixtures,
and all registered worktrees. Investigate missing or opaque references before any removal.

Reproduce the M5 `test_factory_converts_interrupted_round_analysis_to_failed` failure on the M5
baseline and current code. Record its origin, owner, and a concrete resolution or follow-up. Do
not waive an acceptance check because the failure predates M5. Freeze candidate-specific checks,
recovery drills, setup commands, and commit boundaries for M7–M9. Split a family before assignment
if it needs another storage contract or cannot fit one phase. Record current 0112 and 0114
boundaries and the 0114 final qualification evidence. Do not remove data or change tracking here.

Checks: repeat bounded inventory counts and representative dependency lookups; verify restore sources
and hashes where available; run the named failure on both revisions; check local Markdown links.
Commit only the inventory and plan/board updates. The output is an actionable cutover plan, not a
declaration that all candidates are safe to remove.

## M7 — Isolated development setup

Apply the M5 root contract to the selected remaining mutable roots and maintained development setup.
Make isolation the normal path without silently redirecting an operator's existing human data.
Provide an explicit operator-corpus access path and clear missing-asset errors. Do not edit the
auto-generated environment file; use its supported configuration or document the generator command.
Do not remove tracked data or change its authority in this milestone.

Checks: clean setup in two disposable worktrees with distinct roots and the old mutable path
disabled; real API edit/save/readback/restart; source and cross-worktree write isolation; fixture
materialization and missing-asset behavior; affected backend and setup checks. Record exact revision,
commands, asset digests, and remaining roots. Commit setup and root changes with their tests and report.

## M8 — Tracked intake cutover

Use the M6 inventory and M7 setup to cut over the exact selected tracked intake family. Before
untracking, freeze the activation snapshot and verify a usable independent restore source for every
retained original and required metadata. Preserve original recordings and the operator's active
corpus; do not equate removing Git tracking with deleting local source files. Do not touch pipeline
tracking in this milestone. If the independent restore source or a consumer is unresolved, record
the gap and keep the affected paths tracked.
Before integration, protect retained files in every existing checkout from checkout or merge effects.
Rehearse those effects; do not rely on `git rm --cached` alone to protect other worktrees.

Checks: disposable rehearsal with old checkout paths disabled; exact asset identities and current
corpus access through real services; clean checkout, two-worktree isolation, fixture materialization,
and restore/readback. Verify that the main operator corpus remains intact. Measure checkout and
shared Git history separately. Commit only the selected intake tracking, setup changes, tests, and
receipt. No history rewrite or destructive Git/LFS maintenance.

## M9 — Tracked pipeline cutover

Cut over one exact M6-selected tracked pipeline family only after its readers and writers use the
replacement and its retained content has a verified recovery source. Preserve exact revisions,
lineage, review decisions, selections, and pending work. Investigate unresolved references; do not
substitute a different revision. Rehearse the activation in disposable storage before changing
tracking. Split further if independent contracts or families remain.
Protect retained files in existing checkouts from checkout or merge effects before integration.

Checks: real API/service workflow with the old path disabled, including exact content, edit/save,
review decisions, dependencies and restart; recovery drill and frozen snapshot digest; clean
checkout and affected backend/operations checks. Repeat the M0 ready-worktree time and allocation
measurement with two worktrees and report remaining tracked families and the 2 GiB target gap.
Commit only this family, its tests, evidence, and plan updates.

## M10 — Git and LFS maintenance decision

Inspect active Git operations, all worktree refs, temporary objects, LFS reachability, and verified
object availability. Evaluate supported maintenance and its expected space effect. Do not infer safety
from a garbage label, delete pack temporaries by guess, rewrite history, or remove a worktree. Record
remaining shared history and LFS costs separately from checkout bytes. Execute only a bounded safe
operation if the evidence supports it; otherwise record the unresolved decision and follow-up.

Checks: record commands, exact candidate objects and refs, before/after state and free-space samples,
and object availability. Run the relevant Git integrity and recovery checks for any operation.
Commit the evidence and plan updates; do not include unrelated data changes.

## M11 — Format experiment and decision

Benchmark at most two storage alternatives against current storage for one ranked large resource
family. Candidates include transparent lossless compression, less repeated immutable payloads,
or binary storage for embedded arrays/assets. Measure allocated bytes, file count, cold/warm reads,
parse/write time, peak memory, random item access, and agent inspectability. Include metadata costs
and restore complexity. Smaller compressed files can still make application access worse.

Checks: exact content/digest semantics, review decisions, frame/item membership, numerical precision,
lineage, and representative large cases. Freeze one bounded replacement schema, reader/writer
contract, conversion scope, target gain, and recovery plan for M12. If no alternative gives useful
savings without unacceptable access cost, record that result and mark M12 not required. Split a
larger design into explicit milestones before implementation; retain the existing authorization limit.

## M12 — Selected format and conversion

Implement the M11 contract for one family. Update its active readers/writers and tests; remove the
replaced undeployed path. Rehearse conversion in disposable storage before activation. Preserve
exact source bytes where required by existing identities and bind any new representation to them.
Do not convert unrelated payload types as a side effect.

Checks: old path disabled, real API/service read and edit round trip, exact dependencies/review
state, restart, conversion interruption, corruption, and recovery. Repeat the M11 size/access tests
and affected 0114 cases on the same logical corpus. Record code revision and snapshot digest.

## M13 — Prevent regrowth

Define and enforce bounded lifetimes/size budgets for the ranked derived-cache, log, and recovery
families. Keep durable human work and pinned dependencies outside automatic eviction. Give derived
views exact cache keys and a reconstruction path. Invalidate stale views after edits and restart.
Document expiry of completed migration backups and campaign intermediates. Split independent
writer contracts before assignment if this needs more than one small change.

Checks: deterministic budget/expiry tests, pinned entries, missing cache regeneration, stale views,
active readers/writers, and crash recovery separately. Measure hot/cold application behavior with
0114; moving all latency to cache misses is not sufficient. The result must bound new growth.

### M13 execution packages

The acceptance above remains the M13 acceptance. Its ranked paths have independent writers and
retention behavior, so implementation is split into sequential packages. A package is not a new
milestone and does not change the authorized M12–M15 run limit. M13 stays incomplete until every
package is complete and the combined checks pass.

1. **Digest-entry cache lifecycle (complete).** Own only the direct SHA-256-keyed
   `DerivedViewCache` entry directories under `.runtime/pipeline/derived-views`, through
   `operations/src/doko_operations/derived_view.py` and its backend readers and writers. Freeze
   exact-key regeneration, bounded idle expiry and total size, safe eviction with concurrent
   readers/writers, crash recovery, and behavior after source revisions change. This package does
   not own the separate `SampledFrameResolver` writer under `sampled-frames`; package 2 owns that
   path. Keep `~/.cache/doko-detector` and all source, review, and model roots outside this writer.
   Check deterministic expiry/budget, active readers/writers, interruption/restart, missing-entry
   regeneration, stale revision behavior, and hot/cold 0114 cases. Commit this exact writer's
   contract, implementation, tests, evidence report, and updated handoff together.
2. **Sampled-frame cache (complete).** Own only
   `.runtime/pipeline/derived-views/sampled-frames` and the `SampledFrameResolver` read/write
   contract. Bound its per-recording frame cache and coordinate its lifecycle with the parent
   derived-view root. Preserve exact source-video identity and prove cache reconstruction, in-flight
   access, crash recovery, and 0114 cold/warm behavior. Do not assume the digest-entry cache policy
   covers this separate writer.
3. **Provider-response cache (complete).** Own only `.runtime/gemini-cache` and its `gemini_analyzer.py`
   construction and cache API. First identify replay/cost behavior and exact readers. Freeze its
   own expiry and budget before implementation; do not share derived-view eviction code without a
   verified contract. Check deterministic expiry, active requests, restart, and replay behavior.
4. **Operational logs.** Select and name one writer family, starting with per-job `logs.json` in
   `backend/src/dokodetector_backend/job_persistence.py` if its M0 rank and current size justify
   bounds. Preserve active-job logs and any records required for recovery. Check bounded writes,
   concurrent append/read, and restart separately. Campaign command/output logs need their own
   owner and retention decision before they enter this package.
5. **Recovery copies and campaign intermediates.** Inventory one exact retained backup or campaign
   family at a time. Record its writer, pin/dependency roots, reconstructability, expiry condition,
   and recovery procedure. Never apply cache expiry to these paths. Check interrupted creation,
   recovery, and exact retained human work before any expiry or cleanup.

The [M13 growth-bounds report](../../reports/0115-M13_Growth_Bounds.md) records the package
inventory and current phase boundary. A completed package can update its own checks and evidence,
but cannot mark M13 complete while later packages remain.

## M14 — Agent discovery and authority

Add a compact maintained storage map with authority, schema, owner, lookup command, retention class,
and example manifest for each retained family. Use bounded metadata indexes only if measurements
justify them; a new index needs an explicit writer and freshness contract. Keep payloads and old
backups out of default discovery through supported repository search/configuration mechanisms.
Provide commands for targeted opt-in access. Explain what is tracked, shared, ignored, and recoverable.

Checks: repeat M0 tasks to find a recording, a current human revision, an exact run input, a model
bundle, and a cleanup reason. Record search bytes/lines and lookup correctness against frozen
answers. Test that changed data does not leave a false authoritative pointer. Do not claim token
or reasoning improvements from file-count reduction alone. Run Markdown link checks.

## M15 — Qualification and closure

Repeat storage and worktree measurements on the same machine and declared retained corpus.
Compare the original and final layouts with all retained logical inputs fixed; also report any
intentional removal of generated history. Separate actual reclaimed disk, relocated bytes,
compressed bytes, cache bytes that will regrow, and Git history that remains.

Run the affected 0114 HTTP/startup/browser checks against pre-cleanup and cleaned snapshots, using
the current code for both where possible. Check bounded parse/read counts as unrelated data grows.
Do not compare a smaller, easier dataset with a larger one and call that a code optimization.
Complete a real-backend review/edit/save/restart workflow and the recovery drill. Recheck pending
review queues, active epic inputs, model loads, clean setup, and two-worktree isolation.

Checks: combined affected automated tests, lint/format/types, storage-plan idempotence, manifest and
exact lineage checks, local Markdown links, worktree and agent benchmarks. Meet frozen targets or
record a concrete unresolved gap; do not close as Complete while acceptance is unmet. Publish
before/after evidence, commands, retained backup expiry, ongoing budgets, and named follow-ups.
Update the epic and board in the final focused commit.
