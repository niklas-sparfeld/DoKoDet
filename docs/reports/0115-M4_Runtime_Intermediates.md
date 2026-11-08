# Epic 0115 M4: runtime intermediates

## Frozen scope before apply

M4 targets the highest-ranked training-input family that is unused by active work in M0:
`.runtime/synthetic-visible-region-0070-all-recordings-training-v2/campaign-dataset`. The actual
root is present in the main worktree, not this detached worktree. It belongs to the completed
`0068-m0-reviewed-rfdetr-local-visible-card-detector` run
`rfdetr-visible-card-detector-m2-training-1789830871`, recorded at code revision
`2009f52efc22a7391705678f3d06520b8bb81b1f`. The run is complete and has no next stage. The
producer and inventory are the only source-code/report references found in the bounded search.

Remove only these two regular COCO annotation files:

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `campaign-dataset/train/_annotations.coco.json` | 2,648,785 | `33dcd06af3a846ed07e2c1fbc9b0037a078d8494df3bd4adf3ba7ae35722b8b8` |
| `campaign-dataset/valid/_annotations.coco.json` | 522,537 | `75f291f89ee00edfebe85ea31a787ebeefafe6cbcb4807ff3560e9cf3b4cc7ab` |

The frozen deletion is 3,171,322 logical bytes in two files. Keep `subset.json`, all 718 image
symlinks and their targets, the intact training-view, every checkpoint, the `bundle/`, run and
training configuration, metrics, and memory log. Keep the sibling 50/50 experiment and all
configured bundles. This scope does not retire the full 1.9 GiB root.

Before apply, require: exact dependency search; the exact 0070 bundle is absent from configured
model and iOS export inputs; run/review and split provenance is retained; the two candidate hashes
match; the training-view and every linked target exist; no active writer or open file is present;
and the M2 dry-run permits only these two files. After apply, compare the retained root manifest,
logical bytes, regular-file and symlink counts, and retained bundle/model hashes. Load retained
bundles and run a bounded deterministic probe. Do not retrain or call a paid provider.

The milestone commit contains the pre/post evidence, provenance summary, report, epic, and board.
No code or storage contract changes are in scope.

## Provenance and reconstruction limits

`run.json`, `subset.json`, `training_config.json`, `metrics.csv`, the bundle manifest, and the
checkpoint remain. They record split image and annotation IDs, recording IDs, the materialization
and subset digests, campaign manifest digest, preprocessing configuration, seed, code revision,
RF-DETR / Torch / TorchVision / Supervision versions, selected checkpoint digest, and validation
metrics. The two annotation file digests above are recorded here. The 718 symlink targets remain in
the separate training-view. The run's preprocessing source is still available at its recorded Git
revision, which matches the current materializer source. The retained view and recorded versions
identify the annotation generation path. Exact byte reconstruction of the two COCO files was not
run, so full input-byte reconstruction remains unverified. The saved hashes preserve their exact
former identity. This is not a claim that the complete training run can be reproduced without its
original environment and intermediate checkpoints.

## Checks and result

The `cleanup_0115.py` dry-run permitted exactly the two frozen files. Its apply receipt reports
`complete` and records both removals. The helper's open-file check found no file open below the
selected root immediately before apply. A separate `lsof +D` check also returned no open files.
No training or provider request ran.

