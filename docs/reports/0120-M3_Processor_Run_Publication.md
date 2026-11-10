# 0120 M3: processor-run status publication

Date: 2026-11-10. Baseline revision: `40919499`.

## Result

`ProcessorRunStore` now publishes compact per-run status contributions to the M1 catalog for run
creation, status changes, progress writes, and restart recovery. The run store remains authoritative.
Each catalog source contains only the run ID, recording ID, processor type, and status. Counters
aggregate by processor type and status, so a status transition replaces that run's old count with
its new count. Progress-only writes keep the same contribution and do not increase counts.

The catalog outbox now supports one processor-run prepare/finalize intent. Under the per-run lock,
the store writes an intent with the expected old and target state digests and the compact target
projection. It then commits the existing state file or staged run directory and finalizes the
catalog receipt. Finalization converts the intent to the existing M1 publication record before
applying it. Recovery visits only pending catalog records. It reads the exact named run, finalizes
when the target digest matches, cancels when the old digest matches, and fails visibly for any
other state. No run history scan is added. The catalog does not store request or state payloads.

The explicit disposable catalog list path now reads processor-run counters instead of parsing
saved run requests. The production list reader remains unchanged until the M5/M6 activation.

## Scope decision

The initial M3 acceptance could not cover a crash after the authoritative state commit and before
the catalog outbox existed. `ProcessorRunStore` had no existing recovery journal. Startup run
enumeration would violate M1's pending-only recovery contract. The scope review kept the catalog
approach and added one prepare/finalize intent contract to M1. The run store remains the source
authority; this adds no new store or general transaction framework. The prepare/finalize order and
crash cases are recorded in M3 of the active epic.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_processor_run_catalog_publication.py backend/tests/test_pipeline_store.py backend/tests/test_pipeline_lineage_writer.py backend/tests/test_recording_catalog_index.py backend/tests/test_recording_catalog_node_publication.py backend/tests/test_recording_catalog_growth_contract.py backend/tests/test_round_analysis_api.py -q` — passed on initial and correction submissions; 3 strict expected failures in the M0 growth file remain scheduled for M6.
- `mise exec -- uv run --project backend ruff check` on changed Python sources and tests — passed.
- `mise exec -- uv run --project backend ruff format --check` on changed Python sources and tests — passed.
- `git diff --check` — passed.
- The indexed route test disables run-status discovery and verifies `active-run` from catalog counters.
- Initial tests cover same-run create concurrency, pre-commit intent cancellation, post-commit
  recovery, catalog receipt replay after SQLite commit, duplicate create, all run statuses,
  progress count stability, and 10x terminal-run history with fixed active work.
- Local Markdown links in the epic, board, glossary, and this report — checked.
- No backend Python type checker is configured in the project or `mise.toml`.

## Correction 1/2

Sanity review found that startup recovery reconciled a pending intent without the named run lock.
It could cancel an intent while its writer had not yet committed the source state. Recovery now
acquires the exact run lock and rereads the pending record after acquiring it. Concurrent recoverers
serialize on that lock and the second one sees the first one's result. The established order remains
run lock, then catalog publication lock.

The review also confirmed a same-process retry gap. After finalize converts an intent to an ordinary
M1 outbox record, an `_apply` failure left that record pending. The intent-only recovery path ignored
it, so the next state write failed when it tried to prepare another publication. The run store now
checks the exact pending source record under the run lock, verifies its compact source value against
the authoritative run status, then replays it through M1. The separate restart receipt-gap test
remains, and a new test proves same-process recovery before the next progress write.

New tests hold a writer after intent creation while startup recovery waits on the same run lock, and
run two recoverers against one pending intent. Both preserve the correct status count. The complete
targeted test set, Ruff checks, format checks and `git diff --check` pass after correction 1/2.
Sanity review acceptance is pending. Current goal progress remains 3/8 accepted and 5 remain; run
re-plannings are 1/10; M3 scope-review re-plannings are 1/5; M3 corrections are 1/2. Production
cutover and retained-data conversion remain scheduled for M5/M6. No later milestone was added.

## Correction 2/2

Review found that `pending_processor_runs()` read the outbox without its publication lock. It now
copies and validates pending intents while holding that lock, then returns before recovery acquires
any run locks. Recovery still takes the exact run lock and rereads the pending record under the
publication lock. This keeps lock order consistent: snapshot uses only publication; reconciliation
uses run then publication.

New concurrency checks hold an enumeration while another operation removes an intent and while a
writer finalizes and replaces an intent. The snapshot returns a valid record, and each mutation
finishes after the snapshot releases the publication lock. A separate create crash test stops before
the staged run directory commits; restart sees the exact run absent and cancels the intent without
adding a catalog row. Tests from both earlier corrections remain, including overlapping live writer
recovery, concurrent recovery, same-process retry, and restart receipt-gap replay.

The targeted backend tests, Ruff, format, Markdown link and diff checks pass. Sanity review acceptance
is pending, and the M3 correction allowance is exhausted at 2/2. Goal progress remains 3/8 accepted
and 5 remain. Run re-plannings are 1/10; the M3 scope-review count is 1/5. Do not start M4 before
acceptance. If re-review does not accept, perform scope review before further M3 work.

## Scope review after correction exhaustion

Final sanity review found another recovery edge in the same intent approach. In
`_recover_run_catalog_intent_locked`, an existing run path whose `state.json` is missing, a symlink,
or another non-file path falls into the same branch as an absent run. When the intent's old digest is
`None`, recovery can cancel the create intent and hide an invalid persisted run. This is an
unaccepted M3 defect; the implementation must not treat it as an absent source.

No code change was authorized because M3 has used both correction turns and this finding is another
edge in the same approach. M3 stays In Progress. The bounded correction, if the user authorizes it,
must distinguish a truly absent run directory from an existing invalid path; preserve the pending
intent and fail visibly for an existing symlink or non-directory run path, a missing or symlinked
state file, or a state path that is not a file. Only a truly absent create source or a valid exact
old-state digest can cancel an intent. Add tests for absent-create cancellation and invalid-path
preservation. Retain all prior pre/post-commit, writer-overlap, concurrent-recovery, same-process
retry and restart receipt-gap boundaries. Re-run M3 checks and stop if more contracts or broader
recovery are required.

Initial plan count is eight; M0–M2 are accepted, including M2's first disposable API workflow.
M3 remains pending, followed by M4 recording/analysis/package adapters, M5 retained-data rehearsal,
M6 API/web activation, and M7 qualification/closure. Progress is 3/8 accepted and 5 remain. M3
scope-review re-plannings are 1/5, run re-plannings are 1/10, and M3 corrections are exhausted at
2/2. Do not start M4 or retry M3 on a new run until the user explicitly authorizes an additional
correction or selects another disposition.
