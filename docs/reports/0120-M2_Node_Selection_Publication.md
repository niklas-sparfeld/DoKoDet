# 0120 M2: node and selection publication

Date: 2026-11-10. Baseline revision: `7ca31b2869e4e3548e909d600b3e10ea6afd56a8`.

## Result

The app now creates the M1 recording catalog index and passes it to the pipeline node and selection
stores. Node creation and saves publish one compact node contribution after the durable revision
history outbox is committed. App construction replays pending catalog publications and the named
revision-history outbox. Exact selection updates publish both generated and completed-reference
pointers through the same M1 source protocol.

In explicit disposable test activation, `GET /v1/recordings` reads node availability from catalog
counters and the table-observation blocker from the exact selection projection. It does not enumerate
node manifests, revisions, or exact selections. The production default keeps the existing list
reader until M5/M6 rehearsal and activation. Processor-run status keeps its current reader until M3;
recording metadata and analysis/package summaries keep their current readers until their planned
adapter milestones.

## Workflow evidence

The disposable app test writes real table-observation nodes and exact selections to persistent
storage. It simulates interruption after the node commit and before catalog publication, then opens a
new app instance to replay the revision-history outbox. A generated selection change runs through
the real pipeline API while a node publication runs concurrently. The test keeps both generated and
completed-reference identities, confirms the table-observation availability count, verifies that a
missing exact target fails, and reads `/v1/recordings` with node and selection discovery disabled.
The blocker clears. A second app restart retains the result.

Separate tests interrupt standalone and coordinated selection publication after the selection
pointer reaches its target state but before the catalog contribution is published. Both recover
from the existing coordinated transaction journal after app restart. An identical standalone retry
returns the committed selection. A production-default route test verifies that the catalog reader is
not called and existing node-derived status remains visible.

The fixture has no analyses, evidence packages, or processor runs. It therefore proves the first
complete workflow for the assigned node/selection source families. Other source families remain on
their existing readers.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_recording_catalog_index.py backend/tests/test_recording_catalog_node_publication.py backend/tests/test_pipeline_node_selection_store.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_pipeline_api.py backend/tests/test_observation_pipeline_api.py backend/tests/test_visible_card_pipeline_api.py backend/tests/test_round_analysis_api.py -q` — passed, 108 tests. One existing Starlette/httpx deprecation warning.
- `mise exec -- uv run --project backend ruff check` on the changed Python sources and test — passed.
- `mise exec -- uv run --project backend ruff format --check` on the changed Python sources and test — passed.
- `git diff --check` — passed.
- No backend Python type checker is configured in `mise.toml` or the project.
- Local links in the epic, board, glossary, and this report — checked.

## Sanity review and scope review

The first submission did not pass the workflow checkpoint. It proved fresh-data route behavior, but
it did not close two durable selection gaps. `update_exact` writes the selection file before it
creates the catalog outbox. A crash in that gap leaves no replay record. Coordinated recovery also
skips a selection that already reached its target revision, so it can leave the catalog stale when
the process stopped before catalog publication. The app also activates the indexed list path by
default, although retained recordings have not been indexed before M5/M6.

Scope review disposition: keep the bounded M2 approach and fix these local boundaries using the
existing M1 outbox and coordinated transaction journal. Add no authority, persistent contract, or
prerequisite. Keep production `/v1/recordings` on its existing reader until the planned M5/M6
activation. Enable the indexed path only for explicit disposable test activation. The next proof
must keep the real API test with node discovery disabled and add separate crash/restart coverage for
standalone and coordinated selection writes, plus a production-default route regression. Stop if
this proof cannot pass within the correction allowance.

The correction passed the first-workflow checkpoint. It keeps the existing catalog and transaction
contracts, adds no source owner or prerequisite, and restores the production-default list behavior.
M2 is complete after correction 1/2. Run progress is 3/8 complete and 5 remain. Re-plannings remain
0/10. M3 is next: connect processor-run state writes. Recording, analysis, and package adapters
remain scheduled for M4.
