"""Recording-scoped CardEvent review workspace routes."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from doko_operations import (
    CARD_EVENT_REVIEW_COLLECTION_SCHEMA_VERSION,
    CardEventProposal,
    CardEventReviewConflict,
    CardEventReviewError,
    CardEventReviewNotFound,
    CardEventReviewSource,
    CardEventReviewStore,
    CardEventReviewWriteError,
    proposal_id,
)
from fastapi import APIRouter, Request
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from dokodetector_backend.errors import ContractError
from dokodetector_backend.intake_contract import (
    TASK_CARD_EVENT,
    IntakeContractError,
    ProposalGeneratorRun,
    parse_repository_bundle,
    validate_repository_bundle,
)
from dokodetector_backend.repository_bundle_repository import (
    RepositoryBundleRepository,
    StoredRepositoryBundle,
)
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.video_probe import (
    VideoProbeError,
    VideoProbeUnavailable,
    probe_video_path,
)

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
PROPOSAL_DECISIONS = Literal["undecided", "accepted", "dismissed"]
REVIEW_STATES = Literal["not_started", "draft", "completed"]
EVENT_STATES = Literal["proposed", "reviewed", "dismissed"]
EVENT_ORIGINS = Literal["manual", "model", "device"]
EVENT_COMMAND_ACTIONS = Literal["accept", "dismiss", "undo", "edit", "retime", "remove"]


class CardEventProposalDecisionRequest(BaseModel):
    """The client-controlled decision for one immutable proposal."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    decision: PROPOSAL_DECISIONS


class CardEventReviewDraftUpdateRequest(BaseModel):
    """A complete next draft and the revision it replaces."""

    model_config = ConfigDict(extra="forbid")

    annotation: dict[str, Any]
    proposals: list[CardEventProposalDecisionRequest] | dict[str, PROPOSAL_DECISIONS] = Field(
        default_factory=list, validation_alias=AliasChoices("proposals", "proposal_decisions")
    )
    expected_revision: int = Field(ge=0)
    full_video_acknowledged: bool = Field(
        default=False,
        validation_alias=AliasChoices("full_video_acknowledged", "acknowledge_full_video"),
    )


class CardEventReviewCompletionRequest(BaseModel):
    """The explicit full-recording completion acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    full_video_acknowledged: bool = Field(
        default=False,
        validation_alias=AliasChoices("full_video_acknowledged", "acknowledge_full_video"),
    )


class CardEventReviewRevisionRequest(BaseModel):
    """The immutable reviewed version to copy into a new draft."""

    model_config = ConfigDict(extra="forbid")

    parent_version_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("parent_version_id", "version_id"),
    )
    expected_revision: int = Field(ge=0)


class CardEventReviewCreateRequest(BaseModel):
    """The operator and optional completed review used to seed a new draft."""

    model_config = ConfigDict(extra="forbid")

    operator: str = Field(min_length=1)
    parent_review_id: str | None = None


class CardEventReviewResourceUpdateRequest(CardEventReviewDraftUpdateRequest):
    """A complete next draft for one recording-owned review resource."""


class CardEventProposalResponse(BaseModel):
    """One immutable proposal with its separate human decision."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    proposal_generator_run_id: str
    time_s: float
    probability: float
    model_bundle_id: str
    execution_platform: str
    decision: PROPOSAL_DECISIONS


