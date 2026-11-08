# Epic 0115 M5: worktree storage contract

Date: 2026-11-08

Pre-M5 baseline revision: `5809f9dc7511308bc92fcd523bb3f03ed5767053`

Tested implementation revision: `9f523c3eeb2b42bd11becf39c970c45cf8922c04`

Scope: one configurable mutable storage root and its API persistence path. No retained operator data
was changed.

## Contract

`DOKO_STORAGE_ROOT` is the explicit root for mutable state owned by one checkout. The backend maps
it to `runtime/`, `data/operations/`, `data/intake/recordings/`,
`data/intake/evidence-packages/`, and `data/incoming/videos/`. The setting wins over default paths
and configured path fields. A caller must choose a distinct root for each worktree. The backend
does not infer an operator corpus path or copy operator data into this root. Without this variable,
existing repository-relative defaults remain in force; use the variable for every isolated
development or test process until M6 changes the default.

Open selected operator recordings with an explicit byte-copy command. It requires a separate source
corpus path, one or more exact recording IDs, and `DOKO_STORAGE_ROOT`; it validates every bundle,
copies files into worktree intake through the existing atomic storage writer, and checks the copied
bundle fingerprint and file digests. It rejects missing or invalid bundles and never links source
files into mutable storage. Example:

```sh
DOKO_STORAGE_ROOT=/tmp/doko-state \
  mise exec -- uv run --project backend dokodetector-import-operator-recordings \
  --operator-corpus-root /path/to/operator/data/intake/recordings \
  --recording-id cardeventnet-IMG_0637
```

The selected bundle stays in the operator corpus. Its original files remain the local restore
source. This is an import operation, not a transparent overlay or a move. Do not delete the source
copy. Model bundles are not imported by this command.

Code and compact fixtures stay in Git. Large immutable model bundles and operator source assets stay
in their declared external locations and are referenced by exact path and digest. Caches belong under
the worktree's `runtime/`. Mutable operation records, uploads, review drafts, and jobs belong under
that worktree's root. Never hard-link mutable files. Opening an operator corpus is a deliberate
copy of selected validated bundles; the source is read-only. A clean checkout needs `mise install`,
`mise exec -- uv sync --project backend`, `DOKO_STORAGE_ROOT=/absolute/path/to/worktree-state`,
and the usual app command. Missing
external assets must be reported as missing and must not be fabricated or fetched implicitly. The
M5 workflow has no external model dependency. Local restore availability for moved media/models
remains part of M6/M11 qualification; M5 does not move these assets.

## Reader and writer inventory

| Resource | Representative schema / state | Active reader and writer | M5 replacement and check |
| --- | --- | --- | --- |
| Pipeline nodes and revisions | `pipeline-node/v1`, `event-data/v1` | `PipelineNodeStore`, pipeline edit/review and workspace APIs | Operations root selected by `DOKO_STORAGE_ROOT`; API edit/readback and restart checks below |
| Repository recording bundles | `repository-bundle/v1` and hashed bundle members | `RepositoryBundleStorage`, `RecordingBundleStore`, recording APIs | Explicit CLI copy to per-worktree intake; API uploads still write only there |
| Evidence packages | Evidence manifest, package record, enrollment and lineage schemas | `EvidencePackageStorage` and evidence-package APIs | Per-worktree intake root; no operator corpus writer is configured |
| Derived media and provider cache | Keyed derived-view cache; Gemini response cache | `PipelineRuntimeStorage`, `RecordingThumbnailCache`, Gemini analyzer | Per-worktree `runtime/`; cache identity and eviction remain M9 work |
| Local model bundles and source media | Bundle manifests and source manifests with SHA-256 | Processor providers and recording readers | External immutable inputs stay path/digest addressed; model-specific relocation and restore are not converted here |

M5 changes only root selection. It does not convert the other storage readers or writers, alter
schemas, or make existing checkouts safe by default. M6 owns remaining-root cutover.

## First replacement workflow and verification

The complete replacement path copies one selected checked-in operator recording bundle into one
worktree intake root, then creates and edits a pipeline node through the production FastAPI routes.
It reads the exact recording bundle and edited revision, restarts the app, and repeats both reads.
The two disposable worktrees used `fixtures/repository-bundle/v1/both`. All five source file hashes
matched their imported copies. The checked-in event fixture digest is
`7e9415663949314206228ee99dc5dd3d69ebbb6e8be28f6f51bd34730c423007`; the source video digest is
`7184fd89dd78b265e8f617989e8a9659897e060bde2d4f8d47dc05708771f8a8`. The test also verifies that
the operator fixture tree is unchanged. A repeated API upload returned the same bundle with
`created=false`, while the source remained unchanged. Each worktree had a separate
`DOKO_STORAGE_ROOT`; their saved edit revisions have different parent revision IDs. No review node
was written to the legacy checkout's pipeline-node root.

