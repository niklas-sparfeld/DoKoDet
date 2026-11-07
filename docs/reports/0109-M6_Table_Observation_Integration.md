# 0109 M6 table observation integration

Date: 2026-11-07

## Result

Table observations use the shared still-frame surface. The center has no video or controls. The
Timeline Rail lists observations from the exact selected node revision. The inspector shows the
selected observation, its cards and identity candidates, capabilities, status, and exact spatial
source links.

The inspector resolves visible-card source revisions only through the selected observation
revision's exact lineage edges. It draws a polygon only when the observation card, source event,
source video digest, requested and resolved times, frame index, dimensions, and image digest match
the loaded still frame. A source mismatch or missing polygon does not create a substitute shape.
Multiple linked source revisions are selectable in the inspector. This selection changes only the
view.

The workspace keeps observed zero-card results distinct from failed and insufficient-evidence
results. It reports a missing observation within its selected revision without falling back to a
different revision. An observation without exact source-frame identity stays interval evidence.
Selecting it does not replace the current time with its observed-at timestamp.

## Verification

The code and this report are committed together in the M6 milestone commit.

- `cd web && npm run check` passed: TypeScript, ESLint, Prettier, generated API comparison, and 195
  frontend tests.
- `cd web && npm run build` passed. Vite reports the existing bundle-size warning.
- `cd web && npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts --reporter=line`
  passed. The regression checks the shared workspace layout at desktop and narrow widths. At desktop
  size it also checks Table observation interval selection, exact linked geometry, and a center with
  no video, text, or controls.
- Focused observation and workspace tests passed: 40 tests across three files. They cover missing
  items, failed and partial attempts, zero-card, failed and insufficient-evidence results, multiple
  sources, interval-only selection, and retained exact-revision item selection.
- Generated API output was unchanged. The milestone adds no backend API or persisted write.
- Local Markdown links in the epic, board, and report resolve.

## Decisions and limits

The selected node revision remains authoritative. Its exact lineage edges define the available
spatial sources. The browser does not edit observation or source data. Interval-only inspection
preserves the workspace time cursor and shows no overlay. No persistence workflow applies because
the milestone changes browser view state only.

Evidence is based on deterministic component fixtures and the local Playwright browser fixture.
It does not claim real-recording geometry quality or backend persistence behavior.

## Next

M7 integrates analysis evidence and hypotheses.
