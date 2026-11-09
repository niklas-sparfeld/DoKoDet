# Epic 0118 M3: 0070 synthetic training view

Date: 2026-11-09

## Result

The selected family is the frozen Epic 0070 M5 50/50 training view at
`.runtime/synthetic-visible-region-0070-m5-50-50-view/`. Keep it. The view remains an input to the
0071 cluster-crop materializer. The bounded M3 investigation is complete. All 24 immutable revision
manifests and contents match. Four present recovery roots contain the exact state hashes for the
same seven recordings; no candidate root contains an exact draft hash. The canonical reference root
is absent. The other 17 exact states and all 24 exact drafts remain unavailable within the search
boundary. No expiry condition or removal is justified. Preserve the view and all available review
data. No stored data changed.

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
The exact 0068 review references are in `data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json`.
Their archived roots are under
`data/operations-recovery/0108-m10-20261105/migration-stage-accepted-loss/evidence/operations/`:
`pipeline/revisions/<revision-id>/manifest.json` and `content.json`, plus
`pipeline-references/<recording-id>/visible_cards/state.json` and `draft.json`. The canonical
`data/operations/pipeline-references/` root is absent. The archive has all 24 expected revision
manifest hashes and content hashes, 7 of 24 expected state hashes, and 0 of 24 expected draft
hashes. For `cardeventnet-IMG_0090`, the expected state/draft hashes are
`2000bfa9401de0c3ac11cb43caf5856912faace04761beefd2d34266c5f8adc7` and
`c52a97ed072f0689c502891aeaab34985c0ce6a5f4dcb4969b3517eba75a3c70`; archived values are
`efcbb8ec2e68eb53635f150d663c44899af240cf3f8e769c941538417853ed11` and
`87225bb692f635d9a306e24e93bada07a70fc65dae70998db52f773d8e8f5d66`. These are different human
review state and draft bytes. The frozen manifest preserves their former digests, but not those
exact bytes. This gap prevents a complete review-dependency check and blocks an expiry decision.

The M2 manifest pins nine calibration digests. The audit maps all nine to M2 calibration records;
all 537 scene calibration links match both a calibration record and the corresponding receipt.
The 0071 reader validates its own training-view schema and digest, COCO rows, synthetic image
hashes, and receipt self-digests. It does not check the M0/M1/M2 manifest file links, M0 review
reference hashes, or compare the M2 receipt digest listed in each scene summary. The independent
audit linked below performs the manifest, receipt, and calibration-link checks and records the
M0 review-reference hash mismatch.

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
  docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/audit_0118_m3.py \
  --repository "$PWD" --restored-view /tmp/0118-m3-campaign-view \
  --evidence docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/reference-dependency-audit.json
