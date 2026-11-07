# Epic 0109 M9 — Accessibility and layout cleanup

## Result

M9 completes keyboard and visual focus checks for geometry selection, distinguishes geometry
layers by line pattern, moves frame loading and failure messages for observations and round
analysis into the inspector, and removes the unused Events video surface and its frame and video
caches.

Geometry polygons keep their accessible names and button semantics. Enter and Space select a
focused shape. Focus has a visible high-contrast stroke. Visible regions use a solid line, pile
regions and observed source geometry use dashed lines, and ignore regions use dotted lines. These
patterns add a visual distinction when color is not available.

The browser check verifies that the identity crop and source remain separate at desktop and
390-pixel layouts. Focusing the crop hides other inspector sections while keeping the source
visible. The step navigation remains horizontally scrollable on narrow screens.

## Removed implementation

Search found no runtime import of `CardEventFrameSurface`. Its only consumers were its own tests.
The shared still-frame loader replaced it. M9 removes the unused surface, its tests, and the
`cardEventFrameCache` and `recordingVideoCache` modules and tests. M3 event-editor CSS for that
surface is also removed. Other source-video uses remain in the Timeline Rail and processing
controls.

## Verification

- `cd web && npm run check` — passed: type check, lint, formatting, generated API comparison, and
  187 frontend tests.
- `cd web && npm run build` — passed. Vite reports the existing 518 kB JavaScript chunk warning.
- `cd web && npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts` — passed, 3 tests.
  The browser check verified an empty center for identity and analysis states, no center video or
  controls, crop focus, source and inspector separation at desktop and 390 pixels, and saved
  analysis selection.
- API generation reported that the temporary processor-run catalog root was unavailable. The
  generated OpenAPI comparison still passed; this warning did not change API output.

## Limits

This milestone does not run a full assistive-technology audit. The all-step browser regression and
closeout checks remain in M10.
