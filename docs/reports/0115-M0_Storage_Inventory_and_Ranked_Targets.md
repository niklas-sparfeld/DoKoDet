# Epic 0115 M0: storage inventory and ranked targets

Date: 2026-11-07
Source revision: `a17d1d8f34f1441482da9cf1d3f4fb0c6b95de6a`
Scope: bounded inventory and target freeze. No retained data was removed.

## Method and repeatability

The initial root-size baseline ran from a clean worktree at source revision
`a17d1d8f34f1441482da9cf1d3f4fb0c6b95de6a`. The repeatable inventory command and application
profiler ran later at `682dcb7baafdf0f089a5ee3b33e093808419bf54` while only M0 documentation and
measurement tools were uncommitted. Neither pass changed retained data or runtime code. The
inventory read path metadata and selected manifests. It did not parse all retained payloads or
inspect sealed test content. Root sizes came from `du -k -d 1 data .runtime .git`; the command was
run twice with no output differences. The
repeatable metadata walk is implemented in [`scripts/inventory_0115_storage.py`](../../scripts/inventory_0115_storage.py).
It inventories the main roots, shared `.git`, the external content-addressed cache, and each
registered worktree. It records `du` allocation, logical/path allocation, file counts, extensions,
largest files, symlinks, hard-link paths, tracked/LFS counts, ignore samples, and worktree state.
Two runs with unchanged inputs produced byte-identical JSON. `du` is allocated directory size.
The metadata walk totals path sizes and `st_blocks`; it can count APFS clones or hard links more
than once. Neither result is unique physical space or guaranteed reclaimable space.

Reproduce it from the repository root:

```sh
mise exec -- uv run --project backend python scripts/inventory_0115_storage.py --top 5 > /tmp/0115-inventory-a.json
mise exec -- uv run --project backend python scripts/inventory_0115_storage.py --top 5 > /tmp/0115-inventory-b.json
cmp /tmp/0115-inventory-a.json /tmp/0115-inventory-b.json
```

The [retained inventory JSON](0115-M0_Storage_Inventory_and_Ranked_Targets.artifacts/storage-inventory.json)
is one complete command result. The report tables summarize it. This repeat was captured at
`682dcb7baafdf0f089a5ee3b33e093808419bf54`; the earlier directory-size baseline remains tied to
the source revision shown above.

The registered-worktree and shared-object baseline used:

```sh
git worktree list --porcelain
git count-objects -vH
git ls-files data .runtime
git lfs ls-files
du -k -d 1 data .runtime .git
du -k -d 1 data/operations-recovery data/operations .runtime/pipeline
```

Two passes found no changing root sizes. The only recorded volatility was Git garbage: ten
temporary object or pack files totaling 2.65 GiB were reported by `git count-objects -vH` during
this inventory. No Git maintenance was run. Four existing detached iOS worktrees and the main worktree
were registered; none was changed.

| Registered detached worktree | Allocated bytes | Regular files / symlinks | `data` bytes | Largest file | Most common extensions by count |
| --- | ---: | ---: | ---: | --- | --- |
| `ios-06bcc178-643c-45ee-97b0-ef0164590b88` | 18,865,176 KiB | 67,354 / 32 | 17,146,848 KiB | 1,061,930,405-byte source video | `.json` 32,590; `.h` 9,077; `.py` 8,875; `.js` 5,397; `.ts` 3,168 |
| `ios-3e34d68c-fc82-4647-8565-e12e996798ef` | 18,634,444 KiB | 65,737 / 29 | 17,146,848 KiB | 1,061,930,405-byte source video | `.json` 32,585; `.h` 9,049; `.py` 7,752; `.js` 5,396; `.ts` 3,172 |
| `ios-8302f3d2-911c-4776-9e7d-90ada947d4c0` | 18,633,988 KiB | 65,710 / 29 | 17,146,848 KiB | 1,061,930,405-byte source video | `.json` 32,583; `.h` 9,049; `.py` 7,752; `.js` 5,396; `.ts` 3,172 |
| `ios-ea2238c1-eaa1-46e6-a9bc-ebd15fdbb3d4` | 14,480,640 KiB | 530 / 0 | 14,069,188 KiB | 869,798,284-byte source video | `.py` 254; `.json` 192; `.mov` 54; `.md` 9 |

