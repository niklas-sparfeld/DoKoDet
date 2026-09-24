# Agent-scale visible-card review modules

## Plan status

- **Summary:** Split the visible-card workbench and its pipeline editor into small, cohesive modules
  with focused tests. Preserve all operator behavior and review contracts.
- **Status:** In Progress
- **Depends on:** Completed 0059 web workspace module boundaries and completed 0074 unified
  visible-card review workbench
- **Builds on:** The existing `PipelineVisibleCardTypes`, `VisibleCardReviewWorkbenchState`,
  inspector, presentation, calibration diagnostics, pose-scene, Timeline Rail, and maintained-reference
  command boundaries
- **Outcome:** A Luna phase can change one visible-card concern without loading two multi-thousand-line
  React components and their complete test files. The public editor and workbench contracts remain
  stable for their current consumers.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — freeze behavior, public boundaries, characterization coverage, and module ownership.
- **M1:** Complete — extract workbench controls, proposal presentation, and focused assertions.
- **M2:** Not started — extract workbench surface interaction and layers.
- **M3:** Not started — extract editor data, geometry, and URL helpers.
- **M4:** Not started — extract the maintained-reference command controller.
- **M5:** Not started — make both component roots small composition boundaries and split tests by owner.

## 1. Purpose

`VisibleCardReviewWorkbench.tsx` has 4,280 lines. It owns workbench state coordination, card-scene
drafts, calibration-anchor gestures, surface navigation, command-bar presentation, layer rendering,
projection helpers, and geometry helpers. `PipelineVisibleCardEditor.tsx` has 3,394 lines. It owns
reference loading, generated-result loading, proposal polling, calibration refinement, the ordered
maintained-reference command queue, polygon editing, frame selection, inspector portals, and page
composition. Their focused tests have 1,810 and 2,713 lines respectively.

The existing code already has good first seams: shared visible-card types, a workbench reducer,
inspector portals, presentation helpers, calibration diagnostics, and pose-scene helpers. This epic
uses those seams. It does not redesign the review workflow or add an abstract framework.

## 2. Fixed design

Keep these public component boundaries during the epic:

```text
PipelineVisibleCardEditor
  -> visible-card editor controller
  -> visible-card editor data and geometry helpers
  -> inspector and proposal presentation
  -> VisibleCardReviewWorkbench
       -> workbench controller
       -> command controls
       -> review surface interaction
       -> ordered evidence layers
```

The two current component files become composition boundaries. They may keep the public exports
used by `RecordingWorkspaceShell` and existing tests. Internal modules may use explicit typed
parameter objects. Do not introduce React context, a global store, an event bus, or a generic
canvas framework only to avoid props.

Use these ownership rules:

- The editor controller owns asynchronous load, polling, retry, conflict recovery, ordered command
  application, and all authoritative draft state.
- The workbench controller owns transient viewport, pointer gesture, selection, and local scene
  draft coordination. `VisibleCardReviewWorkbenchState` remains the pure reducer owner of workbench
  preferences and availability.
- Presentation modules render controls, inspector content, surface, and layers. They do not call
  the API or write review commands directly.
- Pure parsing, geometry, transform, and identifier helpers are ordinary TypeScript modules with
  direct unit tests. They do not import React.
- A test file tests the module that owns the behavior. Keep end-to-end editor tests only for the
  cross-module operator loop.

Preserve current URLs, API calls, maintained-reference command order, retry limit, calibration
preview timing, source-coordinate storage, layer draw order, hit-test priority, accessibility names,
keyboard behavior, and generated read-only behavior. Do not change data revisions, proposal
lineage, calibration authority, or the Timeline Rail contract.

## 3. Scope

This epic includes:

- behavior-preserving extraction and deletion of duplicate local helpers;
- typed internal controller and view-model boundaries;
- colocated test files for extracted pure logic and interaction behavior;
- moving only selectors exclusively used by an extracted presentation module; and
- a final root-file and focused-test size guard for these two surfaces.

This epic excludes:

- new visible-card, card-scene, calibration, or maintained-reference behavior;
- API, URL, persistence, or data-contract changes;
- a visual redesign or CSS-token cleanup outside selectors moved with their owner;
- changes to the recording workspace, inspector, Timeline Rail, or another review stage; and
- a shared framework for event or visual-identity editors.

## 4. Delivery milestones

