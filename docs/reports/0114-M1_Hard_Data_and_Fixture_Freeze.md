# Epic 0114 M1: hard-data inventory and fixture work

Date: 2026-11-07
Scope: bounded metadata discovery, local hard examples, and seeded disposable storage.

## Metadata inventory and selection

The inventory read only the 1,006 `manifest.json` files under
`data/operations/pipeline-nodes` and used file sizes for the selected node. It did not parse all
retained revisions, derived views, or operation artifacts. All 1,006 node manifests parsed. The
nodes cover 234 event, 392 visible-card, 201 visual-identity, 138 card-scene-proposal, 7
table-observation, and 34 virtual-scene data sets.

| Observed dimension | Largest metadata value | Selection evidence |
| --- | ---: | --- |
| Source video bytes | 1,061,930,405 bytes | `game-2026-08-20-01-005`; selected hard example |
| Source video duration | 520,753,000 microseconds | `cardeventnet-IMG_0670`; separate duration stress candidate |
| Node manifest count | 1,006 | Exact bounded manifest root inventory |
| Selected hard media node | 8,282-byte event revision | Node `5606e120-028e-52d0-9e1a-b1fafdbc23ee`, exact head `dd991694-5b35-5bfd-924b-1d84bee6a16c`, with the maximum-size source video |
| Selected data lineage | 4 nodes; 2 branches share one copied source and one branch has a later revision | `cardeventnet-IMG_0650`; every node, head, and revision is in the frozen asset set |
| Job history | 0 JSON job records in `data/operations/jobs` | Current checkout has only its owner lock; use seeded growth for reproducible job sizes |

The two largest source dimensions belong to different recordings. This preserves the distinction
between transfer size and duration. A second bounded pass statted all 1,223 node revision files
(1,361,640,622 bytes total), grouped node manifests by recording and content type, and measured
draft files under the exact calibration-draft root. It parsed only the largest candidate per data
type with the application parsers.

| Dimension | Observed maximum | Exact candidate and validation |
| --- | ---: | --- |
| Visual identity payload | 16,005,605 bytes; 226 outcomes and 5,160 identity candidates | Node `e0d2e2fb-53ab-59c5-8991-3aba74f828ae`, revision `f78c1e0a-2c0f-5312-98d6-b0b9b6650c0e`; `parse_visual_identity_data_bytes` passed |
| Visible-card polygon payload | 12,136,454 bytes; 49 outcomes, 327 polygons, and 226 identity candidates | Node `b5090a82-d8ba-5714-a66b-6ee4e4e707f1`, revision `dd8b1436-cf47-5104-87c6-6b2b0cc4c572`; `parse_visible_card_data_bytes` passed |
| Proposed scene payload | 5,532,993 bytes; 50 frames and 289 poses | Node `fea60b6f-a408-5efe-800f-483067026612`, revision `88353478-23a2-5add-a837-9fd2dec54039`; `parse_proposed_card_scene_data_bytes` passed |
| Calibration review draft | 180,869 bytes; 51 source frame digests | `cardeventnet-IMG_0655`, draft `calibration-draft-card-scene-proposals-card-scene-proposal-0086-91x59-IMG_0655-retry-65bb8ec7-attempt-1`; `CalibrationDraft.from_mapping` passed |
| Same-recording visible-card node count | 18 nodes | `cardeventnet-IMG_0650`; selected heads show two copies of one source node and one further copied revision |
| Revisions per node | 3 | Maximum statted revision-directory count; generated `deep_lineage` profile validates 384 revisions on one node through `PipelineNodeStore` |

The selected scene-proposal maximum is an inventory candidate, but it is not part of the frozen
snapshot. It names detector revision `visible-cards-89cd0940-fd94-4e44-b07f-a4fbf96efd87-attempt-1`
and calibration revision `calibration-8732f5afcb52683bce7e50e7`, which do not have a verified
transitive source in this checkout. The selected visible-card data freezes the largest polygon and
identity payload with complete source media and revision history instead. The 1.7 GB pipeline-node
root and 6.5 GB derived-view root are local storage sizes, not copied fixture sizes.