class CardEventReviewResponse(BaseModel):
    """The current source-linked CardEvent review state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cardevent-review/v1"]
    recording_id: str
    source_asset_id: str
    source_sha256: str
    video: str
    annotation: dict[str, Any]
    draft_revision: int
    draft_digest: str
    review_state: REVIEW_STATES
    full_video_acknowledged: bool
    reviewer: str | None
    completed_at: str | None
    completed_version_id: str | None
    completed_version_digest: str | None
    parent_version_id: str | None
    parent_digest: str | None
    reviewed_annotation_digest: str | None
    proposal_decision_digest: str | None
    completion_receipt_id: str | None
    proposals: list[CardEventProposalResponse]


class CardEventReviewResourceResponse(BaseModel):
    """One stable recording-owned CardEvent review resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cardevent-review-resource/v1"]
    review_id: str
    review_url: str
    recording_id: str
    source_asset_id: str
    source_sha256: str
    video: str
    operator: str
    created_at: str
    updated_at: str
    annotation: dict[str, Any]
    draft_revision: int
    draft_digest: str
    review_state: Literal["draft", "completed"]
    full_video_acknowledged: bool
    reviewer: str | None
    completed_at: str | None
    completed_version_id: str | None
    completed_version_digest: str | None
    parent_review_id: str | None
    parent_version_id: str | None
    parent_digest: str | None
    reviewed_annotation_digest: str | None
    proposal_decision_digest: str | None
    completion_receipt_id: str | None
    proposals: list[CardEventProposalResponse]
    events: list["CardEventResponse"]


class CardEventProposalLineageResponse(BaseModel):
    """Immutable proposal facts retained on one review event."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    proposal_generator_run_id: str
    proposal_time_s: float
    probability: float
    model_bundle_id: str
    execution_platform: str


class CardEventResponse(BaseModel):
    """One event in the unified CardEvent review collection."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    effective_time_s: float
    type: str
    confidence: str | None
    notes: str | None = None
    state: EVENT_STATES
    origin: EVENT_ORIGINS
    proposal: CardEventProposalLineageResponse | None


class CardEventCreateRequest(BaseModel):
    """One manual event command."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    effective_time_s: float = Field(validation_alias=AliasChoices("effective_time_s", "time_s"))
    type: str = Field(min_length=1)
    confidence: str | None = "confirmed"
    notes: str | None = None


class CardEventCommandRequest(BaseModel):
    """One idempotent command for a proposal-backed or manual event."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    action: EVENT_COMMAND_ACTIONS = Field(validation_alias=AliasChoices("action", "command"))
    effective_time_s: float | None = Field(
        default=None, validation_alias=AliasChoices("effective_time_s", "time_s")
    )
    type: str | None = Field(default=None, min_length=1)
    confidence: str | None = None
    notes: str | None = None


class CardEventCommandResponse(BaseModel):
    """The result of one ordered event command."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cardevent-review-event/v1"]
    review_id: str
    draft_revision: int
    changed_event: CardEventResponse | None
    event_counts: dict[str, int]
    completion_blockers: list[str]


class CardEventReviewListItemResponse(BaseModel):
    """One concise review entry in the recording-owned collection."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    review_url: str
    recording_id: str
    state: Literal["draft", "completed"]
    review_state: Literal["draft", "completed"]
    operator: str
    reviewer: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    completed_version_id: str | None
    completed_version_digest: str | None
    parent_review_id: str | None
    parent_version_id: str | None
    event_counts: dict[str, int]
    reviewed_event_count: int
    proposed_event_count: int
    dismissed_event_count: int


