# Automatic calibration without a size reference

## Plan status

- **Summary:** Publish an automatic table-plane calibration from fitted card evidence when its
  selection, coverage, fit, and held-out gates pass.
- **Status:** Closed
- **Depends on:** Completed 0075 calibration, 0076 candidate selection, and 0077 rounded outline
- **Outcome:** Independent full-card outlines are optional evaluation data. Their absence or bias
  does not block an otherwise valid automatic calibration or proposed card scene.
- **Closure reason:** Complete
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — remove the independent size-reference publication gate, keep optional
  comparison metrics, update failed-run review text, and measure frozen results in the
  [M0 report](../../reports/0078-M0_Automatic_Calibration_Without_Size_Reference.md).

## 1. Purpose

The table coordinate system uses one fitted card short side as its unit. An automatic run estimates
the source-image scale of that unit from selected card boundaries. It has no confirmed full-card
outline to compare against during normal processing. Requiring such an outline made a valid
automatic fit impossible to publish even when every other gate passed.

## 2. M0 — Remove the reference gate

- Keep candidate count, diversity, spatial coverage, fit quality, and held-out boundary gates.
- Remove independent size-reference availability and bias from the publication decision.
- Retain optional independent-outline comparison metrics when reference data is supplied.
- Let proposed card scenes use a published automatic calibration without reference outlines.
- Show the optional comparison as a diagnostic, not a failed gate.
- Compare frozen real and synthetic cases, including the known uniform-shrink case.

**Done when:** A detector-only fit publishes if its remaining gates pass, an independent comparison
can report bias without blocking publication, and frozen results identify which runs change status.
