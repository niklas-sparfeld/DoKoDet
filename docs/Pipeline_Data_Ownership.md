# Pipeline data ownership

**Status: Completed handoff.**

This is a completed M0 handoff record for epic 0048. It records the storage and orchestration
boundaries used during the 0048 and 0049 implementation. It does not add a second architecture
specification or current operator route. The recording pipeline source is the accepted recording
video. Device evidence packages remain separate showcase artifacts; epic 0049 removed the old
package-backed recording entry points.

Use the [target architecture](TableObservationReconstruction.md) for current shared boundaries and
the [epic board](plans/README.md) for current work. The tables below retain historical
implementation evidence.

## Shared pipeline contracts

| Contract | M0 owner | Boundary added later |
| --- | --- | --- |
| Revision envelope, source references, event content, run request/state, selection | `operations/src/doko_operations/pipeline_data.py` | M1 stores revisions, runs, and selections; M3–M7 add concrete execution |
| Video source identity | `RecordingVideoSource` in `pipeline_data.py`, with accepted bundle facts from the backend | M2 resolves frames and crops from this source |
| Event content validation | `EventData` and `EventRecord` in `pipeline_data.py` | M3 publishes generated or imported event revisions; M8–M9 maintain reviewed events |

## Event operations

| Current operation | Retained validator or provider | Replacement milestone |
| --- | --- | --- |
| `CardEventReviewStore` draft commands and completed review validation in `operations/src/doko_operations/cardevent_review.py` | Existing event type, timing, ordering, command, and source validation stays authoritative for the old editor | M8 adapts its edit validation to the maintained event reference; M9 owns coverage and completion |
| `CardEventNetReviewAdapter` and event proposal projection in `operations/src/doko_operations/cardevent.py` | Existing CardEventNet inference and proposal decoding remain the provider boundary | M3 wraps the provider in `ProcessorRunRequest` and publishes `event-data/v1` |
| `cardevent-device-predictions/v1` validation in `schemas/training-recording/device-predictions-v1.schema.json` and recording-bundle validation | Existing device-prediction metadata and timing checks remain valid for imports | M3 imports valid predictions as generated event content without making device media a pipeline source |
| CardEvent review routes in `backend/src/dokodetector_backend/card_event_review_api.py` | Existing HTTP models translated to the old review store | 0049 switched the recording editor to maintained-reference APIs |
| Recording source and accepted video discovery in `recording_bundle_store.py`, `recordings_api.py`, and backend intake contracts | Accepted bundle validation remained the source of recording ID, video path, digest, length, and duration | M1/M2 consumed these facts; 0049 changed UI entry points only |

## Visible-card operations

| Current operation | Retained validator or provider | Replacement milestone |
| --- | --- | --- |
| `VisibleCardReviewBatchStore` and `VisibleCardBatchRequest` in `operations/src/doko_operations/visible_card_review_batch.py` | Existing request, detector identity, frame, geometry, crop, failure, and publication validation remains valid for the old batch | M1 stores pipeline results; M2 owns reusable video-derived views; M4 publishes visible-card revisions |
| `FFmpegVisibleCardFrameExtractor` and `OpenCVVisibleCardFrameExtractor` in `visible_card_review_batch.py` | Existing decoders are retained as tested provider adapters while ownership moves | M2 extracts shared frame selection and crop resolution into `operations/src/doko_operations/derived_view.py` |
| `VisibleCardProvider`, `FakeVisibleCardProvider`, `GeminiVisibleCardProvider`, and `LocalVisibleCardProvider` in `table_evidence_analyzer/src/table_evidence_analyzer/visible_cards.py` | Existing provider interfaces and normalized detector result validation remain authoritative | M4 adapts one explicit provider into the processor run boundary |
| `VisibleCardReviewQueue`, `VisibleCardFrameReview`, and action validation in `table_evidence_analyzer/src/table_evidence_analyzer/visible_card_review_workflow.py` | Existing visible-region meaning, reviewed empty state, unusable state, and action validation remain authoritative | M8 adapts edit validation; M9 owns explicit frame coverage and affected work |
| `VisibleCardReviewBatchStore` in `backend` routes and `visible_card_review_api.py` | Existing batch lifecycle and HTTP translation remained available for the old workspace | 0049 removed the batch entry path after the maintained reference was exposed |

## Visual identity operations

