from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from game_engine.replay import CardPlay, ReplayError, replay_round

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1" / "rounds" / "unambiguous.json"
)


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fixture_round() -> tuple[list[CardPlay], dict[str, list[str]]]:
    payload = load_fixture()
    ground_truth = payload["ground_truth"]
    assert isinstance(ground_truth, dict)

    card_plays = ground_truth["card_plays"]
    physical_hands = ground_truth["physical_hands"]
    assert isinstance(card_plays, list)
    assert isinstance(physical_hands, dict)

    plays = [CardPlay(player=play["player"], card=play["card"]) for play in card_plays]
    hands = {
        player: [physical_card.rsplit("-copy-", maxsplit=1)[0] for physical_card in cards]
        for player, cards in physical_hands.items()
    }
    return plays, hands


def test_exact_fixture_replays_and_derives_each_trick_winner() -> None:
    plays, hands = fixture_round()
    payload = load_fixture()
    observations = payload["input"]["observations"]
    assert [
        observation["cards"][0]["identity_candidates"][0]["card"] for observation in observations
    ] == [play.card for play in plays]

    replay = replay_round(
        plays,
        active_players=("player-01", "player-02", "player-03", "player-04"),
        first_trick_leader="player-01",
        initial_hands=hands,
    )

    assert len(replay.plays) == 40
    assert len(replay.tricks) == 10
    assert [trick.leader for trick in replay.tricks] == [
        "player-01",
        "player-02",
        "player-03",
        "player-01",
        "player-01",
        "player-02",
        "player-04",
        "player-02",
        "player-02",
        "player-02",
    ]
    assert [(trick.index, trick.winner) for trick in replay.tricks] == [
        (1, "player-02"),
        (2, "player-03"),
        (3, "player-01"),
        (4, "player-01"),
        (5, "player-02"),
        (6, "player-04"),
        (7, "player-02"),
        (8, "player-02"),
        (9, "player-02"),
        (10, "player-02"),
    ]


def test_replay_rejects_a_short_card_play_sequence() -> None:
    plays, hands = fixture_round()

    with pytest.raises(ReplayError, match="card-play count"):
        replay_round(
            plays[:-1],
            active_players=("player-01", "player-02", "player-03", "player-04"),
            first_trick_leader="player-01",
            initial_hands=hands,
        )


def test_replay_rejects_a_deck_count_violation() -> None:
    plays, hands = fixture_round()
    invalid_hands = copy.deepcopy(hands)
    invalid_hands["player-01"][0] = "SPADES_QUEEN"

    with pytest.raises(ReplayError, match="deck count"):
        replay_round(
            plays,
            active_players=("player-01", "player-02", "player-03", "player-04"),
            first_trick_leader="player-01",
            initial_hands=invalid_hands,
        )


def test_replay_rejects_a_card_that_breaks_the_following_category() -> None:
    plays, hands = fixture_round()
    invalid_plays = copy.deepcopy(plays)
    invalid_plays[5] = CardPlay(player="player-03", card="HEARTS_KING")

    with pytest.raises(ReplayError, match="following category"):
        replay_round(
            invalid_plays,
            active_players=("player-01", "player-02", "player-03", "player-04"),
            first_trick_leader="player-01",
            initial_hands=hands,
        )
