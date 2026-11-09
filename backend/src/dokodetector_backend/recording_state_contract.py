"""Versioned contracts for recording-owned current pipeline state (0117 M1).

These models define data and HTTP shapes only. They do not read or publish storage.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Union

from pydantic import Field, StringConstraints, model_validator

from dokodetector_backend.contract import ContractModel, Sha256

RECORDING_STATE_SNAPSHOT_SCHEMA = "recording-state-snapshot/v1"
RECORDING_HEAD_SCHEMA = "recording-head/v1"
RECORDING_STATE_SUMMARY_SCHEMA = "recording-state-summary/v1"
RECORDING_STATE_ERROR_SCHEMA = "recording-state-error/v1"
RECORDING_HISTORY_PAGE_SCHEMA = "recording-history-page/v1"

Identifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
ArtifactIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*(/[A-Za-z0-9][A-Za-z0-9._:-]*)+$",
    ),
]
SnapshotId = Annotated[str, StringConstraints(pattern=r"^rs_[0-9a-f]{64}$")]
SlotName = Literal[
    "events",
    "visible_cards",
    "table_plane_calibration",
    "virtual_scenes",
    "visual_identities",
    "table_observations",
    "reconstruction_results",
]
ResourceKind = Literal[
    "pipeline-node-revision",
    "table-plane-calibration-revision",
    "round-reconstruction-result",
]


class ExactResourceRef(ContractModel):
    """Address one immutable resource by kind, identity, schema, and digest."""

    kind: ResourceKind
    resource_id: Identifier
    schema_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"),
    ]
    sha256: Sha256
    node_id: Identifier | None = None
    revision_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_address(self) -> ExactResourceRef:
        if self.kind == "pipeline-node-revision":
            if not self.node_id or not self.revision_id:
                raise ValueError("pipeline-node-revision requires node_id and revision_id")
            if self.resource_id != self.revision_id:
                raise ValueError("resource_id must equal revision_id")
        elif self.node_id is not None or self.revision_id is not None:
            raise ValueError("node fields are valid only for pipeline-node-revision")
        return self


class DependencyRef(ContractModel):
    """One exact input used to determine whether a result is stale."""

    role: Identifier
    resource: ExactResourceRef


class SlotSelection(ContractModel):
    """A generated or completed-reference selection, including explicit emptiness/staleness."""

    state: Literal["empty", "selected", "stale"]
    resource: ExactResourceRef | None = None
    stale_reason: (
        Literal["dependency_changed", "dependency_missing", "manual_invalidation"] | None
    ) = None
    dependencies: list[DependencyRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> SlotSelection:
        if self.state == "empty":
            if self.resource is not None or self.stale_reason is not None or self.dependencies:
                raise ValueError("empty selection cannot contain a resource or dependencies")
        elif self.resource is None:
            raise ValueError("selected and stale selections require an exact resource")
        if self.state == "stale" and self.stale_reason is None:
            raise ValueError("stale selection requires stale_reason")
        if self.state == "selected" and self.stale_reason is not None:
            raise ValueError("selected selection cannot have stale_reason")
        return self


class StageSelection(ContractModel):
    """Keep generated output separate from the completed human reference."""

    generated: SlotSelection
    completed_reference: SlotSelection


class StageSummarySelection(ContractModel):
    """Keep compact generated and completed-reference states independently visible."""

    generated: Literal["empty", "selected", "stale"]
    completed_reference: Literal["empty", "selected", "stale"]


class IndependentReviewRef(ContractModel):
    """Reference review work without merging it into selected generated state."""

    review_kind: Literal["pipeline-review", "visible-card-review", "frame-review-workflow"]
    review_id: Identifier
    resource: ExactResourceRef
    state: Literal["draft", "in_review", "completed"]


class RecordingStateSnapshot(ContractModel):
    """Immutable selected state. Its ID is the digest of canonical content without snapshot_id."""

    schema_version: Literal["recording-state-snapshot/v1"] = RECORDING_STATE_SNAPSHOT_SCHEMA
    recording_id: Identifier
    snapshot_id: SnapshotId
    predecessor_snapshot_id: SnapshotId | None = None
    slots: dict[SlotName, StageSelection]
    independent_reviews: list[IndependentReviewRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_slots(self) -> RecordingStateSnapshot:
        required = set(SlotName.__args__)
        if set(self.slots) != required:
            raise ValueError("slots must contain every defined slot exactly once")
        for slot, selection in self.slots.items():
            for choice in (selection.generated, selection.completed_reference):
                if choice.resource and choice.resource.kind == "pipeline-node-revision":
                    if slot == "table_plane_calibration":
                        raise ValueError("calibration slot requires a calibration resource")
                    if slot == "reconstruction_results":
                        raise ValueError("reconstruction slot requires a reconstruction resource")
                if (
                    choice.resource is not None
                    and slot == "table_plane_calibration"
                    and choice.resource.kind != "table-plane-calibration-revision"
                ):
                    raise ValueError("calibration slot requires a calibration resource")
                if (
                    choice.resource is not None
                    and slot == "reconstruction_results"
                    and choice.resource.kind != "round-reconstruction-result"
                ):
                    raise ValueError("reconstruction slot requires a reconstruction resource")
        canonical = json.dumps(
            self.model_dump(mode="json", exclude={"snapshot_id"}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        expected_id = "rs_" + hashlib.sha256(canonical).hexdigest()
        if self.snapshot_id != expected_id:
            raise ValueError("snapshot_id must match the canonical snapshot digest")
        return self


class RecordingHead(ContractModel):
    """Concurrency authority for exactly one current snapshot."""

    schema_version: Literal["recording-head/v1"] = RECORDING_HEAD_SCHEMA
    recording_id: Identifier
    version: int = Field(ge=1)
    snapshot_id: SnapshotId


class RecordingStateSummary(ContractModel):
    """Rebuildable compact projection; valid only for the exact HEAD version and snapshot."""

    schema_version: Literal["recording-state-summary/v1"] = RECORDING_STATE_SUMMARY_SCHEMA
    recording_id: Identifier
    head_version: int = Field(ge=1)
    snapshot_id: SnapshotId
    snapshot_sha256: Sha256
    slots: dict[SlotName, StageSummarySelection]

    @model_validator(mode="after")
    def validate_slots(self) -> RecordingStateSummary:
        if set(self.slots) != set(SlotName.__args__):
            raise ValueError("slots must contain every defined slot exactly once")
        return self


class CompactAnalysisMetadata(ContractModel):
    item_kind: Literal["analysis"] = "analysis"
    analysis_id: Identifier
    schema_version: Literal["round-analysis/v1"]
    status: Literal["queued", "analyzing_evidence", "reconstructing", "complete", "failed"]
    created_at: str
    updated_at: str
    result_sha256: Sha256 | None = None


class CompactPackageMetadata(ContractModel):
    item_kind: Literal["package"] = "package"
    package_id: Identifier
    schema_version: Literal["evidence-package/v1"]
    status: Literal["available", "missing", "corrupt"]
    manifest_sha256: Sha256 | None = None


class CompactJobMetadata(ContractModel):
    item_kind: Literal["job"] = "job"
    job_id: Identifier
    schema_version: Literal["backend-job/v1"]
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    updated_at: str
    request_id: Identifier | None = None


CatalogMetadataItem = Annotated[
    Union[CompactAnalysisMetadata, CompactPackageMetadata, CompactJobMetadata],
    Field(discriminator="item_kind"),
]


class CatalogMetadataPage(ContractModel):
    """Bounded detail metadata page; never embed unbounded lists in the catalog summary."""

    schema_version: Literal["recording-catalog-metadata-page/v1"] = (
        "recording-catalog-metadata-page/v1"
    )
    recording_id: Identifier
    collection: Literal["analyses", "packages", "jobs"]
    items: list[CatalogMetadataItem] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, max_length=2048)
    has_more: bool

    @model_validator(mode="after")
    def validate_page(self) -> CatalogMetadataPage:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more must match next_cursor presence")
        expected_kind = {"analyses": "analysis", "packages": "package", "jobs": "job"}[
            self.collection
        ]
        if any(item.item_kind != expected_kind for item in self.items):
            raise ValueError("metadata page items must match collection")
        return self


class JobProjectionAuthority(ContractModel):
    """Durable Job Manager generation used to validate all compact job projections."""

    schema_version: Literal["job-projection-authority/v1"] = "job-projection-authority/v1"
    manager_id: Identifier
    epoch: Identifier
    sequence: int = Field(ge=1)


class RecordingJobProjection(ContractModel):
    """Bounded active-job view tied to the Job Manager's durable cross-process authority."""

    schema_version: Literal["recording-job-projection/v1"] = "recording-job-projection/v1"
    recording_id: Identifier
    authority_epoch: Identifier
    authority_sequence: int = Field(ge=1)
    active_job_count: int = Field(ge=0)
    jobs: list[CompactJobMetadata] = Field(max_length=20)
    next_cursor: str | None = Field(default=None, max_length=2048)
    has_more: bool

    @model_validator(mode="after")
    def validate_projection(self) -> RecordingJobProjection:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more must match next_cursor presence")
        if len(self.jobs) > self.active_job_count:
            raise ValueError("job preview cannot exceed active_job_count")
        if self.has_more != (len(self.jobs) < self.active_job_count):
            raise ValueError("job preview continuation must match active_job_count")
        if any(job.status not in {"queued", "running", "cancelling"} for job in self.jobs):
            raise ValueError("job projection can contain only active jobs")
        return self

    def validate_authority(self, authority: JobProjectionAuthority) -> None:
        """Reject a projection unless it matches the current durable manager marker."""

        if self.authority_epoch != authority.epoch or self.authority_sequence != authority.sequence:
            raise ValueError("job projection is stale relative to Job Manager authority")


