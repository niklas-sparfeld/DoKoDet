"""Bounded identity-only reconstruction for uncertain table observations."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from .contract import ObservedCard, ReconstructionInput, TableObservation
from .evidence import (
    EVIDENCE_FAMILIES,
    EvidenceFamily,
    VisualEvidenceScore,
    VisualEvidenceWeights,
    score_observed_card,
)
from .replay import ReplayError, TrickResult, replay_round
from .rules import CardPlay, RulesError, Ruleset

ReconstructionStatus = Literal["resolved", "ambiguous", "impossible", "incomplete"]


@dataclass(frozen=True, slots=True)
class GameplayResult:
    """The gameplay result represented by one retained reconstruction hypothesis."""

    plays: tuple[CardPlay, ...]
    tricks: tuple[TrickResult, ...]
    initial_hands: Mapping[str, tuple[str, ...]]

    @property
    def key(self) -> tuple[tuple[str, str], ...]:
        """Return the stable equivalence key used to merge observation explanations."""

        return tuple((play.player, play.card) for play in self.plays)


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Separate identity evidence from costs for latent observation actions."""

    identity_candidate_log_score: float
    ignored_observed_card_count: int
    inferred_missing_play_count: int
    visual_evidence_score: VisualEvidenceScore = field(default_factory=VisualEvidenceScore)

    @property
    def total_score(self) -> float:
        """Return the deterministic branch score used for hypothesis ordering."""

        return (
            self.identity_candidate_log_score
            - 0.35 * self.ignored_observed_card_count
            - 0.75 * self.inferred_missing_play_count
            + self.visual_evidence_score.total
        )


@dataclass(frozen=True, slots=True)
class ReconstructionHypothesis:
    """One legal gameplay result and its best supporting observation explanation."""

    gameplay: GameplayResult
    source_observation_ids: tuple[str, ...]
    source_observed_card_ids: tuple[str, ...]
    ignored_observed_card_ids: tuple[str, ...]
    missing_play_indices: tuple[int, ...]
    score_breakdown: ScoreBreakdown

    @property
    def plays(self) -> tuple[CardPlay, ...]:
        """Return the card plays in logical order."""

        return self.gameplay.plays

    @property
    def tricks(self) -> tuple[TrickResult, ...]:
        """Return derived trick results."""

        return self.gameplay.tricks

    @property
    def score(self) -> float:
        """Return the total deterministic branch score."""

        return self.score_breakdown.total_score


@dataclass(frozen=True, slots=True)
class FocusedDecision:
    """The smallest gameplay difference between retained hypotheses."""

    kind: Literal["card_play"]
    play_index: int
    player: str
    alternatives: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class ReconstructionDiagnostics:
    """Search and evidence facts needed to explain a reconstruction result."""

    ruleset: str
    deck_variant: str
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


@dataclass(frozen=True, slots=True)
class ReconstructionResult:
    """The status, retained gameplay hypotheses, focused alternatives, and diagnostics."""

    status: ReconstructionStatus
    hypotheses: tuple[ReconstructionHypothesis, ...]
    focused_decisions: tuple[FocusedDecision, ...]
    diagnostics: ReconstructionDiagnostics

    @property
    def best_hypothesis(self) -> ReconstructionHypothesis | None:
        """Return the highest-ranked hypothesis, when one exists."""

        return self.hypotheses[0] if self.hypotheses else None


@dataclass(frozen=True, slots=True)
class ReconstructionAblation:
    """Results recorded with one optional visual evidence family enabled and disabled."""

    family: EvidenceFamily
    without_evidence: ReconstructionResult
    with_evidence: ReconstructionResult


@dataclass(frozen=True, slots=True)
class _ObservedCardToken:
    observation_id: str
    observed_card_id: str
    observed_card: ObservedCard
    candidates: tuple[tuple[str, float], ...]
    tracklet_id: str | None


