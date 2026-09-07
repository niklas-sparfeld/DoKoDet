"""HTTP routes for generated pipeline stages and derived views."""

from __future__ import annotations

from typing import Any

from doko_operations.derived_view import DerivedViewError
from fastapi import APIRouter, Request
from fastapi.responses import Response

from dokodetector_backend.errors import ContractError
from dokodetector_backend.observation_pipeline_service import (
    ObservationPipelineError,
    ObservationPipelineInputError,
)
from dokodetector_backend.pipeline_api_contracts import run_response, validate_recording_id
from dokodetector_backend.pipeline_service import (
    EventPipelineService,
    PipelineInputError,
    PipelineServiceError,
)
from dokodetector_backend.pipeline_store import (
    PipelineConflict,
    PipelineNotFound,
    PipelineSelectionConflict,
    PipelineStateError,
)
from dokodetector_backend.visible_card_pipeline_service import (
    VisibleCardPipelineError,
    VisibleCardPipelineInputError,
)
from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineInputError,
)

router = APIRouter()
BASE = "/api/recordings/{recording_id}/pipeline/events"
VISIBLE_CARD_BASE = "/api/recordings/{recording_id}/pipeline/visible-cards"
DERIVED_FRAME_BASE = (
    "/api/recordings/{recording_id}/pipeline/derived-views/exact-event/{requested_time_us}"
)
VISUAL_IDENTITY_BASE = "/api/recordings/{recording_id}/pipeline/visual-identities"
IDENTITY_CROP_BASE = (
    "/api/recordings/{recording_id}/pipeline/derived-views/identity-crops/{revision_id}/{item_id}"
)
OBSERVATION_BASE = "/api/recordings/{recording_id}/pipeline/observations"


def _event_service(request: Request) -> EventPipelineService:
    return request.app.state.event_pipeline_service


def _visible_service(request: Request) -> Any:
    return request.app.state.visible_card_pipeline_service


def _visual_identity_service(request: Request) -> Any:
    return request.app.state.visual_identity_pipeline_service


def _observation_service(request: Request) -> Any:
    return request.app.state.observation_pipeline_service


@router.post(BASE, status_code=202)
@router.post(BASE + "/runs", status_code=202, include_in_schema=False)
def start_event_run(recording_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Freeze and queue one event processor request."""

    service = _event_service(request)
    validate_recording_id(recording_id)
    try:
        return run_response(service.start_inference(recording_id, payload))
    except (PipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(BASE)
@router.get(BASE + "/runs", include_in_schema=False)
def list_event_runs(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable event processor runs for one recording."""

    validate_recording_id(recording_id)
    try:
        runs = _event_service(request).list_runs(recording_id)
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [run_response(run) for run in runs]}