The first three worktrees have nearly identical source and `data` sizes. Their path summaries have
the same top video files and similar `.json`, `.h`, `.py`, `.js`, and `.ts` counts. The fourth is
still marked `locked initializing` by Git and has a smaller checkout. These are path-level
allocations. The same source-video paths recur, but no deduplicated-space claim follows without
filesystem clone or shared-object accounting. `.git` remains shared and is not included in these
per-worktree totals. Between the initial snapshot and the reproducible inventory, the `ios-3e34`
worktree changed by 8 KiB and one regular file. The two scripted passes then matched exactly.

## Storage inventory

Sizes below use allocated `du -k` bytes converted to GiB. Counts and extensions are path-based
metadata from the bounded walker. `.git` is shared by all registered worktrees. The external
content-addressed cache is outside the checkout.

| Root | Allocated size | File or object count | Evidence and classification |
| --- | ---: | ---: | --- |
| `data` | 50.2 GiB | 257,463 regular files | Mixed source, durable operations, and recovery data; 240,209 `.json`, 8,499 `.lock`, 5,031 `.jpg`, 741 `.mp4`, 109 `.mov` |
| `data/intake` | 15.2 GiB | 2,530 files | Preserve original source assets. The largest video is 1,061,930,405 bytes. |
| `data/operations` | 4.3 GiB | 62,629 files | Mixed current authority, campaigns, and older pipeline representation. |
| `data/operations/pipeline-nodes` | 1.7 GiB | 1,006 node manifests; 1,223 revision files | Current ignored durable node data. M1 must prove recovery before any tracking or path change. |
| `data/operations/pipeline` | 1.6 GiB | 31,536 tracked files | Older persisted representation. Keep until its remaining readers and recovery role are closed. |
| `data/operations-recovery` | 30.1 GiB | 191,373 regular files | Recovery and migration-stage candidates; includes declared migration losses and preserved drafts. |
| `data/operations-recovery/0108-m10-20261105` | 24.1 GiB | 142,746 regular files | Largest recovery tree; exact candidate for M1 comparison, not yet reclaimable. |
| `data/models` | 82.5 MiB | 9 files | Ignored local DINOv3 model bundle; preserve. |
| `.runtime` | 42.6 GiB by `du` | 236,521 regular files; 9,094 symlinks | Run output, training views, model work, and caches. Largest individual checkpoints are about 567 MB. |
| `.runtime/pipeline/derived-views` | 6.5 GiB | 71,804 files: 30,082 `.bin`, 30,131 `.json`, 11,590 `.jpg` | Keyed derived-view cache with active API readers and writers. |
| `.runtime/gemini-cache` | 2.7 GiB | 18,655 JSON files | Provider response cache; recomputation can incur provider cost. |
| `.runtime/rfdetr-segmentation-0092-m4` | 3.5 GiB | 29 regular files; 1,748 symlinks | Historical training run. Five 567 MB checkpoints have five different SHA-256 digests. Its `bundle/` is required by active Epic 0096 M4 and is retained. |
| `.runtime/synthetic-visible-region-0070-all-recordings-training-v2` | 1.9 GiB | 14 regular files; 718 symlinks | Old processed training input and run output. Its run and bundle manifests preserve selection and digest facts; no active reader was found in the bounded source search. |
| `.runtime/synthetic-visible-region-0070-m4-50-50` | 3.7 GiB | 48 regular files; 1,901 symlinks | Two historical comparison runs with separate bundle digests; their checkpoints are distinct. Preserve provenance pending M4 dependency review. |
| `~/.cache/doko-detector` | 1.84 GiB logical | 60 content-addressed files | 0114 hard-fixture assets; 57 exact current inputs are pinned by the M1/M4 fixture contract. Keep through 0114 M11. |
| `.git` | 30.8 GiB | shared object database and worktree metadata | Pack files total 11.35 GiB; local LFS is 16.8 GiB. Git-reported garbage is 2.65 GiB and needs separate active-operation review. |

