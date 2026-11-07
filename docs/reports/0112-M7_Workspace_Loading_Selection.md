# 0112 M7 workspace loading and selection

## Result

M7 is complete. `RecordingPipelineWorkspace.tsx` is a 476-line composition root. Workspace and
lineage loading live in `useRecordingPipelineData.ts`. URL state and selection commands live in
`useRecordingPipelineSelection.ts`; pure URL sanitization and initial-stage choice live in
`recordingPipelineSelection.ts`. The workspace owns one URL selection state. No job polling moved
into these modules.

Workspace requests carry a sequence number. A response can update state only when it is still the
newest request and its recording ID matches the current recording. A completed workspace for one
recording does not satisfy a same-stage request for another recording. The workspace shows its
loading state until the new recording loads. Root-route stage selection waits for the matching
recording workspace. Lineage graphs, errors, and validation notices are exposed only for the
recording that requested them. Abort signals still cancel recording and graph requests. Scheduled
loads no longer retain an identity after abort or failure, so a later request for the same
recording and stage can run. Recording and stage changes also invalidate all active requests before
the next scheduled load starts. This covers signal-less conflict reloads and manual refreshes.
Request sequence checks stop older loads from replacing newer data. Selection attempts carry
recording and request ownership through success, error, busy-state cleanup, and 409 recovery. A
delayed result from a prior recording cannot update the workspace or notice, or start a conflict
reload after the switch. Same-recording 409 recovery remains active.

## Coverage

`useRecordingPipelineData.test.tsx` covers stale recording responses, completed-load same-stage
recording switches, stale stage responses, overlapping refreshes, and graph errors. The workspace
suite verifies that a recording switch shows loading instead of the prior recording and that a root
route selects its initial stage from the new recording. A delayed graph test verifies that the new
recording does not receive the prior graph while loading. The other workspace suites cover deleted
lineage nodes, invalid saved URLs, URL restoration, exact selected revisions after a selection
conflict, and the composed workspace. The workspace tests are split into focused files; each remains
within the 800-line test budget. The composition root and each new production module meet their line
budgets. Deterministic tests cover A → B → A before the load timer, failed B followed by A and a new
B request, deferred conflict-reload success and failure before B's scheduled load, and deferred old
selection success, ordinary error, and 409 responses after B loads. They verify that B's selection
and later requests remain usable. The round-analysis workspace test uses its required
`JobStateProvider`.

## Checks

From `web/`:

- `npx eslint src/pipeline/RecordingPipeline*.test.tsx src/pipeline/RecordingPipelineWorkspace.tsx src/pipeline/recordingPipelineSelection.ts src/pipeline/useRecordingPipelineData.ts src/pipeline/useRecordingPipelineSelection.ts src/pipeline/useRecordingPipelineData.test.tsx src/pipeline/useRecordingPipelineSelection.test.tsx` — passed.
- `npm run typecheck` — passed.
- `npm test -- --run src/pipeline/RecordingPipelineWorkspace.test.tsx src/pipeline/RecordingPipelineWorkspacePresentation.test.tsx src/pipeline/RecordingPipelineWorkspaceSelection.test.tsx src/pipeline/RecordingPipelineSelectionIntegration.test.tsx src/pipeline/useRecordingPipelineData.test.tsx` — 45 tests passed.
- The same `npm test -- --run` command with `src/pipeline/useRecordingPipelineSelection.test.tsx` added — all 48 tests across six files passed.
- `npm test -- --run src/pipeline/useRecordingPipelineData.test.tsx src/pipeline/useRecordingPipelineSelection.test.tsx src/pipeline/RecordingPipelineWorkspaceSelection.test.tsx` — 26 tests passed after owner invalidation changes.
- `npm run typecheck` — passed after owner invalidation changes.
- `npx eslint src/pipeline/useRecordingPipelineData.ts src/pipeline/useRecordingPipelineData.test.tsx` — passed after owner invalidation changes.
- `npx prettier --check src/pipeline/useRecordingPipelineData.ts src/pipeline/useRecordingPipelineData.test.tsx` — passed after owner invalidation changes.
- `npx prettier --check src/pipeline/RecordingPipeline*.test.tsx src/pipeline/RecordingPipelineWorkspace.tsx src/pipeline/recordingPipelineSelection.ts src/pipeline/useRecordingPipelineData.ts src/pipeline/useRecordingPipelineSelection.ts src/pipeline/useRecordingPipelineData.test.tsx src/pipeline/useRecordingPipelineSelection.test.tsx` — passed.
- Line budgets: workspace composition 476/500; workspace data and selection modules 272/700 and 246/700; largest workspace test 727/800.

During integration with 0113, these workspace suites mock `AutomatedPipelineControls` so they test
workspace loading and selection without the shared `JobStateProvider` required by the launch
controls. The launch controls keep their own provider-wrapped tests.

No API or persisted-data contract changed. Initial M7 checks passed at `10eab971`. Owner-invalidation
correction checks passed at revision `5a29f034`.
