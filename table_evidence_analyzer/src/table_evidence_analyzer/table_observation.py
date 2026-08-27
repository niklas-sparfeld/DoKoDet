"""Strict V1 table-observation contract for the analyzer side of the boundary."""

from __future__ import annotations

import json
import math
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


class ContractModel(BaseModel):
    """Immutable, closed JSON data for the analyzer boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ObservationSource(ContractModel):
    """The evidence package and optional snippet that produced an observation."""

    package_id: Identifier
    snippet_part_name: Identifier | None = None


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
    identity_candidates: list[IdentityCandidate] = Field(min_length=1, max_length=24)
    presence_score: BoundedScore | None = None
    newly_visible_score: BoundedScore | None = None
    active_area_score: BoundedScore | None = None
    association_candidates: list[AssociationCandidate] | None = Field(default=None, max_length=24)
    card_tracklet_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_candidates(self) -> ObservedCard:
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


class AnalyzerMetadata(ContractModel):
    """Analyzer identity recorded with each observation."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=256)


class TableObservation(ContractModel):
    """One ordered, uncertain visual observation with no game claims."""

    schema_version: Literal["table-observation/v1"]
    observation_id: Identifier
    source: ObservationSource
    session: ObservationSession
    observed_at_ms: int = Field(ge=0)
    status: ObservationStatus
    capabilities: list[Capability] = Field(min_length=1, max_length=len(ANALYZER_CAPABILITIES))
    cards: list[ObservedCard] = Field(default_factory=list, max_length=64)
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
            raise ValueError("identity_candidates is required in table-observation/v1.")
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
    "CALIBRATION_STATES",
    "ContractError",
    "IdentityCandidate",
    "OBSERVATION_PROBABILITY_TOLERANCE",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationSession",
    "ObservationSource",
    "ObservedCard",
    "TableObservation",
    "canonical_json_bytes",
    "parse_observation_bytes",
    "validate_observation",
]
