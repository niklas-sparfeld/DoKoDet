# Robust automatic table-plane calibration

- **Status:** Ready
- **Depends on:** Completed 0072 pose-based visible-card review and 0073 proposed card scenes and calibration refinement.
- **Outcome:** One complete, stable-camera RF-DETR result produces an automatic table-plane calibration whose projected full cards fit reliable card boundaries across the view. Poor polygons have bounded or zero influence. The same fit serves automatic calibration and operator anchor refinement.

## Problem and current behavior

`card_plane_calibration.py` selects isolated, high-confidence predictions, fits a quadrilateral to
each mask, and calls `fit_table_plane` in `card_plane_geometry.py`. That fit starts from one card's
homography. It rectifies the other quadrilaterals, rejects high rectangle-shape residuals, and sets
card size from the median transformed short side. It does not fit the projected card boundary to
the source polygon. A complete but small detector mask can therefore reduce the common card size.
The current held-out gate checks a fitted quadrilateral with a generous corner-distance tolerance;
it does not measure systematic card-size error. `card_plane_calibration_refinement.py` calls the
same geometry fit, so changing only automatic calibration would leave two fit behaviors.

Use the original detector polygons or masks as uncertain evidence. Do not treat them as reviewed
geometry. Preserve one recording-scoped calibration, immutable revisions, candidate receipts, and
the existing scene/review lineage. No operator selection of calibration frames is required.

## Fit design

1. Read the complete selected local result, independent of RF-DETR variant. Convert each prediction
   to a source-frame mask and ordered boundary samples. Validate dimensions, source transform,
   finite geometry, confidence, connected components, clipping, and overlap. A card near the edge
   of the view remains eligible if its full boundary is visible. A card cut off by the frame does
   not constrain the fit. Record each rejection reason.
2. Measure candidate quality before calibration: mask-to-quad agreement, convexity, boundary
   straightness, corner support, component dominance, and separation from other cards. These are
   image-space measurements; perspective trapezoids remain valid. Discard incomplete, crowded, or
   unstable boundaries. Give the cleanest complete cards most weight, but cap influence per frame,
   temporal interval, and image region. Detector confidence is one signal, not the weight alone.
3. Fit one shared image-to-table homography and one fixed card shape, with a free center and rotation
   for each card. Fix the table short side to `1` and the long side to the canonical `1.5` to remove
   scale ambiguity. Use several deterministic seeds from spatially separated clean cards. Optimize
   shared homography parameters and card poses together; do not average per-card homographies or
   update the shared transform once per card in input order.
4. Score each candidate in source pixels against its projected full-card outline. Use a symmetric,
   length-normalized boundary distance: polygon boundary to projected edges and projected edges to
   polygon boundary. Measure signed extent and area errors to expose size bias. Sample edges
   uniformly rather than letting dense detector vertices dominate. Use a robust loss and iterative
   reweighting; reject observations with a large residual after a provisional fit. Set deterministic
   iteration, convergence, and tie-break rules. Reject degenerate or mirrored transforms.
5. Hold out independent temporal and spatial groups. Report boundary error, projected-to-observed
   width/height and area ratios, rejected-candidate counts, and regional errors (center versus view
   edges). Gate publication on enough complete cards, spatial and orientation diversity, stable
   geometry, held-out fit, and absence of a systematic size bias. A failed gate returns an actionable
   diagnostic. Never silently publish a merely plausible transform.

A homography cannot correct radial lens distortion. First measure regional residuals on held-out
cards. If edge residuals remain coherent after the shared fit, add a small, bounded lens-correction
model in a later milestone and compare it with the homography on held-out data. Keep the simpler
homography when the extra model does not improve held-out fit. A lens correction changes the mapping
contract and every projection consumer; it must never be hidden inside a homography matrix.

Uniformly shrunken rectangles are indistinguishable from smaller cards if no complete-card evidence
exists. The solver must rely on clean complete cards for size, and fail when that evidence is too
weak. It must not claim to recover hidden corners from uniformly biased polygons.

## Milestones

### M0 — Freeze an evaluation set and acceptance gates

- Select complete local RF-DETR results from available variants and recordings. Keep exact source
  revision IDs. Include clean isolated cards, repeated stationary cards, edge-of-view cards, piles,
  partial cards, weak masks, and any observed size-underestimate cases. Add synthetic known-
  homography cases with controlled polygon shrink, noise, outliers, and clipping.
