# Epic 0117 M6b: bounded active-job projections

Date: 2026-11-09

## Submission status

Unaccepted and incomplete after replan 10. The first submission checked the global M6a sequence
against one JSON file per recording. Any job transition, including one for an unrelated recording,
made every index stale and called `list_jobs()`. A fresh page also parsed and validated the whole
active-job array before slicing it. The test set did not include growth counters or persisted index
corruption.

The API route and JSON projection store were removed in the M6b1 commit. The route stays disabled
until M6b2 reads from the ordered transactional index and proves bounded work. The closed 0114
inventory remains unchanged; M6b2 owns an active supplement and passing checker.

## Initial submission record

The initial implementation added `GET /api/recordings/{recording_id}/state/jobs` with an M1
`recording-job-projection/v1` response with at most 20 active job summaries. The response is scoped
to one recording. Terminal jobs are excluded. The page count is the number of active jobs remaining
from that cursor boundary, which matches the M1 projection validator.

The projection index is stored under `data/operations/jobs/recording-projections/recordings/` with
the M6a authority epoch and sequence. A missing or stale index is rebuilt from authoritative job
records. The Job Manager lock covers the authority read, rebuild, and page construction. Cursors are
HMAC signed with a durable local key and bind the recording, jobs collection, filters, page size,
last stable key, and authority epoch and sequence. Any authority change expires an existing cursor.
The key and projection files use the existing atomic JSON writer.

## Changes

- Added the recording-scoped jobs route and stable invalid/expired cursor mappings.
- Added per-recording compact active-job indexes and authority validation.
- Added an API test for multi-page traversal, terminal exclusion, recording isolation, cross-process
  status change, cursor expiry, and repeated process restart.
- Added a threaded read/write test. It confirms that the reader waits for the writer and returns the
  new status and authority sequence.
- Regenerated `web/src/api/openapi.ts`. No web caller exists yet; M8 owns the UI flow.

## Checks

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_job_projection.py backend/tests/test_job_projection_authority.py backend/tests/test_job_store.py backend/tests/test_recording_state_contract.py` — passed.
- `mise exec -- uv run --project backend ruff check` on the changed Python files — passed.
- `mise exec -- uv run --project backend ruff format --check` on the changed Python files — passed.
- `mise exec -- npm run generate:api` — passed.
- `mise exec -- npm run verify:api` — passed.
- `mise exec -- npm run typecheck` — passed.
- `git diff --check` — passed.
- `backend/scripts/check_interactive_ui_performance_inventory.py` still reports nine current state
  routes missing from the 0114 inventory, including this new route. Eight state routes were already
  absent before M6b. The 0114 inventory is a closed-epic artifact and remains unchanged. There is no
  browser consumer to check in M6b.

The API tests report the existing Starlette `httpx` deprecation warning.

## Limits and handoff

M6b does not add analysis or evidence-package metadata pages, catalog conversion, or a web consumer.
Those remain M6c, M6d, and M8. The active index is rebuilt after any Job Manager authority change;
that rebuild reads authoritative job records. A page from an unchanged authority reads the compact
index. Job Manager restart recovery can turn queued work into terminal interrupted jobs; the
projection omits them after authority advances.

The run remains capped at 14 milestones: 9 complete, 5 remaining. Next is M6c. M6b replan count is
0/5, correction count is 0/2, and run replan count is 4/10.
