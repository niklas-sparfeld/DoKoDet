from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from uuid import UUID

import pytest
from game_engine import (
    CardPlay,
    FocusedDecision,
    GameplayResult,
    IgnoredAction,
    InferredAction,
    ReconstructionDiagnostics,
    ReconstructionHypothesis,
    ReconstructionResult,
    ScoreBreakdown,
    SelectedAction,
    TrickResult,
    VisualEvidenceScore,
    canonical_json_bytes,
    load_round_scenario,
    parse_observation_bytes,
    parse_reconstruction_input_bytes,
)

from doko_operations.cli import main
from doko_operations.counterfactual import (
    ROUND_COUNTERFACTUAL_SCHEMA_VERSION,
    RoundCounterfactualRequest,
    canonical_counterfactual_bytes,
    canonical_counterfactual_sha256,
    derive_counterfactual_input,
    parse_round_counterfactual_request_bytes,
    recompute_counterfactual,
)
from doko_operations.round_reconstruction import (
    ObservationSourceRecord,
    RoundReconstructionContractError,
    RoundReconstructionPublicationError,
    build_round_reconstruction_result,
    canonical_request_bytes,
    canonical_request_sha256,
    canonical_result_bytes,
    load_round_reconstruction_input_bundle,
    load_round_reconstruction_observations,
    parse_round_reconstruction_request_bytes,
    parse_round_reconstruction_result_bytes,
    run_round_reconstruction,
    run_round_reconstruction_values,
    serialize_engine_result,
    sha256_bytes,
)

GAME_ENGINE_SCENARIO_ROOT = Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1" / "rounds"


def request_payload() -> dict[str, object]:
    return {
        "schema_version": "round-reconstruction-run/v1",
        "run_id": "example-round-01",
        "round_setup": {
            "game_id": "game-01",
            "round_id": "game-01-round-01",
            "ruleset": {"name": "doko-normal", "version": "v1"},
            "deck_variant": "doko-40-v1",
            "active_players": [
                "player-01",
                "player-02",
                "player-03",
                "player-04",
            ],
            "dealer": "dealer-01",
            "first_trick_leader": "player-01",
        },
        "observation_paths": [
            "observations/observation-001.json",
            "observations/observation-002.json",
        ],
        "search": {
            "max_missing_plays": 1,
            "max_hypotheses": 256,
            "max_search_nodes": 250000,
        },
        "output_root": "artifacts/round-reconstruction",
    }


def diagnostics_payload() -> dict[str, object]:
    return {
        "ruleset": "doko-normal/v1",
        "deck_variant": "doko-40-v1",
        "capabilities": ["identity_candidates"],
        "calibration_states": ["fixture"],
        "observations_seen": 2,
        "card_proposals_seen": 2,
        "search_nodes": 3,
        "complete_branches": 0,
        "merged_branches": 0,
        "rejected_branches": ["replay rejected branch (x1)"],
        "ignored_observations": [],
        "incomplete_observations": [],
        "search_limits": {
            "max_missing_plays": 1,
            "effective_missing_play_budget": 1,
            "missing_play_slots": -1,
            "max_hypotheses": 256,
            "max_search_nodes": 250000,
        },
        "truncated": False,
        "evidence_families": [],
        "ablated_evidence": [],
    }


def result_payload() -> dict[str, object]:
    return {
        "schema_version": "round-reconstruction-result/v2",
        "run_id": "example-round-01",
        "operations_version": "0.1.0",
        "request_sha256": "0" * 64,
        "sources": [
            {
                "observation_path": "observations/observation-001.json",
                "observation_id": "observation-001",
                "byte_length": 42,
                "sha256": "1" * 64,
            }
        ],
        "search": {
            "max_missing_plays": 1,
            "max_hypotheses": 256,
            "max_search_nodes": 250000,
        },
        "status": "incomplete",
        "hypotheses": [],
        "focused_decisions": [],
        "diagnostics": diagnostics_payload(),
    }


