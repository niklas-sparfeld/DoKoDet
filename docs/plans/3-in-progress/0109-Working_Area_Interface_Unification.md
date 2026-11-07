# Working area interface unification

## Plan status

- **Summary:** Build one current-frame geometry surface for all processing steps. Adapt the current
  node-backed editors to use it. Keep controls, text, crops, and result details outside the center.
- **Status:** In Progress
- **Depends on:** [0107 — Unified pipeline data lineage](../5-closed/0107-Unified_Pipeline_Data_Lineage.md)
  and [0108 — Horizontal lineage workspace](../5-closed/0108-Horizontal_Lineage_Workspace.md), including its
  separate Virtual scenes step and exact lineage selection.
- **Outcome:** M0–M4 are complete. M1 adds a tested, selectable polygon surface for exact-frame
  geometry. M2 adds shared still-frame loading and identity checks. Neither milestone restores or
  claims the historical editing interactions. M3 connects Events to the still-frame surface. M4
  connects Visible cards and Virtual scenes. M5–M10 are not started. See the
  [M0 inventory and contract](../../reports/0109-M0_Working_Area_Inventory.md) and the execution
  handoff below.

## Problem and inspection

The current tabs use different source surfaces and place controls and descriptions in different
areas. Inspection of the current code found these differences:

| Step               | Current implementation                                                                                                                                                                                                                | Change required                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Events             | `CardEventFrameSurface` switches between derived JPEGs and a video element. Its frame chrome contains time, loading, and error descriptions.                                                                                          | Shared still frame; all time and status information outside the center.                                                                               |
| Visible cards      | The current node-backed editor loads an exact visible-card revision, selects outcomes, shows the recording video, and edits region, pile, and ignore arrays as JSON. It has no geometry renderer or direct geometry editing.          | Add the common frame geometry surface; later connect exact still frames and geometry adapters. Keep JSON editing until a geometry editor replaces it. |
| Virtual scenes     | The current node-backed editor loads an exact virtual-scene revision, selects frames, shows the recording video, and edits scene JSON. It has no pose renderer or direct pose editing.                                                | Add calibrated pose outlines and editing through later step integration; keep scene and calibration details in the inspector.                         |
| Visual identities  | `PipelineNodeVisualIdentityEditor` displays exact crop/source details and identity review controls.                                                                                                                                   | Shared selectable source regions; crop, candidates, and classification controls in the inspector.                                                     |
| Table observations | `PipelineObservationWorkbench` shows a native video player and a textual observation summary.                                                                                                                                         | Shared source frame with exact spatial evidence when available; interval and summary outside the center.                                              |
| Round analysis     | `PipelineRoundAnalysisWorkbench` shows a native video player, a summary, and a button that replaces the center with `RecordingAnalysisView`. That view has its own selection, evidence rows, hypotheses, and counterfactual controls. | Shared source frame at all times; integrate existing results with the rail and inspector. Remove the alternate central workbench.                     |

These are source-code findings, not a completed browser usability study. M0 verifies the rendered
layout with local fixtures. Use the domain meanings in the [glossary](../../glossary.md).

## Relationship to 0107 and 0108

0107 owns data, provenance, review, accepted inputs, and copy rules. 0108 owns the two-row step
navigation, lineage drawer, editor integration, migration, and runtime cutover. Do not duplicate
that work or create another data selector here.

0107 defines virtual scenes as separate content. 0108 exposes their separate step. Thus the user
selects Visible cards or Virtual scenes through normal step navigation. Remove the old edit-mode
switch that combines these tasks inside Visible cards. Keep camera/rectified viewpoint, layer
visibility, and active drawing tools as independent controls. They do not select a data set or
change its authority. No additional top-level "view modes" selector is needed.

0108 completed its cutover with node-backed editors. This epic builds on those current contracts
and replaces their video and JSON-only geometry views as each step is connected. It does not restore
deleted historical renderers or block 0108.

## Shared layout and interaction

- **Top:** The 0108 processing navigation and lineage drawer remain the source of data selection.
- **Center:** One current-frame surface. It contains source pixels, spatial geometry, selection,
  focus indicators, and direct edit handles only. Keep the same frame sizing and fit behavior in
  every step. Preserve the source aspect ratio; do not force every image into a square.
