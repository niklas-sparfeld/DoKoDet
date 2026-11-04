# Epic 0105 M3: Recording Workspace Action

Date: 2026-11-04

## Result

The recording workspace inspector now provides one action to start the complete pipeline. It
loads the recording session and known game and round IDs. The operator enters four player IDs, the
dealer, and the first-trick leader. The form checks these facts before it sends the request.

The request uses the existing local stage settings when they are available. It uses local provider
defaults for visible-card and identity proposals. The backend validates provider and model
availability before it accepts a run. Rules version and search limits are visible in the form.

The workspace stores the accepted run ID in browser storage. It reads the durable status after
reload and polls while the run is active. It shows each stage, failure details, and links to the
existing stage views. A completed reconstruction links to its saved analysis.

This UI does not report execution success as reconstruction correctness. Browser storage restores
the latest run started in that browser for this recording. The backend remains the durable source
of run state.

## Verification

- `npm run typecheck` passed.
- `npm test -- src/pipeline/AutomatedPipelineControls.test.tsx src/api/client.test.ts` passed: 11
  tests.
- The compact workspace inspector test passed after its expected section list included the new
  action. Vitest also reported an unhandled `URL.createObjectURL` fixture error from the existing
  recording-video cache test setup. The full workspace test file has a separate failing URL-state
  expectation.
- ESLint and Prettier passed for all changed web source and test files. The full web lint command
  still reports two existing synchronous state updates in `CardEventFrameSurface.tsx` and one
  dependency warning in `VisibleCardReviewWorkbenchView.tsx`.

Browser fixtures verify missing round facts, one accepted start, restored status and stage links,
and a restored failed stage with its cause. M4 still needs to verify the complete local backend
fixture through the user-facing path.