def reconstruct_round(
    reconstruction_input: ReconstructionInput,
    *,
    ruleset: Ruleset | None = None,
    max_missing_plays: int = 1,
    missing_play_slots: Sequence[int] | None = None,
    max_hypotheses: int = 256,
    max_search_nodes: int = 250_000,
    evidence_weights: VisualEvidenceWeights | None = None,
    ablated_evidence: Collection[EvidenceFamily] = (),
    forced_identity_by_observed_card_id: Mapping[str, str] | None = None,
    forced_player_by_play_index: Mapping[int, str] | None = None,
    ignored_observed_card_ids: Collection[str] = (),
) -> ReconstructionResult:
    """Exhaustively reconstruct a bounded identity-only round.

    The search consumes observed-card proposals in time order. It can ignore proposals, choose one
    identity candidate, or insert a bounded missing card play when the input contains fewer card
    proposals than the selected deck requires. ``missing_play_slots`` can constrain an inferred
    play to known logical one-based slots. A complete branch derives its initial player hands from
    the selected plays and is then checked by the deterministic replay core.
    """

    if max_missing_plays < 0:
        raise ValueError("max_missing_plays must not be negative.")
    if max_hypotheses < 1:
        raise ValueError("max_hypotheses must be positive.")
    if max_search_nodes < 1:
        raise ValueError("max_search_nodes must be positive.")
    requested_ablations = tuple(ablated_evidence)
    if any(family not in EVIDENCE_FAMILIES for family in requested_ablations):
        raise ValueError("ablated_evidence contains an unknown evidence family.")
    if len(set(requested_ablations)) != len(requested_ablations):
        raise ValueError("ablated_evidence must contain unique evidence families.")
    forced_identities = dict(forced_identity_by_observed_card_id or {})
    forced_players = dict(forced_player_by_play_index or {})
    required_ignored_card_ids = frozenset(ignored_observed_card_ids)

    selected_ruleset = ruleset or _default_ruleset()
    if selected_ruleset.manifest.deck_variant != reconstruction_input.deck_variant:
        raise ValueError("ruleset manifest must match the reconstruction deck variant.")
    expected_plays = selected_ruleset.manifest.expected_plays
    if missing_play_slots is None:
        allowed_missing_slots: frozenset[int] | None = None
    else:
        requested_missing_slots = tuple(missing_play_slots)
        allowed_missing_slots = frozenset(requested_missing_slots)
        if any(slot < 1 or slot > expected_plays for slot in allowed_missing_slots):
            raise ValueError("missing play slots must be within the manifest play count.")
        if len(allowed_missing_slots) != len(requested_missing_slots):
            raise ValueError("missing play slots must be unique.")
    if any(play_index < 1 or play_index > expected_plays for play_index in forced_players):
        raise ValueError("forced player play indices must be within the manifest play count.")

    tokens, incomplete_observations = _flatten_observations(reconstruction_input.observations)
    missing_budget = min(max_missing_plays, max(0, expected_plays - len(tokens)))
    players = tuple(reconstruction_input.active_players)
    selected_evidence_weights = evidence_weights or VisualEvidenceWeights()
    for family in requested_ablations:
        selected_evidence_weights = selected_evidence_weights.without(family)
    ablated_families = tuple(
        family for family in EVIDENCE_FAMILIES if family in set(requested_ablations)
    )
    tracklets_enabled = "card_tracklets" in _capabilities(reconstruction_input.observations)
    tracklets_enabled = tracklets_enabled and "tracklet" not in ablated_families

    hypotheses: dict[tuple[tuple[str, str], ...], ReconstructionHypothesis] = {}
    rejection_counts: Counter[str] = Counter()
    ignored_observation_ids: set[str] = set()
    search_nodes = 0
    complete_branches = 0
    merged_branches = 0
    truncated = False

    def reject(reason: str) -> None:
        rejection_counts[reason] += 1

    def search(
        token_index: int,
        plays: tuple[CardPlay, ...],
        current_trick: tuple[CardPlay, ...],
        leader: str,
        card_counts: dict[str, int],
        source_observation_ids: tuple[str, ...],
        source_card_ids: tuple[str, ...],
        ignored_card_ids: tuple[str, ...],
        missing_play_indices: tuple[int, ...],
        used_tracklet_ids: frozenset[str],
        identity_log_score: float,
        visual_evidence_score: VisualEvidenceScore,
    ) -> None:
        nonlocal search_nodes, complete_branches, merged_branches, truncated
        if search_nodes >= max_search_nodes:
            truncated = True
            return
        search_nodes += 1

        remaining_tokens = len(tokens) - token_index
        remaining_missing = missing_budget - len(missing_play_indices)
        if len(plays) + remaining_tokens + remaining_missing < expected_plays:
            reject("search branch cannot reach the complete card-play count")
            return

        if len(plays) == expected_plays:
            complete_branches += 1
            trailing_card_ids = tuple(token.observed_card_id for token in tokens[token_index:])
            all_ignored_card_ids = ignored_card_ids + trailing_card_ids
            ignored_observation_ids.update(token.observation_id for token in tokens[token_index:])
            _retain_complete_branch(
                hypotheses,
                plays=plays,
                source_observation_ids=source_observation_ids,
                source_card_ids=source_card_ids,
                ignored_card_ids=all_ignored_card_ids,
                missing_play_indices=missing_play_indices,
                identity_log_score=identity_log_score,
                visual_evidence_score=visual_evidence_score,
                active_players=players,
                first_trick_leader=reconstruction_input.first_trick_leader,
                ruleset=selected_ruleset,
                max_hypotheses=max_hypotheses,
                reject=reject,
                on_merged=lambda: _increment_merged(),
            )
            return

        if token_index < len(tokens):
            token = tokens[token_index]
            candidates = (
                () if token.observed_card_id in required_ignored_card_ids else token.candidates
            )
            if candidates and token.observed_card_id in forced_identities:
                forced_card = forced_identities[token.observed_card_id]
                candidate_probabilities = dict(candidates)
                candidates = ((forced_card, candidate_probabilities.get(forced_card, 1.0)),)
            for card, probability in candidates:
                if card not in selected_ruleset.manifest_cards:
                    reject(f"replay rejected branch: candidate {card} is outside the selected deck")
                    continue
                if card_counts[card] >= selected_ruleset.card_copy_count(card):
                    reject(f"replay rejected branch: card multiplicity for {card} exceeds the deck")
                    continue
                if (
                    tracklets_enabled
                    and token.tracklet_id is not None
                    and token.tracklet_id in used_tracklet_ids
                ):
                    reject(
                        "association rejected branch: one card tracklet cannot represent "
                        "two card plays"
                    )
                    continue
                next_play, next_trick, next_leader = _append_play(
                    card,
                    current_trick=current_trick,
                    leader=leader,
                    active_players=players,
                    ruleset=selected_ruleset,
                )
                required_player = forced_players.get(len(plays) + 1)
                if required_player is not None and next_play.player != required_player:
                    reject(
                        f"correction rejected branch: card play {len(plays) + 1} must be by "
                        f"{required_player}, got {next_play.player}"
                    )
                    continue
                next_counts = dict(card_counts)
                next_counts[card] += 1
                next_tracklet_ids = (
                    used_tracklet_ids | {token.tracklet_id}
                    if tracklets_enabled and token.tracklet_id is not None
                    else used_tracklet_ids
                )
                selected_card_evidence = score_observed_card(
                    token.observed_card,
                    action="select",
                    selected_observed_card_ids=frozenset(source_card_ids),
                    selected_tracklet_ids=used_tracklet_ids,
                    weights=selected_evidence_weights,
                )
                search(
                    token_index + 1,
                    plays + (next_play,),
                    next_trick,
                    next_leader,
                    next_counts,
                    source_observation_ids + (token.observation_id,),
                    source_card_ids + (token.observed_card_id,),
                    ignored_card_ids,
                    missing_play_indices,
                    next_tracklet_ids,
                    identity_log_score + math.log(probability),
                    visual_evidence_score.add(selected_card_evidence),
                )

            ignored_observation_ids.add(token.observation_id)
            ignored_card_evidence = score_observed_card(
                token.observed_card,
                action="ignore",
                selected_observed_card_ids=frozenset(source_card_ids),
                selected_tracklet_ids=used_tracklet_ids,
                weights=selected_evidence_weights,
            )
            search(
                token_index + 1,
                plays,
                current_trick,
                leader,
                card_counts,
                source_observation_ids,
                source_card_ids,
                ignored_card_ids + (token.observed_card_id,),
                missing_play_indices,
                used_tracklet_ids,
                identity_log_score,
                visual_evidence_score.add(ignored_card_evidence),
            )

        next_missing_slot = len(plays) + 1
        if len(missing_play_indices) < missing_budget and (
            allowed_missing_slots is None or next_missing_slot in allowed_missing_slots
        ):
            for card in selected_ruleset.manifest_cards:
                if card_counts[card] >= selected_ruleset.card_copy_count(card):
                    continue
                next_play, next_trick, next_leader = _append_play(
                    card,
                    current_trick=current_trick,
                    leader=leader,
                    active_players=players,
                    ruleset=selected_ruleset,
                )
                next_counts = dict(card_counts)
                next_counts[card] += 1
                search(
                    token_index,
                    plays + (next_play,),
                    next_trick,
                    next_leader,
                    next_counts,
                    source_observation_ids,
                    source_card_ids,
                    ignored_card_ids,
                    missing_play_indices + (len(plays) + 1,),
                    used_tracklet_ids,
                    identity_log_score,
                    visual_evidence_score,
                )

    merged_counter = [0]

    def _increment_merged() -> None:
        merged_counter[0] += 1

    initial_counts = {card: 0 for card in selected_ruleset.manifest_cards}
    search(
        0,
        (),
        (),
        reconstruction_input.first_trick_leader,
        initial_counts,
        (),
        (),
        (),
        (),
        frozenset(),
        0.0,
        VisualEvidenceScore(),
    )
    merged_branches = merged_counter[0]

    ordered_hypotheses = tuple(
        sorted(
            hypotheses.values(),
            key=lambda hypothesis: (-hypothesis.score, hypothesis.gameplay.key),
        )
    )
    if ordered_hypotheses:
        status: ReconstructionStatus = "resolved" if len(ordered_hypotheses) == 1 else "ambiguous"
        focused_decisions = _focused_decisions(ordered_hypotheses)
    else:
        status = "incomplete" if len(tokens) < expected_plays else "impossible"
        focused_decisions = ()
        if len(tokens) < expected_plays:
            reject(
                "incomplete result: fewer card proposals than the complete card-play count "
                f"({len(tokens)} < {expected_plays})"
            )
        else:
            reject("impossible result: no legal complete hypothesis survived replay")

    diagnostics = ReconstructionDiagnostics(
        ruleset=f"{reconstruction_input.ruleset.name}/{reconstruction_input.ruleset.version}",
        deck_variant=reconstruction_input.deck_variant,
        capabilities=_capabilities(reconstruction_input.observations),
        calibration_states=tuple(
            sorted({observation.calibration for observation in reconstruction_input.observations})
        ),
        observations_seen=len(reconstruction_input.observations),
        card_proposals_seen=len(tokens),
        search_nodes=search_nodes,
        complete_branches=complete_branches,
        merged_branches=merged_branches,
        rejected_branches=tuple(
            f"{reason} (x{count})" for reason, count in rejection_counts.items()
        ),
        ignored_observations=tuple(sorted(ignored_observation_ids)),
        incomplete_observations=tuple(sorted(incomplete_observations)),
        search_limits={
            "max_missing_plays": max_missing_plays,
            "effective_missing_play_budget": missing_budget,
            "missing_play_slots": (
                -1 if allowed_missing_slots is None else len(allowed_missing_slots)
            ),
            "max_hypotheses": max_hypotheses,
            "max_search_nodes": max_search_nodes,
        },
        truncated=truncated,
        evidence_families=_evidence_families(reconstruction_input.observations),
        ablated_evidence=ablated_families,
    )
    return ReconstructionResult(
        status=status,
        hypotheses=ordered_hypotheses,
        focused_decisions=focused_decisions,
        diagnostics=diagnostics,
    )


