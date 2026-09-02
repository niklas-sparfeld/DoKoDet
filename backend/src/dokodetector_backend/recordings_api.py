"""HTTP routes for recording discovery and explicit round-analysis recovery."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from doko_operations import (
    CardEventReviewError,
    VisualCardIdentityBatchError,
    VisualCardIdentityBatchStore,
    load_visual_card_identity_review_batch,
)
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from dokodetector_backend.card_event_development_split_api import (
    load_card_event_development_recordings,
)
from dokodetector_backend.card_event_review_api import _load_source
from dokodetector_backend.errors import ContractError
from dokodetector_backend.intake_contract import (
    TASK_CARD_EVENT,
    DataTask,
    Disposition,
    LifecycleState,
    TaskEnrollment,
    parse_source_record,
    parse_task_enrollment,
)
from dokodetector_backend.repository import StoredRoundAnalysis
from dokodetector_backend.round_analysis_api import _queue_round_analysis
from dokodetector_backend.round_analysis_contract import RoundAnalysisStatus
from dokodetector_backend.round_analysis_service import (
    RoundAnalysisService,
    RoundAnalysisValidationError,
)
from dokodetector_backend.video_probe import (
    VideoProbeError,
    VideoProbeUnavailable,
    probe_video_path,
)

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
AnalysisState = Literal[
    "queued",
    "analyzing_evidence",
    "reconstructing",
    "complete",
    "failed",
]
ResultStatus = Literal["resolved", "ambiguous", "incomplete", "impossible"]


class RecordingAnalysisSummary(BaseModel):
    """Small analysis status embedded in the recording catalog."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: UUID
    recording_id: str
    round_id: str
    state: AnalysisState
    total_evidence_packages: int
    completed_evidence_packages: int
    result_status: ResultStatus | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RecordingSummary(BaseModel):
    """One accepted recording and its round-analysis history."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str
    source_asset_id: str
    video_id: str
    session_id: str
    state: str
    source_sha256: str
    received_at: datetime
    round_id: str
    card_event_review_state: str
    card_event_event_count: int
    development_partition: str | None
    evidence_package_ids: list[UUID]
    analyses: list[RecordingAnalysisSummary]
    can_start_analysis: bool
    analysis_blocker: str | None


class RecordingListResponse(BaseModel):
    """Recording catalog response."""

    model_config = ConfigDict(extra="forbid")

    recordings: list[RecordingSummary]


class RecordingMediaFactsResponse(BaseModel):
    """Technical facts measured from the accepted source video when available."""

    model_config = ConfigDict(extra="forbid")

    container: str
    video_codec: str
    width: int
    height: int
    nominal_frame_rate: float
    duration_ms: int
    frame_count: int


class RecordingVideoResponse(BaseModel):
    """The immutable source video and its optional local media probe."""

    model_config = ConfigDict(extra="forbid")

    url: str
    content_type: str
    media_facts: RecordingMediaFactsResponse | None


class RecordingSourceResponse(BaseModel):
    """Trusted metadata read from the immutable source record."""

    model_config = ConfigDict(extra="forbid")

    original_filename: str
    acquisition_method: str
    source_permission: str
    allowed_uses: list[str]
    session_id: str | None
    recording_id: str | None
    video_id: str | None
    game_id: str | None
    round_id: str | None
    table_setup: str | None
    content_type: str | None
    retention_state: str
    notes: str | None


class RecordingTaskEnrollmentResponse(BaseModel):
    """One immutable initial data-task enrollment."""

    model_config = ConfigDict(extra="forbid")

    task_enrollment_id: str
    task: DataTask
    disposition: Disposition
    lifecycle_state: LifecycleState
    operator: str
    created_at_utc: str
    reason: str | None


class RecordingCardEventReviewSummary(BaseModel):
    """Current CardEvent review placeholder until the review workspace exists."""

    model_config = ConfigDict(extra="forbid")

    state: str
    event_count: int
    reviewed_at: str | None


class RecordingTrainingUseSummary(BaseModel):
    """Current task-enrollment and development-use projection."""

    model_config = ConfigDict(extra="forbid")

    card_event_task: RecordingTaskEnrollmentResponse | None
    eligibility: str
    development_partition: str | None
    active_split_version_id: str | None
    active_split_digest: str | None
    development_group_keys: list[list[str]]
    blocker: str | None


class RecordingIdentityDatasetSummary(BaseModel):
    """Identity classifier dataset eligibility shown on the recording page."""

    model_config = ConfigDict(extra="forbid")

    state: str
    dataset_version_id: str | None
    dataset_version_digest: str | None
    split_version_id: str | None
    split_version_digest: str | None
    sample_count: int
    excluded_count: int
    development_partition: str | None
    blocker: str | None


class RecordingDetailResponse(BaseModel):
    """Strict recording resource projection for the web workspace."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str
    source_asset_id: str
    video_id: str
    session_id: str
    state: str
    source_sha256: str
    received_at: datetime
    round_id: str
    source: RecordingSourceResponse
    video: RecordingVideoResponse
    evidence_package_ids: list[UUID]
    task_enrollments: list[RecordingTaskEnrollmentResponse]
    card_event_review: RecordingCardEventReviewSummary
    training_use: RecordingTrainingUseSummary
    identity_dataset: RecordingIdentityDatasetSummary
    analyses: list[RecordingAnalysisSummary]
    can_start_analysis: bool
    analysis_blocker: str | None
    next_action: str


