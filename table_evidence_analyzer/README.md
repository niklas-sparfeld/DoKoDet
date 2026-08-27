# TableEvidenceAnalyzer

This package contains the stable table-observation contract and the local training-tool command
line for TableEvidenceAnalyzer capabilities. It does not capture evidence, apply game rules, or
locate cards in a complete evidence package.

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
