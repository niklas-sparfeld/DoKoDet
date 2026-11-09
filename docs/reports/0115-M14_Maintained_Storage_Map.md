# Epic 0115 M14: maintained storage map

Date: 2026-11-08

This map points to existing evidence and current repository paths. It is not a new inventory. The
sizes in the linked reports are dated measurements, not current totals or unique physical space.
Update this map when a listed root, owner, retention policy, or recovery status changes. Check its
links and lookup commands as part of that update. Use `DOKO_STORAGE_ROOT` for a worktree's mutable
state. The examples below assume the repository root and use exact recording, node, revision, or
report identities when those are known.

## Storage families

| Family and current path | Authority, owner, and lookup | Retention and recovery |
| --- | --- | --- |
| Original recordings: `data/intake/recordings/<recording-id>/` (ignored local data) | Source asset authority. `RecordingBundleStore` and recording APIs read bundles; `operator_corpus_import.py` copies selected bundles into a worktree root. See [M5](0115-M5_Worktree_Storage_Contract.md), [M8](0115-M8_Intake_Cutover.md). | Preserve. Main checkout keeps the corpus locally. M8 verified all 239 remote Git blobs, 43 sibling raw videos, 15 remote LFS videos, and two bundle restores. No new worktree receives the corpus implicitly. |
| Current pipeline nodes, revisions, reviews, calibrations, and operation state: `data/operations/pipeline-nodes/` (ignored local data; use `$DOKO_STORAGE_ROOT/data/operations/pipeline-nodes/` for isolated work) | Current durable authority. `PipelineNodeStore` owns node manifests, heads, and immutable revisions; review and calibration stores own their records. For one exact node: `rg --no-ignore -n '"schema_version"|"node_id"' data/operations/pipeline-nodes/<node-id>/manifest.json`; for one revision: `rg --files --no-ignore data/operations/pipeline-nodes/<node-id>/revisions/<revision-id>`. See [M1](0115-M1_Recovery_and_Cleanup_Plan.md), [M6](0115-M6_Cutover_Inventory.md), [M9](0115-M9_Pipeline_Cutover.md). | Preserve human work and active dependencies. M1/M9 verified selected content and restart workflows. The accepted-loss recovery package is local to the same source volume; it is not off-volume disaster recovery. |
| Legacy pipeline revisions, runs, and selections: `data/operations/pipeline/{revisions,runs,selections}/` (ignored local data) | Retained historical representation; explicit migration, inventory, and repair tools may read it. Exact root and readers are in [M6](0115-M6_Cutover_Inventory.md). | Preserve while referenced. M9 verified all 31,521 files against both its activation snapshot and the recovery package. The package is same-volume; a shallow remote clone also restored these exact files. Fifteen `automated-runs/**` records remain tracked and separate. |
| Accepted-loss migration and recovery stage: `data/operations-recovery/0108-m10-20261105/migration-stage-accepted-loss/` (ignored recovery copy) | Recovery authority for the recorded 0108 package. Inspect its `migration.json` and package files; verify with the [recovery verifier](../../scripts/verify_0115_recovery.py). See [M1](0115-M1_Recovery_and_Cleanup_Plan.md) and [M3](0115-M3_Recovery_Tree_Retirement.md). | Retain as recovery evidence. It shares the source volume. Full-root physical allocation and off-volume recovery remain unknown. M3 removed only the 51 verified duplicate recovery videos. |
| Model source and runtime assets: `data/models/` and selected `.runtime/` campaign bundles (ignored local data) | Immutable model inputs. The DINOv3 source is under `data/models/dinov3-vits16-pretrain-lvd1689m`; active RF-DETR 0092 bundle is `.runtime/rfdetr-segmentation-0092-m4/bundle`. Providers and preflight read exact configured paths. See [M1](0115-M1_Recovery_and_Cleanup_Plan.md), [M4](0115-M4_Runtime_Intermediates.md), [M6](0115-M6_Cutover_Inventory.md). | Preserve current bundles and active dependencies. M1 verified local clone digests and offline DINOv3 loading. Restore availability differs by asset; do not infer an independent backup from ignored status or a model bundle's presence. |
| Derived views and sampled frames: `$DOKO_STORAGE_ROOT/runtime/pipeline/derived-views/` (per-worktree derived caches) | `DerivedViewCache` and `SampledFrameResolver` reconstruct entries from exact source revisions or videos. Exact readers and policies are in [M13](0115-M13_Growth_Bounds.md); the compressed crop format and isolated conversion are in [M11](0115-M11_Format_Experiment_and_Decision.md) and [M12](0115-M12_Format_Conversion.md). | Derived cache, not authority. Direct entries use an 8 GiB unpinned logical-byte budget and 30-day idle expiry; sampled JPEG frames use a 2 GiB budget, 30-day idle expiry, and 2,048-frame per-recording/transform cap. Pinned entries and metadata are outside these bounds. |
| Provider responses: `$DOKO_STORAGE_ROOT/runtime/gemini-cache/` (per-worktree cache) | `gemini_analyzer.py` and visible-card provider code own reads and writes. The exact 209 replay receipts are listed in the [pin manifest](0115-M13_Growth_Bounds.artifacts/provider-cache-pins.json); see [M13](0115-M13_Growth_Bounds.md). | Recomputable cache; a miss can incur provider cost. The policy uses a 4 GiB unpinned logical-byte budget and 180-day idle expiry. The 209 pinned 0088 replay responses are preserved. Pinned bytes and metadata are outside the budget. |
| 0114 hard-fixture assets: `~/.cache/doko-detector/interactive-performance/` (external, shared by worktrees) | Content-addressed fixture assets. The [M0 inventory](0115-M0_Storage_Inventory_and_Ranked_Targets.md) and [M6 cutover inventory](0115-M6_Cutover_Inventory.md) record the pinned manifest and reader contract. | Protected qualification inputs, not an eviction target for runtime cache policies. M0/M1 evidence pinned 57 exact assets. Current physical allocation and independent backup are not established here. |
| Git objects and LFS: shared `.git/` object database and `.git/lfs/` | Git refs, worktree metadata, and LFS pointers/objects are shared across registered worktrees. Exact audit path and ownership findings are in [M10](0115-M10_Git_and_LFS_Maintenance.md). | Retain. No objects were removed. Dangling-object ownership and a stable LFS prune set remain unresolved; do not infer reclaimable space from Git's garbage count. |

