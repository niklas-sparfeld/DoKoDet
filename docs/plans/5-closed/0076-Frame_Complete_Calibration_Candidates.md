# Frame-complete automatic calibration candidates

## Plan status

- **Summary:** Keep calibration cards inside the source frame, reject incomplete cards, and make
  each selection decision visible for review.
- **Status:** Closed
- **Depends on:** Completed 0075 robust automatic table-plane calibration
- **Outcome:** Automatic calibration removes candidates whose fitted full-card outline crosses the
  source-frame boundary or has strong evidence of occlusion. Failed-run review shows fit,
  held-out, and discarded cards with metrics.
- **Closure reason:** Complete
- **Closure note:** All three milestones are complete. Frozen real results still need independent
  full-card outlines before publication, and the held-out and coverage gates still fail.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — reject candidates whose projected full-card outline leaves the source frame,
  refit without them, and record the before-and-after measurements in the
  [M0 report](../../reports/0076-M0_Frame_Complete_Calibration_Candidates.md).
- **M1:** Complete — show fit, held-out, and discarded candidates as distinct frame overlays with
  per-card metrics and filters.
- **M2:** Complete — reject candidates whose projected edge is hidden by another detected card
  and masks with a deep inward notch. Record the measurements in the
  [M2 report](../../reports/0076-M2_Occluded_Calibration_Candidates.md).

## 1. Purpose

Epic 0075 rejects a detector mask when the mask touches the image edge. A mask can stay inside the
image while the fitted full-card outline extends past the edge. Such a candidate can still enter the
calibration fit.

After an initial fit, project every selected observation as a full card. Reject an observation when
any projected corner is outside its source frame. Repeat the fit and this check until every selected
full-card outline stays inside its frame. Keep the rejection in the candidate receipt and exclude
the observation from fit and held-out metrics.

M0 handles frame containment. M1 makes the selection evidence visible. M2 covers occluded card
boundaries.

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

## 3. M1 — Show candidate decisions in failed-run review

- Mark fit, held-out, and discarded cards with distinct colors and labels.
- Show each card's boundary distances and selection evidence on the frame.
- Let the operator filter the three roles. Use detected geometry when a discarded card has no
  projected outline.

**Done when:** A failed-run review can distinguish all three roles and inspect each card's metrics
without treating a rejected projected outline as a selected card.

## 4. M2 — Stabilize complete-card selection under occlusion

Improve the `is this card fully visible` decision for cards covered by other cards. Measure it on
retained examples before choosing a detection change.
