# DokoDetector TableEvidenceAnalyzer — Model Training Foundation

## Plan status

- **Summary:** Build reproducible train, evaluate, and export mechanics for analyzer model components
- **Status:** In Progress
- **Depends on:** Plan 0020, which is complete
- **Builds on:** Plan 0006 provides the table-observation contract and canonical fixtures
- **Reviewed:** 2026-08-28 against repository baseline `e771072f9`, completed plans 0006, 0020,
  and 0025, the current backend and analyzer contracts, and active plans 0022, 0027, and 0028
- **Starts with:** A tiny generated fixture; reviewed plan 0025 evidence is not a prerequisite
- **Unblocks:** The future TableEvidenceAnalyzer capability-development plan
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Outcome

Build reusable mechanics for TableEvidenceAnalyzer model experiments without selecting its final
internal components.

At the end of this plan, one local command sequence can:

```text
frozen tiny dataset manifest
  -> validated samples and deterministic transforms
  -> CPU smoke training
  -> checkpoint and resume
  -> held-out evaluation
  -> machine-readable run report
  -> versioned analyzer capability bundle
  -> declared capability output in a plan 0006 observed-card fixture
```

The first model may be intentionally weak. This plan proves reproducibility, lineage, and tooling.
Recognition quality belongs to the next plan.

## 2. Reuse and boundaries

Reuse proven CardEventNet patterns where the concepts match:

- root `mise.toml` runtime versions;
- uv lock files and ordinary Python commands;
- configuration snapshots;
- dataset and split version recording;
- seeded loaders and worker initialization;
- resumable checkpoints;
- run summaries written before and after training;
- CPU smoke tests and optional CUDA or MPS execution;
- separate model-heavy evaluation.

Do not import CardEventNet temporal-event code into the TableEvidenceAnalyzer. The tasks, inputs,
labels, and metrics differ. Share small general utilities only after two real consumers justify
extraction.

Plan 0020 owns source, annotation, review, lineage, dataset eligibility, group-safe splits, coverage,
and lifecycle receipts. This plan consumes its implemented `dataset-version/v1` and
`table-dataset-split/v1` contracts. It must not scan raw directories and decide which labels are
trustworthy.

Plan 0006 supersedes the plan 0005 runtime boundary with `table-observation/v1`. Training code
exports small measured capabilities that a TableEvidenceAnalyzer can combine. It must not force
every model bundle to implement the complete table-observation pipeline.

Plan 0025 provides optional motion evidence for later transition and tracking work. It does not
block this plan. Add reviewed real evidence through the plan 0020 review and dataset path when it
is available. Do not make unreviewed plan 0025 packages into training labels.

## 3. Current repository baseline

The repository now contains more foundation than this plan originally assumed:

- `card_event_net` implements table-observation annotation, review, dataset assembly, group-safe
  split, validation, coverage, and lifecycle-receipt commands;
- `table_evidence_analyzer` contains the canonical `table-observation/v1` models and contract tests;
- `game_engine` consumes the same canonical observation fixtures;
- the backend stores canonical observations through the stable analyzer boundary;
- the current dataset entry identifies a source frame, observed card, box, target, source asset, and
  transform, but a training loader still needs a deterministic way to resolve and verify the frame
  bytes that it crops.

Use these implementations. Do not create a second dataset, split, review, or observation contract
inside the new package. The first two milestones must complete the active backend boundary cutover
and package rename that plan 0006 exposed. The dataset milestone must add the missing sample-byte
resolution contract before training code depends on local directory conventions.

## 4. Initial project shape

The lightweight analyzer package now has this shape:

```text
table_evidence_analyzer/
├── pyproject.toml
├── uv.lock
├── README.md
├── configs/
│   ├── smoke.yaml
│   └── baseline.yaml
├── src/table_evidence_analyzer/
│   ├── domain/
│   ├── data/
│   ├── models/
│   ├── training/
│   ├── evaluation/
│   ├── export/
│   └── cli.py
└── tests/
    ├── fixtures/
    ├── unit/
    └── integration/
```