```

The [independent audit](0118-M3_0070_Synthetic_Training_View.artifacts/audit_0118_m3.py)
checks the frozen M0/M1/M2 manifest file and content digests; all 447 M1 accepted source/review
files; all 537 M2 scene image and receipt links and digests; all 789 files in the 0068
materialization and all 24 source-video byte lengths and SHA-256 values; the 0070 comparison and
run/bundle/checkpoint references; and every restored view file by path, length, and SHA-256.
It then calls the actual 0071 `_load_synthetic_input` reader. Two fresh processes passed. Both
checked 1,328 restored files (539,044,062 logical bytes), 537 rows, and train COCO SHA-256
`36cb12e81c4162a88d154ace161424e9428e2b7caabba416a83397bc64d59212`; all manifest and run
identities matched the table above. The audit reports the review root mismatch above; it does not
pass the full review-dependency acceptance check. The rehearsal used the canonical retained source,
review, calibration, and receipt roots; it did not copy or qualify an independent backup of those
dependencies. It verifies this restore and reader path, not full regeneration.

The [reference hash audit artifact](0118-M3_0070_Synthetic_Training_View.artifacts/reference-dependency-audit.json)
contains the expected and observed state, draft, revision-manifest, and content hashes for all 24
recordings.

No expiry or removal is authorized. Logical bytes, path allocation, and summed allocated blocks are
reported separately. Physical APFS allocation, off-volume recovery, live pins, and exact byte
regeneration remain unknown.

## Bounded search and legacy review roles

The read-only search checked these manifests and their exact roots:

| Root checked | Source in the records | Result |
| --- | --- | --- |
| `data/operations/pipeline-references/` | Canonical `reference_path` values in the 0068 manifest | Absent |
| `data/operations-recovery/0108-m10-20261105/migration-source/operations/pipeline-references/` | `inventory-config.json` maps `root_id=operations` to `migration-source/operations`; the inventory plans list 371 reference files under that root | 7/24 exact states; 0/24 exact drafts |
| `data/operations-recovery/0108-m10-20261105/migration-stage/evidence/operations/pipeline-references/` | `migration-stage/migration.json` lists 371 reference files under `evidence/operations` | 7/24 exact states; 0/24 exact drafts |
| `data/operations-recovery/0108-m10-20261105/migration-stage-accepted-loss/evidence/operations/pipeline-references/` | Selected `migration-stage-accepted-loss/migration.json`; M0 and M2 reports | 7/24 exact states; 0/24 exact drafts |
| `data/operations-recovery/0108-m10-20261105/operations/pipeline-references/` | Same recovery tree's sibling `operations/` contains the archived 0068 and 0070 manifests | 7/24 exact states; 0/24 exact drafts |

The six JSON inventory and recovery records inspected were `inventory-config.json`, `inventory-plan.json`,
`inventory-plan-final.json`, `inventory-plan-accepted-loss.json`,
`migration-stage/migration.json`, and `migration-stage-accepted-loss/migration.json`. The inventory
plans and both migration manifests enumerate 371 `pipeline-references` files with
`root_id=operations`; the config maps the source operations root to `migration-source/operations`.
They identify no additional `pipeline-references` root. No other worktree or filesystem was
searched.

The read-only pass checked raw SHA-256 for all 24 state and 24 draft files under each present root.
Each present root had the same seven exact state files:
`cardeventnet-IMG_0092`, `cardeventnet-IMG_0642`, `cardeventnet-IMG_0644`,
`cardeventnet-IMG_0645`, `cardeventnet-IMG_0646`, `cardeventnet-IMG_0669`, and
`cardeventnet-IMG_0674`. Seventeen state files differed from the expected hash. All 24 draft files
were present but differed from the expected hash. The per-record, per-root expected and observed
hashes are in the [root search audit](0118-M3_0070_Synthetic_Training_View.artifacts/reference-root-search.json).
The prior [reference hash audit](0118-M3_0070_Synthetic_Training_View.artifacts/reference-dependency-audit.json)
also records the accepted-loss archive values and the matching immutable revision hashes. Different
archived state or draft bytes are not substitutes for the expected historical files.

All four present candidate roots and the matching state files are owned by uid 501, gid 20, and
share the active node store's filesystem device. They are local copies on the same volume, not
independent recovery sources.

The legacy contract in `operations/src/doko_operations/pipeline_reference.py` defines
`pipeline-reference-state/v1` and `pipeline-reference-draft/v2`. State stores the draft revision and
status, source revision, and selected completed revision. Draft stores the current mutable review
items, decisions, coverage, impact, and input lineage. The `PipelineReferenceStore` reader validates
the state and draft together and checks their revision and source identities; `get_state` can read
state without loading a draft. For each of the seven exact states, `PipelineReferenceStore.get_state`
read the state and returned the matching `selected_completed_revision_id` in all four roots. The
per-root audit records each selected revision and draft revision. This state-only check supports that
pointer read; it does not restore the full reference. The `PipelineRevisionStore` reader validates
the immutable revision manifest, content digest, content schema, and lineage. The matching immutable
content establishes the reviewed content bytes and their revision identity. It cannot recover the
historical selected pointer or mutable draft contents. No exact draft matches, so no complete
state/draft pair or resumable review can be restored from these candidates. No mutable fact was
inferred from the immutable revision.

This completes the bounded M3 investigation, not full recovery or exact regeneration. Preserve the
training view and every known review/recovery root. M3 authorizes no deletion or expiry. Exact
recovery, independent backup, live pins, off-volume recovery, and physical APFS allocation remain
unknown.

## Checks

- `mise exec -- uv run --project operations python docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/audit_0118_m3.py --repository /Users/niklas.sparfeld/Developer/doko_detector --restored-view /tmp/0118-m3-verified-view-20261109 --evidence docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/reference-dependency-audit.json` — audit completed twice. It verified 24/24 revision manifests and content, 9/9 calibration records and 537/537 scene links, and the restored view. It found only 7/24 expected reference-state hashes and 0/24 expected draft hashes.
- Read-only `audit_campaign_review_references` against the frozen 0068 manifest — 24/24 immutable manifest/content hashes matched; accepted-loss state/draft canonical hashes matched raw file SHA-256 results (7/24 states, 0/24 drafts).
- `PYTHONPATH=backend/src:operations/src mise exec -- uv run --project backend python docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/audit_0118_m3_reference_roots.py --repository /Users/niklas.sparfeld/Developer/doko_detector --output docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/reference-root-search.json` — checked all 24 state/draft pairs under five roots; four present roots each matched seven state hashes and no draft hashes. The state reader returned all seven matching pointers in each root.
- `mise exec -- uv run --project backend ruff check docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/audit_0118_m3_reference_roots.py` and `ruff format --check` — passed.
- `git diff --check` and changed Markdown link validation — passed.

No authoritative data changed. M3 is complete as a bounded investigation with the historical
state/draft gap recorded. No expiry or deletion is authorized.