class RecordingStateError(ContractModel):
    """Stable safe error codes for state and exact-resource APIs."""

    schema_version: Literal["recording-state-error/v1"] = RECORDING_STATE_ERROR_SCHEMA
    code: Literal[
        "recording_state_not_initialized",
        "recording_state_conflict",
        "recording_state_corrupt",
        "recording_snapshot_missing",
        "recording_resource_missing",
        "recording_resource_corrupt",
        "recording_cursor_invalid",
        "recording_cursor_expired",
        "recording_page_size_invalid",
    ]
    message: str = Field(min_length=1, max_length=240)
    retryable: bool = False
    current_head_version: int | None = Field(default=None, ge=1)


class HistoryPageCursor(ContractModel):
    """Cursor contents before opaque encoding by the history API."""

    schema_version: Literal["recording-history-cursor/v1"] = "recording-history-cursor/v1"
    recording_id: Identifier
    collection: Literal[
        "snapshots",
        "revisions",
        "candidates",
        "lineage_edges",
        "analyses",
        "packages",
        "jobs",
    ]
    filter_sha256: Sha256
    upper_bound_sequence: int = Field(ge=1)
    # Composite history keys can contain the longest valid lineage endpoints.
    last_key: str | None = Field(default=None, max_length=4096)
    page_size: int = Field(ge=1, le=100)
    authority_epoch: Identifier | None = None
    authority_sequence: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_job_authority(self) -> HistoryPageCursor:
        if self.collection == "jobs":
            if self.authority_epoch is None or self.authority_sequence is None:
                raise ValueError("job cursor must pin Job Manager authority")
        elif self.authority_epoch is not None or self.authority_sequence is not None:
            raise ValueError("Job Manager authority is valid only for job cursors")
        return self


