# Review-first calibration gates

## Plan status

- **Summary:** Publish usable virtual card proposals for human annotation when the fit is valid.
- **Status:** Closed
- **Depends on:** Completed 0075 calibration and 0078 automatic size estimate
- **Outcome:** Spatial coverage and held-out boundary checks guide review. A modestly lower boundary straightness cutoff admits more candidate masks. The review view paints fitted rounded outlines.
- **Closure reason:** Complete
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — make spatial coverage and held-out boundary checks advisory, lower minimum boundary straightness from 0.65 to 0.55, fix rounded outline display, and compare frozen results in the [M0 report](../../reports/0079-M0_Review_First_Calibration_Gates.md).

## Purpose

Virtual cards are inputs to human annotation. A distant camera can concentrate all cards in a small image region. A flawed detector mask can also fail a held-out boundary check. Neither condition alone makes the fitted card plane unusable for review.

## Publication rule

Keep candidate count, temporal and table-position diversity, orientation diversity, held-out population, and fit quality as blocking checks. Record spatial coverage and held-out boundary results as review warnings. Preserve their measured values and per-card diagnostics. Reject a candidate mask with boundary straightness below 0.55.