### M0 — Freeze behavior and ownership

- Record the current imports, public exports, current consumers, and the ownership map in this epic.
- Add or move characterization tests for the fragile seams: generated versus maintained loading,
  ordered command retry and conflict recovery, proposal polling to a terminal state, calibration
  preview and apply, Camera and Rectified switching, layer order, selection, pointer gestures,
  keyboard actions, and frame decisions.
- Define named internal module contracts before moving code. Each contract must state its inputs,
  outputs, owner, and whether it can issue a review command.
- Establish a final size budget: each root component is at most 500 nonblank lines; each focused
  test file is at most 800 nonblank lines. A module may exceed that budget only for a coherent
  geometry or layer algorithm, with a short documented reason in the module header.

Acceptance:

- Run the existing focused tests before and after the milestone. Record current baseline failures;
  do not change behavior to make a characterization pass.
- The added characterization tests fail for a meaningful change to the listed behavior.
- The plan identifies one destination module for every function currently local to either root.
- No production behavior changes.

#### M0 implementation evidence — 2026-09-24

- Recorded the public exports and consumer paths, the current behavior coverage, the destination
  for every named top-level helper, and the internal contracts for each planned module.
- Added characterization for queued proposal polling, stale-revision conflict recovery, and
  calibration apply. Existing cases characterize generated read-only output, maintained-reference
  loading and rebase, transient command retry, proposal-scene loading, calibration preview data,
  Camera and Rectified switching, layer order, selection, pointer gestures, keyboard actions, and
  frame decisions.
- The two focused files report 70 passing and 10 failing existing tests. The failures are in
  timeline-slot rendering, polygon selection and editing, ignore-region editing, and generated
  suggestion restore. They reproduce without production changes in this milestone. Keep them as
  recorded baseline; do not alter behavior during extraction to hide them.
- No production code or review behavior changed.

#### Public boundary and consumers

`VisibleCardReviewWorkbench.tsx` exports `VisibleCardReviewWorkbench`, its props, action unions,
and `VisibleCardFrameDecision`. `PipelineVisibleCardEditor.tsx` exports
`PipelineVisibleCardEditor`, its props, and the `PipelineVisibleCardRailItem` type re-export.
`RecordingWorkspaceShell.tsx` renders the editor. `RecordingWorkspaceRail.tsx` and its test import
the rail-item type. The editor imports and renders the workbench. Keep these exports stable through
the epic.

#### Named module contracts

| Module | Inputs and outputs | Owner | Can issue a review command? |
| --- | --- | --- | --- |
| `VisibleCardReviewWorkbench.tsx` | Public props in; composed workbench view out | Public composition root and workbench coordinator | No; it emits typed callbacks to the editor |
| `VisibleCardReviewWorkbenchController.ts` | Typed frame capabilities, preferences, callbacks, and pointer events in; transient selection, viewport, gesture, and local scene view model out | Workbench controller | No; it emits typed workbench actions and scene or anchor callbacks |
| `VisibleCardWorkbenchControls.tsx` | Narrow typed action and selection view models in; command bar and selection controls out | Workbench presentation | No |
| `VisibleCardWorkbenchProposalPresentation.tsx` | Candidate and proposal view models in; proposal column and candidate previews out | Workbench presentation | No |
| `VisibleCardWorkbenchSurface.tsx` | Frame, viewport, selection, layers, and typed pointer callbacks in; accessible SVG surface out | Surface presentation | No |
| `VisibleCardWorkbenchLayers.tsx` | Layer render context in; SVG layer nodes in fixed registry order | Evidence layer presentation | No |
| `VisibleCardWorkbenchGeometry.ts` | Points, polygons, poses, projections, and dimensions in; deterministic coordinates and SVG attributes out | Pure workbench geometry | No |
| `PipelineVisibleCardEditor.tsx` | Public editor props in; editor, inspector, rail, and workbench composition out | Public composition root | No; it delegates commands to its controller |
| `PipelineVisibleCardEditorController.ts` | Editor props and API client in; named async operations and editor view model out | Authoritative editor state and command controller | Yes; this is the sole API and command-queue owner |
| `PipelineVisibleCardData.ts` | Unknown API payloads and typed frames in; parsed frames, coverage, decisions, IDs, and mappings out | Pure editor data parsing | No |
| `PipelineVisibleCardGeometry.ts` | Points, candidate geometry, and pointer coordinates in; validated or edited geometry and hit-test results out | Pure editor geometry | No |
| `PipelineVisibleCardUrl.ts` | Current URL state and selected values in; parsed state and updated URL out | URL helpers | No |

