# 0112 M7 workspace loading and selection

## Result

M7 is complete. `RecordingPipelineWorkspace.tsx` is a 469-line composition root. Workspace and
lineage loading live in `useRecordingPipelineData.ts`. URL state and selection commands live in
`useRecordingPipelineSelection.ts`; pure URL sanitization and initial-stage choice live in
`recordingPipelineSelection.ts`. The workspace owns one URL selection state. No job polling moved
into these modules.

Workspace requests carry a sequence number. A response can update state only when it is still the
newest request and its recording ID matches the current recording. A completed workspace for one
recording does not satisfy a same-stage request for another recording. The workspace shows its
loading state until the new recording loads. Root-route stage selection waits for the matching
recording workspace. Lineage graphs, errors, and validation notices are exposed only for the
recording that requested them. Abort signals still cancel recording and graph requests. This also
prevents an older refresh response from replacing newer workspace data.

## Coverage

`useRecordingPipelineData.test.tsx` covers stale recording responses, completed-load same-stage
recording switches, stale stage responses, overlapping refreshes, and graph errors. The workspace
suite verifies that a recording switch shows loading instead of the prior recording and that a root
route selects its initial stage from the new recording. A delayed graph test verifies that the new
recording does not receive the prior graph while loading. The other workspace suites cover deleted
lineage nodes, invalid saved URLs, URL restoration, exact selected revisions after a selection
conflict, and the composed workspace. The workspace tests are split into focused files; each remains
within the 800-line test budget. The composition root and each new production module meet their line
budgets.

## Checks

From `web/`:

- `npx eslint src/pipeline/RecordingPipeline*.test.tsx src/pipeline/RecordingPipelineWorkspace.tsx src/pipeline/recordingPipelineSelection.ts src/pipeline/useRecordingPipelineData.ts src/pipeline/useRecordingPipelineSelection.ts src/pipeline/useRecordingPipelineData.test.tsx` — passed.
- `npm run typecheck` — passed.
- `npm test -- --run src/pipeline/RecordingPipelineWorkspace.test.tsx src/pipeline/RecordingPipelineWorkspacePresentation.test.tsx src/pipeline/RecordingPipelineWorkspaceSelection.test.tsx src/pipeline/RecordingPipelineSelectionIntegration.test.tsx src/pipeline/useRecordingPipelineData.test.tsx` — 41 tests passed.
- `npx prettier --check` on the changed workspace and test files — passed.

During integration with 0113, these workspace suites mock `AutomatedPipelineControls` so they test
workspace loading and selection without the shared `JobStateProvider` required by the launch
controls. The launch controls keep their own provider-wrapped tests.

No API or persisted-data contract changed. M8 and M9 remain.
