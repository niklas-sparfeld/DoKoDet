"""HTTP routes for recording discovery and explicit round-analysis recovery."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from dokodetector_backend.errors import ContractError
from dokodetector_backend.intake_contract import (
    DataTask,
    Disposition,
    LifecycleState,
    TaskEnrollment,
    parse_source_record,
    parse_task_enrollment,
)
from dokodetector_backend.round_analysis_api import _queue_round_analysis
from dokodetector_backend.round_analysis_contract import RoundAnalysisStatus
from dokodetector_backend.round_analysis_service import (
    RoundAnalysisService,
    RoundAnalysisValidationError,
)
from dokodetector_backend.stored_models import StoredRoundAnalysis
from dokodetector_backend.video_probe import (
    VideoProbeError,
    VideoProbeUnavailable,
    probe_video_path_metadata,
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
PipelineStageKey = Literal[
    "events",
    "visible_cards",
    "visual_identities",
    "table_observations",
    "round_analyses",
]
PipelineStageState = Literal[
    "video-only",
    "empty",
    "active-run",
    "partial",
    "failed",
    "data-available",
    "complete",
    "unavailable",
]


class RecordingPipelineStageSummary(BaseModel):
    """One compact pipeline stage state for the recording catalog."""

    model_config = ConfigDict(extra="forbid")

    key: PipelineStageKey
    state: PipelineStageState


class RecordingPipelineStatusSummary(BaseModel):
    """The lightweight pipeline status embedded in each recording catalog entry."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["recording-pipeline-status/v1"]
    stages: list[RecordingPipelineStageSummary] = Field(min_length=5, max_length=5)


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


SelectionState = Literal["selected", "not-selected", "unavailable"]
SelectionType = Literal[
    "events",
    "visible_cards",
    "virtual_scenes",
    "card_scene_proposals",
    "visual_identities",
    "table_observations",
]


class RecordingSelectionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: SelectionType
    state: SelectionState
    selected_generated: dict[str, str] | None
    selected_completed_reference: dict[str, str] | None


