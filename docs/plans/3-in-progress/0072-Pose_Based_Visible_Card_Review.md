# Pose-based visible-card review

## Plan status

- **Summary:** Automatically calibrate one table plane from high-confidence isolated-card detections
  across a recording, fit full-card poses and stacking order, and let the operator correct cards by
  moving them on a virtual table.
- **Status:** In Progress
- **Depends on:** 0048 pipeline data and execution, and 0049 recording pipeline review
- **Builds on:** The table-plane calibration in 0070, the reviewed local segmentation provider in
  0068, and the local cascade in 0071
- **Outcome:** The visible-card review tool automatically derives a recording-global calibration and
  initializes a reviewed card scene from local predictions. The operator adjusts card centers,
  rotations, count, and stacking order on a calibrated virtual table. The system derives exact
  source-frame visible regions from the reviewed scene.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — the shared card-plane geometry boundary and versioned calibration, candidate,
  pose, stacking-order, scene, fit-diagnostic, and derived-region contracts are frozen. 0070 now
  uses the shared homography, calibration, mask, polygon, component, and occlusion primitives.
- **M1:** Complete — automatically mine and validate a recording-global table calibration from
  isolated-card detections, with immutable local revision storage and read-only diagnostics.
- **M2:** Complete — initialize fixed-size card poses and deterministic frame-local stacking order
  from model predictions, with retained suggestion evidence and fit diagnostics.
- **M3:** Complete — the calibrated local result path now uses a synchronized source-frame and
  rectified virtual-table card-scene editor with ordered maintained-reference commands.
- **M4:** Complete — derive and validate deterministic reviewed visible regions from the reviewed
  card scene and gate downstream identity and dataset use on the validated view.
- **M5:** Not started — verify the complete local-prediction-to-reviewed-data loop.

## 1. Purpose

RF-DETR polygons are a useful clue but a poor human editing abstraction. Their points can be dense,
their boundaries can be rough, and overlapping cards can be divided incorrectly. A physical card
has much stronger structure: it is one fixed-size rectangle on the table plane, with a center,
rotation, and position in the frame's card stacking order.

This epic uses that structure. For one stable-camera recording, the system mines all
high-confidence isolated-card detections from the selected complete-recording local result. It fits
one robust recording-global table-plane calibration and one card size from that population. No
person selects calibration frames or edits calibration corners. The system then converts each
frame's model predictions into an initial reviewed card scene. The operator corrects that scene by
moving and rotating virtual cards, changing their order, and adding or removing cards. The system
projects the full cards back into the source frame and derives visible regions by applying frame
clipping and card-card occlusion.

The maintained visible-card reference remains the human authority. Generated model polygons remain
immutable suggestions. Card poses are the reviewed geometric authority; visible-region polygons
are deterministic derived output.

```text
high-confidence isolated-card detections across the recording
  -> recording-global table-plane calibration and card size
  -> local predicted polygons
  -> initial card poses and stacking order
  -> operator edits cards on the virtual table
  -> deterministic source-frame visible regions
  -> completed maintained visible-card reference
```

## 2. Fixed scope

This epic includes:

- one table-plane calibration for one stable-camera recording;
- automatic mining, temporal de-duplication, quadrilateral fitting, robust calibration, and
  validation over high-confidence isolated-card detections;
- reuse of the metric rectification mathematics developed in 0070 through a shared geometry
  library;
- deterministic pose and stacking-order initialization from local predicted polygons;
- a rectified virtual-table editor synchronized with the exact source frame;
- card move, rotate, reorder, add, remove, and restore-suggestion actions;
- deterministic projection, clipping, card-card occlusion, mask-to-polygon conversion, and derived
  box calculation;
- maintained-reference, source-lineage, downstream-impact, and dataset integration; and
- focused operator verification on distant and overlapping cards.

This epic does not include:

- another detector, segmentation model, prompt, threshold, or training comparison;
- changes to 0070 synthetic-data generation or 0071 cascade training;
- camera intrinsics, lens correction, camera tracking, or a general 3D reconstruction system;
- per-frame homography fitting or support for a moving camera inside one calibrated recording;
- manual calibration-frame selection or calibration-corner editing;
- inference of card identity, card side, a pile, a trick, or a card play from geometric order;
- automatic modeling of human hands or other non-card occluders;
- free-form polygon correction as the primary workflow; or
- a provider promotion or default-provider change.

The existing ignore-region and unusable-frame decisions remain available. Use them when a hand,
foreign object, severe blur, or another unsupported condition prevents a reliable card scene. This
epic does not turn those conditions into hidden-card geometry.

## 3. Recording-global table calibration

