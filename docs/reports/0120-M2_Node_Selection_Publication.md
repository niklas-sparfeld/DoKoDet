# 0120 M2: node and selection publication

Date: 2026-11-10. Baseline revision: `7ca31b2869e4e3548e909d600b3e10ea6afd56a8`.

## Result

The app now creates the M1 recording catalog index and passes it to the pipeline node and selection
stores. Node creation and saves publish one compact node contribution after the durable revision
history outbox is committed. App construction replays pending catalog publications and the named
revision-history outbox. Exact selection updates publish both generated and completed-reference
pointers through the same M1 source protocol.

`GET /v1/recordings` now reads node availability from catalog counters. It reads the table-observation
blocker from the exact selection projection. It does not enumerate node manifests or revisions.
Processor-run status still comes from the current run-status reader, so the existing stage precedence
remains in effect until M3 connects those writers. Recording metadata and analysis/package summaries
also keep their current readers until their planned adapter milestones.

## Workflow evidence

The disposable app test writes real table-observation nodes and exact selections to persistent
storage. It simulates interruption after the node commit and before catalog publication, then opens a
new app instance to replay the revision-history outbox. A generated selection change runs through
the real pipeline API while a node publication runs concurrently. The test keeps both generated and
completed-reference identities, confirms the table-observation availability count, verifies that a
missing exact target fails, and reads `/v1/recordings` with node enumeration and the old workspace
status reader disabled. The blocker clears. A second app restart retains the result.

The fixture has no analyses, evidence packages, or processor runs. It therefore proves the first
complete workflow for the assigned node/selection source families. Other source families remain on
their existing readers.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_recording_catalog_node_publication.py backend/tests/test_recording_catalog_index.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_pipeline_api.py backend/tests/test_round_analysis_api.py -q` — passed, 81 tests. One existing Starlette/httpx deprecation warning.
- `mise exec -- uv run --project backend ruff check` on the changed Python sources and test — passed.
- `mise exec -- uv run --project backend ruff format --check` on the changed Python sources and test — passed.
- `git diff --check` — passed.
- No backend Python type checker is configured in `mise.toml` or the project.
- Local links in the epic, board, glossary, and this report — checked.

## Progress

M2 passed its scheduled first-workflow checkpoint. M2 family corrections: 0/2. No re-planning,
source owner, persistent contract, or scope change was needed. Run progress is 3/8 complete and 5
remain. M3 is the next bounded milestone: connect processor-run state writes while preserving
status precedence. Recording, analysis, and package adapters remain scheduled for M4.