Use commands such as:

```bash
table-analyzer data validate --dataset <manifest> --split <split> --artifacts <index>
table-analyzer train --config <config>
table-analyzer evaluate --run <run-dir> --split validation
table-analyzer export --run <run-dir> --output <bundle-dir>
table-analyzer classify-crop --bundle <bundle-dir> --image <crop>
```

Keep command names stable only after their first contract tests exist. Do not add `mise` tasks that
only wrap these commands.

Do not add a full-package `analyze` command in this plan. The first model receives an oracle crop. It
cannot find visible cards in an evidence package. Plan 0022 owns visible-card localization and the
composed evidence-package analyzer.

## 5. Dataset adapter contract

The loader accepts an explicit dataset version and split version from plan 0020. It also accepts an
explicit sample-artifact index or resolver contract. The resolver maps each `source_frame_id` to
bytes and a content digest without making a local path part of sample identity. Every resolved
sample contains:

- `dataset_item_id`, `source_asset_id`, `source_frame_id`, and `observed_card_id`;
- verified source-frame bytes and content digest;
- the reviewed box, visual card identity, quality tags, and transform version;
- target-schema, annotation, review, deck, and card-set versions;
- session, game, table-setup, and source-lineage leakage groups;
- the frozen eligibility and allowed-use state;
- the named partition from `table-dataset-split/v1`.

The dataset and split digests define membership. The artifact index locates immutable bytes. A
cache can materialize crops, but each crop records the source-frame digest, box, transform version,
and derived digest. Delete and rebuild a stale cache instead of accepting it.

The first training task is oracle-crop card identity because it isolates identity recognition from
localization. Use reviewed human boxes from real data when they exist. Until then, use a tiny
generated fixture with obvious labels and at least three independent leakage groups to test train,
validation, and test mechanics only.

The loader must reject:

- unknown schema versions;
- missing or changed source bytes;
- unreviewed or ineligible samples;
- card identities outside the declared card set;
- overlap between leakage groups across partitions;
- a missing sample-artifact entry or changed source-frame bytes;
- a crop whose box or transform version does not match the manifest.

Do not silently skip invalid samples. Evaluation reports every excluded or failed item.

## 6. Configuration and reproducibility

Each run resolves one complete configuration before training starts:

```text
task and model adapter
dataset and split versions
input preprocessing
augmentation
optimizer and schedule
batch size and worker count
seed
epoch or step budget
checkpoint policy
device and precision request
metric selection
```

Write `run.json` before the first batch with:

- run ID and start time;
- code revision and dirty-state marker;
- complete resolved configuration;
- Python and dependency versions;
- platform, device, and accelerator details;
- dataset, split, source, annotation, and card-set digests;
- seed and deterministic-mode settings.

Update the run record atomically with status and metrics. Preserve failed and interrupted run
metadata.

Exact bit-for-bit training equality across CPU, MPS, and CUDA is not required. The same dataset,
configuration, and seed must define the same semantic experiment.

## 7. Model adapter

Define a small task interface rather than coupling training to one library model:

```python
class TrainableAnalyzerTask(Protocol):
    def build_model(self, config: ModelConfig): ...
    def compute_loss(self, batch: Batch, outputs: Outputs): ...
    def decode(self, outputs: Outputs) -> Predictions: ...
    def metrics(self, predictions: Predictions, targets: Targets): ...
```

The first adapter is a small card-set-manifest-sized crop classifier. The current shared card set
has 24 visual identities. Do not reduce its output to the 20 identities in `doko-40-v1`: the
TableEvidenceAnalyzer can report an identity outside the selected round deck, and reconstruction
owns deck rejection. The classifier exists to exercise the pipeline. Do not present it as the
chosen production architecture.