@router.get("/v1/recordings", response_model=RecordingListResponse)
def list_recordings(request: Request) -> RecordingListResponse:
    """List accepted recordings with linked packages and analyses."""

    service: RoundAnalysisService = request.app.state.round_analysis_service
    training_projection = _catalog_training_projection(request)
    return RecordingListResponse(
        recordings=[
            RecordingSummary(
                recording_id=entry.recording.recording_id,
                source_asset_id=entry.recording.source_asset_id,
                video_id=entry.recording.video_id,
                session_id=entry.recording.session_id,
                state=entry.recording.state,
                source_sha256=entry.recording.source_sha256,
                received_at=entry.recording.received_at,
                round_id=entry.round_id,
                card_event_review_state=training_projection.get(
                    entry.recording.recording_id, ("not_started", 0, None)
                )[0],
                card_event_event_count=training_projection.get(
                    entry.recording.recording_id, ("not_started", 0, None)
                )[1],
                development_partition=training_projection.get(
                    entry.recording.recording_id, ("not_started", 0, None)
                )[2],
                evidence_package_ids=list(entry.evidence_package_ids),
                analyses=[_analysis_summary(analysis) for analysis in entry.analyses],
                can_start_analysis=entry.can_start_analysis,
                analysis_blocker=entry.analysis_blocker,
            )
            for entry in service.recording_catalog()
        ]
    )


def _catalog_training_projection(
    request: Request,
) -> dict[str, tuple[str, int, str | None]]:
    """Return review and partition facts for the recording catalog."""

    try:
        facts = load_card_event_development_recordings(request)
        split = request.app.state.card_event_development_split_store.read(facts)
    except (CardEventReviewError, ContractError, RuntimeError, ValueError):
        return {}
    partitions = {
        recording_id: partition
        for partition in ("train", "validation", "unassigned", "test")
        for recording_id in split[partition]
    }
    return {
        item.recording_id: (
            item.review_state,
            item.review_event_count,
            partitions.get(item.recording_id),
        )
        for item in facts
    }


def _identity_dataset_projection(
    request: Request, recording_id: str
) -> RecordingIdentityDatasetSummary:
    """Project the latest identity review dataset status for a recording."""

    root = (
        VisualCardIdentityBatchStore(request.app.state.settings.operations_root).workspace_root
        / "visual-card-identity-review-batches"
    )
    states: list[dict[str, object]] = []
    if root.is_dir():
        for path in root.glob("visual-card-identity-batch-*/batch.json"):
            try:
                state = load_visual_card_identity_review_batch(path)
            except (VisualCardIdentityBatchError, OSError, ValueError):
                continue
            if state["recording_id"] == recording_id:
                states.append(state)
    current = max(states, key=lambda value: str(value["updated_at_utc"]), default=None)
    if current is None:
        return RecordingIdentityDatasetSummary(
            state="not_ready",
            dataset_version_id=None,
            dataset_version_digest=None,
            split_version_id=None,
            split_version_digest=None,
            sample_count=0,
            excluded_count=0,
            development_partition=None,
            blocker="Complete the visual card identity review before dataset use.",
        )
    dataset = current.get("dataset")
    if not isinstance(dataset, dict):
        identity_state = (
            "review_required" if current["review_state"] == "draft" else "publication_required"
        )
        return RecordingIdentityDatasetSummary(
            state=identity_state,
            dataset_version_id=None,
            dataset_version_digest=None,
            split_version_id=None,
            split_version_digest=None,
            sample_count=0,
            excluded_count=0,
            development_partition=None,
            blocker="Complete and publish the visual card identity review.",
        )
    return RecordingIdentityDatasetSummary(
        state="eligible" if dataset["status"] == "eligible" else "blocked",
        dataset_version_id=dataset["dataset_version_id"],
        dataset_version_digest=dataset["dataset_version_digest"],
        split_version_id=dataset["split_version_id"],
        split_version_digest=dataset["split_version_digest"],
        sample_count=dataset["sample_count"],
        excluded_count=dataset["excluded_count"],
        development_partition=dataset["development_partition"],
        blocker=dataset["blocker"],
    )