def engine_result() -> ReconstructionResult:
    plays = (
        CardPlay(player="player-01", card="CLUBS_ACE"),
        CardPlay(player="player-02", card="CLUBS_NINE"),
        CardPlay(player="player-03", card="SPADES_NINE"),
        CardPlay(player="player-04", card="HEARTS_NINE"),
    )
    return ReconstructionResult(
        status="ambiguous",
        hypotheses=(
            ReconstructionHypothesis(
                gameplay=GameplayResult(
                    plays=plays,
                    tricks=(
                        TrickResult(
                            index=1,
                            leader="player-01",
                            plays=plays,
                            winner="player-01",
                            winning_card="CLUBS_ACE",
                        ),
                    ),
                    initial_hands={
                        "player-01": ("CLUBS_ACE",),
                        "player-02": ("CLUBS_NINE",),
                        "player-03": ("SPADES_NINE",),
                        "player-04": ("HEARTS_NINE",),
                    },
                ),
                source_observation_ids=("observation-001",),
                source_observed_card_ids=("observed-card-001",),
                ignored_observed_card_ids=("observed-card-ignored",),
                missing_play_indices=(2,),
                actions=(
                    SelectedAction(
                        kind="selected",
                        observation_id="observation-001",
                        observed_card_id="observed-card-001",
                        play_index=1,
                        player="player-01",
                        card="CLUBS_ACE",
                        candidate_probability=math.exp(-0.25),
                        identity_log_score_contribution=-0.25,
                        visual_evidence_score=VisualEvidenceScore(
                            presence=0.1,
                            newly_visible=0.2,
                            predecessor=0.3,
                            active_area=0.4,
                            tracklet=0.5,
                        ),
                        score_contribution=1.25,
                    ),
                    InferredAction(
                        kind="inferred",
                        play_index=2,
                        player="player-02",
                        card="CLUBS_NINE",
                        missing_play_penalty=-0.75,
                        score_contribution=-0.75,
                    ),
                    SelectedAction(
                        kind="selected",
                        observation_id="observation-002",
                        observed_card_id="observed-card-002",
                        play_index=3,
                        player="player-03",
                        card="SPADES_NINE",
                        candidate_probability=1.0,
                        identity_log_score_contribution=0.0,
                        visual_evidence_score=VisualEvidenceScore(),
                        score_contribution=0.0,
                    ),
                    SelectedAction(
                        kind="selected",
                        observation_id="observation-002",
                        observed_card_id="observed-card-003",
                        play_index=4,
                        player="player-04",
                        card="HEARTS_NINE",
                        candidate_probability=1.0,
                        identity_log_score_contribution=0.0,
                        visual_evidence_score=VisualEvidenceScore(),
                        score_contribution=0.0,
                    ),
                    IgnoredAction(
                        kind="ignored",
                        observation_id="observation-001",
                        observed_card_id="observed-card-ignored",
                        ignore_penalty=-0.35,
                        visual_evidence_score=VisualEvidenceScore(),
                        score_contribution=-0.35,
                    ),
                ),
                score_breakdown=ScoreBreakdown(
                    identity_candidate_log_score=-0.25,
                    ignored_observed_card_count=1,
                    inferred_missing_play_count=1,
                    visual_evidence_score=VisualEvidenceScore(
                        presence=0.1,
                        newly_visible=0.2,
                        predecessor=0.3,
                        active_area=0.4,
                        tracklet=0.5,
                    ),
                ),
            ),
        ),
        focused_decisions=(
            FocusedDecision(
                kind="card_play",
                play_index=2,
                player="player-02",
                alternatives=("player-02:CLUBS_NINE", "player-02:SPADES_NINE"),
                source_observation_ids=("observation-001", "observation-002"),
                description="card play 2 has retained legal alternatives",
            ),
        ),
        diagnostics=ReconstructionDiagnostics(
            ruleset="doko-normal/v1",
            deck_variant="doko-40-v1",
            capabilities=("identity_candidates", "presence_score"),
            calibration_states=("fixture",),
            observations_seen=2,
            card_proposals_seen=4,
            search_nodes=7,
            complete_branches=2,
            merged_branches=1,
            rejected_branches=("replay rejected branch (x1)",),
            ignored_observations=(),
            incomplete_observations=(),
            search_limits={
                "max_missing_plays": 1,
                "effective_missing_play_budget": 1,
                "missing_play_slots": -1,
                "max_hypotheses": 256,
                "max_search_nodes": 250000,
            },
            truncated=False,
            evidence_families=("presence",),
            ablated_evidence=(),
        ),
    )


def observation_payload(
    observation_id: str,
    event_sequence: int,
    observed_at_ms: int,
    *,
    session_id: str = "session-01",
) -> dict[str, object]:
    return {
        "schema_version": "table-observation/v1",
        "observation_id": observation_id,
        "source": {"package_id": "package-01"},
        "session": {"session_id": session_id, "event_sequence": event_sequence},
        "observed_at_ms": observed_at_ms,
        "status": "insufficient_evidence",
        "capabilities": ["identity_candidates"],
        "cards": [],
        "calibration": "fixture",
        "analyzer": {"name": "fixture-analyzer", "version": "1.0"},
        "diagnostics": {},
    }


def write_observation_request(
    tmp_path,
    payloads: list[dict[str, object]],
) -> tuple[object, object, list[bytes]]:
    request_directory = tmp_path / "request-directory"
    observation_directory = request_directory / "observations"
    observation_directory.mkdir(parents=True)
    observation_paths = []
    observation_bytes = []
    for index, payload in enumerate(payloads, start=1):
        path = observation_directory / f"observation-{index:03d}.json"
        source = json.dumps(payload, indent=2).encode("utf-8")
        path.write_bytes(source)
        observation_paths.append(f"observations/{path.name}")
        observation_bytes.append(source)

    request_payload_value = request_payload()
    request_payload_value["observation_paths"] = observation_paths
    request = parse_round_reconstruction_request_bytes(
        json.dumps(request_payload_value).encode("utf-8")
    )
    request_path = request_directory / "request.json"
    request_path.write_bytes(json.dumps(request_payload_value).encode("utf-8"))
    return request, request_path, observation_bytes