The tracked-file count under `data` and `.runtime` is 32,044. Of these, 31,536 are under the
older `data/operations/pipeline` root. `data/operations/pipeline-nodes`, `data/models`, and
`.runtime` are ignored local resources. They are not represented by a clean Git checkout. Source
video paths use Git LFS (`git lfs ls-files`: 63 entries); LFS objects are shared in `.git/lfs`.

Representative exact resource sizes and schemas come from the [0114 hard-data report](0114-M1_Hard_Data_and_Fixture_Freeze.md): 1,006 `pipeline-node/v1` manifests; 1,223 revision files; a 16,005,605-byte visual-identity revision; a 12,136,454-byte visible-card revision; a 5,532,993-byte proposed-scene revision; and one 180,869-byte calibration draft. The hard fixture now pins 57 hashed assets across four recordings and seven nodes, including every required revision and copy ancestor. These are durable records and dependencies, not cache eviction candidates.

Targeted content checks found no `base64` or `data:image` markers in the five sampled large revision
files. Their SHA-256 digests differ, including each sampled parent/head pair; no repeated revision
payload was found in those samples. A same-size filter found an exact duplicate for the largest
source video: its 1,061,930,405 bytes have SHA-256
`b8daa5ac29ce330c5859d4c8825a60457e734b4b11d1b8e3ab6556217268ce73` in both
`data/intake/recordings/game-2026-08-20-01-005/...mov` and the matching recovery-tree path. The
intake copy is protected; the recovery copy remains until M1 verifies the snapshot's purpose. The
five equal-size 0092 M4 training checkpoints also have different hashes. We did not hash all
videos, crops, or checkpoint files.

The local hard-fixture cache contains 60 content-addressed files totaling 1.84 GiB; its largest
entry is the same 1,061,930,405-byte source video. 0114 M1 validates exact hashes and lineage, and
M4/M9 verify production reads and cold/warm media behavior. Current time to recreate the full hard
cache, recovery restore time, and provider-cache replay cost are not recorded. M1 and M9 own those
measurements before applying any retention limit.

## Disposable worktree baseline

A detached benchmark worktree at the source revision was created under `/tmp`, set up with the
documented backend and browser commands, checked by importing the backend app, then removed. The
existing worktrees were not modified.

| Step | Command | Time | Allocated worktree bytes |
| --- | --- | ---: | ---: |
| Checkout | `git worktree add --detach /tmp/doko-detector-0115-m0-benchmark HEAD` | 20.068 s | 17,683,200 KiB |
| Tool and package setup | `mise install`; `mise exec -- uv sync --project backend`; `mise exec -- npm ci`; `mise exec -- npm run build`; backend import check | 41.212 s | 18,610,588 KiB total |
| Ready | Checkout plus setup | 61.280 s | 17.75 GiB total; setup added 927,388 KiB (0.884 GiB) |

The checkout includes 15.2 GiB of tracked original intake and 1.6 GiB of tracked older pipeline
files. It does not copy `.runtime`. The shared `.git` object database is excluded from the
worktree figure. APFS clone accounting can make path allocation differ from unique physical bytes.
The measured setup covered the backend and web build only; optional inference and operations
environments were not included.

## Application and agent baselines

The current 0114 evidence is a usable correctness and workload baseline, but most timings remain
preliminary rather than a stable regression baseline:

