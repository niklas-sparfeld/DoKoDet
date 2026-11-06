# Epic 0108 M12 verification and closure

Date: 2026-11-07

## Result

M12 is complete. The browser regression exercises the lineage drawer and exact revision flow with
recorded API fixtures. It checks the two-row navigation, revision history and source, an empty
Visible cards step, copy-on-edit notice and selection, retained review decisions, reload, and both
exact inputs to an analysis.

The test exposed a lost notice: the event editor unmounted when it selected the new copy. The
workspace now keeps the notice after that change.

## Local migration and removal audit

The active `data/operations/pipeline-nodes` store has 1,006 node manifests and 1,223 revision
directories. The canonical `.pipeline-node-selections` store has 136 JSON files. The migration
receipt records 835 imported pipeline revisions, 594 processor runs, five analysis runs, 126
maintained drafts, 13 calibration drafts, 11 independent reviews, and 136 selections. A read-only
inspection found nodes with event, visible-card, identity, scene, and observation content for
`cardeventnet-IMG_0637`.

The retired `data/operations/pipeline-references` and `data/operations/pipeline-reviews` paths are
absent. Their recovery snapshots contain 511 files and 121,556,946 bytes, and 53 files and
21,514,843 bytes, respectively. These counts match the M11 removal receipt, which records tree
digests and migration-reader copy verification. Selection recovery records preserve the 136
canonical exact selections.

The M11 acceptance audit remains the removal evidence: active processors use exact node references
and one publication path; legacy revision reads remain in migration inventory and offline repair;
the old reference and review stores were removed after recovery verification. Focused API,
selection, review, migration, transaction, and node-store tests passed again in M12.

## Checks

- `npm run check` — passed: TypeScript, ESLint, Prettier, generated API comparison, and 179 Vitest
  tests.
- `npm run test:e2e` — passed: production build and all eight Playwright tests, including the new
  lineage regression.
- Focused backend tests — passed across pipeline API, lineage, node store, node edits and reviews,
  selection store, migration import/apply, transaction recovery, and writer modules.
- Backend Ruff and format checks — passed for pipeline workspace, lineage, node-store, and focused
  test modules.
- Migration inspection — passed: active node and selection counts, absent retired stores, and
  recovery file and byte counts match their receipts.
- Markdown links — passed for the moved epic, its board entry, and all inbound epic links.
- `mise exec -- uv run pytest -q` from `backend` — one unrelated failure remains:
  `tests/test_app.py::test_factory_converts_interrupted_round_analysis_to_failed` expects an
  unlinked queued round analysis to become failed at app construction. The record stays queued.
  An isolated rerun fails the same way. The test covers round-analysis recovery, and M12 changes no
  backend files or round-analysis behavior. All focused M12 backend tests pass.

## Closure

All milestones M0–M12 are complete. Processor input and trigger UX remains later work, as scoped in
the epic. No migration, model-quality, or hardware run was required for M12.
