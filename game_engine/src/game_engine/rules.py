"""Deterministic normal-round rules for the supported Doppelkopf deck."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from .cards import DeckManifest, load_deck_manifest

CardCategory = Literal["TRUMP", "CLUBS", "SPADES", "HEARTS"]

_TRUMP_ORDER_HIGH_TO_LOW = (
    "HEARTS_TEN",
    "CLUBS_QUEEN",
    "SPADES_QUEEN",
    "HEARTS_QUEEN",
    "DIAMONDS_QUEEN",
    "CLUBS_JACK",
    "SPADES_JACK",
    "HEARTS_JACK",
    "DIAMONDS_JACK",
    "DIAMONDS_ACE",
    "DIAMONDS_TEN",
    "DIAMONDS_KING",
    "DIAMONDS_NINE",
)
_PLAIN_RANK_ORDER_HIGH_TO_LOW = ("ACE", "TEN", "KING", "NINE")


class RulesError(ValueError):
    """Raised when a card or play is not valid for the selected ruleset."""


@dataclass(frozen=True, slots=True)
class CardPlay:
    """One card play in logical play order."""

    player: str
    card: str


class Ruleset(Protocol):
    """Interface required by deterministic replay and later reconstruction."""

    manifest: DeckManifest

    @property
    def hand_size(self) -> int: ...

    @property
    def manifest_cards(self) -> tuple[str, ...]: ...

    def card_copy_count(self, card: str) -> int: ...

    def validate_card(self, card: str) -> str: ...

    def card_category(self, card: str) -> CardCategory: ...

    def following_category(self, card: str) -> CardCategory: ...

    def card_order(self, card: str) -> int: ...

    def legal_cards(self, hand: Sequence[str], trick: Sequence[CardPlay]) -> tuple[str, ...]: ...

    def trick_winner(self, trick: Sequence[CardPlay]) -> tuple[str, str]: ...

    def clockwise_order(self, active_players: Sequence[str], leader: str) -> tuple[str, ...]: ...

    def next_player(self, active_players: Sequence[str], player: str) -> str: ...

    def validate_initial_hands(
        self,
        active_players: Sequence[str],
        initial_hands: Mapping[str, Sequence[str]],
    ) -> dict[str, list[str]]: ...


class DokoNormalRuleset:
    """Normal V1 card-play rules, backed by an explicit deck manifest."""

    def __init__(self, manifest: DeckManifest | None = None) -> None:
        self.manifest = manifest or load_deck_manifest("doko-40-v1")
        self._manifest_cards = tuple(card.card for card in self.manifest.cards)
        self._manifest_card_set = frozenset(self._manifest_cards)
        self._copy_counts = {card.card: card.copies for card in self.manifest.cards}
        self._trump_strength = {
            card: len(_TRUMP_ORDER_HIGH_TO_LOW) - index
            for index, card in enumerate(_TRUMP_ORDER_HIGH_TO_LOW)
            if card in self._manifest_card_set
        }
        self._plain_strength = {
            rank: len(_PLAIN_RANK_ORDER_HIGH_TO_LOW) - index
            for index, rank in enumerate(_PLAIN_RANK_ORDER_HIGH_TO_LOW)
        }

    @property
    def hand_size(self) -> int:
        """Return the equal hand size derived from the deck manifest."""

        return self.manifest.expected_plays // 4

    @property
    def manifest_cards(self) -> tuple[str, ...]:
        """Return visual card identities in manifest order."""

        return self._manifest_cards

    def card_copy_count(self, card: str) -> int:
        """Return the allowed physical multiplicity for one visual identity."""

        self.validate_card(card)
        return self._copy_counts[card]

    def validate_card(self, card: str) -> str:
        """Validate that a visual card identity belongs to the selected deck."""

        if card not in self._manifest_card_set:
            raise RulesError(f"card {card!r} is not in the selected deck.")
        return card

    def card_category(self, card: str) -> CardCategory:
        """Return the following category for a visual card identity."""

        self.validate_card(card)
        suit, rank = card.rsplit("_", maxsplit=1)
        if (
            suit == "DIAMONDS"
            or (suit == "HEARTS" and rank == "TEN")
            or rank
            in {
                "QUEEN",
                "JACK",
            }
        ):
            return "TRUMP"
        return suit  # type: ignore[return-value]

    def following_category(self, card: str) -> CardCategory:
        """Return the category that a player must follow when this card leads."""

        return self.card_category(card)

    def card_order(self, card: str) -> int:
        """Return an order value where a larger value wins within its category."""

        self.validate_card(card)
        category = self.card_category(card)
        if category == "TRUMP":
            return self._trump_strength[card]
        rank = card.rsplit("_", maxsplit=1)[1]
        return self._plain_strength[rank]

    def legal_cards(self, hand: Sequence[str], trick: Sequence[CardPlay]) -> tuple[str, ...]:
        """Return the cards in ``hand`` that satisfy the led following category."""

        for card in hand:
            self.validate_card(card)
        if not trick:
            return tuple(hand)

        lead_category = self.following_category(trick[0].card)
        following = tuple(card for card in hand if self.following_category(card) == lead_category)
        return following or tuple(hand)

    def trick_winner(self, trick: Sequence[CardPlay]) -> tuple[str, str]:
        """Return the winner and winning card for one complete four-card trick."""

        if len(trick) != 4:
            raise RulesError("a trick must contain exactly four card plays.")
        players = [play.player for play in trick]
        if len(players) != len(set(players)):
            raise RulesError("a trick cannot contain two card plays by one player.")

        lead_card = trick[0].card
        winner = trick[0]
        for candidate in trick[1:]:
            if self.card_beats(candidate.card, winner.card, lead_card):
                winner = candidate
        return winner.player, winner.card

    def card_beats(self, candidate: str, incumbent: str, lead_card: str) -> bool:
        """Return whether ``candidate`` beats ``incumbent`` for the led card."""

        lead_category = self.card_category(lead_card)
        candidate_category = self.card_category(candidate)
        incumbent_category = self.card_category(incumbent)

        candidate_eligible = candidate_category == "TRUMP" or candidate_category == lead_category
        incumbent_eligible = incumbent_category == "TRUMP" or incumbent_category == lead_category
        if candidate_eligible != incumbent_eligible:
            return candidate_eligible
        if not candidate_eligible:
            return False
        if candidate_category != incumbent_category:
            return candidate_category == "TRUMP"
        return self.card_order(candidate) > self.card_order(incumbent)

    def clockwise_order(self, active_players: Sequence[str], leader: str) -> tuple[str, ...]:
        """Return active players from ``leader`` in declared clockwise order."""

        players = tuple(active_players)
        if not players or len(players) != len(set(players)):
            raise RulesError("active players must be non-empty and unique.")
        if leader not in players:
            raise RulesError("trick leader must be an active player.")
        leader_index = players.index(leader)
        return players[leader_index:] + players[:leader_index]

    def next_player(self, active_players: Sequence[str], player: str) -> str:
        """Return the next active player in declared clockwise order."""

        players = tuple(active_players)
        if player not in players:
            raise RulesError("player must be active.")
        return players[(players.index(player) + 1) % len(players)]

    def validate_initial_hands(
        self,
        active_players: Sequence[str],
        initial_hands: Mapping[str, Sequence[str]],
    ) -> dict[str, list[str]]:
        """Validate and copy the complete physical deck represented by visual identities."""

        players = tuple(active_players)
        if len(players) != 4 or len(players) != len(set(players)):
            raise RulesError("a round must have exactly four unique active players.")
        if set(initial_hands) != set(players):
            raise RulesError("initial hands must contain exactly the active players.")

        copied_hands: dict[str, list[str]] = {}
        actual_counts = {card: 0 for card in self.manifest_cards}
        for player in players:
            hand = list(initial_hands[player])
            if len(hand) != self.hand_size:
                raise RulesError(
                    f"player hand size for {player} must be {self.hand_size}, got {len(hand)}."
                )
            for card in hand:
                self.validate_card(card)
                actual_counts[card] += 1
            copied_hands[player] = hand

        expected_counts = self._copy_counts
        if actual_counts != expected_counts:
            raise RulesError(
                f"deck count does not match the selected manifest: expected {expected_counts}, "
                f"got {actual_counts}."
            )
        return copied_hands


__all__ = ["CardCategory", "CardPlay", "DokoNormalRuleset", "RulesError", "Ruleset"]
