from __future__ import annotations

import pytest

from game_engine.rules import CardPlay, DokoNormalRuleset, RulesError

RULESET = DokoNormalRuleset()


@pytest.mark.parametrize(
    ("card", "category"),
    [
        ("CLUBS_ACE", "CLUBS"),
        ("SPADES_KING", "SPADES"),
        ("HEARTS_TEN", "TRUMP"),
        ("DIAMONDS_ACE", "TRUMP"),
        ("CLUBS_QUEEN", "TRUMP"),
        ("HEARTS_JACK", "TRUMP"),
    ],
)
def test_normal_ruleset_classifies_trump_and_plain_suits(card: str, category: str) -> None:
    assert RULESET.card_category(card) == category


def test_normal_ruleset_orders_all_trumps_high_to_low() -> None:
    expected = [
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
    ]

    actual = sorted(
        (card for card in RULESET.manifest_cards if RULESET.card_category(card) == "TRUMP"),
        key=RULESET.card_order,
        reverse=True,
    )

    assert actual == expected


def test_normal_ruleset_orders_plain_suit_ranks_high_to_low() -> None:
    expected_by_suit = {
        "CLUBS": ["CLUBS_ACE", "CLUBS_TEN", "CLUBS_KING"],
        "SPADES": ["SPADES_ACE", "SPADES_TEN", "SPADES_KING"],
        "HEARTS": ["HEARTS_ACE", "HEARTS_KING"],
    }
    for suit, expected in expected_by_suit.items():
        actual = sorted(
            (card for card in RULESET.manifest_cards if RULESET.card_category(card) == suit),
            key=RULESET.card_order,
            reverse=True,
        )
        assert actual == expected


def test_following_category_requires_trump_or_the_led_plain_suit() -> None:
    hand = [
        "CLUBS_ACE",
        "SPADES_ACE",
        "HEARTS_ACE",
        "DIAMONDS_ACE",
        "CLUBS_QUEEN",
    ]

    for suit in ("CLUBS", "SPADES", "HEARTS"):
        assert RULESET.legal_cards(hand, [CardPlay("player-01", f"{suit}_KING")]) == (
            f"{suit}_ACE",
        )
    assert RULESET.legal_cards(hand, [CardPlay("player-01", "DIAMONDS_KING")]) == (
        "DIAMONDS_ACE",
        "CLUBS_QUEEN",
    )
    assert RULESET.legal_cards(hand, [CardPlay("player-01", "CLUBS_KING")]) == ("CLUBS_ACE",)


def test_trick_winner_uses_plain_suit_then_trump_order() -> None:
    plain_trick = (
        CardPlay("player-01", "CLUBS_KING"),
        CardPlay("player-02", "HEARTS_ACE"),
        CardPlay("player-03", "CLUBS_ACE"),
        CardPlay("player-04", "SPADES_ACE"),
    )
    trump_trick = (
        CardPlay("player-01", "CLUBS_KING"),
        CardPlay("player-02", "DIAMONDS_ACE"),
        CardPlay("player-03", "CLUBS_QUEEN"),
        CardPlay("player-04", "DIAMONDS_QUEEN"),
    )
    plain_lead_with_trump = (
        CardPlay("player-01", "HEARTS_KING"),
        CardPlay("player-02", "HEARTS_ACE"),
        CardPlay("player-03", "DIAMONDS_ACE"),
        CardPlay("player-04", "SPADES_KING"),
    )

    assert RULESET.trick_winner(plain_trick) == ("player-03", "CLUBS_ACE")
    assert RULESET.trick_winner(trump_trick) == ("player-03", "CLUBS_QUEEN")
    assert RULESET.trick_winner(plain_lead_with_trump) == ("player-03", "DIAMONDS_ACE")


def test_next_player_follows_the_declared_clockwise_order() -> None:
    active_players = ("player-01", "player-02", "player-03", "player-04")

    assert RULESET.next_player(active_players, "player-01") == "player-02"
    assert RULESET.next_player(active_players, "player-04") == "player-01"


def test_invalid_card_is_rejected_by_the_ruleset() -> None:
    with pytest.raises(RulesError, match="not in the selected deck"):
        RULESET.card_category("HEARTS_NINE")
