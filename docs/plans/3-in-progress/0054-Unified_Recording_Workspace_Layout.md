# Unified recording workspace layout

## Plan status

- **Summary:** Rebuild the recording pipeline UI around one large task surface, one persistent
  Timeline Rail, and one right-side metadata inspector. Remove repeated stage summaries, temporal
  lists, and tables that compete with the recording.
- **Status:** In Progress
- **Depends on:** 0048 and 0049 complete
- **Readiness:** The recording-owned routes, accepted-video stream, exact-frame derived view,
  pipeline workspace response, maintained references, processor controls, comparison results, and
  URL state already exist. This epic changes their web composition. It does not need a new backend
  or persistence contract.
- **Outcome:** At normal desktop sizes, the current video or source frame and the Timeline Rail are
  visible without page scrolling. Every pipeline stage uses the same layout and temporal navigation.
  Progress, the primary action, save state, and metadata have one predictable home.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — add the shared presentation model, representative pipeline states, browser
  viewport fixtures, and geometry helpers with focused unit coverage.
- **M1:** Complete — replace the tall page preamble with a bounded viewport shell, compact top bar,
  internal task and inspector scroll regions, and a Timeline Rail slot.
- **M2:** Complete — add the persistent inspector with stable progress, action, state, selection,
  metadata, and lineage/history sections; move workspace controls, diagnostics, and history into it.
- **M3:** Complete — add the shared Timeline Rail with transport, scrubbing, item lanes,
  synchronized URL/video selection, exact-frame previews, zoom, and accessible interaction states.
- **M4:** Complete — migrate generated event proposals and maintained-reference review to the
  shared video, inspector, and Timeline Rail workbench; remove the event timeline and tables.
- **M5:** Complete — migrate visible-card generation and review to the shared workbench.
- **M6:** Complete — migrate visual identity generation and review to the shared workbench.
- **M7:** Complete — migrate table-observation work to the shared workbench.
- **M8:** Complete — migrate round-analysis work to the shared workbench.
- **M9:** Not started — migrate comparison work to the shared workbench.
- **M10:** Not started — finish responsive, accessibility, visual, and obsolete-UI cleanup.

## 1. Current state and decision

Epic 0049 completed the recording-owned pipeline and removed obsolete review routes. Keep that
result. Do not reopen or amend the closed epic. This follow-up changes the presentation of the
implemented workflow.

The current `RecordingPipelineWorkspace` is one long document. Before it renders a stage editor, it
renders:

1. wide page padding and a separate back link;
2. a large product eyebrow, page title, recording identity, and video digest;
3. diagnostics;
4. five stage-navigation cards;
5. five more stage-summary cards;
6. another selected-stage heading and status;
7. a next-action panel;
8. generated/reviewed and revision selectors;
9. exact-input history; and
10. processor or analysis controls.

The stage editor, source video, and stage timeline follow that stack. A normal laptop viewport can
therefore show only navigation and status content. The operator must scroll before reaching the
recording.

Temporal navigation is also duplicated:

- event review has a timeline and a complete event table with screenshots;
- visible-card and visual identity review each have a source-item list and a timeline;
- generated event, visible-card, and visual identity results fall back to separate tables;
- comparison has a source-ordered outcome list beside its source view; and
- round analysis opens another diagnostic timeline below separate analysis lists and controls.

There is no workspace-level metadata inspector. Metadata is spread across the header, summary
cards, selectors, details elements, stage panels, count blocks, fixed completion bars, and tables.
The existing responsive rules mainly collapse these regions into a longer single column.

The correction is one shared viewport workbench. The recording is the stable context, the current
task owns the center, the inspector owns status and actions, and the Timeline Rail is the only
temporal index.

## 2. Target layout

Use this desktop hierarchy:

```text
+--------------------------------------------------------------------------+
| Compact top bar: Back | Recording | Stage tabs | Generated / Reviewed    |
+----------------------------------------------------+---------------------+
|                                                    | Progress            |
|                                                    | Primary action      |
|       Current task surface                         | Save state          |
|       Video, source frame, polygon editor,         | Current selection   |
|       identity crop, observation, or comparison   | Recording metadata  |
|                                                    | Lineage and history |
+----------------------------------------------------+---------------------+
| Timeline Rail: transport | playhead | task lanes | time | zoom           |
+--------------------------------------------------------------------------+
```

