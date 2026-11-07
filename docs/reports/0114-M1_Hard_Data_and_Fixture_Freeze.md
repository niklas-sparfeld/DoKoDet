# Epic 0114 M1: hard-data inventory and fixture freeze

Date: 2026-11-07
Scope: bounded metadata discovery, a frozen local example, and seeded disposable storage.

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
between transfer size and duration. Polygon payload, review draft, lineage fan-out, and result-item
extremes were not inferred from retained content. M2–M4 must extend the bounded inventory for
those dimensions before selecting cases. The 1.7 GB pipeline-node root and 6.5 GB derived-view
root are local storage sizes, not copied fixture sizes.

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
- No timings or fixes were selected in M1.
