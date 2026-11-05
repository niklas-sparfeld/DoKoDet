# Epic 0110 M4: unified job HTTP API

M4 adds `/api/jobs` management routes for enqueue, list, detail, cancel, retry, queue move, and
bounded log pages. One manager owns the operations root for the app lifetime. The API returns job
capabilities with detail, uses filter-bound cursors, reports queue groups on every list page, and
returns the current queue revision and order when a move conflicts.

The job type registry validates closed requests before acceptance. The API tests register fake
`fake` and `automated_pipeline` types. The normal app does not accept a job type until an owning
milestone registers it. The manager persists up to 1,000 diagnostic entries per job. Missing result
artifacts appear as unavailable references. Enqueue and retry require an idempotency key and return
`202` with a `Location` header.

The OpenAPI document now defines the job routes and response types. The generated browser contract
is `web/src/api/openapi.ts`. M5 will register the first real processor type and switch its launch
callers.

Focused verification:

- `cd backend && mise exec -- uv run pytest tests/test_jobs_api.py tests/test_job_store.py tests/test_job_scheduler.py tests/test_api.py` — 67 passed.
- Ruff check and format passed for the changed backend files.
- `cd web && npm run generate:api` and `npm run verify:api` passed.