- **Inspector:** Viewpoint and layer controls, active tools, selected-item details, crop preview,
  candidates, review and editing commands, save/conflict state, calibration metrics, run status,
  and errors. Group common view controls consistently above step-specific details.
- **Timeline Rail:** One time cursor, scrubber, frame stepping, event/observation intervals,
  selected-item navigation, and analysis rows. Time labels and time-entry controls belong here.
  Existing selection/review controls can use its command slots. Do not add a second time cursor.

No buttons, toolbars, badges, headings, captions, legends, IDs, card names, probabilities, metrics,
help text, empty-state messages, loading messages, or error descriptions appear in the center.
This rule also excludes hover tooltips and SVG titles that produce visible tooltips. Natural text
in source pixels is unchanged. Accessible names and hidden screen-reader descriptions remain.
Show loading, failure, no selection, and missing-data explanations in the inspector and rail. A
blank central surface must always have an explanation there; do not hide failures.

Commands still exist. Move their buttons outside the center. Do not make review, deletion, identity
correction, stacking order changes, or calibration acceptance automatic. Support direct geometry
selection and dragging in the center, plus equivalent keyboard and inspector operations. Keep
handles and focus marks free of text. Document shortcuts outside the image.

On narrow layouts, place the inspector below or beside the center. Its expanded crop/details must
not cover the image. No floating crop, modal decision form, or action toolbar over the frame.

## Frame and selection contract

- Maintain one workspace time cursor independently from the selected node, item, and analysis.
  Step switches retain time and viewport where valid. Clear an item only when exact correspondence
  is absent; explain that in the inspector. Never match cards by list position or similar time.
- Resolve source frames through a shared still-image loader. Reuse the existing derived-frame API
  and exact stored-frame paths where possible. No workspace renderer, comparison pane, or decoder
  fallback creates a video element. Local server-side video decoding remains allowed.
- Separate requested time from resolved frame time and identity. Expose both in the rail when they
  differ. Do not claim that a snapped sample or interval representative is the requested frame.
- Scrubbing can use bounded cached previews. Editing and review require the exact authoritative
  frame and evidence. A sampled preview never authorizes geometry edits or review.
- Draw overlays only when source identity, frame identity, dimensions, coordinate transform, and
  required calibration match. Suppress incompatible overlays and disable mutations. Do not
  interpolate, stretch evidence onto a nearby frame, or silently select an unrelated revision.
- A card/observation row selection can seek its exact evidence frame. An interval without a single
  source frame does not justify such a seek: retain the cursor or use a declared representative,
  identified in the rail. Scrubbing between evidence frames shows source pixels without stale
  overlays. Observation interval coverage alone does not establish per-frame geometry.
- Prevent late requests from replacing newer frames, crops, or overlays. On transition, clear stale
  spatial content; edits stay disabled until the exact frame and overlay context are ready. Keep
  caches bounded and release object URLs. Never buffer the full recording in the browser.
- Preserve deep links, reload, and back/forward through the 0108 selection contract. Persist view
  preferences separately from data selection. Browsing and display controls do not save content,
  create copies, accept review, launch processors, or change processor inputs.

## Spatial elements and step configurations

Use explicit layer names. Do not combine all geometry under an ambiguous "Cards" switch.
The table lists initial defaults; other supported layers are optional, read-only context.

| Spatial element            | Meaning and behavior                                                                                                                   | Default use                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Source frame               | Exact resolved source pixels; camera view is always available when pixels resolve.                                                     | All steps.                                                                                    |
| Visible regions            | Observed visible-card polygons; derived boxes only when those are the available geometry. Keep box fallback explicit in the inspector. | Visible cards and Visual identities; Table observations when exact sources resolve.           |
| Pile regions               | Coarse pile footprints. Never imply component count or identity.                                                                       | Visible cards; downstream only when included in exact evidence.                               |
| Ignore regions             | Excluded visual evidence, distinct from cards and piles.                                                                               | Visible cards.                                                                                |
| Full-card outlines         | Projected card poses under exact calibration, including hidden extent.                                                                 | Virtual scenes. Optional read-only context elsewhere only through exact source links.         |
| Derived visible regions    | Visible regions calculated from the selected virtual scene and stacking order. Distinct from detector or reviewed visible regions.     | Optional in Virtual scenes; downstream only when these are the declared crop/evidence source. |
| Calibration geometry       | Anchor corners, mapping geometry, and fit outlines. Text and measured errors stay in the inspector.                                    | Optional in Virtual scenes.                                                                   |
| Other observation geometry | Active table area or other declared spatial evidence, only if the stored capability supplies valid geometry and source correspondence. | Optional in Table observations. No new analyzer capability is required.                       |
| Selection and edit handles | One consistent selected shape and keyboard focus treatment. Handles appear only for the active editable content.                       | All selectable geometry; editing in the owning step only.                                     |