| Current operation | Retained validator or provider | Replacement milestone |
| --- | --- | --- |
| `CardIdentityClassifier`, `CardClassificationResult`, and classifier caching in `table_evidence_analyzer/src/table_evidence_analyzer/card_classification.py` | Existing candidate order, identity values, score handling, and provider errors remain authoritative | M5 adapts the classifier behind an explicit visual-identity processor boundary |
| `DinoV3IdentityConfig` and local identity bundle/runtime contracts in `table_evidence_analyzer/src/table_evidence_analyzer/local_identity.py` | Existing local model identity and crop transform contracts remain authoritative | M5 records implementation and model lineage in the frozen run request |
| `VisualCardIdentityClassifier` and `VisualCardIdentityClassifierIdentity` in `operations/src/doko_operations/visual_card_identity_review_batch.py` | Existing explicit classifier identity and result validation remain authoritative for the old path | M5 reuses the provider through the new run contract |
| `VisualCardIdentityReviewBatchStore` and its decision validation | Existing identity usability, candidate, crop, and failure validation remains authoritative | M8 adapts edit validation; M9 owns card coverage and affected work |
| Identity review routes in `backend/src/dokodetector_backend/visual_card_identity_review_api.py` | Existing HTTP models and batch lifecycle remained available for the old workspace | 0049 removed the batch entry path after maintained references were available |
| Existing identity dataset projection in `operations/src/doko_operations/visual_card_identity_dataset.py` | Existing source permission, development partition, and target checks remain authoritative | M10 consumes explicit completed identity reference revisions and frozen crop policies |

## Observation operations

| Current operation | Retained validator or provider | Replacement milestone |
| --- | --- | --- |
| `TableObservation`, `ObservationSource`, and nested observation validation in `table_evidence_analyzer/src/table_evidence_analyzer/table_observation.py` | Existing observation meanings, identity-only evidence, detected-empty evidence, and insufficient evidence remain authoritative | M6 revises source lineage to recording video, assembly run, and exact input revisions |
| `VisibleCardTableAnalyzer` and `BundleCardClassifier` in `visible_card_observation.py` | Existing observation projection and classifier composition remain reusable behavior | M6 uses them through a pure observation assembler; it does not infer gameplay state |
| `TableObservationReviewAdapter` and package-backed assembly in `operations/src/doko_operations/table_evidence.py` | Existing review adapter and package validator remain available for the legacy package review route | M6 adds observation assembly from selected event, visible-card, and identity revisions |
| `TableObservationStore` and analyzer-facing backend adapters | Existing file validation and observation result handling remain authoritative for old observations | M6 changes uniqueness and searchable identity from package/analyzer to observation ID and run/input lineage |
| Round analysis input assembly in `operations/src/doko_operations/round_reconstruction_execution.py` and `backend/src/dokodetector_backend/round_analysis_service.py` | Existing reconstruction engine, state transitions, result store, timeline, and counterfactual behavior remain authoritative | M7 pins a table-observation revision and explicit round context before queueing |

## Historical legacy entry points

The following paths were available while M0–M10 built the new foundation. They were not new
pipeline inputs and were not valid fallbacks for new processor code.

- Event review: `CardEventReviewStore`, `card_event_review_api.py`, and the `/v1/recordings/{recording_id}/card-event-reviews` and `/v1/recordings/{recording_id}/card-event-review` routes.
- Visible-card review: `VisibleCardReviewBatchStore`, `visible_card_review_api.py`, `visible_card_review_workflow.py`, and the `/v1/recordings/{recording_id}/visible-card-review` and `/v1/visible-card-reviews/{batch_id}` routes.
- Visual identity review: `VisualCardIdentityReviewBatchStore`, `visual_card_identity_review_api.py`, and the `/v1/recordings/{recording_id}/identity-review` and `/v1/identity-reviews/{batch_id}` routes.
- Package-backed evidence and observation review: `evidence_package.py`, `table_evidence.py`, `TableEvidenceReviewAdapter`, `TableObservationReviewAdapter`, and the package/analyzer routes registered by `backend/src/dokodetector_backend/api.py` and `app.py`.
- Device showcase: recording-bundle evidence packaging, package generation, and package upload remain independently usable. Their frames and snippets are not visual inputs for M2–M7.

Epic 0049 removed or redirected the recording-workspace entry points above. This section remains as
historical evidence of the boundary that the completed cutover replaced.
