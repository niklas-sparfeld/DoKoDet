# Core ML export compatibility for RF-DETR and DINOv3

## Plan status

- **Summary:** Export the exact frozen RF-DETR and DINOv3 models to Core ML, or record a
  bounded compatibility blocker for each model.
- **Status:** In Progress
- **Depends on:** Epic 0103 M0–M3 complete. The exact 0092 RF-DETR and 0088 DINOv3 bundles are
  available in the local runtime paths recorded by the 0103 reports.
- **Outcome:** Each model has either a Core ML package that passes the frozen 0103 Python output
  comparisons or a reproducible, bounded export blocker. Packages stay outside Git. Device
  measurements are outside this epic.

## Scope and constraints

Use the exact artifacts and fixed inputs from [Epic 0103](../5-closed/0103-iPhone_Model_Feasibility.md).
The current failure evidence is in the [RF-DETR M1 report](../../reports/0103-M1_RF-DETR_Core_ML_Export.md)
and the [DINOv3 M2 report](../../reports/0103-M2_DINOv3_Core_ML_Export.md). The current exporter
attempts are in `scripts/0103_m1_export_rfdetr.py` and `scripts/0103_m2_export_dinov3.py`.

Do not retrain, replace, or modify the frozen weights. Do not access sealed tests, run a sealed evaluator, change model selection, or change runtime defaults. Record every converter and dependency version. Keep generated packages outside Git. Do not claim model quality from export parity.

Limit compatibility work to one selected route for each model. A route can use a supported converter path or a narrow graph rewrite. The route must preserve the exact model outputs. Do not run an open-ended converter-version sweep. If no safe route is available, record the blocker and stop that model's attempt.

## M0 — Select bounded compatibility routes — Complete

The [M0 route report](../../reports/0104-M0_Core_ML_Compatibility_Routes.md) records the
reproduced converter failure, selected routes, version pins, and stop conditions.

- Reproduce or inspect the recorded integer-conversion failures at the RF-DETR encoder node and
  DINOv3 attention node. Keep the exact checkpoint and bundle digests fixed.
- Reduce each failure to the smallest useful graph or operator example. Identify whether one
  supported converter path or a narrow semantics-preserving graph rewrite can address it.
- Select and pin at most one route for each model. Record the versions, changed graph operations,
  expected outputs, and a stop condition before either export attempt.
- If no safe route exists for a model, record the evidence. Do not change its weights to make
  conversion pass.

## M1 — Export RF-DETR

- Use the selected M0 route with the exact 0092 M4 checkpoint and bundle digest.
- Export the fixed `[1,3,432,432]` input and the frozen boxes, class logits, and mask logits.
- On all six frozen M0 frames, compare input preprocessing, detections, masks, scores, normalized
  boxes, and the 0.5 confidence decisions against the M0 Python references. Report unmatched
  detections and all differences beyond the frozen tolerances.
- Add focused checks for any graph rewrite. A bounded conversion failure may complete M1 only when
  the exact failure and attempted route are reproducible.

## M2 — Export DINOv3

- Use the selected M0 route with the exact 0088 M6 encoder, head, configuration, target map, and
  calibration.
- Export the fixed `[1,3,224,224]` input and 25 logits. Preserve the existing crop transform and
  feature layout.
- On both frozen M0 crops, compare all 25 logits, calibrated scores, ranks, and the `FACE_DOWN`
  decision. Report threshold changes and all differences beyond the frozen tolerances.
- Add focused checks for any graph rewrite. A bounded conversion failure may complete M2 only when
  the exact failure and attempted route are reproducible.

## Handoff

This epic does not run models on an iPhone. Report the package path and digest, or the blocker, for
each model. A later device-measurement plan can use only packages that pass the frozen Python
comparisons. CardEventNet's existing iPhone support is recorded in
[Epic 0002](../5-closed/0002-iOS_CardEventNet_PoC.md).