The top bar is navigation, not a landing-page header. It contains one compact recording label,
duration, stage tabs with status, and the generated/reviewed switch when it applies. Remove the
large `Recording pipeline` heading, accepted-video callout, separate stage-summary grid, and
repeated selected-stage heading from the working view.

The center is the largest region. It shows the source video by default. A task that needs a still
frame, polygon canvas, crop, observation, or comparison can replace or divide the source surface.
The task must keep enough source context to explain the current selection.

The right inspector has a stable order:

1. review or run progress;
2. one primary action and its blocker;
3. save, conflict, or execution state;
4. current item and task controls;
5. recording and accepted-video metadata; and
6. collapsed exact revision, run, lineage, diagnostic, and history details.

Show an active error or conflict next to the affected action. Do not hide it in collapsed metadata.
Remove the floating completion bar. Put `Complete reference` or `Publish corrected reference` in the
inspector when review is active. Other modes use the same slot for their one primary action.

The Timeline Rail stays at the bottom of the workspace. It contains transport, the current time,
the full recording range, a playhead, and stage-specific lanes. It must remain visible while the
center or inspector scrolls internally.

At widths below the desktop breakpoint, keep the task surface before supporting information. Put
the rail directly after the task surface and collapse the inspector into named disclosures. A
mobile page can scroll. It must not place stage summaries or metadata before the source surface.

## 3. Shared Timeline Rail

Create one `RecordingTimelineRail` component and one shared time-selection model. Do not keep a
different rail implementation in each editor.

The rail must:

- seek the accepted video and update the existing `t_us` URL state;
- select the nearest or directly activated stage item and update the existing `item` URL state;
- show the playhead and the complete recording duration with useful tick labels;
- use lanes for stage items, proposals, review state, coverage, and comparison outcomes as needed;
- support click, drag scrubbing, pointer capture, touch, keyboard item stepping, and play/pause;
- show an exact source-frame preview on pointer hover and keyboard focus;
- debounce preview requests, cancel stale requests, and reuse the existing exact-frame derived-view
  route without inventing a new cache or source contract;
- expose ordered item buttons, selection state, time, and review state to assistive technology; and
- preserve current stage shortcuts unless a documented rail shortcut replaces them.

The rail is the only temporal index. Remove the event table, resolved-frame lists, identity-card
lists, generated-result tables, analysis selection lists, and comparison outcome list when their
primary purpose is to select a time-bound item. Keep non-temporal run history and exact-input
history as inspector disclosures. The inspector can show `Item 3 of 12` and all fields for the
selected item without recreating a queue.

## 4. Stage composition

Generated and reviewed content use the same stage composition. Change marker style, available
actions, and metadata by origin and review state. Do not switch to a table-only layout for generated
content.

| Stage or mode      | Central task surface                                                         | Timeline Rail lanes                                      | Inspector focus                                                           |
| ------------------ | ---------------------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------- |
| Events             | Large source video with the selected event range                             | Events, proposals, review state, full-recording coverage | Start/end/type editing, add/accept/reject, save state, completion         |
| Visible cards      | Large exact source frame and polygon editor, with video available in context | Resolved frames, frame decision, proposal count          | Frame outcome, proposal actions, geometry controls, coverage, completion  |
| Visual identities  | Source frame and identity crop in one central comparison surface             | Identity source cards and review state                   | Candidate choice, unusable/source-problem actions, coverage, completion   |
| Table observations | Source video or exact frame with the selected observation summary            | Observation intervals and execution state                | Compatible inputs, assembly action, selected observation metadata         |
| Round analyses     | Video/evidence view synchronized with the selected analysis point            | Analysis evidence and reconstruction state               | Analysis selection, reconstruction action, result and diagnostic metadata |
| Comparison         | The selected source context with the compared outcomes together              | Differences and matches across the recording             | Left/right/reference selectors, matching policy, summary, exact inputs    |

Task controls that act directly on the visual surface can stay next to that surface. Status,
selection facts, and form fields that do not need spatial context belong in the inspector. Keep the
same placement across stages.

## 5. Presentation model and boundaries

Add a pure web presentation model between the existing API responses and the shared shell. It must
derive:

- compact stage-tab state and the current primary action;
- the displayed generated or reviewed revision;
- inspector sections and active blockers;
- source-surface mode and selected-item facts;
- normalized rail items, lanes, time ranges, state, and labels; and
- empty, loading, failed, draft, affected, and complete presentation states.

