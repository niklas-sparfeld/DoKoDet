# Unified visible-card review workbench

## Plan status

- **Summary:** Replace the separate polygon and virtual-table review presentations with one
  visible-card workbench that has independent viewpoint, layer, edit-tool, and action controls.
- **Status:** Ready
- **Depends on:** Completed 0049 recording pipeline review, completed 0054 unified recording
  workspace layout, completed 0065 visible-card ignore regions, and completed 0073 proposed card
  scenes and calibration refinement
- **Builds on:** The maintained-reference commands, source-frame polygon editor, pose editor,
  table-plane calibration, Timeline Rail, inspector, and ordered save behavior from those plans
- **Outcome:** An operator reviews every visible-card frame in one stable workbench. The operator
  can change between Camera and Rectified viewpoints, show several evidence layers together,
  choose one edit tool, and find all applicable actions in one consistent command bar.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — freeze the interaction model and add shared workbench state.
- **M1:** Not started — render both viewpoints and all supported layers in one review surface.
- **M2:** Not started — move visible-region and ignore-region editing into the workbench.
- **M3:** Not started — move virtual-card editing into the workbench.
- **M4:** Not started — move mapping refinement into the workbench.
- **M5:** Not started — consolidate actions, remove the split presentations, and verify the complete
  operator loop.

## 1. Problem

Visible-card review currently selects one of two component trees from the shape of the active
frame. A frame with a card scene opens the virtual-table editor. A frame without a card scene opens
the source-frame polygon editor. Each tree owns its own canvas, selection behavior, controls, and
actions.

This split presents one reviewed data item as two different products. It also couples unrelated
choices:

- changing the coordinate view also changes which evidence is visible;
- choosing an editor determines which canvas and action layout appears;
- polygon, card-pose, ignore-region, and mapping actions appear in different places; and
- controls use short symbols or overlapping labels without always identifying the object they
  affect.

The underlying data is one visible-card frame. Source-frame polygons, virtual cards, derived
visible regions, ignore regions, and calibration evidence are different representations or layers
of that frame. The UI must reflect that model.

## 2. Fixed interaction model

Use one **Visible-card review workbench** for generated and maintained-reference frames. Its state
has four independent dimensions.

### 2.1 Viewpoint: one selected value

The viewpoint controls the coordinate system and background, not the reviewed data:

- **Camera** shows the exact source frame in source-image coordinates.
- **Rectified** shows the same frame in the rectified table coordinate system.

Use one viewpoint toggle button, not two adjacent buttons. Its visible label shows the current
viewpoint. Its accessible name also states the viewpoint that activation will open, for example,
`Viewpoint: Camera. Switch to Rectified`. Activating it changes Camera to Rectified or Rectified to
Camera. Disable the single button with a visible reason when Rectified is unavailable.

Both viewpoints use the same selection, layers, edit tool, draft, undo state, and save queue.
Changing viewpoint never writes a review command. Keep the selected viewpoint when the operator
moves between frames. Disable Rectified with a visible reason when no valid table-plane
calibration exists. Do not replace the complete workbench with another editor.

### 2.2 Layers: zero or more selected values

The **Show** control uses one independent pressed or unpressed toggle button for each layer. It
does not use paired show/hide buttons, a mutually exclusive segmented control, or another edit
mode switch. The first release supports:

- **Visible regions** for reviewed or proposed source-frame polygons;
- **Virtual cards** for full-card outlines, stacking order, and selection;
- **Ignore regions** for reviewed source-frame exclusions;
- **Detector suggestions** for immutable generated evidence; and
- **Mapping diagnostics** for anchors, current projections, and candidate projections.

Render every enabled and available layer at the same time. Transform geometry into the active
viewpoint for display. Keep stored geometry in its existing authority coordinate system. A layer
that is unavailable for the selected frame stays listed, disabled, with a short reason.