#### Destination map for current named helpers

All workbench helpers below move to the named destination in their row. Inline callbacks and
handlers move with the module that owns their state. Types and constants that describe one owner
move with that owner. `VisibleCardReviewWorkbenchState.ts` remains the pure preference and
availability reducer.

| Current local helpers | Destination |
| --- | --- |
| `WorkbenchCommandBar`, `WorkbenchTimelineSelectionActions`, `FrameDecisionActions`, `VirtualCardSelectionActions`, `MappingSelectionActions`, `VisibleRegionSelectionActions`, and their local selection-action props | `VisibleCardWorkbenchControls.tsx` |
| `WorkbenchProposalColumn`, `CandidatePreview`, `candidateBounds`, `virtualCardPreviewCandidate`, `formatGeometryKind` | `VisibleCardWorkbenchProposalPresentation.tsx` |
| `WorkbenchSurface`, `RectifiedSourceFrame`, `MappingAnchorOverlay`, `MappingProjection`, `renderCalibrationFitOutlines`, `renderEditorOverlay`, `renderLayers`, `renderVisibleRegionLayer`, `renderSuggestionLayer`, `renderIgnoreLayer`, `renderVirtualCardLayer`, `renderMappingLayer` | `VisibleCardWorkbenchSurface.tsx` and `VisibleCardWorkbenchLayers.tsx`; surface and SVG composition go to Surface, ordered evidence rendering goes to Layers |
| `editorPoint`, `sourcePointFromEvent`, `sourcePointToTablePoint`, `readCalibrationAnchors`, `calibrationDraftRevision`, `calibrationCommandCount`, `readAnchorState`, `readString`, `isRecord`, `readTablePoints`, `cloneTablePoints`, `matchProjectionCornersToAnchor`, `mappingStrokeWidth`, `mappingCornerRadius` | `VisibleCardReviewWorkbenchController.ts` for calibration draft state and parsing; `VisibleCardWorkbenchGeometry.ts` for coordinate and projection calculations |
| `candidatePolygons`, `sourceCandidatePolygons`, `candidateNormalizedPolygons`, `candidateIsCoveredByIgnoreRegions`, `polygonsOverlapForIgnore`, `vertexOverlapRatio`, `polygonCentroid`, `polygonsMatch`, `pointInPolygon`, `transformSourcePolygon`, `posePolygon`, `candidatePosePolygon`, `sourcePoint`, `isSelected`, `renderOrder`, `rotationHandle`, `strokeWidth`, `pointsAttribute`, `pathAttribute`, `tableViewBox`, `cameraViewBox`, `surfaceViewBox`, `rectifiedBackgroundPatches`, `affineTriangleTransform`, `selectedPoseForSelection`, `clamp` | `VisibleCardWorkbenchGeometry.ts` |
| Remaining workbench-local transient state, viewport callbacks, keyboard handling, selection transitions, and gesture handlers | `VisibleCardReviewWorkbenchController.ts` |
| `readProposalInputRevisionId`, `readProposalRevisionId`, `toEditableFrame`, `readFramesFromResult`, `readOutcome`, `readFrameIdentity`, `readCandidate`, `readIgnoreRegion`, `isVisibleCardSide`, `readGeometry`, `frameCoverageKey`, `frameCoverageKeyFromIdentity`, `coverageEntries`, `frameDecision`, `nextManualCardId`, `nextManualRegionId`, `copiedIgnoreRegionId`, `newIgnoreRegion`, `ignoreRegionMapping`, `isFrameReviewState`, `isRecord`, `isInteger`, `clamp` | `PipelineVisibleCardData.ts` |
| `geometryPolygons`, `candidateIsWithinIgnoreRegions`, `polygonIsWithin`, `segmentIsWithin`, `segmentIntersectionParameters`, `pointInPolygonUnion`, `findClearlySelectedCandidate`, `findClearlySelectedPolygon`, `isClearlyOutsidePolygons`, `polygonClearanceRatio`, `polygonScale`, `pointInPolygon`, `pointOnSegment`, `reviewedGeometry`, `validatePolygons`, `polygonArea`, `insertPointOnNearestEdge`, `squaredDistanceToSegment`, `pointFromEvent` | `PipelineVisibleCardGeometry.ts` |
| `describeError`, `isRetryableError` | `PipelineVisibleCardEditorController.ts` |
| `readPipelineEditorUrlState`, `updatePipelineUrl` | `PipelineVisibleCardUrl.ts` |
| All editor-local API loading, proposal polling, calibration commands, maintained-reference queue, retry, rebase, optimistic state, and cleanup handlers | `PipelineVisibleCardEditorController.ts` |