class RecordingSummary(BaseModel):
    """One recording row built from bounded root metadata and exact selections."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str
    source_asset_id: str | None
    video_id: str | None
    session_id: str | None
    display_name: str
    received_at: datetime | None
    thumbnail_url: str | None
    metadata_state: Literal["available", "unavailable"]
    selections: list[RecordingSelectionSummary] = Field(min_length=6, max_length=6)


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
    analyses: list[RecordingAnalysisSummary]
    can_start_analysis: bool
    analysis_blocker: str | None


@router.get("/v1/recordings", response_model=RecordingListResponse)
def list_recordings(request: Request) -> RecordingListResponse:
    """List recording identity and exact selections without opening referenced content."""
    root = request.app.state.recording_folder_store.root
    try:
        directories = sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
            ),
            key=lambda path: path.name,
        )
    except FileNotFoundError:
        directories = []
    node_store = request.app.state.pipeline_selection_store.node_store
    locator = node_store.root / ".coordinated-transactions" / ".locator" / "pending.json"
    locator_pending = _selection_locator_pending(locator)
    rows = []
    for recording_path in directories:
        recording_id = recording_path.name
        try:
            recording = request.app.state.recording_folder_store.get(recording_id)
            if recording is None:
                raise ValueError("recording root is invalid")
            source = recording.source
            source_asset_id = recording.source_asset_id
            video_id = recording.video_id
            session_id = recording.session_id
            received_at = recording.received_at
            display_name = source.get("original_filename", recording_id)
            metadata_state = "available"
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            source_asset_id = video_id = session_id = None
            received_at = None
            display_name = recording_id
            metadata_state = "unavailable"
        selections = _recording_selections(node_store.root, recording_id, locator_pending)
        rows.append(
            RecordingSummary(
                recording_id=recording_id,
                source_asset_id=source_asset_id,
                video_id=video_id,
                session_id=session_id,
                display_name=display_name,
                received_at=received_at,
                thumbnail_url=(
                    f"/v1/repository-bundles/{recording_id}/thumbnail"
                    if metadata_state == "available"
                    else None
                ),
                metadata_state=metadata_state,
                selections=selections,
            )
        )
    return RecordingListResponse(recordings=rows)


_LIST_SELECTION_TYPES: tuple[SelectionType, ...] = (
    "events",
    "visible_cards",
    "virtual_scenes",
    "card_scene_proposals",
    "visual_identities",
    "table_observations",
)


def _bounded_json(path: Path, max_bytes: int) -> dict:
    value = json.loads(_bounded_bytes(path, max_bytes))
    if not isinstance(value, dict):
        raise ValueError("metadata file must contain an object")
    return value


def _bounded_bytes(path: Path, max_bytes: int) -> bytes:
    if path.is_symlink():
        raise ValueError("metadata file must not be a symlink")
    with path.open("rb") as file:
        raw = file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("metadata file exceeds list limit")
    return raw


def _selection_locator_pending(path: Path) -> bool:
    try:
        value = _bounded_json(path, 64_000)
    except FileNotFoundError:
        return False
    except (OSError, ValueError, TypeError):
        return True
    if (
        set(value) != {"schema_version", "transaction_id", "request_digest"}
        or value["schema_version"] != "pipeline-node-pending-transaction/v1"
    ):
        return True
    return value["transaction_id"] is not None or value["request_digest"] is not None


def _recording_selections(
    root: Path, recording_id: str, locator_pending: bool
) -> list[RecordingSelectionSummary]:
    rows = []
    for content_type in _LIST_SELECTION_TYPES:
        generated = completed = None
        state: SelectionState = "unavailable" if locator_pending else "not-selected"
        if not locator_pending:
            path = root / ".pipeline-node-selections" / recording_id / f"{content_type}.json"
            try:
                raw = _bounded_json(path, 64_000)
                if (
                    raw.get("schema_version") != "pipeline-node-selection/v1"
                    or raw.get("recording_id") != recording_id
                    or raw.get("content_type") != content_type
                    or not isinstance(raw.get("revision"), int)
                    or isinstance(raw.get("revision"), bool)
                ):
                    raise ValueError("selection identity is invalid")
                if raw["revision"] < 1:
                    raise ValueError("selection revision must be positive")
                generated = _list_pointer(raw.get("selected_generated"))
                completed = _list_pointer(raw.get("selected_completed_reference"))
                state = (
                    "selected" if generated is not None or completed is not None else "not-selected"
                )
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError, KeyError):
                state = "unavailable"
        rows.append(
            RecordingSelectionSummary(
                content_type=content_type,
                state=state,
                selected_generated=generated,
                selected_completed_reference=completed,
            )
        )
    return rows


def _list_pointer(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"node_id", "revision_id"}
        or not all(isinstance(value[key], str) and value[key] for key in value)
    ):
        raise ValueError("selection pointer shape is invalid")
    return value


@router.get(
    "/v1/recordings/{recording_id}",
    response_model=RecordingDetailResponse,
)
def get_recording(recording_id: str, request: Request) -> RecordingDetailResponse:
    """Return accepted recording metadata for the recording workspace."""

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
        task_enrollments=[_task_enrollment_response(item) for item in enrollments.enrollments],
        analyses=[_analysis_summary(analysis) for analysis in entry.analyses],
        can_start_analysis=entry.can_start_analysis,
        analysis_blocker=entry.analysis_blocker,
    )


@router.post(
    "/v1/recordings/{recording_id}/round-analyses",
    response_model=RoundAnalysisStatus,
    status_code=202,
)
async def start_recording_analysis(recording_id: str, request: Request) -> RoundAnalysisStatus:
    """Start a new analysis using the recording pipeline selection when available."""

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
        probe = probe_video_path_metadata(video_paths[0])
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