def run_ablation(
    reconstruction_input: ReconstructionInput,
    *,
    family: EvidenceFamily,
    ruleset: Ruleset | None = None,
    max_missing_plays: int = 1,
    missing_play_slots: Sequence[int] | None = None,
    max_hypotheses: int = 256,
    max_search_nodes: int = 250_000,
    evidence_weights: VisualEvidenceWeights | None = None,
) -> ReconstructionAblation:
    """Run the same input with one optional evidence family enabled and disabled."""

    if family not in EVIDENCE_FAMILIES:
        raise ValueError(f"unknown evidence family: {family}")
    common = {
        "ruleset": ruleset,
        "max_missing_plays": max_missing_plays,
        "missing_play_slots": missing_play_slots,
        "max_hypotheses": max_hypotheses,
        "max_search_nodes": max_search_nodes,
        "evidence_weights": evidence_weights,
    }
    with_evidence = reconstruct_round(reconstruction_input, **common)
    without_evidence = reconstruct_round(
        reconstruction_input,
        **common,
        ablated_evidence=(family,),
    )
    return ReconstructionAblation(
        family=family,
        without_evidence=without_evidence,
        with_evidence=with_evidence,
    )


def reconstruct(
    reconstruction_input: ReconstructionInput,
    **kwargs: object,
) -> ReconstructionResult:
    """Alias for :func:`reconstruct_round` used by small local integrations."""

    return reconstruct_round(reconstruction_input, **kwargs)  # type: ignore[arg-type]