The browser URL remains the restorable selection state. Keep `stage`, `view`, `revision`, `item`,
`t_us`, comparison inputs, and selected analysis behavior from 0049. Sanitize unavailable values
against the loaded workspace as it does now.

Do not change:

- pipeline storage, data revisions, maintained-reference semantics, or review coverage;
- processor execution, comparison matching, analysis, or dataset eligibility contracts;
- accepted-video or derived-view authority;
- recording-list and iOS recording workflows; or
- model, detector, identity, or reconstruction quality.

Do not add compatibility wrappers for the replaced web components. Remove obsolete components,
styles, tests, and props after every stage uses the shared primitives.

## 6. Measurable layout acceptance

Use deterministic pipeline fixtures and test at least `1440 × 900`, `1280 × 800`, and a narrow
mobile viewport.

At both desktop sizes:

- the browser document has no vertical scrollbar in the loaded steady state;
- the compact top bar, current source surface, inspector progress and primary action, and complete
  Timeline Rail are visible at the same time;
- the top bar uses no more than `7rem` of vertical space;
- the task surface receives the remaining width after an inspector between `18rem` and `23rem`;
- the source video or frame is centered in the task surface and uses the available area without
  stretching its aspect ratio;
- the Timeline Rail is at least `6rem` high before an expanded preview or extra lanes;
- a 16:9 source video is not limited by an arbitrary `32rem` maximum when more center space exists;
- only the center detail overlay or inspector can scroll internally when content exceeds its area;
- no stage summary, temporal list, result table, or floating completion bar duplicates the same
  selection or progress; and
- loading, empty, blocked, saving, conflict, failed, draft, and completed states keep the shell
  stable and keep the source region in place.

At the narrow viewport:

- the compact top bar can wrap or scroll its stage tabs without expanding every tab into a card;
- the source surface appears before progress, metadata, history, and guidance;
- the rail remains a usable scrub and item-selection control;
- disclosures and controls have no horizontal overflow; and
- completion actions do not cover source content or rail controls.

For all viewports:

- every action and rail item is reachable by keyboard;
- focus remains on the selected item after save, retry, conflict recovery, view changes, and browser
  back/forward navigation;
- color is not the only indication of origin, status, comparison outcome, or review state;
- reduced-motion settings disable animated previews or transitions; and
- source-frame previews do not trigger an unbounded request stream.

## 7. Delivery milestones

### M0 — Shared presentation model and fixtures

- Add the pure presentation model for compact tabs, primary action, inspector sections, task mode,
  and normalized rail items.
- Cover representative video-only, generated, draft, completed, affected, failed, comparison, and
  analysis states without changing API contracts.
- Add reusable desktop and narrow browser fixtures and geometry helpers for later layout assertions.

Acceptance:

- presentation decisions have focused unit tests independent of rendering;
- every implemented pipeline stage maps to a task surface, inspector state, and rail state; and
- existing generated client and pipeline route tests pass unchanged.

### M1 — Viewport shell and compact top bar

- Add the shared top, center, inspector, and bottom slots.
- Replace the large heading, video-digest callout, duplicate stage summary grid, and selected-stage
  heading with the compact top bar.
- Preserve route navigation, stage status, generated/reviewed selection, notices, and active errors.
- Establish desktop viewport sizing and internal-scroll boundaries before migrating editor content.

Acceptance:

- the shell satisfies the desktop geometry checks with placeholder stage content;
- stage and view changes restore through direct URLs and back/forward navigation; and
- diagnostics remain visible when active without permanently reserving top-area height.

### M2 — Metadata inspector

- Add the inspector in the stable section order from this plan.
- Move progress, the primary action, blocker, selectors, accepted-video facts, save or execution
  state, exact inputs, lineage, diagnostics, and history into it.
- Give review completion and processor execution the same primary-action slot.
- Remove fixed completion bars and repeated metadata blocks after their information is available in
  the inspector.

Acceptance:

- every stage and state exposes its current progress, action, and blocker without searching the
  page;
- advanced metadata remains available but does not displace the source surface; and
- no action is duplicated between the shell, stage body, and inspector.

### M3 — Shared Timeline Rail and video synchronization

Status: Complete.