| Measure | Existing evidence | Frozen M0 target |
| --- | --- | --- |
| Hard application resources | 57 exact assets, four bundles, seven nodes; manifest digest `e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`. The live corpus has 1,006 node manifests and 1,223 revision files. | Keep the exact 57-asset fixture and record per-request reads and parses. No request may read the live corpus. |
| HTTP/read cases | Current one-batch M3 hard run: 20/20 samples correct; hard catalog 18.312 s and 3,212 response bytes with four expected IDs. Current M4 hard run: 105/105 samples correct; workspace cold/warm 21.190/21.137 s, lineage 30.040/29.735 s, maximum identity revision 5.176/5.168 s, and maximum polygon revision 3.597/3.565 s. | Keep the 26 named M3/M4 cases and exact identity checks. M11 must record file reads and parses with each latency sample; no new unrelated-data scans may exceed the exact fixture membership. |
| Media and browser cases | Current M9 media runner: 13/13 correct cold/warm and restart samples. M10 has 7 browser/load scenarios, 70 contexts, and 10 startup processes; all passed. Generated-fixture startup-to-use median is 983 ms. | Keep all 7 M10 workflows and 10 startup processes. Full hard-corpus timing and counters beyond these four cases remain M11 work. |
| Agent lookup | Four exact source/report queries returned 4/4 expected resources in 10 lines and 764 output bytes total. Largest query: 389 bytes and 6 lines. | Keep 4/4 exact-resource lookup success. Bound these four discovery outputs to 10 lines and 764 bytes until a compact entrypoint replaces them. |
| Worktree | 61.280 s and 17.75 GiB allocated through backend/web readiness. | M5 target: ready in at most 30 seconds and at most 2.0 GiB new per-worktree allocation, with required exact assets available from a verified shared source. Count `.git` separately. |

The four agent lookup tasks were bounded to exact outputs:

| Task | Command | Result |
| --- | --- | --- |
| Find the node-store owner | `rg -n '^class PipelineNodeStore\b' backend/src/dokodetector_backend/pipeline_node_store.py` | 1 line, 29 bytes; exact owner found |
| Find the hard-data report | `rg --files docs/reports` filtered for `0114-M1_Hard_Data_and_Fixture_Freeze.md` | 1 line, 53 bytes; exact report found |
| Find the node schema reader | `rg -n 'schema_version' backend/src/dokodetector_backend/pipeline_node_store.py` | 6 lines, 389 bytes; current schema checks found |
| Find derived-view cache users | `rg -n 'DerivedViewCache|derived_view_cache' backend/src/dokodetector_backend` | 2 lines, 293 bytes; service owners found |

The retained 0114 samples do not contain read/parse counters. M0 now records representative
counters for four hard M4 cases; M11 must repeat them in the full hard-corpus qualification before
making a reduction claim. The hard catalog result is one sample and is not a latency budget. Agent
lookup numbers are command-output measures, not token savings.

### Measured application reads and numeric ceilings

[`backend/scripts/profile_0115_application_io.py`](../../backend/scripts/profile_0115_application_io.py)
reuses the 0114 hard M4 cases with a fresh disposable fixture and app per request. A Python audit
hook counts read-open events under that fixture root. The profiler also counts `json.loads`,
`BaseModel.model_validate_json`, and loaded `parse_*_data_bytes` calls. Setup, fixture materialization,
and app startup are outside the counter window. These counters describe Python read-open and decoder
calls; they do not count reads by native code or operating-system cache hits. No request read the
live corpus. The run used the 57-asset manifest digest above at source commit
`682dcb7baafdf0f089a5ee3b33e093808419bf54`.

| Hard M4 case | Read opens | Unique fixture paths | Unique JSON paths | `json.loads` calls | Domain data parser calls | Frozen M11 ceiling |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Full workspace | 63 | 38 | 38 | 586 | 14 (8 visible-card, 6 visual-identity) | At most 63 opens, 38 paths, 586 JSON decodes, 14 domain parser calls; 0 live-root reads |
| Lineage | 63 | 35 | 34 | 596 | 14 (8 visible-card, 6 visual-identity) | At most 63 opens, 35 paths, 596 JSON decodes, 14 domain parser calls; 0 live-root reads |
| Maximum identity revision | 6 | 4 | 4 | 12 | 2 visual-identity | At most 6 opens, 4 paths, 12 JSON decodes, 2 domain parser calls; 0 live-root reads |
| Maximum polygon revision | 6 | 4 | 4 | 12 | 2 visible-card | At most 6 opens, 4 paths, 12 JSON decodes, 2 domain parser calls; 0 live-root reads |

