# Epic 0118 M3: 0070 synthetic training view

Date: 2026-11-09

## Result

The selected family is the frozen Epic 0070 M5 50/50 training view at
`.runtime/synthetic-visible-region-0070-m5-50-50-view/`. Keep it. The view remains an input to the
0071 cluster-crop materializer. No expiry condition or removal is justified. No stored data changed.

## Creator, inputs, and authority

The 0070 training-view command builds its manifest through
`operations/src/doko_operations/synthetic_visible_region_training_view.py` and
`build_synthetic_visible_region_training_view`. Its exact manifest is
`data/operations/synthetic-visible-region-0070-m5-50-50-training-view.json`, digest
`2b30c3bc5e1a9c2fd675f95117a1ba25dba6d5ea122fa85e5ab257958c004e63`, file SHA-256
`09f64d5c1ddb890738e4e074342f21e09cc53479b31aa5661de2e0ae72e66361`. The materialized view has
1,328 files, 539,044,062 logical bytes, and 529,088 KiB path allocation. Summed `st_blocks` is
541,786,112 bytes. These are path measurements; unique APFS allocation and physical reclamation
are unknown.

The exact dependency roots and identities are:

| Root or record | Dependency identity |
| --- | --- |
| `data/operations/synthetic-visible-region-0070-m0-manifest.json` | Manifest digest `3dc48add8caadd341772c7a15bbe5a208a19dab8debd342ab267eea942540ebc`; file SHA-256 `7ecfad95b37f524c51555032e53f8186460e59a079a0fdae7a7476c48cee5369` |
| `data/operations/synthetic-visible-region-0070-m1-empty-table-approvals-inputs.json` | Manifest digest `100da710761123383d5d8080b168bbec8c6aad62768a38b9ffcffbef24c368a1`; file SHA-256 `fec93e1d8beb563c1d85c77b53f1900239e5ef5080727a0bd150d7c4c6b2db54` |
| `.runtime/synthetic-visible-region-0070-m1-empty-table-approvals/` and paths in the M1 manifest | 108 source images, 9 reviewed backgrounds, and 165 reviewed cutouts. The M1 manifest pins file hashes. |
| `data/operations/synthetic-visible-region-0070-planar-geometry-production.json` | Manifest digest `96cbcf303127a8ec88b50b618e1d1988d33e412a0d7e984c8296867cc3e6e998`; file SHA-256 `171b20427fba4543fcf2c969d6777c49564745fb0d4b8e995b898240cad306a1` |
| `.runtime/synthetic-visible-region-0070-planar-geometry-production/` | 537 scene images and 537 receipts. Each M2 scene records an accepted empty-table review, a calibration digest, and a receipt path and digest. |
| `.runtime/rfdetr-segmentation-0068/materialization.json` and its root | Materialization digest `77917cb543dc6de02277219c970b2d529dfad4dfc8197944b7d4e514912839a0`; manifest file SHA-256 `58e56b857c0481ff1ec5587e0dd3c5fea3e555e1cfdc8bc9dde3425740913c7f`; train COCO SHA-256 `ded263a476640ad529393f1665382fb5656a26355d0ea765932450cd9ea8083b`. The materialization contains 24 source-video references and its 0068 campaign manifest link. The verifier checked each source-video length and SHA-256. |

M1 records reviewed source decisions and file hashes. M2 binds each of its 537 receipt digests to a
scene and retains the accepted empty-table decision, calibration digest, and placement data. The
training-view manifest also binds these roots to the 0068 reviewed real-data materialization.
The synthetic rows remain synthetic training evidence. They do not replace reviewed references.
The 0071 reader validates its own training-view schema and digest, COCO rows, synthetic image
hashes, and receipt self-digests. It does not check the M0, M1, or M2 manifest file links or compare
the M2 receipt digest listed in each scene summary. The independent verifier linked below performs
those checks and verifies each M1 source/review file, M2 scene image, and receipt.

## Consumers, run references, and retention decision

