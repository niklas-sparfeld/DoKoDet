# Frame-complete automatic calibration candidates

## Plan status

- **Summary:** Keep cards whose projected full-card outline stays inside the source frame in the
  automatic calibration population.
- **Status:** In Progress
- **Depends on:** Completed 0075 robust automatic table-plane calibration
- **Outcome:** Automatic calibration removes candidates whose fitted full-card outline crosses the
  source-frame boundary, records the rejection, and measures the effect on retained results.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — reject candidates whose projected full-card outline leaves the source frame,
  refit without them, and record the before-and-after measurements in the
  [M0 report](../../reports/0076-M0_Frame_Complete_Calibration_Candidates.md).
- **M1:** Not started — improve selection of fully visible cards when other cards cover them. Start
  this milestone only after explicit user confirmation.

## 1. Purpose

Epic 0075 rejects a detector mask when the mask touches the image edge. A mask can stay inside the
image while the fitted full-card outline extends past the edge. Such a candidate can still enter the
calibration fit.

After an initial fit, project every selected observation as a full card. Reject an observation when
any projected corner is outside its source frame. Repeat the fit and this check until every selected
full-card outline stays inside its frame. Keep the rejection in the candidate receipt and exclude
the observation from fit and held-out metrics.

This milestone handles frame containment. It does not change how the processor judges occluded
card boundaries. M1 covers that work after the user confirms it.

## 2. M0 — Filter outlines outside the source frame

- Use source-image boundary coordinates to check each projected full-card outline.
- Mark an out-of-frame observation as `frame_boundary`.
- Remove it from the fit and held-out population, then fit again.
- Update the processor recipe schema and keep deterministic run digests.
- Compare all frozen local and synthetic results with the 0075 baseline.

**Done when:** A regression case proves that an in-frame detector mask is rejected when its
projected full-card outline leaves the frame, the selected fit no longer contains that observation,
and the frozen comparison records changes in candidate selection, fit quality, coverage, and
runtime.

## 3. M1 — Stabilize complete-card selection under occlusion

Improve the `is this card fully visible` decision for cards covered by other cards. Measure it on
retained examples before choosing a detection change. This milestone requires explicit user
confirmation before work starts.
