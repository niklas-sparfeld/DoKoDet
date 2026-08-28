# DokoDetector data lifecycle

This page is the operator guide for the data foundation. It covers source intake, table-observation
review, dataset promotion, split creation, model-run provenance, and source retirement.

The source bytes are immutable. Each operation reads its inputs and writes a new versioned artifact
with a lifecycle receipt. A receipt names the source assets, annotation sets, reviews, dataset
versions, splits, derived artifacts, and runs that it touches.

## Shared storage

Keep shared source bytes at the repository root:

```text
data/incoming/videos/<upload-id>/             pending upload
data/intake/recordings/<recording-id>/        complete recording bundle
data/intake/evidence-packages/<package-id>/   accepted evidence package
data/operations/                              review and lifecycle artifacts
backend/.runtime/                             disposable backend state
```

A pending upload is not a recording and is not an evidence package. It is not visible to a data
task. The backend and operations tools resolve these paths from the repository root.

Inspect the intake before an operation:

```bash
mise exec -- uv run --project operations doko data status --repository-root .
mise exec -- uv run --project operations doko data validate --repository-root .
```

Complete a pending upload only after the operator has supplied the required source metadata and the
two independent task enrollments:

```bash
mise exec -- uv run --project operations doko data complete-video \
  --repository-root . --upload-id <upload-id> --metadata completion.json
```

The command publishes one recording bundle by atomic rename. It does not change the source digest.
If it fails, the pending upload remains available for retry.

## Normal flow

```text
source bytes
    -> source import receipt
    -> draft table observation
    -> reviewed annotation + apply receipt
    -> eligible dataset version + creation receipt
    -> group-safe split + creation receipt
    -> model run receipt
```

### 1. Import source material

Keep original videos and accepted evidence packages outside output directories. Run source intake
with operator metadata:

```bash
uv run cardevent ingest data/raw \
  --operator-metadata data/source-metadata.yaml \
  --manifest data/index/manifest.yaml \
  --index data/index/ingestion-index.json \
  --operator niklas
```

This writes a source import receipt beside the ingestion index. The receipt contains the measured
source digests and the ingestion manifest and index versions. It does not move, rename, or rewrite
the source videos.

For an accepted evidence package, create draft table observations in a new directory. Read the
package from shared intake; do not copy its source media into a component data directory:

```bash
uv run cardevent vision-import fixtures/evidence/v2/example-complete \
  --out-dir data/table-observations/draft \
  --operator niklas
```

Use `data/intake/evidence-packages/<package-id>` in place of the fixture path for repository data.
The import receipt records the evidence package and draft annotation-set versions. A draft is not
eligible data.

### 2. Review and apply annotations

Review all available frames and the optional video snippet:

```bash
uv run cardevent vision-review \
  --annotation data/table-observations/draft/annotation-set-001.json \
  --frames-dir data/intake/evidence-packages/<package-id>/frames \
  --out data/table-observation-reviews/review-001.json \
  --reviewer niklas

uv run cardevent vision-apply-review \
  --annotation data/table-observations/draft/annotation-set-001.json \
  --review data/table-observation-reviews/review-001.json \
  --out-dir data/table-observations/reviewed/annotation-set-001
```

The apply command leaves the draft annotation and review input unchanged. Its
`table-observation-apply-receipt.json` contains a standard lifecycle receipt. The receipt links
the input annotation version, the review version, and the new reviewed annotation version.

A false event proposal can still have visible-card evidence. A visible card is not a card-play
label. Do not edit a source file to correct either decision.

### 3. Create an eligible dataset version

Build the frozen TableEvidenceAnalyzer manifest from reviewed annotations, source records, and
lineage:

```bash
uv run cardevent dataset-build \
  --annotations data/table-observations/reviewed \
  --reviews data/table-observation-reviews \
  --sources data/source-records.json \
  --lineage data/lineage.json \
  --dataset-version-id table-evidence-20260827 \
  --out data/datasets/table-evidence.json \
  --operator niklas
```

The command writes `dataset-creation-receipt.json` beside the coverage reports. The receipt names
every source asset, reviewed annotation set, review, and dataset-version digest used to create the
manifest. Unassigned and excluded records remain in the assembly and coverage reports.

### 4. Create a group-safe split

Create a split only after the dataset version is frozen:

```bash
uv run cardevent dataset-split \
  --dataset data/datasets/table-evidence.json \
  --split-version-id table-evidence-split-20260827 \
  --out data/datasets/table-evidence-split.json \
  --operator niklas
```

The split receipt binds the split to the dataset digest. The split keeps connected session, game,
table-setup, and source-lineage groups together. The `validation` partition name is canonical.
Unassigned entries are explicit and are not silently placed in a partition.

### 5. Record model-run provenance

The TableEvidenceAnalyzer training loop can create a run receipt before or after it writes model
artifacts:

```bash
uv run cardevent training-receipt \
  --dataset data/datasets/table-evidence.json \
  --split data/datasets/table-evidence-split.json \
  --training-run-id table-evidence-run-001 \
  --model-bundle-id table-evidence-model-001 \
  --derived-artifact-id crop-cache-001 \
  --out data/runs/table-evidence-run-001/lifecycle-receipt.json \
  --operator niklas
```

The receipt expands the dataset entries. It names every source asset, annotation set, review,
dataset version, and split version used by the run. The run does not need to scan local directories
to reconstruct its provenance.

### 6. Retire or withdraw a source asset

When permission is withdrawn, write a new source-record version. Select
`deletion_requested` while a deletion decision is pending, or `retired` when the asset is no longer
available for use:

```bash
uv run cardevent retire-source \
  --sources data/source-records.json \
  --source-asset-id source-001 \
  --receipts-dir data/receipts \
  --retention-state deletion_requested \
  --reason "permission withdrawn" \
  --out data/source-records-deletion-requested.json \
  --operator niklas
```

The command does not delete or edit source bytes. It writes a new source-record collection and a
retirement receipt. The receipt lists affected annotation sets, dataset versions, splits, derived
artifacts, model bundles, and training runs. Review that impact before deleting disposable derived
artifacts or invalidating runs.

## Receipt rules

- Receipt inputs and outputs use semantic identifiers, not local paths as identity.
- Source references include the immutable source SHA-256.
- Version references include the dataset or split digest.
- Receipts are strict `lifecycle-receipt/v1` documents and include their own content digest.
- Existing receipts are not overwritten unless a command is run with `--force`.
- A receipt records an operation. It does not grant permission or make an annotation ground truth.
- A source retirement changes the source-record state. It does not rewrite an annotation, dataset,
  model, or source byte.

## Checks before promotion

Run the frozen dataset validation command before a training run:

```bash
uv run cardevent dataset-validate \
  --dataset data/datasets/table-evidence.json \
  --sources data/source-records.json \
  --lineage data/lineage.json \
  --annotations data/table-observations/reviewed \
  --reviews data/table-observation-reviews \
  --split data/datasets/table-evidence-split.json
```

Do not promote a dataset when source bytes changed, source permission is invalid, a review version
is missing, lineage is ambiguous, a duplicate source is present, or a leakage group crosses
partitions.

## Adopt an old runtime package

Packages from the old runtime evidence path need one explicit adoption. Validate and publish the
package into shared intake:

```bash
mise exec -- uv run --project operations doko data adopt-evidence \
  --repository-root . --runtime-root backend/.runtime \
  --package-id <package-id> --metadata package-metadata.json
```

The command keeps the old runtime package until the operator verifies the canonical bundle. After
verification, backend runtime state can be deleted and rebuilt. It must not be used as a second
source authority.