class CardEventReviewCollectionResponse(BaseModel):
    """The review resources owned by one accepted recording."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cardevent-review-collection/v1"]
    recording_id: str
    current_review_id: str | None
    draft_review_id: str | None
    latest_completed_review_id: str | None
    reviews: list[CardEventReviewListItemResponse]


@dataclass(frozen=True, slots=True)
class _CachedCardEventReviewSource:
    """One verified source context keyed by an accepted repository digest."""

    source: CardEventReviewSource
    bundle_fingerprint: str
    card_event_selected: bool


class CardEventReviewSourceContextCache:
    """Reuse verified immutable source context across local review requests."""

    def __init__(self, *, max_entries: int = 128) -> None:
        self.max_entries = max_entries
        self._entries: dict[tuple[str, str], _CachedCardEventReviewSource] = {}
        self._timings: list[dict[str, float | bool | str]] = []
        self._lock = threading.Lock()

    def load(
        self,
        request: Request,
        recording_id: str,
        *,
        require_selected: bool = True,
    ) -> CardEventReviewSource:
        """Return verified source context and record raw cold or warm stage timings."""

        started = time.perf_counter()
        if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
            raise ContractError("invalid_recording_id", "The recording ID is invalid.")

        repository: RepositoryBundleRepository = request.app.state.repository_bundle_repository
        index_started = time.perf_counter()
        indexed = repository.get(recording_id)
        index_ms = _elapsed_ms(index_started)
        if indexed is None:
            self._invalidate_recording(recording_id)
            raise ContractError(
                "recording_not_found",
                "The recording was not found.",
                status_code=404,
            )

        key = (recording_id, indexed.source_sha256)
        with self._lock:
            cached = self._entries.get(key)
        if cached is not None and cached.bundle_fingerprint == indexed.bundle_fingerprint:
            timing = {
                "recording_id": recording_id,
                "source_sha256": indexed.source_sha256,
                "cache_hit": True,
                "repository_index_lookup_ms": index_ms,
                "bundle_metadata_read_ms": 0.0,
                "source_context_validation_ms": 0.0,
                "bundle_member_verification_ms": 0.0,
                "media_probe_ms": 0.0,
                "proposal_projection_ms": 0.0,
            }
            timing["total_ms"] = _elapsed_ms(started)
            self._record_timing(timing)
            return _require_selected(cached, require_selected=require_selected)

        self._invalidate_recording(recording_id)
        timing = {
            "recording_id": recording_id,
            "source_sha256": indexed.source_sha256,
            "cache_hit": False,
            "repository_index_lookup_ms": index_ms,
            "bundle_metadata_read_ms": 0.0,
            "source_context_validation_ms": 0.0,
            "bundle_member_verification_ms": 0.0,
            "media_probe_ms": 0.0,
            "proposal_projection_ms": 0.0,
        }
        source, card_event_selected = _load_source_uncached(
            request,
            recording_id,
            indexed,
            timing,
        )
        cached_source = _CachedCardEventReviewSource(
            source=source,
            bundle_fingerprint=indexed.bundle_fingerprint,
            card_event_selected=card_event_selected,
        )
        with self._lock:
            self._entries[key] = cached_source
            while len(self._entries) > self.max_entries:
                self._entries.pop(next(iter(self._entries)))
        timing["total_ms"] = _elapsed_ms(started)
        self._record_timing(timing)
        return _require_selected(cached_source, require_selected=require_selected)

    def recent_timings(self) -> tuple[dict[str, float | bool | str], ...]:
        """Return raw source-context timing samples for local performance tests."""

        with self._lock:
            return tuple(dict(item) for item in self._timings)

    def _record_timing(self, timing: dict[str, float | bool | str]) -> None:
        with self._lock:
            self._timings.append(dict(timing))
            del self._timings[:-256]

    def _invalidate_recording(self, recording_id: str) -> None:
        with self._lock:
            for key in tuple(self._entries):
                if key[0] == recording_id:
                    del self._entries[key]


def _resource_identity(
    request: Request, review_id: str
) -> tuple[CardEventReviewStore, CardEventReviewSource]:
    store = _review_store(request)
    try:
        identity = store.read_review_identity(review_id)
    except CardEventReviewError as error:
        raise _review_error(error) from error
    recording_id = identity.get("recording_id")
    if not isinstance(recording_id, str):
        raise ContractError(
            "card_event_review_invalid",
            "The stored CardEvent review has no recording owner.",
            status_code=500,
        )
    return store, _load_source(request, recording_id)


@router.get(
    "/v1/recordings/{recording_id}/card-event-reviews",
    response_model=CardEventReviewCollectionResponse,
)
def list_card_event_reviews(
    recording_id: str, request: Request
) -> CardEventReviewCollectionResponse:
    """List all review resources owned by one recording."""

    source = _load_source(request, recording_id, require_selected=False)
    reviews = list(_review_store(request).list_reviews(source))
    draft = next((item for item in reviews if item["state"] == "draft"), None)
    latest_completed = next((item for item in reviews if item["state"] == "completed"), None)
    current = latest_completed or draft
    return CardEventReviewCollectionResponse(
        schema_version=CARD_EVENT_REVIEW_COLLECTION_SCHEMA_VERSION,
        recording_id=recording_id,
        current_review_id=None if current is None else current["review_id"],
        draft_review_id=None if draft is None else draft["review_id"],
        latest_completed_review_id=(
            None if latest_completed is None else latest_completed["review_id"]
        ),
        reviews=[CardEventReviewListItemResponse.model_validate(item) for item in reviews],
    )


@router.post(
    "/v1/recordings/{recording_id}/card-event-reviews",
    response_model=CardEventReviewResourceResponse,
    status_code=201,
)
def create_card_event_review(
    recording_id: str,
    payload: CardEventReviewCreateRequest,
    request: Request,
) -> CardEventReviewResourceResponse:
    """Create one draft review resource for an accepted recording."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).create_review(
            source,
            operator=payload.operator,
            parent_review_id=payload.parent_review_id,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResourceResponse.model_validate(state)


