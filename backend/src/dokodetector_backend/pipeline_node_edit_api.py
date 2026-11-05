"""HTTP routes for atomic lineage node edits, copies, and restores."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import ContractError
from dokodetector_backend.pipeline_node_store import NodeConflict

router = APIRouter(prefix="/api/pipeline/nodes")


class PipelineNodeEditRequest(ContractModel):
    expected_revision_id: str
    idempotency_key: str = Field(min_length=1)
    actor: dict[str, Any]
    content: dict[str, Any]
    pointers: dict[str, str] | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)
    evidence: Any = None


class PipelineNodeCopyRequest(ContractModel):
    revision_id: str
    idempotency_key: str = Field(min_length=1)
    actor: dict[str, Any]
    reason: str = Field(min_length=1)


class PipelineNodeRestoreRequest(ContractModel):
    expected_revision_id: str
    historical_revision_id: str
    idempotency_key: str = Field(min_length=1)
    actor: dict[str, Any]
    pointers: dict[str, str] | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)
    evidence: Any = None


def _execute(operation):
    try:
        return operation()
    except NodeConflict as error:
        raise ContractError("pipeline_node_conflict", str(error), status_code=409) from error
    except (ValueError, OSError) as error:
        raise ContractError("pipeline_node_edit_failed", str(error), status_code=422) from error


@router.post("/{node_id}/edit")
def edit_pipeline_node(
    node_id: str, body: PipelineNodeEditRequest, request: Request
) -> dict[str, Any]:
    """Save the first changed content, copying automatically when accepted use protects it."""
    return _execute(
        lambda: request.app.state.pipeline_node_edits.edit(
            node_id,
            body.expected_revision_id,
            body.content,
            body.idempotency_key,
            body.actor,
            pointers=body.pointers,
            operations=body.operations,
            evidence=body.evidence,
        )
    )


@router.post("/{node_id}/copy")
def copy_pipeline_node(
    node_id: str, body: PipelineNodeCopyRequest, request: Request
) -> dict[str, Any]:
    """Create an explicitly requested copy of an exact saved revision."""
    result = _execute(
        lambda: request.app.state.pipeline_node_edits.copy(
            node_id,
            body.revision_id,
            body.idempotency_key,
            body.actor,
            reason=body.reason,
        )
    )
    result["name"] = request.app.state.pipeline_node_edits.store.get(result["node_id"]).name
    return result


@router.post("/{node_id}/restore")
def restore_pipeline_node(
    node_id: str, body: PipelineNodeRestoreRequest, request: Request
) -> dict[str, Any]:
    """Restore a historical revision through the same protected edit transaction."""
    return _execute(
        lambda: request.app.state.pipeline_node_edits.restore(
            node_id,
            body.expected_revision_id,
            body.historical_revision_id,
            body.idempotency_key,
            body.actor,
            pointers=body.pointers,
            operations=body.operations,
            evidence=body.evidence,
        )
    )