`VisibleCardReviewWorkbenchController.ts` returns named callbacks and view-model fields. It does
not receive or return an API client, raw mutable refs, or a generic dispatch function.
`PipelineVisibleCardEditorController.ts` owns all API calls and mutable queue refs. Presentation
modules receive data and named callbacks only. Pure data, URL, and geometry modules do not import
React. The editor composition root keeps inspector portals, review navigation, status surfaces, and
the public exports.

#### Characterization coverage frozen before extraction

| Behavior | Existing test evidence |
| --- | --- |
| Generated output is read-only; maintained references can be loaded or rebased | `PipelineVisibleCardEditor.test.tsx`: generated read-only; empty-reference start; existing-review switch; proposal-scene load |
| Ordered save retry and conflict recovery | `PipelineVisibleCardEditor.test.tsx`: transient draft retry and new stale-revision recovery case |
| Proposal polling reaches a terminal state | `PipelineVisibleCardEditor.test.tsx`: new queued-to-complete polling case |
| Calibration preview and apply | Existing incomplete preview and workbench anchor-preview cases; new apply payload and completion case |
| Camera and Rectified switching; layer order | `VisibleCardReviewWorkbench.test.tsx`: viewpoint switching and ordered enabled layers |
| Selection, pointer gestures, and keyboard actions | Workbench tests: selection clearing, polygon pointer conversion, pan/zoom, card and anchor drags, keyboard nudge |
| Frame decisions | Workbench and editor tests: distinct Accept frame action, accepted/unreviewed and empty coverage |

The final budget remains at most 500 nonblank lines per root component and at most 800 nonblank
lines per focused test file. A cohesive geometry or layer algorithm can exceed a budget only with
a short reason in its module header.

### M1 — Extract workbench controls and presentation helpers

- Move `WorkbenchCommandBar`, selection-action panels, frame-decision actions, proposal-column
  presentation, candidate previews, and formatting helpers out of
  `VisibleCardReviewWorkbench.tsx` into focused workbench control and presentation modules.
- Give the controls one typed view-model and callback interface. Do not pass the complete workbench
  state or the editor controller to every child.
- Keep command labels, disabled reasons, shortcut hints, portal placement, and action dispatch
  unchanged.
- Move the related component assertions from the monolithic workbench test into control and
  presentation tests. Retain only workbench-level interaction coverage in the root test.

Acceptance:

- Control modules have no API-client imports and emit only typed callbacks.
- Command-bar, selection-action, and frame-decision behavior passes focused tests.
- The workbench still renders one stable command bar for generated and maintained frames.

#### M1 implementation evidence — 2026-09-24

- Moved command-bar and selection-action presentation to
  `VisibleCardWorkbenchControls.tsx`. The root passes a typed control view model and named
  callbacks. The editor state is reduced to the card ID, polygon count, and selected polygon index.
- Moved proposal-column rendering, candidate previews, stack-order previews, and geometry labels to
  `VisibleCardWorkbenchProposalPresentation.tsx`. Moved the pure candidate-coverage, pose-polygon,
  selection, and clamp helpers to `VisibleCardWorkbenchGeometry.ts`.
- Moved proposal layout and frame-decision assertions out of the root workbench test. Added focused
  tests for command labels and disabled reasons, selection-action dispatch, frame-decision callbacks,
  and proposal previews. Existing workbench interaction tests still cover command selection and
  operator dispatch through the root.
- The control and proposal modules do not import the API client. They emit typed callbacks and do
  not issue review commands.
- Verification: typecheck, Prettier, scoped ESLint, and `git diff --check` pass. The workbench and
  control tests pass. The combined workbench/editor run reports 73 passing and the same 10 editor
  baseline failures recorded in M0. Full ESLint also reports two existing errors in
  `cardEvents/CardEventFrameSurface.tsx`; scoped ESLint reports no errors and the existing
  `capabilities` dependency warning in the workbench root.