@router.get(
    "/v1/card-event-reviews/{review_id}",
    response_model=CardEventReviewResourceResponse,
)
def get_card_event_review_resource(
    review_id: str, request: Request
) -> CardEventReviewResourceResponse:
    """Return one stable CardEvent review resource."""

    store, source = _resource_identity(request, review_id)
    try:
        state = store.get_review(review_id, source)
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResourceResponse.model_validate(state)


@router.post(
    "/v1/card-event-reviews/{review_id}/events",
    response_model=CardEventCommandResponse,
)
def add_card_event(
    review_id: str,
    payload: CardEventCreateRequest,
    request: Request,
) -> CardEventCommandResponse:
    """Add one reviewed manual event to a CardEvent review."""

    store, source = _resource_identity(request, review_id)
    try:
        result = store.add_event(
            review_id,
            source,
            client_command_id=payload.client_command_id,
            expected_revision=payload.expected_revision,
            effective_time_s=payload.effective_time_s,
            event_type=payload.type,
            confidence=payload.confidence,
            notes=payload.notes,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventCommandResponse.model_validate(result)


@router.patch(
    "/v1/card-event-reviews/{review_id}/events/{event_id}",
    response_model=CardEventCommandResponse,
)
def update_card_event(
    review_id: str,
    event_id: str,
    payload: CardEventCommandRequest,
    request: Request,
) -> CardEventCommandResponse:
    """Apply one idempotent event command."""

    store, source = _resource_identity(request, review_id)
    try:
        result = store.update_event(
            review_id,
            source,
            event_id=event_id,
            client_command_id=payload.client_command_id,
            expected_revision=payload.expected_revision,
            action=payload.action,
            effective_time_s=payload.effective_time_s,
            event_type=payload.type,
            confidence=payload.confidence,
            notes=payload.notes,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventCommandResponse.model_validate(result)


@router.put(
    "/v1/card-event-reviews/{review_id}",
    response_model=CardEventReviewResourceResponse,
)
def update_card_event_review_resource(
    review_id: str,
    payload: CardEventReviewResourceUpdateRequest,
    request: Request,
) -> CardEventReviewResourceResponse:
    """Save a complete next draft for one stable review resource."""

    store, source = _resource_identity(request, review_id)
    try:
        state = store.update_review(
            review_id,
            source,
            annotation=payload.annotation,
            proposals=_proposal_decisions(payload.proposals),
            expected_revision=payload.expected_revision,
            full_video_acknowledged=payload.full_video_acknowledged,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResourceResponse.model_validate(state)


@router.post(
    "/v1/card-event-reviews/{review_id}/complete",
    response_model=CardEventReviewResourceResponse,
)
def complete_card_event_review_resource(
    review_id: str,
    payload: CardEventReviewCompletionRequest,
    request: Request,
) -> CardEventReviewResourceResponse:
    """Complete one stable CardEvent review resource."""

    store, source = _resource_identity(request, review_id)
    try:
        state = store.complete_review(
            review_id,
            source,
            reviewer=payload.reviewer,
            expected_revision=payload.expected_revision,
            full_video_acknowledged=payload.full_video_acknowledged,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResourceResponse.model_validate(state)


@router.get(
    "/v1/recordings/{recording_id}/card-event-review",
    response_model=CardEventReviewResponse,
)
def get_card_event_review(recording_id: str, request: Request) -> CardEventReviewResponse:
    """Return the current draft and immutable proposals for one recording."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).read(source)
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


@router.put(
    "/v1/recordings/{recording_id}/card-event-review/draft",
    response_model=CardEventReviewResponse,
)
def update_card_event_review_draft(
    recording_id: str,
    payload: CardEventReviewDraftUpdateRequest,
    request: Request,
) -> CardEventReviewResponse:
    """Validate and save one complete CardEvent review draft."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).update_draft(
            source,
            annotation=payload.annotation,
            proposals=_proposal_decisions(payload.proposals),
            expected_revision=payload.expected_revision,
            full_video_acknowledged=payload.full_video_acknowledged,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


@router.post(
    "/v1/recordings/{recording_id}/card-event-review/complete",
    response_model=CardEventReviewResponse,
)
def complete_card_event_review(
    recording_id: str,
    payload: CardEventReviewCompletionRequest,
    request: Request,
) -> CardEventReviewResponse:
    """Publish the current complete draft as an immutable reviewed version."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).complete(
            source,
            reviewer=payload.reviewer,
            expected_revision=payload.expected_revision,
            full_video_acknowledged=payload.full_video_acknowledged,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


@router.post(
    "/v1/recordings/{recording_id}/card-event-review/revisions",
    response_model=CardEventReviewResponse,
)
def start_card_event_review_revision(
    recording_id: str,
    payload: CardEventReviewRevisionRequest,
    request: Request,
) -> CardEventReviewResponse:
    """Start a new draft from one immutable reviewed version."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).start_revision(
            source,
            parent_version_id=payload.parent_version_id,
            expected_revision=payload.expected_revision,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


def _review_store(request: Request) -> CardEventReviewStore:
    return request.app.state.card_event_review_store


def _load_source(
    request: Request, recording_id: str, *, require_selected: bool = True
) -> CardEventReviewSource:
    cache = getattr(request.app.state, "card_event_review_source_cache", None)
    if cache is None:
        cache = CardEventReviewSourceContextCache()
        request.app.state.card_event_review_source_cache = cache
    return cache.load(request, recording_id, require_selected=require_selected)


def _load_source_uncached(
    request: Request,
    recording_id: str,
    indexed: StoredRepositoryBundle,
    timing: dict[str, float | bool | str],
) -> tuple[CardEventReviewSource, bool]:
    """Validate one complete bundle and build its immutable review context."""

    storage: RepositoryBundleStorage = request.app.state.repository_bundle_storage
    bundle_path = storage.bundle_path(recording_id)
    try:
        metadata_started = time.perf_counter()
        manifest = (bundle_path / "manifest.json").read_bytes()
        source_record = (bundle_path / "source-record.json").read_bytes()
        task_enrollment = (bundle_path / "initial-task-enrollment.json").read_bytes()
        bundle_descriptor = parse_repository_bundle(manifest)
        proposal_bytes = {
            descriptor.proposal_generator_run_id: (
                bundle_path / descriptor.relative_path
            ).read_bytes()
            for descriptor in bundle_descriptor.files.proposal_generator_runs
        }
        timing["bundle_metadata_read_ms"] = _elapsed_ms(metadata_started)
        validation_started = time.perf_counter()
        bundle, source, enrollments, runs = validate_repository_bundle(
            manifest,
            source_record,
            task_enrollment,
            proposal_bytes,
        )
        if (
            bundle.recording_id != indexed.recording_id
            or bundle.source_asset_id != indexed.source_asset_id
            or bundle.source_sha256 != indexed.source_sha256
        ):
            raise IntakeContractError("repository index and bundle identity differs")
        timing["source_context_validation_ms"] = _elapsed_ms(validation_started)
        verification_started = time.perf_counter()
        _verify_bundle_members(bundle_path, bundle_descriptor)
        timing["bundle_member_verification_ms"] = _elapsed_ms(verification_started)
    except (IntakeContractError, OSError, ValueError) as error:
        raise ContractError(
            "recording_metadata_invalid",
            "The stored recording metadata is invalid.",
            status_code=500,
        ) from error

    card_event_task = next(
        (item for item in enrollments.enrollments if item.task == TASK_CARD_EVENT),
        None,
    )
    card_event_selected = card_event_task is not None and card_event_task.disposition == "selected"

    video_name = Path(bundle.files.video.relative_path).name
    probe_started = time.perf_counter()
    duration_s = _video_duration(bundle_path / bundle.files.video.relative_path)
    timing["media_probe_ms"] = _elapsed_ms(probe_started)
    proposal_started = time.perf_counter()
    proposals = tuple(_proposals(source.source_asset_id, runs))
    timing["proposal_projection_ms"] = _elapsed_ms(proposal_started)
    return (
        CardEventReviewSource(
            recording_id=bundle.recording_id,
            source_asset_id=source.source_asset_id,
            source_sha256=source.sha256,
            video=video_name,
            proposals=proposals,
            duration_s=duration_s,
        ),
        card_event_selected,
    )


def _require_selected(
    cached: _CachedCardEventReviewSource,
    *,
    require_selected: bool,
) -> CardEventReviewSource:
    if require_selected and not cached.card_event_selected:
        raise ContractError(
            "card_event_review_unavailable",
            "The CardEvent task is not selected for this recording.",
            status_code=422,
        )
    return cached.source


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _proposals(
    source_asset_id: str,
    runs: tuple[ProposalGeneratorRun, ...],
) -> list[CardEventProposal]:
    result: list[CardEventProposal] = []
    for run in sorted(runs, key=lambda item: item.proposal_generator_run_id):
        for index, event in enumerate(run.event_proposals):
            result.append(
                CardEventProposal(
                    proposal_id=proposal_id(
                        source_asset_id,
                        run.proposal_generator_run_id,
                        index,
                        event.time_s,
                    ),
                    proposal_generator_run_id=run.proposal_generator_run_id,
                    time_s=event.time_s,
                    probability=event.probability,
                    model_bundle_id=run.model_bundle_id,
                    execution_platform=run.execution_environment.platform,
                )
            )
    return result


def _proposal_decisions(
    value: list[CardEventProposalDecisionRequest] | dict[str, PROPOSAL_DECISIONS],
) -> list[dict[str, str]]:
    if isinstance(value, dict):
        return [
            {"proposal_id": proposal_id_value, "decision": decision}
            for proposal_id_value, decision in value.items()
        ]
    return [item.model_dump() for item in value]


def _verify_bundle_members(bundle_path: Path, descriptor: Any) -> None:
    members = (
        descriptor.files.video,
        descriptor.files.source_record,
        descriptor.files.task_enrollment,
        *descriptor.files.proposal_generator_runs,
    )
    for member in members:
        path = bundle_path / member.relative_path
        value = path.read_bytes()
        if len(value) != member.byte_length or hashlib.sha256(value).hexdigest() != member.sha256:
            raise IntakeContractError(f"Bundle file does not match {member.relative_path}.")


def _video_duration(path: Path) -> float | None:
    try:
        return probe_video_path(path).duration_ms / 1000.0
    except (OSError, VideoProbeError, VideoProbeUnavailable):
        return None


def _review_error(error: CardEventReviewError) -> ContractError:
    if isinstance(error, CardEventReviewConflict):
        return ContractError("card_event_review_conflict", str(error), status_code=409)
    if isinstance(error, CardEventReviewNotFound):
        return ContractError("card_event_review_version_not_found", str(error), status_code=404)
    if isinstance(error, CardEventReviewWriteError):
        return ContractError("internal_error", str(error), status_code=500)
    return ContractError("card_event_review_invalid", str(error), status_code=422)


__all__ = [
    "CardEventCommandRequest",
    "CardEventCommandResponse",
    "CardEventCreateRequest",
    "CardEventResponse",
    "CardEventReviewSourceContextCache",
    "CardEventReviewCollectionResponse",
    "CardEventReviewCompletionRequest",
    "CardEventReviewCreateRequest",
    "CardEventReviewDraftUpdateRequest",
    "CardEventReviewResponse",
    "CardEventReviewResourceResponse",
    "CardEventReviewResourceUpdateRequest",
    "CardEventReviewRevisionRequest",
    "router",
]
