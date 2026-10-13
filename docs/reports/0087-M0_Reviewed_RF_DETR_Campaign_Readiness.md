# 0087 M0 reviewed RF-DETR campaign readiness

Date: 2026-10-13

## Decision

M0 is complete. The previous readiness decision treated `source-record.json.allowed_uses` as a
permission limit. That was incorrect for these imported recordings. The original CardEventNet
metadata gives all three selected recordings `source_permission: project_use`. The CardEventNet
importer maps that permission to train, validation, test, and evaluation. The persisted
`allowed_uses` values for seven imported recordings instead match historical split labels: six
match `default.yaml`, and `IMG_0661` matches the 0067 validation assignment. Treat those values as
old partition metadata, not as source permission.

Training readiness is ready for the frozen 0087 inputs. The source groups are disjoint, none was
used by 0067 validation or the 0068 sealed test, and the validation group has 36 pile targets. The
sealed test has no pile targets, so do not claim sealed-test pile quality.

## Frozen inputs

The deterministic manifest is
[`0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json`](0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json).
It uses 0086 M2 handoff digest
`57e63ce72236f9b8585c1787df84e7f6a4704b236230522d6ec8303de3e19a92`. Rebuilding the handoff from
the current source and reference stores returned the same digest and three eligible recordings.

| Split | Recording | Source permission | Retained frames | Visible-card targets | Pile targets |
| --- | --- | --- | ---: | ---: | ---: |
| Train | `cardeventnet-IMG_0095` | Project use | 42 | 105 | 38 |
| Validation | `cardeventnet-IMG_0097` | Project use | 40 | 103 | 36 |
| Sealed test | `cardeventnet-IMG_0654` | Project use | 48 | 130 | 0 |

The 0087 validation recording was in the 0068 train partition. The selected checkpoint is the
original pretrained checkpoint, not the 0068 candidate. The 0087 sealed-test recording was not in
the 0068 frozen campaign. Neither 0087 holdout group was used by the recorded 0067 validation or
0068 sealed-test evaluation.

The permission audit preserves the recorded stage values and derives effective uses from the
original `source_permission` with the same rule as the CardEventNet importer. It records the
legacy split file digest and all seven stage-value mismatches. The selected source metadata files
also have content digests in the manifest. This correction changes no source permission value.

The checkpoint is RF-DETR SegMedium from `rfdetr==1.9.4` at
`.runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt`, SHA-256
`3ad325094735f431aee9962a8d204d68eb5bfc393d53e7e836e70998fef5ea58`.

## Frozen gates

Train and validation each meet the minimum support of 30 retained frames, 100 visible-card targets,
and 30 pile targets. The sealed test meets its visible-card support minimum of 30 frames and 100
targets, but has no pile target. M3 uses one corrected-real-only candidate and compares it with the
pinned pretrained checkpoint. No paired retraining control is defined because the prior campaign
does not provide an unchanged common validation split and compatible source groups.

The manifest freezes class-specific mask and box metrics, recall, class confusion, pile-contained
card predictions, card recall near piles, false detections, duplicates, empty predictions, and
per-recording coverage. It includes ordinary overlapping tricks, small-card, frame-edge, human-hand,
and pile slices when supported by the real references. The M3 candidate budget is 7,200 seconds.
M4 permits one fixed synthetic mixture with equal real-sample exposure and the same budget. Omit it
with a recorded reason if no compatible two-class synthetic pool is available. No training or test
inference was run.

## Repeat the freeze

From the repository root, run:

```sh
mise exec -- uv run --project operations --group inference \
  python operations/scripts/freeze_0087_m0.py
```

The command validates the source permission against the original imported metadata and writes the
deterministic manifest. The manifest retains the historical `allowed_uses` values as audit
evidence but uses the permission-derived stage policy for the frozen campaign split.