### 3.1 Automatic calibration population

Use the selected local generated result for the complete recording. Consider every predicted card,
then retain a calibration candidate only when it passes one frozen filter:

- confidence is at or above the calibration threshold;
- its mask has one dominant connected component;
- it stays clear of the source-frame boundary;
- its expanded box does not intersect another retained card prediction in the same frame;
- a convex four-edge fit explains the mask within the frozen residual and coverage limits; and
- the exact frame has the same dimensions and stable source transform as the recording.

These conditions select likely complete, non-occluded, isolated cards. They do not make the model
polygon reviewed evidence and do not make it a training target.

Long-lived cards can produce many near-identical detections. Partition candidates by fixed temporal,
table-position, scale, and orientation bins. Keep the highest-confidence candidate in each bin so
one card or one part of the table cannot dominate the fit. Freeze the confidence threshold, margins,
quadrilateral-fit rule, bin sizes, and tie-breaks in M0.

Require enough retained candidates and enough position and orientation diversity to identify the
plane. Generalize the metric table-plane fitting code from 0070 into one shared, tested geometry
library. Fit one shared image-to-table homography directly from all candidate rectangle constraints
with robust outlier rejection. Do not calculate one homography per card and average matrix elements.
The shared robust fit is the defined recording-wide average because homography matrices have an
arbitrary scale.

The fit produces the inverse transform, a normalized card short side, and a robust median card long
side. Physical units and a unique camera model are not required. The calibration records the source
generated revision, every candidate receipt, temporal and geometry bins, accepted and rejected
candidates, residuals, algorithm version, recipe, and digest.

### 3.2 Validity

Split the de-duplicated population deterministically by temporal and spatial bins. Fit on one part
and validate against the held-out candidates. Publish the calibration only after it passes frozen
candidate-count, residual, aspect-ratio, orientation-diversity, spatial-coverage, and held-out
alignment gates. The projected standard card must align with held-out polygons within a declared
source-pixel tolerance. Model confidence alone cannot pass the calibration.

A recording with too few isolated cards, camera movement, zoom, stabilization drift, changed
resolution, or a changed table setup fails the recording-global calibration gate. The review tool
shows the failed gate and candidate diagnostics. It does not ask for manual calibration input,
silently fit per-frame transforms, or save incorrect reviewed geometry.

Store a passing calibration as an immutable processor-derived, recording-scoped revision. A
maintained card scene references its exact calibration revision and digest. Re-running calibration
from a different generated revision or recipe creates a new revision and marks dependent draft
scenes and downstream identity work as affected. It does not rewrite completed history.

## 4. Prediction-to-scene initialization

### 4.1 Card pose fitting

For each predicted card polygon:

1. Map its source-frame points into the calibrated table plane.
2. Calculate a robust initial center and orientation from the polygon's support and boundary.
3. Fit the fixed calibrated card rectangle around that evidence. Center and rotation can vary; card
   dimensions cannot vary per instance.
4. Project the rectangle back into the source frame and calculate fit diagnostics against the
   original prediction.
5. Retain the original model polygon, confidence, provider, and bundle only as immutable suggestion
   diagnostics.

Use one fixed, bounded fitting recipe. Freeze its search range, objective, tie-breaks, iteration
limit, and failure thresholds in M0. The fit is an editor prefill, not reviewed truth. A poor or
partial polygon can produce a low-confidence pose, and the operator can still move, rotate, or
remove that card. A missed card can be added without a prediction.

### 4.2 Stacking-order initialization

Build overlap relationships from the projected full-card rectangles. For each overlapping pair,
score which prediction owns the overlap evidence. Convert the pairwise scores into one deterministic
frame-local card stacking order. Break equal scores by stable candidate ID. Report weak edges,
contradictions, and cycles as uncertain initialization instead of hiding them.

The order exists only to calculate card-card occlusion in this source frame. It does not assert a
gameplay pile or the temporal order in which cards were played. Non-overlapping cards can keep a
stable arbitrary relative order because their order does not change derived pixels.

After the initial poses and order exist, render the implied visible masks and show their disagreement
with the model polygons. Do not automatically alter card count or accept the initialized scene.

## 5. Reviewed card-scene contract

One reviewed card scene contains:

- the exact source-frame identity;
- the selected table-plane calibration revision and digest;
- one stable card ID for each physical card represented in the frame;
- each card's table-plane center and rotation;
- one frame-local card stacking order;
- the source suggestion ID when the card originated from a prediction;
- the fixed derivation recipe version; and
- the derived visible-region digest.

Card dimensions come from the calibration and are not stored as editable per-card values. Changing
card size requires a new calibration revision.