Later visible-card detection, localization, transition, spatial, and tracking tasks can add
adapters. They must retain the same run, checkpoint, dataset, and evaluation contracts. Each bundle
declares the table-observation capabilities it can help produce.

## 8. Checkpoints and resume

Every checkpoint stores:

- model and optimizer state;
- scheduler and mixed-precision state, when used;
- current epoch and step;
- best-checkpoint metric and value;
- random-generator states needed for practical resume;
- resolved config and dataset digests;
- checkpoint format version.

Resume must reject a changed task, model shape, dataset, split, card set, or preprocessing contract
unless an explicit fine-tune command handles that transition. Do not accidentally treat a new
experiment as a resume.

Always retain the last checkpoint and the validation-selected best checkpoint. Do not select a
checkpoint from test metrics.

## 9. Evaluation contract

Evaluation consumes a frozen run or exported bundle and one named split. It writes:

- sample-level predictions linked to sample IDs;
- top-1 and top-k identity metrics;
- per-class counts and confusion;
- failures grouped by data tags and source groups;
- high-score wrong predictions;
- decode or sample failures;
- runtime and throughput measurements;
- the exact bundle, dataset, and split versions.

The smoke fixture only proves expected overfitting and serialization. It does not produce a product
metric.

Model calibration, visible-card localization, transition and active-area evidence, card tracking,
and complete evidence-package evaluation belong to the capability-development plan. They should
reuse this report envelope and include feature ablations.

## 10. Analyzer capability bundle contract

Export a self-contained versioned bundle with:

```text
bundle manifest
weights or reference artifacts
model adapter and architecture identifier
input preprocessing
card-set and deck-design compatibility
dataset and split provenance
training run ID and code revision
dependency/export environment
metric summary
license record
content hashes
```

An exported bundle loads without the training dataset. Loading validates every content hash and
format version.

The first bundle exposes identity candidates for a supplied crop. A test-only adapter places those
candidates into an observed-card fixture from plan 0006. The backend must import the stable analyzer
runtime contract and bundle loader, not training modules. Remove the obsolete plan 0005 result and
scripted-detector adapters during the package cutover. Do not claim that the oracle-crop bundle
performs visible-card detection, tracking, or end-to-end table observation.

## 11. Small implementation milestones

### M0 — Active-boundary cutover

1. Define the stable analyzer runtime interface around the existing canonical
   `table-observation/v1` models.
2. Replace the backend's legacy result storage and scripted runner with this
   table-observation boundary. Update persistence and tests in the same change.
3. Remove the obsolete plan 0005 result contract, detector protocol, scripted adapter, fixtures,
   configuration names, migrations, and active documentation. Do not keep a dual runtime path.
4. Use the canonical plan 0006 observation fixture in one analyzer-to-backend-to-reconstruction
   contract test.

Acceptance:

- one canonical plan 0006 observation fixture crosses the analyzer, backend, and reconstruction
  boundary without a schema translation;
- the backend persists a schema-valid table observation without importing training internals;
- no active code, command, fixture, database field, or documentation uses
  legacy result schema;
- the backend and analyzer contract tests remain local and do not download weights or data.

Progress (2026-08-28): M0 is complete. Added the stable `TableEvidenceAnalyzer` runtime protocol
and analyzer input models around `table-observation/v1`. Replaced backend result persistence,
storage, routes, and orchestration with table-observation records. Removed the obsolete result
contract, scripted adapter, fixtures, configuration, migration, and active documentation. Updated
the iOS read client to the canonical observation shape. The shared plan 0006 fixture is parsed by
the analyzer-side models, persisted by the backend, and parsed by the reconstruction-side models
with identical canonical bytes. Verification: analyzer 11 tests, backend 94 tests, game-engine 69
tests, and backend/analyzer Ruff checks pass. The Swift package check reached compilation but
remains red on pre-existing concurrency-safety errors in
`ios/CardEventProbeTests/TrainingRecordingUploadQueueTests.swift`; the updated observation client
test has no compile errors.

