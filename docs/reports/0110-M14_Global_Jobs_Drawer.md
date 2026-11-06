# 0110 M14 — Global Jobs drawer

The app now shows persistent Jobs chrome on every current route. The active count uses the shared
job client. The drawer shows active jobs and a bounded history page, supports text filtering,
expands parent jobs to show known child jobs, and uses shared status, cancel, and retry controls.
Queue groups can be reordered with labeled up and down buttons. The API uses the scheduler's
expected revision and reports a refresh message when a reorder conflicts.

On wide screens, the open drawer reserves a 23 rem strip so the central workspace remains visible.
On narrow screens, it opens over a scrim. Escape closes the drawer and restores focus to the Jobs
button. The drawer links use the existing job detail route.

## Verification

- `npm run typecheck` passed.
- Focused ESLint passed for App, drawer, drawer test, API client, and job browser tests.
- `npx vitest run src/jobs/JobsDrawer.test.tsx src/jobs/JobState.test.tsx src/App.test.tsx` passed
  (11 tests).
- `npm run build` passed.
- `npx playwright test tests/e2e/jobs.spec.ts` passed (4 tests), including desktop and narrow
  layout checks, focus return, empty state, failed history, disconnect, existing detail recovery,
  and history navigation.
- `npm run verify:api` passed. The queue move request uses the existing generated schema.

## Limits

Parent expansion shows child jobs that are present in the currently loaded job pages. History in
the drawer loads the first bounded page; the full `/jobs` route retains its cursor pagination.
Queue reorder controls appear after the operator enables reordering and use the current server
queue revision. Full producer workflows and stale cross-client reorder races remain in M16.

## Handoff

M14 is complete. M15 removes duplicate per-feature status and lifecycle UI. M16 owns the complete
fixture workflow and final system closeout.