The reviewed card scene is the geometry authority. The backend derives candidates from it in this
order:

1. construct the full fixed-size table rectangle for each pose;
2. project each rectangle into the exact source frame;
3. clip it to the source-frame boundary;
4. subtract the union of all higher cards in the reviewed stacking order;
5. extract every remaining connected mask component as one visible-region polygon;
6. calculate the derived box from the final visible region; and
7. produce the existing visible-card candidate view for identity crops, comparisons, and datasets.

The derivation uses the shared backend geometry implementation. The client can render a preview,
but it cannot author the final polygons. Persist the scene and the derived candidate view together
with a digest. On read and before dataset materialization, reject a stale or mismatched derived
view. This prevents poses and polygons from becoming two independent authorities.

A card that has no visible pixels after clipping and occlusion is not a visible-card target. Keep
its pose only in the draft while the operator resolves the count or order. A completed visible-card
reference cannot contain a fully hidden card because the source frame does not review it as visible.

## 6. Virtual-table review tool

The visible-card review workbench shows two synchronized views:

1. The exact source frame with model polygons, projected full-card outlines, and derived visible
   regions.
2. A rectified virtual table with fixed-size card rectangles that the operator can manipulate.

Selecting a card in either view selects it in both. The operator can:

- drag a card center on the virtual table;
- rotate it with a handle, keyboard controls, or a numeric angle field;
- nudge center and rotation at coarse and fine increments;
- bring it forward, send it backward, or place it at an exact position in the card stacking order;
- add a new standard-size card at the selected table location;
- remove a false or duplicate card;
- restore the original initialized pose or complete generated suggestion scene; and
- zoom, pan, and fit both views without changing stored table coordinates.

Every edit updates the projected outlines and derived card-card occlusion preview immediately. Keep
the model polygons visible as optional dim overlays so that the operator can compare the geometric
scene with the original suggestion. Make the reviewed derived regions visually distinct from both.

One completed gesture produces one autosaved scene command. Pointer movement does not publish
partial reference revisions. Keyboard and numeric edits use the same ordered command queue, retry,
conflict, and reload behavior as the existing maintained-reference editor. Navigation cannot discard
an unsaved gesture silently.

The editor does not expose polygon vertices for ordinary card-card correction. If the geometric
model cannot explain the source frame, the operator chooses an ignore region or unusable frame. The
tool must not let a free-form polygon hide a bad calibration or unsupported occluder inside a
completed pose-based scene.

## 7. Delivery milestones

### M0 — Freeze geometry and review contracts

- Define versioned contracts for table-plane calibration revisions, calibration candidates and
  receipts, card poses, card stacking order, reviewed card scenes, fit diagnostics, and
  derived-region receipts.
- Extract or generalize the 0070 table-plane fit, homography application, fixed-card projection,
  occlusion, raster-mask, component, and polygon functions into a shared geometry boundary.
- Freeze numeric precision, coordinate systems, corner order, angle convention, raster resolution,
  mask threshold, contour policy, digest inputs, and deterministic tie-breaks.
- Add fixtures for repeated detections of one card, sparse and well-distributed calibration
  populations, calibration outliers, separated cards, two- and three-card overlaps, disconnected
  visible components, frame clipping, total occlusion, contradictory prediction masks, and malformed
  transforms.

Acceptance:

- 0070 and the review path use the same table-plane and card-projection primitives;
- repeated calibration, pose projection, occlusion, and polygon extraction are byte-equivalent;
- table-to-image-to-table round trips meet the frozen tolerance;
- a derived view cannot validate against a different scene or calibration digest; and
- gameplay terms and physical-card identities do not enter the geometry contracts.

#### M0 implementation evidence — 2026-09-20

- Added the shared `card_plane_geometry` boundary for the 0070 table-plane fit, homography
  application, fixed-card projection, binary-mask raster and cleanup rules, connected components,
  polygon extraction, and front-to-back card-card occlusion.
- Added strict versioned contracts for calibration revisions, calibration candidate receipts, card
  poses, stacking order, pose-fit diagnostics, reviewed card scenes, and derived-region receipts.
  Digests bind derived regions to the exact scene and calibration.
- Updated the 0070 planar, recording, empty-table, and rendering paths to use the shared geometry
  primitives. No detector, provider, runtime default, or generated training artifact changed.
- Added focused tests for deterministic contract round trips, reciprocal transforms, fixed-card
  projection, disconnected visible components, digest mismatch rejection, and malformed transforms.
  The focused geometry and 0070 tests pass.

### M1 — Automatically calibrate one recording-global table plane

