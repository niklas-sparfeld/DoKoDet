# CardEvent frame-review editor

## Plan status

- **Summary:** Replace the CardEvent review video with an exact source-frame work surface. Put
  event controls in a compact left sidebar. Keep the current right inspector unchanged.
- **Status:** Closed
- **Depends on:** Plans 0049, 0054, and 0062 complete
- **Builds on:** The shared Timeline Rail, exact source-frame derived view, and CardEvent review
  command queue
- **Outcome:** An operator reviews one CardEvent at a time with a large borderless exact source
  frame. The left sidebar shows the frequent controls and their shortcuts. The existing right
  inspector continues to own progress, save state, completion, and metadata.
- **Closure reason:** Complete
- **Reviewed:** 2026-09-11 against the current CardEvent editor and the visible-card and visual
  identity frame editors.

## Milestone status

- **M0:** Complete — the reviewed editor uses the recording-owned exact source-frame surface with
  selection, playhead, retained-frame, unavailable, and request-failure states.
- **M1:** Complete — move frequent CardEvent controls to the left sidebar and remove repeated
  central UI.
- **M2:** Complete — prove the simplified editor at desktop and narrow sizes with keyboard and
  accessibility coverage.

## 1. Purpose

The CardEvent editor still uses a video element as its main surface. Its selected-event form and
action buttons sit beside the video. It also repeats headings, counts, labels, help, and other
supporting content in the center.

The visible-card and visual-identity editors use an exact source frame for the selected work item.
Use the same rule for CardEvent review. A CardEvent reviewer needs to see the first clear frame for
the selected event and make a small set of fast decisions. The editor must make that task clear.

The target desktop layout is:

```text
+----------------------+-----------------------------------------+----------------------+
| Left controls        | Exact source frame                      | Existing inspector   |
| Previous       Left  | Borderless. Largest available surface.  | Unchanged            |
| Next          Right  |                                         |                      |
| Nudge earlier      , |                                         |                      |
| Nudge later       . |                                         |                      |
| Accept             A |                                         |                      |
| Dismiss           D |                                         |                      |
| Add event         N |                                         |                      |
+----------------------+-----------------------------------------+----------------------+
| Shared Timeline Rail                                                       |
+----------------------------------------------------------------------------+
```

The key is right aligned inside a compact pill on each applicable button. For example, the accept
button reads `Accept` with `A` at its right edge. The button remains a normal accessible button;
the pill is not a separate control.

## 2. Scope

This epic includes:

- the reviewed CardEvent editor source surface and its selected exact source frame;
- a compact left control sidebar for previous, next, nudge earlier, nudge later, accept, dismiss,
  and add-event actions;
- visible shortcut pills on those controls;
- the existing shortcuts: `Left`, `Right`, comma, period, `A`, `D`, and `N`;
- a borderless central frame that uses available workspace area without a decorative card,
  panel, or video controls;
- removal of repeated headings, counts, labels, shortcut disclosure, and other central content
  that does not help the current review decision;
- exact-frame loading, stale-response, missing-frame, and request-failure states; and
- focused component and browser regression coverage.

This epic does not include:

- changes to event types, event timing, review commands, source lineage, completion rules, or the
  ordered save queue;
- a change to the shared Timeline Rail or its lanes;
- a redesign, move, cleanup, or content change to the right inspector;
- changes to generated event results, model execution, or proposal selection rules;
- video playback inside the CardEvent editor; or
- a general editor design system or a cleanup of other sidebars.

## 3. Fixed decisions

1. The reviewed CardEvent editor shows an exact source frame at the current selected event time.
   When no event is selected, it shows the exact source frame at the current Timeline Rail time.
   It does not render a video element in the editor.
2. Reuse the existing recording exact-frame derived-view route and its accepted-source lineage.
   Do not add a second frame cache, extraction route, or CardEvent-specific frame contract.
3. A selection, Timeline Rail seek, left/right action, or nudge changes the requested frame time.
   Cancel or ignore stale frame responses. Keep the last valid frame visible while a replacement
   loads, and expose the new requested time to assistive technology.
4. Keep the existing action meanings and shortcuts. `Left` and `Right` seek by 250 ms. Comma and
   period nudge the selected event by one source frame. `A` accepts, `D` dismisses, and `N` adds an
   event at the current time. Do not run a shortcut while focus is in a text input or another
   editable control.
5. The left sidebar contains only the frequent controls. Show the action text on the left and its
   shortcut on the right in a compact pill. Disabled actions retain their existing reason through
   accessible text or tooltip. Do not make a disabled keyboard hint look actionable.
6. Previous and next use the existing event-marker navigation. They remain available as visible
   controls even though their keyboard behavior is currently `Alt+Left` and `Alt+Right`; show those
   exact shortcut pills. The plain `Left` and `Right` buttons are temporal seek controls, not event
   navigation controls.
7. The central surface has no border, rounded card, duplicate section heading, count block,
   details form, shortcut disclosure, or instructional copy. Keep only the frame and minimal
   non-redundant state needed to understand loading or failure.
8. Keep selected-event fields, progress, save/conflict state, completion controls, review status,
   and metadata where they currently belong in the right inspector. This epic must not change that
   inspector's visual structure or ownership.
9. At narrow widths, show the frame before the left controls and right inspector. The control
   sidebar can become a compact wrapped control row after the frame. Do not introduce page-level
   horizontal scrolling.
10. Preserve all existing CardEvent review commands, URL selection state, optimistic local
    updates, conflict recovery, and keyboard behavior. This is a presentation change only.

## 4. Delivery milestones