## Bounded exact lookups

The lookup commands inspect named resources or metadata. Replace placeholders with IDs from an
existing report, API response, or manifest; do not scan generated roots to discover candidates.
The final recovery verifier is different: it recursively validates and hashes the specified
recovery package, active node tree, and representative recording and model paths under the roots
passed to it. Use it for that whole-root verification, not as an exact-resource lookup.

```sh
# One known recording bundle
rg --files --no-ignore data/intake/recordings/cardeventnet-IMG_0637

# One known pipeline node and immutable revision
rg --no-ignore -n '"schema_version"|"node_id"' \
  data/operations/pipeline-nodes/<node-id>/manifest.json
rg --files --no-ignore data/operations/pipeline-nodes/<node-id>/revisions/<revision-id>

# One report or artifact with an exact known name
rg --files docs/reports | rg '0115-M13_Growth_Bounds(\.md|\.artifacts/provider-cache-pins\.json)$'

# Recursively verify the recovery package and named retained roots
mise exec -- uv run --project backend python scripts/verify_0115_recovery.py \
  --data-root data --runtime-root .runtime --output /tmp/0115-recovery-check.json
```

## Known limits and follow-up

The M0 sizes and counts are historical. This map makes no current size, unique APFS allocation,
reclaimed-space, or complete-backup claim. The accepted-loss stage is on the source volume. Some
training inputs have provenance but cannot be reconstructed byte for byte. The shared Git/LFS
object ownership question remains open. Cache budgets exclude pins or metadata as stated above.
Operational logs, recovery-copy expiry, and campaign-intermediate lifecycle decisions are deferred
to [Epic 0118](../plans/3-in-progress/0118-Operational_and_Recovery_Lifecycle.md).
