# 0096 M3 exact-reference evaluation

Date: 2026-10-17

## Outcome

M3 is complete. The report evaluates corrected M1 segmentation against maintained visible-card references on the exact decoded-image pairs frozen in M0. It excludes three training-only recordings under the M0 evaluation policy. It does not use timestamp proximity to create pairs.

The M0 manifest has 1,003 exact pairs across all permissions. Of these, 123 pairs belong to recordings excluded from evaluation and 880 are eligible. All 880 eligible pairs have M1 outputs. Ten paired frames have unresolved reference outcomes. The other 870 frames support scores. The reference set has 378 unpaired frames; they remain uncovered.

| Scope | Scoreable frames | Reviewed cards | Precision | Recall | F1 | Matched IoU |
|---|---:|---:|---:|---:|---:|---:|
| Outside 0092 M4 refit training | 323 | 850 | 0.897 | 0.925 | 0.911 | 0.898 |
| Overlaps 0092 M4 refit training | 547 | 1352 | 0.996 | 0.993 | 0.994 | 0.941 |
| All eligible pairs | 870 | 2202 | 0.957 | 0.966 | 0.962 | 0.925 |

The outside-training group has 786 matches, 90 false proposals, 64 misses, and 2 duplicate proposals at IoU `>= 0.5`. It covers 323 frames and 850 reviewed cards. The in-sample group is separate and must not be read as generalization evidence.

The evaluator uses the maintained pipeline comparison geometry metric, which rasterizes normalized polygon unions with the pixel-center even-odd rule. It uses the pipeline comparator's greedy one-to-one association and ignore-region handling at IoU `>= 0.5`. A frame with an ignore region remains scoreable; predictions that match the ignored geometry are neutralized. No prediction matched an ignore region in these outputs.

The frame you reviewed (`cardeventnet-event-img_0645-015`) is an exact M0 pair. It has 1 predicted card candidate and 2 reviewed card candidates, plus 1 ignored region. The predicted card matches one reviewed card at IoU 0.913; one reviewed card remains unmatched. Your visual approval is useful review evidence, but this one frame does not replace the bounded scene review.

## Scene measures

M2 published 29 calibrations and failed four calibration gates across 33 corrected recordings. The M2 report names the failures. The maintained reference revisions do not contain reviewed pile-region targets, 3D card poses, scene outlines, or stacking order. These measures are unsupported. The exact paired references contain no explicit reviewed-empty frames, so zero-card accuracy is unsupported. No empty label was inferred from a missing card list.

This M3 report does not promote the model or change defaults. In-sample and outside-training results remain separate. The full per-recording metrics and exact lineage are in [`0096-M3_Exact_Reference_Evaluation.json`](0096-M3_Exact_Reference_Evaluation.json). Rebuild the report with [`evaluate_0096_m3.py`](../../operations/scripts/evaluate_0096_m3.py) using the local pipeline stores.
