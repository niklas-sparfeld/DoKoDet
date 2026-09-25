# Calibration pose-seed refinement from virtual-card fitting

## Plan status

- **Summary:** Use the strongest ideas from virtual-card fitting to improve the initial state of
  automatic table-plane calibration without replacing its recording-global objective.
- **Status:** Closed
- **Depends on:** Completed 0072 pose-based visible-card review, completed 0075 robust automatic
  table-plane calibration, completed 0078 automatic calibration without a size reference, completed
  0079 review-first calibration gates, and the current occlusion-aware virtual-card fitter in
  `card_plane_initialization.py`
- **Builds on:** `fit_table_plane`, its bounded multistart boundary solver, and the current
  `fixed-card-pose-grid-search/v1` pose fitter
- **Outcome:** Calibration can use a better bounded pose seed when it helps, while calibration
  remains controlled by one shared homography, robust boundary residuals, and held-out evidence.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — add and measure the virtual-card-informed calibration initialization path.

## Closure

- **Closure reason:** Complete
- **Closure note:** The shared geometry solver now evaluates a bounded virtual-card pose seed when
  the finite preliminary metric seed is weak. It keeps the existing global robust boundary
  objective, calibration gates, projected peer-boundary exclusion, and anchor-refinement caller.
  Geometry outputs use `card-plane-geometry/v4`; stored `v3` calibration and fit-candidate bytes
  remain readable.

### M0 evidence

- The new seed uses a bounded center and angle search, symmetric edge distance with clipped Huber
  loss, and a quarter-turn initialization hypothesis. The final optimizer and publication gates
  still use the shared robust boundary objective. It does not consume stacking order, an occluder
  mask, or proposed card scenes.
- Frozen comparison before → after: 24/24 local cases published in both runs; 10/10 synthetic
  cases were repeatable; mean local runtime was 5,068 ms → 5,448 ms and maximum runtime was
  15,905 ms → 19,346 ms. Candidate rejection counts and publication decisions stayed unchanged.
  One diagnostic robust-fit index changed on a local case, but it did not change publication or
  the rejection-reason totals.
- Known noisy complete-card fixture before → after: median boundary error 0.436111 px and P90
  error 0.568763 px in both runs; quality passed in both runs. The additional seed was selected
  in one difficult frozen case and matched or lost to the existing seed in the other activations.
- Repeated noisy-fit calls produced the same calibration digest. The focused automatic-calibration,
  shared-geometry, anchor-refinement, initialization, and proposed-scene checks passed: 71 tests.

## Purpose

The current calibration solver jointly estimates one recording-scoped table-plane homography and
one temporary card pose per selected observation. It already uses spatial multistart and a robust
boundary objective. The recent virtual-card work added useful ideas for difficult initial poses:

- bounded local pose search;
- symmetric visible-edge distance with a clipped robust tolerance;
- explicit alternate orientation hypotheses; and
- a boundary-loss threshold before an occlusion refit is attempted.

These ideas must be considered for calibration. The final virtual-card score must not become the
calibration objective, and a better annotation pose must not make an occluded or clipped card valid
calibration evidence.

## Fixed design

1. Keep the calibration objective global. One shared image-to-table homography must explain the
   selected observations. Keep the existing fixed card dimensions, robust symmetric boundary
   residual, outlier handling, held-out validation, deterministic tie breaks, and publication
   gates.
2. Add a bounded pose-seed path. Use the current finite preliminary calibration state, when
   available, to produce improved per-observation pose seeds with the applicable virtual-card
   fitting ideas. Feed those seeds into the existing joint homography-and-pose optimization, then
   compare the result with the existing seeds using the same calibration objective.
3. Do not use frame-local card stacking order, an accumulated occluder mask, or a downstream
   proposed card scene as automatic calibration input. Keep the current projected peer-boundary
   exclusion for materially occluded candidates. Do not salvage a partial card solely because an
   occlusion-aware pose can fit it.
4. Treat alternate orientation hypotheses as initialization candidates only. Use them for trusted
   calibration observations where they improve the shared objective. Do not weaken frame-boundary,
   complete-card, or structural validity rules.
5. Keep anchor refinement on the shared geometry solver and preserve its pinned-anchor and
   conflict semantics. If the shared solver contract changes, update automatic calibration and
   refinement together.
6. Version the geometry algorithm or recipe when generated calibration bytes can change. Preserve
   readability of existing stored revisions and bind new outputs to the new implementation and
   recipe digests.

## M0 — Add and measure the pose-seeded calibration path

- Inspect the current `_fit_seed`, `_optimize_boundary_fit`, `_fit_candidate`, and the history of
  commits `83cda3a83`, `77abaf5c7`, `d47fd21ca`, `45645830e`, and `1486f5169` before editing.
- Implement the smallest shared geometry change that supports an additional virtual-card-informed
  initial state. Keep the final calibration selection and validation on the existing global
  boundary objective. Do not copy the frame-local stack-order refit into calibration.
- Add focused regression tests for clean complete cards, noisy boundaries, alternate orientation,
  piles or occluded candidates, frame-edge candidates, and a case where the additional seed either
  improves or matches the existing fit. Assert that an occluded candidate is excluded rather than
  used to distort the shared mapping.
- Run the frozen calibration comparison and report, before and after:
  - held-out boundary error and regional error;
  - fit quality and publication decisions;
  - rejected-candidate reasons;
  - deterministic repeat digests; and
  - local runtime.
- Run focused automatic-calibration, shared-geometry, anchor-refinement, initialization, and
  proposed-scene tests. Record unrelated pre-existing failures separately.

### M0 acceptance criteria

- The additional seed path improves a documented difficult case or matches the current result
  without a regression on clean complete-card cases.
- The calibration objective remains the robust shared boundary objective. The final virtual-card
  score is not used as a publication gate or as a replacement for held-out calibration evidence.
- Occluded, clipped, disconnected, and structurally invalid observations remain excluded from the
  calibration fit.
- Automatic calibration and calibration anchor refinement remain deterministic and preserve their
  existing lineage and conflict behavior.
- The frozen comparison shows no unexplained publication regression, digest instability, or
  material runtime regression. The report records cases where the new seed does not help.

## Non-goals

- Do not redesign the final virtual-card fitter.
- Do not use a proposed or reviewed card scene to calibrate the table plane.
- Do not fit one homography per frame or let per-card pose flexibility hide a bad shared mapping.
- Do not add a lens model, absolute-size correction, or new calibration UI.