Use one typed layer registry so a later overlay supplies its label, availability, drawing order,
hit-test policy, and renderer without adding another top-level review presentation. Persist layer
choices while navigating frames. Default to the smallest useful set for each review source, but do
not silently change choices after the operator changes them.

### 2.3 Edit tool: one selected value

The **Edit** control selects one exclusive tool:

- **Visible regions** edits card polygons and ignore regions.
- **Virtual cards** edits card count, card pose, and card stacking order.
- **Mapping** edits calibration anchors and previews a recording-wide table-plane calibration.

The active tool controls pointer and keyboard input. It does not control layer visibility. For
example, the operator can edit a visible-region polygon while virtual-card outlines remain visible.
Selecting a disabled tool must show why the frame cannot use it. A viewpoint change must not cancel
the active tool or a committed draft. An in-progress pointer gesture follows the existing cancel
rules before any state change.

Do not add a fourth duplicate editor for inspection. When the workbench is read-only, it keeps the
same selected tool and layers but suppresses mutations and explains the read-only state.

### 2.4 Actions: one stable command bar

Place one command bar directly above the review surface. Keep its groups and order stable:

```text
View: [Camera ↔ Rectified]
Show: Visible regions | Virtual cards | Ignore regions | Suggestions | Mapping
Edit: Visible regions | Virtual cards | Mapping
Selection actions: changes with the active tool and selection
Frame decision: Accept frame | Mark empty | Mark unusable
```

The selection-action group changes with the active tool:

| Active tool     | Selection actions                                                                                                                                                |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Visible regions | Add visible card, add polygon, remove polygon, draw ignore region, convert selection to ignore region, copy ignore regions, delete selection, restore suggestion |
| Virtual cards   | Add virtual card, accept card, reject card, accept remaining cards, remove card, bring forward, send backward, restore proposed scene                            |
| Mapping         | Accept anchor, adjust anchor, pin anchor, exclude anchor, start preview, discard preview, apply mapping                                                          |

Show only actions that make sense for the active tool, but keep the group in the same location.
Keep a disabled action visible when its absence would make the next step unclear. Give every
disabled action a reason. Use text labels with optional symbols. Do not use an unlabeled `+`, `-`,
check mark, arrow, or `Accept` when several objects could receive that action.

Keep **Accept frame** separate from **Accept card** and **Accept anchor**. Accept frame is the final
frame decision and stays in the same command-bar group for every edit tool. It is disabled until
all required card decisions are resolved, the active polygon is valid, no mapping apply is in
progress, and all queued commands are saved. Frame navigation remains in the Timeline Rail and is
not duplicated in the command bar.

## 3. Selection, focus, and state behavior

Use one selection model for the complete workbench. A selected item has a type and stable ID. The
type can be visible card, polygon, ignore region, virtual card, or calibration anchor. The
selection-action group reads this model instead of maintaining component-specific selection state.

Apply these rules:

1. A matching representation of the selected item remains selected across viewpoints.
2. Hiding the selected item's layer clears visual focus only after a clear notice. It does not
   delete or accept the item.
3. Changing the edit tool keeps a compatible selection and clears an incompatible selection.
4. Moving to another frame keeps viewpoint, layer choices, and edit tool when available. It resets
   the item selection and cancels any unfinished pointer gesture.
5. Reload restores the saved backend draft and the last valid viewpoint, layer, and tool choices.
   UI preferences are not review authority and never enter a data revision.
6. Undo, retry, conflict recovery, and pending-save status use the existing ordered maintained-
   reference and calibration-draft paths. The workbench must not create a second command queue.

Keyboard shortcuts are scoped to the active tool. The command bar shows the current shortcuts and
updates accessible names when the tool changes. Do not trigger a canvas shortcut while focus is in
an input, dialog, or inspector control. Keep pan and zoom available through direct mouse and
trackpad gestures and through keyboard input while the review surface has focus. Do not render
dedicated zoom-in, zoom-out, directional-pan, or fit buttons.

## 4. Data and component boundaries

