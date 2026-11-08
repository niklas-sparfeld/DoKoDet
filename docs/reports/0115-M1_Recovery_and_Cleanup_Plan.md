# Epic 0115 M1: recovery evidence and cleanup plan

Date: 2026-11-08

Code revision: `fc78bf8e12c6652fe4b09f7dba7262a0ac529410`

Data source: `/Users/niklas.sparfeld/Developer/doko_detector/data`
Result: **Incomplete. No deletion is authorized.**

## Verified recovery set

The ignored active store is not present in this detached worktree. I read it from the main checkout
and made an APFS clone under `/tmp/0115-m1-recovery` for recovery checks. The clone contained 1,006
node manifests, 27,654 files, and 1,700,808,685 bytes. A sorted per-file SHA-256 manifest matched
the source; its digest is `7152b452c98bec2b0e512f8a5e5a9126f861566107fe242b635cfc01989100c7`.
I also cloned recording `cardeventnet-IMG_0637`, its 129,435,020 bytes across four files, the
86,430,287-byte raw DINOv3 source, and the 172,911,952-byte DINOv3 runtime bundle. Their source
and clone digests matched. The runtime bundle digest is
`7fcd14ef6d897241dad71a81e6f85ffbda4a258ff45224d46b74a6a9cef78186`.

I verified the accepted-loss migration stage with the migration package verifier: 2,086 resources,
34,414 file records, snapshot digest
`c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`, and plan digest
`9bf7bd2979ff3d20026e8509ed6f41b172e1fba8c4aab1002e395fd0bb68febc`. The earlier stage also
passed package verification. It has 1,903 resources and 32,219 file entries, including 51 external
video references. All 32,168 operations file entries in the earlier stage match the accepted stage
by path, byte length, and digest. The accepted stage adds 183 evidence packages and retains the 51
external video references. It records three declared lost detector revision IDs.

I compared the active ignored record store with the accepted stage. All 150 maintained-draft,
independent-review, and calibration-draft records match 441 original files byte for byte, totaling
145,675,545 bytes. Each record carries the accepted snapshot digest. This confirms those original
review and calibration bytes remain available in the current node store and staged package.

## Service and model checks

I restored a bounded set into `/tmp/0115-m1-service`: 28 nodes for the `IMG_0637` lineage and the
`IMG_0097` independent-review references, one recording, migrated record bytes, and three
`IMG_0654` calibration drafts. The temporary API process used isolated operation and runtime roots.

- `GET /api/recordings/cardeventnet-IMG_0637/pipeline` returned HTTP 200 with all five stages.
- `GET /api/recordings/cardeventnet-IMG_0637/pipeline/lineage` returned HTTP 200 with 24 nodes and
  30 revisions.
- `POST /api/pipeline/nodes/1cf7f684-bcfb-5839-8e1d-46fabe5461ce/edit` saved a one-unit change to
  the final event end time in the disposable store. A revision read returned the saved value.
- After stopping and restarting the service, the revision and lineage reads returned HTTP 200 and
  retained the saved value and revision.
- `PipelineReferenceStore` loaded the three `IMG_0637` maintained references with 50, 50, and 98
  items. `VisibleCardReviewStore` loaded the independent `IMG_0097` review with 50 items. The
  `CalibrationDraftStore` loaded all three selected `IMG_0654` drafts.
- The independent review references proposal node/revision
  `b0dcfad1-2f68-5ded-a9c6-ffb19915fb82/aa617a64-b60c-5b33-925e-4784066ce044`, detector
  node/revision `23c3e690-18af-55dc-8073-becf3717b981/6022fe80-db15-5da0-9fbb-fc0326d4d8ae`,
  and calibration `calibration-1d154b1e75fe5bf0b788916d`. The saved calibration digest matches the
  review reference: `1c4edd408a30c222c72a690e2e245b99e55398181111ceffe871175303a54f86`.
- The offline DINOv3 inference loader loaded the cloned `224-cls` encoder (`DINOv3ViTModel`) and
  head (`Linear`) using the declared `inference` dependency group. It used no remote model fetch.

The original full-node-set API request remained CPU-bound for more than two minutes and grew to
about 1 GiB RSS. I stopped it and restored a smaller exact dependency chain from the accepted-loss
stage into a disposable root. The set contains five node revisions, two processor runs, two exact
selections, the independent review, its 1,404,947-byte calibration resource, the 302,193,776-byte
recording bundle, and two persisted run directories (2,014,161 and 1,799,744 bytes). The selected
migration resources total 10,891,987 bytes. The five revisions are the canonical events revision,
maintained events revision, detector revision, proposal revision, and their exact input revisions.
The source video digest is
`f00d7c10c5b9bafd93245c0a9ca702d8b585caf651ff56e7a86a92a4fa7a8c2b`.