@router.get(
    "/v1/recordings/{recording_id}",
    response_model=RecordingDetailResponse,
)
def get_recording(recording_id: str, request: Request) -> RecordingDetailResponse:
    """Return one strict recording projection for the web workspace."""

    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")

    service: RoundAnalysisService = request.app.state.round_analysis_service
    entry = next(
        (
            candidate
            for candidate in service.recording_catalog()
            if candidate.recording.recording_id == recording_id
        ),
        None,
    )
    if entry is None:
        raise ContractError(
            "recording_not_found",
            "The recording was not found.",
            status_code=404,
        )

    bundle_path = request.app.state.repository_bundle_storage.bundle_path(recording_id)
    try:
        source = parse_source_record((bundle_path / "source-record.json").read_bytes())
        enrollments = parse_task_enrollment(
            (bundle_path / "initial-task-enrollment.json").read_bytes()
        )
    except (OSError, TypeError, ValueError) as error:
        raise ContractError(
            "recording_metadata_invalid",
            "The stored recording metadata is invalid.",
            status_code=500,
        ) from error

    recording = entry.recording
    if (
        source.source_asset_id != recording.source_asset_id
        or source.sha256 != recording.source_sha256
        or source.recording_id != recording.recording_id
        or source.video_id != recording.video_id
        or source.session_id != recording.session_id
        or enrollments.source_asset_id != recording.source_asset_id
    ):
        raise ContractError(
            "recording_metadata_invalid",
            "The stored recording metadata is inconsistent.",
            status_code=500,
        )

    task_enrollments = [_task_enrollment_response(item) for item in enrollments.enrollments]
    card_event_task = next(
        (item for item in task_enrollments if item.task == TASK_CARD_EVENT),
        None,
    )
    review_state = "not_started"
    review_event_count = 0
    reviewed_at: str | None = None
    try:
        review_source = _load_source(request, recording_id, require_selected=False)
        review = request.app.state.card_event_review_store.read(review_source)
        review_state = review["review_state"]
        review_event_count = len(review["annotation"]["events"])
        reviewed_at = review.get("completed_at")
    except (CardEventReviewError, ContractError):
        # The recording projection remains readable if an operations workspace is unavailable.
        pass

    development_partition: str | None = None
    active_split_version_id: str | None = None
    active_split_digest: str | None = None
    development_group_keys: list[list[str]] = []
    try:
        development_recordings = load_card_event_development_recordings(request)
        development_split = request.app.state.card_event_development_split_store.read(
            development_recordings
        )
        development_by_id = {
            item["recording_id"]: item for item in development_split["recordings"]
        }
        development_entry = development_by_id.get(recording_id)
        if development_entry is not None:
            development_group_keys = list(development_entry["group_keys"])
        for partition in ("train", "validation", "test", "unassigned"):
            if recording_id in development_split[partition]:
                development_partition = partition
                break
        active_split_version_id = development_split["split_version_id"]
        active_split_digest = development_split["split_version_digest"]
        if development_partition in {"train", "validation", "test"}:
            next_action = f"Assigned to {development_partition}"
    except (CardEventReviewError, ContractError, RuntimeError, ValueError):
        # The recording projection remains readable if split artifacts are unavailable.
        pass

    if card_event_task is None or card_event_task.disposition != "selected":
        eligibility = "not_enrolled"
        blocker = "Select the CardEvent task before reviewing this recording."
        next_action = "Resolve CardEvent task enrollment"
    elif review_state == "completed":
        eligibility = "eligible"
        blocker = None
        next_action = "Assign a development partition"
    else:
        eligibility = "review_required"
        blocker = "Complete the full recording CardEvent review before training use."
        next_action = "Review CardEvent events"

    return RecordingDetailResponse(
        recording_id=recording.recording_id,
        source_asset_id=recording.source_asset_id,
        video_id=recording.video_id,
        session_id=recording.session_id,
        state=recording.state,
        source_sha256=recording.source_sha256,
        received_at=recording.received_at,
        round_id=entry.round_id,
        source=RecordingSourceResponse(
            original_filename=source.original_filename,
            acquisition_method=source.acquisition_method,
            source_permission=source.source_permission,
            allowed_uses=list(source.allowed_uses),
            session_id=source.session_id,
            recording_id=source.recording_id,
            video_id=source.video_id,
            game_id=source.game_id,
            round_id=source.round_id,
            table_setup=source.table_setup,
            content_type=source.content_type,
            retention_state=source.retention_state,
            notes=source.notes,
        ),
        video=RecordingVideoResponse(
            url=f"/v1/repository-bundles/{recording_id}/video",
            content_type="video/quicktime",
            media_facts=_probe_recording_video(bundle_path),
        ),
        evidence_package_ids=list(entry.evidence_package_ids),
        task_enrollments=task_enrollments,
        card_event_review=RecordingCardEventReviewSummary(
            state=review_state,
            event_count=review_event_count,
            reviewed_at=reviewed_at,
        ),
        training_use=RecordingTrainingUseSummary(
            card_event_task=card_event_task,
            eligibility=eligibility,
            development_partition=development_partition,
            active_split_version_id=active_split_version_id,
            active_split_digest=active_split_digest,
            development_group_keys=development_group_keys,
            blocker=blocker,
        ),
        identity_dataset=_identity_dataset_projection(request, recording_id),
        analyses=[_analysis_summary(analysis) for analysis in entry.analyses],
        can_start_analysis=entry.can_start_analysis,
        analysis_blocker=entry.analysis_blocker,
        next_action=next_action,
    )