Keep all backend schemas, immutable revisions, maintained-reference authority, proposal lineage,
table-plane calibration authority, and dataset behavior unchanged.

Replace the frame-shape conditional that chooses `PoseBasedVisibleCardEditor` or
`VisibleCardFramePanel` with one workbench composition:

```text
VisibleCardReviewWorkbench
  -> WorkbenchCommandBar
  -> ReviewSurface
       -> viewpoint transform and background
       -> ordered layer registry
       -> shared selection and hit testing
       -> active edit-tool controller
  -> existing inspector portals
  -> existing Timeline Rail navigation
```

Extract pure transforms and editing operations from the existing components. Reuse their tested
geometry, gesture, and ordered-command behavior. Do not keep the old components as hidden
compatibility paths after the cutover. Remove obsolete component state, duplicated controls, CSS,
and tests in the milestone that replaces them.

Generated results use the same workbench in read-only form. A maintained reference enables edit
tools and decisions. A frame without a proposed card scene remains usable for polygon review. A
frame with a valid calibration but no virtual cards can use **Add virtual card**. A frame without a
valid calibration cannot use Rectified, Virtual cards, or Mapping, but the Camera viewpoint and
visible-region tools remain available.

## 5. Scope

This epic includes:

- one visible-card review surface for polygon and card-scene frames;
- Camera and Rectified viewpoints over the same selected frame;
- simultaneous, extensible evidence-layer toggles;
- exclusive visible-region, virtual-card, and mapping edit tools;
- one stable, contextual command bar with explicit object names;
- one shared selection, focus, pointer, keyboard, and save-state model;
- generated-result read-only presentation in the same workbench;
- removal of the old frame-shape presentation split and duplicated controls; and
- desktop, narrow-layout, keyboard, pointer, reload, and failure regression coverage.

This epic excludes:

- changes to visible-card, card-scene, calibration, or maintained-reference data contracts;
- new detector, identity, calibration, or reconstruction behavior;
- automatic acceptance or new review authority;
- multi-frame editing, batch geometry operations, or comparison between revisions;
- a general canvas framework for other review stages; and
- redesign of the recording shell, inspector, or Timeline Rail.

## 6. Delivery milestones

### M0 — Freeze the workbench state and interaction contract

- Add a typed workbench state for viewpoint, enabled layers, active edit tool, and typed selection.
- Add pure availability and transition rules for frames with polygons, card scenes, calibrations,
  proposals, ignore regions, and read-only state.
- Freeze drawing order, hit-test priority, persistence rules, tool-switch cancellation, shortcut
  scope, single-button toggle semantics, disabled reasons, gesture and keyboard viewport controls,
  and narrow-layout command-bar behavior.
- Add component fixtures and reducer tests for each supported and unsupported state combination.

Acceptance:

- viewpoint, layers, edit tool, and selection can change independently;
- invalid Rectified, Virtual cards, and Mapping states have deterministic reasons;
- frame navigation preserves valid workbench preferences and clears transient selection safely;
- no workbench preference writes a maintained-reference command; and
- every mutating shortcut is owned by exactly one edit tool.

### M1 — Build one surface with both viewpoints and layered evidence

- Add the shared review surface and Camera and Rectified background transforms.
- Add the typed layer registry and render visible regions, virtual cards, ignore regions, detector
  suggestions, and mapping diagnostics in fixed order.
- Add shared selection rendering and hit testing without enabling mutations.
- Use the workbench for generated-result read-only views and maintained-reference inspection.

Acceptance:

- one selected frame remains mounted when the operator changes viewpoint or layer visibility;
- visible regions and virtual cards can appear together in either valid viewpoint;
- stacking order, occlusion, ignore regions, and candidate mapping overlays remain correct;
- unavailable layers stay visible in the Show control with an actionable reason; and
- viewpoint or layer changes do not alter review content, save state, or revision lineage.

### M2 — Integrate visible-region and ignore-region editing