Events needs no spatial overlay by default. Its intervals and boundaries belong on the rail.
Visible cards edits visible, pile, and ignore regions. Virtual scenes edits poses and stacking
order and retains existing calibration operations. Visual identities selects source geometry but
changes classification only through the inspector. Observations and analysis inspect source
geometry without editing upstream evidence. Read-only source layers do not become local content.

Camera versus rectified is a shared viewpoint control, not a processing step or review mode.
Offer rectified view only with an exact valid calibration; otherwise show the reason outside the
center. Preserve pan, zoom, fit/reset, layer toggles, and hidden-layer hit-test rules. Use stroke
patterns and focus treatment as well as color. Put any legend in the inspector.

## Crop preview

Use one resizable selected-item crop section in the inspector. Put the crop above identity choices
and candidate probabilities. The center keeps the full source frame. Small crop thumbnails can
remain in the inspector's item list; remove the separate central proposal/crop column.

For identity inspection, show the actual frozen processor input crop with its policy and exact
source references. A generic selection preview must not masquerade as the processor crop. Name
the preview type and explain missing, unusable, failed, face-down, or outdated evidence outside the
center. Do not synthesize hidden pixels. Selection in frame, rail, list, and crop stays synchronized.

Support crop zoom and fit within the inspector. Collapse other inspector sections when more crop
space is needed. Keep accessible identity-choice buttons and shortcuts there. Crop loading and
errors must not block source-frame inspection or show the previously selected item's crop.

## Table observations

Show observation intervals on the rail. Show the selected observation's observed-card list,
identity candidates, uncertainty, capability availability, status, and all exact source references
in the inspector. A zero-card observation is valid evidence, distinct from a missing or failed
observation. An absent optional capability is unavailable, not a zero score.

Resolve an observed card to exact spatial source evidence when the stored links permit it. Frame,
rail, and inspector selection highlight the same evidence. If the observation has no resolvable
frame geometry, keep it inspectable as interval evidence without inventing a polygon, track,
physical-card identity, or card play. Multiple sources remain explicit; an inspector source choice
changes inspected evidence only, never the observation's processor inputs.

## Round analysis

Keep the shared source frame visible. Present the existing evidence, table-observation, and
reconstruction-hypothesis rows as aligned tracks in the Timeline Rail. Put selected-hypothesis
choice, scores, alternatives, trick/round details, inferred actions, rules, exact inputs, failures,
and diagnostics in the inspector. Allow the rail and inspector to expand outside the center.
Do not require "Open analysis" or "Return to source" buttons.

Only actual source geometry appears over the frame. Do not draw inferred cards or plays as observed
pixels. A hypothesis action can highlight its linked observation/card if exact correspondence
exists. An inferred action without source evidence remains selectable in the rail and inspector;
it does not create a frame, fabricated timestamp, or geometry. Keep untimed inferred actions
ordered between evidence rows without claiming an exact capture time.

Preserve existing counterfactual correction, immutable run comparison, and evidence navigation.
Place their controls and result tables in inspector/expanded rail sections. Corrections remain
correction constraints; they do not change source observations. Scope is presentation and shared
selection, not new reconstruction algorithms or new counterfactual execution behavior.

## Comparison and scope limits

Exact-revision comparison uses two instances of the same surface in the center. Pair selection,
revision labels, explanations, and comparison metrics stay outside it. Synchronize time and
viewpoint only where valid; unmatched frames retain explicit missing-context status in outer
panels. Comparison cannot relax frame/calibration validation or borrow another branch's evidence.

Preserve existing processing controls in their outer slots. No new processor picker, refresh,
rerun workflow, review authority, migration, model, training, iOS redesign, or quality campaign
belongs here. Remove obsolete surface implementations and duplicate state after replacement.
Do not retain compatibility modes for the retired central layouts.

## Milestones

Each milestone is one small implementation phase. Use local recorded fixtures and mocks. Commit
completed milestones to main, update the board, and report one status line per milestone.