### M1 — Package rename and CLI skeleton

1. Use `table_evidence_analyzer/` as the project and Python package name. Update its project metadata
   and dependency names in the same change.
2. Update active imports, commands, dataset task identifiers, fixtures, lock files, and
   documentation. Do not retain the old package as an alias.
3. Keep the canonical `table-observation/v1` models and plan 0006 fixture tests in the renamed
   package.
4. Add the `table-analyzer` CLI skeleton. Add each functional subcommand in the milestone that
   implements it. Do not add a full-package analyzer command.

Acceptance:

- `mise install` and `mise exec -- uv sync` reproduce the renamed package environment;
- the renamed package imports and `table-analyzer --help` runs;
- no active module, command, fixture, dependency, or data-task identifier uses the obsolete
  component name;
- tests do not download weights or data.

Progress (2026-08-28): M1 is complete. Renamed the project and import package to
`table_evidence_analyzer`, updated backend dependencies and active contract imports, and changed
the table-evidence data-task fixture to `table_evidence_analyzer_identity_crop` with its refreshed
dataset digest. Added the offline `table-analyzer` parser with `data validate`, `train`, `evaluate`,
`export`, and `classify-crop` command skeletons; no `analyze` command or training behavior is
implemented. Verification: `mise install`; package `uv sync`; backend `uv sync`; analyzer tests
(13 passed), backend tests (94 passed, 1 existing warning), CardEventNet data-contract tests (6
passed), Ruff checks and format checks, and `table-analyzer --help` pass. The backend full suite
required loopback socket access for its two local-pipeline tests; no weights or data were
downloaded.

### M2 — Materialized smoke dataset

1. Add a tiny generated image fixture through the implemented plan 0020 dataset and split
   contracts.
2. Use at least three independent leakage groups so train, validation, and test partitions are
   non-empty.
3. Define the sample-artifact index or resolver and verify source-frame bytes before cropping.
4. Materialize deterministic crops with complete digest and transform lineage.
5. Validate split, eligibility, target, card-set, lineage, box, transform, and digest rules.
6. Add one fast data-loader integration test.

Acceptance:

- every sample resolves from `dataset_item_id` to verified source-frame bytes and one deterministic
  crop;
- no local absolute path becomes semantic identity;
- invalid lineage, changed frame bytes, stale crops, and split leakage fail clearly;
- tests do not download weights or data;
- training code does not scan annotation or raw-source directories.

Progress (2026-08-28): M2 is complete. Added the offline `sample-artifact-index/v1` resolver,
strict dataset and split validation, a three-sample generated PPM fixture with independent
session, game, table-setup, and source-lineage groups, and a deterministic crop cache with full
source-frame, annotation, review, box, transform, partition, and content-digest lineage. Added
the materialized crop loader and regression tests for changed frame bytes, stale caches, and split
leakage. Verification: `mise exec -- uv run pytest` (16 passed); no weights or data were
downloaded.

### M3 — Minimal train and evaluate loop

1. Add the first crop-classification adapter.
2. Train it to overfit the tiny fixture on CPU.
3. Write sample predictions and the run report.
4. Add deterministic evaluation transforms and seeded training transforms.

Acceptance:

- the smoke run completes in ordinary local development time;
- the expected fixture metric is asserted;
- training and evaluation use the same class and preprocessing contracts.

Progress (2026-08-28): M3 is complete. Added a dependency-free RGB centroid crop-classification
adapter, deterministic PPM preprocessing, seeded configuration snapshots, CPU smoke training, a
run report with environment and dataset/split digests, train sample predictions, and named-split
evaluation reports. The generated fixture overfits its training sample (top-1 accuracy 1.0) and
evaluation writes sample-linked top-k predictions. Verification: `mise exec -- uv run pytest`
(17 passed), `mise exec -- uv run ruff check src tests`, and `mise exec -- uv run ruff format
--check src tests`; no weights or data were downloaded.