- No review behavior, command payload, or public component export changed.

### M2 — Extract workbench interaction and evidence layers

- Move viewport, pointer, wheel, pan, virtual-card gesture, and mapping-anchor gesture handling
  into a focused workbench controller or interaction hook.
- Move `WorkbenchSurface`, rectified background construction, layer renderers, hit testing,
  projection, and pure geometry helpers into surface, layer, and non-React geometry modules.
- Keep `WORKBENCH_LAYER_REGISTRY` as the single registry for layer order and behavior. Preserve
  source and table coordinate conversions exactly.
- Keep `VisibleCardReviewWorkbench.tsx` as the coordinator that connects its public props, the
  reducer, controller, controls, and surface.

Acceptance:

- Layer order, selection, Camera/Rectified rendering, pan/zoom, card move/rotate, and mapping-anchor
  editing have focused regression coverage.
- Pure geometry tests do not mount React.
- The root workbench has no local SVG-layer renderer or low-level polygon helper.

### M3 — Extract editor data, geometry, and URL helpers

- Move response readers, frame conversion, coverage and decision helpers, polygon validation and
  editing calculations, ignore-region calculations, error description, and URL read/write helpers
  from `PipelineVisibleCardEditor.tsx` into named non-React modules.
- Reuse existing `PipelineVisibleCardTypes` and pose-scene types. Do not duplicate a candidate,
  frame, geometry, or save-state contract.
- Make parser failures explicit at the existing UI boundary. Keep current malformed-result handling
  and messages unchanged.
- Split the corresponding unit cases from `PipelineVisibleCardEditor.test.tsx` into direct helper
  tests.

Acceptance:

- The extracted data and geometry modules have direct tests for valid inputs and current invalid
  or boundary inputs.
- The editor no longer defines response parsing, polygon intersection, or URL serialization helpers.
- Generated and maintained frame selection produces the same rail items and review decisions.

### M4 — Extract the maintained-reference command controller

- Move reference hydration, generated-result loading, proposal-run polling, calibration-refinement
  load and commands, ordered command queue, retry scheduling, rebase, completion, and local draft
  synchronization into a typed editor controller hook or controller module.
- Keep the controller as the only owner of API-client calls and mutable queue refs. Its returned
  view model must expose named operations rather than raw refs or a generic dispatch function.
- Keep the editor root responsible for composing inspector portals, review navigation, status
  surfaces, and the workbench. It must not duplicate controller state.
- Add controller tests with mocked client responses for success, terminal failure, retry, stale
  revision conflict, rebase, and unmount cleanup.

Acceptance:

- Command sequence and retry behavior are unchanged and controller tests prove the ordering.
- Proposal polling never blocks the UI and stops at the same terminal states.
- No presentation module imports the API client.

### M5 — Finish composition roots and enforce the agent-scale boundary

- Reduce both root components to public-prop adaptation and composition. Delete superseded local
  helpers, duplicate types, obsolete tests, and CSS selectors made unused by the extractions.
- Split remaining large root tests by source ownership. Retain one concise integration suite per
  root for the complete maintained-reference and generated operator paths.
- Run the full web check and the visible-card browser workflow. Compare the pre-M0 and final public
  exports, URL behavior, command payloads, and relevant DOM accessibility names.
- Add a lightweight repository check that fails when either root component or its root test exceeds
  the M0 budget. The check must ignore generated files and report the offending path and count.

Acceptance:

- Both roots and focused tests satisfy the M0 size budget, except documented cohesive algorithms.
- `npm run check` passes from `web/`.
- The visible-card browser workflow covers generated inspection, maintained editing, save/retry or
  conflict recovery, and Camera/Rectified review without behavior differences.
- There are no unused imports, dead compatibility wrappers, or changed backend contracts.

## 5. Execution rules

Complete milestones in order. Keep each milestone to one Luna phase and one focused commit on
`main`. Do not combine a feature change with an extraction. If characterization reveals an existing
bug, record it separately; do not change behavior in this epic unless a user explicitly adds that
work.

Before each extraction, run the affected focused tests. After it, run those tests, lint, typecheck,
and `git diff --check`. Run `npm run check` and the browser workflow in M5. Work only in
`web/src/visibleCards/` unless an exclusively used style or test requires an adjacent change.