def reconstruct_manual_sequence(
    reconstruction_input: ReconstructionInput,
    plays: Sequence[CardPlay],
    *,
    ruleset: Ruleset | None = None,
) -> ReconstructionResult:
    """Validate a complete human-supplied card-play sequence with the selected ruleset."""

    selected_ruleset = ruleset or _default_ruleset()
    if selected_ruleset.manifest.deck_variant != reconstruction_input.deck_variant:
        raise ValueError("ruleset manifest must match the reconstruction deck variant.")
    resolved_plays = tuple(plays)
    initial_hands: dict[str, list[str]] = {
        player: [] for player in reconstruction_input.active_players
    }
    for play in resolved_plays:
        if play.player not in initial_hands:
            raise ReplayError(f"card play player {play.player} is not active in this round.")
        try:
            selected_ruleset.validate_card(play.card)
        except RulesError as error:
            raise ReplayError(f"card play: {error}") from error
        initial_hands.setdefault(play.player, []).append(play.card)
    replay = replay_round(
        resolved_plays,
        active_players=reconstruction_input.active_players,
        first_trick_leader=reconstruction_input.first_trick_leader,
        initial_hands=initial_hands,
        ruleset=selected_ruleset,
    )
    gameplay = GameplayResult(
        plays=resolved_plays,
        tricks=replay.tricks,
        initial_hands={player: tuple(cards) for player, cards in initial_hands.items()},
    )
    hypothesis = ReconstructionHypothesis(
        gameplay=gameplay,
        source_observation_ids=tuple(
            observation.observation_id for observation in reconstruction_input.observations
        ),
        source_observed_card_ids=tuple(
            card.observed_card_id
            for observation in reconstruction_input.observations
            for card in observation.cards
        ),
        ignored_observed_card_ids=(),
        missing_play_indices=(),
        score_breakdown=ScoreBreakdown(
            identity_candidate_log_score=0.0,
            ignored_observed_card_count=0,
            inferred_missing_play_count=0,
        ),
    )
    diagnostics = ReconstructionDiagnostics(
        ruleset=f"{reconstruction_input.ruleset.name}/{reconstruction_input.ruleset.version}",
        deck_variant=reconstruction_input.deck_variant,
        capabilities=_capabilities(reconstruction_input.observations),
        calibration_states=tuple(
            sorted({observation.calibration for observation in reconstruction_input.observations})
        ),
        observations_seen=len(reconstruction_input.observations),
        card_proposals_seen=sum(
            len(observation.cards) for observation in reconstruction_input.observations
        ),
        search_nodes=0,
        complete_branches=1,
        merged_branches=0,
        rejected_branches=(),
        ignored_observations=(),
        incomplete_observations=(),
        search_limits={},
        truncated=False,
        evidence_families=_evidence_families(reconstruction_input.observations),
        ablated_evidence=(),
    )
    return ReconstructionResult(
        status="resolved",
        hypotheses=(hypothesis,),
        focused_decisions=(),
        diagnostics=diagnostics,
    )


