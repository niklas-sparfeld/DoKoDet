"""Strict versioned table-observation contract for the analyzer side of the boundary."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from .cards import CARD_IDENTITIES, CardIdentity

OBSERVATION_SCHEMA_VERSION = "table-observation/v1"
PILE_OBSERVATION_SCHEMA_VERSION = "table-observation/v2"
OBSERVATION_PROBABILITY_TOLERANCE = 1e-6
CALIBRATION_STATES = ("fixture", "uncalibrated", "calibrated")
ANALYZER_CAPABILITIES = (
    "identity_candidates",
    "presence_score",
    "newly_visible_score",
    "active_area_score",
    "association_candidates",
    "card_tracklets",
)

Capability = Literal[
    "identity_candidates",
    "presence_score",
    "newly_visible_score",
    "active_area_score",
    "association_candidates",
    "card_tracklets",
]
CalibrationState = Literal["fixture", "uncalibrated", "calibrated"]
IdentityStatus = Literal["classified", "face_down", "unusable", "failed"]
CardSide = Literal["face_up", "face_down", "unknown"]
ObservationStatus = Literal["observed", "insufficient_evidence"]
Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
BoundedScore = Annotated[float, Field(ge=0.0, le=1.0)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ContractModel(BaseModel):
    """Immutable, closed JSON data for the analyzer boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ObservationSource(ContractModel):
    """The legacy package or recording-pipeline source that produced an observation."""

    package_id: Identifier | None = None
    snippet_part_name: Identifier | None = None
    recording_id: Identifier | None = None
    video_sha256: Digest | None = None
    assembly_run_id: Identifier | None = None
    input_revision_ids: list[Identifier] | None = None

    @field_validator("video_sha256")
    @classmethod
    def require_lowercase_digest(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("video_sha256 must be a lower-case SHA-256 digest.")
        return value

    @model_validator(mode="after")
    def validate_source_shape(self) -> ObservationSource:
        legacy = self.package_id is not None
        pipeline_values = (
            self.recording_id,
            self.video_sha256,
            self.assembly_run_id,
            self.input_revision_ids,
        )
        pipeline = all(value is not None for value in pipeline_values)
        if legacy == pipeline:
            raise ValueError("observation source must be either package-backed or pipeline-backed.")
        if legacy and self.snippet_part_name is None:
            return self
        if legacy:
            return self
        if self.snippet_part_name is not None:
            raise ValueError("pipeline observation sources cannot contain a snippet part.")
        assert self.input_revision_ids is not None
        if len(self.input_revision_ids) != 3:
            raise ValueError("pipeline observation sources need three input revisions.")
        if len(set(self.input_revision_ids)) != len(self.input_revision_ids):
            raise ValueError("pipeline observation input revisions must be unique.")
        return self


class ObservationSession(ContractModel):
    """Session sequence metadata copied into an observation."""

    session_id: Identifier
    event_sequence: int = Field(ge=1)


class IdentityCandidate(ContractModel):
    """One visual card identity ranked for an observed-card proposal."""

    card: CardIdentity
    probability: float = Field(gt=0.0, le=1.0)

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


class AssociationCandidate(ContractModel):
    """An uncertain link to an observed card in another observation."""

    observed_card_id: Identifier
    score: BoundedScore

    @field_validator("score")
    @classmethod
    def require_finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("association score must be finite.")
        return value


class ObservedCard(ContractModel):
    """One anonymous visual card proposal inside one table observation."""

    observed_card_id: Identifier
    side: CardSide
    identity_status: IdentityStatus = "classified"
    identity_candidates: list[IdentityCandidate] = Field(max_length=24)
    presence_score: BoundedScore | None = None
    newly_visible_score: BoundedScore | None = None
    active_area_score: BoundedScore | None = None
    association_candidates: list[AssociationCandidate] | None = Field(default=None, max_length=24)
    card_tracklet_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_candidates(self) -> ObservedCard:
        if self.identity_status == "classified" and not self.identity_candidates:
            raise ValueError("classified observed cards need identity candidates.")
        if self.identity_status != "classified" and self.identity_candidates:
            raise ValueError(
                f"{self.identity_status} observed cards must not contain identity candidates."
            )
        if not self.identity_candidates:
            return self
        cards = [candidate.card for candidate in self.identity_candidates]
        if len(cards) != len(set(cards)):
            raise ValueError("identity candidate cards must be unique.")

        probabilities = [candidate.probability for candidate in self.identity_candidates]
        if probabilities != sorted(probabilities, reverse=True):
            raise ValueError("identity candidates must be ordered by descending probability.")
        if not math.isclose(
            sum(probabilities),
            1.0,
            rel_tol=0.0,
            abs_tol=OBSERVATION_PROBABILITY_TOLERANCE,
        ):
            raise ValueError(
                "identity candidate probabilities must sum to one within the contract tolerance."
            )
        if self.association_candidates is not None:
            linked_ids = [candidate.observed_card_id for candidate in self.association_candidates]
            if len(linked_ids) != len(set(linked_ids)):
                raise ValueError("association candidate IDs must be unique.")
        return self


class PilePoint(ContractModel):
    """One full-frame normalized point in a coarse pile footprint."""

    x: int = Field(ge=0, le=1000, strict=True)
    y: int = Field(ge=0, le=1000, strict=True)

    @field_validator("x", "y")
    @classmethod
    def require_integer_coordinate(cls, value: int) -> int:
        if isinstance(value, bool):
            raise ValueError("pile coordinates must be integers.")
        return value


class ObservedPileGeometry(ContractModel):
    kind: Literal["pile-region/v1"]
    polygons: list[list[PilePoint]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_polygons(self) -> ObservedPileGeometry:
        for polygon in self.polygons:
            if len(polygon) < 3:
                raise ValueError("pile polygons need at least three points.")
            area = sum(
                polygon[index].x * polygon[(index + 1) % len(polygon)].y
                - polygon[(index + 1) % len(polygon)].x * polygon[index].y
                for index in range(len(polygon))
            )
            if area == 0:
                raise ValueError("pile polygons must have positive area.")
        return self


class PileSourceCandidate(ContractModel):
    revision_id: Identifier
    card_id: Identifier


class ObservedPile(ContractModel):
    """One separate pile footprint retained as visual evidence."""

    pile_id: Identifier
    geometry: ObservedPileGeometry
    normalization: dict[str, object]
    source_candidates: list[PileSourceCandidate] = Field(default_factory=list)
    grouped_candidates: list[dict[str, object]] = Field(default_factory=list)
    grouped_card_states: list[dict[str, object]] = Field(default_factory=list)
    grouped_scene_decision: Literal["accepted", "adjusted", "manual"] | None = None
    origin: Literal["reviewed", "model_prediction"] = "reviewed"
    confidence: BoundedScore | None = None
    model_lineage: dict[str, object] | None = None

    @field_validator("normalization")
    @classmethod
    def validate_normalization(cls, value: dict[str, object]) -> dict[str, object]:
        if set(value) != {"width", "height", "policy_id"}:
            raise ValueError("pile normalization must declare width, height, and policy_id.")
        for field_name in ("width", "height"):
            field_value = value[field_name]
            if (
                isinstance(field_value, bool)
                or not isinstance(field_value, int)
                or field_value <= 0
            ):
                raise ValueError("pile normalization dimensions must be positive integers.")
        if value["policy_id"] != "full-frame-0-1000/v1":
            raise ValueError("pile normalization policy is unsupported.")
        return value

    @field_validator("grouped_candidates", "grouped_card_states", "model_lineage")
    @classmethod
    def require_finite_json_mapping(cls, value: object) -> object:
        if value is not None:
            try:
                json.dumps(value, ensure_ascii=True, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise ValueError("pile metadata must contain finite JSON values.") from error
        return value

    @model_validator(mode="after")
    def validate_lineage(self) -> ObservedPile:
        if self.confidence is not None and not math.isfinite(self.confidence):
            raise ValueError("pile confidence must be finite.")
        if len({(item.revision_id, item.card_id) for item in self.source_candidates}) != len(
            self.source_candidates
        ):
            raise ValueError("pile source candidates must be unique.")
        return self


class AnalyzerMetadata(ContractModel):
    """Analyzer identity recorded with each observation."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=256)


class TableObservation(ContractModel):
    """One ordered, uncertain visual observation with no game claims."""

    schema_version: Literal["table-observation/v1", "table-observation/v2"]
    observation_id: Identifier
    source: ObservationSource
    session: ObservationSession
    observed_at_ms: int = Field(ge=0)
    status: ObservationStatus
    capabilities: list[Capability] = Field(min_length=1, max_length=len(ANALYZER_CAPABILITIES))
    cards: list[ObservedCard] = Field(default_factory=list, max_length=64)
    piles: list[ObservedPile] | None = Field(default=None, max_length=64)
    calibration: CalibrationState
    analyzer: AnalyzerMetadata
    diagnostics: dict[str, object] = Field(default_factory=dict)

    @field_validator("observed_at_ms")
    @classmethod
    def require_integer_timestamp(cls, value: int) -> int:
        if isinstance(value, bool):
            raise ValueError("observed_at_ms must be an integer.")
        return value

    @field_validator("capabilities")
    @classmethod
    def require_ordered_unique_capabilities(cls, value: list[Capability]) -> list[Capability]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique.")
        if value != sorted(value, key=ANALYZER_CAPABILITIES.index):
            raise ValueError("capabilities must use the canonical order.")
        if "identity_candidates" not in value:
            raise ValueError("identity_candidates is required in table observations.")
        return value

    @field_validator("diagnostics")
    @classmethod
    def require_finite_json_diagnostics(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            json.dumps(value, ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("diagnostics must contain finite JSON values.") from error
        return value

    @model_validator(mode="after")
    def validate_status_and_capabilities(self) -> TableObservation:
        if self.status == "insufficient_evidence" and self.cards:
            raise ValueError("insufficient_evidence observations must not contain cards.")
        if self.piles and self.schema_version != PILE_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("pile evidence requires table-observation/v2.")
        pile_ids = [pile.pile_id for pile in (self.piles or [])]
        if len(pile_ids) != len(set(pile_ids)):
            raise ValueError("pile IDs must be unique within an observation.")

        capability_fields = {
            "presence_score": [
                ("presence_score" in card.model_fields_set, card.presence_score)
                for card in self.cards
            ],
            "newly_visible_score": [
                ("newly_visible_score" in card.model_fields_set, card.newly_visible_score)
                for card in self.cards
            ],
            "active_area_score": [
                ("active_area_score" in card.model_fields_set, card.active_area_score)
                for card in self.cards
            ],
            "association_candidates": [
                ("association_candidates" in card.model_fields_set, card.association_candidates)
                for card in self.cards
            ],
            "card_tracklets": [
                ("card_tracklet_id" in card.model_fields_set, card.card_tracklet_id)
                for card in self.cards
            ],
        }
        for capability, fields in capability_fields.items():
            if capability in self.capabilities:
                if any(not present or value is None for present, value in fields):
                    raise ValueError(f"{capability} capability must be present on every card.")
            elif any(present for present, _ in fields):
                raise ValueError(f"{capability} field requires its declared capability.")
        return self


class ContractError(ValueError):
    """A stable error raised while parsing table-observation bytes."""


def validate_observation(payload: Mapping[str, object]) -> TableObservation:
    """Validate one decoded table-observation object."""

    return TableObservation.model_validate(payload)


def parse_observation_bytes(observation_bytes: bytes) -> TableObservation:
    """Parse one UTF-8 table-observation document."""

    if not isinstance(observation_bytes, bytes):
        raise TypeError("observation_bytes must be bytes.")
    try:
        payload = json.loads(observation_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("the table observation is not valid UTF-8 JSON.") from error
    if not isinstance(payload, dict):
        raise ContractError("the table observation JSON value must be an object.")
    try:
        return validate_observation(payload)
    except ValidationError as error:
        raise ContractError("the table observation failed validation.") from error


def canonical_json_bytes(observation: TableObservation) -> bytes:
    """Serialize an observation as stable compact JSON bytes."""

    return json.dumps(
        observation.model_dump(mode="json", exclude_none=True),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = [
    "ANALYZER_CAPABILITIES",
    "CardSide",
    "CALIBRATION_STATES",
    "ContractError",
    "IdentityCandidate",
    "ObservedPile",
    "ObservedPileGeometry",
    "PilePoint",
    "PileSourceCandidate",
    "OBSERVATION_PROBABILITY_TOLERANCE",
    "OBSERVATION_SCHEMA_VERSION",
    "PILE_OBSERVATION_SCHEMA_VERSION",
    "ObservationSession",
    "ObservationSource",
    "ObservedCard",
    "TableObservation",
    "canonical_json_bytes",
    "parse_observation_bytes",
    "validate_observation",
]
