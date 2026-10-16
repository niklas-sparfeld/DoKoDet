# 0088 M7 fine-tuning skip

## Decision

M7 is not required under its frozen M0 entry gate. Do not run an encoder fine-tuning fit in this
milestone.

The best frozen candidate, M6's 224-pixel CLS-plus-mean-patch model, reached 207/208 face-up
top-1 (99.52%) on the model-selection view. This is above the declared 98% target. The independent
source-group support gate also fails: only two groups contribute, while the minimum is three
evaluation groups per class. M7 requires the frozen candidate to miss the target and the support
gate to pass. Neither condition is met.

This skip follows the campaign's conditional gate. It does not show that fine-tuning cannot improve
the classifier for annotation assistance. The final test remains sealed. M3 CLS and M6 pooled
features remain the finalists for M10.

## Evidence

- [M0 readiness contract](0088-M0_Campaign_Readiness.md): candidate gates and per-class support.
- [M6 pooled-feature report](0088-M6_Pooled_Features.md): 207/208 face-up top-1 and two source
  groups.
