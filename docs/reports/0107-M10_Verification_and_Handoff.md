# 0107 M10: verification and handoff

## Verification

The local lineage contract suites passed:

```sh
mise exec -- uv run --project backend pytest \
  backend/tests/test_pipeline_node_store.py \
  backend/tests/test_pipeline_item_provenance.py \
  backend/tests/test_pipeline_node_uses.py \
  backend/tests/test_pipeline_node_edits.py \
  backend/tests/test_pipeline_node_reviews.py \
  backend/tests/test_pipeline_identity_review.py \
  backend/tests/test_virtual_scene_data.py \
  backend/tests/test_pipeline_lineage.py \
  backend/tests/test_lineage_migration_inventory.py \
  backend/tests/test_lineage_migration_apply.py
```

Result: 47 passed. These fixtures cover immutable node revisions, item provenance, accepted-use
protection, copy-on-first-change, review history and coverage, identity decision applicability,
virtual scenes, typed lineage, inventory, and staged migration.

`ruff check backend/src backend/tests` passed. Ruff format checks passed for all lineage foundation
modules and their focused tests. A backend-wide format check reports 22 other files that already
need formatting; none of the checked lineage files are among them.

The full backend test run is not clean in this checkout. It fails at
`test_start_rejects_invalid_preflight_without_persisting_a_run`: the uncommitted local change to
`automated_pipeline_run.py` creates round context instead of rejecting a mismatched session. The
test and implementation are outside this epic and were left untouched. The focused lineage suites
pass independently.

## 0108 integration points

The new lineage foundation is durable and tested, but it is not wired into the application. The
current composition in `backend/src/dokodetector_backend/pipeline_composition.py` creates
`PipelineRevisionStore`, `PipelineSelectionStore`, `PipelineReferenceStore`, and
`VisibleCardReviewStore`. It does not create `PipelineNodeStore` or its edit, use, review, identity,
and graph services.

Epic 0108 must integrate the node services with the existing processors, run records, APIs, and
workspace. Main backend consumers still depend on legacy revision or review storage:

- Processor services: `event_pipeline_service.py`, `visible_card_pipeline_service.py`,
  `proposed_card_scene_pipeline_service.py`, `visual_identity_pipeline_service.py`,
  `observation_pipeline_service.py`, `round_analysis_service.py`, and
  `calibration_refinement_service.py`.
- Selection, comparison, and workspace: `pipeline_store.py`, `pipeline_comparison_service.py`,
  `pipeline_workspace_service.py`, and `pipeline_coordinator.py`.
- Maintained references and independent reviews: `pipeline_reference_service.py`,
  `pipeline_reference_api.py`, `visible_card_review_service.py`, and
  `visible_card_review_api.py`.
- Direct legacy construction: `cardeventnet_canonicalization.py` and
  `pipeline_composition.py`.
- Operations tools read `pipeline-references` directly in `cardevent_inventory.py`,
  `cardevent_interval_readiness.py`, `cardevent_readiness.py`, `cardevent_migration.py`,
  `reviewed_rfdetr_detector_campaign.py`, `rfdetr_segmentation_campaign.py`,
  `dinov3_identity_campaign.py`, and `resilience_baseline.py`.

The active paths include `data/operations/pipeline/revisions`, `runs`, `selections`,
`automated-runs`, `pipeline-references`, `pipeline-reviews`, recording calibration stores, and
round-analysis artifacts. Use a consistent snapshot and the M8/M9 tools before the application
switch. Preserve processor input defaults and external artifact identities. Update every active
consumer before deleting old stores or adapters. Keep a recovery snapshot. Do not migrate live data
as part of this handoff.

## Boundary

Epic 0107 closes with the node, provenance, copy, review, identity-applicability, scene, graph, and
fixture-migration foundations verified. Epic 0108 owns application integration, the local migration
and activation, workspace cutover, recovery, and deletion of replaced runtime paths. Moving 0107 to
Closed does not claim that the application has switched to the new model.