def write_scenario_request(
    tmp_path: Path,
    scenario_name: str,
    *,
    insufficient_evidence: bool = False,
) -> Path:
    """Adapt one game-engine scenario into separate harness observation files."""

    scenario = load_round_scenario(GAME_ENGINE_SCENARIO_ROOT / f"{scenario_name}.json")
    scenario_directory = tmp_path / scenario_name
    observation_directory = scenario_directory / "observations"
    observation_directory.mkdir(parents=True)
    observations = list(scenario.input.observations)
    if insufficient_evidence:
        observations[0] = observations[0].model_copy(
            update={"cards": [], "status": "insufficient_evidence"}
        )

    observation_paths: list[str] = []
    for index, observation in enumerate(observations, start=1):
        observation_path = observation_directory / f"observation-{index:03d}.json"
        observation_path.write_bytes(canonical_json_bytes(observation))
        observation_paths.append(f"observations/{observation_path.name}")

    input_value = scenario.input
    request_payload = {
        "schema_version": "round-reconstruction-run/v1",
        "run_id": f"{scenario_name}-harness",
        "round_setup": {
            "game_id": input_value.game_id,
            "round_id": input_value.round_id,
            "ruleset": input_value.ruleset.model_dump(mode="json"),
            "deck_variant": input_value.deck_variant,
            "active_players": list(input_value.active_players),
            "dealer": input_value.dealer,
            "first_trick_leader": input_value.first_trick_leader,
        },
        "observation_paths": observation_paths,
        "search": {
            "max_missing_plays": 1,
            "max_hypotheses": 256,
            "max_search_nodes": 250000,
        },
        "output_root": "artifacts",
    }
    request_path = scenario_directory / "request.json"
    request_path.write_text(json.dumps(request_payload, indent=2), encoding="utf-8")
    return request_path


def test_request_is_strict_and_canonical() -> None:
    payload = request_payload()
    parsed = parse_round_reconstruction_request_bytes(json.dumps(payload, indent=2).encode("utf-8"))

    assert parsed.round_setup.dealer == "dealer-01"
    assert parsed.round_setup.ruleset.name == "doko-normal"
    assert parsed.observation_paths == (
        "observations/observation-001.json",
        "observations/observation-002.json",
    )
    assert canonical_request_bytes(parsed) == canonical_request_bytes(
        parse_round_reconstruction_request_bytes(json.dumps(payload, sort_keys=True).encode())
    )
    assert canonical_request_bytes(parsed).startswith(b'{"observation_paths":')
    assert canonical_request_sha256(parsed) == canonical_request_sha256(
        parse_round_reconstruction_request_bytes(json.dumps(payload).encode())
    )


def _counterfactual_request_payload(
    input_value,
    result,
    *,
    excluded_observation_ids: list[str] | None = None,
    excluded_observed_cards: list[dict[str, str]] | None = None,
    candidate_probability_overrides: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": ROUND_COUNTERFACTUAL_SCHEMA_VERSION,
        "counterfactual_id": "22222222-2222-4222-8222-222222222222",
        "source_analysis_id": result.run_id,
        "source_input_sha256": sha256_bytes(canonical_json_bytes(input_value)),
        "source_result_sha256": sha256_bytes(canonical_result_bytes(result)),
        "excluded_observation_ids": excluded_observation_ids or [],
        "excluded_observed_cards": excluded_observed_cards or [],
        "candidate_probability_overrides": candidate_probability_overrides or [],
    }


def _counterfactual_source(tmp_path: Path):
    request_path = write_scenario_request(tmp_path, "ambiguous")
    request_payload_value = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload_value["run_id"] = "11111111-1111-4111-8111-111111111111"
    request_path.write_text(json.dumps(request_payload_value), encoding="utf-8")
    artifacts = run_round_reconstruction(request_path)
    input_value = parse_reconstruction_input_bytes(artifacts.input_path.read_bytes())
    result = parse_round_reconstruction_result_bytes(artifacts.result_path.read_bytes())
    return artifacts, input_value, result


def test_counterfactual_request_is_strict_canonical_and_uuid_based() -> None:
    payload = {
        "schema_version": ROUND_COUNTERFACTUAL_SCHEMA_VERSION,
        "counterfactual_id": "22222222-2222-4222-8222-222222222222",
        "source_analysis_id": "11111111-1111-4111-8111-111111111111",
        "source_input_sha256": "1" * 64,
        "source_result_sha256": "2" * 64,
        "excluded_observation_ids": ["observation-001"],
        "excluded_observed_cards": [
            {"observation_id": "observation-002", "observed_card_id": "card-01"}
        ],
        "candidate_probability_overrides": [
            {
                "observation_id": "observation-003",
                "observed_card_id": "card-02",
                "card": "CLUBS_ACE",
                "probability": 0.75,
            }
        ],
    }
    parsed = parse_round_counterfactual_request_bytes(json.dumps(payload, indent=2).encode())

    assert parsed.counterfactual_id == UUID("22222222-2222-4222-8222-222222222222")
    assert canonical_counterfactual_bytes(parsed) == canonical_counterfactual_bytes(
        parse_round_counterfactual_request_bytes(canonical_counterfactual_bytes(parsed))
    )
    assert canonical_counterfactual_sha256(parsed) == sha256_bytes(
        canonical_counterfactual_bytes(parsed)
    )

    unknown = copy.deepcopy(payload)
    unknown["unexpected"] = True
    with pytest.raises(RoundReconstructionContractError, match="invalid fields"):
        parse_round_counterfactual_request_bytes(json.dumps(unknown).encode())

    empty = copy.deepcopy(payload)
    empty["excluded_observation_ids"] = []
    empty["excluded_observed_cards"] = []
    empty["candidate_probability_overrides"] = []
    with pytest.raises(RoundReconstructionContractError, match="at least one change"):
        parse_round_counterfactual_request_bytes(json.dumps(empty).encode())