def _flatten_observations(
    observations: Sequence[TableObservation],
) -> tuple[tuple[_ObservedCardToken, ...], tuple[str, ...]]:
    tokens: list[_ObservedCardToken] = []
    incomplete_observations: list[str] = []
    for observation in observations:
        if observation.status == "insufficient_evidence":
            incomplete_observations.append(observation.observation_id)
        if not observation.cards:
            incomplete_observations.append(observation.observation_id)
        for card in observation.cards:
            tokens.append(
                _ObservedCardToken(
                    observation_id=observation.observation_id,
                    observed_card_id=card.observed_card_id,
                    observed_card=card,
                    candidates=tuple(
                        (candidate.card, candidate.probability)
                        for candidate in card.identity_candidates
                    ),
                    tracklet_id=card.card_tracklet_id,
                )
            )
    return tuple(tokens), tuple(dict.fromkeys(incomplete_observations))


def _append_play(
    card: str,
    *,
    current_trick: tuple[CardPlay, ...],
    leader: str,
    active_players: Sequence[str],
    ruleset: Ruleset,
) -> tuple[CardPlay, tuple[CardPlay, ...], str]:
    order = ruleset.clockwise_order(active_players, leader)
    play = CardPlay(player=order[len(current_trick)], card=card)
    next_trick = current_trick + (play,)
    if len(next_trick) < 4:
        return play, next_trick, leader
    winner, _ = ruleset.trick_winner(next_trick)
    return play, (), winner