### M0 — Freeze layout and capability fixtures — Complete

Verify the current rendered tabs and inventory every command, diagnostic, selection, crop, and
analysis function. Assign each to the center, inspector, or rail. Define typed surface inputs and
frame/selection invariants. Record desktop and narrow-layout examples in a short report.

Acceptance: fixtures cover all six steps, comparison, empty and failed results, historical/read-only
content, missing calibration, interval-only evidence, and untimed inferred actions. No function
is lost merely to remove its central button or text. No application behavior changes yet.

Result: the [M0 inventory](../../reports/0109-M0_Working_Area_Inventory.md) records the current
function placement, typed frame/selection contract, fixture coverage, and desktop/narrow examples.
Contract fixtures specify missing-calibration, interval-only, and untimed-action behavior without
changing application behavior. Existing functions remain in place for the later surface migrations.

### M1 — Build the common geometry surface foundation — Complete

Add a reusable surface that displays a supplied still image and exact-frame polygon overlays.
Reject overlays whose source, frame, dimensions, or image digest differ. Draw calibration-bound
geometry only when the active calibration revision and digest match. Support accessible shape
selection by pointer and keyboard. Keep all visible labels, controls, diagnostics, and commands
outside the surface. This milestone is a rendering and selection foundation; it does not claim to
restore prior region, pose, mapping, or calibration editing interactions.

Acceptance: focused tests prove frame and calibration mismatch suppression, stable image aspect
ratio, selectable accessible polygons, and no visible text or controls inside the surface. M2 adds
the shared exact-frame loader. M4 connects visible-card and virtual-scene data and builds the
step-specific editing adapters while preserving current node and revision contracts.

Result: `web/src/workingArea/GeometrySurface.tsx` provides the foundation. Current editors remain
unchanged in this milestone and continue to use video and JSON editing.

### M2 — Implement shared exact-frame loading — Complete

Provide shared still-frame loading and requested/resolved identity state. Reuse bounded frame
caching. Extend the local frame API only if existing endpoints cannot prove the required identity;
update generated API types if changed. Add race and sample/exact mutation guards.

Acceptance: rapid scrub and step switches cannot restore stale frames or overlays; failures,
source changes, and variable frame timing are explicit. No video element or full-video buffer.

Result: `workingAreaFrame.ts` provides shared exact and sampled still-frame loading, a bounded
32-frame object-URL cache, requested/resolved timing, source/frame identity validation, stale-request
protection, and an exact-only mutation guard. The existing derived-frame endpoint now returns the
source digest, frame index, dimensions, and request timing in documented identity headers. No video
element or full-video buffer is used.

### M3 — Connect Events to the shared surface — Complete

Replace its frame/video renderer. Connect the rail cursor, exact event jumps, frame stepping, and
existing event edits. Move time, loading, buffering replacement status, and errors outside center.

Acceptance: event navigation and boundary editing retain behavior with still images. No independent
media clock, source playback toggle, or event-specific frame chrome remains.

Result: Events now loads the shared exact still frame from the accepted video identity. Event edits,
loading and save errors, requested/resolved time, and review controls stay in the inspector or rail.
The rail owns event jumps, the time cursor, and previous/next frame controls. Frame stepping resolves
the requested frame index through the local frame service. Events has no video element, playback
toggle, or media clock.

### M4 — Connect Visible cards and Virtual scenes — Complete

Connect the separate node-backed steps to the common still-frame surface. Move editing and review
controls into the inspector and navigation into the rail. Preserve region, pile, ignore, pose,
stacking, and calibration operations. Offer other exact-source geometry as read-only context only.

Acceptance: each step edits only its own content; source/calibration mismatch blocks edits. Pan,
zoom, viewpoint, review, copy-on-change, and calibration diagnostics remain available.

Result: both steps use exact still frames and keep their controls in the inspector and frame
selection in the Timeline Rail. Visible cards draws source geometry and keeps region, pile, ignore,
review, and copy-on-change operations. Virtual scenes reads the exact published calibration, draws
calibrated pose outlines, supports source and rectified views, and keeps pose, stacking, review, and
copy-on-change operations. A source, frame, dimension, or calibration mismatch suppresses geometry
and blocks edits and frame review. See the
[M4 integration report](../../reports/0109-M4_Node_Steps_Surface_Integration.md).

