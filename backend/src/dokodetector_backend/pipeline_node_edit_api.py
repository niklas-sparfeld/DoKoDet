"""HTTP routes for atomic lineage node edits, copies, and restores."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import ContractError
from dokodetector_backend.pipeline_node_store import NodeConflict

router = APIRouter(prefix="/api/pipeline/nodes")


class PipelineNodeItemReviewRequest(ContractModel):
    review_id: str = Field(min_length=1)
    revision_id: str
    item_id: str
    question: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    reviewer: dict[str, Any]
    evidence: dict[str, Any]


class PipelineNodeCoverageReviewRequest(ContractModel):
    review_id: str = Field(min_length=1)
    revision_id: str
    question: str = Field(min_length=1)
    coverage: dict[str, Any]
    reviewer: dict[str, Any]
    evidence: dict[str, Any]


class PipelineNodeOverallReviewRequest(ContractModel):
    review_id: str = Field(min_length=1)
    revision_id: str
    question: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    reviewer: dict[str, Any]
    evidence: dict[str, Any]


class PipelineNodeEditRequest(ContractModel):
    expected_revision_id: str
    idempotency_key: str = Field(min_length=1)
    actor: dict[str, Any]
    content: dict[str, Any]
    pointers: dict[str, str] | None = None
    base_pointers: dict[str, str] | None = None
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
    result = _execute(
        lambda: request.app.state.pipeline_node_edits.edit(
            node_id,
            body.expected_revision_id,
            body.content,
            body.idempotency_key,
            body.actor,
            pointers=body.pointers,
            base_pointers=body.base_pointers,
            operations=body.operations,
            evidence=body.evidence,
        )
    )
    result["name"] = request.app.state.pipeline_node_edits.store.get(result["node_id"]).name
    return result


@router.get("/{node_id}/revisions/{revision_id}")
def get_pipeline_node_revision(node_id: str, revision_id: str, request: Request) -> dict[str, Any]:
    """Return the immutable content and metadata for one exact node revision."""
    try:
        node = request.app.state.pipeline_node_edits.store.get(node_id)
        revision = request.app.state.pipeline_node_edits.store.read_revision(node_id, revision_id)
        return {
            "node_id": node.node_id,
            "name": node.name,
            "content_type": node.content_type,
            "source": node.source,
            "head_revision_id": node.head_revision_id,
            "revision_id": revision.revision_id,
            "parent_revision_id": revision.parent_revision_id,
            "content": revision.content,
            "metadata": revision.metadata,
            "created_at": revision.created_at,
        }
    except (KeyError, ValueError, OSError) as error:
        raise ContractError("pipeline_node_not_found", str(error), status_code=404) from error


@router.post("/{node_id}/reviews/item")
def review_pipeline_node_item(
    node_id: str, body: PipelineNodeItemReviewRequest, request: Request
) -> dict[str, Any]:
    return _execute(
        lambda: request.app.state.pipeline_node_reviews.item(
            body.review_id,
            node_id,
            body.revision_id,
            body.item_id,
            body.question,
            body.decision,
            body.reviewer,
            body.evidence,
        )
    )


@router.post("/{node_id}/reviews/coverage")
def review_pipeline_node_coverage(
    node_id: str, body: PipelineNodeCoverageReviewRequest, request: Request
) -> dict[str, Any]:
    return _execute(
        lambda: request.app.state.pipeline_node_reviews.coverage(
            body.review_id,
            node_id,
            body.revision_id,
            body.question,
            body.coverage,
            body.reviewer,
            body.evidence,
        )
    )


@router.post("/{node_id}/reviews/overall")
def review_pipeline_node_overall(
    node_id: str, body: PipelineNodeOverallReviewRequest, request: Request
) -> dict[str, Any]:
    return _execute(
        lambda: request.app.state.pipeline_node_reviews.overall(
            body.review_id,
            node_id,
            body.revision_id,
            body.question,
            body.decision,
            body.reviewer,
            body.evidence,
        )
    )


@router.get("/{node_id}/revisions/{revision_id}/reviews")
def list_pipeline_node_reviews(
    node_id: str, revision_id: str, request: Request
) -> list[dict[str, Any]]:
    try:
        return list(request.app.state.pipeline_node_reviews.list_for_revision(node_id, revision_id))
    except (KeyError, ValueError, OSError) as error:
        raise ContractError(
            "pipeline_node_review_unavailable", str(error), status_code=404
        ) from error


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
            base_pointers=body.base_pointers,
            operations=body.operations,
            evidence=body.evidence,
        )
    )