@router.post(
    "/v1/recordings/{recording_id}/round-analyses",
    response_model=RoundAnalysisStatus,
    status_code=202,
)
async def start_recording_analysis(recording_id: str, request: Request) -> RoundAnalysisStatus:
    """Start a new analysis using all valid evidence linked to one recording."""

    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")
    service: RoundAnalysisService = request.app.state.round_analysis_service
    try:
        payload = service.default_request_for_recording(recording_id)
    except RoundAnalysisValidationError as error:
        raise ContractError("invalid_analysis_request", str(error), status_code=422) from error
    return await _queue_round_analysis(payload, request)


def _analysis_summary(analysis: StoredRoundAnalysis) -> RecordingAnalysisSummary:
    """Convert durable analysis metadata to the catalog response."""

    return RecordingAnalysisSummary(
        analysis_id=analysis.analysis_id,
        recording_id=analysis.recording_id,
        round_id=analysis.round_id,
        state=analysis.state,
        total_evidence_packages=analysis.total_evidence_packages,
        completed_evidence_packages=analysis.completed_evidence_packages,
        result_status=analysis.result_status,
        error=analysis.error,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


def _task_enrollment_response(item: TaskEnrollment) -> RecordingTaskEnrollmentResponse:
    """Convert one intake enrollment into the recording projection."""

    return RecordingTaskEnrollmentResponse(
        task_enrollment_id=item.task_enrollment_id,
        task=item.task,
        disposition=item.disposition,
        lifecycle_state=item.lifecycle_state,
        operator=item.operator,
        created_at_utc=item.created_at_utc,
        reason=item.reason,
    )


def _probe_recording_video(bundle_path: Path) -> RecordingMediaFactsResponse | None:
    """Read optional media facts without making the recording route depend on ffprobe."""

    try:
        video_directory = bundle_path / "videos"
        video_paths = tuple(sorted(video_directory.glob("*.mov")))
        if len(video_paths) != 1:
            return None
        probe = probe_video_path(video_paths[0])
    except (OSError, TypeError, VideoProbeError, VideoProbeUnavailable):
        return None
    return RecordingMediaFactsResponse(
        container=probe.container,
        video_codec=probe.video_codec,
        width=probe.width,
        height=probe.height,
        nominal_frame_rate=probe.nominal_frame_rate,
        duration_ms=probe.duration_ms,
        frame_count=probe.frame_count,
    )
