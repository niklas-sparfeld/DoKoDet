"""Strict create, status, and result models for round analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from doko_operations.counterfactual import (
    ROUND_COUNTERFACTUAL_SCHEMA_VERSION,
    CounterfactualObservedCardReference,
    CounterfactualProbabilityOverride,
    RoundCounterfactualRequest,
)
from doko_operations.round_reconstruction import (
    RoundReconstructionContractError,
    RoundReconstructionRunResult,
    RoundSetup,
    SearchLimits,
)
from pydantic import Field, StringConstraints, field_validator, model_validator

from dokodetector_backend.contract import ContractModel, Sha256

ROUND_ANALYSIS_SCHEMA_VERSION = "round-analysis/v1"
ROUND_ANALYSIS_STATES = (
    "queued",
    "analyzing_evidence",
    "reconstructing",
    "complete",
    "failed",
)
ROUND_ANALYSIS_TERMINAL_STATES = ("complete", "failed")
Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class AnalysisRoundRuleset(ContractModel):
    """The fixed ruleset accepted by the round reconstruction contract."""

    name: Literal["doko-normal"]
    version: Literal["v1"]


class AnalysisRoundSetup(ContractModel):
    """Explicit round setup supplied with an analysis request."""

    game_id: Identifier
    round_id: Identifier
    ruleset: AnalysisRoundRuleset
    deck_variant: Literal["doko-40-v1"]
    active_players: list[Identifier] = Field(min_length=4, max_length=4)
    dealer: Identifier
    first_trick_leader: Identifier

    @model_validator(mode="after")
    def validate_with_operations_contract(self) -> AnalysisRoundSetup:
        """Run the shared Plan 0031 setup validation."""

        try:
            RoundSetup.from_mapping(self.model_dump(mode="python"))
        except RoundReconstructionContractError as error:
            raise ValueError(str(error)) from error
        return self

    def to_shared(self) -> RoundSetup:
        """Return the validated operations-library setup value."""

        return RoundSetup.from_mapping(self.model_dump(mode="python"))


class AnalysisSearchLimits(ContractModel):
    """The three explicit Plan 0031 search limits."""

    max_missing_plays: int = Field(ge=0)
    max_hypotheses: int = Field(gt=0)
    max_search_nodes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_with_operations_contract(self) -> AnalysisSearchLimits:
        """Run the shared Plan 0031 search-limit validation."""

        try:
            SearchLimits.from_mapping(self.model_dump(mode="python"))
        except RoundReconstructionContractError as error:
            raise ValueError(str(error)) from error
        return self

    def to_shared(self) -> SearchLimits:
        """Return the validated operations-library search limits."""

        return SearchLimits.from_mapping(self.model_dump(mode="python"))


class RoundAnalysisCreateRequest(ContractModel):
    """Client-created analysis request and its immutable input selection."""

    schema_version: Literal["round-analysis/v1"] = ROUND_ANALYSIS_SCHEMA_VERSION
    analysis_id: UUID
    recording_id: Identifier
    round_id: Identifier
    session_id: UUID
    round_setup: AnalysisRoundSetup
    evidence_package_ids: list[UUID] = Field(min_length=1)
    search: AnalysisSearchLimits

    @model_validator(mode="after")
    def validate_request_identity(self) -> RoundAnalysisCreateRequest:
        if self.round_setup.round_id != self.round_id:
            raise ValueError("round_setup.round_id must match round_id.")
        if len(self.evidence_package_ids) != len(set(self.evidence_package_ids)):
            raise ValueError("evidence_package_ids must contain unique values.")
        return self

    def to_mapping(self) -> dict[str, Any]:
        """Return the JSON object used for canonical persistence."""

        return self.model_dump(mode="json")


class RoundAnalysisResult(ContractModel):
    """Compact terminal result returned by the analysis API."""

    analysis_id: UUID
    terminal_status: Literal["complete"]
    reconstruction_status: Literal["resolved", "ambiguous", "incomplete", "impossible"]
    hypotheses: list[dict[str, Any]]
    focused_decisions: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    input_artifact_id: str = Field(min_length=1, max_length=512)
    input_artifact_sha256: Sha256
    result_artifact_id: str = Field(min_length=1, max_length=512)
    result_artifact_sha256: Sha256


class RoundAnalysisStatus(ContractModel):
    """Status document for one queued, running, or terminal analysis."""

    analysis_id: UUID
    recording_id: Identifier
    round_id: Identifier
    session_id: UUID
    state: Literal[
        "queued",
        "analyzing_evidence",
        "reconstructing",
        "complete",
        "failed",
    ]
    total_evidence_packages: int = Field(ge=0)
    completed_evidence_packages: int = Field(ge=0)
    result: RoundAnalysisResult | None = None
    error: str | None = Field(default=None, min_length=1, max_length=512)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("analysis timestamps must include a UTC offset.")
        if value.utcoffset() != timedelta(0):
            raise ValueError("analysis timestamps must use UTC.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> RoundAnalysisStatus:
        if self.completed_evidence_packages > self.total_evidence_packages:
            raise ValueError("completed_evidence_packages cannot exceed total_evidence_packages.")
        if self.state == "complete":
            if (
                self.result is None
                or self.error is not None
                or self.completed_at is None
                or self.completed_evidence_packages != self.total_evidence_packages
            ):
                raise ValueError("a complete analysis must have a result and completion time.")
            if self.result.analysis_id != self.analysis_id:
                raise ValueError("result.analysis_id must match analysis_id.")
        elif self.state == "failed":
            if self.error is None or self.result is not None or self.completed_at is None:
                raise ValueError("a failed analysis must have an error and completion time.")
        elif self.result is not None or self.error is not None or self.completed_at is not None:
            raise ValueError("a non-terminal analysis cannot have terminal fields.")
        return self


class CounterfactualObservedCardReferenceModel(ContractModel):
    """An observed-card reference supplied by a counterfactual request."""

    observation_id: Identifier
    observed_card_id: Identifier

    def to_shared(self) -> CounterfactualObservedCardReference:
        """Return the validated operations-library reference value."""

        return CounterfactualObservedCardReference(
            observation_id=self.observation_id,
            observed_card_id=self.observed_card_id,
        )


class CounterfactualProbabilityOverrideModel(ContractModel):
    """A candidate probability change supplied by a counterfactual request."""

    observation_id: Identifier
    observed_card_id: Identifier
    card: str = Field(min_length=1, max_length=64)
    probability: float

    def to_shared(self) -> CounterfactualProbabilityOverride:
        """Return the validated operations-library override value."""

        return CounterfactualProbabilityOverride(
            observation_id=self.observation_id,
            observed_card_id=self.observed_card_id,
            card=self.card,
            probability=self.probability,
        )


class RoundCounterfactualCreateRequest(ContractModel):
    """Client-created request for one immutable derived reconstruction."""

    schema_version: Literal["round-analysis-counterfactual/v1"] = (
        ROUND_COUNTERFACTUAL_SCHEMA_VERSION
    )
    counterfactual_id: UUID
    source_analysis_id: UUID
    source_input_sha256: Sha256
    source_result_sha256: Sha256
    excluded_observation_ids: list[Identifier] = Field(default_factory=list)
    excluded_observed_cards: list[CounterfactualObservedCardReferenceModel] = Field(
        default_factory=list
    )
    candidate_probability_overrides: list[CounterfactualProbabilityOverrideModel] = Field(
        default_factory=list
    )

    def to_shared(self) -> RoundCounterfactualRequest:
        """Validate and convert this HTTP payload with the shared operations contract."""

        return RoundCounterfactualRequest.from_mapping(self.model_dump(mode="json"))

    def to_mapping(self) -> dict[str, Any]:
        """Return the JSON object used for canonical persistence."""

        return self.model_dump(mode="json")


class CounterfactualArtifact(ContractModel):
    """Identity and digest for one counterfactual runtime artifact."""

    relative_path: str = Field(min_length=1, max_length=512)
    byte_length: int = Field(ge=0)
    sha256: Sha256


class RoundCounterfactualArtifacts(ContractModel):
    """The request, input, and result artifacts for one counterfactual."""

    request: CounterfactualArtifact
    input: CounterfactualArtifact
    result: CounterfactualArtifact


class RoundCounterfactualResponse(ContractModel):
    """The strict response for one stored counterfactual reconstruction."""

    schema_version: Literal["round-analysis-counterfactual-response/v1"] = (
        "round-analysis-counterfactual-response/v1"
    )
    counterfactual_id: UUID
    source_analysis_id: UUID
    request: RoundCounterfactualCreateRequest
    artifacts: RoundCounterfactualArtifacts
    result: dict[str, Any]

    @field_validator("result")
    @classmethod
    def validate_result(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            return RoundReconstructionRunResult.from_mapping(value).to_mapping()
        except (TypeError, ValueError) as error:
            raise ValueError("counterfactual result is invalid.") from error

    @model_validator(mode="after")
    def validate_identity(self) -> RoundCounterfactualResponse:
        if self.request.counterfactual_id != self.counterfactual_id:
            raise ValueError("request.counterfactual_id must match counterfactual_id.")
        if self.request.source_analysis_id != self.source_analysis_id:
            raise ValueError("request.source_analysis_id must match source_analysis_id.")
        if self.result.get("run_id") != str(self.counterfactual_id):
            raise ValueError("result.run_id must match counterfactual_id.")
        return self


def canonical_analysis_request_bytes(request: RoundAnalysisCreateRequest) -> bytes:
    """Serialize an analysis request as deterministic compact UTF-8 JSON."""

    if not isinstance(request, RoundAnalysisCreateRequest):
        raise TypeError("request must be a RoundAnalysisCreateRequest.")
    return json.dumps(
        request.to_mapping(),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_analysis_request_sha256(request: RoundAnalysisCreateRequest) -> str:
    """Return the digest of an analysis request's canonical JSON bytes."""

    return hashlib.sha256(canonical_analysis_request_bytes(request)).hexdigest()


