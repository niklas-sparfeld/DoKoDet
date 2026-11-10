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

- `mise exec -- uv run --project backend pytest backend/tests/test_processor_run_catalog_publication.py backend/tests/test_pipeline_store.py backend/tests/test_pipeline_lineage_writer.py backend/tests/test_recording_catalog_index.py backend/tests/test_recording_catalog_node_publication.py backend/tests/test_recording_catalog_growth_contract.py backend/tests/test_round_analysis_api.py -q` — passed; 3 strict expected failures in the M0 growth file remain scheduled for M6.
- `mise exec -- uv run --project backend ruff check` on changed Python sources and tests — passed.
- `mise exec -- uv run --project backend ruff format --check` on changed Python sources and tests — passed.
- `git diff --check` — passed.
- The indexed route test disables run-status discovery and verifies `active-run` from catalog counters.
- Separate tests cover same-run create concurrency, pre-commit intent cancellation, post-commit recovery, catalog receipt replay after SQLite commit, duplicate create, all run statuses, progress count stability, and 10x terminal-run history with fixed active work.
- Local Markdown links in the epic, board, glossary, and this report — checked.
- No backend Python type checker is configured in the project or `mise.toml`.

## Progress and limits

M3 is complete. The disposable indexed list path no longer parses processor-run requests. No
production cutover or retained-data conversion was performed. M5 must rebuild compact run status
contributions for retained runs before M6 activation. Run progress is 4/8 complete and 4 remain.
Run re-plannings are 1/10; M3's scope-review re-planning is 1/5. M3 implementation corrections are
0/2. No later milestone was added.