- Add the rail, transport, playhead, time ticks, lanes, selection model, and zoom appropriate for
  short and long recordings.
- Connect click, drag, touch, keyboard, video time, `item`, and `t_us` state in both directions.
- Add debounced hover and focus frame previews through the existing derived-view route.
- Add request cancellation, bounded preview caching, reduced-motion behavior, and accessibility
  labels.

Acceptance:

- one shared component covers every stage fixture without stage-specific time math;
- stale preview responses cannot replace the current preview;
- a selected item and playhead survive reload and back/forward navigation; and
- pointer, touch, keyboard, accessibility, and request-bound tests pass.

### M4 — Event workbench

Status: Complete (2026-09-06).

- The generated and reviewed event views now use the accepted recording video in the central task
  surface. The selected event editor keeps integer-microsecond corrections, ordered commands,
  retries, conflict recovery, keyboard shortcuts, and completion coverage.
- Generated proposals, maintained-reference events, review state, and full-recording coverage now
  use the shared Timeline Rail. Reviewed reference items hydrate into the rail after the existing
  reference resource loads. Rail selection restores `item` and `t_us` state and seeks the same
  source video.
- Event primary actions, operator and reviewer fields, save or conflict state, retry actions,
  coverage, and completion are mounted in the shared inspector. The fixed completion bar is gone.
- Removed the event-specific timeline, screenshot table, generated-result table, and screenshot
  capture path. Added regression coverage for the shared video, rail hydration, and duplicate-list
  removal.

Verification: `mise exec -- npm run check` in `web` passed. This includes typecheck, lint,
formatting, generated OpenAPI parity, and 67 unit/component tests.

- Put the accepted video in the central surface for generated and reviewed events.
- Represent generated proposals, maintained-reference events, state, and full-recording coverage in
  rail lanes.
- Put selected-event editing and add, accept, reject, remove, save, and completion actions in the
  shared task and inspector regions.
- Remove the event screenshot table and event-specific timeline implementation.

Acceptance:

- the existing event review command ordering, conflict recovery, coverage, and keyboard behavior
  remain intact;
- generated and reviewed event selection uses the same video and rail; and
- no event list or table duplicates rail navigation.

### M5 — Visible-card workbench

Status: Complete (2026-09-06).

- Generated and reviewed visible-card views now use one source-video context and selected exact
  frame surface. Polygon overlays and reviewed geometry editing keep the existing derived-frame and
  correction lineage.
- Resolved frames, frame decisions, and proposal counts now use the shared Timeline Rail for both
  generated and reviewed views. Rail selection restores `item` and `t_us` state.
- Frame outcomes, coverage, review completion, operator and reviewer fields, save or conflict state,
  and retry actions now use the shared inspector. The fixed completion bar is gone.
- Removed the resolved-frame list, generated-result table, and visible-card timeline. Added
  regression coverage for generated and reviewed rail hydration, exact-frame rendering, URL
  selection, and duplicate-list removal.

Verification: `mise exec -- npm run check` and `mise exec -- npm run build` in `web` passed.

- Make the selected exact source frame and polygon editor the central surface.
- Put resolved frames, decision state, and proposal count on rail lanes for generated and reviewed
  views.
- Move frame outcome, proposal editing, geometry controls, progress, save state, and completion into
  the shared task and inspector regions.
- Remove the resolved-frame list, generated-result table, and stage-specific timeline.

Acceptance:

- proposal overlays and polygon editing keep their current source and correction lineage;
- empty and unusable decisions stay distinct and coverage remains explicit; and
- pointer, keyboard, autosave, conflict, derived-frame, and cold-cache tests pass.

### M6 — Visual identity workbench

- Make the source frame and identity crop the central task surface.
- Put source cards and review state on rail lanes for generated and reviewed views.
- Move identity candidates, selection, unusable and source-problem actions, progress, save state, and
  completion into the shared inspector.
- Remove the identity-card list, generated-result table, and stage-specific timeline.

Acceptance:

- the source visible region, crop policy, candidates, and human decision remain distinguishable;
- unusable and failed visual identity outcomes remain distinct; and
- source-frame, crop, command ordering, keyboard, retry, conflict, and completion tests pass.

### M7 — Table-observation workbench

Status: Complete (2026-09-06).

- The table-observation stage now keeps the accepted source video in the central task surface.
  Selecting an observation interval in the shared Timeline Rail seeks that video and restores the
  selected observation and source time through `item` and `t_us` URL state.