def parse_round_analysis_create_request_bytes(raw: bytes) -> RoundAnalysisCreateRequest:
    """Parse one canonical or client-supplied UTF-8 analysis request."""

    if not isinstance(raw, bytes):
        raise TypeError("contract bytes must be bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("round-analysis request must be UTF-8 JSON.") from error
    if not isinstance(value, Mapping):
        raise ValueError("round-analysis request must be a JSON object.")
    return RoundAnalysisCreateRequest.model_validate(value)


__all__ = [
    "AnalysisRoundRuleset",
    "AnalysisRoundSetup",
    "AnalysisSearchLimits",
    "CounterfactualArtifact",
    "CounterfactualObservedCardReferenceModel",
    "CounterfactualProbabilityOverrideModel",
    "ROUND_ANALYSIS_SCHEMA_VERSION",
    "ROUND_ANALYSIS_STATES",
    "ROUND_ANALYSIS_TERMINAL_STATES",
    "RoundCounterfactualArtifacts",
    "RoundCounterfactualCreateRequest",
    "RoundCounterfactualResponse",
    "RoundAnalysisCreateRequest",
    "RoundAnalysisResult",
    "RoundAnalysisStatus",
    "canonical_analysis_request_bytes",
    "canonical_analysis_request_sha256",
    "parse_round_analysis_create_request_bytes",
]