- Move card polygon selection, point insertion, dragging, multi-polygon editing, and deletion into
  the shared surface.
- Move ignore-region draw, edit, convert, copy, and delete operations into the same tool.
- Add the Visible regions selection actions to the shared command bar.
- Remove the replaced polygon canvas and its separate action controls.

Acceptance:

- the retained polygon and ignore-region browser cases pass through the workbench;
- edits made in either valid viewpoint persist in the existing source-coordinate contracts;
- virtual cards and suggestions can remain visible during polygon editing;
- tool and viewpoint changes cannot save an incomplete or invalid polygon; and
- retry, conflict, reload, and undo behavior still use the existing command queue.

### M3 — Integrate virtual-card editing

- Move virtual-card selection, move, rotate, numeric edit, add, remove, card decision, and stacking-
  order operations into the shared surface.
- Add the Virtual cards selection actions to the shared command bar.
- Preserve mouse, trackpad, pointer-cancel, keyboard, pan, zoom, and source-projection behavior.
- Remove the replaced pose-editor toolbar, its zoom, pan, and fit buttons, and its card action
  controls.

Acceptance:

- card geometry stays synchronized between Camera and Rectified viewpoints;
- visible-region and ignore-region layers can remain visible during card editing;
- every card action names its target and card acceptance is distinct from frame acceptance;
- mouse, trackpad, and keyboard users can pan and zoom without dedicated viewport-control buttons;
- selection, zoom target, pan, draft, and save status survive viewpoint changes; and
- existing card-scene commands and proposal lineage remain byte-equivalent.

### M4 — Integrate mapping refinement

- Move calibration-anchor handles, constraints, numeric edits, anchor decisions, preview overlays,
  and candidate-calibration gestures into the shared surface.
- Add the Mapping selection actions to the shared command bar.
- Keep recording-wide preview impact and apply controls connected to the existing inspector and
  atomic calibration operation.
- Remove the replaced mapping-mode toolbar and duplicated preview actions.

Acceptance:

- Mapping uses the same selected frame and layers as the other tools;
- current and candidate projections can appear with polygons and virtual cards in either viewpoint;
- entering Mapping never changes a card pose or visible-region polygon;
- leaving Mapping never applies or discards a candidate without an explicit action; and
- apply, discard, stale revision, affected-item confirmation, and failure recovery retain the 0073
  behavior.

### M5 — Consolidate decisions and verify the complete loop

- Move all contextual edit actions and frame decisions into the final command bar.
- Keep only frame navigation and temporal seeking in the Timeline Rail.
- Remove the remaining frame-shape branching, obsolete components, duplicated state, styles, and
  tests.
- Add concise in-product guidance for View, Show, Edit, selection actions, and frame decisions.
- Run one bounded local operator exercise over frames with polygons only, proposed card scenes,
  ignore regions, mapping refinement, unsupported calibration, and generated read-only data.

Acceptance:

- every visible-card frame opens the same workbench and keeps the same control locations;
- the active tool is always visible and only its valid selection actions are offered;
- Accept card, Accept anchor, Apply mapping, and Accept frame are visually and accessibly distinct;
- 1440 px, 1280 px, and narrow layouts keep the surface primary and the command bar usable;
- pointer, keyboard-only, focus, accessible-name, reload, retry, and conflict browser tests pass;
- the operator exercise completes without opening or recognizing a separate virtual-table editor;
  and
- no old presentation or compatibility path remains.

## 7. Verification

Use focused reducer, transform, layer-order, hit-test, action-availability, shortcut, and component
tests in each milestone. Retain the existing polygon, ignore-region, card-scene, gesture, mapping,
save-queue, and calibration-refinement regression cases while moving them to the workbench.

Finish with frontend type, lint, format, unit, production-build, and browser checks. Run browser
coverage at 1440 px, 1280 px, and the retained narrow viewport. Verify Camera and Rectified with
mouse, trackpad, touch-style pointer events, and keyboard-only input. Check all local Markdown
links.