## Frozen local snapshot

The source manifest freezes 42 exact assets across four recording bundles, seven pipeline nodes,
their saved revisions, one calibration revision, and the largest calibration review draft. It
includes the 1,061,930,405-byte source video, the 16,005,605-byte identity revision, the 12,136,454-
byte visible-card polygon revision, the four-node shared-copy branch, and the 180,869-byte draft.
All parent revisions for the two large data nodes are included. The validator loads bundles through
`RecordingBundleStore`, nodes and content through `PipelineNodeStore`, copy applicability through
`PipelineNodeReviews`, and calibration data through `CalibrationRevisionStore` and
`CalibrationDraftStore`. It checks exact IDs, schema, hashes, media identity, revision closure, and
copy lineage. It stores hashed bytes under
`~/.cache/doko-detector/interactive-performance/sha256/<sha256>`. On the same volume, import uses
hard links to avoid a second 1.9 GB copy; it falls back to byte copies on other volumes. Validation
reconstructs a temporary read-only snapshot from those links. The import does not alter live review
or operations data.

Commands from the repository root:

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --import-hard
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard
```

Missing assets, hash mismatches, schema mismatches, and lineage or media identity mismatches return
an error. A full qualification command must pass `--require-hard`; it must not skip this case.

## Seeded generated tier

The generator uses seed `11401`. The `small`, `representative`, `hard`, and `stress` profiles grow
recordings, nodes, revisions, job records, and result items. It also has independent profiles:
`many_recordings`, `many_nodes`, `deep_lineage`, `job_history`, and `large_result`. Each recording
has a deterministic 64 KiB media asset. A result-size profile puts the largest item count in one
revision. The generator uses `PipelineNodeStore.create` and `save` for production node envelopes,
valid events, parent revisions, and shared-copy lineage. It writes jobs with the production `Job`
model, validates every record with `Job.model_validate_json`, and checks first and last records
through `JobManager.get`. Every file is SHA-256 listed. Validation checks file integrity, exact
media dependencies, every node and revision through the store, transitive parent and copy
references, and job model fields.

Generated fixtures use disposable output only. The target must be empty. With no `--output`, the
tool creates a new temporary directory. It does not read developer storage. Reproducibility check:

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --profile small --output /tmp/doko-perf-one
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --profile small --output /tmp/doko-perf-two
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --validate /tmp/doko-perf-one
```

Compare generated files byte-for-byte. Deleting a required file or breaking a parent, copy, or
media reference makes validation fail. These generated records are workload fixtures, not reviewed
domain data or a performance baseline. A clean checkout can run generated profiles without the
local hard asset cache. A full qualification run must also pass `--require-hard`; it must fail when
one of the pinned local assets is absent.

## Checks

- `find data/operations/pipeline-nodes -name manifest.json -type f | wc -l` — 1,006.
- Bounded Python metadata pass over those manifests — 1,006 parsed; ranks above reproduced.
- Hard asset SHA-256 inventory — all 42 pinned hashes and byte lengths match local source bytes.
- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_performance_fixtures.py`
  — PASS, 5 tests, including reproducibility, missing media, broken lineage, missing hard asset,
  and refusal to write generated fixtures inside the repository.
- `mise exec -- uv run --project backend ruff check backend/scripts/materialize_interactive_ui_performance_fixtures.py backend/tests/test_interactive_ui_performance_fixtures.py`
  — PASS.
- Two independently generated small profiles compared byte-for-byte with `diff -qr` — PASS.
- Representative profile materialization and production validation — PASS, 901 assets.
- Independent `many_recordings`, `many_nodes`, `deep_lineage`, `job_history`, and `large_result`
  profiles materialized and passed their production validations.
- `--import-hard` and `--require-hard` — PASS, all 42 assets; production bundle, node, lineage, and
  calibration readers accepted the reconstructed snapshot.
- No timings or fixes were selected in M1.
