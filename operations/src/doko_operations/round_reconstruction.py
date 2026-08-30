"""Strict contracts for non-streaming round-reconstruction runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from game_engine import (
    CARD_IDENTITIES,
    RECONSTRUCTION_INPUT_SCHEMA_VERSION,
    DokoNormalRuleset,
    ReconstructionInput,
    TableObservation,
    load_deck_manifest,
    parse_observation_bytes,
    reconstruct_round,
)
from game_engine import ContractError as GameEngineContractError
from game_engine import ReconstructionResult as EngineReconstructionResult
from game_engine import canonical_json_bytes as canonical_engine_json_bytes

ROUND_RECONSTRUCTION_RUN_SCHEMA_VERSION = "round-reconstruction-run/v1"
ROUND_RECONSTRUCTION_RESULT_SCHEMA_VERSION = "round-reconstruction-result/v1"
OPERATIONS_PACKAGE_VERSION = "0.1.0"

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RECONSTRUCTION_STATUSES = ("resolved", "ambiguous", "incomplete", "impossible")
CALIBRATION_STATES = ("fixture", "uncalibrated", "calibrated")
CAPABILITIES = (
    "identity_candidates",
    "presence_score",
    "newly_visible_score",
    "active_area_score",
    "association_candidates",
    "card_tracklets",
)
EVIDENCE_FAMILIES = ("presence", "transition", "active_area", "tracklet")


class RoundReconstructionContractError(ValueError):
    """Raised when a round-reconstruction contract is invalid."""


class RoundReconstructionPublicationError(RoundReconstructionContractError):
    """Raised when a round-reconstruction artifact run cannot be published."""


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RoundReconstructionContractError(f"{context} must be an object.")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise RoundReconstructionContractError(
            f"{context} has invalid fields ({'; '.join(details)})."
        )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoundReconstructionContractError(f"{field} must be a non-empty string.")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if IDENTIFIER.fullmatch(result) is None or len(result) > 128:
        raise RoundReconstructionContractError(f"{field} must be a safe identifier.")
    return result


def _path_string(value: Any, field: str) -> str:
    result = _text(value, field)
    if "\x00" in result:
        raise RoundReconstructionContractError(f"{field} must not contain a NUL character.")
    return result


def _digest(value: Any, field: str) -> str:
    result = _text(value, field)
    if SHA256.fullmatch(result) is None:
        raise RoundReconstructionContractError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def sha256_bytes(value: bytes) -> str:
    """Return the lower-case SHA-256 digest of exact source bytes."""

    if not isinstance(value, bytes):
        raise TypeError("digest input must be bytes.")
    return hashlib.sha256(value).hexdigest()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RoundReconstructionContractError(f"{field} must be a positive integer.")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RoundReconstructionContractError(f"{field} must be a non-negative integer.")
    return value


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoundReconstructionContractError(f"{field} must be a finite number.")
    result = float(value)
    if not math.isfinite(result):
        raise RoundReconstructionContractError(f"{field} must be a finite number.")
    return result


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise RoundReconstructionContractError(f"{field} must be a boolean.")
    return value


def _string_list(value: Any, field: str, *, identifiers: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RoundReconstructionContractError(f"{field} must be a list.")
    validator = _identifier if identifiers else _text
    return tuple(validator(item, f"{field}[{index}]") for index, item in enumerate(value))


def _unique(values: Sequence[str], field: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise RoundReconstructionContractError(f"{field} must contain unique values.")
    return tuple(values)


def _card(value: Any, field: str) -> str:
    result = _text(value, field)
    if result not in CARD_IDENTITIES:
        raise RoundReconstructionContractError(f"{field} is not a known visual card identity.")
    return result


def _finite_json(value: Any, field: str) -> Any:
    try:
        json.dumps(value, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise RoundReconstructionContractError(
            f"{field} must contain finite JSON values."
        ) from error
    return value


@dataclass(frozen=True, slots=True)
class RoundRuleset:
    """The ruleset name and version selected for a round."""

    name: Literal["doko-normal"]
    version: Literal["v1"]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RoundRuleset:
        data = _mapping(raw, "round_setup.ruleset")
        _strict(data, {"name", "version"}, "round_setup.ruleset")
        if data["name"] != "doko-normal" or data["version"] != "v1":
            raise RoundReconstructionContractError("round_setup.ruleset must be doko-normal/v1.")
        return cls(name="doko-normal", version="v1")

    def to_mapping(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class RoundSetup:
    """Explicit game and round setup for one reconstruction run."""

    game_id: str
    round_id: str
    ruleset: RoundRuleset
    deck_variant: Literal["doko-40-v1"]
    active_players: tuple[str, ...]
    dealer: str
    first_trick_leader: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RoundSetup:
        data = _mapping(raw, "round_setup")
        _strict(
            data,
            {
                "game_id",
                "round_id",
                "ruleset",
                "deck_variant",
                "active_players",
                "dealer",
                "first_trick_leader",
            },
            "round_setup",
        )
        ruleset = RoundRuleset.from_mapping(data["ruleset"])
        if data["deck_variant"] != "doko-40-v1":
            raise RoundReconstructionContractError("round_setup.deck_variant must be doko-40-v1.")
        players = _string_list(
            data["active_players"], "round_setup.active_players", identifiers=True
        )
        if len(players) != 4:
            raise RoundReconstructionContractError(
                "round_setup.active_players must contain exactly four players."
            )
        _unique(players, "round_setup.active_players")
        leader = _identifier(data["first_trick_leader"], "round_setup.first_trick_leader")
        if leader not in players:
            raise RoundReconstructionContractError(
                "round_setup.first_trick_leader must be an active player."
            )
        return cls(
            game_id=_identifier(data["game_id"], "round_setup.game_id"),
            round_id=_identifier(data["round_id"], "round_setup.round_id"),
            ruleset=ruleset,
            deck_variant="doko-40-v1",
            active_players=players,
            dealer=_identifier(data["dealer"], "round_setup.dealer"),
            first_trick_leader=leader,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "round_id": self.round_id,
            "ruleset": self.ruleset.to_mapping(),
            "deck_variant": self.deck_variant,
            "active_players": list(self.active_players),
            "dealer": self.dealer,
            "first_trick_leader": self.first_trick_leader,
        }


@dataclass(frozen=True, slots=True)
class SearchLimits:
    """The three explicit search bounds accepted by the reconstruction oracle."""

    max_missing_plays: int
    max_hypotheses: int
    max_search_nodes: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "search") -> SearchLimits:
        data = _mapping(raw, context)
        _strict(data, {"max_missing_plays", "max_hypotheses", "max_search_nodes"}, context)
        return cls(
            max_missing_plays=_non_negative_int(
                data["max_missing_plays"], f"{context}.max_missing_plays"
            ),
            max_hypotheses=_positive_int(data["max_hypotheses"], f"{context}.max_hypotheses"),
            max_search_nodes=_positive_int(data["max_search_nodes"], f"{context}.max_search_nodes"),
        )

    def to_mapping(self) -> dict[str, int]:
        return {
            "max_missing_plays": self.max_missing_plays,
            "max_hypotheses": self.max_hypotheses,
            "max_search_nodes": self.max_search_nodes,
        }


@dataclass(frozen=True, slots=True)
class RoundReconstructionRunRequest:
    """Validated input selecting observations and explicit reconstruction setup."""

    run_id: str
    round_setup: RoundSetup
    observation_paths: tuple[str, ...]
    search: SearchLimits
    output_root: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RoundReconstructionRunRequest:
        data = _mapping(raw, "round-reconstruction-run")
        _strict(
            data,
            {
                "schema_version",
                "run_id",
                "round_setup",
                "observation_paths",
                "search",
                "output_root",
            },
            "round-reconstruction-run",
        )
        if data["schema_version"] != ROUND_RECONSTRUCTION_RUN_SCHEMA_VERSION:
            raise RoundReconstructionContractError(
                "unsupported round-reconstruction-run schema version."
            )
        paths = _string_list(data["observation_paths"], "observation_paths")
        if not paths:
            raise RoundReconstructionContractError(
                "observation_paths must contain at least one path."
            )
        _unique(paths, "observation_paths")
        return cls(
            run_id=_identifier(data["run_id"], "run_id"),
            round_setup=RoundSetup.from_mapping(data["round_setup"]),
            observation_paths=tuple(
                _path_string(path, f"observation_paths[{index}]")
                for index, path in enumerate(paths)
            ),
            search=SearchLimits.from_mapping(data["search"]),
            output_root=_path_string(data["output_root"], "output_root"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": ROUND_RECONSTRUCTION_RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "round_setup": self.round_setup.to_mapping(),
            "observation_paths": list(self.observation_paths),
            "search": self.search.to_mapping(),
            "output_root": self.output_root,
        }


@dataclass(frozen=True, slots=True)
class ObservationSourceRecord:
    """Digest and identity metadata for one selected observation source."""

    observation_path: str
    observation_id: str
    byte_length: int
    sha256: str

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "source"
    ) -> ObservationSourceRecord:
        data = _mapping(raw, context)
        _strict(data, {"observation_path", "observation_id", "byte_length", "sha256"}, context)
        return cls(
            observation_path=_path_string(data["observation_path"], f"{context}.observation_path"),
            observation_id=_identifier(data["observation_id"], f"{context}.observation_id"),
            byte_length=_positive_int(data["byte_length"], f"{context}.byte_length"),
            sha256=_digest(data["sha256"], f"{context}.sha256"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "observation_path": self.observation_path,
            "observation_id": self.observation_id,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class LoadedObservation:
    """One parsed observation together with its unchanged source bytes and path metadata."""

    observation_path: str
    resolved_path: Path
    observation_bytes: bytes
    observation: TableObservation
    source_record: ObservationSourceRecord

    @property
    def observation_id(self) -> str:
        """Return the parsed observation identity."""

        return self.observation.observation_id


@dataclass(frozen=True, slots=True)
class RoundReconstructionInputBundle:
    """The validated round input and the source records used to assemble it."""

    request: RoundReconstructionRunRequest
    request_path: Path
    observations: tuple[LoadedObservation, ...]
    reconstruction_input: ReconstructionInput

    @property
    def source_records(self) -> tuple[ObservationSourceRecord, ...]:
        """Return source records in the request's original order."""

        return tuple(item.source_record for item in self.observations)

    @property
    def input(self) -> ReconstructionInput:
        """Return the assembled reconstruction input."""

        return self.reconstruction_input


