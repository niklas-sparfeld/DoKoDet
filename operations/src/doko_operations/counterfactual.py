"""Strict in-memory counterfactual derivation for round reconstruction."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from game_engine import (
    ReconstructionInput,
    TableObservation,
)
from game_engine import canonical_json_bytes as canonical_engine_json_bytes
from game_engine.contract import OBSERVATION_PROBABILITY_TOLERANCE

from .round_reconstruction import (
    RoundReconstructionContractError,
    RoundReconstructionRunRequest,
    RoundReconstructionRunResult,
    RoundSetup,
    SearchLimits,
    _card,
    _digest,
    _identifier,
    _mapping,
    _probability,
    _strict,
    _unique,
    canonical_result_bytes,
    reconstruct_round_reconstruction_input,
    sha256_bytes,
)

ROUND_COUNTERFACTUAL_SCHEMA_VERSION = "round-analysis-counterfactual/v1"


def _uuid(value: Any, field: str) -> UUID:
    if not isinstance(value, str) or not value.strip():
        raise RoundReconstructionContractError(f"{field} must be a UUID.")
    try:
        return UUID(value)
    except ValueError as error:
        raise RoundReconstructionContractError(f"{field} must be a UUID.") from error


@dataclass(frozen=True, slots=True)
class CounterfactualObservedCardReference:
    """One observation and observed-card reference used by a counterfactual."""

    observation_id: str
    observed_card_id: str

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        context: str,
    ) -> CounterfactualObservedCardReference:
        data = _mapping(raw, context)
        _strict(data, {"observation_id", "observed_card_id"}, context)
        return cls(
            observation_id=_identifier(data["observation_id"], f"{context}.observation_id"),
            observed_card_id=_identifier(data["observed_card_id"], f"{context}.observed_card_id"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "observation_id": self.observation_id,
            "observed_card_id": self.observed_card_id,
        }


@dataclass(frozen=True, slots=True)
class CounterfactualProbabilityOverride:
    """A requested probability for one existing identity candidate."""

    observation_id: str
    observed_card_id: str
    card: str
    probability: float

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        context: str,
    ) -> CounterfactualProbabilityOverride:
        data = _mapping(raw, context)
        _strict(data, {"observation_id", "observed_card_id", "card", "probability"}, context)
        return cls(
            observation_id=_identifier(data["observation_id"], f"{context}.observation_id"),
            observed_card_id=_identifier(data["observed_card_id"], f"{context}.observed_card_id"),
            card=_card(data["card"], f"{context}.card"),
            probability=_probability(data["probability"], f"{context}.probability"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "observed_card_id": self.observed_card_id,
            "card": self.card,
            "probability": self.probability,
        }


@dataclass(frozen=True, slots=True)
class RoundCounterfactualRequest:
    """A strict immutable request for one derived reconstruction."""

    counterfactual_id: UUID
    source_analysis_id: UUID
    source_input_sha256: str
    source_result_sha256: str
    excluded_observation_ids: tuple[str, ...]
    excluded_observed_cards: tuple[CounterfactualObservedCardReference, ...]
    candidate_probability_overrides: tuple[CounterfactualProbabilityOverride, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RoundCounterfactualRequest:
        data = _mapping(raw, "round-analysis-counterfactual")
        _strict(
            data,
            {
                "schema_version",
                "counterfactual_id",
                "source_analysis_id",
                "source_input_sha256",
                "source_result_sha256",
                "excluded_observation_ids",
                "excluded_observed_cards",
                "candidate_probability_overrides",
            },
            "round-analysis-counterfactual",
        )
        if data["schema_version"] != ROUND_COUNTERFACTUAL_SCHEMA_VERSION:
            raise RoundReconstructionContractError(
                "unsupported round-analysis-counterfactual schema version."
            )
        raw_excluded_observations = data["excluded_observation_ids"]
        if not isinstance(raw_excluded_observations, list):
            raise RoundReconstructionContractError("excluded_observation_ids must be a list.")
        excluded_observations = _unique(
            tuple(
                _identifier(value, f"excluded_observation_ids[{index}]")
                for index, value in enumerate(raw_excluded_observations)
            ),
            "excluded_observation_ids",
        )
        raw_excluded_cards = data["excluded_observed_cards"]
        if not isinstance(raw_excluded_cards, list):
            raise RoundReconstructionContractError("excluded_observed_cards must be a list.")
        excluded_cards = tuple(
            CounterfactualObservedCardReference.from_mapping(
                value, f"excluded_observed_cards[{index}]"
            )
            for index, value in enumerate(raw_excluded_cards)
        )
        _unique(
            tuple((item.observation_id, item.observed_card_id) for item in excluded_cards),
            "excluded_observed_cards",
        )
        raw_overrides = data["candidate_probability_overrides"]
        if not isinstance(raw_overrides, list):
            raise RoundReconstructionContractError(
                "candidate_probability_overrides must be a list."
            )
        overrides = tuple(
            CounterfactualProbabilityOverride.from_mapping(
                value, f"candidate_probability_overrides[{index}]"
            )
            for index, value in enumerate(raw_overrides)
        )
        _unique(
            tuple((item.observation_id, item.observed_card_id, item.card) for item in overrides),
            "candidate_probability_overrides",
        )
        if not excluded_observations and not excluded_cards and not overrides:
            raise RoundReconstructionContractError(
                "a counterfactual request must contain at least one change."
            )
        return cls(
            counterfactual_id=_uuid(data["counterfactual_id"], "counterfactual_id"),
            source_analysis_id=_uuid(data["source_analysis_id"], "source_analysis_id"),
            source_input_sha256=_digest(data["source_input_sha256"], "source_input_sha256"),
            source_result_sha256=_digest(data["source_result_sha256"], "source_result_sha256"),
            excluded_observation_ids=excluded_observations,
            excluded_observed_cards=excluded_cards,
            candidate_probability_overrides=overrides,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": ROUND_COUNTERFACTUAL_SCHEMA_VERSION,
            "counterfactual_id": str(self.counterfactual_id),
            "source_analysis_id": str(self.source_analysis_id),
            "source_input_sha256": self.source_input_sha256,
            "source_result_sha256": self.source_result_sha256,
            "excluded_observation_ids": list(self.excluded_observation_ids),
            "excluded_observed_cards": [item.to_mapping() for item in self.excluded_observed_cards],
            "candidate_probability_overrides": [
                item.to_mapping() for item in self.candidate_probability_overrides
            ],
        }


@dataclass(frozen=True, slots=True)
class RoundCounterfactualRun:
    """The derived input and deterministic result of one counterfactual run."""

    request: RoundCounterfactualRequest
    reconstruction_request: RoundReconstructionRunRequest
    input: ReconstructionInput
    result: RoundReconstructionRunResult
    input_bytes: bytes
    result_bytes: bytes


def validate_counterfactual_request(
    request: RoundCounterfactualRequest,
    source_input: ReconstructionInput,
    source_result: RoundReconstructionRunResult,
) -> None:
    """Validate source identity, hashes, and all request references."""

    if not isinstance(request, RoundCounterfactualRequest):
        raise TypeError("request must be a RoundCounterfactualRequest.")
    if not isinstance(source_input, ReconstructionInput):
        raise TypeError("source_input must be a ReconstructionInput.")
    if not isinstance(source_result, RoundReconstructionRunResult):
        raise TypeError("source_result must be a RoundReconstructionRunResult.")
    if source_result.run_id != str(request.source_analysis_id):
        raise RoundReconstructionContractError(
            "source_analysis_id must match the source reconstruction result run_id."
        )
    source_input_bytes = canonical_engine_json_bytes(source_input)
    if sha256_bytes(source_input_bytes) != request.source_input_sha256:
        raise RoundReconstructionContractError("source_input_sha256 does not match source input.")
    source_result_bytes = canonical_result_bytes(source_result)
    if sha256_bytes(source_result_bytes) != request.source_result_sha256:
        raise RoundReconstructionContractError("source_result_sha256 does not match source result.")
    input_observation_ids = tuple(item.observation_id for item in source_input.observations)
    result_observation_ids = tuple(item.observation_id for item in source_result.sources)
    if result_observation_ids != input_observation_ids:
        raise RoundReconstructionContractError(
            "source result sources must match source input observations in order."
        )
    _validate_counterfactual_references(request, source_input)


def _validate_counterfactual_references(
    request: RoundCounterfactualRequest,
    source_input: ReconstructionInput,
) -> None:
    """Validate every requested change against one source input."""

    if (
        not request.excluded_observation_ids
        and not request.excluded_observed_cards
        and not request.candidate_probability_overrides
    ):
        raise RoundReconstructionContractError(
            "a counterfactual request must contain at least one change."
        )
    excluded_references = [
        (item.observation_id, item.observed_card_id) for item in request.excluded_observed_cards
    ]
    if len(excluded_references) != len(set(excluded_references)):
        raise RoundReconstructionContractError(
            "excluded_observed_cards must contain unique values."
        )
    override_references = [
        (item.observation_id, item.observed_card_id, item.card)
        for item in request.candidate_probability_overrides
    ]
    if len(override_references) != len(set(override_references)):
        raise RoundReconstructionContractError(
            "candidate_probability_overrides must contain unique candidates."
        )
    input_observations = {item.observation_id: item for item in source_input.observations}
    if len(request.excluded_observation_ids) >= len(input_observations):
        raise RoundReconstructionContractError(
            "a counterfactual must retain at least one source observation."
        )
    for observation_id in request.excluded_observation_ids:
        if observation_id not in input_observations:
            raise RoundReconstructionContractError(
                f"excluded observation {observation_id!r} does not occur in source input."
            )
    excluded_observation_ids = set(request.excluded_observation_ids)
    excluded_cards = {
        (item.observation_id, item.observed_card_id) for item in request.excluded_observed_cards
    }
    for reference in request.excluded_observed_cards:
        observation = input_observations.get(reference.observation_id)
        if observation is None:
            raise RoundReconstructionContractError(
                f"excluded observed-card observation {reference.observation_id!r} does not occur "
                "in source input."
            )
        if reference.observation_id in excluded_observation_ids:
            raise RoundReconstructionContractError(
                "an excluded observed card cannot belong to an excluded observation."
            )
        if not any(
            card.observed_card_id == reference.observed_card_id for card in observation.cards
        ):
            raise RoundReconstructionContractError(
                f"excluded observed card {reference.observed_card_id!r} does not occur in "
                f"observation {reference.observation_id!r}."
            )
    for override in request.candidate_probability_overrides:
        observation = input_observations.get(override.observation_id)
        if observation is None:
            raise RoundReconstructionContractError(
                f"override observation {override.observation_id!r} does not occur in source input."
            )
        if override.observation_id in excluded_observation_ids:
            raise RoundReconstructionContractError(
                "a probability override cannot belong to an excluded observation."
            )
        reference = (override.observation_id, override.observed_card_id)
        if reference in excluded_cards:
            raise RoundReconstructionContractError(
                "a probability override cannot target an excluded observed card."
            )
        card = next(
            (
                item
                for item in observation.cards
                if item.observed_card_id == override.observed_card_id
            ),
            None,
        )
        if card is None:
            raise RoundReconstructionContractError(
                f"override observed card {override.observed_card_id!r} does not occur in "
                f"observation {override.observation_id!r}."
            )
        if len(card.identity_candidates) == 1:
            raise RoundReconstructionContractError(
                "a one-candidate distribution cannot be overridden."
            )
        baseline = next(
            (
                candidate
                for candidate in card.identity_candidates
                if candidate.card == override.card
            ),
            None,
        )
        if baseline is None:
            raise RoundReconstructionContractError(
                f"override candidate {override.card!r} does not occur in observed card "
                f"{override.observed_card_id!r}."
            )
        if override.probability == baseline.probability:
            raise RoundReconstructionContractError(
                "a probability override must differ from its baseline probability."
            )
    overrides_by_reference: dict[tuple[str, str], list[CounterfactualProbabilityOverride]] = {}
    for override in request.candidate_probability_overrides:
        overrides_by_reference.setdefault(
            (override.observation_id, override.observed_card_id), []
        ).append(override)
    for reference, overrides in overrides_by_reference.items():
        card = next(
            item
            for item in input_observations[reference[0]].cards
            if item.observed_card_id == reference[1]
        )
        baseline_by_card = {
            candidate.card: candidate.probability for candidate in card.identity_candidates
        }
        target_probability = sum(item.probability for item in overrides)
        baseline_probability = sum(baseline_by_card[item.card] for item in overrides)
        if target_probability >= 1.0:
            raise RoundReconstructionContractError(
                "probability overrides must leave positive probability for every retained "
                "candidate."
            )
        if not math.isfinite(target_probability) or not math.isfinite(baseline_probability):
            raise RoundReconstructionContractError("probability override values must be finite.")


def _derived_candidates(
    card: Any,
    overrides: Sequence[CounterfactualProbabilityOverride],
) -> list[dict[str, Any]]:
    """Apply candidate overrides and preserve baseline order for probability ties."""

    if not overrides:
        return [
            candidate.model_dump(mode="python", exclude_unset=True)
            for candidate in card.identity_candidates
        ]
    override_by_card = {item.card: item.probability for item in overrides}
    baseline_total = sum(
        candidate.probability
        for candidate in card.identity_candidates
        if candidate.card in override_by_card
    )
    target_total = sum(override_by_card.values())
    other_candidates = [
        candidate
        for candidate in card.identity_candidates
        if candidate.card not in override_by_card
    ]
    if other_candidates:
        remaining_baseline = 1.0 - baseline_total
        remaining_target = 1.0 - target_total
        if remaining_baseline <= 0.0 or remaining_target <= 0.0:
            raise RoundReconstructionContractError(
                "probability overrides cannot produce a positive candidate distribution."
            )
        scale = remaining_target / remaining_baseline
        candidates = [
            {
                "card": candidate.card,
                "probability": override_by_card.get(candidate.card, candidate.probability * scale),
            }
            for candidate in card.identity_candidates
        ]
    else:
        if not math.isclose(
            target_total,
            1.0,
            rel_tol=0.0,
            abs_tol=OBSERVATION_PROBABILITY_TOLERANCE,
        ):
            raise RoundReconstructionContractError(
                "probability overrides must sum to one when all candidates are overridden."
            )
        candidates = [
            {"card": candidate.card, "probability": override_by_card[candidate.card]}
            for candidate in card.identity_candidates
        ]
    for candidate in candidates:
        probability = candidate["probability"]
        if (
            not isinstance(probability, (int, float))
            or not math.isfinite(probability)
            or probability <= 0
        ):
            raise RoundReconstructionContractError(
                "derived candidate probabilities must be finite and greater than zero."
            )
    if not math.isclose(
        sum(candidate["probability"] for candidate in candidates),
        1.0,
        rel_tol=0.0,
        abs_tol=OBSERVATION_PROBABILITY_TOLERANCE,
    ):
        raise RoundReconstructionContractError(
            "derived candidate probabilities must sum to one within the "
            "table-observation tolerance."
        )
    baseline_order = {
        candidate.card: index for index, candidate in enumerate(card.identity_candidates)
    }
    return sorted(
        candidates,
        key=lambda candidate: (-candidate["probability"], baseline_order[candidate["card"]]),
    )


def derive_counterfactual_input(
    request: RoundCounterfactualRequest,
    source_input: ReconstructionInput,
) -> ReconstructionInput:
    """Return a new input with only the requested evidence changes applied."""

    if not isinstance(request, RoundCounterfactualRequest):
        raise TypeError("request must be a RoundCounterfactualRequest.")
    if not isinstance(source_input, ReconstructionInput):
        raise TypeError("source_input must be a ReconstructionInput.")
    _validate_counterfactual_references(request, source_input)
    excluded_observation_ids = set(request.excluded_observation_ids)
    excluded_cards = {
        (item.observation_id, item.observed_card_id) for item in request.excluded_observed_cards
    }
    overrides_by_reference: dict[tuple[str, str], list[CounterfactualProbabilityOverride]] = {}
    for override in request.candidate_probability_overrides:
        overrides_by_reference.setdefault(
            (override.observation_id, override.observed_card_id), []
        ).append(override)

    derived_observations: list[TableObservation] = []
    for observation in source_input.observations:
        if observation.observation_id in excluded_observation_ids:
            continue
        derived_cards: list[dict[str, Any]] = []
        for card in observation.cards:
            reference = (observation.observation_id, card.observed_card_id)
            if reference in excluded_cards:
                continue
            card_payload = card.model_dump(mode="python", exclude_unset=True)
            card_payload["identity_candidates"] = _derived_candidates(
                card,
                overrides_by_reference.get(reference, ()),
            )
            derived_cards.append(card_payload)
        observation_payload = observation.model_dump(mode="python", exclude_unset=True)
        observation_payload["cards"] = derived_cards
        try:
            derived_observations.append(TableObservation.model_validate(observation_payload))
        except ValueError as error:
            raise RoundReconstructionContractError(
                f"derived observation {observation.observation_id!r} failed validation."
            ) from error
    payload = source_input.model_dump(mode="python")
    payload["observations"] = derived_observations
    try:
        return ReconstructionInput.model_validate(payload)
    except ValueError as error:
        raise RoundReconstructionContractError(
            "derived round-reconstruction-input/v1 failed validation."
        ) from error


def validate_round_counterfactual_request(
    payload: Mapping[str, Any],
) -> RoundCounterfactualRequest:
    """Validate one decoded counterfactual request object."""

    return RoundCounterfactualRequest.from_mapping(payload)


def parse_round_counterfactual_request_bytes(raw: bytes) -> RoundCounterfactualRequest:
    """Parse one UTF-8 round-analysis-counterfactual/v1 document."""

    if not isinstance(raw, bytes):
        raise TypeError("contract bytes must be bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RoundReconstructionContractError(
            "round-analysis-counterfactual must be UTF-8 JSON."
        ) from error
    return validate_round_counterfactual_request(_mapping(value, "round-analysis-counterfactual"))


def canonical_counterfactual_bytes(request: RoundCounterfactualRequest) -> bytes:
    """Serialize a counterfactual request as stable compact JSON bytes."""

    if not isinstance(request, RoundCounterfactualRequest):
        raise TypeError("request must be a RoundCounterfactualRequest.")
    return json.dumps(
        request.to_mapping(),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_counterfactual_sha256(request: RoundCounterfactualRequest) -> str:
    """Return the SHA-256 digest of canonical counterfactual request bytes."""

    return sha256_bytes(canonical_counterfactual_bytes(request))


def recompute_counterfactual(
    request: RoundCounterfactualRequest,
    source_input: ReconstructionInput,
    source_result: RoundReconstructionRunResult,
    *,
    deck_manifest_path: str | Path | None = None,
) -> RoundCounterfactualRun:
    """Derive and recompute one counterfactual without changing source artifacts."""

    validate_counterfactual_request(request, source_input, source_result)
    derived_input = derive_counterfactual_input(request, source_input)
    retained_ids = {observation.observation_id for observation in derived_input.observations}
    source_records = tuple(
        record for record in source_result.sources if record.observation_id in retained_ids
    )
    reconstruction_request = RoundReconstructionRunRequest(
        run_id=str(request.counterfactual_id),
        round_setup=RoundSetup.from_mapping(
            {
                "game_id": source_input.game_id,
                "round_id": source_input.round_id,
                "ruleset": source_input.ruleset.model_dump(mode="python"),
                "deck_variant": source_input.deck_variant,
                "active_players": list(source_input.active_players),
                "dealer": source_input.dealer,
                "first_trick_leader": source_input.first_trick_leader,
            }
        ),
        observation_paths=tuple(record.observation_path for record in source_records),
        search=SearchLimits.from_mapping(source_result.search.to_mapping()),
        output_root=".",
    )
    result = reconstruct_round_reconstruction_input(
        reconstruction_request,
        derived_input,
        source_records,
        deck_manifest_path=deck_manifest_path,
    )
    input_bytes = canonical_engine_json_bytes(derived_input)
    result_bytes = canonical_result_bytes(result)
    return RoundCounterfactualRun(
        request=request,
        reconstruction_request=reconstruction_request,
        input=derived_input,
        result=result,
        input_bytes=input_bytes,
        result_bytes=result_bytes,
    )


__all__ = [
    "ROUND_COUNTERFACTUAL_SCHEMA_VERSION",
    "CounterfactualObservedCardReference",
    "CounterfactualProbabilityOverride",
    "RoundCounterfactualRequest",
    "RoundCounterfactualRun",
    "canonical_counterfactual_bytes",
    "canonical_counterfactual_sha256",
    "derive_counterfactual_input",
    "parse_round_counterfactual_request_bytes",
    "recompute_counterfactual",
    "validate_counterfactual_request",
    "validate_round_counterfactual_request",
]