All four responses passed the existing M4 identity and correctness checks. The [measured counters](0115-M0_Storage_Inventory_and_Ranked_Targets.artifacts/application-io.json)
retain exact fixture paths, decoder counts, response identities, and status. These are no-regression
ceilings set before any 0115 storage or application changes; they do not claim a speedup.

Reproduce the count run from the repository root:

```sh
mise exec -- uv run --project backend python backend/scripts/profile_0115_application_io.py --output /tmp/0115-io-profile.json
```

The current 0114 samples used one warmup, one measured request, and one batch for each hard case;
they are correctness and initial baseline evidence, not stable latency distributions. The raw
outputs are retained as [catalog](0115-M0_Storage_Inventory_and_Ranked_Targets.artifacts/catalog-hard.json),
[pipeline](0115-M0_Storage_Inventory_and_Ranked_Targets.artifacts/pipeline-hard.json), and
[media](0115-M0_Storage_Inventory_and_Ranked_Targets.artifacts/media.json) artifacts. They record
source commit, fixture digest, status, response size, digest, and elapsed time.

## Ranked candidates and retention roots

The first numeric storage target is a conditional upper bound, not promised savings: compare the
24.1 GiB and 142,746-file `0108-m10-20261105` tree with the activated authority and M10/M11
reconciliation. M1 must restore representative retained source, review, lineage, and model content
before M3 can retire any path. The M3 target is to reclaim that exact measured tree only if every
retained dependency and declared unique original has a verified replacement; otherwise use the
smaller exact redundant subset. No deletion is approved by this inventory.

| Rank | Candidate | Evidence and active owners | M0 decision and proposed bound |
| --- | --- | --- | --- |
| 1 | `data/operations-recovery/0108-m10-20261105` — 24.1 GiB, 142,746 files | [0108 M10 reconciliation](0108-M10_Migration_Reconciliation.md) lists recovery snapshots, drafts, original bytes, and declared losses. One 1,061,930,405-byte video is an exact duplicate of protected intake by SHA-256. | M1 exact comparison and restore first. Conditional M3 ceiling: 24.1 GiB and 142,746 files; first confirmed duplicate candidate is one file and 1,061,930,405 bytes. No expiry until M1/M3 evidence proves redundancy. |
| 2 | `.runtime/pipeline/derived-views` — 6.5 GiB, 71,804 files | `DerivedViewCache` reads and writes this root; visible-card and identity services use its cache lock. 0114 M9 covers cold/warm frames and crops, review-save invalidation, revision changes, and restart. | Cache candidate, not disposable by name. Provisional M9 ceiling: current 6.5 GiB; proposed 30-day idle expiry only after exact-key regeneration checks pass. |
| 3 | `.runtime/gemini-cache` — 2.7 GiB, 18,655 files | `gemini_analyzer.py` reads/writes provider response caches keyed by request content. Cache hits avoid provider work. Current provider cost and replay value were not measured. | Keep until provider-cost and replay checks. Provisional M9 ceiling: current 2.7 GiB; proposed 180-day idle expiry after response consumers and reproducibility are verified. |
| 4 | `.runtime/rfdetr-segmentation-0092-m4` training outputs — 3.5 GiB | The selected `bundle/` is referenced by active 0096 M4 and is protected. The five similarly sized checkpoints have distinct digests; run manifests retain training and split provenance. | Keep bundle and compact provenance. M4 can consider non-bundle training outputs after dependency and restore checks; no M0 expiry. |
| 5 | `.runtime/synthetic-visible-region-0070-all-recordings-training-v2` — 1.9 GiB | Run and bundle metadata retain materialization and subset digests; 718 paths are symlinks to existing source material. No active reader appeared in the bounded path search. | Candidate for M4 exact-manifest/reader review. Preserve manifests, metrics, splits, and required unique evaluation evidence. |
| 6 | `.runtime/synthetic-visible-region-0070-m4-50-50` — 3.7 GiB | Separate control and synthetic-addition bundle digests; two checkpoint sets are not byte duplicates. | Candidate for M4; preserve experiment identities and results. No duplicate claim from equal file sizes. |
| 7 | `.git` temporary objects — 2.65 GiB reported garbage | Git reported temporary pack/object paths. Existing locked worktree and running Git activity must be checked before maintenance. | Do not prune in M0. Recheck all Git operations, worktree refs, and object reachability before any maintenance. |