def _retain_complete_branch(
    hypotheses: dict[tuple[tuple[str, str], ...], ReconstructionHypothesis],
    *,
    plays: tuple[CardPlay, ...],
    source_observation_ids: tuple[str, ...],
    source_card_ids: tuple[str, ...],
    ignored_card_ids: tuple[str, ...],
    missing_play_indices: tuple[int, ...],
    identity_log_score: float,
    visual_evidence_score: VisualEvidenceScore,
    active_players: Sequence[str],
    first_trick_leader: str,
    ruleset: Ruleset,
    max_hypotheses: int,
    reject,
    on_merged,
) -> None:
    if len(plays) != ruleset.manifest.expected_plays:
        reject("replay rejected branch: complete branch has the wrong card-play count")
        return
    initial_hands: dict[str, list[str]] = {player: [] for player in active_players}
    for play in plays:
        initial_hands[play.player].append(play.card)
    try:
        replay = replay_round(
            plays,
            active_players=active_players,
            first_trick_leader=first_trick_leader,
            initial_hands=initial_hands,
            ruleset=ruleset,
        )
    except ReplayError as error:
        reject(f"replay rejected branch: {error}")
        return

    gameplay = GameplayResult(
        plays=plays,
        tricks=replay.tricks,
        initial_hands={player: tuple(cards) for player, cards in initial_hands.items()},
    )
    key = gameplay.key
    score_breakdown = ScoreBreakdown(
        identity_candidate_log_score=identity_log_score,
        ignored_observed_card_count=len(ignored_card_ids),
        inferred_missing_play_count=len(missing_play_indices),
        visual_evidence_score=visual_evidence_score,
    )
    hypothesis = ReconstructionHypothesis(
        gameplay=gameplay,
        source_observation_ids=tuple(dict.fromkeys(source_observation_ids)),
        source_observed_card_ids=tuple(dict.fromkeys(source_card_ids)),
        ignored_observed_card_ids=tuple(dict.fromkeys(ignored_card_ids)),
        missing_play_indices=missing_play_indices,
        score_breakdown=score_breakdown,
    )
    if key in hypotheses:
        on_merged()
        existing = hypotheses[key]
        merged_source_observations = tuple(
            sorted(set(existing.source_observation_ids) | set(hypothesis.source_observation_ids))
        )
        merged_source_cards = tuple(
            sorted(
                set(existing.source_observed_card_ids) | set(hypothesis.source_observed_card_ids)
            )
        )
        if hypothesis.score > existing.score:
            hypotheses[key] = ReconstructionHypothesis(
                gameplay=hypothesis.gameplay,
                source_observation_ids=merged_source_observations,
                source_observed_card_ids=merged_source_cards,
                ignored_observed_card_ids=hypothesis.ignored_observed_card_ids,
                missing_play_indices=hypothesis.missing_play_indices,
                score_breakdown=hypothesis.score_breakdown,
            )
        else:
            hypotheses[key] = ReconstructionHypothesis(
                gameplay=existing.gameplay,
                source_observation_ids=merged_source_observations,
                source_observed_card_ids=merged_source_cards,
                ignored_observed_card_ids=existing.ignored_observed_card_ids,
                missing_play_indices=existing.missing_play_indices,
                score_breakdown=existing.score_breakdown,
            )
        return
    if len(hypotheses) >= max_hypotheses:
        reject("search result truncated: maximum retained hypotheses reached")
        return
    hypotheses[key] = hypothesis