- The rail now exposes observation intervals and their execution state without a second temporal
  list. The central summary shows the selected observation's source time, outcome, visible-card
  count, and analyzer capabilities.
- Compatible revision-set selection, exact frozen inputs, assembly progress, execution state,
  failure, retry, retained runs, and output metadata remain in the shared inspector.

Verification: `mise exec -- npm run check` and `mise exec -- npm run build` in `web` passed.

- Put selected table-observation source context in the center and its intervals on the rail.
- Put compatible input selection, assembly progress, execution, and result metadata in the
  inspector.

Acceptance:

- video-only observation assembly still uses exact revision sets;
- selection of an observation interval synchronizes the central source context and URL;
- incompatible inputs, loading, execution failure, retry, and completion remain distinct; and
- observation controls and pipeline component tests pass.

### M8 — Round-analysis workbench

Status: Complete (2026-09-06).

- The round-analysis stage now keeps the accepted source video in the central task surface.
  Analysis and reconstruction selection use two shared Timeline Rail lanes and restore the selected
  analysis and source time through `analysis` and `t_us` URL state.
- Exact observation input, rules version, execution state, retained history, and failures stay in
  the inspector. The compact inspector no longer contains a second selectable analysis list.
- A completed analysis opens its existing evidence and counterfactual workbench as a task-surface
  mode inside the shared shell.

Verification: `mise exec -- npm run check` and `mise exec -- npm run build` in `web` passed.

- Compose the existing round-analysis evidence and reconstruction state into the shared source
  surface, rail, and inspector.
- Move exact observation input, rules, execution, result, and diagnostic metadata into the
  inspector.
- Remove the analysis selection list and nested page-like panels that repeat workspace controls.
- Keep the counterfactual workbench as a task-surface mode inside the same shell.

Acceptance:

- analysis still uses exact table-observation revisions and rules versions;
- the selected analysis and time remain restorable in the URL;
- existing counterfactual behavior remains available without creating another top-level layout;
  and
- analysis loading, failure, retry, completion, timeline, and counterfactual tests pass.

### M9 — Comparison workbench

- Put the selected source context and compared outcomes in the center.
- Represent source-ordered matches and differences as rail lanes.
- Move left, right, and reference selectors, matching policy, reviewed scope, summary, and exact
  inputs into the inspector.
- Remove the source-ordered outcome list and comparison-specific page hierarchy.

Acceptance:

- event, visible-card, and visual-identity comparisons use the same selection and source controls;
- selecting a rail outcome seeks the accepted video or exact frame and updates the URL;
- missing reference, incompatible input, partial, empty, and failed states remain distinct; and
- comparison contract and component tests pass unchanged or with presentation-only updates.

### M10 — Responsive proof and cleanup

- Apply the shared spacing, type, panel, badge, button, field, focus, and state treatment to every
  migrated stage.
- Remove obsolete page, summary-card, list, table, timeline, and fixed-completion components and
  styles.
- Add desktop geometry, narrow layout, visual regression, accessibility, and keyboard workflow
  coverage for the complete recording pipeline.
- Exercise one fixture from accepted video through generated output, review completion, downstream
  run, analysis, and comparison.

Acceptance:

- all measurable layout acceptance in this plan passes at the three required viewports;
- the complete fixture workflow uses one shell, one inspector, and one Timeline Rail;
- web tests, browser tests, types, lint, formatting, production build, and local Markdown-link checks
  pass; and
- no obsolete review route or duplicate recording state is restored.

## 8. Implementation guardrails

- Keep milestones as presentation changes over the 0048 and 0049 contracts. Stop and revise this
  epic before adding a backend schema or persistence concept.
- Migrate one stage at a time. Do not maintain a permanent old/new layout switch.
- Keep the central source surface mounted when selection or inspector state changes. Avoid video
  reloads and lost playback position.
- Use existing source video and derived-view URLs. Never read repository paths in the browser.
- Preserve optimistic ordered review commands, idempotent retries, conflict recovery, and explicit
  completion coverage.
- Prefer removal after each migration. Do not hide duplicate lists with CSS while leaving them as a
  second interaction model.
- Keep quality measurement and model behavior in 0051, 0052, 0043, and 0050. This epic changes how
  operators inspect and control existing results.