The 0071 M4 cluster-crop materializer reads the frozen view through
`operations/src/doko_operations/rfdetr_cluster_crop_materialization.py` and its
`_load_synthetic_input` path. Its default points to
`.runtime/synthetic-visible-region-0070-m4-50-50/synthetic-candidate-view`, whose train, validation,
and sealed-test links resolve to this view. The retained comparison record is
`data/operations/synthetic-visible-region-0070-m4-50-50-training-comparison.json`, digest
`03963a7378c166502409e10abe79988b41989d08968b28e78a28419f5d6459e9`. It records completed
control run `rfdetr-visible-card-detector-m2-training-1789859828` at
`.runtime/synthetic-visible-region-0070-m4-50-50/control/bundle` (bundle digest
`504b41a34056108df5882fcd334de6d894fbc02a5eda63b101e545d41779cd49`, manifest SHA-256
`691df8b923b7ad24a74a8f038fe81038bed631e1226a3362b13fed6afb0fe8db`, checkpoint SHA-256
`4274a4e8cb79d186adf91b60a0b870d59e3e9100f9129d40d5561625a3fba088`) and synthetic-addition run
`rfdetr-visible-card-detector-m2-training-1789893357` at
`.runtime/synthetic-visible-region-0070-m4-50-50/synthetic-addition/bundle` (bundle digest
`089169e22aa1ce588971ac48b36f299a2b47162d53a6d2b59aeb87dd3f8e841e`, manifest SHA-256
`34f05ee095fffdd81d4f00aacfe559b1f15a0f4a4d77c925e8d34ab555daa288`, checkpoint SHA-256
`60f65bd6c72a359216650ef8031172a1d7b60264ede799046173e69348a4fa6b`). The 0070 decision remains
`retain_as_experiment`. Current live process pins were not inspected. No campaign-log or output-log
files are part of this contract.

The view may be regenerated by the recorded training-view builder only if its exact frozen
manifests, 0068 materialization, reviewed M1 inputs, M2 calibration and scene receipts, and original
source data remain available. Exact byte regeneration has not been tested. Do not expire it by age
or run completion. Reconsider retention
only after the owner changes the experiment decision, the 0071 consumer no longer reads this input,
all run and model references are rechecked, and an independently stored restore source passes the
same dependency and reader checks. This is a prerequisite list, not removal authorization.

## Disposable restore rehearsal

Reproduce the disposable restore and dependency check from the repository root:

```sh
cp -cR .runtime/synthetic-visible-region-0070-m5-50-50-view /tmp/0118-m3-campaign-view
mise exec -- uv run --project operations python \
  docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/verify_0118_m3.py \
  --repository "$PWD" --restored-view /tmp/0118-m3-campaign-view
```

The [independent verifier](0118-M3_0070_Synthetic_Training_View.artifacts/verify_0118_m3.py)
checks the frozen M0/M1/M2 manifest file and content digests; all 447 M1 accepted source/review
files; all 537 M2 scene image and receipt links and digests; all 789 files in the 0068
materialization and all 24 source-video byte lengths and SHA-256 values; the 0070 comparison and
run/bundle/checkpoint references; and every restored view file by path, length, and SHA-256.
It then calls the actual 0071 `_load_synthetic_input` reader. Two fresh processes passed. Both
checked 1,328 restored files (539,044,062 logical bytes), 537 rows, and train COCO SHA-256
`36cb12e81c4162a88d154ace161424e9428e2b7caabba416a83397bc64d59212`; all manifest and run
identities matched the table above. The rehearsal used the canonical retained source, review,
calibration, and receipt roots; it did not copy or qualify an independent backup of those
dependencies. It verifies this restore and reader path, not full regeneration.

No expiry or removal is authorized. Logical bytes, path allocation, and summed allocated blocks are
reported separately. Physical APFS allocation, off-volume recovery, live pins, and exact byte
regeneration remain unknown.

## Checks

- `mise exec -- uv run --project operations python docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/verify_0118_m3.py --repository /Users/niklas.sparfeld/Developer/doko_detector --restored-view /tmp/0118-m3-verified-view-20261109` — passed twice. It checked all manifest, source, review, calibration, receipt, model, run, and restored-file references listed above.
- `git diff --check` and changed Markdown link validation — passed.

No authoritative data changed.
