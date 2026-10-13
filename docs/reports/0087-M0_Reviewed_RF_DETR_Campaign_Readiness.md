# 0087 M0 reviewed RF-DETR campaign readiness

Date: 2026-10-13

## Decision

M0 is complete. The immutable campaign manifest freezes the eligible references, source groups,
prior evaluation use, split, recipe, checkpoint, candidate counts, budgets, and quality gates.
Two-class training is blocked because the only group that allows validation has no positive pile
targets. Do not train until this support gap is resolved or the campaign gate changes through a
reviewed plan update.

No sealed test is available. The two groups that allow training only cannot be used for evaluation.
The remaining group allows validation and test, so it is reserved for validation. Do not relabel a
train-only group as a test group.

## Frozen inputs

The deterministic manifest is
[`0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json`](0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json).
It uses 0086 M2 handoff digest
`57e63ce72236f9b8585c1787df84e7f6a4704b236230522d6ec8303de3e19a92`. Rebuilding the handoff from
the current source and reference stores returned the same digest and three eligible recordings.

| Split | Recording | Permission | Retained frames | Visible-card targets | Pile targets |
| --- | --- | --- | ---: | ---: | ---: |
| Train | `cardeventnet-IMG_0095` | Train only | 42 | 105 | 38 |
| Train | `cardeventnet-IMG_0097` | Train only | 40 | 103 | 36 |
| Validation | `cardeventnet-IMG_0654` | Train, validation, test, evaluation | 48 | 130 | 0 |

The three source groups are disjoint. None was used by the recorded 0067 validation or 0068 sealed
test. The two train groups were in the 0068 train partition. The 0087 validation group was outside
that frozen campaign. The evaluation uses the pinned pretrained checkpoint, not the old 0068
candidate.

The checkpoint is RF-DETR SegMedium from `rfdetr==1.9.4` at
`.runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt`, SHA-256
`3ad325094735f431aee9962a8d204d68eb5bfc393d53e7e836e70998fef5ea58`. The artifact was verified in
the main checkout. It is not present in this secondary worktree.

## Readiness gaps

- The validation recording has 0 reviewed `card_pile` targets. The frozen minimum is 30. The
  two-class pile AP and recall gates cannot be measured on this validation split.
- No independent sealed-test group remains after source permissions and the validation assignment.
  M5 must record test evaluation as unavailable.
- The M3 design has one corrected-real-only candidate and the pinned pretrained checkpoint as the
  control. There is no paired retraining control because no unchanged common validation split and
  compatible prior source-group assignments exist.
- M4 permits one fixed synthetic mixture with equal real-sample exposure. Omit it with a recorded
  reason if a compatible two-class synthetic pool is not available.

The manifest freezes visible-card comparisons to the pretrained validation result, per-class mask
and box metrics, recall, false detections, duplicates, empty predictions, recording coverage, and
the supported pile and overlap slices. It requires 30 retained frames, 100 visible-card targets,
and 30 pile targets in train and validation. It also freezes a 7,200-second budget for each
candidate. No protected contributor is assigned to training. No training or test inference was run.

## Repeat the freeze

From the repository root, run:

```sh
mise exec -- uv run --project operations --group inference \
  python operations/scripts/freeze_0087_m0.py \
  --checkpoint /Users/niklas.sparfeld/Developer/doko_detector/.runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt
```

The command writes the deterministic manifest and reports `training_readiness: blocked` while
validation pile support remains below the frozen minimum.
