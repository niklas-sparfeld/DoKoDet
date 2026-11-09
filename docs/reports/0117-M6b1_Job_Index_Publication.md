# Epic 0117 M6b1: durable ordered job-index publication

Date: 2026-11-09

## Result

Complete. Job transitions now publish a durable per-recording active-job index through the M6a
transition journal. The SQLite index stores active job summaries, an ordered page index, a
per-recording generation and active count, plus a global sequence marker. It does not copy job
payloads.

The prepared `job-record-transition/v2` record binds the old and new job digests, global authority,
and exact index delta. The writer validates the prior indexed row before it prepares the journal.
It replaces `job.json`, commits the index row, count, and generations in one SQLite transaction,
advances the global authority, then removes the journal. Recovery accepts the old or new database
state and reapplies the delta idempotently. It rejects unrelated job, authority, row, or sequence
values.

## Readiness and limits

A new empty root starts ready. A root with prior intents but no index starts `ready=false`; writes
update only their affected row and sequence while preserving the not-ready state. M6b2 must run an
explicit rebuild before it serves pages from such an index. The rebuild will be one atomic SQLite
transaction and will hold the Job Manager lock. No page API is enabled by M6b1.

Ordinary job index updates use point queries and update one job row. They do not call `list_jobs()`
or read other recordings. Existing idempotency checks on job acceptance still read intent records;
M6b1 does not change that pre-existing behavior. SQLite integrity and schema checks run at manager
startup, not on each transition.

## Checks

- `mise exec -- uv run --project backend pytest -q backend/tests/test_job_projection_authority.py backend/tests/test_job_store.py` — passed 20 tests. Crash injection covers prepared journal, job file, SQLite index, global authority, and journal removal. Recovery checks global and recording sequences and active-row state.
- The same tests cover concurrent reader/writer serialization, replay after index commit, writes with `list_jobs()` disabled, per-recording isolation and maintained counts, legacy-not-ready state, row conflict without job mutation, corrupted database, and missing ordered index.
- `mise exec -- uv run --project backend ruff check` and `ruff format --check` on changed Python files — passed.
- `mise exec -- npm run generate:api` and `npm run verify:api` — passed; the unaccepted M6b route is absent.
- `mise exec -- npm run typecheck` — passed.
- `git diff --check` and local Markdown link check — passed.
- The 0114 inventory checker still reports eight pre-existing recording-state operations absent from its closed inventory. M6b2 owns a separate active supplement and passing checker. There is no M6b1 browser route.

The backend API tests report the existing Starlette `httpx` deprecation warning.

## Handoff

The first M6b submission remains unaccepted; see the [submission record](0117-M6b_Bounded_Active_Job_Projections.md).
Next is M6b2: implement bounded SQL pages and explicit atomic rebuild, measure reads with active and
unrelated job counts growing 10x, add corruption mapping, and add the active API inventory
supplement/checker. The current run remains capped at 14 milestones: 9 complete, 5 remaining. M6b
replan count is 1/5, M6b1 correction count is 0/2, and run replan count is 5/10. M9 is outside this
run.
