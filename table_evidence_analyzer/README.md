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

The `table-analyzer` command exposes the local visible-card baseline and the bounded training
command. The local RF-DETR provider is a Python adapter; backend provider selection is a later
milestone.

```bash
table-analyzer --help
table-analyzer data validate --help
table-analyzer data materialize-visible-card-dataset --help
table-analyzer train --help
table-analyzer evaluate --help
table-analyzer export --help
table-analyzer classify-crop --help
table-analyzer identity-evaluate --help
table-analyzer visible-cards --help
table-analyzer visible-card-evaluate --help
table-analyzer visible-card-batch --help
table-analyzer visible-card-observe --help
table-analyzer visible-card-queue --help
table-analyzer review-visible-card --help
table-analyzer review-visible-card-action --help
table-analyzer complete-visible-card-review --help
table-analyzer freeze-visible-card-review --help
table-analyzer visible-card-prompt-pilot --help
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

Run the existing v1 request and the opt-in v2 visible-region request on the same 20 development
frames. The manifest must use `visible-card-prompt-pilot-input/v1` and mark every frame as
`development`. The pilot cannot select a request from validation, challenge, test, or system-holdout
frames. Use `--provider fake` for a credential-free contract run, or `--provider gemini` when the
runtime credential and request cost are approved:

```bash
table-analyzer visible-card-prompt-pilot \
  --manifest data/outputs/visible-card-prompt-pilot/m0-frames.json \
  --provider gemini \
  --selected-version v2 \
  --selection-reason "Visible-region and tight-box instructions are explicit." \
  --output data/outputs/visible-card-prompt-pilot/m0.json
```

The report stores both request contracts and both result records for every frame. Existing v1
requests and caches remain separate from v2 because the request version, full prompt, and response
schema are part of the cache key.

Create a v2 resumable geometry-review queue from one or more run artifacts. The lineage manifest
must identify the source asset and source-lineage group for every frame:

```bash
table-analyzer visible-card-queue \
  --result data/outputs/visible-card-run/<package-id>.json \
  --run-id visible-card-m0-v1 \
  --lineage-manifest data/outputs/visible-card-review/source-lineage.json \
  --output data/outputs/visible-card-review/m0.json

table-analyzer review-visible-card \
  --queue data/outputs/visible-card-review/m0.json \
  --item-id <package-id>:frame_00 \
  --decision GOOD \
  --not-empty-frame \
  --reviewer <name>

Save one action at a time. Use `accepted` for teacher geometry, `reshaped` for corrected geometry,
`added` for a missed card, and `removed` for a false proposal. A reviewed card JSON object contains
the visible-region polygons, its derived tight box, side, identity usability, and failure tags:

table-analyzer review-visible-card-action \
  --queue data/outputs/visible-card-review/m0.json \
  --item-id <package-id>:frame_00 \
  --action reshaped \
  --card-id card-001 \
  --proposal-index 0 \
  --reviewed-card data/outputs/visible-card-review/card-001.json \
  --reviewer <name>

Finish a GOOD frame only after every teacher proposal has an action. The queue remains resumable
when this command has not run:

table-analyzer complete-visible-card-review \
  --queue data/outputs/visible-card-review/m0.json \
  --item-id <package-id>:frame_00 \
  --reviewer <name>
```

The queue stores the original teacher request and result digests beside each reviewed decision.
`BAD --empty-frame` is an explicit reviewed empty frame; a BAD frame without that flag remains a
different decision. Incomplete queue items cannot pass the completed-review validator. All contract
tests run locally and do not download weights, data, or call Gemini.

Freeze the review wording, source-group partitions, coverage report, teacher set, and crop policy
before a detector comparison. The pilot report must contain exactly 20 development frames and a
selected request version. The partition file must assign every completed queue item to `train`,
`validation`, or `challenge` and must list excluded system-holdout source groups:

```bash
table-analyzer freeze-visible-card-review \
  --queue data/outputs/visible-card-review/m0.json \
  --pilot-report data/outputs/visible-card-prompt-pilot/m0.json \
  --partitions data/outputs/visible-card-review/m2-partitions.json \
  --output-dir data/outputs/visible-card-review/m2-freeze
