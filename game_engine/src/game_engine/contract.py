"""Strict V1 contracts for table observations and reconstruction input."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
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

from .cards import CARD_IDENTITIES, CardIdentity, load_deck_manifest

OBSERVATION_SCHEMA_VERSION = "table-observation/v1"
RECONSTRUCTION_INPUT_SCHEMA_VERSION = "round-reconstruction-input/v1"
ROUND_SCENARIO_SCHEMA_VERSION = "round-scenario/v1"
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
    """Immutable, closed JSON data for the reconstruction boundary."""

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
    def validate_candidates_and_scores(self) -> ObservedCard:
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


class RulesetReference(ContractModel):
    """Named game-rules version selected by reconstruction input."""

    name: Literal["doko-normal"]
    version: Literal["v1"]


class ReconstructionInput(ContractModel):
    """Round setup and ordered observations supplied to reconstruction."""

    schema_version: Literal["round-reconstruction-input/v1"]
    game_id: Identifier
    round_id: Identifier
    ruleset: RulesetReference
    deck_variant: Literal["doko-40-v1"]
    active_players: list[Identifier] = Field(min_length=4, max_length=4)
    dealer: Identifier
    first_trick_leader: Identifier
    observations: list[TableObservation] = Field(max_length=4096)

    @model_validator(mode="after")
    def validate_round_setup(self) -> ReconstructionInput:
        if len(self.active_players) != len(set(self.active_players)):
            raise ValueError("active_players must be unique.")
        if self.first_trick_leader not in self.active_players:
            raise ValueError("first_trick_leader must be an active player.")
        observation_ids = [observation.observation_id for observation in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation IDs must be unique within a reconstruction input.")
        observation_times = [observation.observed_at_ms for observation in self.observations]
        if observation_times != sorted(observation_times):
            raise ValueError("observations must be ordered by observed_at_ms.")
        return self

    @property
    def trick_count(self) -> int:
        """Return the four-card trick count declared by the selected deck manifest."""

        return load_deck_manifest(self.deck_variant).trick_count


class ScenarioExpectation(ContractModel):
    """Expected behavior recorded with a synthetic round scenario."""

    status: Literal["resolved", "ambiguous", "impossible", "incomplete"]
    trick_count: int = Field(gt=0)
    behavior: str = Field(min_length=1, max_length=512)


class RoundScenario(ContractModel):
    """A reconstruction input plus private synthetic truth and test expectation."""

    schema_version: Literal["round-scenario/v1"]
    scenario_id: Identifier
    description: str = Field(min_length=1, max_length=512)
    enabled_capabilities: list[Capability] = Field(
        min_length=1,
        max_length=len(ANALYZER_CAPABILITIES),
    )
    input: ReconstructionInput
    ground_truth: dict[str, object]
    expected: ScenarioExpectation

    @field_validator("ground_truth")
    @classmethod
    def require_finite_json_ground_truth(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            json.dumps(value, ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("ground_truth must contain finite JSON values.") from error
        return value

    @model_validator(mode="after")
    def validate_scenario(self) -> RoundScenario:
        if self.input.trick_count != self.expected.trick_count:
            raise ValueError("scenario expected trick_count must match the deck manifest.")
        actual_capabilities = {
            capability
            for observation in self.input.observations
            for capability in observation.capabilities
        }
        if set(self.enabled_capabilities) != actual_capabilities:
            raise ValueError("enabled_capabilities must match the input observations.")
        return self


class ContractError(ValueError):
    """A stable error raised while parsing reconstruction contract bytes."""


def validate_observation(payload: Mapping[str, object]) -> TableObservation:
    """Validate one decoded table-observation object."""

    return TableObservation.model_validate(payload)


def parse_observation_bytes(observation_bytes: bytes) -> TableObservation:
    """Parse one UTF-8 table-observation document."""

    return _parse_bytes(observation_bytes, validate_observation, "table observation")


def validate_reconstruction_input(payload: Mapping[str, object]) -> ReconstructionInput:
    """Validate one decoded reconstruction-input object."""

    return ReconstructionInput.model_validate(payload)


def parse_reconstruction_input_bytes(input_bytes: bytes) -> ReconstructionInput:
    """Parse one UTF-8 reconstruction-input document."""

    return _parse_bytes(input_bytes, validate_reconstruction_input, "reconstruction input")


def load_reconstruction_input_file(path: Path) -> ReconstructionInput:
    """Read one reconstruction input or extract it from a checked-in scenario fixture."""

    try:
        input_bytes = path.read_bytes()
    except OSError as error:
        raise ContractError(f"could not read reconstruction input: {path}") from error
    try:
        payload = json.loads(input_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"the reconstruction input is not valid UTF-8 JSON: {path}") from error
    if isinstance(payload, dict) and payload.get("schema_version") == ROUND_SCENARIO_SCHEMA_VERSION:
        try:
            return RoundScenario.model_validate(payload).input
        except ValidationError as error:
            raise ContractError(f"round scenario failed validation: {path}") from error
    return parse_reconstruction_input_bytes(input_bytes)


def canonical_json_bytes(model: BaseModel) -> bytes:
    """Serialize a valid contract model as stable compact JSON bytes."""

    return json.dumps(
        model.model_dump(mode="json", exclude_none=True),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def load_round_scenario(path: Path) -> RoundScenario:
    """Load and validate a synthetic round scenario fixture."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ContractError(f"could not read round scenario: {path}") from error
    except json.JSONDecodeError as error:
        raise ContractError(f"round scenario is not valid JSON: {path}") from error
    try:
        return RoundScenario.model_validate(payload)
    except ValidationError as error:
        raise ContractError("round scenario failed validation.") from error


def _parse_bytes(
    contract_bytes: bytes,
    validator,
    description: str,
) -> BaseModel:
    if not isinstance(contract_bytes, bytes):
        raise TypeError("contract bytes must be bytes.")
    try:
        payload = json.loads(contract_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"the {description} is not valid UTF-8 JSON.") from error
    if not isinstance(payload, dict):
        raise ContractError(f"the {description} JSON value must be an object.")
    try:
        return validator(payload)
    except ValidationError as error:
        raise ContractError(f"the {description} failed validation.") from error


__all__ = [
    "ANALYZER_CAPABILITIES",
    "CALIBRATION_STATES",
    "Capability",
    "OBSERVATION_PROBABILITY_TOLERANCE",
    "OBSERVATION_SCHEMA_VERSION",
    "RECONSTRUCTION_INPUT_SCHEMA_VERSION",
    "ROUND_SCENARIO_SCHEMA_VERSION",
    "AssociationCandidate",
    "AnalyzerMetadata",
    "ContractError",
    "IdentityCandidate",
    "ObservationSession",
    "ObservationSource",
    "ObservedCard",
    "ReconstructionInput",
    "RoundScenario",
    "RulesetReference",
    "ScenarioExpectation",
    "TableObservation",
    "canonical_json_bytes",
    "load_reconstruction_input_file",
    "load_round_scenario",
    "parse_observation_bytes",
    "parse_reconstruction_input_bytes",
    "validate_observation",
    "validate_reconstruction_input",
]
