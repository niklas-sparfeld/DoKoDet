"""Immutable human constraints and local reconstruction handoff."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from .cards import CardIdentity, load_deck_manifest
from .contract import ContractModel, Identifier, ReconstructionInput
from .reconstruction import (
    ReconstructionResult,
    reconstruct_manual_sequence,
    reconstruct_round,
)
from .replay import ReplayError
from .rules import CardPlay

CORRECTION_SCHEMA_VERSION = "reconstruction-correction/v1"
CORRECTION_DOCUMENT_SCHEMA_VERSION = "reconstruction-corrections/v1"


class _CorrectionBase(ContractModel):
    """Provenance shared by every immutable correction constraint."""

    schema_version: Literal["reconstruction-correction/v1"]
    constraint_id: Identifier
    reviewer_id: Identifier
    created_at_ms: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=512)


class SelectIdentityCorrection(_CorrectionBase):
    """Select one visual card identity for an observed-card proposal."""

    kind: Literal["select_identity"]
    observed_card_id: Identifier
    selected_card: CardIdentity


class AssignPlayerCorrection(_CorrectionBase):
    """Assign an active player to one logical card-play slot."""

    kind: Literal["assign_player"]
    play_index: int = Field(ge=1)
    player: Identifier


class InsertCardPlayCorrection(_CorrectionBase):
    """Insert one manually reviewed card play at a logical slot."""

    kind: Literal["insert_card_play"]
    play_index: int = Field(ge=1)
    player: Identifier
    card: CardIdentity


class DeleteCardPlayCorrection(_CorrectionBase):
    """Delete one logical card-play slot from a reviewed sequence."""

    kind: Literal["delete_card_play"]
    play_index: int = Field(ge=1)


class ChangeOrderCorrection(_CorrectionBase):
    """Move one logical card play to another slot."""

    kind: Literal["change_order"]
    from_play_index: int = Field(ge=1)
    to_play_index: int = Field(ge=1)

    @model_validator(mode="after")
    def require_changed_index(self) -> ChangeOrderCorrection:
        if self.from_play_index == self.to_play_index:
            raise ValueError("change_order must move a card play to a different index.")
        return self


class MarkObservationIrrelevantCorrection(_CorrectionBase):
    """Exclude one observation from reconstruction selection."""

    kind: Literal["mark_observation_irrelevant"]
    observation_id: Identifier


class AssociateObservedCardsCorrection(_CorrectionBase):
    """Assert that two observed-card proposals refer to one visual card."""

    kind: Literal["associate_observed_cards"]
    observed_card_id: Identifier
    related_observed_card_id: Identifier

    @model_validator(mode="after")
    def require_distinct_cards(self) -> AssociateObservedCardsCorrection:
        if self.observed_card_id == self.related_observed_card_id:
            raise ValueError("associated observed-card IDs must be different.")
        return self


class SeparateObservedCardsCorrection(_CorrectionBase):
    """Assert that two observed-card proposals are separate visual cards."""

    kind: Literal["separate_observed_cards"]
    observed_card_id: Identifier
    related_observed_card_id: Identifier

    @model_validator(mode="after")
    def require_distinct_cards(self) -> SeparateObservedCardsCorrection:
        if self.observed_card_id == self.related_observed_card_id:
            raise ValueError("separated observed-card IDs must be different.")
        return self


class SetTrickBoundaryCorrection(_CorrectionBase):
    """Set a proposed trick boundary after a logical card-play slot."""

    kind: Literal["set_trick_boundary"]
    after_play_index: int = Field(ge=1)


class ManualCardPlay(ContractModel):
    """One card play in a complete manually supplied sequence."""

    player: Identifier
    card: CardIdentity


class CompleteSequenceCorrection(_CorrectionBase):
    """Replace reconstruction with one complete human-supplied card-play sequence."""

    kind: Literal["complete_sequence"]
    card_plays: tuple[ManualCardPlay, ...] = Field(min_length=1, max_length=40)


CorrectionConstraint: TypeAlias = Annotated[
    SelectIdentityCorrection
    | AssignPlayerCorrection
    | InsertCardPlayCorrection
    | DeleteCardPlayCorrection
    | ChangeOrderCorrection
    | MarkObservationIrrelevantCorrection
    | AssociateObservedCardsCorrection
    | SeparateObservedCardsCorrection
    | SetTrickBoundaryCorrection
    | CompleteSequenceCorrection,
    Field(discriminator="kind"),
]


class CorrectionDocument(ContractModel):
    """A file-based, versioned collection of immutable constraints for one round."""

    schema_version: Literal["reconstruction-corrections/v1"]
    round_id: Identifier
    constraints: tuple[CorrectionConstraint, ...] = Field(min_length=1, max_length=4096)

    @field_validator("constraints")
    @classmethod
    def require_unique_constraint_ids(
        cls, value: tuple[CorrectionConstraint, ...]
    ) -> tuple[CorrectionConstraint, ...]:
        ids = [constraint.constraint_id for constraint in value]
        if len(ids) != len(set(ids)):
            raise ValueError("correction constraint IDs must be unique.")
        return value


ConflictKind = Literal["contract_conflict", "deck_conflict", "rules_conflict"]


@dataclass(frozen=True, slots=True)
class CorrectionConflict:
    """One exact conflict that prevents a correction from becoming reviewed truth."""

    constraint_id: str
    kind: ConflictKind
    message: str


@dataclass(frozen=True, slots=True)
class ReviewedReconstruction:
    """A recomputed result that retains its source result and correction history."""

    source_result: ReconstructionResult
    result: ReconstructionResult
    constraints: tuple[CorrectionConstraint, ...]


@dataclass(frozen=True, slots=True)
class CorrectionApplication:
    """The result of applying a correction document without changing source evidence."""

    source_result: ReconstructionResult
    constraints: tuple[CorrectionConstraint, ...]
    reviewed_result: ReconstructionResult | None
    conflicts: tuple[CorrectionConflict, ...]

    @property
    def reviewed_reconstruction(self) -> ReviewedReconstruction | None:
        """Return the reviewed reconstruction when all constraints were valid."""

        if self.reviewed_result is None:
            return None
        return ReviewedReconstruction(
            source_result=self.source_result,
            result=self.reviewed_result,
            constraints=self.constraints,
        )


def apply_corrections(
    reconstruction_input: ReconstructionInput,
    correction_document: CorrectionDocument,
    *,
    source_result: ReconstructionResult | None = None,
) -> CorrectionApplication:
    """Apply constraints and recompute a result while preserving the source result and input."""

    original_result = source_result or reconstruct_round(reconstruction_input)
    constraints = correction_document.constraints
    conflicts: list[CorrectionConflict] = []
    if correction_document.round_id != reconstruction_input.round_id:
        conflicts.append(
            CorrectionConflict(
                constraint_id="document",
                kind="contract_conflict",
                message=(
                    f"correction document targets round {correction_document.round_id}, "
                    f"not {reconstruction_input.round_id}"
                ),
            )
        )
        return CorrectionApplication(original_result, constraints, None, tuple(conflicts))

    observed_cards = {
        card.observed_card_id
        for observation in reconstruction_input.observations
        for card in observation.cards
    }
    observation_ids = {
        observation.observation_id for observation in reconstruction_input.observations
    }
    selected_deck = load_deck_manifest(reconstruction_input.deck_variant)
    selected_cards = {card.card for card in selected_deck.cards}
    forced_identities: dict[str, str] = {}
    forced_players: dict[int, str] = {}
    ignored_card_ids: set[str] = set()
    complete_constraints: list[CompleteSequenceCorrection] = []
    sequence_edits: list[
        InsertCardPlayCorrection | DeleteCardPlayCorrection | ChangeOrderCorrection
    ] = []
    unsupported_constraints: list[str] = []

    for constraint in constraints:
        if isinstance(constraint, SelectIdentityCorrection):
            if constraint.observed_card_id not in observed_cards:
                conflicts.append(
                    _contract_conflict(
                        constraint,
                        f"unknown observed card {constraint.observed_card_id}",
                    )
                )
            elif constraint.selected_card not in selected_cards:
                conflicts.append(
                    CorrectionConflict(
                        constraint.constraint_id,
                        "deck_conflict",
                        f"selected card {constraint.selected_card} is outside selected deck "
                        f"{reconstruction_input.deck_variant}",
                    )
                )
            elif (
                constraint.observed_card_id in forced_identities
                and forced_identities[constraint.observed_card_id] != constraint.selected_card
            ):
                conflicts.append(
                    _contract_conflict(
                        constraint,
                        f"observed card {constraint.observed_card_id} has conflicting "
                        "selected identities",
                    )
                )
            else:
                forced_identities[constraint.observed_card_id] = constraint.selected_card
        elif isinstance(constraint, AssignPlayerCorrection):
            if constraint.player not in reconstruction_input.active_players:
                conflicts.append(
                    _rules_conflict(
                        constraint,
                        f"player {constraint.player} is not active in this round",
                    )
                )
            elif constraint.play_index > selected_deck.expected_plays:
                conflicts.append(
                    _rules_conflict(
                        constraint,
                        "card play "
                        f"{constraint.play_index} is outside the selected deck play count "
                        f"{selected_deck.expected_plays}",
                    )
                )
            elif (
                constraint.play_index in forced_players
                and forced_players[constraint.play_index] != constraint.player
            ):
                conflicts.append(
                    _contract_conflict(
                        constraint,
                        f"card play {constraint.play_index} has conflicting active players",
                    )
                )
            else:
                forced_players[constraint.play_index] = constraint.player
        elif isinstance(constraint, MarkObservationIrrelevantCorrection):
            if constraint.observation_id not in observation_ids:
                conflicts.append(
                    _contract_conflict(
                        constraint,
                        f"unknown observation {constraint.observation_id}",
                    )
                )
            else:
                ignored_card_ids.update(
                    card.observed_card_id
                    for observation in reconstruction_input.observations
                    if observation.observation_id == constraint.observation_id
                    for card in observation.cards
                )
        elif isinstance(constraint, CompleteSequenceCorrection):
            complete_constraints.append(constraint)
            for play in constraint.card_plays:
                if play.player not in reconstruction_input.active_players:
                    conflicts.append(
                        _rules_conflict(
                            constraint,
                            f"player {play.player} is not active in this round",
                        )
                    )
                if play.card not in selected_cards:
                    conflicts.append(
                        CorrectionConflict(
                            constraint.constraint_id,
                            "deck_conflict",
                            f"card {play.card} is outside selected deck "
                            f"{reconstruction_input.deck_variant}",
                        )
                    )
        elif isinstance(
            constraint,
            (InsertCardPlayCorrection, DeleteCardPlayCorrection, ChangeOrderCorrection),
        ):
            sequence_edits.append(constraint)
        elif isinstance(
            constraint, (AssociateObservedCardsCorrection, SeparateObservedCardsCorrection)
        ):
            unsupported_constraints.append(
                f"{constraint.kind} requires an association-aware reconstruction input"
            )
        elif isinstance(constraint, SetTrickBoundaryCorrection):
            conflicts.append(
                _rules_conflict(
                    constraint,
                    "doko-normal/v1 fixes trick boundaries at every four card plays",
                )
            )

    if unsupported_constraints:
        for constraint, message in zip(
            (
                constraint
                for constraint in constraints
                if isinstance(
                    constraint,
                    (AssociateObservedCardsCorrection, SeparateObservedCardsCorrection),
                )
            ),
            unsupported_constraints,
            strict=True,
        ):
            conflicts.append(_contract_conflict(constraint, message))
    if len(complete_constraints) > 1:
        conflicts.append(
            _contract_conflict(
                complete_constraints[1],
                "only one complete_sequence constraint can be applied at a time",
            )
        )
    if complete_constraints and (
        sequence_edits or forced_identities or forced_players or ignored_card_ids
    ):
        conflicts.append(
            _contract_conflict(
                complete_constraints[0],
                "complete_sequence cannot be combined with another gameplay constraint",
            )
        )
    if conflicts:
        return CorrectionApplication(original_result, constraints, None, tuple(conflicts))

    try:
        if complete_constraints:
            reviewed_result = reconstruct_manual_sequence(
                reconstruction_input,
                tuple(
                    CardPlay(play.player, play.card) for play in complete_constraints[0].card_plays
                ),
            )
        elif sequence_edits:
            reviewed_result = _apply_sequence_edits(
                reconstruction_input,
                original_result,
                sequence_edits,
            )
        else:
            reviewed_result = reconstruct_round(
                reconstruction_input,
                forced_identity_by_observed_card_id=forced_identities,
                forced_player_by_play_index=forced_players,
                ignored_observed_card_ids=ignored_card_ids,
            )
    except ReplayError as error:
        failed_constraint = complete_constraints[0] if complete_constraints else constraints[-1]
        message = str(error)
        kind: ConflictKind = "deck_conflict" if _is_deck_conflict(message) else "rules_conflict"
        conflicts.append(CorrectionConflict(failed_constraint.constraint_id, kind, message))
        return CorrectionApplication(original_result, constraints, None, tuple(conflicts))

    return CorrectionApplication(original_result, constraints, reviewed_result, ())


def parse_correction_bytes(correction_bytes: bytes) -> CorrectionDocument:
    """Parse one UTF-8 correction document from the local handoff."""

    try:
        payload = json.loads(correction_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("correction document is not valid UTF-8 JSON") from error
    try:
        return CorrectionDocument.model_validate(payload)
    except ValueError as error:
        raise ValueError(
            "correction document does not match reconstruction-corrections/v1"
        ) from error


def load_correction_document(path: Path) -> CorrectionDocument:
    """Read and validate one checked-in correction document."""

    try:
        return parse_correction_bytes(path.read_bytes())
    except OSError as error:
        raise ValueError(f"could not read correction document: {path}") from error


def _apply_sequence_edits(
    reconstruction_input: ReconstructionInput,
    source_result: ReconstructionResult,
    edits: Sequence[InsertCardPlayCorrection | DeleteCardPlayCorrection | ChangeOrderCorrection],
) -> ReconstructionResult:
    if source_result.best_hypothesis is None:
        raise ReplayError("no source hypothesis is available for a sequence correction.")
    plays = list(source_result.best_hypothesis.plays)
    expected_plays = load_deck_manifest(reconstruction_input.deck_variant).expected_plays
    for edit in edits:
        if isinstance(edit, InsertCardPlayCorrection):
            if edit.play_index > len(plays) + 1:
                raise ReplayError(f"card play insertion index {edit.play_index} is out of range.")
            plays.insert(edit.play_index - 1, CardPlay(edit.player, edit.card))
        elif isinstance(edit, DeleteCardPlayCorrection):
            if edit.play_index > len(plays):
                raise ReplayError(f"card play deletion index {edit.play_index} is out of range.")
            del plays[edit.play_index - 1]
        else:
            if edit.from_play_index > len(plays) or edit.to_play_index > len(plays):
                raise ReplayError("card-play order correction index is out of range.")
            play = plays.pop(edit.from_play_index - 1)
            plays.insert(edit.to_play_index - 1, play)
    if len(plays) != expected_plays:
        raise ReplayError(
            f"card-play count must be {expected_plays}, got {len(plays)} after correction."
        )
    return reconstruct_manual_sequence(reconstruction_input, plays)


def _contract_conflict(constraint: _CorrectionBase, message: str) -> CorrectionConflict:
    return CorrectionConflict(constraint.constraint_id, "contract_conflict", message)


def _rules_conflict(constraint: _CorrectionBase, message: str) -> CorrectionConflict:
    return CorrectionConflict(constraint.constraint_id, "rules_conflict", message)


def _is_deck_conflict(message: str) -> bool:
    return "deck" in message or "not in the selected" in message


__all__ = [
    "AssignPlayerCorrection",
    "AssociateObservedCardsCorrection",
    "ChangeOrderCorrection",
    "CompleteSequenceCorrection",
    "CORRECTION_DOCUMENT_SCHEMA_VERSION",
    "CORRECTION_SCHEMA_VERSION",
    "CorrectionApplication",
    "CorrectionConflict",
    "CorrectionConstraint",
    "CorrectionDocument",
    "DeleteCardPlayCorrection",
    "InsertCardPlayCorrection",
    "ManualCardPlay",
    "MarkObservationIrrelevantCorrection",
    "ReviewedReconstruction",
    "SelectIdentityCorrection",
    "SeparateObservedCardsCorrection",
    "SetTrickBoundaryCorrection",
    "apply_corrections",
    "load_correction_document",
    "parse_correction_bytes",
]
