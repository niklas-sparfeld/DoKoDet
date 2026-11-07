# M8 launch request extraction

M8 split the surviving processor launch code after 0113 closed its unified start flow. Event,
visible-card, and visual-identity actions remain in the shared `JobStartActions` modal and use the
shared job submission contract. The workspace still supplies retained processor run details. This
extraction adds no feature poller, retry path, or second job lifecycle.

## Owners

- `pipelineLaunchRequest.ts` builds typed processor requests, exact input references, crop choices,
  provider/model defaults, and validation messages.
- `EventLaunchFields.tsx`, `VisibleCardLaunchFields.tsx`, and `VisualIdentityLaunchFields.tsx` own
  the three surviving modal form sections.
- `RunControls.tsx` remains the submission composition root (489 lines).
- `RunHistoryPresentation.tsx` and `RunStatusPresentation.tsx` render workspace-backed run details.
- `usePipelineLaunchClient.ts` composes the existing jobs and processing clients.

## Verification

- `cd web && npm run typecheck` — passed.
- `cd web && npx eslint src/pipeline/RunControls.tsx src/pipeline/pipelineLaunchRequest.ts src/pipeline/EventLaunchFields.tsx src/pipeline/VisibleCardLaunchFields.tsx src/pipeline/VisualIdentityLaunchFields.tsx src/pipeline/RunHistoryPresentation.tsx src/pipeline/RunStatusPresentation.tsx src/pipeline/usePipelineLaunchClient.ts` — passed.
- `cd web && npx prettier --check src/pipeline/RunControls.tsx src/pipeline/pipelineLaunchRequest.ts src/pipeline/EventLaunchFields.tsx src/pipeline/VisibleCardLaunchFields.tsx src/pipeline/VisualIdentityLaunchFields.tsx src/pipeline/RunHistoryPresentation.tsx src/pipeline/RunStatusPresentation.tsx src/pipeline/usePipelineLaunchClient.ts` — passed.
- `cd web && npm test -- --run src/api/client.test.ts src/pipeline/RecordingPipelineWorkspace.test.tsx src/pipeline/RunControls.test.tsx` — 39 passed.

The UI suite covers exact revision inputs, proposed-scene crop choice, provider/model defaults,
validation, submitted payloads, and links to the shared job route. The existing `RunControls.test.tsx`
is 1,301 lines and covers multiple launch and run-history concerns; M10 owns its test-size split.
