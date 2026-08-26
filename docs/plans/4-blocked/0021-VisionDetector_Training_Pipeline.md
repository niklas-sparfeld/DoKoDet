# DokoDetector VisionDetector — Training Pipeline Foundation

## Plan status

- **Summary:** Build a reproducible VisionDetector train/evaluate/export loop before model research
- **Status:** Blocked
- **Depends on:** Plan 0020 milestone M1
- **Reviewed:** 2026-08-26 against the current CardEventNet training pipeline
- **Starts early:** Use tiny generated fixtures before enough real VisionDetector data exists
- **Unblocks:** The future recognition-development plan

## 1. Outcome

Build the reusable mechanics for VisionDetector experiments without selecting the final recognition
architecture.

At the end of this plan, one local command sequence can:

```text
frozen tiny dataset manifest
  -> validated samples and deterministic transforms
  -> CPU smoke training
  -> checkpoint and resume
  -> held-out evaluation
  -> machine-readable run report
  -> versioned detector bundle
  -> inference through the plan 0005 interface
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

Do not import CardEventNet temporal-event code into VisionDetector. The tasks, inputs, labels, and
metrics differ. Share small general utilities only after two real consumers justify extraction.

Plan 0020 owns source, annotation, review, lineage, and dataset eligibility. This plan consumes a
frozen dataset manifest. It must not scan raw directories and decide which labels are trustworthy.

Plan 0005 owns the production-facing detector input and result contract. Training code may expose
additional diagnostics, but exported inference must use that boundary.

## 3. Initial project shape

Extend the lightweight `vision_detector/` package from plan 0005:

```text
vision_detector/
├── pyproject.toml
├── uv.lock
├── README.md
├── configs/
│   ├── smoke.yaml
│   └── baseline.yaml
├── src/vision_detector/
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
visiondet data validate --dataset <manifest>
visiondet train --config <config>
visiondet evaluate --run <run-dir> --split validation
visiondet export --run <run-dir> --output <bundle-dir>
visiondet infer --bundle <bundle-dir> --evidence <package-dir>
```

Keep command names stable only after their first contract tests exist. Do not add `mise` tasks that
only wrap these commands.

## 4. Dataset adapter contract

The loader accepts an explicit dataset and split version from plan 0020. Every sample contains:

- stable sample and source identifiers;
- source frame or crop reference plus content digest;
- target and target-schema version;
- annotation and review version;
- deck and card-set version;
- transform lineage;
- session and game leakage groups;
- allowed-use state.

The first training task is oracle-crop card identity because it isolates identity recognition from
localization. Use reviewed human crops from real data when they exist. Until then, use a tiny
generated fixture with obvious labels to test mechanics only.

The loader must reject:

- unknown schema versions;
- missing or changed source bytes;
- unreviewed or ineligible samples;
- card identities outside the declared card set;
- overlap between leakage groups across partitions;
- derived artifacts whose transform version does not match the manifest.

Do not silently skip invalid samples. Evaluation reports every excluded or failed item.

## 5. Configuration and reproducibility

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

## 6. Model adapter

Define a small task interface rather than coupling training to one library model:

```python
class TrainableVisionTask(Protocol):
    def build_model(self, config: ModelConfig): ...
    def compute_loss(self, batch: Batch, outputs: Outputs): ...
    def decode(self, outputs: Outputs) -> Predictions: ...
    def metrics(self, predictions: Predictions, targets: Targets): ...
```

The first adapter is a small 24-class or deck-manifest-sized crop classifier. Its purpose is to
exercise the pipeline. Do not present it as the chosen production architecture.

Later localization and multi-frame tasks may add adapters. They must retain the same run,
checkpoint, dataset, and evaluation contracts.

## 7. Checkpoints and resume

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

## 8. Evaluation contract

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

Model calibration, event-card localization, and complete evidence-package evaluation belong to the
recognition-development plan, but they should reuse this report envelope.

## 9. Detector bundle contract

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

The bundle adapter implements the plan 0005 `VisionDetector` interface. For the oracle-crop smoke
task, a test-only evidence adapter may use annotated crops. Do not claim that this is end-to-end
event recognition.

## 10. Small implementation milestones

### M0 — Project and smoke dataset

1. Add the Python project and CLI skeleton.
2. Add a tiny generated image dataset through the plan 0020 manifest adapter.
3. Validate split, lineage, target, and digest rules.
4. Add one fast data-loader integration test.

Acceptance:

- `mise install` and `uv sync` reproduce the environment;
- tests do not download weights or data;
- invalid lineage and split leakage fail clearly.

### M1 — Minimal train and evaluate loop

1. Add the first crop-classification adapter.
2. Train it to overfit the tiny fixture on CPU.
3. Write sample predictions and the run report.
4. Add deterministic evaluation transforms and seeded training transforms.

Acceptance:

- the smoke run completes in ordinary local development time;
- the expected fixture metric is asserted;
- training and evaluation use the same class and preprocessing contracts.

### M2 — Checkpoint, resume, and failure records

1. Save last and best checkpoints.
2. Resume an interrupted smoke run.
3. Reject incompatible resume inputs.
4. Preserve a structured record for a failed run.

Acceptance:

- resumed and uninterrupted smoke runs have equivalent semantic progress;
- best-checkpoint selection uses validation only;
- corrupt checkpoints fail without damaging prior artifacts.

### M3 — Export and plan 0005 inference

1. Export the smoke model bundle.
2. Validate bundle hashes and compatibility.
3. Load it through the detector adapter.
4. Produce a schema-valid plan 0005 result from a real-image integration fixture.

Acceptance:

- the backend does not import training internals;
- model output becomes normalized candidate probabilities;
- calibration is declared `uncalibrated` until measured;
- repeated inference is deterministic for the fixture.

### M4 — Portable accelerator execution

1. Keep CPU as the test baseline.
2. Support MPS and CUDA through explicit device selection.
3. Record the actual device and precision.
4. Document provider-neutral filesystem staging for a larger run.

Acceptance:

- the same command and config shape work locally and on one CUDA machine;
- no cloud-provider SDK or Docker requirement enters the training code;
- a failed accelerator request does not silently run a different experiment.

## 11. Out of scope

- selecting the final detector, classifier, tracker, or video architecture;
- sourcing or accepting unreviewed labels;
- production accuracy targets;
- automatic hyperparameter sweeps;
- a hosted experiment platform or model registry;
- distributed training;
- automatic deployment after export;
- game-engine rules or posterior correction.

## 12. Verification

Run:

```bash
cd vision_detector
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Run the CPU overfit, checkpoint-resume, export, and plan 0005 inference integration tests. Run one
optional CUDA smoke test before relying on remote training.

## 13. Definition of done

- a frozen dataset manifest drives every sample;
- a tiny CPU run proves train, evaluate, checkpoint, resume, and export;
- run metadata captures code, data, environment, seed, and failures;
- bundle loading verifies hashes and compatibility;
- exported inference implements the plan 0005 contract;
- ordinary tests remain local, fast, offline, and accelerator-independent;
- the next plan can compare recognition ideas without rebuilding experiment mechanics.
