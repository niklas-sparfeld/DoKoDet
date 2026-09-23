# Robust automatic table-plane calibration

- **Status:** In Progress
- **Depends on:** Completed 0072 pose-based visible-card review and 0073 proposed card scenes and calibration refinement.
- **Outcome:** One complete, stable-camera RF-DETR result produces an automatic table-plane calibration whose projected full cards fit reliable card boundaries across the view. Poor polygons have bounded or zero influence. A fit that misses publication gates remains an inspectable calibration fit candidate with measured error. The same fit serves automatic calibration and operator anchor refinement.

## Current milestone status

- **M0 — Complete.** Froze 24 local RF-DETR revisions, ten known-geometry synthetic cases, a read-only evaluator, and measured acceptance gates. The [baseline report](../../reports/0075-M0_Calibration_Baseline.md) records current results. Real-data outline acceptance remains pending because the frozen frames have no independent full-card outlines.
- **M1 — Complete.** Added source-frame evidence, uniform boundary samples, image-space quality measures, quality-first selection, and caps for repeated evidence. All ten synthetic cases repeat exactly. The [M1 report](../../reports/0075-M1_Candidate_Evidence.md) records the selection results. Real-data outline acceptance remains pending.
- **M2 — Not started.**
- **M3 — Not started.**
- **M4 — Not started.**
- **M5 — Not started.**

## Problem and current behavior

`card_plane_calibration.py` selects isolated, high-confidence predictions, fits a quadrilateral to
each mask, and calls `fit_table_plane` in `card_plane_geometry.py`. That fit starts from one card's
homography. It rectifies the other quadrilaterals, rejects high rectangle-shape residuals, and sets
card size from the median transformed short side. It does not fit the projected card boundary to
the source polygon. A complete but small detector mask can therefore reduce the common card size.
The current held-out gate checks a fitted quadrilateral with a generous corner-distance tolerance;
it does not measure systematic card-size error. `card_plane_calibration_refinement.py` calls the
same geometry fit, so changing only automatic calibration would leave two fit behaviors.
Many real recordings currently fail calibration. The processor discards the calculated transform
when a fit or validation gate fails, and proposed-scene creation then returns no card overlays.
This makes those failures hard to inspect.

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
   geometry, held-out fit, and absence of a systematic size bias. Keep the best finite, nondegenerate
   transform as a calibration fit candidate when a quality gate fails. Never silently publish a merely
   plausible transform.

## Best-effort result and diagnostics

Separate **fit availability** from **publication quality**. The solver should return its best valid
calibration fit candidate even when too few cards, poor diversity, high residual, size bias, or camera movement
prevents publication. Do not stop candidate generation at a minimum-count or diversity gate if a
valid exploratory fit can still be computed. Rank deterministic fit attempts by the same robust
objective and record the selected attempt and convergence reason. A result with no usable geometry,
inconsistent source coordinates, or no finite invertible transform has no calibration fit candidate; report the
specific reason and evidence counts.

The calibration fit candidate is a run-scoped diagnostic artifact with its transform, card size, source revision,
recipe, digest, and fit lineage. It is **not** a published table-plane calibration and cannot enter
the maintained reference or dataset path by accident. A failed run keeps its calibration fit candidate and failed
gates. Proposed-scene processing exposes read-only candidate card outlines on representative source
frames and links them to the contributing predictions. The operator can inspect these overlays and
the worst-fit frames even when ordinary proposal creation fails.

Report measured error rather than a naked confidence number: median, 90th-percentile, and worst
held-out symmetric boundary distance in source pixels; the same distances divided by local projected
card short-side length; signed size/area bias; inlier and rejected counts; spatial coverage; and
regional residuals. Show `unavailable` when there are too few independent held-out cards. A bounded
quality band may summarize these measurements, but it must state its rule and must not be presented
as a calibrated probability. Every failed gate and every discarded observation remains visible.

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
  partial cards, weak masks, current calibration failures, and any observed size-underestimate cases.
  Add synthetic known-homography cases with controlled polygon shrink, noise, outliers, and clipping.
- Store a reproducible local evaluation manifest with a small set of independently checked full-card
  outlines and a read-only comparison command. Measure current projected-card boundary error,
  signed extent/area bias, held-out error by image region, candidate yield, runtime, failure rate,
  and how many failed runs still have an inspectable calibration fit candidate. Use independent frames or card
  groups for scoring; do not score only the observations used for fitting. If the source frames for
  independent outlines are absent, record that limit and keep the real-data acceptance gate pending
  until they are available.
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
  size, outlier rejection, orientation, deterministic bytes, best valid attempts after quality-gate
  failure, and honest no-candidate cases.

**Done when:** Both automatic calibration and anchor refinement use one tested fit, and the M0
synthetic gates pass.

### M3 — Validate, score, and retain the best calibration fit candidate

- Replace corner-only held-out alignment with independent boundary and size-bias validation. Report
  quality weight, residual, and fit decision for each observation, plus regional aggregate metrics.
- Version the processor recipe and run contract. Retain a calibration fit candidate on quality-gate
  failure, with all failed gates, measured distances, and source lineage. Keep immutable old
  revisions readable while new runs produce new digests. Publish only candidates that pass the
  gates. Confirm that scene initialization and reviewed-data lineage still use the exact published
  calibration.
- Add regression tests for low candidate count, poor diversity, inconsistent geometry, held-out
  failure, and moving-camera evidence. Assert that each mathematically valid case returns a
  calibration fit candidate and distances, while structurally invalid cases explain why none is available.

**Done when:** A failed quality gate preserves an inspectable calibration fit candidate and honest metrics without
publishing it, and the M0 synthetic gates pass.

### M4 — Show failed fits and verify full recordings

- Make failed calibration runs and their calibration fit candidates reachable from the recording review
  flow. Show read-only candidate outlines beside detector polygons, the numerical distance and
  size-bias measures, candidate yield, failed gates, and links to worst-fit frames. Clearly label
  the candidate as diagnostic. Keep it out of maintained-reference and dataset actions.
- Run the M0 real-result comparison and relevant operations, backend, and UI checks. Record how many
  previously failing recordings now publish and how many return a calibration fit candidate. Fix
  measured regressions before accepting the milestone.

**Done when:** The full recording path passes the frozen M0 gates locally, and a failed fit can be
inspected in the review flow without changing published calibration or reviewed data.

### M5 — Decide whether view-edge distortion needs a separate model

- Inspect held-out regional residuals from M4. Record whether the edge error is coherent across
  clean cards and recordings, and whether a homography can meet the M0 view-edge gate. Close this
  milestone with evidence if it can.
- If it cannot, report the distortion diagnostic with the calibration fit candidate and create a separate
  epic for a bounded lens-correction model. That epic must version the mapping contract and cover
  geometry, pose initialization, scene editor, anchor refinement, derivation, and reflow. It must
  compare the new model against the homography on held-out groups.

**Done when:** View-edge behavior is measured and the homography either passes or has an explicit
distortion diagnostic and a specified follow-up epic.

## Verification and boundaries

Use the existing `mise` toolchain and focused automated checks. Measure against the frozen M0
manifest after each fit change. Keep runtime suitable for local recording processing. Do not use
reviewed card scenes as automatic fit input. Do not infer hidden card corners from a pile, fit one
homography per frame, or silently change the geometry of stored calibration revisions.