def test_counterfactual_derivation_excludes_an_observation_without_mutating_source(
    tmp_path: Path,
) -> None:
    artifacts, input_value, result = _counterfactual_source(tmp_path)
    source_input_bytes = artifacts.input_path.read_bytes()
    source_result_bytes = artifacts.result_path.read_bytes()
    source_observations = {
        path: path.read_bytes() for path in (tmp_path / "ambiguous" / "observations").glob("*.json")
    }
    request = RoundCounterfactualRequest.from_mapping(
        _counterfactual_request_payload(
            input_value,
            result,
            excluded_observation_ids=["observation-001"],
        )
    )

    derived = derive_counterfactual_input(request, input_value)

    assert [item.observation_id for item in derived.observations] == [
        item.observation_id for item in input_value.observations[1:]
    ]
    assert canonical_json_bytes(input_value) == source_input_bytes
    assert artifacts.result_path.read_bytes() == source_result_bytes
    assert {
        path: path.read_bytes() for path in (tmp_path / "ambiguous" / "observations").glob("*.json")
    } == source_observations


def test_counterfactual_derivation_excludes_card_and_rescales_existing_candidates(
    tmp_path: Path,
) -> None:
    _, input_value, result = _counterfactual_source(tmp_path)
    source_card = input_value.observations[0].cards[0]
    request = RoundCounterfactualRequest.from_mapping(
        _counterfactual_request_payload(
            input_value,
            result,
            excluded_observed_cards=[
                {
                    "observation_id": input_value.observations[1].observation_id,
                    "observed_card_id": input_value.observations[1].cards[0].observed_card_id,
                }
            ],
            candidate_probability_overrides=[
                {
                    "observation_id": input_value.observations[0].observation_id,
                    "observed_card_id": source_card.observed_card_id,
                    "card": source_card.identity_candidates[0].card,
                    "probability": 0.75,
                }
            ],
        )
    )

    derived = derive_counterfactual_input(request, input_value)
    derived_card = derived.observations[0].cards[0]

    assert len(derived.observations[1].cards) == 0
    assert [candidate.probability for candidate in derived_card.identity_candidates] == [
        pytest.approx(0.75),
        pytest.approx(0.25),
    ]
    assert derived_card.identity_candidates[0].card == source_card.identity_candidates[0].card


def test_counterfactual_recomputation_is_deterministic_and_reuses_source_search_limits(
    tmp_path: Path,
) -> None:
    artifacts, input_value, result = _counterfactual_source(tmp_path)
    source_input_bytes = artifacts.input_path.read_bytes()
    source_result_bytes = artifacts.result_path.read_bytes()
    source_observation_bytes = {
        path: path.read_bytes() for path in (tmp_path / "ambiguous" / "observations").glob("*.json")
    }
    source_card = input_value.observations[0].cards[0]
    request = RoundCounterfactualRequest.from_mapping(
        _counterfactual_request_payload(
            input_value,
            result,
            candidate_probability_overrides=[
                {
                    "observation_id": input_value.observations[0].observation_id,
                    "observed_card_id": source_card.observed_card_id,
                    "card": source_card.identity_candidates[0].card,
                    "probability": 0.75,
                }
            ],
        )
    )

    first = recompute_counterfactual(request, input_value, result)
    second = recompute_counterfactual(request, input_value, result)

    assert first.result.run_id == str(request.counterfactual_id)
    assert first.reconstruction_request.search == result.search
    assert first.result.search == result.search
    assert first.input_bytes == second.input_bytes
    assert first.result_bytes == second.result_bytes
    assert artifacts.input_path.read_bytes() == source_input_bytes
    assert artifacts.result_path.read_bytes() == source_result_bytes
    assert {
        path: path.read_bytes() for path in (tmp_path / "ambiguous" / "observations").glob("*.json")
    } == source_observation_bytes


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"excluded_observation_ids": ["missing-observation"]}, "does not occur"),
        (
            {
                "excluded_observation_ids": ["observation-001"],
                "excluded_observed_cards": [
                    {
                        "observation_id": "observation-001",
                        "observed_card_id": "observation-001-card-01",
                    }
                ],
            },
            "cannot belong",
        ),
    ),
)
def test_counterfactual_rejects_invalid_source_references(
    tmp_path: Path,
    change: dict[str, object],
    message: str,
) -> None:
    _, input_value, result = _counterfactual_source(tmp_path)
    payload = _counterfactual_request_payload(input_value, result, **change)
    request = RoundCounterfactualRequest.from_mapping(payload)

    with pytest.raises(RoundReconstructionContractError, match=message):
        recompute_counterfactual(request, input_value, result)


