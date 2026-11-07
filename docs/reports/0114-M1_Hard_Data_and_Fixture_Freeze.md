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
| Selected hard revision | 2,641,025 bytes; 40 frames | `bcf3f325-e35e-5bc0-b276-fa4e33aa874d`, `card_scene_proposals` |
| Selected data lineage | 1 exact node and revision | Node `f3391fc3-049b-5fc2-ab40-30ea381d946e`; its source video identity is checked against the recording bundle |
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
| Revisions per node | 3 | Maximum statted revision-directory count; generated fixtures do not yet reproduce this with application lineage |

The 18-node group gives a fan-out candidate, but it is not yet a frozen transitive fixture. The
selected scene-proposal revision names a detector revision and calibration revision whose assets
are absent from the hard snapshot. The selected calibration draft names a base calibration
revision that is also absent. The 1.7 GB pipeline-node root and 6.5 GB derived-view root are local
storage sizes, not copied fixture sizes.

## Frozen local snapshot

The hard snapshot freezes the exact repository bundle, source record, 1,061,930,405-byte MOV,
pipeline node manifest, head, and exact revision listed in the fixture script. The manifest hashes
bind each byte asset. The validator checks the repository-bundle and source-record schemas, node
and revision schemas, node-to-recording identity, video SHA-256 and size, exact head revision, and
revision content digest. It stores files under
`~/.cache/doko-detector/interactive-performance/sha256/<sha256>`. On the same volume, import uses
hard links to avoid another 1 GB copy; it falls back to a byte copy on other volumes. The snapshot
does not alter live review or operations data.

Commands from the repository root:

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --import-hard
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard
```

Missing assets, hash mismatches, schema mismatches, and lineage or media identity mismatches return
an error. A full qualification command must pass `--require-hard`; it must not skip this case.

## Seeded generated tier

The generator uses seed `11401`. Its frozen `small`, `representative`, `hard`, and `stress` profiles
contain respectively 4/24/96/384 recordings, 8/96/480/1,920 nodes, 16/288/1,920/9,600 revisions,
12/300/2,500/10,000 jobs, and a separate largest result of 20/120/600/1,200 items. Each recording
has a 64 KiB deterministic media asset. The largest item count appears once per profile so result
payload size does not multiply by every node and revision. Every file is SHA-256 listed in the
fixture manifest. The generator validates hashes, lengths, recording dependencies, lineage node
and revision closure, and media membership.

Generated fixtures use disposable output only. The target must be empty. With no `--output`, the
tool creates a new temporary directory. It does not read developer storage. Reproducibility check:

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --profile small --output /tmp/doko-perf-one
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --profile small --output /tmp/doko-perf-two
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --validate /tmp/doko-perf-one
```

Compare the generated files byte-for-byte. Deleting a required file makes validation fail with its
path. These generated records are storage workload fixtures, not reviewed domain data or a
performance baseline. A clean checkout can run this tier without the local hard asset cache.

## Correction: M1 is incomplete

The first M1 commit marked this milestone complete too early. The materializer writes its own
pipeline-node and job-shaped JSON. It does not use application stores. Its node manifest has fields
that strict `PipelineNodeStore` rejects, its head adds a rejected field, and its revision files omit
the required `pipeline-node-revision/v1` envelope and revision digest. Its job records fail the
strict `Job` model. The current tests validate only the materializer's private schema; they do not
establish application-schema validity.

The manifest pins one scene-proposal snapshot, but that revision references a detector revision
(`visible-cards-89cd0940-fd94-4e44-b07f-a4fbf96efd87-attempt-1`) and calibration revision
(`calibration-8732f5afcb52683bce7e50e7`) that are absent from the asset set. It does not pin the
measured largest identity, visible-card polygon, or review-draft candidates. Those require exact
asset hashes, media identity, and complete parent, copy, and input lineage before timing.

M1 remains incomplete. The next change must build seeded data through application schemas or real
stores, pin the exact selected examples and their dependency closure, then validate them with the
production parsers and lineage readers. Do not start M2 against the current fixture corpus.

## Checks

- `find data/operations/pipeline-nodes -name manifest.json -type f | wc -l` — 1,006.
- Bounded Python metadata pass over those manifests — 1,006 parsed; ranks above reproduced.
- Hard asset SHA-256 inventory — all six pinned hashes match the local source bytes.
- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_performance_fixtures.py`
  — PASS, 5 tests, including reproducibility, missing media, broken lineage, missing hard asset,
  and refusal to write generated fixtures inside the repository.
- `mise exec -- uv run --project backend ruff check backend/scripts/materialize_interactive_ui_performance_fixtures.py backend/tests/test_interactive_ui_performance_fixtures.py`
  — PASS.
- Two independently generated small profiles compared byte-for-byte with `diff -qr` — PASS.
- Representative profile materialization and built-in validation — PASS, 805 assets.
- `--import-hard` and `--require-hard` — PASS, all six local content-addressed assets.
- No timings or fixes were selected in M1. The checks above pass for the fixture script's private
  contract only; they do not close the application-schema and dependency-closure gaps above.
