# Epic 0115 M5: worktree storage contract

Date: 2026-11-08  
Source revision: `5809f9dc7511308bc92fcd523bb3f03ed5767053`  
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

Worktree creation began with `git worktree add --detach` at revision
`2362e9b04fa63647b3cb77682d113c3c0c337bd2`. The first checkout took 17.97 seconds. Each checkout
measured 17,739,124 KiB allocated before local Python setup. After `uv run` built the backend
environment and the API workflow ran, totals were 18,453,996 and 18,454,020 KiB. Each isolated
storage root allocated 40 KiB. This is far above
the M0 ceiling of 2 GiB per worktree. The checkout already contains large tracked data; M6 owns
tracking cutover. The measurements did not include `npm ci` or the frontend build, so there is no
full web create-to-ready result. The second checkout time was not captured separately.

The clean-checkout test command created the backend environment, built five local packages,
installed 61 packages, and passed. The imported recording bundle is the recovery copy for this
workflow, and the operator source remains available and unchanged. No retained operator asset was
moved. The M0 size target remains unmet and must be measured again after M6 tracking cutover.

## Commit boundary and handoff

Commit boundary: backend root setting, corpus-copy CLI and tests, this report, epic, board, and
current execution handoff. No data deletion, Git maintenance, corpus conversion, or model
relocation is in scope.

Requested run: 11 milestones. Completed: 4 before M5. Remaining after M5: 6. M6 must apply the
contract to remaining roots, qualify full clean-checkout and web readiness, and repeat the 2-GiB
measurement after tracking cutover.
