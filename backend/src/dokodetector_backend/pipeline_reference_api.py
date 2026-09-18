"""HTTP routes for maintained pipeline references."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.pipeline_api_contracts import reference_response, validate_recording_id
from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceConflict,
    PipelineReferenceCoverageError,
    PipelineReferenceError,
    PipelineReferenceInputError,
)
from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceNotFound,
    PipelineReferenceStoreError,
)
from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineInputError,
)

router = APIRouter()
REFERENCE_BASE = "/api/recordings/{recording_id}/pipeline/references/{content_type}"
REFERENCE_STAGE_BASE = "/api/recordings/{recording_id}/pipeline/{content_type}/reference"


class AutoApprovalResultResponse(ContractModel):
    """One retained classifier outcome used by an auto-approval decision."""

    result_id: str
    classifier: dict[str, Any]


class AutoApprovalItemResponse(ContractModel):
    """One draft item and its retained Gemini/local comparison result."""

    item_id: str
    reason: Literal[
        "eligible",
        "already_reviewed",
        "gemini_unavailable",
        "gemini_face_down",
        "gemini_unusable",
        "gemini_failed",
        "local_unavailable",
        "local_face_down",
        "local_unusable",
        "local_failed",
        "identity_mismatch",
    ]
    eligible: bool
    gemini_result: AutoApprovalResultResponse | None
    local_result: AutoApprovalResultResponse | None


class AutoApprovalLocalRunResponse(ContractModel):
    """The one configured local run started or reused for this comparison."""

    run_id: str
    status: Literal["queued", "running", "complete", "partial", "failed"]
    attempt: int = Field(gt=0)


class AutoApprovalPlanResponse(ContractModel):
    """The immutable inputs and current decisions for an auto-approval attempt."""

    recording_id: str
    draft_revision: int = Field(ge=0)
    source_revision_id: str
    local_run: AutoApprovalLocalRunResponse | None
    items: list[AutoApprovalItemResponse]


class AutoApprovalApplyRequest(ContractModel):
    """The optimistic command that applies the currently eligible decisions."""

    expected_revision: int = Field(ge=0)
    operator_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)


class AutoApprovalReceiptResponse(ContractModel):
    """The durable receipt for one revision-guarded auto-approval command."""

    schema_version: Literal["visual-identity-auto-approval-receipt/v1"]
    recording_id: str
    command_id: str
    draft_revision: int = Field(ge=0)
    source_revision_id: str
    accepted_item_ids: list[str]
    comparisons: list[AutoApprovalItemResponse]


def _reference_service(request: Request) -> Any:
    return request.app.state.pipeline_reference_service


def _visual_identity_service(request: Request) -> Any:
    return request.app.state.visual_identity_pipeline_service


@router.get(REFERENCE_BASE)
@router.get(REFERENCE_STAGE_BASE, include_in_schema=False)
def get_reference(recording_id: str, content_type: str, request: Request) -> dict[str, Any]:
    """Return one maintained reference draft and its current pointer."""

    validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).get_reference(recording_id, content_type)
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except (PipelineReferenceInputError, PipelineReferenceStoreError) as error:
        raise ContractError("reference_unavailable", str(error), status_code=409) from error
    return reference_response(reference)


@router.post(
    "/api/recordings/{recording_id}/pipeline/visual-identities/auto-approval-plan",
    status_code=202,
    response_model=AutoApprovalPlanResponse,
)
def plan_visual_identity_auto_approval(recording_id: str, request: Request) -> dict[str, Any]:
    """Compare a visual identity draft with retained local results and queue local work once."""

    validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).get_reference(recording_id, "visual_identities")
        source_revision_id = reference.draft.source_revision_id
        if source_revision_id is None:
            raise PipelineReferenceInputError("The visual identity draft has no generated source.")
        return {
            "recording_id": recording_id,
            "draft_revision": reference.state.draft_revision,
            **_visual_identity_service(request).plan_auto_approval(
                recording_id,
                source_revision_id,
                tuple(item.to_mapping() for item in reference.draft.items),
            ),
        }
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except (PipelineReferenceInputError, VisualIdentityPipelineInputError) as error:
        raise ContractError("invalid_auto_approval_request", str(error), status_code=422) from error
    except (PipelineReferenceError, VisualIdentityPipelineError) as error:
        raise ContractError("auto_approval_unavailable", str(error), status_code=503) from error


@router.post(
    "/api/recordings/{recording_id}/pipeline/visual-identities/auto-approval",
    response_model=AutoApprovalReceiptResponse,
)
def apply_visual_identity_auto_approval(
    recording_id: str, payload: AutoApprovalApplyRequest, request: Request
) -> dict[str, Any]:
    """Accept only current matching Gemini/local draft items with one guarded command."""

    validate_recording_id(recording_id)
    reference_service = _reference_service(request)
    receipt_store = request.app.state.pipeline_reference_store
    try:
        existing = receipt_store.get_auto_approval_receipt(
            recording_id, "visual_identities", payload.command_id
        )
        if existing is not None:
            return existing
        reference = reference_service.get_reference(recording_id, "visual_identities")
        if reference.state.draft_revision != payload.expected_revision:
            raise PipelineReferenceConflict(
                "the maintained reference draft changed; reload the current revision", reference
            )
        source_revision_id = reference.draft.source_revision_id
        if source_revision_id is None:
            raise PipelineReferenceInputError("The visual identity draft has no generated source.")
        plan = _visual_identity_service(request).plan_auto_approval(
            recording_id,
            source_revision_id,
            tuple(item.to_mapping() for item in reference.draft.items),
        )
        comparisons = plan["items"]
        accepted_item_ids = [item["item_id"] for item in comparisons if item["eligible"]]
        if accepted_item_ids:
            reference_service.update_draft(
                recording_id,
                "visual_identities",
                {
                    "expected_revision": payload.expected_revision,
                    "operator_id": payload.operator_id,
                    "command_id": payload.command_id,
                    "operations": [
                        {"operation": "accept_identity_suggestion", "item_id": item_id}
                        for item_id in accepted_item_ids
                    ],
                },
            )
        receipt = {
            "schema_version": "visual-identity-auto-approval-receipt/v1",
            "recording_id": recording_id,
            "command_id": payload.command_id,
            "draft_revision": payload.expected_revision,
            "source_revision_id": source_revision_id,
            "accepted_item_ids": accepted_item_ids,
            "comparisons": comparisons,
        }
        receipt_store.write_auto_approval_receipt(
            recording_id, "visual_identities", payload.command_id, receipt
        )
        return receipt
    except PipelineReferenceConflict as error:
        raise ContractError(
            "reference_conflict",
            str(error),
            status_code=409,
            details=[
                APIErrorDetail(
                    field="current_revision", message=str(error.current.state.draft_revision)
                )
            ],
        ) from error
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except (PipelineReferenceInputError, VisualIdentityPipelineInputError) as error:
        raise ContractError("invalid_auto_approval_request", str(error), status_code=422) from error
    except (PipelineReferenceError, VisualIdentityPipelineError) as error:
        raise ContractError("auto_approval_unavailable", str(error), status_code=503) from error


@router.post(REFERENCE_BASE, status_code=201)
@router.post(REFERENCE_STAGE_BASE, status_code=201, include_in_schema=False)
def create_reference(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Create the one recording-owned reference, seeded from a result or empty."""

    validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).create_reference(
            recording_id, content_type, payload
        )
    except PipelineReferenceConflict as error:
        raise ContractError("reference_conflict", str(error), status_code=409) from error
    except PipelineReferenceInputError as error:
        raise ContractError("invalid_reference_request", str(error), status_code=422) from error
    except PipelineReferenceError as error:
        raise ContractError("reference_unavailable", str(error), status_code=503) from error
    return reference_response(reference)


