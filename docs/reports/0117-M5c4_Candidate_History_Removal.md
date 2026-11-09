# 0117 M5c4 — Remove the unsupported candidate history collection

**Status:** Complete  
**Date:** 2026-11-09

## Decision and scope

The generic `/api/recordings/{recording_id}/state/candidates` collection has no publisher, persisted
source, or web consumer. The collection gives embedded proposals a separate history identity without
defining how to select, order, or publish them. M5c4 removes this unused API and its index and
contract artifacts.

This change preserves proposal discovery through exact pipeline revision content and the existing
calibration-refinement preview. The apply operation materializes a calibration revision, which stays
available through revision history. These proposal values remain processor-derived; this change does
not label them as human-reviewed.

## Changes

- Removed the generic candidates route, cursor/page contract values, resource collection value, and
  ordered-index collection root.
- Kept snapshot, revision, and lineage-edge history routes and index roots.
- Regenerated `web/src/api/openapi.ts`; it no longer declares the candidates route or collection.
- Added an API regression that confirms the removed route returns 404 while the remaining collection
  pages preserve their collection-specific order.

## Verification

- `mise exec -- uv run pytest -q tests/test_recording_history_api.py tests/test_recording_history_order_index.py tests/test_recording_history_store.py`: passed, 56 tests. This includes the absent-route regression and sorted snapshot, revision, and lineage history pages.
- `mise exec -- uv run ruff check ...` and `ruff format --check ...`: passed for all changed Python files.
- `mise exec -- npm run generate:api` followed by `mise exec -- npm run verify:api`: passed. The generated OpenAPI has no generic candidates route or collection.
- `mise exec -- uv run pytest -q tests/test_calibration_refinement_service.py tests/test_interactive_ui_residual_write_performance.py::test_calibration_apply_has_timing_and_published_readback`: passed. The existing calibration refinement/apply workflow remains available and materializes a readable calibration revision.
- `git diff --check`: passed. Search of `web/src` found no consumer of the removed generic route.

The test run reports the existing Starlette deprecation warning for `httpx`; it does not fail.

## Replan and handoff

The eighth recorded epic replan splits the prior M5c candidate-source decision into this concrete
removal milestone. The current run replan count is 3/10. M5 discovery completes with this
milestone. The run is 7/14 complete with 7 milestones remaining. Next is M6. The 14-slot run covers
M5c4 and M6–M12; M13–M16 are outside the run.
