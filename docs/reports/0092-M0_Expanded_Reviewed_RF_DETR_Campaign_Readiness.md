# 0092 M0 expanded reviewed RF-DETR campaign readiness

Date: 2026-10-14

## Decision

M0 is complete and training readiness is ready. The current 0086 M4 handoff has 20 eligible
recordings and 20 distinct source groups. All 20 have completed `visible-card-data/v2` references,
reviewed visible-card masks, explicit pile coverage, source-group lineage, and training permission.
The permanent `IMG_0092` exclusion and temporary `IMG_0096` deferral remain in force.

The deterministic manifest is
[`0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json`](0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json).
It pins the 0086 M4 handoff digest `503408822bc123b2ebb0f8388f8aed7d9378479b196b9f2e1cd244dbae89c1e6`,
all selected event and reference revisions, original source permissions, source groups, prior
evaluation use, recipe, checkpoint, support, budgets, and exclusions. Its digest is
`bd452cc3f904007ed481af1f13b56e3910374c0d9392dfbf42de900379e741fa`.

## Frozen partitions

The previous 0087 validation and sealed-test groups, `IMG_0097` and `IMG_0654`, are assigned to
training only. The new validation and sealed-test groups have no prior campaign evaluation use.
All source-group, session, table, asset, and video lineage values are disjoint between partitions.

| Partition | Recordings | Retained frames | Visible-card targets | Pile targets |
| --- | --- | ---: | ---: | ---: |
| Train | 16 | 684 | 1,835 | 170 |
| Validation | `IMG_0651`, `IMG_0658` | 98 | 270 | 87 |
| Sealed test | `IMG_0656`, `IMG_0660` | 92 | 247 | 105 |

Both validation recordings contain reviewed piles. The fresh sealed test also has reviewed pile
targets, so report pile quality only for the pile-bearing results that pass the selected partition
checks. The test stays unopened until the validation result and decision are locked.

The frozen recipe uses RF-DETR SegMedium at 432×432, `rfdetr==1.9.4`, the two-class map from 0091,
one real-only candidate, and seed 6701. It uses the selectable 0087 bundle as the measured baseline
(`018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9`) and the pinned pretrained
checkpoint as a second reference. The runtime default remains `gemini`.

The candidate budget is 144,000 seconds. The final-refit budget is 180,000 seconds. These limits
scale the 0087 observed 6,503.74-second run from 42 retained training frames to the 0092 train and
full-pool frame counts, with about 34 percent margin. Source-video bytes were not rehashed. No
training or test inference ran in M0.

## Reproduction

Rebuild the read-only 0086 handoff and then freeze 0092 M0:

```sh
mise exec -- uv run --project operations python operations/scripts/build_0086_detection_handoff.py \
  --repository-root . --output .runtime/0086-m4/detection-handoff.json
mise exec -- uv run --project operations python operations/scripts/freeze_0092_m0.py
```

The freeze fails if the candidate set, permissions, reference digests, source groups, prior
evaluation use, support, pretrained checkpoint, 0087 decision, or selected bundle changes. The
0087 candidate bundle remains under `.runtime`; no model weights are committed.