@router.put(REFERENCE_BASE + "/draft")
@router.put(REFERENCE_STAGE_BASE + "/draft", include_in_schema=False)
def update_reference_draft(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Apply conflict-safe review operations to the current reference draft."""

    validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).update_draft(recording_id, content_type, payload)
    except PipelineReferenceConflict as error:
        raise ContractError(
            "reference_conflict",
            str(error),
            status_code=409,
            details=[
                APIErrorDetail(
                    field="current_revision",
                    message=str(error.current.state.draft_revision),
                )
            ],
        ) from error
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except PipelineReferenceInputError as error:
        raise ContractError("invalid_reference_edit", str(error), status_code=422) from error
    except PipelineReferenceError as error:
        raise ContractError("reference_unavailable", str(error), status_code=503) from error
    return reference_response(reference)


@router.post(REFERENCE_BASE + "/complete", status_code=201)
@router.post(REFERENCE_STAGE_BASE + "/complete", status_code=201, include_in_schema=False)
def complete_reference(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Publish the reviewed draft as an immutable completed reference revision."""

    validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).complete_reference(
            recording_id, content_type, payload
        )
    except PipelineReferenceConflict as error:
        raise ContractError(
            "reference_conflict",
            str(error),
            status_code=409,
            details=[
                APIErrorDetail(
                    field="current_revision",
                    message=str(error.current.state.draft_revision),
                )
            ],
        ) from error
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except PipelineReferenceCoverageError as error:
        raise ContractError(
            "incomplete_reference_coverage",
            str(error),
            status_code=422,
            details=[APIErrorDetail(**detail) for detail in error.details],
        ) from error
    except PipelineReferenceInputError as error:
        raise ContractError("invalid_reference_completion", str(error), status_code=422) from error
    except PipelineReferenceError as error:
        raise ContractError("reference_unavailable", str(error), status_code=503) from error
    return reference_response(reference)


__all__ = ["router"]