def test_counterfactual_rejects_equal_and_one_candidate_overrides(tmp_path: Path) -> None:
    _, input_value, result = _counterfactual_source(tmp_path)
    source_card = input_value.observations[0].cards[0]
    base = _counterfactual_request_payload(input_value, result)

    equal = copy.deepcopy(base)
    equal["candidate_probability_overrides"] = [
        {
            "observation_id": input_value.observations[0].observation_id,
            "observed_card_id": source_card.observed_card_id,
            "card": source_card.identity_candidates[0].card,
            "probability": source_card.identity_candidates[0].probability,
        }
    ]
    with pytest.raises(RoundReconstructionContractError, match="differ"):
        recompute_counterfactual(
            RoundCounterfactualRequest.from_mapping(equal), input_value, result
        )

    one_candidate = copy.deepcopy(base)
    one_candidate["candidate_probability_overrides"] = [
        {
            "observation_id": input_value.observations[1].observation_id,
            "observed_card_id": input_value.observations[1].cards[0].observed_card_id,
            "card": input_value.observations[1].cards[0].identity_candidates[0].card,
            "probability": 0.75,
        }
    ]
    with pytest.raises(RoundReconstructionContractError, match="one-candidate"):
        recompute_counterfactual(
            RoundCounterfactualRequest.from_mapping(one_candidate), input_value, result
        )


def test_counterfactual_rejects_source_hash_mismatch_and_removing_every_observation(
    tmp_path: Path,
) -> None:
    _, input_value, result = _counterfactual_source(tmp_path)
    base = _counterfactual_request_payload(input_value, result)

    hash_mismatch = copy.deepcopy(base)
    hash_mismatch["source_result_sha256"] = "0" * 64
    hash_request = RoundCounterfactualRequest.from_mapping(
        {
            **hash_mismatch,
            "excluded_observation_ids": ["observation-001"],
        }
    )
    with pytest.raises(RoundReconstructionContractError, match="source_result_sha256"):
        recompute_counterfactual(hash_request, input_value, result)

    all_observations = copy.deepcopy(base)
    all_observations["excluded_observation_ids"] = [
        observation.observation_id for observation in input_value.observations
    ]
    all_request = RoundCounterfactualRequest.from_mapping(all_observations)
    with pytest.raises(RoundReconstructionContractError, match="retain at least one"):
        recompute_counterfactual(all_request, input_value, result)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        ("round_setup", {"unexpected": True}),
        ("search", {"max_missing_plays": 1}),
    ),
)
def test_request_rejects_unknown_or_missing_fields(path: str, value: object) -> None:
    payload = request_payload()
    if path == "round_setup":
        payload[path] = {**payload[path], **value}  # type: ignore[dict-item]
    else:
        payload[path] = value

    with pytest.raises(RoundReconstructionContractError, match="invalid fields"):
        parse_round_reconstruction_request_bytes(json.dumps(payload).encode())


def test_request_rejects_duplicate_paths_and_invalid_search_bounds() -> None:
    duplicate_paths = request_payload()
    duplicate_paths["observation_paths"] = ["same.json", "same.json"]
    with pytest.raises(RoundReconstructionContractError, match="unique"):
        parse_round_reconstruction_request_bytes(json.dumps(duplicate_paths).encode())

    invalid_bounds = request_payload()
    invalid_bounds["search"] = {
        "max_missing_plays": True,
        "max_hypotheses": 0,
        "max_search_nodes": 0,
    }
    with pytest.raises(RoundReconstructionContractError, match="non-negative integer"):
        parse_round_reconstruction_request_bytes(json.dumps(invalid_bounds).encode())


def test_request_rejects_inactive_first_trick_leader() -> None:
    payload = request_payload()
    setup = copy.deepcopy(payload["round_setup"])
    setup["first_trick_leader"] = "dealer-01"
    payload["round_setup"] = setup

    with pytest.raises(RoundReconstructionContractError, match="active player"):
        parse_round_reconstruction_request_bytes(json.dumps(payload).encode())


