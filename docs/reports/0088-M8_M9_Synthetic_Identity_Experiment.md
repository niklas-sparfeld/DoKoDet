# 0088 M8/M9 synthetic identity experiment plan

## Decision

On 2026-10-16, the user authorized one exploratory synthetic-training comparison for annotation
assistance. This updates the active 0088 plan after its original M0 freeze. It does not change the
frozen source-group partitions, real-only evaluation, formal quality gates, or fit caps. The earlier
[M8 skip record](0088-M8_Synthetic_Pool_Skip.md) remains a record of the original gate decision and
is superseded by this plan.

## Basis in the 0070 generator

Epic 0070 already provides deterministic card cutouts, alpha masks, scene rendering, exact
visible-region masks, per-instance receipts, and source lineage. Its renderer emits a generic
`visible_card` segmentation class. It does not emit DINO visual-identity labels. M8 must join each
eligible cutout to an exact reviewed 0088 training identity. The join must use source asset, frame,
item, and crop lineage. Do not infer identity from the segmentation label or from pixels.

Reuse the existing renderer and its rendered appearance variation. Add only a small adapter to
produce the DINO crop and support mask for each rendered card. Limit every real source, background,
and geometry contributor to the frozen 0088 training groups. Use a fixed neutral canvas when no
eligible training background exists. If a contributor cannot be proven to be training-only or its
identity cannot be joined exactly, exclude it. If no eligible pool remains, publish a skip receipt
and do not train.

## Frozen experiment

- Source set: exact reviewed identity crops in the 0088 training partition only.
- Pool: one deterministic rendered appearance per eligible real training crop; pool size cannot
  exceed the eligible real training crop count.
- Labels: inherit the exact reviewed identity of the contributing cutout.
- Masks: use the renderer's exact visible-region mask; apply the same DINO crop and preprocessing
  policy as real samples.
- `FACE_DOWN`: augment only if an eligible reviewed training contributor exists. Synthetic copies
  do not increase its reviewed sample or source-group counts or qualify back-design generalization.
- Evaluation: the unchanged real M6 model-selection crops. No synthetic validation or test rows.
- Candidate: 224-pixel CLS plus mean patch features, frozen encoder, seed 17, eight epochs, and the
  M0 fit recipe. Draw one synthetic crop for each real crop draw and preserve the M6 real draw count.
  Report additional optimizer steps, time, and memory.
- Decision rule: report absolute correct-crop counts and each corrected or regressed crop. A net
  gain of at least one correct real selection crop without an inference-limit regression is a
  useful exploratory annotation-assistance signal. Do not require a one-percentage-point gain.
- M10: if M9 meets that rule, compare M9 and M6 with the two additional seeds. Otherwise compare M3
  and M6. Keep M10 within its existing four-fit maximum.

This experiment can measure whether the one fixed synthetic treatment helps the current real
selection cases. It cannot establish independent-group generalization, fill absent reviewed-class
support, or qualify a model for promotion. Keep the final test sealed until M13.