Retained roots for later dependency checks are original `data/intake`; current ignored
`data/operations/pipeline-nodes`; current human drafts, reviews, calibrations, and selections under
`data/operations`; current model bundles and campaign provenance; active 0096/0106 artifacts; the
57 pinned 0114 assets under `~/.cache/doko-detector`; and a verified recovery set. The older
tracked `data/operations/pipeline` remains until M5/M6 prove the replacement and every remaining
reader. The shared `.git` and LFS object store remain outside per-worktree bytes.

## Commands and results

- `du -k -d 1 data .runtime .git` and `du -k -d 1 data/operations-recovery data/operations .runtime/pipeline`, repeated twice — PASS; exact output matched.
- `mise exec -- uv run --project backend python scripts/inventory_0115_storage.py --top 5` repeated with unchanged inputs and compared using `cmp` — PASS; 41,345-byte JSON outputs matched. The output includes all four registered worktrees and shared `.git` separately.
- `git worktree list --porcelain`, `git count-objects -vH`, `git ls-files data .runtime`, and `git lfs ls-files` — PASS; counts recorded above. Git reported 10 garbage objects totaling 2.65 GiB; no maintenance was run.
- Four bounded exact-resource lookup commands — PASS, 4/4 resources; 10 lines and 764 output bytes.
- Disposable worktree setup: `mise install`; `mise exec -- uv sync --project backend`; `mise exec -- npm ci`; `mise exec -- npm run build`; `mise exec -- uv run --project backend python -c 'from dokodetector_backend.app import create_app'` — PASS. The temporary worktree was removed; the original four detached worktrees remain registered.
- `mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard` — PASS; all 57 hard assets validated.
- `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_catalog_read_performance.py --profile hard --warmups 1 --repeats 1 --batches 1 --timeout 180 --output /tmp/0115-m0-current-catalog.json` — PASS, 20/20 samples.
- `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_pipeline_read_performance.py --warmups 1 --repeats 1 --batches 1 --timeout 180 --output /tmp/0115-m0-current-pipeline.json` — PASS, 105/105 samples.
- `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_media_performance.py --output /tmp/0115-m0-current-media.json` — PASS, 13/13 samples.
- `mise exec -- uv run --project backend python backend/scripts/profile_0115_application_io.py --output /tmp/0115-io-profile.json` — PASS; full workspace, lineage, identity revision, and polygon revision passed exact response checks. The run recorded 0 live-root reads and the per-case read/parse counts above.
- `mise exec -- uv run --project backend ruff check scripts/inventory_0115_storage.py backend/scripts/profile_0115_application_io.py` and `mise exec -- uv run --project backend ruff format --check scripts/inventory_0115_storage.py backend/scripts/profile_0115_application_io.py` — PASS.
- Existing 0114 M10 real-process evidence: 7 workflows, 70 contexts, and 10 startup processes — PASS as recorded by that report. All current M3/M4/M9 samples are preliminary and not a stable latency distribution.
- Filtered SHA-256 checks on five sampled large node revisions, the same-size duplicate source/recovery video pair, and the five 567,065,639-byte 0092 M4 checkpoints — PASS; revision and checkpoint digests differ, and the two video digests match. No broad video or checkpoint hashing was done.
- `git diff --check` and local Markdown link validation — PASS after the plan move.

## Limits

This inventory establishes directory sizes and candidate metadata, not recoverable bytes. It does
not prove every snapshot duplicate, regeneration cost, complete storage reader/writer graph, or
provider-cache monetary cost. The four application counters are representative, not a full-corpus
baseline; the one-sample latency results are not stable budgets. M1 owns exact recovery
verification; M4 owns one old training-input family; M5 owns the worktree data contract; M9 owns
cache limits and expiry; M11 owns full hard-corpus performance and counter qualification.
