# 0109 M7 analysis integration

Date: 2026-11-07

## Result

Round analysis uses the shared still-frame surface in the center. The old central source-video and
workbench toggle is removed. The Timeline Rail lists evidence, observation, inferred-play, and
hypothesis choices. The inspector shows the selected analysis and row details.

Selecting an evidence row selects the row and moves the workspace cursor to its event time. The
frame service loads the sampled source frame for that cursor. The rail marks the selected row.
Selecting an inferred play keeps the current cursor. The UI labels the inferred play as untimed and
does not draw geometry for it. The selected analysis, row, hypothesis, and source time remain in the
URL and restore after reload.

## Verification

- `cd web && npm run check` passed: typecheck, ESLint, Prettier, generated API comparison, and 196
  frontend tests.
- `cd web && npm run build` passed. Vite reports the existing bundle-size warning.
- `cd web && npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts --reporter=line`
  passed. The browser check covers the shared frame, evidence row selection, hypothesis selection,
  reload restoration, and no video in the center. It also checks the existing desktop and narrow
  workspace layouts.
- Generated API output did not change. M7 adds no backend API or persisted write.
- Local Markdown links in the epic, board, and report resolve.

## Decisions and limits

Evidence event time is the source cursor for a linked row. Inferred plays do not have an exact source
time or geometry, so they do not move the cursor or create pixels. The analysis timeline has no
exact geometry contract. The center shows the source frame without card polygons.

This milestone changes browser view selection only. It adds no persistence behavior, so no
disposable persistence workflow applies. The browser fixture does not establish real-recording
quality.

## Next

M8 relocates counterfactual and comparison functions.
