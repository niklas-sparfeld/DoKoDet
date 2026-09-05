"""HTTP routes for recording event processor runs."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request

from dokodetector_backend.errors import ContractError
from dokodetector_backend.observation_pipeline_service import (
    ObservationPipelineError,
    ObservationPipelineInputError,
    ObservationPipelineService,
)
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
    VisibleCardPipelineService,
)
from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineInputError,
    VisualIdentityPipelineService,
)

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
BASE = "/api/recordings/{recording_id}/pipeline/events"
VISIBLE_CARD_BASE = "/api/recordings/{recording_id}/pipeline/visible-cards"
VISUAL_IDENTITY_BASE = "/api/recordings/{recording_id}/pipeline/visual-identities"
OBSERVATION_BASE = "/api/recordings/{recording_id}/pipeline/observations"


@router.post(BASE, status_code=202)
@router.post(BASE + "/runs", status_code=202, include_in_schema=False)
def start_event_run(recording_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Freeze and queue one event processor request."""

    service = _service(request)
    _validate_recording_id(recording_id)
    try:
        return _run_response(service.start_inference(recording_id, payload))
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

    _validate_recording_id(recording_id)
    try:
        runs = _service(request).list_runs(recording_id)
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.post(BASE + "/import", status_code=201)
@router.post(BASE + "/imports", status_code=201, include_in_schema=False)
def import_event_predictions(
    recording_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Validate and import one recording-bundle event prediction artifact."""

    _validate_recording_id(recording_id)
    try:
        run = _service(request).import_predictions(recording_id, payload)
        return _run_response(run)
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

    _validate_recording_id(recording_id)
    selection = _service(request).selection_store.get(recording_id, "events")
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

    _validate_recording_id(recording_id)
    try:
        selection = _service(request).select_generated(recording_id, payload)
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
        return _run_response(_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(BASE + "/{run_id}/retry", status_code=202)
@router.post(BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_event_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed or partial event processor run."""

    try:
        return _run_response(_service(request).retry(recording_id, run_id))
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
        run, revisions = _service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(VISIBLE_CARD_BASE, status_code=202)
@router.post(VISIBLE_CARD_BASE + "/runs", status_code=202, include_in_schema=False)
def start_visible_card_run(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze one event revision and queue a visible-card detector run."""

    _validate_recording_id(recording_id)
    try:
        return _run_response(_visible_service(request).start_detection(recording_id, payload))
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

    _validate_recording_id(recording_id)
    try:
        runs = _visible_service(request).list_runs(recording_id)
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.get(VISIBLE_CARD_BASE + "/selection")
@router.get(VISIBLE_CARD_BASE + "/generated-selection", include_in_schema=False)
def get_visible_card_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current visible-card generated and reference pointers."""

    _validate_recording_id(recording_id)
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

    _validate_recording_id(recording_id)
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
        return _run_response(_visible_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(VISIBLE_CARD_BASE + "/{run_id}/retry", status_code=202)
@router.post(VISIBLE_CARD_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_visible_card_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed visible-card detector run."""

    try:
        return _run_response(_visible_service(request).retry(recording_id, run_id))
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
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(VISUAL_IDENTITY_BASE, status_code=202)
@router.post(VISUAL_IDENTITY_BASE + "/runs", status_code=202, include_in_schema=False)
def start_visual_identity_run(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze one visible-card revision and queue identity classification."""

    _validate_recording_id(recording_id)
    try:
        return _run_response(
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

    _validate_recording_id(recording_id)
    try:
        runs = _visual_identity_service(request).list_runs(recording_id)
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.get(VISUAL_IDENTITY_BASE + "/selection")
@router.get(VISUAL_IDENTITY_BASE + "/generated-selection", include_in_schema=False)
def get_visual_identity_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current visual identity generated and reference pointers."""

    _validate_recording_id(recording_id)
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

    _validate_recording_id(recording_id)
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
        return _run_response(_visual_identity_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(VISUAL_IDENTITY_BASE + "/{run_id}/retry", status_code=202)
@router.post(
    VISUAL_IDENTITY_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False
)
def retry_visual_identity_run(
    recording_id: str, run_id: str, request: Request
) -> dict[str, Any]:
    """Retry one failed visual identity classifier run."""

    try:
        return _run_response(_visual_identity_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (VisualIdentityPipelineInputError, PipelineConflict, PipelineStateError) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISUAL_IDENTITY_BASE + "/{run_id}/result")
@router.get(VISUAL_IDENTITY_BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_visual_identity_result(
    recording_id: str, run_id: str, request: Request
) -> dict[str, Any]:
    """Return a completed visual identity run and its stored revision."""

    try:
        run, revisions = _visual_identity_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(OBSERVATION_BASE, status_code=202)
@router.post(OBSERVATION_BASE + "/runs", status_code=202, include_in_schema=False)
def start_observation_assembly(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze three selected revisions and queue observation assembly."""

    _validate_recording_id(recording_id)
    try:
        return _run_response(_observation_service(request).start_assembly(recording_id, payload))
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

    _validate_recording_id(recording_id)
    try:
        runs = _observation_service(request).list_runs(recording_id)
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.get(OBSERVATION_BASE + "/selection")
@router.get(OBSERVATION_BASE + "/generated-selection", include_in_schema=False)
def get_observation_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current table-observation generated and reference pointers."""

    _validate_recording_id(recording_id)
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

    _validate_recording_id(recording_id)
    try:
        selection = _observation_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (ObservationPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(OBSERVATION_BASE + "/{run_id}")
@router.get(OBSERVATION_BASE + "/runs/{run_id}", include_in_schema=False)
def get_observation_assembly(
    recording_id: str, run_id: str, request: Request
) -> dict[str, Any]:
    """Return one observation assembly run and its immutable request."""

    try:
        return _run_response(_observation_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(OBSERVATION_BASE + "/{run_id}/retry", status_code=202)
@router.post(OBSERVATION_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_observation_assembly(
    recording_id: str, run_id: str, request: Request
) -> dict[str, Any]:
    """Retry one failed observation assembly run."""

    try:
        return _run_response(_observation_service(request).retry(recording_id, run_id))
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
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


def _service(request: Request) -> EventPipelineService:
    return request.app.state.event_pipeline_service


def _visible_service(request: Request) -> VisibleCardPipelineService:
    return request.app.state.visible_card_pipeline_service


def _visual_identity_service(request: Request) -> VisualIdentityPipelineService:
    return request.app.state.visual_identity_pipeline_service


def _observation_service(request: Request) -> ObservationPipelineService:
    return request.app.state.observation_pipeline_service


def _validate_recording_id(recording_id: str) -> None:
    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")


def _run_response(run: Any) -> dict[str, Any]:
    request = run.request.to_mapping()
    state = run.state.to_mapping()
    return {
        "run_id": run.run_id,
        "recording_id": run.request.source.recording_id,
        "processor_type": run.request.processor_type,
        "status": run.state.status,
        "attempt": run.state.attempt,
        "request": request,
        "state": state,
    }


__all__ = ["router"]