- Store a reproducible local evaluation manifest with a small set of independently checked full-card
  outlines and a read-only comparison command. Measure current
  projected-card boundary error, signed extent/area bias, held-out error by image region, candidate
  yield, runtime, and failure rate. Use independent frames or card groups for scoring; do not score
  only the observations used for fitting. If the source frames for independent outlines are absent,
  record that limit and keep the real-data acceptance gate pending until they are available.
- Freeze numerical acceptance thresholds from the measured cases in the evaluation manifest. At
  minimum, require improvement on the recorded size-underestimate cases, no regression on clean
  complete cards, rejection of pile/partial outliers, exact repeatability, and a bounded local run
  time. Do not use a single aggregate score to hide a failure at the view edge.

**Done when:** The baseline report names its revisions and cases, can be reproduced locally, and
states the pass/fail gates for later milestones.

### M1 — Extract and rank complete-card evidence

- Extend the calibration observation with boundary samples and quality measures. Keep every
  candidate's source identity and reason for acceptance or rejection. Accept RF-DETR variants
  through their common local-result geometry rather than provider-specific assumptions.
- Reject disconnected, clipped, crowded, and weakly supported full-card geometry. Deduplicate by
  time and image region after quality scoring; cap repeated observations without losing spatial
  coverage. Keep fully visible cards near image edges.
- Add focused tests for trapezoids, shrink, partial masks, piles, duplicate cards, and edge cards.

**Done when:** Candidate selection is deterministic, explainable, and passes the M0 evidence cases.

### M2 — Replace the shared table-plane fit

- Implement the joint robust boundary fit in `card_plane_geometry.py` behind a new algorithm
  version. Use bounded multistart initialization, fixed iteration and convergence limits, and
  finite-transform checks. Keep intermediate fitting helpers internal.
- Pass observation weights and boundary data from automatic calibration. Update anchor refinement
  to call the same shared solver with its existing candidate/accepted/adjusted/pinned policy;
  preserve pinned-anchor conflict diagnostics. Remove the current repeated-quad approximation.
- Add synthetic tests with known homographies and biased/noisy masks. Verify recovered projection,
  size, outlier rejection, orientation, deterministic bytes, and solver failure paths.

**Done when:** Both automatic calibration and anchor refinement use one tested fit, and the M0
synthetic gates pass.

### M3 — Validate and publish the new automatic calibration

- Replace corner-only held-out alignment with independent boundary and size-bias validation. Report
  quality weight, residual, and fit decision for each candidate, plus regional aggregate metrics.
- Version the processor recipe and diagnostics; keep immutable old revisions readable while new
  runs produce new digests. Update proposed-scene creation and failure guidance only where the new
  diagnostics require it. Confirm that scene initialization and reviewed-data lineage still use the
  exact published calibration.
- Run the M0 real-result comparison and relevant operations, backend, and UI checks. Fix measured
  regressions before accepting the milestone.

**Done when:** The full recording path passes the frozen M0 gates locally, and failures remain
explicit and actionable.

### M4 — Decide whether view-edge distortion needs a separate model

- Inspect held-out regional residuals from M3. Record whether the edge error is coherent across
  clean cards and recordings, and whether a homography can meet the M0 view-edge gate. Close this
  milestone with evidence if it can.
- If it cannot, specify a bounded lens-correction model and versioned mapping contract before
  implementation. Require full projection support in geometry, pose initialization, scene editor,
  anchor refinement, derivation, and reflow. Fit lens terms only with enough edge evidence and
  compare against the simpler homography on held-out groups. Publish the more complex mapping only
  if it passes all gates; otherwise fail with a distortion diagnostic.

**Done when:** View-edge behavior is measured and either the homography passes or a separately
versioned mapping is implemented and validated end to end.

## Verification and boundaries

Use the existing `mise` toolchain and focused automated checks. Measure against the frozen M0
manifest after each fit change. Keep runtime suitable for local recording processing. Do not use
reviewed card scenes as automatic fit input. Do not infer hidden card corners from a pile, fit one
homography per frame, or silently change the geometry of stored calibration revisions.