- Add a deterministic calibration processor and immutable revision store under the recording
  workspace.
- Mine, filter, fit quadrilaterals, and de-duplicate isolated-card candidates from the selected
  complete-recording local result.
- Fit the robust table plane and card size through the shared M0 library, then evaluate the held-out
  temporal and spatial bins.
- Show candidate yield, temporal and table coverage, accepted and rejected candidates, residuals,
  validation results, and projected standard-card overlays as read-only diagnostics.
- Reject insufficient evidence, changed resolution, or camera movement with an actionable automatic
  calibration failure.

Acceptance:

- an eligible selected result produces a calibration without human frame or corner input;
- repeated runs over the same generated revision produce identical candidates, transforms, size,
  diagnostics, and digest;
- held-out high-confidence isolated-card candidates meet the frozen source-pixel alignment gate;
- repeated observations of one long-lived card cannot satisfy the diversity gates by themselves;
- an insufficient or moving-camera recording cannot publish a global calibration; and
- a new calibration revision marks dependent draft and downstream work as affected without changing
  immutable history.

#### M1 implementation evidence — 2026-09-20

- Added the deterministic `card_plane_calibration` processor. It accepts one complete local result,
  filters confidence, boundary, connected-component, quadrilateral, overlap, and bin-duplicate
  candidates, and fits one shared table plane through the M0 geometry library.
- Added deterministic temporal/spatial holdout validation with candidate yield, coverage, fit,
  residual, gate, and failure diagnostics. Changed frame dimensions and source transforms fail with
  actionable automatic diagnostics. One long-lived card cannot pass the diversity gates by itself.
- Added `CalibrationRevisionStore`, which writes canonical immutable manifests below the recording
  workspace and rejects content changes at an existing revision path. No detector, provider, runtime
  default, or generated training artifact changed.
- Added repeatability, rejection, failure, held-out validation, and immutable-store tests. The M1
  tests and shared geometry regressions pass.

#### M2 implementation evidence — 2026-09-20

- Added the deterministic `card_plane_initialization` processor. It selects one exact source frame,
  maps each model polygon into the calibrated table plane, and fits a bounded fixed-size card pose
  with a frozen grid-search recipe.
- Added source-linked suggestion diagnostics that retain polygons, confidence, provider, bundle,
  and fit residuals without changing the generated revision. Partial, rough, duplicate, malformed,
  and below-threshold candidates remain visible as failed or low-confidence diagnostics.
- Added pairwise overlap-evidence scoring and deterministic front-to-back ordering. Weak edges and
  order cycles are explicit in the stacking contract and do not become automatic review decisions.
- Added repeatability, calibrated-dimension, partial/low-confidence, failed-candidate, duplicate,
  and all-failed initialization tests. The M2, M1, and shared-geometry focused suites pass.

### M2 — Initialize poses and card stacking order

- Implement the fixed polygon-to-pose fit and pairwise stacking-evidence calculation.
- Produce one deterministic initial scene for a selected local generated result and calibration.
- Retain suggestion polygons and model identity as diagnostics, not reviewed geometry.
- Expose fit residuals, low-confidence poses, uncertain order edges, contradictions, and candidates
  that could not initialize.
- Add backend and fixture coverage for full, partial, rough, overlapping, duplicate, and missing
  model polygons.

Acceptance:

- the same result and calibration always produce the same initial scene and diagnostics;
- every initialized card has the calibrated dimensions and a source-linked suggestion ID;
- uncertain evidence is visible and never becomes an automatic review decision;
- initialization never changes the immutable generated revision; and
- a failed candidate fit does not block manual card creation on an otherwise valid frame.

#### M3 implementation evidence — 2026-09-20

- Added the versioned card-scene editor envelope to visible-card pipeline data. It preserves the
  reviewed scene, initialized scene, calibrated projection, and immutable suggestion lineage through
  canonical data round trips.
- Added the synchronized source-frame and rectified virtual-table editor. It supports card select,
  move, rotate, keyboard nudge, reorder, add, remove, restore, zoom, pan, and fit actions. The
  source view keeps model polygons dim and shows projected fixed-card outlines with live
  card-card visible-region masks.
- Routed calibrated scene edits through the existing maintained-reference `set_frame_review` queue.
  Each completed gesture produces one ordered command and keeps the existing retry, duplicate
  command, conflict recovery, reload, and optimistic save behavior. Empty and unusable decisions
  clear the draft scene.
- Added responsive and accessible controls plus focused scene-contract and editor interaction tests.
  Web typecheck, lint, formatting, production build, and all 183 web tests pass. Focused backend
  reference/data tests and the M0–M2 geometry suites pass.