Commands run from each disposable worktree:

```sh
DOKO_STORAGE_ROOT=/tmp/0115-m5-final-a mise exec -- uv run --project backend pytest \
  backend/tests/test_worktree_storage_contract.py backend/tests/test_operator_corpus_import.py
DOKO_STORAGE_ROOT=/tmp/0115-m5-final-b mise exec -- uv run --project backend pytest \
  backend/tests/test_worktree_storage_contract.py backend/tests/test_operator_corpus_import.py
```

Both commands passed (3 tests each). The importer tests include missing-bundle rejection, source
immutability, exact target hash checks, no hard links, and exact replay. The missing local model
behavior passed the existing provider availability test (`available=false`).

The settings regression test verifies all five mutable roots resolve below the requested root. The
current focused app and pipeline API run passed 43 tests and had one unrelated failure:
`test_factory_converts_interrupted_round_analysis_to_failed` observed `queued` without entering the
application lifespan. The failure is independent of root selection and needs confirmation from the
baseline before it is assigned to M5.

## Disposable checkout to ready measurements

I created two clean detached worktrees at revision `9f523c3eeb2b42bd11becf39c970c45cf8922c04`.
The readiness boundary matches the M0 baseline: `git worktree add`, `mise install`, backend
`uv sync`, frontend `npm ci`, frontend build, then backend `create_app()` initialization. The
fixture API edit/save/restart test ran after readiness and passed in each worktree.

Commands, run sequentially per worktree:

```sh
/usr/bin/time -p git worktree add --detach /private/tmp/doko-0115-m5-qual-a <revision>
/usr/bin/time -p mise install
/usr/bin/time -p mise exec -- uv sync --project backend
(cd web && /usr/bin/time -p mise exec -- npm ci)
(cd web && /usr/bin/time -p mise exec -- npm run build)
DOKO_STORAGE_ROOT=/private/tmp/doko-0115-m5-qual-a-state \
  mise exec -- uv run --project backend python -c \
  'from dokodetector_backend.app import create_app; create_app()'
DOKO_STORAGE_ROOT=/private/tmp/doko-0115-m5-qual-a-state \
  mise exec -- uv run --project backend pytest \
  backend/tests/test_worktree_storage_contract.py backend/tests/test_operator_corpus_import.py
```

| Worktree | Checkout | `mise install` | Backend sync | `npm ci` | Frontend build | Backend ready | Create to ready sum | Checkout allocation | Ready allocation | Setup growth |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 17.94 s | 0.02 s | 1.13 s | 2.60 s | 4.07 s | 0.54 s | 26.30 s | 17,739,140 KiB | 18,670,260 KiB | 931,120 KiB / 953,466,880 bytes |
| B | 17.09 s | 0.03 s | 1.03 s | 4.33 s | 4.07 s | 0.54 s | 27.09 s | 17,739,140 KiB | 18,673,008 KiB | 933,868 KiB / 956,280,832 bytes |

Each isolated storage root allocated 40 KiB after its API workflow. The full additional path
allocation per ready worktree was 19,118,346,240 bytes (A) and 19,121,160,192 bytes (B), including
the checkout. `df -k /tmp` showed 17,764,776 KiB less free space after checkout A and 17,764,968
KiB less after checkout B. The volume-wide free-space delta is not an exact per-file APFS physical
allocation measure; background activity can affect it. `du` path allocation counts each checkout
separately and does not claim unique physical or reclaimable bytes.

Both create-to-ready sums meet the 30-second M0 time target. The checkout allocations are 16.92 GiB,
14.92 GiB above the 2 GiB target. Ready allocations are 17.80 GiB (A) and 17.81 GiB (B), which
exceed the target by 15.80 GiB and 15.81 GiB. M6 owns tracking cutover and must repeat this
measurement after reducing tracked checkout contents.

The clean-checkout commands created one backend environment per worktree, built five local
packages, and installed 61 Python packages. Each frontend install added 272 npm packages and the
production build passed, with the existing >500 kB chunk warning. The API workflow passed 3 tests
per worktree. The imported bundle remains the local copy for this workflow; the source fixture is
unchanged. The earlier post-setup values (18,453,996 and 18,454,020 KiB) came from a setup without
frontend dependencies and are superseded by this complete measurement.

## Commit boundary and handoff

Commit boundary: backend root setting, corpus-copy CLI and tests, this report, epic, board, and
current execution handoff. No data deletion, Git maintenance, corpus conversion, or model
relocation is in scope.

Requested run: 11 milestones. Completed: 4 before M5. Remaining after M5: 6. M6 must apply the
contract to remaining roots, qualify full clean-checkout and web readiness, and repeat the 2-GiB
measurement after tracking cutover.