```

The output contains immutable `teacher-manifest.json`, `train-manifest.json`,
`validation-manifest.json`, `challenge-manifest.json`, `coverage-report.json`,
`review-policy.json`, `crop-policy.json`, and `freeze-manifest.json` files. The coverage report
counts frames by source-lineage group and failure tag. It states the gap to 100 usable seed frames,
five source groups, and the 40% maximum group share when the corpus does not meet those targets.
The train, validation, and challenge partitions cannot share a source-lineage group, and the
system holdout cannot enter the freeze.

The crop policy is fixed before evaluation: `raw_rectangular` crops the derived box,
`oracle_visible_region` replaces pixels outside the reviewed polygons with RGB `(128, 128, 128)`,
and `conservative_box_only` rejects a card unless identity is usable and it has no failure tags.
No crop policy is chosen from validation or challenge results.

Materialize the bounded local visible-card detector dataset from an existing exact-event
extraction and cached provider run artifacts. The output references source frames in place and
contains `dataset-manifest.json`, `annotations.json`, `split.json`, and `recipe.json`:

```bash
table-analyzer data materialize-visible-card-dataset \
  --evidence-root ../card_event_net/data/outputs/annotation-evidence-0ms \
  --results-root data/outputs/visible-card-batch/m2/results \
  --output-dir data/outputs/visible-card-dataset/m0
```

The command selects 20 frames, adds only enough deterministic frames to represent three
source-lineage groups and non-empty pseudo-label examples in both partitions, and never selects
more than 40 frames. Gemini boxes remain marked `unreviewed_pseudo_label`; the output is not a
reviewed-reference dataset. The recipe freezes RF-DETR Large (`rfdetr==1.9.4`), 704 x 704 input,
one CUDA device, 20 epochs, seed 37, and a 0.5 confidence threshold.

Run one bounded RF-DETR training operation on a CUDA machine. The dataset and source evidence are
mounted inputs. The checkpoint and all generated files stay below the mounted output path:

```bash
mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  train-visible-card-detector \
  --dataset-dir /mnt/input/visible-card-dataset/m0 \
  --evidence-root /mnt/input/annotation-evidence-0ms \
  --pretrained-checkpoint /mnt/input/rf-detr-large.pth \
  --output-dir /mnt/output/visible-card-training/m1
```

The command writes `run.json`, RF-DETR outputs, and a digest-checked `bundle/` with
`checkpoint_best_total.pth`. Use `--runner fixture` for local contract tests. The fixture runner
does not import RF-DETR or download weights.

Load the native local detector on an explicit CPU or MPS device. The provider converts RF-DETR
pixel boxes to the normalized visible-card proposal contract and keeps the bundle digest and
detector scores in `raw_response`. Install the inference group on the target Mac:

```bash
mise exec -- uv sync --project table_evidence_analyzer --group inference
```

```python
from table_evidence_analyzer import LocalVisibleCardProvider

provider = LocalVisibleCardProvider(
    "data/outputs/visible-card-training/m1/bundle",
    device="cpu",  # use "mps" only when the runtime supports it
)
```

Malformed input and detector failures return a `ProviderResult` with `status="unavailable"`.
The provider does not move MPS inference to CPU.

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

Join visible-card proposals to the exported identity capability and write canonical
`table-observation/v1` artifacts. The bundle must declare `identity_candidates`; its calibration
state is copied to each observation. The adapter uses an axis-aligned bounding crop of each
provider polygon and records crop and provider provenance in diagnostics. It does not add presence,
tracking, or game-state claims:

```bash
table-analyzer visible-card-batch \
  --evidence-root ../card_event_net/data/outputs/annotation-evidence-0ms-v1 \
  --output-dir data/outputs/visible-card-batch/observations \
  --cache-dir data/cache/visible-cards \
  --identity-bundle data/outputs/identity-bundle \
  --provider fake
```

For one frame, use `visible-card-observe`. Use `--provider gemini` only when the runtime
environment contains `GEMINI_API_KEY` and the request cost is approved.

The proof-of-concept Gemini identity classifier consumes the deterministic polygon crop, converts
it to PNG for the API, and emits a single canonical visual card identity only when the crop is
readable. `UNKNOWN` produces no identity candidate. Its responses are cached separately from
visible-card proposals and the observation records classifier token and cost data:

```bash
table-analyzer visible-card-observe \
  --image ../card_event_net/data/outputs/annotation-evidence-0ms/<package-id>/frames/frame_00.jpg \
  --package-id <package-id> \
  --provider gemini \
  --identity-classifier gemini \
  --output data/outputs/table-observation/<package-id>.json
```

For a batch, pass `--identity-classifier gemini` to `visible-card-batch`. Both Gemini stages need
`GEMINI_API_KEY`; run them only when the request cost is approved.