### M0 — Add the exact CardEvent frame surface

- Add a focused CardEvent frame-surface component that resolves the current requested time through
  the existing exact source-frame derived view.
- Connect selection, Timeline Rail time, seek, and event nudge updates to that requested time.
- Remove the editor video element and its playback dependency from reviewed CardEvent review.
- Add clear loading, retained-last-frame, unavailable-frame, and request-failure states.

Acceptance:

- selecting an event displays its exact source frame at the effective event time;
- a Timeline Rail seek updates the frame without a video element or video controls;
- rapid time changes cannot replace the current frame with a stale response;
- missing or failed frames do not hide the requested time or corrupt review state; and
- generated API and focused component checks pass.

#### M0 implementation evidence — 2026-09-11

- Added `CardEventFrameSurface` and reused `pipelineDerivedFramePath` for the recording-owned
  exact source-frame request.
- Added abort and sequence checks so an older response cannot replace a newer requested time.
- Kept the last valid frame visible while a replacement loads or fails. Exposed requested and
  displayed times through image alternative text, status text, and stable data attributes.
- Replaced the reviewed editor video surface and media-event coverage tracking with the exact
  frame surface and the existing selection/playhead path. Generated results still use their
  existing read-only video surface.
- Added focused tests for route resolution, stale responses, retained frames, unavailable frames,
  request failures, and the reviewed editor's no-video contract.
- Verification passed: `mise exec -- npm run typecheck`, `mise exec -- npm run lint`,
  `mise exec -- npm run format`, `mise exec -- npm test`, `mise exec -- npm run verify:api`, and
  `mise exec -- npm run build` from `web`.

#### M1 implementation evidence — 2026-09-11

- Added a compact reviewed-mode control sidebar for previous/next event navigation, 250 ms seek,
  one-frame nudge, accept, dismiss, and add-event actions. Each button has a visible shortcut
  pill and an accessible action-plus-shortcut name.
- Reused the existing selection, seek, nudge, decision, add, optimistic-update, and ordered-save
  handlers. Previous and next retain their Alt+Left and Alt+Right marker navigation; plain Left
  and Right seek the playhead by 250 ms.
- Removed the central selected-event form, count header, keyboard-help disclosure, and review
  instruction. The existing workspace inspector still owns counts, selection, progress, save
  state, completion, and metadata.
- Added responsive ordering so the exact frame precedes the controls at narrow widths. Disabled
  controls keep an accessible reason, and disabled shortcut pills do not look actionable.
- Verification passed: `mise exec -- npm run lint`, `mise exec -- npm run format`,
  `mise exec -- npm test`, and `mise exec -- npm run build` from `web`.

### M1 — Create the compact control sidebar

- Add the left sidebar with previous, next, seek, nudge, accept, dismiss, and add-event controls.
- Render each shortcut as a right-aligned pill inside its action button.
- Reuse existing handlers and disabled rules. Do not change command payloads or save ordering.
- Remove the selected-event card, central count header, keyboard-help disclosure, and redundant
  explanatory text from the central editor region.
- Keep the existing right inspector unchanged.

Acceptance:

- every required action has a visible button and its documented shortcut pill;
- clicking a button and using its shortcut produce the same existing command or navigation result;
- the central frame is borderless and is the largest visual element;
- accept, dismiss, and add remain distinguishable by review state and enabled state; and
- no duplicated action, count, status, or metadata block remains in the center.

### M2 — Verify responsive and accessible review

- Add desktop and narrow browser fixtures for pending, accepted, dismissed, manual, no-selection,
  loading, and failed-frame states.
- Verify keyboard focus order, button names, shortcut text, frame alternative text, and status
  announcements.
- Verify that the current right-inspector output is unchanged by this epic.
- Run the relevant frontend type, lint, build, unit, and browser checks.

Acceptance:

- at `1440 x 900`, the left controls, borderless frame, Timeline Rail, and existing right inspector
  are visible without page-level horizontal scrolling;
- at `390 x 844`, the frame comes before controls and supporting information, and no control is
  clipped;
- keyboard workflows for seek, marker navigation, nudge, accept, dismiss, and add still pass;
- rapid frame changes, save retry, and conflict recovery retain their current behavior; and
- the CardEvent editor has no video element in reviewed mode.

#### M2 implementation evidence — 2026-09-11

- Added Playwright fixtures for pending, accepted, dismissed, manual, no-selection, loading, and
  failed-frame reviewed states. The fixtures use the recording-owned pipeline, maintained
  reference, exact-frame, and draft-update routes.
- Added desktop and narrow geometry checks for the borderless frame, left controls, existing right
  inspector, shared Timeline Rail, page bounds, and narrow frame-first ordering. All shortcut
  buttons are checked for visible pills, accessible names, and keyboard focus order.
- Added browser checks for exact-frame alternative text, live status announcements, all review
  commands, repeated frame requests, and the absence of a video element in the reviewed task
  surface. The focused editor tests continue to cover save retry and revision-conflict recovery.
- Verification passed: `mise exec -- npm run typecheck`, `mise exec -- npm run lint`,
  `mise exec -- npm run format`, `mise exec -- npm test` (150 tests), and
  `mise exec -- npm run test:e2e` (12 tests, including a fresh production build) from `web`.

## 5. Verification

For each milestone, run the focused CardEvent editor and workspace presentation tests. Run the
generated API check when the frame route is consumed through generated types. Before closure, run
the web type, lint, build, and browser checks declared by the repository. Test a cold exact-frame
request, a cached request, a rapid selection change, and a source-frame failure.
