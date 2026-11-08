# Data cleanup

## Plan status

- **Status:** In Progress
- **Depends on:** 0108 and 0110 complete. No unmet dependency for M0. Coordinate storage changes
  with 0112 and performance checks with 0114 before changing their shared boundaries.
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
retained reasons for candidates it does not remove. M9 must cover cache eviction and the lifecycle
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
and crash recovery separately when coordinated writes change. Coordinate with ongoing 0112 store
extraction and 0114 fixtures; do not alter their contracts concurrently without resolving ownership.

## Milestone status

| Milestone | Observable result / commit boundary | State |
| --- | --- | --- |
| M0 | Storage inventory, cost baseline, retention roots, and ranked targets | Complete |
| M1 | Tested recovery of retained authority and an exact cleanup manifest | Complete |
| M2 | Bounded cleanup planner and apply mechanism | Complete |
| M3 | Retire verified redundant migration and recovery trees | Complete |
| M4 | Remove one ranked family of unused runtime intermediates | Complete |
| M5 | Specify and prove isolated worktree data access | Complete |
| M6 | Cut over Git tracking and development setup to the verified layout | Not started |
| M7 | Measure compact storage candidates and select one bounded format change | Not started |
| M8 | Implement and convert the selected format family | Not started |
| M9 | Bound cache, log, and future recovery-copy growth | Not started |
| M10 | Add compact agent discovery and data-authority guidance | Not started |
| M11 | Verify savings, workflows, performance, and recovery; close | Not started |

## Execution handoff

- **Run:** requested 11 milestones; completed 5; remaining 6.
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
  unchanged. Worktree storage was
  17,739,124 KiB at checkout in each and 18,453,996 / 18,453,972 KiB after Python setup. This fails
  the M0 2 GiB target; M6 must complete tracking cutover. A bounded app/pipeline test run passed 43
  tests with one lifespan-related failure recorded in the report. The legacy data defaults are
  still active when the explicit root is absent.
- **Decisions and limits:** Explicit operator access copies selected validated bundles into the
  worktree intake. The source stays intact as the local restore copy. The 2 GiB worktree target
  remains unmet until M6 tracking cutover. M5 does not relocate model bundles or verify full
  frontend readiness.
- **Next:** M6 — tracking and setup cutover.
- **Commit boundary:** Storage-root and corpus-copy code/tests, M5 report, this epic, and board
  entry in one focused milestone commit.

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

## M6 — Tracking and setup cutover

Apply M5 to the remaining selected roots and maintained setup commands. Remove obsolete tracked
copies and update ignore/LFS rules only after current authority is recoverable and consumers use
the replacement. Do not manually edit the auto-generated environment file. Use its supported
configuration path or document the command that its generator must invoke.
Evaluate supported Git/LFS maintenance against active operations, all worktree refs, required
history, and verified object availability. Do not delete pack temporaries or LFS objects by guess.

Checks: clean checkout, two-worktree isolation, fixture materialization, current corpus access,
retained-model loading, and recovery with old paths disabled. Measure checkout bytes separately
from shared history. Report history costs left in place. Run affected backend/operations checks.

## M7 — Format experiment and decision

Benchmark at most two storage alternatives against current storage for one ranked large resource
family. Candidates include transparent lossless compression, less repeated immutable payloads,
or binary storage for embedded arrays/assets. Measure allocated bytes, file count, cold/warm reads,
parse/write time, peak memory, random item access, and agent inspectability. Include metadata costs
and restore complexity. Smaller compressed files can still make application access worse.

Checks: exact content/digest semantics, review decisions, frame/item membership, numerical precision,
lineage, and representative large cases. Freeze one bounded replacement schema, reader/writer
contract, conversion scope, target gain, and recovery plan for M8. If no alternative gives useful
savings without unacceptable access cost, record that result and mark M8 not required. Split a
larger design into explicit milestones before implementation; retain the existing authorization limit.

## M8 — Selected format and conversion

Implement the M7 contract for one family. Update its active readers/writers and tests; remove the
replaced undeployed path. Rehearse conversion in disposable storage before activation. Preserve
exact source bytes where required by existing identities and bind any new representation to them.
Do not convert unrelated payload types as a side effect.

Checks: old path disabled, real API/service read and edit round trip, exact dependencies/review
state, restart, conversion interruption, corruption, and recovery. Repeat the M7 size/access tests
and affected 0114 cases on the same logical corpus. Record code revision and snapshot digest.

## M9 — Prevent regrowth

Define and enforce bounded lifetimes/size budgets for the ranked derived-cache, log, and recovery
families. Keep durable human work and pinned dependencies outside automatic eviction. Give derived
views exact cache keys and a reconstruction path. Invalidate stale views after edits and restart.
Document expiry of completed migration backups and campaign intermediates. Split independent
writer contracts before assignment if this needs more than one small change.

Checks: deterministic budget/expiry tests, pinned entries, missing cache regeneration, stale views,
active readers/writers, and crash recovery separately. Measure hot/cold application behavior with
0114; moving all latency to cache misses is not sufficient. The result must bound new growth.

## M10 — Agent discovery and authority

Add a compact maintained storage map with authority, schema, owner, lookup command, retention class,
and example manifest for each retained family. Use bounded metadata indexes only if measurements
justify them; a new index needs an explicit writer and freshness contract. Keep payloads and old
backups out of default discovery through supported repository search/configuration mechanisms.
Provide commands for targeted opt-in access. Explain what is tracked, shared, ignored, and recoverable.

Checks: repeat M0 tasks to find a recording, a current human revision, an exact run input, a model
bundle, and a cleanup reason. Record search bytes/lines and lookup correctness against frozen
answers. Test that changed data does not leave a false authoritative pointer. Do not claim token
or reasoning improvements from file-count reduction alone. Run Markdown link checks.

## M11 — Qualification and closure

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