I started the real FastAPI app on loopback with isolated roots. Across two service starts,
`GET /api/recordings/cardeventnet-IMG_0097/pipeline` returned five stages and
`GET /api/recordings/cardeventnet-IMG_0097/pipeline/lineage` returned five nodes and two processor
runs. Both runs' exact input and output node/revision references matched the migration manifest.
All five exact revision endpoints returned the expected content. The same run graph and revisions
were available after restart. The existing `VisibleCardReviewStore.list_reviews` reader returned
the restored 50-item review before and after restart, with status `draft` and no commands.

The legacy review-scoped HTTP routes were removed during 0108 M11. The current operator path uses
canonical visible-card and virtual-scene data nodes, with revision-bound review records, the
recording workspace, node edit routes, and node review routes. The offline `lineage_draft_migration`
module maps each retained review to its own deterministic visible-card node and, when it contains
scene facts, a separate virtual-scene node. This is the supported recovery path; it does not require
a new HTTP or storage contract. The existing store API read alone did not prove this path. M1 stays
incomplete until the selected review is restored through this importer and verified through the
current workspace and node APIs, including restart and edit/readback.
## Exact cleanup plan

The [machine-readable cleanup plan](0115-M1_Recovery_and_Cleanup_Plan.artifacts/cleanup-plan.json)
lists each exact candidate path, digest, size, matching protected intake path, exclusions, unknown
references, recovery location, disk needs, and expiry conditions. A streaming SHA-256 check
compared all 51 recovery-video files (14,516,434,567 logical bytes) with the accepted-stage
manifest and corresponding intake files. Every hash and byte length matched. These are individual
M3 candidates only; this does not authorize deletion of any file or recovery root.

The accepted-loss stage remains at
`data/operations-recovery/0108-m10-20261105/migration-stage-accepted-loss` in the main checkout.
Its activation manifest and snapshot digest were rechecked. This is a durable local recovery
location on the same volume, not an off-volume backup. Keep it until M3 completes a full dependency
audit and recovery drill. The plan also preserves the 137 item histories, 13 intermediate draft
histories, and three processor-run records that M10 reports as uncertain. The two restored selected
runs do not resolve those three other missing-run records.

The exact 0097 restore required 302,193,776 bytes for its recording bundle, 10,891,987 bytes of
migration resources, 1,404,947 bytes for its calibration resource, and 3,813,905 bytes for the two
persisted run directories. `df -h` showed 73 GiB available before and after the bounded restore. A
full copy of the 24.1 GiB 0108 recovery root was not attempted. Physical APFS allocation and any
future deletion's actual free-space gain remain unknown. The shared UV cache measured 2.4 GiB. I
removed the inference virtual environment created for the model check and did not prune the cache
or other data. The APFS clone's physical allocation remains unknown.
## Reproduction and evidence

Run the bounded static checks from a checkout with the ignored data roots:

```sh
mise exec -- uv run --project backend python scripts/verify_0115_recovery.py \
  --data-root /path/to/main/data \
  --runtime-root /path/to/main/.runtime \
  --output /tmp/0115-recovery-validation.json
```

The checked summaries are in [recovery-validation.json](0115-M1_Recovery_and_Cleanup_Plan.artifacts/recovery-validation.json),
[selected-chain-validation.json](0115-M1_Recovery_and_Cleanup_Plan.artifacts/selected-chain-validation.json),
and [video-comparisons.json](0115-M1_Recovery_and_Cleanup_Plan.artifacts/video-comparisons.json).
The API process, restored run chain, review-store reads, and model loader were temporary checks;
the test copy was removed. Do not treat this evidence as full-corpus recovery or deletion approval.

## Remaining acceptance gaps

- The selected independent review has not yet been restored as its canonical visible-card and
  virtual-scene nodes and verified through the current workspace and node-review APIs. This uses
  the existing 0108 M11 importer and contracts; no new route or storage contract is in scope.
- The accepted-loss migration stage is the verified local recovery location. It shares the source
  volume, and its physical APFS allocation and full-root recovery cost remain unknown.
- Full path-level reference analysis for the other recovery snapshots remains open. The 51 video
  files match their intake originals, but M3 must still check all snapshot references and prove its
  recovery drill before any deletion.
M1 remains **In Progress**. No data was deleted or changed in the authoritative store.
