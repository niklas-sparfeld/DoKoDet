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

Code and compact fixtures stay in Git. Large immutable model bundles and operator source assets stay
in their declared external locations and are referenced by exact path and digest. Caches belong under
the worktree's `runtime/`. Mutable operation records, uploads, review drafts, and jobs belong under
that worktree's root. Never hard-link mutable files. Opening an operator corpus is a deliberate
read-only action by a caller that names the corpus path; the M5 API workflow below uses only a
checked-in fixture. A clean checkout needs only `mise install`, `mise exec -- uv sync --project
backend`, `DOKO_STORAGE_ROOT=/absolute/path/to/worktree-state`, and the usual app command. Missing
external assets must be reported as missing and must not be fabricated or fetched implicitly. The
M5 workflow has no external model dependency. Local restore availability for moved media/models
remains part of M6/M11 qualification; M5 does not move these assets.

## Reader and writer inventory

| Resource | Representative schema / state | Active reader and writer | M5 replacement and check |
| --- | --- | --- | --- |
| Pipeline nodes and revisions | `pipeline-node/v1`, `event-data/v1` | `PipelineNodeStore`, pipeline edit/review and workspace APIs | Operations root selected by `DOKO_STORAGE_ROOT`; API edit/readback and restart checks below |
| Repository recording bundles | `recording-manifest/v1` and hashed bundle members | `RepositoryBundleStorage`, `RecordingBundleStore`, recording APIs | Per-worktree intake root; M5 uses the checked-in compact fixture only |
| Evidence packages | Evidence manifest, package record, enrollment and lineage schemas | `EvidencePackageStorage` and evidence-package APIs | Per-worktree intake root; no operator corpus writer is configured |
| Derived media and provider cache | Keyed derived-view cache; Gemini response cache | `PipelineRuntimeStorage`, `RecordingThumbnailCache`, Gemini analyzer | Per-worktree `runtime/`; cache identity and eviction remain M9 work |
| Local model bundles and source media | Bundle manifests and source manifests with SHA-256 | Processor providers and recording readers | External immutable inputs stay path/digest addressed; model-specific relocation and restore are not converted here |

M5 changes only root selection. It does not convert the other storage readers or writers, alter
schemas, or make existing checkouts safe by default. M6 owns remaining-root cutover.

## First replacement workflow and verification

The complete replacement path is the production FastAPI app configured with one explicit storage
root, then a real pipeline-node create/edit/revision API sequence, readback after a fresh app
instance, and comparison with a second root. The frozen input is the checked-in
`fixtures/pipeline-data/v1/event-data-interval.json`; both worktrees must retain identical fixture
bytes and digest. The path does not read the ignored `data/` tree or `.runtime` from either
worktree. Missing-input behavior is the existing explicit processor availability response; the
workflow does not load a model.

The settings regression test verifies all five mutable roots resolve below the requested root. The
current focused app and pipeline API run passed 43 tests and had one unrelated failure:
`test_factory_converts_interrupted_round_analysis_to_failed` observed `queued` without entering the
application lifespan. The failure is independent of root selection and needs confirmation from the
baseline before it is assigned to M5.

Worktree creation and ready-time measurements, two-worktree API edit/restart evidence, byte-level
fixture comparisons, missing-asset response, and clean-checkout setup are required before this
milestone can be marked complete. Record exact commands, hashes, timings, and incremental byte
counts here. The frozen M0 target is at most 30 seconds and at most 2 GiB newly allocated per
worktree, excluding shared `.git`.

## Commit boundary and handoff

Commit boundary: backend root setting and test, this report, epic, board, and current execution
handoff. No data deletion, Git maintenance, corpus conversion, model relocation, or other root
conversion is in scope.

Requested run: 11 milestones. Completed: 4 before M5. Remaining after M5: 6. M6 must verify the
first-workflow evidence above before converting more roots. If the complete API test needs a
separate storage contract or schema migration, stop and split that prerequisite into a planned
milestone before continuing.
