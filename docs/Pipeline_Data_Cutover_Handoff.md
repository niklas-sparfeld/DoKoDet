# Pipeline data cutover handoff

This document records the M10 handoff from package-backed data work to the recording pipeline.
Epic 0049 owns the user-facing cutover. It can remove the old entry points after it exposes the
maintained references through the recording workspace.

## New entry points

Recording-based processor and review work uses the immutable pipeline stores:

- `backend/src/dokodetector_backend/pipeline_store.py` provides
  `PipelineRevisionStore.require`, `PipelineRevisionStore.publish`, and the run and selection
  stores. Revisions contain `manifest.json` and `content.json`.
- `backend/src/dokodetector_backend/pipeline_reference_service.py` provides the maintained
  reference lifecycle. Completion publishes a human revision and advances the completed-reference
  selection.
- `operations/src/doko_operations/derived_view.py` resolves frames and crops from the accepted
  recording video. It does not inspect an evidence package.
- `operations/src/doko_operations/pipeline_dataset.py` provides
  `PipelineDatasetConsumer`, the three typed dataset builders, and immutable
  `pipeline-dataset/v1` manifests. A request must name the completed reference, upstream reference
  revisions, source-group facts, partition, and full policies.
- The HTTP routes under
  `/api/recordings/{recording_id}/pipeline/` expose event, visible-card, identity, observation,
  and maintained-reference runs and selections. The recording source remains the accepted video
  in the repository intake bundle.

Generated revisions remain selectable for processor inputs and may be named as an explicit
dataset robustness comparison. They are never eligible as reviewed targets.

## Legacy routes and adapters for 0049 to remove

0049 can remove these package-backed entry points after the maintained-reference UI is ready:

- Event review: `CardEventReviewStore`,
  `backend/src/dokodetector_backend/card_event_review_api.py`, and the
  `/v1/recordings/{recording_id}/card-event-reviews` and
  `/v1/recordings/{recording_id}/card-event-review` routes.
- Visible-card review: `VisibleCardReviewBatchStore`,
  `backend/src/dokodetector_backend/visible_card_review_api.py`,
  `table_evidence_analyzer/src/table_evidence_analyzer/visible_card_review_workflow.py`, and the
  `/v1/recordings/{recording_id}/visible-card-review` and
  `/v1/visible-card-reviews/{batch_id}` routes.
- Identity review: `VisualCardIdentityReviewBatchStore`,
  `backend/src/dokodetector_backend/visual_card_identity_review_api.py`, and the
  `/v1/recordings/{recording_id}/identity-review` and
  `/v1/identity-reviews/{batch_id}` routes.
- Package-backed observation work: `evidence_package.py`, `table_evidence.py`,
  `TableEvidenceReviewAdapter`, `TableObservationReviewAdapter`, and the package/analyzer routes
  registered by `backend/src/dokodetector_backend/api.py` and `app.py`.
- Old dataset adapters: `CardEventNetReviewAdapter` in
  `operations/src/doko_operations/cardevent.py`, `materialize_visible_card_dataset` in
  `table_evidence_analyzer/src/table_evidence_analyzer/visible_card_dataset.py`, and the legacy
  projection in `operations/src/doko_operations/visual_card_identity_dataset.py`. Keep them until
  0049 completes the UI cutover, then remove their package-backed input paths.

The device evidence package remains a separate showcase upload until 0049 changes that product
boundary. It is not a recording-pipeline input.

## Foundation proof commands

Run these commands from the repository root:

```text
mise exec -- uv run --project operations pytest operations/tests/test_pipeline_dataset.py -q
mise exec -- uv run --project backend pytest backend/tests/test_local_pipeline.py -q
mise exec -- uv run --project backend pytest backend/tests/test_pipeline_api.py backend/tests/test_pipeline_reference.py -q
mise exec -- uv run --project operations ruff check operations/src operations/tests
mise exec -- npm --prefix web run verify:api
mise exec -- npm --prefix web run typecheck
mise exec -- npm --prefix web run lint
mise exec -- npm --prefix web test -- --run
```

The first command proves completed event, visible-card, and identity revisions, exact upstream
alignment, frozen policies, permissions, protected groups, and explicit robustness inputs. The
local pipeline test proves the video-only recording path and restart-safe persisted lineage. The
dataset consumer has no import from the evidence-package modules and does not open package media or
package manifests.

## Measured real-data limits

M10 proves the contracts with local generated and synthetic fixtures. The repository has no checked-in
real recording with completed maintained event, visible-card, and identity reference revisions,
and no frozen real-data `pipeline-dataset/v1` manifest. The current `data/` and `backend/data/`
directories contain local runtime state only.

Therefore M10 makes no real-data coverage or model-quality claim. Epic 0049 must collect and review
real recording coverage through the maintained-reference workspace. Epic 0043 remains blocked until
that reviewed real coverage is declared and measured.