@dataclass(frozen=True, slots=True)
class RoundReconstructionArtifacts:
    """Published files and result for one round-reconstruction run."""

    directory: Path
    input_path: Path
    result_path: Path
    result: RoundReconstructionRunResult


def _observation_entry(
    entry: LoadedObservation | TableObservation,
    index: int,
) -> tuple[TableObservation, str]:
    if isinstance(entry, LoadedObservation):
        return entry.observation, entry.observation_path
    if isinstance(entry, TableObservation):
        return entry, f"observations[{index}]"
    raise TypeError("observation entries must be LoadedObservation or TableObservation values.")


def validate_observation_group(
    observations: Sequence[LoadedObservation | TableObservation],
) -> tuple[TableObservation, ...]:
    """Validate identity, session, and order invariants without sorting observations."""

    entries = tuple(observations)
    if not entries:
        raise RoundReconstructionContractError("observations must contain at least one entry.")

    parsed: list[TableObservation] = []
    first_by_id: dict[str, int] = {}
    first_session_id: str | None = None
    first_session_position: int | None = None
    for index, entry in enumerate(entries):
        observation, path = _observation_entry(entry, index)
        parsed.append(observation)
        previous_index = first_by_id.get(observation.observation_id)
        if previous_index is not None:
            raise RoundReconstructionContractError(
                "duplicate observation_id at positions "
                f"{previous_index} and {index}: {observation.observation_id!r} "
                f"({path!r})."
            )
        first_by_id[observation.observation_id] = index

        session_id = observation.session.session_id
        if first_session_id is None:
            first_session_id = session_id
            first_session_position = index
        elif session_id != first_session_id:
            raise RoundReconstructionContractError(
                "mixed session IDs at positions "
                f"{first_session_position} and {index}: "
                f"{first_session_id!r} and {session_id!r}."
            )

    for index in range(1, len(parsed)):
        previous = parsed[index - 1]
        current = parsed[index]
        previous_sequence = previous.session.event_sequence
        current_sequence = current.session.event_sequence
        if current_sequence <= previous_sequence:
            raise RoundReconstructionContractError(
                "invalid session.event_sequence order at positions "
                f"{index - 1} and {index}: "
                f"{previous_sequence} then {current_sequence}; values must be strictly increasing."
            )
        previous_time = previous.observed_at_ms
        current_time = current.observed_at_ms
        if current_time < previous_time:
            raise RoundReconstructionContractError(
                "invalid observed_at_ms order at positions "
                f"{index - 1} and {index}: "
                f"{previous_time} then {current_time}; values must be nondecreasing."
            )
    return tuple(parsed)