class SnapshotHistoryItem(ContractModel):
    """One immutable snapshot address in recording history."""

    item_kind: Literal["snapshot"] = "snapshot"
    item_key: Identifier
    snapshot_id: SnapshotId
    sha256: Sha256
    publication_sequence: int = Field(ge=1)
    predecessor_snapshot_id: SnapshotId | None = None


class LineageEndpoint(ContractModel):
    """One exact endpoint from the existing lineage graph key contract."""

    kind: Literal["revision", "run", "artifact"]
    node_id: Identifier | None = None
    revision_id: Identifier | None = None
    run_id: Identifier | None = None
    artifact_id: ArtifactIdentifier | None = None
    sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_endpoint(self) -> LineageEndpoint:
        if self.kind == "revision":
            valid = self.node_id is not None and self.revision_id is not None
        elif self.kind == "run":
            valid = self.run_id is not None
        else:
            valid = self.artifact_id is not None and self.sha256 is not None
        if not valid:
            raise ValueError("lineage endpoint is missing its exact identity")
        if self.kind != "revision" and (self.node_id is not None or self.revision_id is not None):
            raise ValueError("node fields are valid only for revision endpoints")
        if self.kind != "run" and self.run_id is not None:
            raise ValueError("run_id is valid only for run endpoints")
        if self.kind != "artifact" and (self.artifact_id is not None or self.sha256 is not None):
            raise ValueError("artifact fields are valid only for artifact endpoints")
        return self


