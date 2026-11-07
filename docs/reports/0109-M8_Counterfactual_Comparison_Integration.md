# 0109 M8 counterfactual and comparison integration

Date: 2026-11-07

## Result

Exact run comparison now uses two instances of the shared still-frame renderer in the center. Both
surfaces load the exact source time for the selected comparison outcome and validate the recording
digest and returned frame identity through the shared frame service. The comparison center has no
video or command controls.

Run-pair selectors, the completed reference selector, comparison metrics, failures, selected
outcome details, and exact run, reference, frame, and derived-view references remain in the
inspector. URL state retains the selected immutable pair and outcome. Counterfactual controls and
their immutable result comparison remain in the analysis inspector. Existing correction behavior
is unchanged.

## Verification

- Focused tests passed: `cd web && npm test -- --run src/pipeline/ComparisonView.test.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx` (27 tests).
- `cd web && npm run check` passed: TypeScript, ESLint, Prettier, generated API comparison, and 196 frontend tests.
- `cd web && npm run build` passed. Vite reported the existing bundle-size warning.
- `cd web && npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts --reporter=line` passed (3 tests). The new browser case checks two shared exact-frame surfaces, the inspector outcome facts, and no video or controls in the center. Existing cases check M7 selection, reload, and workspace layout.
- Generated API output did not change. The comparison request calculates from immutable run and reference revisions and does not write retained data. No disposable persistence workflow applies.
- Local Markdown links in the epic, board, and this report resolve.

## Decisions and limits

The selected outcome's exact source time drives both still-frame surfaces. The comparison is read-only.
The surfaces use the shared frame service and show source pixels; they draw no geometry unless a
future comparison contract supplies geometry with an exact frame identity. The inspector retains the
existing comparison result and source references.

Counterfactual commands and results are already portaled into the analysis inspector in the M7
workspace. M8 preserves that placement and does not change correction constraints or calculation
behavior. The browser fixtures do not establish real-recording geometry quality.

## Next

M9 completes accessibility and layout cleanup.
