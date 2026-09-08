# Web workspace module boundaries

## Plan status

- **Summary:** Give each recording workspace responsibility a small local source, style, and test
  surface without changing the operator workflow.
- **Status:** Closed
- **Depends on:** 0053 discovery complete
- **Outcome:** An operator UI change can start at the owning workspace surface instead of requiring
  the recording workspace host, all three stage editors, and the shared stylesheet.
- **Closure reason:** Complete
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## M0 evidence and boundary decision

The 0053 count remains valid. Excluding generated `web/src/api/openapi.ts`, the web source has
26,431 lines. `web/src/App.module.css` has 5,846 lines and 920 top-level class selectors. These
non-generated source or test files have at least 1,000 lines:

| Surface | Lines | Mixed responsibilities | Existing focused proof |
| --- | ---: | --- | --- |
| `pipeline/RecordingPipelineWorkspace.tsx` | 1,723 | route and URL state, workspace loading, stage selection, Timeline Rail data, shell, inspector, and history | `RecordingPipelineWorkspace.test.tsx` |
| `cardEvents/PipelineCardEventEditor.tsx` | 1,843 | maintained-reference command state, inspector portals, source video, generated result, and rail items | `PipelineCardEventEditor.test.tsx` |
| `visibleCards/PipelineVisibleCardEditor.tsx` | 2,096 | maintained-reference command state, inspector portals, frame geometry, proposal overlay, and rail items | `PipelineVisibleCardEditor.test.tsx` |
| `visualIdentities/PipelineVisualIdentityEditor.tsx` | 1,847 | maintained-reference command state, inspector portals, source surface, item panel, and rail items | `PipelineVisualIdentityEditor.test.tsx` |
| `analysis/AnalysisView.tsx` | 1,715 | analysis status, synchronized timeline, source video, evidence detail, explanation, and formatting helpers | `roundAnalysisFixture.ts` consumers and workspace tests |
| `pipeline/ObservationAndAnalysisControls.tsx` | 1,001 | observation command state, round-analysis command state, history, status, and URL construction | `ObservationAndAnalysisControls.test.tsx` |

The recording workspace imports all three editors, run controls, the Timeline Rail, comparison,
observation, and analysis workbenches. It owns recording-wide selection, loaded workspace data, URL
state, and Timeline Rail aggregation. A stage editor owns local draft, save, retry, and
selected-item state; it reports rail items upward but does not own recording-wide state.

Recent 0054 commits confirm the seams. Stage changes repeatedly co-changed one editor with
`RecordingPipelineWorkspace.tsx`; event and visible-card changes also changed `App.module.css` and
their adjacent test. Responsive and comparison changes co-changed the workspace host, its tests,
comparison, presentation helpers, and the stylesheet. This supports moving existing cohesive
surfaces and their selectors, not adding pass-through wrappers or duplicating state.

The main consumers use 98 selectors in `AnalysisView`, 51 in the visual identity editor, 43 in the
workspace host, 41 in the visible-card editor, and 35 in the event editor. Move only selectors used
by a moved surface. Keep genuinely shared tokens and controls in the root stylesheet until a
consumer-specific move proves ownership. Do not rename selectors only to make their origin visible.

The browser boundary proves the completed 0054 shell at 1440px, 1280px, and 390px. It checks shell
dimensions, narrow viewport overflow, centre/inspector/Timeline Rail order, fresh, generated,
failed, affected, reload, and conflict flows. Retain it as the layout and workflow guard while
focused tests move with their responsibility.

## Milestone status

- **M0:** Complete — measured ownership, co-change, style, and verification seams; replaced the
  outline with delivery milestones.
- **M1:** Complete — extracted and tested route and URL-state helpers from the recording workspace;
  preserved existing URL shapes and canonical recording redirects.
- **M2:** Complete — isolated the recording workspace shell, inspector/history, and recording-wide
  Timeline Rail coordination surfaces.
- **M3:** Complete — give the event stage editor local source, generated-result, inspector, and
  presentation ownership.
- **M4:** Complete — give the visible-card stage editor local frame and inspector ownership.
- **M5:** Complete — give the visual-identity stage editor local source and inspector ownership.
- **M6:** Complete — separate observation and round-analysis command state, status/history
  presentation, and the local analysis URL helper.
- **M7:** Complete — separate analysis timeline/source-detail presentation from analysis
  formatting and data-reading helpers.

## Delivery milestones

### M1 — Recording route and URL state

Move route parsing, URL-state parsing, and path construction from
`pipeline/RecordingPipelineWorkspace.tsx` into one responsibility-focused pipeline helper module.
Keep the existing exports or update only in-package consumers. Do not change any URL shape.

