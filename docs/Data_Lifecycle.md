# DokoDetector data lifecycle

This page is the operator guide for source intake and the handoff to the recording pipeline.
CardEventNet owns source-video intake and event-model work. The recording pipeline owns table
observation review, dataset assembly, split validation, model-run provenance, and source-retention
impact.

Source bytes are immutable. Each operation reads its inputs and writes a new versioned artifact.

## Shared storage

Keep shared source bytes at the repository root:

```text
data/incoming/videos/<upload-id>/             pending upload
data/intake/recordings/<recording-id>/        complete recording bundle
data/intake/evidence-packages/<package-id>/   accepted evidence package
data/operations/                              durable review, pipeline, and analysis artifacts
.runtime/                                     disposable backend cache and local process state
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
    -> recording-pipeline table-observation revisions
    -> pipeline-owned dataset, split, and model-run artifacts
```

### 1. Import source material

Keep original videos and accepted evidence packages outside output directories. Run source intake
with operator metadata:

```bash
uv run cardevent ingest /path/to/source-videos \
  --operator-metadata data/source-metadata.yaml \
  --manifest .runtime/cardevent/ingestion/manifest.yaml \
  --index .runtime/cardevent/ingestion/ingestion-index.json \
  --operator niklas
```

This writes a source import receipt beside the ingestion index. The receipt contains the measured
source digests and the ingestion manifest and index versions. It does not move, rename, or rewrite
the source videos.

The recording pipeline owns table-observation creation and review. CardEventNet does not import
those observations or assemble a package-backed dataset.

### 2. Continue in the recording pipeline

Use the recording workspace for table-observation revisions and the operations tools for the
dataset, split, model-run, and source-retention records that depend on those revisions. The
recording pipeline is the owner of these later lifecycle steps. See the
[repository documentation route](../README.md#documentation-route) for the current component
entry points.

## Receipt rules

- The CardEventNet intake receipt uses semantic identifiers, not local paths as identity.
- Source references include the immutable source SHA-256.
- Receipts are strict `lifecycle-receipt/v1` documents and include their own content digest.
- A receipt records an operation. It does not grant permission or make an annotation ground truth.
- Source-retention state and impact records are owned by operations. They do not rewrite a source
  byte or a historical derived artifact.

## Checks before promotion

Run the intake status and validation checks before using a recording in the pipeline:

```bash
mise exec -- uv run --project operations doko data status --repository-root .
mise exec -- uv run --project operations doko data validate --repository-root .
```

The recording pipeline validates table-observation revisions and their dataset lineage before
model processing. Do not promote data when source bytes changed, source permission is invalid, a
review version is missing, lineage is ambiguous, a duplicate source is present, or a leakage group
crosses partitions.

## Adopt an old runtime package

Packages from the old runtime evidence path need one explicit adoption. Validate and publish the
package into shared intake:

```bash
mise exec -- uv run --project operations doko data adopt-evidence \
  --repository-root . --runtime-root .runtime \
  --package-id <package-id> --metadata package-metadata.json
```

The command keeps the old runtime package until the operator verifies the canonical bundle. After
verification, backend runtime state can be deleted and rebuilt. It must not be used as a second
source authority.
