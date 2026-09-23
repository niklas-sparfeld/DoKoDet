# Rounded physical card outlines

## Plan status

- **Summary:** Use a measured rounded card edge for calibration and derived visible regions.
- **Status:** Closed
- **Depends on:** Completed 0075 table-plane calibration and completed 0076 candidate selection
- **Outcome:** The fit, held-out metrics, review overlay, and card-region derivation use one
  rounded full-card outline. Four virtual corner intersections still define each pose.
- **Closure reason:** Complete
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — measure the ASS Altenburger deck corner radius, apply a shared outline to
  calibration and card-region masks, and compare frozen metrics in the
  [M0 report](../../reports/0077-M0_Rounded_Physical_Card_Outlines.md).

## 1. Purpose

A rectangle places its virtual corners outside the rounded edge of a physical card. Calibration
previously measured the detector contour against those sharp corners. Derived visible regions also
filled those corner pixels. Use one rounded outline while keeping the rectangular pose and
homography controls.

## 2. M0 — Use one rounded full-card outline

- Measure the radius on the local deck images and express it relative to the short side.
- Keep four virtual corner intersections for pose, homography, and card dimensions.
- Compare sampled rounded edges with observed card boundaries during fit and held-out checks.
- Use the same projected outline for frame and peer occlusion checks, review overlays, and derived
  visible-region masks.
- Record the ratio and bump geometry, calibration, and derivation versions.
- Compare all frozen local and synthetic calibration results.

**Done when:** Geometry and crop regression cases pass, the frozen comparison records quality and
runtime changes, and the new outline is reproducible from the shared geometry contract.
