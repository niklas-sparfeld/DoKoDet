# 0110 M13 — Browser job client and details

The app now owns one shared job client and active-job polling loop. The loop pauses when the page is
hidden and restarts when it becomes visible. It rejects stale list responses. The `/jobs` route has
bounded active and history lists. History uses the server cursor and loads one page at a time.

The `/jobs/{id}` route loads one job and at most 100 log entries per request. Active jobs refresh
every two seconds. The route aborts requests on navigation and ignores responses from an old route.
It retries after a connection error and resumes polling when the page becomes visible. Browser
back and forward continue to use the app's `popstate` route handling. Reload opens the same URL.

Shared status and action components expose status, cancel, and retry actions. Result links accept
same-origin paths tied to the exact job, or counterfactual paths whose analysis and result IDs match
the job. Invalid, unrelated, or external paths do not become links.

## Verification

- `npm run typecheck` passed.
- Focused ESLint for `src/App.tsx`, `src/api/client.ts`, and `src/jobs` passed with one hook warning
  during an intermediate run; the warning was then removed.
- `npx vitest run src/App.test.tsx src/jobs src/api/client.test.ts` passed (20 tests).
- `npm run verify:api` passed. No API schema changes were needed.
- `npx vitest run src/jobs` passed (5 tests). The provider test mounts two consumers, verifies one
  shared list poll, and resolves an older response after a newer response to confirm that stale data
  does not replace the current job list.
- `npm run build` passed.
- `npx playwright test tests/e2e/jobs.spec.ts` passed (2 browser tests). The tests cover history
  cursor pagination, exact job and result links, reload, browser back and forward, recovery after an
  API disconnect, and polling pause/resume across hidden and visible page states.
- `npm run check` stopped at lint because `src/cardEvents/CardEventFrameSurface.tsx` has two
  existing effect-state lint errors. `npm run format` reports seven pre-existing unformatted files
  outside this milestone. The full Vitest run also showed failures in the existing video and frame
  cache tests; focused job and App tests pass.

M13 browser acceptance passed. M16 still owns full workflow browser checks across all job producers.
