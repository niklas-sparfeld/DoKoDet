# TableEvidenceAnalyzer

This package contains the stable table-observation contract and the local training-tool command
line for TableEvidenceAnalyzer capabilities. It does not capture evidence or apply game rules.
The analyzer reads accepted evidence packages from the shared repository intake and writes only
task-specific derived artifacts.

## Shared evidence intake

Accepted packages are immutable source bundles under:

```text
../data/intake/evidence-packages/<package-id>/
```

The package contains `evidence-manifest.json`, selected frames, an optional video snippet, source
permission, independent task enrollments, and lineage. TableEvidenceAnalyzer can discover a
package only when its `table_evidence_analysis` enrollment has `disposition: selected`. It reads
the source files in place. It does not copy them into `table_evidence_analyzer/data/`.

Use the repository operations command to inspect the shared source and review work:

```bash
mise exec -- uv run --project ../operations doko data status --repository-root ..
mise exec -- uv run --project ../operations doko data review \
  --repository-root .. --task table_evidence_analysis --reviewer <name>
```

Pending uploads under `../data/incoming/videos/` are not visible to this task. Complete them with
the operations command before review. A review does not change source bytes or make a table
observation ground truth.

## Setup

From this directory:

```bash
mise exec -- uv sync
```

## Command line

The `table-analyzer` command currently exposes the planned command shape. Training, evaluation,
export, classification, and dataset validation behavior will land in later milestones.

```bash
table-analyzer --help
table-analyzer data validate --help
table-analyzer train --help
table-analyzer evaluate --help
table-analyzer export --help
table-analyzer classify-crop --help
```

All contract tests run locally and do not download weights or data.