def _focused_decisions(
    hypotheses: Sequence[ReconstructionHypothesis],
) -> tuple[FocusedDecision, ...]:
    if len(hypotheses) < 2:
        return ()
    max_plays = max(len(hypothesis.plays) for hypothesis in hypotheses)
    for index in range(max_plays):
        alternatives = {
            (
                hypothesis.plays[index].player,
                hypothesis.plays[index].card,
            )
            for hypothesis in hypotheses
            if index < len(hypothesis.plays)
        }
        if len(alternatives) < 2:
            continue
        ordered_alternatives = tuple(f"{player}:{card}" for player, card in sorted(alternatives))
        source_observation_ids = tuple(
            sorted(
                {
                    observation_id
                    for hypothesis in hypotheses
                    for observation_id in hypothesis.source_observation_ids
                    if index < len(hypothesis.plays)
                    and (hypothesis.plays[index].player, hypothesis.plays[index].card)
                    in alternatives
                }
            )
        )
        player = sorted(player for player, _ in alternatives)[0]
        return (
            FocusedDecision(
                kind="card_play",
                play_index=index + 1,
                player=player,
                alternatives=ordered_alternatives,
                source_observation_ids=source_observation_ids,
                description=(
                    f"card play {index + 1} has retained legal alternatives: "
                    + ", ".join(ordered_alternatives)
                ),
            ),
        )
    return ()


def _capabilities(observations: Sequence[TableObservation]) -> tuple[str, ...]:
    """Return declared capabilities in their contract order."""

    capabilities = {
        capability for observation in observations for capability in observation.capabilities
    }
    from .contract import ANALYZER_CAPABILITIES

    return tuple(capability for capability in ANALYZER_CAPABILITIES if capability in capabilities)


def _evidence_families(observations: Sequence[TableObservation]) -> tuple[EvidenceFamily, ...]:
    """Return optional evidence families available in the input."""

    capabilities = set(_capabilities(observations))
    available: list[EvidenceFamily] = []
    if "presence_score" in capabilities:
        available.append("presence")
    if {"newly_visible_score", "association_candidates"} & capabilities:
        available.append("transition")
    if "active_area_score" in capabilities:
        available.append("active_area")
    if "card_tracklets" in capabilities:
        available.append("tracklet")
    return tuple(available)


def _default_ruleset() -> Ruleset:
    from .rules import DokoNormalRuleset

    return DokoNormalRuleset()


__all__ = [
    "FocusedDecision",
    "GameplayResult",
    "ReconstructionAblation",
    "ReconstructionDiagnostics",
    "ReconstructionHypothesis",
    "ReconstructionResult",
    "ReconstructionStatus",
    "ScoreBreakdown",
    "reconstruct",
    "reconstruct_manual_sequence",
    "reconstruct_round",
]