def test_result_is_strict_canonical_and_finite() -> None:
    payload = result_payload()
    parsed = parse_round_reconstruction_result_bytes(json.dumps(payload, indent=2).encode())

    assert parsed.status == "incomplete"
    assert canonical_result_bytes(parsed) == canonical_result_bytes(
        parse_round_reconstruction_result_bytes(json.dumps(payload, sort_keys=True).encode())
    )
    assert canonical_result_bytes(parsed).startswith(b'{"diagnostics":')

    unknown = copy.deepcopy(payload)
    unknown["diagnostics"]["unexpected"] = True  # type: ignore[index]
    with pytest.raises(RoundReconstructionContractError, match="invalid fields"):
        parse_round_reconstruction_result_bytes(json.dumps(unknown).encode())

    legacy = result_payload()
    legacy["schema_version"] = "round-reconstruction-result/v1"
    with pytest.raises(RoundReconstructionContractError, match="unsupported"):
        parse_round_reconstruction_result_bytes(json.dumps(legacy).encode())

    non_finite = copy.deepcopy(payload)
    non_finite["diagnostics"]["search_nodes"] = float("nan")  # type: ignore[index]
    with pytest.raises(RoundReconstructionContractError, match="non-negative integer"):
        parse_round_reconstruction_result_bytes(json.dumps(non_finite).encode())


def test_result_rejects_unknown_status_and_bad_source_digest() -> None:
    payload = result_payload()
    payload["status"] = "not-a-status"
    with pytest.raises(RoundReconstructionContractError, match="status"):
        parse_round_reconstruction_result_bytes(json.dumps(payload).encode())

    payload = result_payload()
    payload["sources"][0]["sha256"] = "not-a-digest"  # type: ignore[index]
    with pytest.raises(RoundReconstructionContractError, match="SHA-256"):
        parse_round_reconstruction_result_bytes(json.dumps(payload).encode())


def test_result_requires_unique_sources_and_matching_search_limits() -> None:
    payload = result_payload()
    payload["sources"] = [payload["sources"][0], copy.deepcopy(payload["sources"][0])]  # type: ignore[index]
    with pytest.raises(RoundReconstructionContractError, match="observation_id"):
        parse_round_reconstruction_result_bytes(json.dumps(payload).encode())

    payload = result_payload()
    payload["search"]["max_search_nodes"] = 10  # type: ignore[index]
    with pytest.raises(RoundReconstructionContractError, match="must match"):
        parse_round_reconstruction_result_bytes(json.dumps(payload).encode())


def test_engine_result_serialization_preserves_engine_data_and_provenance() -> None:
    request = parse_round_reconstruction_request_bytes(json.dumps(request_payload()).encode())
    sources = (
        ObservationSourceRecord(
            observation_path="observations/observation-001.json",
            observation_id="observation-001",
            byte_length=42,
            sha256="1" * 64,
        ),
        ObservationSourceRecord(
            observation_path="observations/observation-002.json",
            observation_id="observation-002",
            byte_length=43,
            sha256="2" * 64,
        ),
    )

    result = build_round_reconstruction_result(request, sources, engine_result())

    assert result.run_id == request.run_id
    assert result.request_sha256 == canonical_request_sha256(request)
    assert result.status == "ambiguous"
    assert result.sources == sources
    assert result.hypotheses[0].gameplay.tricks[0].winning_card == "CLUBS_ACE"
    assert result.hypotheses[0].score_breakdown.visual_evidence_score.tracklet == 0.5
    assert result.hypotheses[0].total_score == pytest.approx(0.15)
    assert [action.kind for action in result.hypotheses[0].actions] == [
        "selected",
        "inferred",
        "selected",
        "selected",
        "ignored",
    ]
    assert result.focused_decisions[0].alternatives == (
        "player-02:CLUBS_NINE",
        "player-02:SPADES_NINE",
    )
    assert result.diagnostics.search_nodes == 7

    serialized = serialize_engine_result(request, sources, engine_result())
    assert serialized == canonical_result_bytes(result)
    reparsed = parse_round_reconstruction_result_bytes(serialized)
    assert reparsed.to_mapping() == result.to_mapping()

    invalid = result.to_mapping()
    invalid["hypotheses"][0]["total_score"] = 0.16  # type: ignore[index]
    with pytest.raises(RoundReconstructionContractError, match="sum of action contributions"):
        parse_round_reconstruction_result_bytes(json.dumps(invalid).encode())


def test_engine_result_serialization_requires_request_ordered_sources() -> None:
    request = parse_round_reconstruction_request_bytes(json.dumps(request_payload()).encode())
    source = ObservationSourceRecord(
        observation_path="wrong/path.json",
        observation_id="observation-001",
        byte_length=42,
        sha256="1" * 64,
    )

    with pytest.raises(RoundReconstructionContractError, match=r"observation_paths\[0\]"):
        build_round_reconstruction_result(request, (source, source), engine_result())


def test_observation_loader_preserves_request_order_bytes_and_digests(
    tmp_path, monkeypatch
) -> None:
    request, request_path, source_bytes = write_observation_request(
        tmp_path,
        [
            observation_payload("observation-001", 1, 100),
            observation_payload("observation-002", 2, 100),
        ],
    )
    monkeypatch.chdir(tmp_path)

    loaded = load_round_reconstruction_observations(request, request_path)

    assert [item.observation_id for item in loaded] == [
        "observation-001",
        "observation-002",
    ]
    assert [item.observation_bytes for item in loaded] == source_bytes
    assert loaded[0].resolved_path == request_path.parent / "observations/observation-001.json"
    assert loaded[0].source_record.observation_path == "observations/observation-001.json"
    assert loaded[0].source_record.byte_length == len(source_bytes[0])
    assert loaded[0].source_record.sha256 == hashlib.sha256(source_bytes[0]).hexdigest()

    bundle = load_round_reconstruction_input_bundle(request, request_path)
    assert bundle.request == request
    assert bundle.request_path == request_path
    assert bundle.source_records == tuple(item.source_record for item in loaded)
    assert bundle.input.game_id == "game-01"
    assert [item.observation_id for item in bundle.input.observations] == [
        "observation-001",
        "observation-002",
    ]