class LineageEdgeHistoryItem(ContractModel):
    """One stable relationship edge in the explicit lineage graph."""

    item_kind: Literal["lineage_edge"] = "lineage_edge"
    item_key: Identifier
    edge_kind: Literal["revised", "copied", "restored", "used", "produced"]
    source: LineageEndpoint
    target: LineageEndpoint
    publication_sequence: int = Field(ge=1)
    role: Identifier | None = None

    def stable_sort_key(self) -> tuple[str, ...]:
        """Return a total order that distinguishes every valid lineage edge."""

        def endpoint_key(endpoint: LineageEndpoint) -> tuple[str, ...]:
            return (
                endpoint.kind,
                endpoint.node_id or "",
                endpoint.revision_id or "",
                endpoint.run_id or "",
                endpoint.artifact_id or "",
                endpoint.sha256 or "",
            )

        return (
            *endpoint_key(self.source),
            *endpoint_key(self.target),
            self.edge_kind,
            self.role or "",
            self.item_key,
        )

    def stable_cursor_key(self) -> str:
        """Serialize the complete sort key without delimiter ambiguity."""

        return json.dumps(self.stable_sort_key(), separators=(",", ":"))


class ResourceHistoryItem(ContractModel):
    """One exact revision or candidate resource in stable history."""

    item_kind: Literal["resource"] = "resource"
    item_key: Identifier
    resource: ExactResourceRef
    publication_sequence: int = Field(ge=1)


class RecordingHistoryAuthority(ContractModel):
    """Per-recording durable monotonic insertion boundary for all history collections."""

    schema_version: Literal["recording-history-authority/v1"] = "recording-history-authority/v1"
    recording_id: Identifier
    sequence: int = Field(ge=1)


HistoryItem = Annotated[
    Union[SnapshotHistoryItem, LineageEdgeHistoryItem, ResourceHistoryItem],
    Field(discriminator="item_kind"),
]


class RecordingHistoryPage(ContractModel):
    """One bounded, stable page of typed snapshot, resource, or lineage metadata."""

    schema_version: Literal["recording-history-page/v1"] = RECORDING_HISTORY_PAGE_SCHEMA
    recording_id: Identifier
    collection: Literal["snapshots", "revisions", "candidates", "lineage_edges"]
    upper_bound_sequence: int = Field(ge=1)
    items: list[HistoryItem] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, max_length=8192)
    has_more: bool

    @model_validator(mode="after")
    def validate_cursor_state(self) -> RecordingHistoryPage:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more must match next_cursor presence")
        expected_kind = {
            "snapshots": "snapshot",
            "revisions": "resource",
            "candidates": "resource",
            "lineage_edges": "lineage_edge",
        }[self.collection]
        if any(item.item_kind != expected_kind for item in self.items):
            raise ValueError("history page items must match collection")
        if any(item.publication_sequence > self.upper_bound_sequence for item in self.items):
            raise ValueError("history page item exceeds the frozen insertion boundary")
        return self


class RecordingHeadUpdate(ContractModel):
    """Explicit selection or restore request with optimistic concurrency."""

    recording_id: Identifier
    expected_head_version: int = Field(ge=1)
    snapshot_id: SnapshotId
    action: Literal["select_snapshot", "restore_snapshot"]


class SnapshotFrozenProcessorInputs(ContractModel):
    """Durable processor launch inputs; HEAD movement cannot change these references."""

    recording_id: Identifier
    snapshot_id: SnapshotId
    head_version: int = Field(ge=1)
    inputs: dict[SlotName, list[ExactResourceRef]]
    select_output_on_completion: bool = False
    expected_head_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_conditional_selection(self) -> SnapshotFrozenProcessorInputs:
        if self.select_output_on_completion != (self.expected_head_version is not None):
            raise ValueError("select-on-completion requires expected_head_version")
        return self
