"""Deterministic replay of a resolved round card-play sequence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .rules import CardPlay, RulesError, Ruleset


class ReplayError(ValueError):
    """Raised when a resolved card-play sequence contradicts the round rules."""


@dataclass(frozen=True, slots=True)
class TrickResult:
    """The derived result of one complete trick."""

    index: int
    leader: str
    plays: tuple[CardPlay, ...]
    winner: str
    winning_card: str


@dataclass(frozen=True, slots=True)
class RoundReplay:
    """A validated card-play sequence and its derived trick results."""

    plays: tuple[CardPlay, ...]
    tricks: tuple[TrickResult, ...]


def replay_round(
    plays: Iterable[CardPlay],
    *,
    active_players: Sequence[str],
    first_trick_leader: str,
    initial_hands: Mapping[str, Sequence[str]],
    ruleset: Ruleset | None = None,
) -> RoundReplay:
    """Replay a complete resolved round and derive each trick winner.

    ``active_players`` must be in clockwise order. ``initial_hands`` contains visual identities;
    repeated identities represent the two physical copies allowed by the selected manifest.
    """

    selected_ruleset = ruleset or _default_ruleset()
    players = tuple(active_players)
    if len(players) != 4 or len(players) != len(set(players)):
        raise ReplayError("a round must have exactly four unique active players.")
    if first_trick_leader not in players:
        raise ReplayError("first trick leader must be an active player.")

    try:
        remaining_hands = selected_ruleset.validate_initial_hands(players, initial_hands)
    except RulesError as error:
        raise ReplayError(str(error)) from error

    resolved_plays = tuple(plays)
    expected_play_count = selected_ruleset.manifest.expected_plays
    if len(resolved_plays) != expected_play_count:
        raise ReplayError(
            f"card-play count must be {expected_play_count}, got {len(resolved_plays)}."
        )

    tricks: list[TrickResult] = []
    current_trick: list[CardPlay] = []
    leader = first_trick_leader
    for play_index, play in enumerate(resolved_plays, start=1):
        trick_index = (play_index - 1) // 4 + 1
        offset = (play_index - 1) % 4
        expected_player = selected_ruleset.clockwise_order(players, leader)[offset]
        if play.player != expected_player:
            raise ReplayError(
                f"card play {play_index} must be by {expected_player}, got {play.player}."
            )
        try:
            selected_ruleset.validate_card(play.card)
        except RulesError as error:
            raise ReplayError(f"card play {play_index}: {error}") from error
        if play.card not in remaining_hands[play.player]:
            raise ReplayError(
                f"card play {play_index} by {play.player} is not in that player's remaining hand."
            )

        try:
            legal_cards = selected_ruleset.legal_cards(remaining_hands[play.player], current_trick)
        except RulesError as error:
            raise ReplayError(f"card play {play_index}: {error}") from error
        if play.card not in legal_cards:
            raise ReplayError(
                f"card play {play_index} by {play.player} violates the following category."
            )

        remaining_hands[play.player].remove(play.card)
        current_trick.append(play)
        if len(current_trick) == 4:
            try:
                winner, winning_card = selected_ruleset.trick_winner(current_trick)
            except RulesError as error:
                raise ReplayError(f"trick {trick_index}: {error}") from error
            tricks.append(
                TrickResult(
                    index=trick_index,
                    leader=leader,
                    plays=tuple(current_trick),
                    winner=winner,
                    winning_card=winning_card,
                )
            )
            leader = winner
            current_trick.clear()

    if current_trick:
        raise ReplayError("card-play sequence ended with an incomplete trick.")
    if any(remaining_hands[player] for player in players):
        raise ReplayError("card-play sequence did not empty every player hand.")
    return RoundReplay(plays=resolved_plays, tricks=tuple(tricks))


def _default_ruleset() -> Ruleset:
    from .rules import DokoNormalRuleset

    return DokoNormalRuleset()


__all__ = ["CardPlay", "ReplayError", "RoundReplay", "TrickResult", "replay_round"]
