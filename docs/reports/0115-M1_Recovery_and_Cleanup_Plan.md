# Epic 0115 M1: recovery evidence and cleanup plan

Date: 2026-11-08

Code revision: `63c5953f662728e09c5124ade19d8df52218d6a6`

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
about 1 GiB RSS. I stopped it and used the smaller dependency-complete set above. The bounded
lineage API returned no processor-run records. I did not restore the run store or prove the full
run-parent/output chain through the service API. This is an acceptance gap.

## Exact cleanup plan

The [machine-readable cleanup plan](0115-M1_Recovery_and_Cleanup_Plan.artifacts/cleanup-plan.json)
lists the exact paths, reasons, unknown references, current recovery location, disk requirements,
and expiry conditions. One file is a candidate for M3 only:

`data/operations-recovery/0108-m10-20261105/recording-videos/data/intake/recordings/game-2026-08-20-01-005/videos/game-2026-08-20-01-005-video.mov`

Its 1,061,930,405 bytes have SHA-256
`b8daa5ac29ce330c5859d4c8825a60457e734b4b11d1b8e3ab6556217268ce73`, matching the protected
intake copy. All other recovery snapshots and video files remain excluded because M1 did not prove
their full dependency and recovery roles. The plan records the 137 item histories, 13 intermediate
draft histories, and three processor-run records that M10 reports as uncertain.

The verified temporary restores were removed after the checks. The authoritative active data and
0108 packages remain in the main checkout. A full copy of the 24.1 GiB 0108 recovery root was not
attempted. Available space readings changed from 39 GiB at the start to a 3.1 GiB low watermark,
then 73 GiB at the latest check; the cause of this fluctuation is unknown. The shared UV cache
measured 2.4 GiB. I removed the inference virtual environment created for the model check and did
not prune the cache or other data. The APFS clone's physical allocation and any future deletion's
actual free-space gain remain unknown.

## Reproduction and evidence

Run the bounded static checks from a checkout with the ignored data roots:

```sh
mise exec -- uv run --project backend python scripts/verify_0115_recovery.py \
  --data-root /path/to/main/data \
  --runtime-root /path/to/main/.runtime \
  --output /tmp/0115-recovery-validation.json
```

The checked summary is in [recovery-validation.json](0115-M1_Recovery_and_Cleanup_Plan.artifacts/recovery-validation.json).
The API process, edited revision, restart receipt, review-store reads, and model loader were
temporary checks; the test copy was removed. Do not treat this evidence as full-corpus recovery,
run-chain verification, or deletion approval.

## Remaining acceptance gaps

- Restore and read the selected processor runs and their exact graph inputs/outputs through the
  disposable service, including after restart.
- Verify that the independent review's complete proposal, detector, calibration, and source
  dependencies are exposed through the intended runtime API, not only the retained review store.
- Establish a durable recovery location and exact physical space needs before any M3 apply step.
- Finish full path-level reference analysis for the remaining recovery snapshots and 50 unchecked
  video files.

M1 remains **In Progress**. No data was deleted or changed in the authoritative store.