### M3 — Edit cards on the virtual table

- Replace polygon-point correction for calibrated local results with the synchronized source-frame
  and rectified-table scene editor.
- Implement select, drag, rotate, nudge, reorder, add, remove, restore, zoom, pan, and fit actions.
- Render projected full-card outlines and live derived visible regions after every local edit.
- Integrate scene commands with autosave, retry, command de-duplication, revision-conflict recovery,
  keyboard navigation, accessibility, and responsive layout.

Acceptance:

- an operator separates a merged two-card suggestion by moving two standard cards and correcting
  their stacking order, without editing polygon points;
- adding and removing cards changes the reviewed count and the derived regions immediately;
- source and virtual-table selections, poses, and overlays remain synchronized after resize and
  reload;
- one gesture produces one ordered saved command; and
- cancel, retry, conflict, and restore paths do not lose or duplicate scene edits.

### M4 — Publish deterministic reviewed visible regions

- Add the backend scene-to-visible-region derivation and digest validation to maintained-reference
  update and completion paths.
- Store the reviewed scene and its derived visible-card candidate view without creating two geometry
  authorities.
- Propagate changed card IDs and calibration revisions through downstream identity-impact handling.
- Update comparison, identity crop, review coverage, and dataset materialization to consume the
  validated derived candidate view.
- Reject completion for stale derivation, invalid order, fully hidden retained cards, failed
  calibration, or unsupported external occlusion.

#### M4 implementation evidence — 2026-09-20

- Added one shared deterministic scene derivation path. It projects fixed-size poses, clips them to
  the exact source frame, subtracts higher cards in the reviewed order, preserves disconnected
  components, and emits reviewed visible-region candidates plus a digest receipt.
- Wired maintained-reference scene updates to replace stale candidate geometry with the derived
  candidate view. Completion re-derives the view and rejects stale receipts, invalid scene order,
  source-frame dimension mismatches, and fully hidden retained poses. Drafts can keep a hidden pose
  while the operator corrects the scene.
- Added downstream validation for visual identity crops, comparison inputs, review coverage, and
  dataset materialization. Processor polygons cannot enter dataset targets without reviewed scene
  derivation and completed coverage. Scene card IDs and calibration revision changes now propagate
  identity re-review impact.
- Exposed `card_scene` through the visible-card API contract and preserved the derived receipt in
  the web editor envelope. Added geometry, backend reference, dataset, and contract regression
  tests.
- Focused geometry, reference, data, dataset, comparison, identity, web, type, lint, formatting,
  and build checks pass. Full operations coverage passes except the pre-existing M8 campaign
  artifact test; full backend coverage passes except the pre-existing route-inventory count test.

Acceptance:

- visible regions contain only frame-clipped pixels not covered by higher cards;
- overlapping cards remain separate candidates and disconnected components survive derivation;
- completed references reload and rederive byte-equivalent visible-card candidates;
- downstream crops and training targets trace to the reviewed scene and exact calibration revision;
  and
- a processor polygon cannot become a training target without a completed reviewed scene and
  coverage decision.

### M5 — Verify the pose-based annotation loop

- Add an end-to-end fixture from recording calibration and local predictions through completed
  reference and dataset materialization.
- Run a bounded local operator review on distant cards, two-card overlaps, three-card overlaps,
  wrong model counts, and wrong initial stacking order.
- Record automatic calibration runtime, candidate yield and rejection reasons, plus per-frame counts
  of accepted poses, moved cards, rotations, reorder actions, additions, removals, ignore regions,
  and unusable frames.
- Publish concise in-product guidance for calibration diagnostics and scene correction.

Acceptance:

- the complete loop runs locally without Gemini, cloud infrastructure, or human calibration input;
- the operator can correct overlapping-card output through card pose and order edits alone on the
  supported frames;
- generated predictions, calibration evidence, reviewed scene, derived polygons, and dataset target
  retain complete lineage;
- browser, API, persistence, geometry, dataset, type, lint, formatting, and build checks pass; and
- unsupported frames fail explicitly instead of producing plausible but incorrect geometry.

## 8. Verification

Run shared-geometry unit and property tests, backend calibration and reference tests, API and
persistence tests, component and browser interaction tests, dataset-materialization tests, and the
normal type, lint, formatting, and production-build checks. Include candidate threshold boundaries,
temporal de-duplication, uneven table coverage, calibration outliers, held-out validation,
exact-frame changes, calibration replacement, cold reload, transient retry, duplicate commands,
revision conflict, source resize, frame clipping, disconnected components, equal stacking scores,
cyclic order evidence, fully hidden cards, and external-occluder rejection.