def test_observation_loader_rejects_duplicate_ids_and_mixed_sessions(tmp_path) -> None:
    duplicate_request, duplicate_path, _ = write_observation_request(
        tmp_path / "duplicate",
        [
            observation_payload("same-observation", 1, 100),
            observation_payload("same-observation", 2, 200),
        ],
    )
    with pytest.raises(RoundReconstructionContractError) as duplicate_error:
        load_round_reconstruction_observations(duplicate_request, duplicate_path)
    assert "positions 0 and 1" in str(duplicate_error.value)
    assert "same-observation" in str(duplicate_error.value)

    mixed_request, mixed_path, _ = write_observation_request(
        tmp_path / "mixed",
        [
            observation_payload("observation-001", 1, 100, session_id="session-a"),
            observation_payload("observation-002", 2, 200, session_id="session-b"),
        ],
    )
    with pytest.raises(RoundReconstructionContractError) as mixed_error:
        load_round_reconstruction_observations(mixed_request, mixed_path)
    assert "positions 0 and 1" in str(mixed_error.value)
    assert "session-a" in str(mixed_error.value)
    assert "session-b" in str(mixed_error.value)


@pytest.mark.parametrize(
    ("first_sequence", "second_sequence", "first_time", "second_time", "message"),
    (
        (2, 2, 100, 200, "session.event_sequence"),
        (1, 2, 200, 100, "observed_at_ms"),
    ),
)
def test_observation_loader_rejects_invalid_order_without_sorting(
    tmp_path,
    first_sequence: int,
    second_sequence: int,
    first_time: int,
    second_time: int,
    message: str,
) -> None:
    request, request_path, _ = write_observation_request(
        tmp_path,
        [
            observation_payload("observation-001", first_sequence, first_time),
            observation_payload("observation-002", second_sequence, second_time),
        ],
    )

    with pytest.raises(RoundReconstructionContractError) as error:
        load_round_reconstruction_observations(request, request_path)

    rendered = str(error.value)
    assert message in rendered
    assert "positions 0 and 1" in rendered
    assert f"{first_sequence if message == 'session.event_sequence' else first_time}" in rendered
    assert f"{second_sequence if message == 'session.event_sequence' else second_time}" in rendered


def test_observation_loader_reports_invalid_source_path_and_contract(tmp_path) -> None:
    request, request_path, _ = write_observation_request(
        tmp_path,
        [observation_payload("observation-001", 1, 100)],
    )
    request_path.unlink()
    request_path.write_text(
        json.dumps(
            {
                **request.to_mapping(),
                "observation_paths": ["observations/missing.json"],
            }
        ),
        encoding="utf-8",
    )
    request = parse_round_reconstruction_request_bytes(request_path.read_bytes())
    with pytest.raises(RoundReconstructionContractError, match="missing.json"):
        load_round_reconstruction_observations(request, request_path)

    invalid_path = tmp_path / "invalid-source.json"
    invalid_path.write_bytes(b"not-json")
    request_payload_value = request_payload()
    request_payload_value["observation_paths"] = [str(invalid_path)]
    invalid_request = parse_round_reconstruction_request_bytes(
        json.dumps(request_payload_value).encode()
    )
    with pytest.raises(RoundReconstructionContractError, match="failed table-observation/v1"):
        load_round_reconstruction_observations(invalid_request, request_path)


def test_round_run_publishes_canonical_artifacts_and_uses_request_relative_paths(
    tmp_path, monkeypatch
) -> None:
    request, request_path, source_bytes = write_observation_request(
        tmp_path,
        [
            observation_payload("observation-001", 1, 100),
            observation_payload("observation-002", 2, 200),
        ],
    )
    monkeypatch.chdir(tmp_path / "request-directory" / "observations")

    artifacts = run_round_reconstruction(request_path)

    expected_directory = request_path.parent / "artifacts/round-reconstruction/example-round-01"
    assert artifacts.directory == expected_directory
    assert artifacts.input_path == expected_directory / "input.json"
    assert artifacts.result_path == expected_directory / "result.json"
    assert artifacts.result.status == "incomplete"
    assert parse_reconstruction_input_bytes(artifacts.input_path.read_bytes()).game_id == "game-01"
    parsed_result = parse_round_reconstruction_result_bytes(artifacts.result_path.read_bytes())
    assert parsed_result.to_mapping() == artifacts.result.to_mapping()
    assert artifacts.result.sources[0].sha256 == hashlib.sha256(source_bytes[0]).hexdigest()


