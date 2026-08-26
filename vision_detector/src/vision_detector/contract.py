"""Strict V1 domain types for the visual evidence and detection result boundary."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from vision_detector.cards import CARD_IDENTITIES, CardIdentity

VISION_SCHEMA_VERSION = "vision-detection/v1"
VISION_PROBABILITY_TOLERANCE = 1e-6
MAX_CANDIDATES = len(CARD_IDENTITIES)
MAX_OBSERVATIONS = 32
MAX_OBSERVATION_BYTES = 4096

VisionStatus = Literal[
    "confident",
    "uncertain",
    "no_card_found",
    "insufficient_evidence",
]
CalibrationState = Literal["fixture", "uncalibrated", "calibrated"]
CALIBRATION_STATES = ("fixture", "uncalibrated", "calibrated")
PartName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]

JsonObservation: TypeAlias = dict[str, object]


class VisionContractModel(BaseModel):
    """Immutable model with a closed JSON shape."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class VisionFrame(VisionContractModel):
    """One frame exposed to a detector without client or game context."""

    part_name: PartName
    actual_offset_ms: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    jpeg_bytes: bytes | None = Field(default=None, min_length=1)
    local_reference: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def require_one_frame_source(self) -> VisionFrame:
        if (self.jpeg_bytes is None) == (self.local_reference is None):
            raise ValueError("a vision frame must contain exactly one read-only source.")
        return self


class VisionEvidence(VisionContractModel):
    """Visual-only detector input for one accepted evidence package."""

    package_id: UUID
    event_time_ms: int = Field(ge=0)
    frames: list[VisionFrame] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_frame_names(self) -> VisionEvidence:
        names = [frame.part_name for frame in self.frames]
        if len(names) != len(set(names)):
            raise ValueError("vision frame part names must be unique.")
        return self


class VisionSession(VisionContractModel):
    """Session and event sequence copied into a stored result by orchestration."""

    session_id: UUID
    event_sequence: int = Field(ge=1)


class VisionCandidate(VisionContractModel):
    """One normalized visual card candidate."""

    card: CardIdentity
    probability: float = Field(gt=0.0)

    @field_validator("card")
    @classmethod
    def require_known_card(cls, value: str) -> str:
        if value not in CARD_IDENTITIES:
            raise ValueError("candidate card is not in the shared card set.")
        return value

    @field_validator("probability")
    @classmethod
    def require_finite_probability(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("candidate probability must be finite.")
        return value


class VisionDetectorMetadata(VisionContractModel):
    """Detector identity recorded with each immutable result."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=256)


class VisionDetectionResult(VisionContractModel):
    """One immutable, ranked V1 vision result."""

    schema_version: Literal["vision-detection/v1"]
    result_id: UUID
    package_id: UUID
    session: VisionSession
    status: VisionStatus
    selected_card: CardIdentity | None = None
    candidates: list[VisionCandidate] = Field(max_length=MAX_CANDIDATES)
    calibration: CalibrationState
    detector: VisionDetectorMetadata
    observations: list[JsonObservation] = Field(default_factory=list, max_length=MAX_OBSERVATIONS)
    created_at: datetime

    @field_validator("selected_card")
    @classmethod
    def require_known_selected_card(cls, value: str | None) -> str | None:
        if value is not None and value not in CARD_IDENTITIES:
            raise ValueError("selected_card is not in the shared card set.")
        return value

    @field_validator("created_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a UTC offset.")
        if value.utcoffset() != timedelta(0):
            raise ValueError("created_at must use UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("observations")
    @classmethod
    def validate_observations(cls, value: list[JsonObservation]) -> list[JsonObservation]:
        for observation in value:
            if not isinstance(observation, dict) or any(
                not isinstance(key, str) for key in observation
            ):
                raise ValueError("observations must be JSON objects with string keys.")
            try:
                encoded = json.dumps(observation, ensure_ascii=True, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise ValueError("observations must contain finite JSON values.") from error
            if len(encoded.encode("utf-8")) > MAX_OBSERVATION_BYTES:
                raise ValueError("an observation exceeds the size limit.")
        return value

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return (
            value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )

    @model_validator(mode="after")
    def validate_result_rules(self) -> VisionDetectionResult:
        candidate_cards = [candidate.card for candidate in self.candidates]
        if len(candidate_cards) != len(set(candidate_cards)):
            raise ValueError("candidate cards must be unique.")

        probabilities = [candidate.probability for candidate in self.candidates]
        if probabilities != sorted(probabilities, reverse=True):
            raise ValueError("candidates must be ordered by descending probability.")

        if self.candidates:
            total = sum(probabilities)
            if not math.isclose(
                total,
                1.0,
                rel_tol=0.0,
                abs_tol=VISION_PROBABILITY_TOLERANCE,
            ):
                raise ValueError(
                    "candidate probabilities must sum to one within the contract tolerance."
                )

        ranked_status = self.status in {"confident", "uncertain"}
        if ranked_status != bool(self.candidates):
            raise ValueError(
                "confident and uncertain results require candidates; "
                "abstained results require none."
            )

        if self.status == "confident":
            if self.selected_card != self.candidates[0].card:
                raise ValueError("confident selected_card must equal the first candidate.")
        elif self.selected_card is not None:
            raise ValueError("selected_card is only allowed for confident results.")
        return self


class VisionContractError(ValueError):
    """A stable error raised while parsing result bytes."""


def validate_result(payload: Mapping[str, object]) -> VisionDetectionResult:
    """Validate a decoded result object."""

    return VisionDetectionResult.model_validate(payload)


def parse_result_bytes(result_bytes: bytes) -> VisionDetectionResult:
    """Parse and validate one UTF-8 V1 result document."""

    if not isinstance(result_bytes, bytes):
        raise TypeError("result_bytes must be bytes.")
    try:
        payload = json.loads(result_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisionContractError("the vision result is not valid UTF-8 JSON.") from error
    if not isinstance(payload, dict):
        raise VisionContractError("the vision result JSON value must be an object.")
    try:
        return validate_result(payload)
    except ValidationError as error:
        raise VisionContractError("the vision result failed validation.") from error


def canonical_json_bytes(result: VisionDetectionResult) -> bytes:
    """Serialize a result into the stable bytes used by later persistence."""

    return json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = [
    "CALIBRATION_STATES",
    "MAX_CANDIDATES",
    "MAX_OBSERVATIONS",
    "VISION_PROBABILITY_TOLERANCE",
    "VISION_SCHEMA_VERSION",
    "VisionCandidate",
    "VisionContractError",
    "VisionDetectionResult",
    "VisionDetectorMetadata",
    "VisionEvidence",
    "VisionFrame",
    "VisionSession",
    "VisionStatus",
    "canonical_json_bytes",
    "parse_result_bytes",
    "validate_result",
]
