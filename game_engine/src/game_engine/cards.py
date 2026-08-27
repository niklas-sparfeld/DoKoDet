"""Shared card-set and deck-manifest models for reconstruction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

CARD_SET_SCHEMA_VERSION = "card-set/v1"
DECK_MANIFEST_SCHEMA_VERSION = "deck-manifest/v1"
CARD_SET_ID = "doko-german-suited-v1"

Suit = Literal["CLUBS", "SPADES", "HEARTS", "DIAMONDS"]
Rank = Literal["NINE", "JACK", "QUEEN", "KING", "TEN", "ACE"]
CardIdentity = Annotated[
    str,
    StringConstraints(pattern=r"^(CLUBS|SPADES|HEARTS|DIAMONDS)_(NINE|JACK|QUEEN|KING|TEN|ACE)$"),
]

SUITS: tuple[Suit, ...] = ("CLUBS", "SPADES", "HEARTS", "DIAMONDS")
RANKS: tuple[Rank, ...] = ("NINE", "JACK", "QUEEN", "KING", "TEN", "ACE")
CARD_IDENTITIES: tuple[str, ...] = tuple(f"{suit}_{rank}" for suit in SUITS for rank in RANKS)
_CARD_IDENTITY_SET = frozenset(CARD_IDENTITIES)


class CardContractModel(BaseModel):
    """Immutable, closed JSON data for shared card configuration."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class CardSetManifest(CardContractModel):
    """The complete visual identity set supported by the V1 contract."""

    schema_version: Literal["card-set/v1"]
    card_set_id: Literal["doko-german-suited-v1"]
    suits: list[Suit] = Field(min_length=1)
    ranks: list[Rank] = Field(min_length=1)
    visual_identities: list[CardIdentity] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contents(self) -> CardSetManifest:
        if len(self.suits) != len(set(self.suits)):
            raise ValueError("card-set suits must be unique.")
        if len(self.ranks) != len(set(self.ranks)):
            raise ValueError("card-set ranks must be unique.")
        if len(self.visual_identities) != len(set(self.visual_identities)):
            raise ValueError("card-set visual identities must be unique.")
        if self.suits != list(SUITS) or self.ranks != list(RANKS):
            raise ValueError("card-set suits and ranks must match the shared card set.")
        if self.visual_identities != list(CARD_IDENTITIES):
            raise ValueError("card-set visual identities must match the shared card set.")
        return self


class DeckCard(CardContractModel):
    """One visual identity and its physical multiplicity in a deck."""

    card: CardIdentity
    copies: int = Field(ge=1)

    @field_validator("card")
    @classmethod
    def require_known_card(cls, value: str) -> str:
        if value not in _CARD_IDENTITY_SET:
            raise ValueError("deck card is not in the shared card set.")
        return value


class DeckManifest(CardContractModel):
    """One explicit deck variant."""

    schema_version: Literal["deck-manifest/v1"]
    deck_variant: Literal["doko-40-v1", "doko-48-v1"]
    card_set_id: Literal["doko-german-suited-v1"]
    suits: list[Suit] = Field(min_length=1)
    ranks: list[Rank] = Field(min_length=1)
    physical_copies_per_identity: int = Field(ge=1)
    cards: list[DeckCard] = Field(min_length=1)
    physical_card_count: int = Field(gt=0)
    expected_plays: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_contents(self) -> DeckManifest:
        if len(self.suits) != len(set(self.suits)):
            raise ValueError("deck suits must be unique.")
        if len(self.ranks) != len(set(self.ranks)):
            raise ValueError("deck ranks must be unique.")
        if self.suits != list(SUITS):
            raise ValueError("deck suits must match the shared card set.")
        if self.physical_copies_per_identity != 2:
            raise ValueError("the shared deck manifests must contain two physical copies.")
        if self.deck_variant == "doko-40-v1" and self.ranks != [
            "JACK",
            "QUEEN",
            "KING",
            "TEN",
            "ACE",
        ]:
            raise ValueError("doko-40-v1 must contain its five configured ranks.")
        if self.deck_variant == "doko-48-v1" and self.ranks != list(RANKS):
            raise ValueError("doko-48-v1 must contain its six configured ranks.")

        expected_cards = [f"{suit}_{rank}" for suit in self.suits for rank in self.ranks]
        actual_cards = [card.card for card in self.cards]
        if actual_cards != expected_cards:
            raise ValueError("deck cards must match the suit and rank order.")
        if any(card.copies != self.physical_copies_per_identity for card in self.cards):
            raise ValueError("each deck identity must have the configured physical multiplicity.")
        if self.physical_card_count != sum(card.copies for card in self.cards):
            raise ValueError("physical_card_count must equal the sum of card copies.")
        if self.expected_plays != self.physical_card_count:
            raise ValueError("expected_plays must equal physical_card_count.")
        if self.expected_plays % 4:
            raise ValueError("expected_plays must divide into four-card tricks.")
        return self

    @property
    def trick_count(self) -> int:
        """Return the number of four-card tricks in this manifest."""

        return self.expected_plays // 4


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_card_set(path: Path | None = None) -> CardSetManifest:
    """Load the canonical card-set fixture."""

    return _load_json_model(path or default_card_set_path(), CardSetManifest)


def load_deck_manifest(variant: str, path: Path | None = None) -> DeckManifest:
    """Load one canonical deck-manifest fixture by variant."""

    if variant not in {"doko-40-v1", "doko-48-v1"}:
        raise ValueError("unknown deck variant.")
    return _load_json_model(path or default_deck_manifest_path(variant), DeckManifest)


def default_card_set_path() -> Path:
    """Return the repository's shared card-set fixture path."""

    return _repository_root() / "fixtures" / "game-engine" / "v1" / "card-set.json"


def default_deck_manifest_path(variant: str) -> Path:
    """Return the repository's shared deck-manifest fixture path."""

    return _repository_root() / "fixtures" / "game-engine" / "v1" / "decks" / f"{variant}.json"


def _load_json_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"could not read shared card configuration: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"shared card configuration is not valid JSON: {path}") from error
    return model_type.model_validate(payload)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


__all__ = [
    "CARD_IDENTITIES",
    "CARD_SET_ID",
    "CARD_SET_SCHEMA_VERSION",
    "CardIdentity",
    "CardSetManifest",
    "DeckCard",
    "DECK_MANIFEST_SCHEMA_VERSION",
    "DeckManifest",
    "default_card_set_path",
    "default_deck_manifest_path",
    "load_card_set",
    "load_deck_manifest",
]