def test_round_run_rejects_existing_target_and_failed_run_leaves_no_final_directory(
    tmp_path,
) -> None:
    request, request_path, _ = write_observation_request(
        tmp_path,
        [observation_payload("observation-001", 1, 100)],
    )
    output_root = request_path.parent / "artifacts/round-reconstruction"
    target = output_root / request.run_id
    target.mkdir(parents=True)
    marker = target / "marker"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(RoundReconstructionPublicationError, match="already exists"):
        run_round_reconstruction(request_path)
    assert marker.read_text(encoding="utf-8") == "keep"

    missing_payload = request.to_mapping()
    missing_payload["run_id"] = "failed-round-01"
    missing_payload["observation_paths"] = ["observations/missing.json"]
    failed_request_path = request_path.parent / "failed-request.json"
    failed_request_path.write_text(json.dumps(missing_payload), encoding="utf-8")
    failed_request = parse_round_reconstruction_request_bytes(failed_request_path.read_bytes())

    with pytest.raises(RoundReconstructionContractError, match="missing.json"):
        run_round_reconstruction(failed_request_path)
    failed_target = failed_request_path.parent / failed_request.output_root / failed_request.run_id
    assert not failed_target.exists()


def test_round_reconstruction_cli_reports_status_and_artifact_directory(tmp_path, capsys) -> None:
    _, request_path, _ = write_observation_request(
        tmp_path,
        [observation_payload("observation-001", 1, 100)],
    )

    assert main(["reconstruct", "round", "--request", str(request_path)]) == 0

    output = capsys.readouterr()
    expected_directory = request_path.parent / "artifacts/round-reconstruction/example-round-01"
    assert f"artifact directory: {expected_directory}" in output.out
    assert "status: incomplete" in output.out
    assert output.err == ""


def test_round_reconstruction_cli_reports_contract_errors(tmp_path, capsys) -> None:
    request_path = tmp_path / "invalid-request.json"
    request_path.write_text("not-json", encoding="utf-8")

    assert main(["reconstruct", "round", "--request", str(request_path)]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "error:" in output.err


def test_value_orchestration_uses_explicit_sources_and_preserves_command_artifacts(
    tmp_path: Path,
) -> None:
    request, request_path, _ = write_observation_request(
        tmp_path,
        [
            observation_payload("observation-001", 1, 100),
            observation_payload("observation-002", 2, 100),
        ],
    )

    command_artifacts = run_round_reconstruction(request_path)
    value_artifacts = run_round_reconstruction_values(
        request,
        [request_path.parent / path for path in request.observation_paths],
        tmp_path / "value-artifacts",
    )

    assert value_artifacts.result.to_mapping() == command_artifacts.result.to_mapping()
    assert value_artifacts.input_path.read_bytes() == command_artifacts.input_path.read_bytes()
    assert value_artifacts.result_path.read_bytes() == command_artifacts.result_path.read_bytes()


@pytest.mark.parametrize(
    ("scenario_name", "expected_status", "insufficient_evidence"),
    (
        ("unambiguous", "resolved", False),
        ("ambiguous", "ambiguous", False),
        ("incomplete", "incomplete", True),
        ("impossible", "impossible", False),
    ),
)
def test_round_harness_adapts_scenario_fixtures_to_all_result_statuses(
    tmp_path: Path,
    scenario_name: str,
    expected_status: str,
    insufficient_evidence: bool,
) -> None:
    request_path = write_scenario_request(
        tmp_path,
        scenario_name,
        insufficient_evidence=insufficient_evidence,
    )

    artifacts = run_round_reconstruction(request_path)

    assert artifacts.result.status == expected_status
    input_value = parse_reconstruction_input_bytes(artifacts.input_path.read_bytes())
    request = parse_round_reconstruction_request_bytes(request_path.read_bytes())
    assert (
        len(input_value.observations)
        == len(artifacts.result.sources)
        == len(request.observation_paths)
    )
    assert all(
        (request_path.parent / observation_path).is_file()
        for observation_path in request.observation_paths
    )
    assert (
        parse_round_reconstruction_result_bytes(artifacts.result_path.read_bytes()).to_mapping()
        == artifacts.result.to_mapping()
    )
    if expected_status == "ambiguous":
        assert artifacts.result.focused_decisions
    if expected_status in {"resolved", "ambiguous"}:
        observed_card_count = sum(
            len(observation.cards) for observation in input_value.observations
        )
        assert artifacts.result.hypotheses
        for hypothesis in artifacts.result.hypotheses:
            assert len(hypothesis.actions) == observed_card_count
            assert sum(action.score_contribution for action in hypothesis.actions) == pytest.approx(
                hypothesis.total_score, abs=1e-9
            )
    if insufficient_evidence:
        first_source = request_path.parent / "observations/observation-001.json"
        assert parse_observation_bytes(first_source.read_bytes()).status == "insufficient_evidence"
        assert artifacts.result.diagnostics.incomplete_observations == ("observation-001",)