Acceptance checks:

- Unit tests cover valid recording, stage, comparison, selection, analysis, and invalid route states.
- `npm run check` passes.
- The pipeline browser test opens the fresh recording at its canonical stage URL.

#### M1 implementation evidence — 2026-09-07

- Added `pipeline/recordingPipelineUrl.ts` as the focused owner of stage keys, route parsing, URL
  state parsing, and task/comparison path construction.
- Updated the app, comparison view, workspace, and tests to import the focused URL boundary. The
  workspace no longer owns route parsing or query serialization.
- Added 13 URL regression cases for valid and invalid routes, encoded selection and analysis state,
  and task/comparison query filtering.
- `npm run check` passed with 85 tests. The pipeline browser suite passed all four tests.

### M2 — Recording workspace host surfaces

Split the recording-wide host into cohesive workspace shell, inspector/history, and recording-wide
state/Timeline Rail coordination surfaces. Keep loaded `PipelineWorkspace`, stage selection, URL
state, and aggregated Timeline Rail items at the recording workspace boundary. Move exclusively
used styles with their surface, preserving shared selectors and computed layout behavior.

Acceptance checks:

- Focused workspace tests cover loading, selection conflict recovery, stage navigation, inspector
  history, and Timeline Rail item aggregation.
- `npm run check` passes.
- The pipeline browser test preserves 1440px, 1280px, and 390px shell bounds and ordering.

#### M2 implementation evidence — 2026-09-07

- Added focused shell, task-surface, inspector/history, status, formatting, navigation, and
  Timeline Rail coordination modules. The host now keeps loaded workspace data, stage selection,
  URL state, and the composition boundary.
- Moved workspace-only shell, inspector, history, and Timeline Rail wrapper styles into colocated
  CSS modules. Shared editor selectors remain in `App.module.css`.
- Added direct rail aggregation tests for event coverage, visible-card decisions and proposals,
  and visual identity review lanes. Existing workspace tests continue to cover loading, stage
  navigation, inspector history, selection conflict recovery, and shared rail selection.
- `npm run check` passed with 89 tests. The pipeline browser suite passed all four viewport and
  workflow tests.

### M3 — Event stage ownership

Extract the event editor's source video, generated-result, and inspector portal surfaces with local
state helpers and exclusively used styles. Keep maintained-reference commands, selected event, and
rail-item callback behavior unchanged.

Acceptance checks:

- Focused event tests cover draft save, retry, generated selection, inspector selection, and rail items.
- `npm run check` passes.
- The pipeline browser test still covers generated suggestions, failed jobs, reload, and conflict recovery.

#### M3 implementation evidence — 2026-09-08

- Added focused event types, formatting, source/generated presentation, inspector portal, and CSS
  module boundaries. The editor keeps maintained-reference commands, selected event state, and
  Timeline Rail callbacks at the editor boundary.
- Removed event-only review-panel, form, frame-readout, and action selectors from `App.module.css`;
  shared selectors remain available to the other stage editors.
- Added focused assertions for draft save and retry/conflict behavior, generated selection,
  inspector selection, and Timeline Rail item callbacks.
- `npm run check` passed with 93 tests. The pipeline browser suite passed all four tests, including
  generated suggestions, failed jobs, cold reload, conflict recovery, viewport bounds, and retired
  route handling.

### M4 — Visible-card stage ownership

Extract the visible-card editor's frame, geometry/proposal overlay, and inspector portal surfaces
with local state helpers and exclusively used styles. Keep maintained-reference commands, selected
frame, source-frame mapping, and rail-item callback unchanged.

Acceptance checks:

- Focused visible-card tests cover draft save, retry, selection, geometry/proposal presentation, and rail items.
- `npm run check` passes.
- The pipeline browser test opens the affected visible-card review state in the workspace inspector.

#### M4 implementation evidence — 2026-09-08

- Added focused visible-card types, formatting, frame/proposal presentation, inspector portal, and
  CSS module boundaries. The editor keeps maintained-reference commands, selected frame state,
  source-frame mapping, and Timeline Rail callbacks at the editor boundary.
- Added explicit local styles for the visible-card workbench, frame canvas, proposal list, geometry
  editor, inspector state, coverage, and error surfaces. Removed the extracted frame, overlay,
  proposal, and inspector selectors from `App.module.css`; shared visual-identity selectors remain.
- Focused tests cover draft geometry save, transient retry, explicit generated-frame selection,
  geometry/proposal presentation, and Timeline Rail items.
- `npm run check` passed with 95 tests. The pipeline browser suite passed all four tests, including
  the affected visible-card workspace inspector flow.

### M5 — Visual-identity stage ownership

