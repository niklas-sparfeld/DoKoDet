"""HTTP routes for independent visible-card reviews."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.pipeline_api_contracts import validate_recording_id
from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceConflict,
    PipelineReferenceCoverageError,
    PipelineReferenceError,
    PipelineReferenceInputError,
)
from dokodetector_backend.pipeline_reference_store import PipelineReferenceNotFound
from dokodetector_backend.visible_card_review_store import (
    VisibleCardReviewConflict,
    VisibleCardReviewStoreError,
)

router = APIRouter()
BASE = "/api/recordings/{recording_id}/pipeline/visible-card-reviews"


def _service(request: Request) -> Any:
    return request.app.state.visible_card_review_service


def _summary(review: Any) -> dict[str, Any]:
    return {
        "review_id": review.review_id,
        "recording_id": review.recording_id,
        "status": review.status,
        "source": review.source,
        "lineage": review.lineage,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
        "draft_revision": review.reference.draft.revision,
        "legacy": review.legacy,
    }


def _detail(review: Any) -> dict[str, Any]:
    return {
        **_summary(review),
        "state": review.reference.state.to_mapping(),
        "draft": review.reference.draft.to_mapping(),
    }


@router.get(BASE)
def list_visible_card_reviews(recording_id: str, request: Request) -> dict[str, Any]:
    validate_recording_id(recording_id)
    try:
        reviews = _service(request).list(recording_id)
    except (PipelineReferenceError, VisibleCardReviewStoreError) as error:
        raise ContractError(
            "visible_card_reviews_unavailable", str(error), status_code=503
        ) from error
    return {"recording_id": recording_id, "reviews": [_summary(item) for item in reviews]}


@router.post(BASE, status_code=201)
def create_visible_card_review(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    validate_recording_id(recording_id)
    try:
        return _detail(_service(request).create(recording_id, payload))
    except PipelineReferenceInputError as error:
        raise ContractError("invalid_visible_card_review", str(error), status_code=422) from error
    except VisibleCardReviewConflict as error:
        raise ContractError("visible_card_review_conflict", str(error), status_code=409) from error
    except PipelineReferenceConflict as error:
        raise ContractError("visible_card_review_conflict", str(error), status_code=409) from error
    except PipelineReferenceError as error:
        raise ContractError(
            "visible_card_review_unavailable", str(error), status_code=503
        ) from error


@router.get(BASE + "/{review_id}")
def get_visible_card_review(recording_id: str, review_id: str, request: Request) -> dict[str, Any]:
    validate_recording_id(recording_id)
    try:
        return _detail(_service(request).get(recording_id, review_id))
    except PipelineReferenceNotFound as error:
        raise ContractError("visible_card_review_not_found", str(error), status_code=404) from error
    except (PipelineReferenceError, VisibleCardReviewStoreError) as error:
        raise ContractError(
            "visible_card_review_unavailable", str(error), status_code=409
        ) from error


@router.put(BASE + "/{review_id}/draft")
def update_visible_card_review(
    recording_id: str, review_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    validate_recording_id(recording_id)
    try:
        review = _service(request).update(recording_id, review_id, payload)
        return {
            **_detail(review),
            "command_receipt": {
                "review_id": review_id,
                "command_id": payload["command_id"],
                "draft_revision": review.reference.draft.revision,
            },
        }
    except PipelineReferenceConflict as error:
        raise ContractError(
            "visible_card_review_conflict",
            str(error),
            status_code=409,
            details=[
                APIErrorDetail(
                    field="current_revision", message=str(error.current.state.draft_revision)
                )
            ],
        ) from error
    except PipelineReferenceNotFound as error:
        raise ContractError("visible_card_review_not_found", str(error), status_code=404) from error
    except PipelineReferenceInputError as error:
        raise ContractError(
            "invalid_visible_card_review_edit", str(error), status_code=422
        ) from error
    except (PipelineReferenceError, VisibleCardReviewStoreError) as error:
        raise ContractError(
            "visible_card_review_unavailable", str(error), status_code=503
        ) from error


@router.post(BASE + "/{review_id}/complete", status_code=201)
def complete_visible_card_review(
    recording_id: str, review_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    validate_recording_id(recording_id)
    try:
        return _detail(_service(request).complete(recording_id, review_id, payload))
    except PipelineReferenceConflict as error:
        raise ContractError("visible_card_review_conflict", str(error), status_code=409) from error
    except PipelineReferenceCoverageError as error:
        raise ContractError(
            "incomplete_visible_card_review",
            str(error),
            status_code=422,
            details=[APIErrorDetail(**detail) for detail in error.details],
        ) from error
    except PipelineReferenceInputError as error:
        raise ContractError(
            "invalid_visible_card_review_completion", str(error), status_code=422
        ) from error
    except PipelineReferenceError as error:
        raise ContractError(
            "visible_card_review_unavailable", str(error), status_code=503
        ) from error


@router.post(BASE + "/{review_id}/select")
def select_completed_visible_card_review(
    recording_id: str, review_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    validate_recording_id(recording_id)
    if set(payload) != {"expected_selection_revision"}:
        raise ContractError(
            "invalid_visible_card_review_selection",
            "expected_selection_revision is required",
            status_code=422,
        )
    try:
        selection = _service(request).select_completed(
            recording_id, review_id, payload["expected_selection_revision"]
        )
    except PipelineReferenceConflict as error:
        raise ContractError(
            "visible_card_review_selection_conflict", str(error), status_code=409
        ) from error
    except PipelineReferenceNotFound as error:
        raise ContractError("visible_card_review_not_found", str(error), status_code=404) from error
    except PipelineReferenceInputError as error:
        raise ContractError(
            "invalid_visible_card_review_selection", str(error), status_code=422
        ) from error
    except (PipelineReferenceError, VisibleCardReviewStoreError) as error:
        raise ContractError(
            "visible_card_review_unavailable", str(error), status_code=503
        ) from error
    return {"selection": selection}
__all__ = ["router"]