def resolve_observation_paths(
    request: RoundReconstructionRunRequest,
    request_path: str | Path,
) -> tuple[Path, ...]:
    """Resolve request observation paths relative to the request file's parent directory."""

    request_file = Path(request_path).expanduser().resolve()
    base_directory = request_file.parent
    return tuple(
        path if (path := Path(observation_path)).is_absolute() else base_directory / path
        for observation_path in request.observation_paths
    )


def load_round_reconstruction_observations(
    request: RoundReconstructionRunRequest,
    request_path: str | Path,
) -> tuple[LoadedObservation, ...]:
    """Read, digest, and parse each requested table observation in request order."""

    resolved_paths = resolve_observation_paths(request, request_path)
    loaded: list[LoadedObservation] = []
    for index, (observation_path, resolved_path) in enumerate(
        zip(request.observation_paths, resolved_paths, strict=True)
    ):
        try:
            observation_bytes = resolved_path.read_bytes()
        except OSError as error:
            raise RoundReconstructionContractError(
                f"could not read observation_paths[{index}] {observation_path!r}: {resolved_path}"
            ) from error
        try:
            observation = parse_observation_bytes(observation_bytes)
        except GameEngineContractError as error:
            raise RoundReconstructionContractError(
                f"observation_paths[{index}] {observation_path!r} failed table-observation/v1 "
                "validation."
            ) from error
        loaded.append(
            LoadedObservation(
                observation_path=observation_path,
                resolved_path=resolved_path,
                observation_bytes=observation_bytes,
                observation=observation,
                source_record=ObservationSourceRecord(
                    observation_path=observation_path,
                    observation_id=observation.observation_id,
                    byte_length=len(observation_bytes),
                    sha256=sha256_bytes(observation_bytes),
                ),
            )
        )
    validate_observation_group(loaded)
    return tuple(loaded)


def assemble_round_reconstruction_input(
    request: RoundReconstructionRunRequest,
    observations: Sequence[LoadedObservation | TableObservation],
) -> ReconstructionInput:
    """Build and validate one game-engine round input from ordered observations."""

    parsed_observations = validate_observation_group(observations)
    setup = request.round_setup
    payload = {
        "schema_version": RECONSTRUCTION_INPUT_SCHEMA_VERSION,
        "game_id": setup.game_id,
        "round_id": setup.round_id,
        "ruleset": setup.ruleset.to_mapping(),
        "deck_variant": setup.deck_variant,
        "active_players": list(setup.active_players),
        "dealer": setup.dealer,
        "first_trick_leader": setup.first_trick_leader,
        "observations": list(parsed_observations),
    }
    try:
        return ReconstructionInput.model_validate(payload)
    except ValueError as error:
        raise RoundReconstructionContractError(
            "assembled round-reconstruction-input/v1 failed validation."
        ) from error


def load_round_reconstruction_input_bundle(
    request: RoundReconstructionRunRequest,
    request_path: str | Path,
) -> RoundReconstructionInputBundle:
    """Load observations and assemble the validated game-engine round input."""

    loaded = load_round_reconstruction_observations(request, request_path)
    return RoundReconstructionInputBundle(
        request=request,
        request_path=Path(request_path),
        observations=loaded,
        reconstruction_input=assemble_round_reconstruction_input(request, loaded),
    )


def load_round_reconstruction_input(
    request: RoundReconstructionRunRequest,
    request_path: str | Path,
) -> ReconstructionInput:
    """Load and assemble the game-engine round input selected by a run request."""

    return load_round_reconstruction_input_bundle(request, request_path).reconstruction_input


