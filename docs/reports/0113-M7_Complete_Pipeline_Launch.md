# 0113 M7 — Complete-pipeline launch

## Result

The complete-pipeline action now opens the shared start dialog. It shows the accepted source video and digest, the session, all six stage model/configuration objects, round facts, rules, search limits, and expected outputs. It submits through the existing pipeline preflight API. The API validates and freezes the exact round facts and source before it accepts the parent job. It rejects missing facts or a session mismatch before it writes a run or accepts a job.

The dialog retains its values after a preflight error. An uncertain response retries the same payload and idempotency key. A confirmed launch links to the parent in Jobs and refreshes the shared Jobs state. It does not keep a separate pipeline poller or restore an earlier run from local storage. A later launch makes a new request with a fresh key. The parent records exact child job IDs and input/output revision IDs through the existing stage chain.

## Checks

- `pytest backend/tests/test_automated_pipeline_run.py backend/tests/test_automated_pipeline_jobs.py backend/tests/test_pipeline_run_api.py` — 16 passed. This includes invalid-fact and wrong-session preflight, no persisted run or parent job on invalid facts, exact child input/output revision lineage, and new parent job acceptance.
- `npx vitest run src/pipeline/AutomatedPipelineControls.test.tsx` — 2 passed. The fixture checks displayed settings and facts in the request, retained values after a 422, the shared parent link, exact child lineage display, and fresh keys for a later launch.
- `npm run typecheck` — passed.
- `npm run verify:api` — passed after generating the request schema.
- Ruff checks and format on changed backend files — passed.
- Playwright `pipeline-cutover.spec.ts -g "starts a fact-complete pipeline"` — could not reach the app UI: the page body stayed empty and the action was absent. The existing “opens fresh accepted video” smoke test also failed before its first UI assertion because the banner was absent. Direct HTTP checks to the local Vite root and route returned 200. Browser acceptance remains to verify in M10.

The API export printed the existing optional `processor_run_catalog_skipped` notice because the temporary data root is not available. The API type verification passed.

## Limits

The current server exposes opaque per-stage model and configuration objects. The dialog shows and edits those objects as JSON and keeps the server preflight as the authority for provider/model availability. This milestone does not add execution modes or provider discovery.
