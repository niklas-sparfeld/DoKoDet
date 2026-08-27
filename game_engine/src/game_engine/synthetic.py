"""Seeded legal-round and table-observation generators for reconstruction tests."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from typing import Literal, Protocol

from .cards import CARD_IDENTITIES
from .contract import (
    ANALYZER_CAPABILITIES,
    Capability,
    ReconstructionInput,
    RoundScenario,
    ScenarioExpectation,
    TableObservation,
)
from .replay import RoundReplay, replay_round
from .rules import CardPlay, Ruleset

ObservationStatus = Literal["observed", "insufficient_evidence"]


@dataclass(frozen=True, slots=True)
class PhysicalCard:
    """One private physical copy of a visual card identity."""

    card: str
    copy_index: int

    @property
    def identifier(self) -> str:
        """Return the private physical-card identifier used in synthetic truth."""

        return f"{self.card}-copy-{self.copy_index}"


@dataclass(frozen=True, slots=True)
class SyntheticRound:
    """A legal seeded round and its private physical-card ground truth."""

    seed: int
    active_players: tuple[str, ...]
    dealer: str
    first_trick_leader: str
    physical_hands: Mapping[str, tuple[PhysicalCard, ...]]
    physical_plays: tuple[tuple[CardPlay, PhysicalCard], ...]
    replay: RoundReplay

    @property
    def initial_hands(self) -> dict[str, tuple[str, ...]]:
        """Return the visual identities in each private initial hand."""

        return {
            player: tuple(card.card for card in hand)
            for player, hand in self.physical_hands.items()
        }

    @property
    def card_plays(self) -> tuple[CardPlay, ...]:
        """Return the resolved visual card plays in logical order."""

        return tuple(play for play, _ in self.physical_plays)

    def ground_truth(self) -> dict[str, object]:
        """Return JSON-compatible private truth for a round scenario fixture."""

        trick_by_play = {
            play_index: trick.index
            for trick in self.replay.tricks
            for play_index, _ in enumerate(trick.plays, start=(trick.index - 1) * 4 + 1)
        }
        return {
            "seed": self.seed,
            "active_players": list(self.active_players),
            "dealer": self.dealer,
            "first_trick_leader": self.first_trick_leader,
            "physical_hands": {
                player: [card.identifier for card in hand]
                for player, hand in self.physical_hands.items()
            },
            "card_plays": [
                {
                    "play_index": index,
                    "trick": trick_by_play[index],
                    "player": play.player,
                    "card": play.card,
                    "physical_card": physical_card.identifier,
                }
                for index, (play, physical_card) in enumerate(self.physical_plays, start=1)
            ],
            "trick_winners": [
                {
                    "trick": trick.index,
                    "leader": trick.leader,
                    "winner": trick.winner,
                    "winning_card": trick.winning_card,
                }
                for trick in self.replay.tricks
            ],
        }


@dataclass(frozen=True, slots=True)
class ObservationCardDraft:
    """Internal observation card before contract identifiers are assigned."""

    card: str
    source_play_index: int | None = None
    candidates: tuple[tuple[str, float], ...] | None = None
    presence_score: float | None = None
    newly_visible_score: float | None = None
    active_area_score: float | None = None
    association_source_play_indices: tuple[tuple[int, float], ...] = ()
    tracklet_key: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationDraft:
    """Internal observation state passed between independent error modules."""

    source_play_indices: tuple[int, ...]
    cards: tuple[ObservationCardDraft, ...]
    status: ObservationStatus = "observed"


class ObservationError(Protocol):
    """One deterministic transformation of synthetic observation drafts."""

    name: str

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]: ...


@dataclass(frozen=True, slots=True)
class RepeatObservation:
    """Repeat one observation to model repeated event proposals."""

    observation_index: int
    count: int = 1
    name: str = field(default="repeated_observation", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        if self.count < 1:
            raise ValueError("repeat count must be positive.")
        result = list(observations)
        result[self.observation_index + 1 : self.observation_index + 1] = [
            observations[self.observation_index]
        ] * self.count
        return result


@dataclass(frozen=True, slots=True)
class EmptyObservation:
    """Remove visible cards from one observation while keeping the observation."""

    observation_index: int
    name: str = field(default="empty_observation", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        result = list(observations)
        result[self.observation_index] = replace(result[self.observation_index], cards=())
        return result


@dataclass(frozen=True, slots=True)
class InsufficientEvidenceObservation:
    """Replace one observation with an explicit acquisition failure."""

    observation_index: int
    name: str = field(default="insufficient_evidence", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        result = list(observations)
        result[self.observation_index] = replace(
            result[self.observation_index],
            cards=(),
            status="insufficient_evidence",
        )
        return result


@dataclass(frozen=True, slots=True)
class DropObservations:
    """Drop observations to model missing event proposals or missing card plays."""

    observation_indices: tuple[int, ...]
    name: str = field(default="missing_observation", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        indices = set(self.observation_indices)
        if len(indices) != len(self.observation_indices):
            raise ValueError("observation indices must be unique.")
        for index in indices:
            _require_index(observations, index)
        return [
            observation for index, observation in enumerate(observations) if index not in indices
        ]


@dataclass(frozen=True, slots=True)
class CandidateConfusion:
    """Replace one identity ranking with configured candidates."""

    observation_index: int
    candidates: tuple[str, ...]
    probabilities: tuple[float, ...] | None = None
    card_index: int = 0
    name: str = field(default="ambiguous_identity", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        if not self.candidates or len(set(self.candidates)) != len(self.candidates):
            raise ValueError("candidate identities must be non-empty and unique.")
        if any(card not in CARD_IDENTITIES for card in self.candidates):
            raise ValueError("candidate identities must be in the shared card set.")
        probabilities = self.probabilities or _default_probabilities(len(self.candidates))
        if len(probabilities) != len(self.candidates):
            raise ValueError("candidate probabilities must match candidate identities.")
        if any(probability <= 0.0 for probability in probabilities):
            raise ValueError("candidate probabilities must be positive.")
        total = sum(probabilities)
        normalized = tuple(probability / total for probability in probabilities)
        if tuple(sorted(normalized, reverse=True)) != normalized:
            raise ValueError("candidate probabilities must be in descending order.")
        observation = observations[self.observation_index]
        if not 0 <= self.card_index < len(observation.cards):
            raise ValueError("card index is outside the observation.")
        cards = list(observation.cards)
        cards[self.card_index] = replace(
            cards[self.card_index],
            candidates=tuple(zip(self.candidates, normalized, strict=True)),
        )
        result = list(observations)
        result[self.observation_index] = replace(observation, cards=tuple(cards))
        return result


@dataclass(frozen=True, slots=True)
class FalseCardProposal:
    """Add a card proposal that is not part of the source play."""

    observation_index: int
    card: str
    presence_score: float = 0.1
    name: str = field(default="false_observed_card", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        _validate_score(self.presence_score, "presence_score")
        if self.card not in CARD_IDENTITIES:
            raise ValueError("false card must be in the shared card set.")
        observation = observations[self.observation_index]
        false_card = ObservationCardDraft(
            card=self.card,
            presence_score=self.presence_score,
            newly_visible_score=0.0,
            active_area_score=0.0,
        )
        result = list(observations)
        result[self.observation_index] = replace(
            observation,
            cards=observation.cards + (false_card,),
        )
        return result


@dataclass(frozen=True, slots=True)
class DuplicateDetection:
    """Add a second visual proposal for an already visible card."""

    observation_index: int
    card_index: int = 0
    name: str = field(default="duplicate_detection", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        observation = observations[self.observation_index]
        if not 0 <= self.card_index < len(observation.cards):
            raise ValueError("card index is outside the observation.")
        duplicate = replace(
            observation.cards[self.card_index],
            source_play_index=None,
            presence_score=0.2,
        )
        result = list(observations)
        result[self.observation_index] = replace(
            observation,
            cards=observation.cards + (duplicate,),
        )
        return result


@dataclass(frozen=True, slots=True)
class RetainedSideCard:
    """Add a retained card outside the active table area."""

    observation_index: int
    card: str
    active_area_score: float = 0.0
    name: str = field(default="retained_side_card", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        _validate_score(self.active_area_score, "active_area_score")
        if self.card not in CARD_IDENTITIES:
            raise ValueError("retained card must be in the shared card set.")
        observation = observations[self.observation_index]
        side_card = ObservationCardDraft(
            card=self.card,
            presence_score=1.0,
            newly_visible_score=0.0,
            active_area_score=self.active_area_score,
        )
        result = list(observations)
        result[self.observation_index] = replace(
            observation,
            cards=observation.cards + (side_card,),
        )
        return result


@dataclass(frozen=True, slots=True)
class OldTrickReplay:
    """Show an earlier observation again after later card plays."""

    observation_index: int
    name: str = field(default="old_trick_replay", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        return list(observations) + [observations[self.observation_index]]


@dataclass(frozen=True, slots=True)
class EarlyAppearance:
    """Show a source card before its normal observation position."""

    source_play_index: int
    insert_before_index: int = 0
    name: str = field(default="early_physical_appearance", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        source = self.source_play_index - 1
        _require_index(observations, source)
        if not 0 <= self.insert_before_index <= len(observations):
            raise ValueError("insert position is outside the observation stream.")
        result = list(observations)
        result.insert(self.insert_before_index, observations[source])
        return result


@dataclass(frozen=True, slots=True)
class ClearTrick:
    """Insert an empty observed point when the table is cleared."""

    trick_index: int
    name: str = field(default="trick_clearing", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        if self.trick_index < 1:
            raise ValueError("trick index must be positive.")
        insert_at = self.trick_index * 4
        if insert_at > len(observations):
            raise ValueError("trick index is outside the observation stream.")
        result = list(observations)
        result.insert(insert_at, ObservationDraft(source_play_indices=(), cards=()))
        return result


@dataclass(frozen=True, slots=True)
class ReappearAfterOcclusion:
    """Insert an empty point before a card appears again."""

    observation_index: int
    name: str = field(default="occlusion_reappearance", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        result = list(observations)
        result.insert(
            self.observation_index,
            ObservationDraft(source_play_indices=(), cards=()),
        )
        result.insert(self.observation_index + 2, observations[self.observation_index])
        return result


@dataclass(frozen=True, slots=True)
class MissingIdentityCandidate:
    """Replace a true identity with a candidate list that omits it."""

    observation_index: int
    replacement: str
    card_index: int = 0
    name: str = field(default="missing_identity_candidate", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        _require_index(observations, self.observation_index)
        observation = observations[self.observation_index]
        if not 0 <= self.card_index < len(observation.cards):
            raise ValueError("card index is outside the observation.")
        source_card = observation.cards[self.card_index]
        if self.replacement == source_card.card or self.replacement not in CARD_IDENTITIES:
            raise ValueError("replacement must be a different shared card identity.")
        result = list(observations)
        cards = list(observation.cards)
        cards[self.card_index] = replace(
            source_card,
            candidates=((self.replacement, 1.0),),
        )
        result[self.observation_index] = replace(observation, cards=tuple(cards))
        return result


@dataclass(frozen=True, slots=True)
class CandidateMultiplicityViolation:
    """Put one visual identity above its deck multiplicity in candidates."""

    card: str
    count: int = 3
    name: str = field(default="candidate_multiplicity_violation", init=False)

    def apply(
        self,
        observations: Sequence[ObservationDraft],
        *,
        rng: random.Random,
    ) -> list[ObservationDraft]:
        if self.card not in CARD_IDENTITIES:
            raise ValueError("candidate card must be in the shared card set.")
        if self.count < 1:
            raise ValueError("candidate multiplicity must be positive.")
        eligible = [index for index, observation in enumerate(observations) if observation.cards]
        if self.count > len(eligible):
            raise ValueError("candidate multiplicity exceeds available observations.")
        result = list(observations)
        for index in eligible[: self.count]:
            observation = result[index]
            card = observation.cards[0]
            cards = list(observation.cards)
            cards[0] = replace(card, candidates=((self.card, 1.0),))
            result[index] = replace(observation, cards=tuple(cards))
        return result


@dataclass(frozen=True, slots=True)
class ObservationConfig:
    """Stable metadata and optional evidence families for generated observations."""

    capabilities: tuple[Capability, ...] = ("identity_candidates",)
    package_id: str = "synthetic-package"
    session_id: str = "synthetic-session"
    start_time_ms: int = 1000
    step_ms: int = 1000
    analyzer_name: str = "synthetic"
    analyzer_version: str = "synthetic-v1"
    calibration: Literal["fixture", "uncalibrated", "calibrated"] = "fixture"

    def __post_init__(self) -> None:
        if not self.capabilities:
            raise ValueError("identity_candidates must be enabled.")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("observation capabilities must be unique.")
        if tuple(sorted(self.capabilities, key=ANALYZER_CAPABILITIES.index)) != self.capabilities:
            raise ValueError("observation capabilities must use canonical order.")
        if "identity_candidates" not in self.capabilities:
            raise ValueError("identity_candidates must be enabled.")
        if self.start_time_ms < 0 or self.step_ms < 1:
            raise ValueError("observation times must start at zero and increase.")


def generate_round(
    seed: int,
    *,
    active_players: Sequence[str] = ("player-01", "player-02", "player-03", "player-04"),
    dealer: str = "dealer-01",
    first_trick_leader: str | None = None,
    ruleset: Ruleset | None = None,
) -> SyntheticRound:
    """Generate and replay one legal round from a deterministic seed."""

    selected_ruleset = ruleset or _default_ruleset()
    players = tuple(active_players)
    if len(players) != 4 or len(set(players)) != 4:
        raise ValueError("a synthetic round needs exactly four unique active players.")
    leader = first_trick_leader or players[0]
    if leader not in players:
        raise ValueError("first trick leader must be active.")
    if dealer in players:
        raise ValueError("the synthetic dealer must sit out the round.")

    deck = [
        PhysicalCard(card=card, copy_index=copy_index)
        for card in selected_ruleset.manifest_cards
        for copy_index in range(1, selected_ruleset.card_copy_count(card) + 1)
    ]
    random.Random(seed).shuffle(deck)
    hand_size = selected_ruleset.hand_size
    physical_hands = {
        player: tuple(deck[index * hand_size : (index + 1) * hand_size])
        for index, player in enumerate(players)
    }
    remaining = {player: list(hand) for player, hand in physical_hands.items()}
    rng = random.Random(seed ^ 0x5EED)
    physical_plays: list[tuple[CardPlay, PhysicalCard]] = []
    current_leader = leader
    for _ in range(selected_ruleset.manifest.trick_count):
        trick: list[CardPlay] = []
        for player in selected_ruleset.clockwise_order(players, current_leader):
            legal_cards = selected_ruleset.legal_cards(
                [physical_card.card for physical_card in remaining[player]],
                trick,
            )
            legal_indices = [
                index
                for index, physical_card in enumerate(remaining[player])
                if physical_card.card in legal_cards
            ]
            selected_index = rng.choice(legal_indices)
            physical_card = remaining[player].pop(selected_index)
            play = CardPlay(player=player, card=physical_card.card)
            physical_plays.append((play, physical_card))
            trick.append(play)
        current_leader, _ = selected_ruleset.trick_winner(trick)

    replay = replay_round(
        (play for play, _ in physical_plays),
        active_players=players,
        first_trick_leader=leader,
        initial_hands={
            player: [physical_card.card for physical_card in hand]
            for player, hand in physical_hands.items()
        },
        ruleset=selected_ruleset,
    )
    return SyntheticRound(
        seed=seed,
        active_players=players,
        dealer=dealer,
        first_trick_leader=leader,
        physical_hands=physical_hands,
        physical_plays=tuple(physical_plays),
        replay=replay,
    )


def generate_observations(
    synthetic_round: SyntheticRound,
    *,
    config: ObservationConfig | None = None,
    errors: Sequence[ObservationError] = (),
) -> tuple[TableObservation, ...]:
    """Convert a latent round into deterministic validated table observations."""

    selected_config = config or ObservationConfig()
    drafts = [
        ObservationDraft(
            source_play_indices=(index,),
            cards=(
                ObservationCardDraft(
                    card=play.card,
                    source_play_index=index,
                    newly_visible_score=1.0,
                    active_area_score=1.0,
                    tracklet_key=f"play-{index}",
                ),
            ),
        )
        for index, play in enumerate(synthetic_round.card_plays, start=1)
    ]
    rng = random.Random(synthetic_round.seed ^ 0x0B5E_4A71)
    for error in errors:
        drafts = error.apply(drafts, rng=rng)
    return tuple(
        _materialize_observation(draft, index, selected_config)
        for index, draft in enumerate(drafts, start=1)
    )


def build_scenario(
    scenario_id: str,
    synthetic_round: SyntheticRound,
    *,
    description: str,
    expected_status: Literal["resolved", "ambiguous", "impossible", "incomplete"],
    behavior: str,
    config: ObservationConfig | None = None,
    errors: Sequence[ObservationError] = (),
) -> RoundScenario:
    """Build a checked-in round scenario with private source truth."""

    selected_config = config or ObservationConfig()
    observations = generate_observations(
        synthetic_round,
        config=selected_config,
        errors=errors,
    )
    reconstruction_input = ReconstructionInput.model_validate(
        {
            "schema_version": "round-reconstruction-input/v1",
            "game_id": f"synthetic-game-{synthetic_round.seed}",
            "round_id": f"synthetic-game-{synthetic_round.seed}-round-01",
            "ruleset": {"name": "doko-normal", "version": "v1"},
            "deck_variant": "doko-40-v1",
            "active_players": list(synthetic_round.active_players),
            "dealer": synthetic_round.dealer,
            "first_trick_leader": synthetic_round.first_trick_leader,
            "observations": [
                observation.model_dump(mode="json", exclude_none=True)
                for observation in observations
            ],
        }
    )
    ground_truth = synthetic_round.ground_truth()
    ground_truth["generator"] = {
        "name": "game_engine.synthetic",
        "version": "synthetic-v1",
        "configuration": {
            "capabilities": list(selected_config.capabilities),
            "package_id": selected_config.package_id,
            "session_id": selected_config.session_id,
            "start_time_ms": selected_config.start_time_ms,
            "step_ms": selected_config.step_ms,
            "analyzer_name": selected_config.analyzer_name,
            "analyzer_version": selected_config.analyzer_version,
            "calibration": selected_config.calibration,
        },
        "error_modules": [error.name for error in errors],
        "error_configuration": [_error_configuration(error) for error in errors],
    }
    ground_truth["observation_sources"] = [
        {
            "observation_index": index,
            "source_play_indices": list(observation.source_play_indices),
        }
        for index, observation in enumerate(_drafts_for_truth(synthetic_round, errors), start=1)
    ]
    return RoundScenario(
        schema_version="round-scenario/v1",
        scenario_id=scenario_id,
        description=description,
        enabled_capabilities=list(selected_config.capabilities),
        input=reconstruction_input,
        ground_truth=ground_truth,
        expected=ScenarioExpectation(
            status=expected_status,
            trick_count=len(synthetic_round.replay.tricks),
            behavior=behavior,
        ),
    )


def _drafts_for_truth(
    synthetic_round: SyntheticRound,
    errors: Sequence[ObservationError],
) -> list[ObservationDraft]:
    """Apply errors again to recover private source links for fixture metadata."""

    drafts = [
        ObservationDraft(
            source_play_indices=(index,),
            cards=(ObservationCardDraft(card=play.card, source_play_index=index),),
        )
        for index, play in enumerate(synthetic_round.card_plays, start=1)
    ]
    rng = random.Random(synthetic_round.seed ^ 0x0B5E_4A71)
    for error in errors:
        drafts = error.apply(drafts, rng=rng)
    return drafts


def _materialize_observation(
    draft: ObservationDraft,
    index: int,
    config: ObservationConfig,
) -> TableObservation:
    observed_card_id_prefix = f"observation-{index:03d}"
    observed_cards = []
    for card_index, draft_card in enumerate(draft.cards, start=1):
        candidates = draft_card.candidates or ((draft_card.card, 1.0),)
        card_id = f"{observed_card_id_prefix}-card-{card_index:02d}"
        associations = [
            {
                "observed_card_id": f"observation-{source_index:03d}-card-01",
                "score": score,
            }
            for source_index, score in draft_card.association_source_play_indices
            if source_index < index
        ]
        observed_card: dict[str, object] = {
            "observed_card_id": card_id,
            "identity_candidates": [
                {"card": card, "probability": probability} for card, probability in candidates
            ],
        }
        if "presence_score" in config.capabilities:
            observed_card["presence_score"] = (
                draft_card.presence_score if draft_card.presence_score is not None else 1.0
            )
        if "newly_visible_score" in config.capabilities:
            observed_card["newly_visible_score"] = (
                draft_card.newly_visible_score
                if draft_card.newly_visible_score is not None
                else 1.0
            )
        if "active_area_score" in config.capabilities:
            observed_card["active_area_score"] = (
                draft_card.active_area_score if draft_card.active_area_score is not None else 1.0
            )
        if "association_candidates" in config.capabilities:
            observed_card["association_candidates"] = associations
        if "card_tracklets" in config.capabilities:
            observed_card["card_tracklet_id"] = (
                draft_card.tracklet_key or f"tracklet-{index:03d}-{card_index:02d}"
            )
        observed_cards.append(observed_card)
    return TableObservation.model_validate(
        {
            "schema_version": "table-observation/v1",
            "observation_id": observed_card_id_prefix,
            "source": {
                "package_id": config.package_id,
                "snippet_part_name": "event_snippet",
            },
            "session": {
                "session_id": config.session_id,
                "event_sequence": index,
            },
            "observed_at_ms": config.start_time_ms + (index - 1) * config.step_ms,
            "status": draft.status,
            "capabilities": list(config.capabilities),
            "cards": observed_cards,
            "calibration": config.calibration,
            "analyzer": {
                "name": config.analyzer_name,
                "version": config.analyzer_version,
            },
            "diagnostics": {},
        }
    )


def _default_probabilities(count: int) -> tuple[float, ...]:
    weights = tuple(float(count - index) for index in range(count))
    total = sum(weights)
    return tuple(weight / total for weight in weights)


def _error_configuration(error: ObservationError) -> dict[str, object]:
    """Return init-time error parameters for reproducible scenario metadata."""

    return {
        field_info.name: getattr(error, field_info.name)
        for field_info in fields(error)
        if field_info.init
    }


def _require_index(observations: Sequence[ObservationDraft], index: int) -> None:
    if not 0 <= index < len(observations):
        raise ValueError("observation index is outside the observation stream.")


def _validate_score(score: float, name: str) -> None:
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{name} must be between zero and one.")


def _default_ruleset() -> Ruleset:
    from .rules import DokoNormalRuleset

    return DokoNormalRuleset()


__all__ = [
    "CandidateConfusion",
    "CandidateMultiplicityViolation",
    "ClearTrick",
    "DropObservations",
    "DuplicateDetection",
    "EarlyAppearance",
    "EmptyObservation",
    "FalseCardProposal",
    "InsufficientEvidenceObservation",
    "MissingIdentityCandidate",
    "ObservationConfig",
    "ObservationDraft",
    "ObservationError",
    "OldTrickReplay",
    "PhysicalCard",
    "ReappearAfterOcclusion",
    "RepeatObservation",
    "RetainedSideCard",
    "SyntheticRound",
    "build_scenario",
    "generate_observations",
    "generate_round",
]
