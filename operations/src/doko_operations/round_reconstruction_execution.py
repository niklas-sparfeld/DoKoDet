"""Round-reconstruction input loading, execution, and artifact publication."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_engine import (
    RECONSTRUCTION_INPUT_SCHEMA_VERSION,
    DokoNormalRuleset,
    IgnoredAction,
    InferredAction,
    ReconstructionInput,
    SelectedAction,
    TableObservation,
    load_deck_manifest,
    parse_observation_bytes,
    reconstruct_round,
)
from game_engine import ContractError as GameEngineContractError
from game_engine import ReconstructionResult as EngineReconstructionResult
from game_engine import canonical_json_bytes as canonical_engine_json_bytes

from doko_operations.round_reconstruction_contract import (
    OPERATIONS_PACKAGE_VERSION,
    CardPlayRecord,
    FocusedDecisionRecord,
    GameplayResultRecord,
    IgnoredActionRecord,
    InferredActionRecord,
    ObservationSourceRecord,
    ReconstructionActionRecord,
    ReconstructionDiagnosticsRecord,
    ReconstructionHypothesisRecord,
    RoundReconstructionContractError,
    RoundReconstructionRunRequest,
    RoundReconstructionRunResult,
    ScoreBreakdownRecord,
    SelectedActionRecord,
    TrickResultRecord,
    VisualEvidenceScoreRecord,
    _identifier,
    _unique,
    canonical_request_sha256,
    canonical_result_bytes,
    load_round_reconstruction_request,
    sha256_bytes,
    validate_round_reconstruction_result,
)


class RoundReconstructionPublicationError(RoundReconstructionContractError):
    """Raised when a round-reconstruction artifact run cannot be published."""


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

    return load_round_reconstruction_observations_from_paths(
        request,
        resolve_observation_paths(request, request_path),
    )


def load_round_reconstruction_observations_from_paths(
    request: RoundReconstructionRunRequest,
    source_paths: Sequence[str | Path],
) -> tuple[LoadedObservation, ...]:
    """Read and validate observations from explicit paths in request order."""

    if not isinstance(request, RoundReconstructionRunRequest):
        raise TypeError("request must be a RoundReconstructionRunRequest.")
    if isinstance(source_paths, (str, bytes)):
        raise TypeError("source_paths must be a sequence of paths.")
    try:
        explicit_paths = tuple(Path(path).expanduser().resolve() for path in source_paths)
    except (TypeError, ValueError) as error:
        raise TypeError("source_paths must contain path values.") from error
    if len(explicit_paths) != len(request.observation_paths):
        raise RoundReconstructionContractError(
            "source_paths must contain one path for each observation_paths entry."
        )

    loaded: list[LoadedObservation] = []
    for index, (observation_path, resolved_path) in enumerate(
        zip(request.observation_paths, explicit_paths, strict=True)
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
        plays=tuple(CardPlayRecord(player=play.player, card=play.card) for play in gameplay.plays),
        tricks=tuple(
            TrickResultRecord(
                index=trick.index,
                leader=trick.leader,
                plays=tuple(
                    CardPlayRecord(player=play.player, card=play.card) for play in trick.plays
                ),
                winner=trick.winner,
                winning_card=trick.winning_card,
            )
            for trick in gameplay.tricks
        ),
        initial_hands={player: tuple(cards) for player, cards in gameplay.initial_hands.items()},
    )


def _serialize_engine_action(action: Any) -> ReconstructionActionRecord:
    if isinstance(action, SelectedAction):
        visual = action.visual_evidence_score
        return SelectedActionRecord(
            kind="selected",
            observation_id=action.observation_id,
            observed_card_id=action.observed_card_id,
            play_index=action.play_index,
            player=action.player,
            card=action.card,
            candidate_probability=action.candidate_probability,
            identity_log_score_contribution=action.identity_log_score_contribution,
            visual_evidence_score=VisualEvidenceScoreRecord(
                presence=visual.presence,
                newly_visible=visual.newly_visible,
                predecessor=visual.predecessor,
                active_area=visual.active_area,
                tracklet=visual.tracklet,
            ),
            score_contribution=action.score_contribution,
        )
    if isinstance(action, IgnoredAction):
        visual = action.visual_evidence_score
        return IgnoredActionRecord(
            kind="ignored",
            observation_id=action.observation_id,
            observed_card_id=action.observed_card_id,
            ignore_penalty=action.ignore_penalty,
            visual_evidence_score=VisualEvidenceScoreRecord(
                presence=visual.presence,
                newly_visible=visual.newly_visible,
                predecessor=visual.predecessor,
                active_area=visual.active_area,
                tracklet=visual.tracklet,
            ),
            score_contribution=action.score_contribution,
        )
    if isinstance(action, InferredAction):
        return InferredActionRecord(
            kind="inferred",
            play_index=action.play_index,
            player=action.player,
            card=action.card,
            missing_play_penalty=action.missing_play_penalty,
            score_contribution=action.score_contribution,
        )
    raise TypeError("actions must contain game-engine reconstruction action values.")


def _serialize_engine_hypothesis(hypothesis: Any) -> ReconstructionHypothesisRecord:
    score = hypothesis.score_breakdown
    visual = score.visual_evidence_score
    return ReconstructionHypothesisRecord(
        gameplay=_serialize_engine_gameplay(hypothesis.gameplay),
        source_observation_ids=tuple(hypothesis.source_observation_ids),
        source_observed_card_ids=tuple(hypothesis.source_observed_card_ids),
        ignored_observed_card_ids=tuple(hypothesis.ignored_observed_card_ids),
        missing_play_indices=tuple(hypothesis.missing_play_indices),
        actions=tuple(_serialize_engine_action(action) for action in hypothesis.actions),
        total_score=hypothesis.total_score,
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
    """Load a request file and run one local round reconstruction."""

    request_file = Path(request_path).expanduser().resolve()
    request = load_round_reconstruction_request(request_file)
    return run_round_reconstruction_values(
        request,
        resolve_observation_paths(request, request_file),
        resolve_round_reconstruction_output_directory(request, request_file),
    )


def run_round_reconstruction_values(
    request: RoundReconstructionRunRequest,
    source_paths: Sequence[str | Path],
    output_root: str | Path,
    *,
    deck_manifest_path: str | Path | None = None,
) -> RoundReconstructionArtifacts:
    """Run reconstruction from validated values and explicit source and output paths.

    The request keeps the stable source labels and search values used in canonical artifacts.
    ``source_paths`` identifies the corresponding files on the local filesystem. This split lets
    the backend call the same orchestration without creating a command request file.
    """

    if not isinstance(request, RoundReconstructionRunRequest):
        raise TypeError("request must be a RoundReconstructionRunRequest.")
    loaded = load_round_reconstruction_observations_from_paths(request, source_paths)
    reconstruction_input = assemble_round_reconstruction_input(request, loaded)
    result = reconstruct_round_reconstruction_input(
        request,
        reconstruction_input,
        tuple(item.source_record for item in loaded),
        deck_manifest_path=deck_manifest_path,
    )
    input_bytes = canonical_engine_json_bytes(reconstruction_input)
    result_bytes = canonical_result_bytes(result)
    directory = publish_round_reconstruction_artifacts(
        output_root,
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


def reconstruct_round_reconstruction_input(
    request: RoundReconstructionRunRequest,
    reconstruction_input: ReconstructionInput,
    source_records: Sequence[ObservationSourceRecord],
    *,
    deck_manifest_path: str | Path | None = None,
) -> RoundReconstructionRunResult:
    """Reconstruct one already-materialized input without publishing artifacts."""

    if not isinstance(request, RoundReconstructionRunRequest):
        raise TypeError("request must be a RoundReconstructionRunRequest.")
    if not isinstance(reconstruction_input, ReconstructionInput):
        raise TypeError("reconstruction_input must be a ReconstructionInput.")
    if isinstance(source_records, (str, bytes)):
        raise TypeError("source_records must be a sequence of source records.")
    records = tuple(source_records)
    if len(records) != len(reconstruction_input.observations):
        raise RoundReconstructionContractError(
            "source_records must contain one record for each reconstruction input observation."
        )
    if tuple(record.observation_id for record in records) != tuple(
        observation.observation_id for observation in reconstruction_input.observations
    ):
        raise RoundReconstructionContractError(
            "source_records must use the reconstruction input observation order."
        )
    manifest_path = (
        _local_deck_manifest_path()
        if deck_manifest_path is None
        else Path(deck_manifest_path).expanduser().resolve()
    )
    try:
        engine_result = reconstruct_round(
            reconstruction_input,
            ruleset=DokoNormalRuleset(
                load_deck_manifest(reconstruction_input.deck_variant, path=manifest_path)
            ),
            max_missing_plays=request.search.max_missing_plays,
            max_hypotheses=request.search.max_hypotheses,
            max_search_nodes=request.search.max_search_nodes,
        )
    except ValueError as error:
        raise RoundReconstructionContractError(
            f"round reconstruction failed validation: {error}"
        ) from error
    return build_round_reconstruction_result(request, records, engine_result)


__all__ = [
    "LoadedObservation",
    "RoundReconstructionArtifacts",
    "RoundReconstructionInputBundle",
    "RoundReconstructionPublicationError",
    "assemble_round_reconstruction_input",
    "build_round_reconstruction_result",
    "load_round_reconstruction_input",
    "load_round_reconstruction_input_bundle",
    "load_round_reconstruction_observations",
    "load_round_reconstruction_observations_from_paths",
    "publish_round_reconstruction_artifacts",
    "reconstruct_round_reconstruction_input",
    "resolve_observation_paths",
    "resolve_round_reconstruction_output_directory",
    "run_round_reconstruction",
    "run_round_reconstruction_values",
    "serialize_engine_result",
    "serialize_round_reconstruction_result",
    "sha256_bytes",
    "validate_observation_group",
]
