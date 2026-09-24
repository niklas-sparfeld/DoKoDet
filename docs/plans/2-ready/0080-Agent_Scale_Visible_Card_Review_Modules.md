# Agent-scale visible-card review modules

## Plan status

- **Summary:** Split the visible-card workbench and its pipeline editor into small, cohesive modules
  with focused tests. Preserve all operator behavior and review contracts.
- **Status:** Ready
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

- **M0:** Not started — freeze behavior and the module ownership map.
- **M1:** Not started — extract workbench controls and presentation helpers.
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

- Existing focused tests pass before and after the milestone.
- The added characterization tests fail for a meaningful change to the listed behavior.
- The plan identifies one destination module for every function currently local to either root.
- No production behavior changes.

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
