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

The `table-analyzer` command exposes the local visible-card baseline and the planned training
command shape. Training, evaluation, export, classification, and dataset validation behavior will
land in later milestones.

```bash
table-analyzer --help
table-analyzer data validate --help
table-analyzer train --help
table-analyzer evaluate --help
table-analyzer export --help
table-analyzer classify-crop --help
table-analyzer identity-evaluate --help
table-analyzer visible-cards --help
table-analyzer visible-card-evaluate --help
table-analyzer visible-card-batch --help
table-analyzer visible-card-queue --help
table-analyzer review-visible-card --help
```

Run the first visible-card baseline on one exact-event JPEG. Use `--provider gemini` only when
`GEMINI_API_KEY` is present in the process environment. The fake provider is deterministic and
does not need credentials:

```bash
table-analyzer visible-cards \
  --image ../card_event_net/data/outputs/annotation-evidence-0ms/<package-id>/frames/frame_00.jpg \
  --package-id <package-id> \
  --frame-part-name frame_00 \
  --target-offset-ms 0 \
  --provider gemini \
  --output data/outputs/visible-card-run/<package-id>.json \
  --overlay data/outputs/visible-card-run/<package-id>.svg
```

The output contains the request contract, request key, normalized proposals, raw provider response,
token counts, latency, retry count, and estimated cost. Cache files are keyed by the full request
contract. Credentials are read at runtime and are never written to the result or cache.

Create and update a resumable review queue from one or more run artifacts:

```bash
table-analyzer visible-card-queue \
  --result data/outputs/visible-card-run/<package-id>.json \
  --run-id visible-card-m0-v1 \
  --output data/outputs/visible-card-review/m0.json

table-analyzer review-visible-card \
  --queue data/outputs/visible-card-review/m0.json \
  --item-id <package-id>:frame_00 \
  --decision GOOD \
  --reviewer <name>
```

All contract tests run locally and do not download weights, data, or call Gemini.

Evaluate identity feasibility with reviewed oracle crops. The command fits both deterministic
baselines from the train partition and writes top-1/top-k, confusion, and quality-tag metrics for
the selected partition. This is an identity measurement only; it does not measure visible-card
localization or produce a table observation:

```bash
table-analyzer identity-evaluate \
  --dataset ../data/derived/table-evidence/dataset.json \
  --split ../data/derived/table-evidence/split.json \
  --artifacts ../data/derived/table-evidence/artifacts/index.json \
  --partition validation \
  --output data/outputs/identity-feasibility/m1.json
```

After reviewed polygon references exist, evaluate one or more cached provider runs. The reference
file must use `visible-card-reference/v1` and must cover every supplied result exactly once:

```bash
table-analyzer visible-card-evaluate \
  --result data/outputs/visible-card-run/<package-id>.json \
  --reference data/outputs/visible-card-review/m2-references.json \
  --output data/outputs/visible-card-evaluation/m2.json
```

Run one exact-event request per extracted package. The default fake provider is local and
credential-free. Add `--resume` after an interrupted run. Use `--provider gemini` only when the
runtime environment contains `GEMINI_API_KEY` and the request cost is approved:

```bash
table-analyzer visible-card-batch \
  --evidence-root ../card_event_net/data/outputs/annotation-evidence-0ms-v1 \
  --output-dir data/outputs/visible-card-batch/m2 \
  --cache-dir data/cache/visible-cards \
  --provider fake
```
