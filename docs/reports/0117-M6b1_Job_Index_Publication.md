# Epic 0117 M6b1: durable ordered job-index publication

Date: 2026-11-09

## Result

Complete for bounded incremental index publication; no end-to-end Job Manager transition bound is
claimed. Job transitions now publish a durable per-recording active-job index through the M6a
transition journal. The SQLite index stores active job summaries, an ordered page index, a
per-recording generation and active count, plus a global sequence marker. It does not copy job
payloads.

The prepared `job-record-transition/v2` record binds the old and new job digests, global authority,
and exact index delta. The writer validates the prior indexed row before it prepares the journal.
It replaces `job.json`, commits the index row, count, and generations in one SQLite transaction,
advances the global authority, then removes the journal. Recovery accepts the old or new database
state and reapplies the delta idempotently. It rejects unrelated job, authority, row, or sequence
values. Correction 1/2 uses UTF-8 canonical JSON for the indexed job digest, matching the M6a
authority's job-file digest. A non-ASCII job update now survives a subsequent interrupted transition
and recovery.

## Readiness and limits

A new empty root starts ready. A root with prior intents but no index starts `ready=false`; writes
update only their affected row and sequence while preserving the not-ready state. M6b2 must run an
explicit rebuild before it serves pages from such an index. The rebuild will be one atomic SQLite
transaction and will hold the Job Manager lock. No page API is enabled by M6b1.

The bounded claim is limited to index publication: it uses point queries and updates one job row,
without calling `list_jobs()` or reading other recordings. This does not bound an end-to-end job
transition. `JobManager.transition()` still calls `_reconcile(self._intents())`; queue reconciliation
reads all committed job records. `accept()` also scans intents for idempotency keys, sequence
allocation, and parent-step uniqueness. This remains an acceptance gap for M6 overall. M6b1a owns a
durable bounded queue and acceptance authority with crash recovery and 10x growth checks. M6b2
depends on M6b1a. SQLite integrity and schema checks run at manager startup, not on each index update.

## Checks

- `mise exec -- uv run --project backend pytest -q backend/tests/test_job_projection_authority.py backend/tests/test_job_store.py` — passed 23 tests. Crash injection covers prepared journal, job file, SQLite index, global authority, and journal removal. Recovery checks global and recording sequences and active-row state.
- The same tests cover concurrent reader/writer serialization, replay after index commit, writes with `list_jobs()` disabled, per-recording isolation and maintained counts, legacy-not-ready state, row conflict without job mutation, corrupted database, and missing ordered index.
- `test_unicode_job_digest_survives_transition_recovery` passes at prepared-journal, job-record, and index-commit crash boundaries.
- `mise exec -- uv run --project backend ruff check` and `ruff format --check` on changed Python files — passed.
- `mise exec -- npm run generate:api` and `npm run verify:api` — passed; the unaccepted M6b route is absent.
- `mise exec -- npm run typecheck` — passed.
- `git diff --check` and local Markdown link check — passed.
- The 0114 inventory checker still reports eight pre-existing recording-state operations absent from its closed inventory. M6b2 owns a separate active supplement and passing checker. There is no M6b1 browser route. The prior `list_jobs()`-disabled test does not establish bounded end-to-end transition work; M6b1a must verify queue and acceptance growth.

The backend API tests report the existing Starlette `httpx` deprecation warning.

## Handoff

The first M6b submission remains unaccepted; see the [submission record](0117-M6b_Bounded_Active_Job_Projections.md).
Next is M6b1a: add bounded queue and acceptance authority and recovery. M6b2 depends on that work;
it owns bounded SQL pages, explicit atomic rebuild, 10x read growth, corruption mapping, and the
active API inventory supplement/checker. The run remains capped at 14 milestones: 9 complete, 5
remaining. M6b replan count is 2/5, M6b1 correction count is 1/2, and run replan count is 6/10.
M8–M16 are outside this run.
