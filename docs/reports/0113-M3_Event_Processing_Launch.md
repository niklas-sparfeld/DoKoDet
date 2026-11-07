# 0113 M3 event processing launch

M3 moves event processing into the shared **Actions** modal in the recording inspector. The modal
shows the recording ID, accepted recording video, processor implementation, model, configuration,
and extraction policy. It explains that the operation creates a fresh event result and does not
change review decisions. The action remains visible when the accepted video is missing or invalid;
the blocker stays in the modal and disables submission.

The event action owns construction of the frozen `event_processing` request in `RunControls` and
submits it through the shared `useJobSubmission` owner. Submission keeps an idempotency key across
uncertain acceptance, prevents duplicate requests, retains rejected values, closes the modal after
acceptance, refreshes the recording workspace, and links the job. Existing event results, run
details, and review controls remain available. The old inline event launch button and its alternate
submission path are removed. Other processor forms are unchanged.

## `event_import` disposition

The M0 inventory found no browser submitter for `event_import`. Keep its registry entry and generic
job API support for agent/import tooling. M3 does not add an import UI. M9 must repeat the browser
caller audit before removing any unused client facade or changing registry support.

## 0112 coordination

0112 M8 remains unstarted and owns extraction of launch request construction from `RunControls`.
For now, the event action handler owns its request construction and form context; the shared modal
owns the launch presentation and `useJobSubmission` owns acceptance behavior. When 0112 M8 lands,
the event handler should call its extracted request builder while retaining this modal and submit
path. Confirm that boundary before 0112 M8 edits. M3 does not change 0112-owned code.

## Verification

- `npm test -- --run src/pipeline/RunControls.test.tsx src/jobs/JobStartActions.test.tsx src/jobs/JobStartInfrastructure.test.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx` — passed, 48 tests. Covers the frozen request, blocked source, accepted job link, shared modal behavior, and workspace inspector.
- `npm run typecheck` — passed.
- `npm run lint -- --no-warn-ignored` — passed.
- `npx prettier --check src/jobs/JobStartActions.tsx src/pipeline/RunControls.tsx src/pipeline/RunControls.test.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx` — passed.
- `npm run test:e2e -- --grep "job start actions fixture"` — passed, 2 browser checks for keyboard/focus, drawers, desktop and narrow layouts, and cancel without submission. Vite reported the existing 500 kB chunk-size advisory.
- `git diff --check` and local Markdown-link check — passed.

No API, backend, or generated API contract changed.