@router.post(BASE + "/import", status_code=201)
@router.post(BASE + "/imports", status_code=201, include_in_schema=False)
def import_event_predictions(
    recording_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Validate and import one recording-bundle event prediction artifact."""

    validate_recording_id(recording_id)
    try:
        run = _event_service(request).import_predictions(recording_id, payload)
        return run_response(run)
    except PipelineInputError as error:
        raise ContractError("invalid_event_import", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except PipelineConflict as error:
        raise ContractError("pipeline_conflict", str(error), status_code=409) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(BASE + "/selection")
@router.get(BASE + "/generated-selection", include_in_schema=False)
def get_generated_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current generated and completed-reference event pointers."""

    validate_recording_id(recording_id)
    selection = _event_service(request).selection_store.get(recording_id, "events")
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(BASE + "/selection")
@router.put(BASE + "/generated-selection", include_in_schema=False)
def update_generated_selection(
    recording_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Update the generated event pointer with an optimistic revision check."""

    validate_recording_id(recording_id)
    try:
        selection = _event_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (PipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(BASE + "/{run_id}")
@router.get(BASE + "/runs/{run_id}", include_in_schema=False)
def get_event_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one event processor run and its immutable request."""

    try:
        return run_response(_event_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(BASE + "/{run_id}/retry", status_code=202)
@router.post(BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_event_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed or partial event processor run."""

    try:
        return run_response(_event_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (PipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(BASE + "/{run_id}/result")
@router.get(BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_event_result(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return a completed event run and its stored data revisions."""

    try:
        run, revisions = _event_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(VISIBLE_CARD_BASE, status_code=202)
@router.post(VISIBLE_CARD_BASE + "/runs", status_code=202, include_in_schema=False)
def start_visible_card_run(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze one event revision and queue a visible-card detector run."""

    validate_recording_id(recording_id)
    try:
        return run_response(_visible_service(request).start_detection(recording_id, payload))
    except (VisibleCardPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISIBLE_CARD_BASE)
@router.get(VISIBLE_CARD_BASE + "/runs", include_in_schema=False)
def list_visible_card_runs(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable visible-card detector runs for one recording."""

    validate_recording_id(recording_id)
    try:
        runs = _visible_service(request).list_runs(recording_id)
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [run_response(run) for run in runs]}


@router.get(VISIBLE_CARD_BASE + "/selection")
@router.get(VISIBLE_CARD_BASE + "/generated-selection", include_in_schema=False)
def get_visible_card_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current visible-card generated and reference pointers."""

    validate_recording_id(recording_id)
    selection = _visible_service(request).selection_store.get(recording_id, "visible_cards")
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(VISIBLE_CARD_BASE + "/selection")
@router.put(VISIBLE_CARD_BASE + "/generated-selection", include_in_schema=False)
def update_visible_card_selection(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Update the visible-card generated pointer with an optimistic revision check."""

    validate_recording_id(recording_id)
    try:
        selection = _visible_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (VisibleCardPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(VISIBLE_CARD_BASE + "/{run_id}")
@router.get(VISIBLE_CARD_BASE + "/runs/{run_id}", include_in_schema=False)
def get_visible_card_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one visible-card detector run and its immutable request."""

    try:
        return run_response(_visible_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(VISIBLE_CARD_BASE + "/{run_id}/retry", status_code=202)
@router.post(VISIBLE_CARD_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_visible_card_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed visible-card detector run."""

    try:
        return run_response(_visible_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (VisibleCardPipelineInputError, PipelineConflict, PipelineStateError) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISIBLE_CARD_BASE + "/{run_id}/result")
@router.get(VISIBLE_CARD_BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_visible_card_result(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one completed visible-card detector run and its stored revision."""

    try:
        run, revisions = _visible_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.get(DERIVED_FRAME_BASE, response_class=Response)
def get_recording_exact_event_frame(
    recording_id: str, requested_time_us: int, request: Request
) -> Response:
    """Return one verified exact-event frame resolved from the accepted recording video."""

    validate_recording_id(recording_id)
    if requested_time_us < 0:
        raise ContractError(
            "invalid_derived_view_request",
            "requested_time_us must be non-negative.",
            status_code=422,
        )
    try:
        frame = _visible_service(request).resolve_source_frame(recording_id, requested_time_us)
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except (VisibleCardPipelineInputError, DerivedViewError, OSError, RuntimeError) as error:
        raise ContractError("derived_view_unavailable", str(error), status_code=409) from error
    return Response(
        content=frame.image_bytes,
        media_type=frame.content_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"{frame.image_sha256}"',
        },
    )


@router.get(IDENTITY_CROP_BASE, response_class=Response)
def get_recording_identity_crop(
    recording_id: str, revision_id: str, item_id: str, request: Request
) -> Response:
    """Return one verified identity crop derived from a stored identity revision."""

    validate_recording_id(recording_id)
    try:
        crop = _visual_identity_service(request).resolve_identity_crop(
            recording_id, revision_id, item_id
        )
    except PipelineNotFound as error:
        raise ContractError("identity_crop_not_found", str(error), status_code=404) from error
    except (VisualIdentityPipelineInputError, DerivedViewError, OSError, RuntimeError) as error:
        raise ContractError("derived_view_unavailable", str(error), status_code=409) from error
    if crop.image_bytes is None:
        raise ContractError(
            "identity_crop_unavailable",
            crop.unusable_reason or "The identity crop is unavailable.",
            status_code=409,
        )
    return Response(
        content=crop.image_bytes,
        media_type=crop.content_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"{crop.image_sha256}"',
        },
    )


@router.post(VISUAL_IDENTITY_BASE, status_code=202)
@router.post(VISUAL_IDENTITY_BASE + "/runs", status_code=202, include_in_schema=False)
def start_visual_identity_run(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze one visible-card revision and queue identity classification."""

    validate_recording_id(recording_id)
    try:
        return run_response(
            _visual_identity_service(request).start_classification(recording_id, payload)
        )
    except (VisualIdentityPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISUAL_IDENTITY_BASE)
@router.get(VISUAL_IDENTITY_BASE + "/runs", include_in_schema=False)
def list_visual_identity_runs(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable visual identity classifier runs for one recording."""

    validate_recording_id(recording_id)
    try:
        runs = _visual_identity_service(request).list_runs(recording_id)
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [run_response(run) for run in runs]}


@router.get(VISUAL_IDENTITY_BASE + "/selection")
@router.get(VISUAL_IDENTITY_BASE + "/generated-selection", include_in_schema=False)
def get_visual_identity_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current visual identity generated and reference pointers."""

    validate_recording_id(recording_id)
    selection = _visual_identity_service(request).selection_store.get(
        recording_id, "visual_identities"
    )
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(VISUAL_IDENTITY_BASE + "/selection")
@router.put(VISUAL_IDENTITY_BASE + "/generated-selection", include_in_schema=False)
def update_visual_identity_selection(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Update the visual identity generated pointer with an optimistic revision check."""

    validate_recording_id(recording_id)
    try:
        selection = _visual_identity_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (VisualIdentityPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(VISUAL_IDENTITY_BASE + "/{run_id}")
@router.get(VISUAL_IDENTITY_BASE + "/runs/{run_id}", include_in_schema=False)
def get_visual_identity_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one visual identity classifier run and its immutable request."""

    try:
        return run_response(_visual_identity_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(VISUAL_IDENTITY_BASE + "/{run_id}/retry", status_code=202)
@router.post(
    VISUAL_IDENTITY_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False
)
def retry_visual_identity_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed visual identity classifier run."""

    try:
        return run_response(_visual_identity_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (VisualIdentityPipelineInputError, PipelineConflict, PipelineStateError) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISUAL_IDENTITY_BASE + "/{run_id}/result")
@router.get(VISUAL_IDENTITY_BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_visual_identity_result(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return a completed visual identity run and its stored revision."""

    try:
        run, revisions = _visual_identity_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(OBSERVATION_BASE, status_code=202)
@router.post(OBSERVATION_BASE + "/runs", status_code=202, include_in_schema=False)
def start_observation_assembly(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze three selected revisions and queue observation assembly."""

    validate_recording_id(recording_id)
    try:
        return run_response(_observation_service(request).start_assembly(recording_id, payload))
    except (ObservationPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(OBSERVATION_BASE)
@router.get(OBSERVATION_BASE + "/runs", include_in_schema=False)
def list_observation_assemblies(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable observation assembly runs for one recording."""

    validate_recording_id(recording_id)
    try:
        runs = _observation_service(request).list_runs(recording_id)
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [run_response(run) for run in runs]}


@router.get(OBSERVATION_BASE + "/selection")
@router.get(OBSERVATION_BASE + "/generated-selection", include_in_schema=False)
def get_observation_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current table-observation generated and reference pointers."""

    validate_recording_id(recording_id)
    selection = _observation_service(request).selection_store.get(
        recording_id, "table_observations"
    )
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(OBSERVATION_BASE + "/selection")
@router.put(OBSERVATION_BASE + "/generated-selection", include_in_schema=False)
def update_observation_selection(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Update the generated table-observation pointer with an optimistic revision check."""

    validate_recording_id(recording_id)
    try:
        selection = _observation_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (ObservationPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(OBSERVATION_BASE + "/{run_id}")
@router.get(OBSERVATION_BASE + "/runs/{run_id}", include_in_schema=False)
def get_observation_assembly(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one observation assembly run and its immutable request."""

    try:
        return run_response(_observation_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(OBSERVATION_BASE + "/{run_id}/retry", status_code=202)
@router.post(OBSERVATION_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_observation_assembly(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed observation assembly run."""

    try:
        return run_response(_observation_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (ObservationPipelineInputError, PipelineConflict, PipelineStateError) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(OBSERVATION_BASE + "/{run_id}/result")
@router.get(OBSERVATION_BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_observation_assembly_result(
    recording_id: str, run_id: str, request: Request
) -> dict[str, Any]:
    """Return one completed observation assembly and its stored revision."""

    try:
        run, revisions = _observation_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


__all__ = ["router"]