@dataclass(frozen=True, slots=True)
class CardPlayRecord:
    """One serialized engine card play."""

    player: str
    card: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> CardPlayRecord:
        data = _mapping(raw, context)
        _strict(data, {"player", "card"}, context)
        return cls(
            player=_identifier(data["player"], f"{context}.player"),
            card=_card(data["card"], f"{context}.card"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {"player": self.player, "card": self.card}


@dataclass(frozen=True, slots=True)
class TrickResultRecord:
    """One serialized complete trick from an engine hypothesis."""

    index: int
    leader: str
    plays: tuple[CardPlayRecord, ...]
    winner: str
    winning_card: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> TrickResultRecord:
        data = _mapping(raw, context)
        _strict(data, {"index", "leader", "plays", "winner", "winning_card"}, context)
        raw_plays = data["plays"]
        if not isinstance(raw_plays, list) or len(raw_plays) != 4:
            raise RoundReconstructionContractError(f"{context}.plays must contain four plays.")
        return cls(
            index=_positive_int(data["index"], f"{context}.index"),
            leader=_identifier(data["leader"], f"{context}.leader"),
            plays=tuple(
                CardPlayRecord.from_mapping(play, f"{context}.plays[{index}]")
                for index, play in enumerate(raw_plays)
            ),
            winner=_identifier(data["winner"], f"{context}.winner"),
            winning_card=_card(data["winning_card"], f"{context}.winning_card"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "leader": self.leader,
            "plays": [play.to_mapping() for play in self.plays],
            "winner": self.winner,
            "winning_card": self.winning_card,
        }


@dataclass(frozen=True, slots=True)
class GameplayResultRecord:
    """Serialized gameplay represented by one reconstruction hypothesis."""

    plays: tuple[CardPlayRecord, ...]
    tricks: tuple[TrickResultRecord, ...]
    initial_hands: Mapping[str, tuple[str, ...]]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> GameplayResultRecord:
        data = _mapping(raw, context)
        _strict(data, {"plays", "tricks", "initial_hands"}, context)
        raw_plays = data["plays"]
        if not isinstance(raw_plays, list):
            raise RoundReconstructionContractError(f"{context}.plays must be a list.")
        raw_tricks = data["tricks"]
        if not isinstance(raw_tricks, list):
            raise RoundReconstructionContractError(f"{context}.tricks must be a list.")
        raw_hands = _mapping(data["initial_hands"], f"{context}.initial_hands")
        hands: dict[str, tuple[str, ...]] = {}
        for player, cards in raw_hands.items():
            player_id = _identifier(player, f"{context}.initial_hands key")
            if not isinstance(cards, list):
                raise RoundReconstructionContractError(
                    f"{context}.initial_hands.{player_id} must be a list."
                )
            hands[player_id] = tuple(
                _card(card, f"{context}.initial_hands.{player_id}[{index}]")
                for index, card in enumerate(cards)
            )
        return cls(
            plays=tuple(
                CardPlayRecord.from_mapping(play, f"{context}.plays[{index}]")
                for index, play in enumerate(raw_plays)
            ),
            tricks=tuple(
                TrickResultRecord.from_mapping(trick, f"{context}.tricks[{index}]")
                for index, trick in enumerate(raw_tricks)
            ),
            initial_hands=hands,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "plays": [play.to_mapping() for play in self.plays],
            "tricks": [trick.to_mapping() for trick in self.tricks],
            "initial_hands": {player: list(cards) for player, cards in self.initial_hands.items()},
        }


@dataclass(frozen=True, slots=True)
class VisualEvidenceScoreRecord:
    """Serialized visual evidence contributions in a hypothesis score."""

    presence: float
    newly_visible: float
    predecessor: float
    active_area: float
    tracklet: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> VisualEvidenceScoreRecord:
        data = _mapping(raw, context)
        _strict(
            data,
            {"presence", "newly_visible", "predecessor", "active_area", "tracklet"},
            context,
        )
        return cls(
            presence=_finite_number(data["presence"], f"{context}.presence"),
            newly_visible=_finite_number(data["newly_visible"], f"{context}.newly_visible"),
            predecessor=_finite_number(data["predecessor"], f"{context}.predecessor"),
            active_area=_finite_number(data["active_area"], f"{context}.active_area"),
            tracklet=_finite_number(data["tracklet"], f"{context}.tracklet"),
        )

    def to_mapping(self) -> dict[str, float]:
        return {
            "presence": self.presence,
            "newly_visible": self.newly_visible,
            "predecessor": self.predecessor,
            "active_area": self.active_area,
            "tracklet": self.tracklet,
        }


@dataclass(frozen=True, slots=True)
class ScoreBreakdownRecord:
    """Serialized score inputs used to rank one reconstruction hypothesis."""

    identity_candidate_log_score: float
    ignored_observed_card_count: int
    inferred_missing_play_count: int
    visual_evidence_score: VisualEvidenceScoreRecord

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> ScoreBreakdownRecord:
        data = _mapping(raw, context)
        _strict(
            data,
            {
                "identity_candidate_log_score",
                "ignored_observed_card_count",
                "inferred_missing_play_count",
                "visual_evidence_score",
            },
            context,
        )
        return cls(
            identity_candidate_log_score=_finite_number(
                data["identity_candidate_log_score"],
                f"{context}.identity_candidate_log_score",
            ),
            ignored_observed_card_count=_non_negative_int(
                data["ignored_observed_card_count"],
                f"{context}.ignored_observed_card_count",
            ),
            inferred_missing_play_count=_non_negative_int(
                data["inferred_missing_play_count"],
                f"{context}.inferred_missing_play_count",
            ),
            visual_evidence_score=VisualEvidenceScoreRecord.from_mapping(
                data["visual_evidence_score"], f"{context}.visual_evidence_score"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "identity_candidate_log_score": self.identity_candidate_log_score,
            "ignored_observed_card_count": self.ignored_observed_card_count,
            "inferred_missing_play_count": self.inferred_missing_play_count,
            "visual_evidence_score": self.visual_evidence_score.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class ReconstructionHypothesisRecord:
    """Serialized legal gameplay result and its source explanation."""

    gameplay: GameplayResultRecord
    source_observation_ids: tuple[str, ...]
    source_observed_card_ids: tuple[str, ...]
    ignored_observed_card_ids: tuple[str, ...]
    missing_play_indices: tuple[int, ...]
    score_breakdown: ScoreBreakdownRecord

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> ReconstructionHypothesisRecord:
        data = _mapping(raw, context)
        _strict(
            data,
            {
                "gameplay",
                "source_observation_ids",
                "source_observed_card_ids",
                "ignored_observed_card_ids",
                "missing_play_indices",
                "score_breakdown",
            },
            context,
        )
        missing = data["missing_play_indices"]
        if not isinstance(missing, list):
            raise RoundReconstructionContractError(
                f"{context}.missing_play_indices must be a list."
            )
        indices = tuple(
            _positive_int(value, f"{context}.missing_play_indices[{index}]")
            for index, value in enumerate(missing)
        )
        if indices != tuple(sorted(set(indices))):
            raise RoundReconstructionContractError(
                f"{context}.missing_play_indices must be unique and ordered."
            )
        return cls(
            gameplay=GameplayResultRecord.from_mapping(data["gameplay"], f"{context}.gameplay"),
            source_observation_ids=_unique(
                _string_list(
                    data["source_observation_ids"],
                    f"{context}.source_observation_ids",
                    identifiers=True,
                ),
                f"{context}.source_observation_ids",
            ),
            source_observed_card_ids=_unique(
                _string_list(
                    data["source_observed_card_ids"],
                    f"{context}.source_observed_card_ids",
                    identifiers=True,
                ),
                f"{context}.source_observed_card_ids",
            ),
            ignored_observed_card_ids=_unique(
                _string_list(
                    data["ignored_observed_card_ids"],
                    f"{context}.ignored_observed_card_ids",
                    identifiers=True,
                ),
                f"{context}.ignored_observed_card_ids",
            ),
            missing_play_indices=indices,
            score_breakdown=ScoreBreakdownRecord.from_mapping(
                data["score_breakdown"], f"{context}.score_breakdown"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "gameplay": self.gameplay.to_mapping(),
            "source_observation_ids": list(self.source_observation_ids),
            "source_observed_card_ids": list(self.source_observed_card_ids),
            "ignored_observed_card_ids": list(self.ignored_observed_card_ids),
            "missing_play_indices": list(self.missing_play_indices),
            "score_breakdown": self.score_breakdown.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class FocusedDecisionRecord:
    """Serialized smallest gameplay difference between retained hypotheses."""

    kind: Literal["card_play"]
    play_index: int
    player: str
    alternatives: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    description: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> FocusedDecisionRecord:
        data = _mapping(raw, context)
        _strict(
            data,
            {
                "kind",
                "play_index",
                "player",
                "alternatives",
                "source_observation_ids",
                "description",
            },
            context,
        )
        if data["kind"] != "card_play":
            raise RoundReconstructionContractError(f"{context}.kind must be card_play.")
        alternatives = _string_list(data["alternatives"], f"{context}.alternatives")
        if len(alternatives) < 2 or len(set(alternatives)) != len(alternatives):
            raise RoundReconstructionContractError(
                f"{context}.alternatives must contain at least two unique values."
            )
        return cls(
            kind="card_play",
            play_index=_positive_int(data["play_index"], f"{context}.play_index"),
            player=_identifier(data["player"], f"{context}.player"),
            alternatives=alternatives,
            source_observation_ids=_unique(
                _string_list(
                    data["source_observation_ids"],
                    f"{context}.source_observation_ids",
                    identifiers=True,
                ),
                f"{context}.source_observation_ids",
            ),
            description=_text(data["description"], f"{context}.description"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "play_index": self.play_index,
            "player": self.player,
            "alternatives": list(self.alternatives),
            "source_observation_ids": list(self.source_observation_ids),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class ReconstructionDiagnosticsRecord:
    """Serialized search and evidence diagnostics from the reconstruction engine."""

    ruleset: str
    deck_variant: Literal["doko-40-v1"]
    capabilities: tuple[str, ...]
    calibration_states: tuple[str, ...]
    observations_seen: int
    card_proposals_seen: int
    search_nodes: int
    complete_branches: int
    merged_branches: int
    rejected_branches: tuple[str, ...]
    ignored_observations: tuple[str, ...]
    incomplete_observations: tuple[str, ...]
    search_limits: Mapping[str, int]
    truncated: bool
    evidence_families: tuple[str, ...]
    ablated_evidence: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "diagnostics"
    ) -> ReconstructionDiagnosticsRecord:
        data = _mapping(raw, context)
        fields = {
            "ruleset",
            "deck_variant",
            "capabilities",
            "calibration_states",
            "observations_seen",
            "card_proposals_seen",
            "search_nodes",
            "complete_branches",
            "merged_branches",
            "rejected_branches",
            "ignored_observations",
            "incomplete_observations",
            "search_limits",
            "truncated",
            "evidence_families",
            "ablated_evidence",
        }
        _strict(data, fields, context)
        if data["ruleset"] != "doko-normal/v1":
            raise RoundReconstructionContractError(f"{context}.ruleset must be doko-normal/v1.")
        if data["deck_variant"] != "doko-40-v1":
            raise RoundReconstructionContractError(f"{context}.deck_variant must be doko-40-v1.")
        capabilities = _string_list(data["capabilities"], f"{context}.capabilities")
        if any(value not in CAPABILITIES for value in capabilities):
            raise RoundReconstructionContractError(
                f"{context}.capabilities contains an unknown value."
            )
        _unique(capabilities, f"{context}.capabilities")
        calibration_states = _string_list(
            data["calibration_states"], f"{context}.calibration_states"
        )
        if any(value not in CALIBRATION_STATES for value in calibration_states):
            raise RoundReconstructionContractError(
                f"{context}.calibration_states contains an unknown value."
            )
        _unique(calibration_states, f"{context}.calibration_states")
        evidence_families = _string_list(data["evidence_families"], f"{context}.evidence_families")
        if any(value not in EVIDENCE_FAMILIES for value in evidence_families):
            raise RoundReconstructionContractError(
                f"{context}.evidence_families contains an unknown value."
            )
        _unique(evidence_families, f"{context}.evidence_families")
        ablated_evidence = _string_list(data["ablated_evidence"], f"{context}.ablated_evidence")
        if any(value not in EVIDENCE_FAMILIES for value in ablated_evidence):
            raise RoundReconstructionContractError(
                f"{context}.ablated_evidence contains an unknown value."
            )
        _unique(ablated_evidence, f"{context}.ablated_evidence")
        raw_limits = _mapping(data["search_limits"], f"{context}.search_limits")
        _strict(
            raw_limits,
            {
                "max_missing_plays",
                "effective_missing_play_budget",
                "missing_play_slots",
                "max_hypotheses",
                "max_search_nodes",
            },
            f"{context}.search_limits",
        )
        missing_slots = raw_limits["missing_play_slots"]
        if (
            isinstance(missing_slots, bool)
            or not isinstance(missing_slots, int)
            or missing_slots < -1
        ):
            raise RoundReconstructionContractError(
                f"{context}.search_limits.missing_play_slots must be -1 or non-negative."
            )
        search_limits = {
            "max_missing_plays": _non_negative_int(
                raw_limits["max_missing_plays"], f"{context}.search_limits.max_missing_plays"
            ),
            "effective_missing_play_budget": _non_negative_int(
                raw_limits["effective_missing_play_budget"],
                f"{context}.search_limits.effective_missing_play_budget",
            ),
            "missing_play_slots": missing_slots,
            "max_hypotheses": _positive_int(
                raw_limits["max_hypotheses"], f"{context}.search_limits.max_hypotheses"
            ),
            "max_search_nodes": _positive_int(
                raw_limits["max_search_nodes"], f"{context}.search_limits.max_search_nodes"
            ),
        }
        return cls(
            ruleset="doko-normal/v1",
            deck_variant="doko-40-v1",
            capabilities=capabilities,
            calibration_states=calibration_states,
            observations_seen=_non_negative_int(
                data["observations_seen"], f"{context}.observations_seen"
            ),
            card_proposals_seen=_non_negative_int(
                data["card_proposals_seen"], f"{context}.card_proposals_seen"
            ),
            search_nodes=_non_negative_int(data["search_nodes"], f"{context}.search_nodes"),
            complete_branches=_non_negative_int(
                data["complete_branches"], f"{context}.complete_branches"
            ),
            merged_branches=_non_negative_int(
                data["merged_branches"], f"{context}.merged_branches"
            ),
            rejected_branches=_string_list(
                data["rejected_branches"], f"{context}.rejected_branches"
            ),
            ignored_observations=_unique(
                _string_list(
                    data["ignored_observations"],
                    f"{context}.ignored_observations",
                    identifiers=True,
                ),
                f"{context}.ignored_observations",
            ),
            incomplete_observations=_unique(
                _string_list(
                    data["incomplete_observations"],
                    f"{context}.incomplete_observations",
                    identifiers=True,
                ),
                f"{context}.incomplete_observations",
            ),
            search_limits=search_limits,
            truncated=_boolean(data["truncated"], f"{context}.truncated"),
            evidence_families=evidence_families,
            ablated_evidence=ablated_evidence,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ruleset": self.ruleset,
            "deck_variant": self.deck_variant,
            "capabilities": list(self.capabilities),
            "calibration_states": list(self.calibration_states),
            "observations_seen": self.observations_seen,
            "card_proposals_seen": self.card_proposals_seen,
            "search_nodes": self.search_nodes,
            "complete_branches": self.complete_branches,
            "merged_branches": self.merged_branches,
            "rejected_branches": list(self.rejected_branches),
            "ignored_observations": list(self.ignored_observations),
            "incomplete_observations": list(self.incomplete_observations),
            "search_limits": dict(self.search_limits),
            "truncated": self.truncated,
            "evidence_families": list(self.evidence_families),
            "ablated_evidence": list(self.ablated_evidence),
        }


@dataclass(frozen=True, slots=True)
class RoundReconstructionRunResult:
    """Strict deterministic result artifact for one reconstruction run."""

    run_id: str
    operations_version: str
    request_sha256: str
    sources: tuple[ObservationSourceRecord, ...]
    search: SearchLimits
    status: Literal["resolved", "ambiguous", "incomplete", "impossible"]
    hypotheses: tuple[ReconstructionHypothesisRecord, ...]
    focused_decisions: tuple[FocusedDecisionRecord, ...]
    diagnostics: ReconstructionDiagnosticsRecord

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RoundReconstructionRunResult:
        data = _mapping(raw, "round-reconstruction-result")
        _strict(
            data,
            {
                "schema_version",
                "run_id",
                "operations_version",
                "request_sha256",
                "sources",
                "search",
                "status",
                "hypotheses",
                "focused_decisions",
                "diagnostics",
            },
            "round-reconstruction-result",
        )
        if data["schema_version"] != ROUND_RECONSTRUCTION_RESULT_SCHEMA_VERSION:
            raise RoundReconstructionContractError(
                "unsupported round-reconstruction-result schema version."
            )
        raw_sources = data["sources"]
        if not isinstance(raw_sources, list) or not raw_sources:
            raise RoundReconstructionContractError("sources must contain at least one record.")
        raw_hypotheses = data["hypotheses"]
        if not isinstance(raw_hypotheses, list):
            raise RoundReconstructionContractError("hypotheses must be a list.")
        raw_decisions = data["focused_decisions"]
        if not isinstance(raw_decisions, list):
            raise RoundReconstructionContractError("focused_decisions must be a list.")
        status = data["status"]
        if status not in RECONSTRUCTION_STATUSES:
            raise RoundReconstructionContractError(
                "status must be resolved, ambiguous, incomplete, or impossible."
            )
        sources = tuple(
            ObservationSourceRecord.from_mapping(source, f"sources[{index}]")
            for index, source in enumerate(raw_sources)
        )
        _unique(
            tuple(source.observation_id for source in sources),
            "sources.observation_id",
        )
        _unique(
            tuple(source.observation_path for source in sources),
            "sources.observation_path",
        )
        search = SearchLimits.from_mapping(data["search"])
        diagnostics = ReconstructionDiagnosticsRecord.from_mapping(data["diagnostics"])
        for field in ("max_missing_plays", "max_hypotheses", "max_search_nodes"):
            if diagnostics.search_limits[field] != getattr(search, field):
                raise RoundReconstructionContractError(
                    f"diagnostics.search_limits.{field} must match search.{field}."
                )
        return cls(
            run_id=_identifier(data["run_id"], "run_id"),
            operations_version=_text(data["operations_version"], "operations_version"),
            request_sha256=_digest(data["request_sha256"], "request_sha256"),
            sources=sources,
            search=search,
            status=status,
            hypotheses=tuple(
                ReconstructionHypothesisRecord.from_mapping(hypothesis, f"hypotheses[{index}]")
                for index, hypothesis in enumerate(raw_hypotheses)
            ),
            focused_decisions=tuple(
                FocusedDecisionRecord.from_mapping(decision, f"focused_decisions[{index}]")
                for index, decision in enumerate(raw_decisions)
            ),
            diagnostics=diagnostics,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": ROUND_RECONSTRUCTION_RESULT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "operations_version": self.operations_version,
            "request_sha256": self.request_sha256,
            "sources": [source.to_mapping() for source in self.sources],
            "search": self.search.to_mapping(),
            "status": self.status,
            "hypotheses": [hypothesis.to_mapping() for hypothesis in self.hypotheses],
            "focused_decisions": [decision.to_mapping() for decision in self.focused_decisions],
            "diagnostics": self.diagnostics.to_mapping(),
        }


def _result_source_records(
    request: RoundReconstructionRunRequest,
    source_records: Sequence[ObservationSourceRecord] | RoundReconstructionInputBundle,
) -> tuple[ObservationSourceRecord, ...]:
    if isinstance(source_records, RoundReconstructionInputBundle):
        if source_records.request != request:
            raise RoundReconstructionContractError(
                "input bundle request must match the request used for result serialization."
            )
        records = source_records.source_records
    else:
        if isinstance(source_records, (str, bytes)):
            raise TypeError("source_records must be a sequence of source records.")
        try:
            records = tuple(source_records)
        except TypeError as error:
            raise TypeError("source_records must be a sequence of source records.") from error

    if len(records) != len(request.observation_paths):
        raise RoundReconstructionContractError(
            "source_records must contain one record for each observation_paths entry."
        )

    validated: list[ObservationSourceRecord] = []
    for index, (request_path, source) in enumerate(
        zip(request.observation_paths, records, strict=True)
    ):
        if not isinstance(source, ObservationSourceRecord):
            raise TypeError("source_records must contain ObservationSourceRecord values.")
        record = ObservationSourceRecord.from_mapping(source.to_mapping(), f"sources[{index}]")
        if record.observation_path != request_path:
            raise RoundReconstructionContractError(
                f"sources[{index}].observation_path must match observation_paths[{index}]: "
                f"{record.observation_path!r} != {request_path!r}."
            )
        validated.append(record)
    _unique(tuple(record.observation_id for record in validated), "sources.observation_id")
    _unique(tuple(record.observation_path for record in validated), "sources.observation_path")
    return tuple(validated)


def _serialize_engine_gameplay(gameplay: Any) -> GameplayResultRecord:
    return GameplayResultRecord(
        plays=tuple(
            CardPlayRecord(player=play.player, card=play.card) for play in gameplay.plays
        ),
        tricks=tuple(
            TrickResultRecord(
                index=trick.index,
                leader=trick.leader,
                plays=tuple(
                    CardPlayRecord(player=play.player, card=play.card)
                    for play in trick.plays
                ),
                winner=trick.winner,
                winning_card=trick.winning_card,
            )
            for trick in gameplay.tricks
        ),
        initial_hands={
            player: tuple(cards) for player, cards in gameplay.initial_hands.items()
        },
    )


def _serialize_engine_hypothesis(hypothesis: Any) -> ReconstructionHypothesisRecord:
    score = hypothesis.score_breakdown
    visual = score.visual_evidence_score
    return ReconstructionHypothesisRecord(
        gameplay=_serialize_engine_gameplay(hypothesis.gameplay),
        source_observation_ids=tuple(hypothesis.source_observation_ids),
        source_observed_card_ids=tuple(hypothesis.source_observed_card_ids),
        ignored_observed_card_ids=tuple(hypothesis.ignored_observed_card_ids),
        missing_play_indices=tuple(hypothesis.missing_play_indices),
        score_breakdown=ScoreBreakdownRecord(
            identity_candidate_log_score=score.identity_candidate_log_score,
            ignored_observed_card_count=score.ignored_observed_card_count,
            inferred_missing_play_count=score.inferred_missing_play_count,
            visual_evidence_score=VisualEvidenceScoreRecord(
                presence=visual.presence,
                newly_visible=visual.newly_visible,
                predecessor=visual.predecessor,
                active_area=visual.active_area,
                tracklet=visual.tracklet,
            ),
        ),
    )


def _serialize_engine_diagnostics(diagnostics: Any) -> ReconstructionDiagnosticsRecord:
    return ReconstructionDiagnosticsRecord(
        ruleset=diagnostics.ruleset,
        deck_variant=diagnostics.deck_variant,
        capabilities=tuple(diagnostics.capabilities),
        calibration_states=tuple(diagnostics.calibration_states),
        observations_seen=diagnostics.observations_seen,
        card_proposals_seen=diagnostics.card_proposals_seen,
        search_nodes=diagnostics.search_nodes,
        complete_branches=diagnostics.complete_branches,
        merged_branches=diagnostics.merged_branches,
        rejected_branches=tuple(diagnostics.rejected_branches),
        ignored_observations=tuple(diagnostics.ignored_observations),
        incomplete_observations=tuple(diagnostics.incomplete_observations),
        search_limits=dict(diagnostics.search_limits),
        truncated=diagnostics.truncated,
        evidence_families=tuple(diagnostics.evidence_families),
        ablated_evidence=tuple(diagnostics.ablated_evidence),
    )


def build_round_reconstruction_result(
    request: RoundReconstructionRunRequest,
    source_records: Sequence[ObservationSourceRecord] | RoundReconstructionInputBundle,
    engine_result: EngineReconstructionResult,
) -> RoundReconstructionRunResult:
    """Build and validate the operations result from one engine result."""

    if not isinstance(request, RoundReconstructionRunRequest):
        raise TypeError("request must be a RoundReconstructionRunRequest.")
    if not isinstance(engine_result, EngineReconstructionResult):
        raise TypeError("engine_result must be a game-engine ReconstructionResult.")

    result = RoundReconstructionRunResult(
        run_id=request.run_id,
        operations_version=OPERATIONS_PACKAGE_VERSION,
        request_sha256=canonical_request_sha256(request),
        sources=_result_source_records(request, source_records),
        search=request.search,
        status=engine_result.status,
        hypotheses=tuple(
            _serialize_engine_hypothesis(hypothesis) for hypothesis in engine_result.hypotheses
        ),
        focused_decisions=tuple(
            FocusedDecisionRecord(
                kind=decision.kind,
                play_index=decision.play_index,
                player=decision.player,
                alternatives=tuple(decision.alternatives),
                source_observation_ids=tuple(decision.source_observation_ids),
                description=decision.description,
            )
            for decision in engine_result.focused_decisions
        ),
        diagnostics=_serialize_engine_diagnostics(engine_result.diagnostics),
    )
    try:
        return validate_round_reconstruction_result(result.to_mapping())
    except RoundReconstructionContractError as error:
        raise RoundReconstructionContractError(
            f"engine reconstruction result failed operations serialization: {error}"
        ) from error


def serialize_engine_result(
    request: RoundReconstructionRunRequest,
    source_records: Sequence[ObservationSourceRecord] | RoundReconstructionInputBundle,
    engine_result: EngineReconstructionResult,
) -> bytes:
    """Return canonical result bytes for one validated engine result."""

    return canonical_result_bytes(
        build_round_reconstruction_result(request, source_records, engine_result)
    )


serialize_round_reconstruction_result = serialize_engine_result


def resolve_round_reconstruction_output_directory(
    request: RoundReconstructionRunRequest,
    request_path: str | Path,
) -> Path:
    """Resolve the request's output root relative to the request file."""

    request_file = Path(request_path).expanduser().resolve()
    output_root = Path(request.output_root).expanduser()
    if not output_root.is_absolute():
        output_root = request_file.parent / output_root
    return output_root.resolve()


def publish_round_reconstruction_artifacts(
    output_root: str | Path,
    run_id: str,
    input_bytes: bytes,
    result_bytes: bytes,
) -> Path:
    """Publish canonical input and result files as one immutable run directory."""

    if not isinstance(input_bytes, bytes) or not isinstance(result_bytes, bytes):
        raise TypeError("artifact contents must be bytes.")
    run_identifier = _identifier(run_id, "run_id")
    root = Path(output_root).expanduser().resolve()
    destination = root / run_identifier
    if destination.exists() or destination.is_symlink():
        raise RoundReconstructionPublicationError(
            f"round-reconstruction artifact directory already exists: {destination}"
        )

    staging: Path | None = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise RoundReconstructionPublicationError(
                f"round-reconstruction artifact directory already exists: {destination}"
            )
        staging = Path(tempfile.mkdtemp(prefix=f".{run_identifier}-", dir=root))
        (staging / "input.json").write_bytes(input_bytes)
        (staging / "result.json").write_bytes(result_bytes)
        if (staging / "input.json").read_bytes() != input_bytes:
            raise OSError("published input bytes failed verification")
        if (staging / "result.json").read_bytes() != result_bytes:
            raise OSError("published result bytes failed verification")
        os.rename(staging, destination)
        staging = None
    except RoundReconstructionPublicationError:
        raise
    except OSError as error:
        raise RoundReconstructionPublicationError(
            f"could not publish round-reconstruction artifacts: {destination}"
        ) from error
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    return destination


def _local_deck_manifest_path() -> Path:
    """Find the checked-in deck manifest without using the current working directory."""

    module_path = Path(__file__).resolve()
    for directory in (module_path.parent, *module_path.parents):
        candidate = directory / "fixtures" / "game-engine" / "v1" / "decks" / "doko-40-v1.json"
        if candidate.is_file():
            return candidate
    raise RoundReconstructionContractError(
        "could not locate the checked-in doko-40-v1 deck manifest."
    )


def run_round_reconstruction(request_path: str | Path) -> RoundReconstructionArtifacts:
    """Run one local round reconstruction and atomically publish its artifacts."""

    request_file = Path(request_path).expanduser().resolve()
    request = load_round_reconstruction_request(request_file)
    bundle = load_round_reconstruction_input_bundle(request, request_file)
    try:
        engine_result = reconstruct_round(
            bundle.reconstruction_input,
            ruleset=DokoNormalRuleset(
                load_deck_manifest("doko-40-v1", path=_local_deck_manifest_path())
            ),
            max_missing_plays=request.search.max_missing_plays,
            max_hypotheses=request.search.max_hypotheses,
            max_search_nodes=request.search.max_search_nodes,
        )
    except ValueError as error:
        raise RoundReconstructionContractError(
            f"round reconstruction failed validation: {error}"
        ) from error

    input_bytes = canonical_engine_json_bytes(bundle.reconstruction_input)
    result = build_round_reconstruction_result(request, bundle, engine_result)
    result_bytes = canonical_result_bytes(result)
    directory = publish_round_reconstruction_artifacts(
        resolve_round_reconstruction_output_directory(request, request_file),
        request.run_id,
        input_bytes,
        result_bytes,
    )
    return RoundReconstructionArtifacts(
        directory=directory,
        input_path=directory / "input.json",
        result_path=directory / "result.json",
        result=result,
    )


def validate_round_reconstruction_request(
    payload: Mapping[str, Any],
) -> RoundReconstructionRunRequest:
    """Validate one decoded round-reconstruction-run/v1 object."""

    return RoundReconstructionRunRequest.from_mapping(payload)


def validate_round_reconstruction_result(
    payload: Mapping[str, Any],
) -> RoundReconstructionRunResult:
    """Validate one decoded round-reconstruction-result/v1 object."""

    return RoundReconstructionRunResult.from_mapping(payload)


def _parse_bytes(raw: bytes, context: str, validator):
    if not isinstance(raw, bytes):
        raise TypeError("contract bytes must be bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RoundReconstructionContractError(f"{context} must be UTF-8 JSON.") from error
    return validator(_mapping(value, context))


def parse_round_reconstruction_request_bytes(raw: bytes) -> RoundReconstructionRunRequest:
    """Parse one UTF-8 round-reconstruction-run/v1 document."""

    return _parse_bytes(raw, "round-reconstruction-run", validate_round_reconstruction_request)


def parse_round_reconstruction_result_bytes(raw: bytes) -> RoundReconstructionRunResult:
    """Parse one UTF-8 round-reconstruction-result/v1 document."""

    return _parse_bytes(raw, "round-reconstruction-result", validate_round_reconstruction_result)


def load_round_reconstruction_request(path: str | Path) -> RoundReconstructionRunRequest:
    """Load and validate one request file."""

    request_path = Path(path)
    try:
        return parse_round_reconstruction_request_bytes(request_path.read_bytes())
    except OSError as error:
        raise RoundReconstructionContractError(
            f"could not read round-reconstruction-run: {request_path}"
        ) from error


def load_round_reconstruction_result(path: str | Path) -> RoundReconstructionRunResult:
    """Load and validate one result artifact."""

    result_path = Path(path)
    try:
        return parse_round_reconstruction_result_bytes(result_path.read_bytes())
    except OSError as error:
        raise RoundReconstructionContractError(
            f"could not read round-reconstruction-result: {result_path}"
        ) from error


def canonical_json_bytes(
    model: RoundReconstructionRunRequest | RoundReconstructionRunResult,
) -> bytes:
    """Serialize a validated run contract as deterministic compact UTF-8 JSON bytes."""

    if not isinstance(model, (RoundReconstructionRunRequest, RoundReconstructionRunResult)):
        raise TypeError("model must be a round reconstruction request or result.")
    value = _finite_json(model.to_mapping(), "contract")
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_request_bytes(request: RoundReconstructionRunRequest) -> bytes:
    """Serialize a request using its canonical representation."""

    return canonical_json_bytes(request)


def canonical_result_bytes(result: RoundReconstructionRunResult) -> bytes:
    """Serialize a result using its canonical representation."""

    return canonical_json_bytes(result)


def canonical_request_sha256(request: RoundReconstructionRunRequest) -> str:
    """Return the SHA-256 digest of a request's canonical JSON bytes."""

    return hashlib.sha256(canonical_request_bytes(request)).hexdigest()


# Short aliases keep the contract API convenient for the later command implementation.
RoundReconstructionRequest = RoundReconstructionRunRequest
RoundReconstructionResult = RoundReconstructionRunResult
SourceRecord = ObservationSourceRecord
SourceObservationRecord = ObservationSourceRecord
parse_run_request_bytes = parse_round_reconstruction_request_bytes
parse_run_result_bytes = parse_round_reconstruction_result_bytes
validate_run_request = validate_round_reconstruction_request
validate_run_result = validate_round_reconstruction_result


__all__ = [
    "CAPABILITIES",
    "CALIBRATION_STATES",
    "CardPlayRecord",
    "EVIDENCE_FAMILIES",
    "FocusedDecisionRecord",
    "GameplayResultRecord",
    "LoadedObservation",
    "OPERATIONS_PACKAGE_VERSION",
    "ObservationSourceRecord",
    "RECONSTRUCTION_STATUSES",
    "ROUND_RECONSTRUCTION_RESULT_SCHEMA_VERSION",
    "ROUND_RECONSTRUCTION_RUN_SCHEMA_VERSION",
    "ReconstructionDiagnosticsRecord",
    "ReconstructionHypothesisRecord",
    "RoundReconstructionContractError",
    "RoundReconstructionArtifacts",
    "RoundReconstructionInputBundle",
    "RoundReconstructionPublicationError",
    "RoundReconstructionRequest",
    "RoundReconstructionResult",
    "RoundReconstructionRunRequest",
    "RoundReconstructionRunResult",
    "RoundRuleset",
    "RoundSetup",
    "ScoreBreakdownRecord",
    "SearchLimits",
    "SourceRecord",
    "SourceObservationRecord",
    "TrickResultRecord",
    "VisualEvidenceScoreRecord",
    "build_round_reconstruction_result",
    "canonical_json_bytes",
    "canonical_request_bytes",
    "canonical_request_sha256",
    "canonical_result_bytes",
    "assemble_round_reconstruction_input",
    "load_round_reconstruction_request",
    "load_round_reconstruction_result",
    "load_round_reconstruction_input",
    "load_round_reconstruction_input_bundle",
    "load_round_reconstruction_observations",
    "parse_round_reconstruction_request_bytes",
    "parse_round_reconstruction_result_bytes",
    "publish_round_reconstruction_artifacts",
    "parse_run_request_bytes",
    "parse_run_result_bytes",
    "resolve_round_reconstruction_output_directory",
    "run_round_reconstruction",
    "sha256_bytes",
    "serialize_engine_result",
    "serialize_round_reconstruction_result",
    "validate_round_reconstruction_request",
    "validate_round_reconstruction_result",
    "validate_observation_group",
    "validate_run_request",
    "validate_run_result",
]