Extract the visual-identity editor's item panel, source surface, and inspector portal surfaces with
local state helpers and exclusively used styles. Keep maintained-reference commands, selected
identity, identity outcome presentation, and rail-item callback behavior unchanged.

Acceptance checks:

- Focused visual-identity tests cover draft save, retry, selection, outcome presentation, and rail items.
- `npm run check` passes.
- The pipeline browser test opens a workspace without requests to retired review routes.

#### M5 implementation evidence — 2026-09-08

- Added focused visual-identity types, formatting, source/crop presentation, inspector portal,
  and CSS module boundaries. The editor keeps maintained-reference commands, selected identity
  state, and Timeline Rail callbacks at the editor boundary.
- Moved identity-only source, crop, proposal, decision, inspector, and reviewer styles out of
  `App.module.css`; shared controls remain in the root stylesheet.
- Focused tests cover generated selection, Timeline Rail items, draft save, transient retry,
  outcome presentation, and the visible-card geometry-review link.
- `npm run check` passed with 97 tests. The pipeline browser suite passed all four tests, including
  retired route handling and the workspace shell workflows.

### M6 — Observation and round-analysis controls

Split observation and round-analysis command forms, status/history presentation, and their local
URL helper from `ObservationAndAnalysisControls.tsx`. Keep command state in its control surface.
Do not move analysis rendering or alter processor requests.

Acceptance checks:

- Focused controls tests cover command validation, run state, history, and analysis-path creation.
- `npm run check` passes.
- The pipeline browser test preserves fresh and failed processor workflows.

#### M6 implementation evidence — 2026-09-08

- Split observation command state and run presentation into `ObservationRunControls.tsx`,
  `ObservationRunFormatting.ts`, and `ObservationRunPresentation.tsx`.
- Split round-analysis command state and status/history presentation into
  `RoundAnalysisControls.tsx`, `RoundAnalysisFormatting.ts`, and
  `RoundAnalysisPresentation.tsx`. Command state remains local to each control surface.
- Moved analysis path construction into `roundAnalysisUrl.ts`. Processor requests and analysis
  rendering contracts remain unchanged; the old module is now a small in-package export bridge.
- Focused controls tests cover incomplete context validation, completed run state, failed-run
  history and retry, search-limit validation, and encoded analysis paths.
- `npm run check` passed with 100 tests. The pipeline browser suite passed all four tests.

### M7 — Analysis presentation ownership

Separate analysis timeline/source-detail presentation from pure formatting and data-reading helpers
in `AnalysisView.tsx`; colocate exclusively used styles and tests. Keep the selected analysis
contract, synchronized timeline, evidence detail, counterfactual controls, and source video behavior.

Acceptance checks:

- Focused analysis tests cover timeline selection, evidence detail, formatting helpers, and counterfactual inputs.
- `npm run check` passes.
- The pipeline browser test passes at 1440px, 1280px, and 390px.

#### M7 implementation evidence — 2026-09-08

- Reduced `analysis/AnalysisView.tsx` to an in-package compatibility entry point. The selected
  analysis loader and timeline/source-detail presentation now live in
  `AnalysisTimelinePresentation.tsx`.
- Moved display-row construction, URL selection readers, reconstruction data snapshots, action
  readers, and formatting helpers into `analysisFormatting.ts`. The counterfactual workbench now
  imports this local analysis boundary directly.
- Added focused analysis tests for synchronized row and hypothesis selection, evidence detail
  media, counterfactual classification input, display-row data, and formatting helpers.
- Preserved the selected analysis contract, synchronized timeline, source recording seek behavior,
  evidence detail overlay, and counterfactual controls.
- `npm run check` passed with 106 tests. The pipeline browser suite passed all four tests, including
  the 1440px, 1280px, and 390px shell checks.

## Dependencies, exclusions, and execution rules

0053 is complete, so this epic has no unmet dependency. Complete M1 and M2 first to stabilize the
recording-wide boundary. M3 through M5 follow M2 and must not create a shared editor framework. M6
and M7 can follow M2 independently but remain separate Luna phases.

Preserve the completed 0054 viewport shell, central source surface, workspace inspector, and
Timeline Rail. Do not change operator behavior, URLs, accessibility semantics, API contracts,
persistence, generated `web/src/api/openapi.ts`, or the generated-client boundary. Do not add 0051
identity-quality behavior. Do not redesign the recording pipeline, comparison, or analysis workflow.

Do not create a component only to forward props. Each move must leave a responsibility with local
state, markup, styles, or focused tests. If a milestone requires duplicated state or selector-order
changes, stop it and record the evidence in this epic before selecting the next milestone.