The [preflight provenance](0115-M4_Runtime_Intermediates.artifacts/preflight-provenance.json)
preserves 718 unique reviewed source frame hashes, 21 source/review revision IDs, 20 source groups,
20 source-video hashes, and 1,985 target-geometry hashes, with the original split and annotation
membership in the retained `run.json`. The training view passed its materialization verifier after
apply with digest `db1f43ae99d07d00896a9d5668b84f01bc93d5b3dbf4b935f00382065efdc709`; all 718
symlink targets existed before apply and remain. The retained bundle and the configured 0092 bundle
both loaded. Each returned `status=ok` twice for the same deterministic 432x432 gray PNG; proposal
and pile results matched across repeats. The [probe receipt](0115-M4_Runtime_Intermediates.artifacts/postflight-probes.json)
records exact bundle and output digests. The 0092 bundle digest was
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`.

The exact postflight manifest of all remaining files, symlink targets, and directories matches the
preflight manifest after excluding only the two authorized paths. The retained-root manifest
digest is `f2e4db809ad6a90bd5fcfe8ee7b33704e017a40f6eda2560792b3f77724bfaea`; see the
[preflight manifest](0115-M4_Runtime_Intermediates.artifacts/preflight-root-manifest.json),
[postflight manifest](0115-M4_Runtime_Intermediates.artifacts/postflight-root-manifest.json), and
[retirement receipt](0115-M4_Runtime_Intermediates.artifacts/retirement-receipt.json). The
[checkpoint audit](0115-M4_Runtime_Intermediates.artifacts/checkpoint-audit.json) records the
different checkpoint hashes and the exact selected-checkpoint copy in `bundle/`. The root had
15 regular files and 718 symlinks before, and has 13 regular files and the same 718 symlinks after.
Its logical regular-file bytes fell from 1,988,142,489 to 1,984,971,167. `du -sk` measured
1,941,588 KiB before and 1,938,492 KiB after; cleanup plan, receipt, and lock files are in the
post-apply directory measurement, so this is not a free-space claim.

The dependency search found the candidate path and bundle digest only in the training producer and
0115 inventory; exact path and digest searches in tracked model/iOS source and operation/recovery
records found no active consumer. The configured example points to the separate 0092 bundle.
The main worktree currently contains unrelated uncommitted changes in `AGENTS.md` and
`docs/workflows/epic-execution.md`; neither file was changed by M4. The 0070 root remains about
1.9 GiB. All checkpoint files have distinct hashes except the exact selected checkpoint duplicated
in `bundle/`; retain the other checkpoint variants, bundle, metrics, run and training configuration,
split record, and image links. The separate 0070 50/50 experiment has distinct control and synthetic
bundle digests. The 0092 run supplies the active 0096 bundle. The derived-view cache has active
readers and writers; Gemini responses have unresolved replay value and cost; and 0114 hard assets
remain pinned until qualification. These are retained follow-ups for their named milestones, not
part of M4. This M4 removed the unused COCO input manifests only; it did not retire the entire
training run or claim its 1.9 GiB as savings.

## Other M0 training and cache candidates

| M0 candidate | M4 disposition and reason |
| --- | --- |
| `.runtime/rfdetr-segmentation-0092-m4` (3.5 GiB) | Retain. Its selected bundle is the active 0096 M4 input. The five checkpoints have distinct hashes and this milestone did not establish that the other checkpoints are disposable. |
| `.runtime/synthetic-visible-region-0070-all-recordings-training-v2` (1.9 GiB) | Remove only the two COCO input manifests described above. Retain the selected unreviewed bundle, all distinct checkpoint states, metrics, input memberships, and image links. |
| `.runtime/synthetic-visible-region-0070-m4-50-50` (3.7 GiB) | Retain. It contains separate control and synthetic-addition experiments with distinct bundle digests and non-duplicate checkpoint sets. |
| `.runtime/pipeline/derived-views` (6.5 GiB) | Retain for M9. Active readers and writers depend on its keyed cache; M9 must prove regeneration and expiry first. |
| `.runtime/gemini-cache` (2.7 GiB) | Retain for M9. Provider replay value and cost remain unmeasured. |
| 0114 hard-fixture assets (1.84 GiB external cache) | Retain until M11 completes exact fixture qualification. |

M0 did not rank an abandoned or failed training run above these candidates. M4 did not delete other
historical runtime outputs. The ranked families have these exact completion and retention facts:

- `rfdetr-segmentation-0092-m4` measured 3,632,944 KiB, 29 regular files, and 1,748 symlinks.
  Its `run.json` records completed run `rfdetr-segmentation-m3-training-1792096060`, campaign
  manifest digest `bd452cc3…`, code revision `d867c1e0…`, materialization digest `af5d8feb…`,
  subset digest `7ff2ebbd…`, and 874 train plus 874 validation images. Its selected bundle digest
  `05fa6d14…` is referenced by the active 0096 M4 path. Two earlier attempt receipts say
  `interrupted_without_run_receipt`; both resumed the same output from the exact same `last.ckpt`
  digest `aafd6804…` at epochs 5 / steps 1299 and 1099. The final run completed and has no next
  stage. Keep the final bundle, exact run and split provenance, and interruption receipts because
  the bundle is active and the attempt lineage explains how it was produced. See the
  [ranked-family audit](0115-M4_Runtime_Intermediates.artifacts/historical-training-family-audit.json).
- The 0070 all-recordings run measured 1,938,492 KiB after M4, 13 data files, and 718 symlinks.
  Run and bundle manifests record its completed status, input digests, split, code, versions, and
  metrics. The COCO files were the only removed inputs. The selected bundle is marked unreviewed;
  no promotion or candidate-retirement decision exists. Retain its distinct checkpoint states and
  model output until a bounded model-candidate disposition exists.
- The 0070 50/50 root measured 3,919,360 KiB, 48 regular files, and 1,907 symlinks. Its control
  and synthetic-addition runs both completed with distinct run, materialization, subset, checkpoint,
  and bundle digests (`504b41a3…` and `089169e2…`). The synthetic candidate view is an input to the
  current cluster-crop materializer. The retained M6 annotation-effort decision says
  `retain_as_experiment`, does not promote a provider or change runtime defaults, and records that
  no legal development batch exists. Keep both experiment outputs, their input views, metrics, and
  split facts for that frozen comparison decision. The ranked-family audit stores each exact run,
  bundle, dataset digest, and measured path.

The two interrupted 0092 attempts are not separate failed experiments: both receipts point to one
completed 0092 output and one resumed checkpoint. The control and synthetic-addition 0070 runs are
separate completed experiments; neither is an abandoned run. This M4 inventory covers the three
training families ranked by M0. Other historical runtime folders outside those M0 candidates were
not selected or removed in this bounded milestone.