### M4 — Checkpoint, resume, and failure records

1. Save last and best checkpoints.
2. Resume an interrupted smoke run.
3. Reject incompatible resume inputs.
4. Preserve a structured record for a failed run.

Acceptance:

- resumed and uninterrupted smoke runs have equivalent semantic progress;
- best-checkpoint selection uses validation only;
- corrupt checkpoints fail without damaging prior artifacts.

Progress (2026-08-28): M4 is complete. Added atomic `checkpoint-last.json` and
`checkpoint-best.json` artifacts with checkpoint format, progress, model state, and
validation-selected metric metadata. Resume validates the task, seed, dataset, and split
digests before loading state. Failed validation or resume attempts write structured failed-run
metadata without overwriting an existing checkpoint. Verification: `mise exec -- uv run pytest`
(19 passed), `mise exec -- uv run ruff check src tests`, and `mise exec -- uv run ruff format
--check src tests`; no weights or data were downloaded.

### M5 — Export and table-observation capability

1. Export the smoke model bundle.
2. Validate bundle hashes and compatibility.
3. Load it through the stable runtime adapter without importing training modules.
4. Classify a supplied crop and produce identity candidates inside a schema-valid plan 0006
   observed-card fixture.

Acceptance:

- the backend does not import training internals;
- model output becomes normalized candidate probabilities;
- the bundle declares `identity_candidates` and does not claim other capabilities;
- calibration is declared `uncalibrated` until measured;
- repeated inference is deterministic for the fixture.

### M6 — Portable accelerator execution

1. Keep CPU as the test baseline.
2. Support MPS and CUDA through explicit device selection.
3. Record the actual device and precision.
4. Document provider-neutral filesystem staging for a larger run.

Acceptance:

- the same command and config shape selects CPU, MPS, or CUDA without an implicit fallback;
- automated device-selection tests cover all three requests and the unavailable-device failures;
- run metadata records the selected device and precision for the CPU smoke path;
- no cloud-provider SDK or Docker requirement enters the training code;
- a failed accelerator request does not silently run a different experiment.

## 12. Out of scope

- selecting the final visible-card detector, classifier, tracker, or video architecture;
- sourcing or accepting unreviewed labels;
- production accuracy targets;
- automatic hyperparameter sweeps;
- a hosted experiment platform or model registry;
- distributed training;
- automatic deployment after export;
- round or game reconstruction rules, or posterior correction;
- locating visible cards in a complete frame or evidence package;
- changing the plan 0025 capture profile based on smoke-model results.

## 13. Verification

Run:

```bash
mise install
cd table_evidence_analyzer
mise exec -- uv sync
mise exec -- uv run pytest
mise exec -- uv run ruff check .
mise exec -- uv run ruff format --check .
```

Run the CPU overfit, checkpoint-resume, export, and plan 0006 observation-fixture integration tests.
Automated tests must exercise explicit CPU, MPS, and CUDA selection without requiring an
accelerator. Run a real MPS or CUDA smoke test when that hardware is available and record it as
supplementary evidence. A real CUDA smoke test is required before relying on remote CUDA training,
but it is not required to close this local training-foundation plan.

## 14. Definition of done

- a frozen dataset manifest drives every sample;
- the project and package use the `table_evidence_analyzer` name;
- the active backend and analyzer boundary uses `table-observation/v1` without a legacy runtime
  path;
- dataset entries resolve to verified frame bytes and deterministic crops without directory scans;
- a tiny CPU run proves train, evaluate, checkpoint, resume, and export;
- run metadata captures code, data, environment, seed, and failures;
- bundle loading verifies hashes and compatibility;
- exported inference declares and implements one plan 0006 table-observation capability;
- ordinary tests remain local, fast, offline, and accelerator-independent;
- the next plan can compare recognition ideas without rebuilding experiment mechanics.