### M5 — Integrate selected crops and Visual identities — Not started

Replace the identity-specific frame renderer. Add the common inspector crop section and move
identity choices and proposal lists out of center. Synchronize frame/list/rail/crop selection.

Acceptance: correct crop policy/source and candidates remain inspectable; rapid item changes never
show stale crops. Missing/unusable crops and keyboard classification work without central controls.

### M6 — Connect Table observations — Not started

Replace video and summary with the common surface. Add interval selection, observed-card inspector,
capability/status details, exact spatial source links, and explicit no-geometry behavior.

Acceptance: zero-card, missing, failed, multiple-source, and interval-only fixtures stay distinct.
Only matching evidence produces overlays. Selection does not mutate inputs or source evidence.

### M7 — Integrate analysis evidence and hypotheses — Not started

Keep the frame surface mounted. Move existing evidence/observation/hypothesis rows into the rail
and result detail into inspector sections. Unify analysis, row, hypothesis, and source selection
with workspace navigation; remove the central source/workbench toggle.

Acceptance: selecting linked evidence seeks/highlights the exact source; untimed inferred plays
remain readable without fabricated pixels or time. Reload restores analysis and hypothesis choice.

### M8 — Relocate counterfactual and comparison functions — Not started

Move existing counterfactual controls/results outside center. Use the shared renderer in exact
revision comparison. Preserve immutable run selection and explicit pair controls.

Acceptance: existing correction and comparison fixtures retain behavior, failures, and source
references. No video or alternate central analysis page returns through these nested flows.

### M9 — Complete accessibility and layout cleanup — Not started

Verify keyboard equivalents, focus, external announcements, layer patterns, inspector crop sizing,
and narrow layouts. Remove replaced components, mode state, CSS, video caches, and handlers only
when their remaining consumers are gone. Retain unrelated source-video uses outside this workspace.

Acceptance: no supported workspace state puts controls, labels, tooltips, or descriptions in center.
Every blank/loading/error state has an outer explanation. Inspector expansion never covers source.

### M10 — Verify all steps and close — Not started

Run focused frontend tests, browser regression, type/build/lint/format checks, API checks if changed,
and relevant frame-service backend checks. Check local Markdown links. Publish commands and any
unrelated baseline failures; close only after the acceptance requirements pass.

Acceptance: a browser regression scrubs and switches all six steps, checks exact frame/overlay/crop
selection and stale requests, edits regions and poses, classifies a card, inspects observation and
analysis uncertainty, compares immutable results, and restores history. It checks the absence of
video elements, central text, and central command controls. No hardware or model rerun is needed.

## Execution handoff

- Completed: M0 — freeze layout and capability fixtures; M1 — add the common exact-frame geometry
  surface foundation; M2 — add shared still-frame loading and source/frame identity state; M3 —
  connect Events to the exact still-frame surface; M4 — connect Visible cards and Virtual scenes.
- Changes: Visible-card polygons render over exact source frames. Both editors place controls in the
  inspector and frame navigation in the rail. Virtual scenes reads the requested published
  calibration revision and checks its digest and frame dimensions before drawing or editing poses.
  The rectified view uses that homography to warp source pixels. Pose, stacking, review, and
  copy-on-change controls remain in the inspector. Details are in the
  [M4 integration report](../../reports/0109-M4_Node_Steps_Surface_Integration.md).
- Checks: `cd web && npm run check` passed (typecheck, lint, Prettier, generated API comparison,
  and 189 frontend tests). `cd web && npm run build` passed. The M4 browser regression passed at
  desktop and narrow sizes. It covered exact frame selection, both surfaces, calibration mismatch
  blocking, rectified view, review, and copy-on-change. The focused published-calibration API test,
  Ruff lint, Ruff format, and local Markdown link check passed. Evidence is in the M4 report.
- Decisions: node-backed revisions remain authoritative. The calibration endpoint reads one exact
  published revision from the existing immutable calibration store. It does not select or modify
  calibration. The editor checks source SHA, requested time, frame index, presentation time,
  dimensions, image digest, calibration revision ID, and calibration digest.
- Limits: pose edits use center dragging plus inspector fields and stacking controls. Rotation
  has no center handle; use its typed inspector field.
- Next: M5 — Integrate selected crops and Visual identities.
- Run: requested 11 milestones, completed 5, remaining 6.
