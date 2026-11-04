# Epic 0105 M4: Complete Workflow Verification

Date: 2026-11-04

## Result

The deterministic fixture completes the six-stage coordinator plan and retains the overall run
status, stage status, and exact input and output revision IDs. The fixture includes a valid empty
event output. The worker restart check resumes at the interrupted stage and keeps the completed
event result. The API fixture starts the run through the recording-scoped route and reads its
durable status. The workspace control fixture starts once, reloads the saved run ID, restores
completed status, and displays links for all six stage results and the saved analysis.

These checks verify execution and lineage. They do not verify that event proposals, card proposals,
identity proposals, observations, or the reconstruction are correct. The fixture worker returns
deterministic revision IDs; it does not run model inference or create stage payloads in the retained
production stores. The UI and backend fixtures are tested in separate processes. There is no
browser-to-backend Playwright fixture for this action yet.

## Reproduction

From the repository root, run the backend fixture checks:

```sh
mise exec -- uv run --project backend pytest \
  backend/tests/test_automated_pipeline_run.py \
  backend/tests/test_automated_pipeline_worker.py \
  backend/tests/test_pipeline_run_api.py \
  backend/tests/test_pipeline_coordinator.py
```

The worker fixture uses session `session-1`, round `round-1`, game `game-1`, players `p1` through
`p4`, dealer `p1`, first-trick leader `p2`, rules `v1`, and search limits 1 missing play, 16
hypotheses, and 1,000 search nodes. It supplies fixed fixture configuration for the five processor
stages and generates an idempotency key. It completes all six stages, then checks exact lineage,
empty event handling, failure retention, accepted-run startup, and interrupted-run recovery.

From `web/`, run the workspace control checks and static checks:

```sh
npm run typecheck
npm test -- --run src/pipeline/AutomatedPipelineControls.test.tsx src/api/client.test.ts
npx eslint src/pipeline/AutomatedPipelineControls.tsx src/pipeline/AutomatedPipelineControls.test.tsx src/pipeline/RecordingWorkspaceInspector.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx src/api/client.ts
npx prettier --check src/pipeline/AutomatedPipelineControls.tsx src/pipeline/AutomatedPipelineControls.test.tsx src/pipeline/RecordingWorkspaceInspector.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx src/api/client.ts
```

The UI fixture uses the recording workspace action, enters four player IDs, dealer, and first-trick
leader, starts once, then unmounts and mounts the control again to model reload. It checks all six
result links, including the analysis link. Together, the backend and web commands reproduce the
fixture workflow without model files, cloud services, or hardware.

## Verification

- Backend run, worker, API, and coordinator tests: 26 passed.
- Web pipeline control and API client tests: 11 passed.
- Web TypeScript typecheck: passed.
- Scoped ESLint and Prettier checks: passed.
- `npm run test:e2e`: production build passed; Playwright reported 6 passed and 9 failed in
  existing CardEvent review, workspace navigation, and keyboard-name assertions. None of those
  failing cases exercises the automated pipeline control. The suite has no end-to-end test for
  this action.

The web build reported its existing large-chunk warning. The Playwright failures are recorded as a
coverage limit; they do not change the passing focused pipeline fixture results.
