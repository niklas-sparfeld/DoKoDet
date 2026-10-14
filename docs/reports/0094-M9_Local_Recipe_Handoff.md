# Epic 0094 M9: Local recipe handoff

## Result

The small CPU lifecycle now covers interrupt, exact resume, calibration, export, bundle reload, and
classification for all four combinations of encoder mode (`frozen` and `last_two_blocks`) and
feature layout (`cls` and `cls_mean_patch`) at 384 pixels. Each fixture calibration view contains
one synthetic sample for each of the 25 targets, including `FACE_DOWN`, and uses a separate source
group. The resumed run records the selected input size and recipe; the reloaded classifier returns
25 scores and FACE_DOWN probability metadata.

The CLI now exposes `--encoder-training frozen|last_two_blocks`, so the adapted recipe can be run
from the command line. Calibration also accepts direct training runs without a campaign manifest;
it still checks sample and source-group separation against the frozen dataset and split.

## Reusable commands

Run these from the repository root after 0088 has frozen a training view, recipe identity configs,
and a disjoint calibration-logit view. `IDENTITY_CONFIG` binds the input size, feature layout,
preprocessing and licensed pretrained asset. Set `ENCODER_MODE` to `frozen` or `last_two_blocks`.

```bash
WEIGHTS=data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-75000a5eec53a52f088f9e6e
RUN=path/to/0088/run
IDENTITY_CONFIG="$RUN/recipes/384-cls.json"
OUT="$RUN/results/384-cls-adapted"

mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  train-dinov3-identity \
  --dataset "$RUN/data/dataset.json" \
  --split "$RUN/data/split.json" \
  --artifacts "$RUN/data/artifact-index.json" \
  --identity-config "$IDENTITY_CONFIG" \
  --weights-root "$WEIGHTS" \
  --campaign-manifest "$RUN/manifest.json" \
  --output "$OUT" \
  --encoder-training last_two_blocks \
  --epochs 8 --batch-size 1 --device mps

# After an interruption, resume the same output with the last checkpoint.
mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  train-dinov3-identity \
  --dataset "$RUN/data/dataset.json" \
  --split "$RUN/data/split.json" \
  --artifacts "$RUN/data/artifact-index.json" \
  --identity-config "$IDENTITY_CONFIG" \
  --weights-root "$WEIGHTS" \
  --campaign-manifest "$RUN/manifest.json" \
  --output "$OUT" \
  --encoder-training last_two_blocks \
  --epochs 8 --batch-size 1 --device mps \
  --resume "$OUT/checkpoint-last.pt"

mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  calibrate-dinov3-identity \
  --run "$OUT" \
  --view "$RUN/data/calibration-logits.json" \
  --output "$RUN/results/384-cls-calibration.json"

mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  export-dinov3-identity \
  --run "$OUT" \
  --identity-config "$IDENTITY_CONFIG" \
  --weights-root "$WEIGHTS" \
  --calibration "$RUN/results/384-cls-calibration.json" \
  --output "$RUN/results/384-cls-bundle"

mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  evaluate-dinov3-identity \
  --run "$OUT" \
  --bundle "$RUN/results/384-cls-bundle" \
  --output "$RUN/results/384-cls-evaluation.json" \
  --device mps

mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer \
  classify-dinov3-identity \
  --bundle "$RUN/results/384-cls-bundle" \
  --image "$RUN/data/sample.ppm" \
  --device mps
```

Use `--encoder-training frozen` for the frozen encoder. Use an identity config with
`feature_layout: cls_mean_patch` to run the pooled feature layout. Set the config's declared input
size to 224 or 448 for those recipes. The adapted path requires batch size 1. Calibration input
must carry the completed run ID, best-checkpoint digest, target logits, and disjoint sample and
source lineage IDs. Calibration output is an explicit input to export; there is no implicit review
threshold.

## Dependencies and assets

The training dependency group pins PyTorch 2.13.0, torchvision 0.28.0, Transformers 5.16.1, and
safetensors 0.8.0. Python is 3.13. The materialized licensed asset is
`facebook/dinov3-vits16-pretrain-lvd1689m`, revision `master`, with model weights SHA-256
`4610ad75edef83e75afdebf162d148dc628045ea6cbb83d67d4708c709c4f91d` and config SHA-256
`9481247be9f95a134a5599402b4bfc838eecdf9a7fffbf4debd1c70ec213898b`. The file is 82 MiB in the
local bundle directory. The asset manifest records license `dinov3-license`, version `2025-08-19`,
accepted locally on 2026-09-17.

## Verification and resource results

The focused lifecycle and contract suite passed across training, augmentation,
checkpoint resume, frozen and adapted bundle reload, calibration, 224/384/448 transforms, local
identity contracts, and CLI parsing. The four new 384-pixel lifecycle cases use a generated small
encoder so they remain fast and deterministic. They are software contract evidence, not a model
quality result.

The materialized DINOv3 encoder also loaded with `local_files_only=True` and completed one CPU
forward pass on a zero-valued `[1, 3, 384, 384]` tensor. It returned finite `[1, 384]` pooled features.
On this Mac the process took 9.87 seconds and reached 510 MB maximum resident set size. This is a
single-forward feasibility measurement. It does not measure training time, throughput, MPS
behavior, or data quality.

Verification command:

```text
mise exec -- uv run --project table_evidence_analyzer --group training pytest -q -rA \
  table_evidence_analyzer/tests/test_dinov3_training.py \
  table_evidence_analyzer/tests/test_dinov3_augmentation.py \
  table_evidence_analyzer/tests/test_dinov3_bundle.py \
  table_evidence_analyzer/tests/test_dinov3_bundle_contract.py \
  table_evidence_analyzer/tests/test_dinov3_calibration.py \
  table_evidence_analyzer/tests/test_local_identity.py \
  table_evidence_analyzer/tests/test_cli.py
```

The handoff does not claim real-data accuracy, FACE_DOWN generalization, Gemini parity, promotion,
or completion of the reviewed identity corpus. The existing crop-cache visible-mask limitation
remains. Epic 0088 owns those campaign results.
