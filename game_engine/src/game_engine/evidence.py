"""Capability-aware visual evidence scoring adapters."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

from .contract import ObservedCard

EvidenceFamily = Literal["presence", "transition", "active_area", "tracklet"]
EVIDENCE_FAMILIES: tuple[EvidenceFamily, ...] = (
    "presence",
    "transition",
    "active_area",
    "tracklet",
)


@dataclass(frozen=True, slots=True)
class VisualEvidenceWeights:
    """Weights for optional visual evidence score transforms.

    These weights rank legal branches. They are not probabilities and do not create a calibrated
    round confidence.
    """

    presence: float = 1.0
    newly_visible: float = 1.0
    predecessor: float = 1.0
    active_area: float = 1.0
    tracklet: float = 1.0

    def __post_init__(self) -> None:
        for name in ("presence", "newly_visible", "predecessor", "active_area", "tracklet"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} evidence weight must be finite and non-negative.")

    def without(self, family: EvidenceFamily) -> VisualEvidenceWeights:
        """Return these weights with one evidence family disabled."""

        if family not in EVIDENCE_FAMILIES:
            raise ValueError(f"unknown evidence family: {family}")
        if family == "presence":
            return replace(self, presence=0.0)
        if family == "transition":
            return replace(self, newly_visible=0.0, predecessor=0.0)
        if family == "active_area":
            return replace(self, active_area=0.0)
        return replace(self, tracklet=0.0)


@dataclass(frozen=True, slots=True)
class VisualEvidenceScore:
    """Weighted score contributions for one selected or ignored observed card."""

    presence: float = 0.0
    newly_visible: float = 0.0
    predecessor: float = 0.0
    active_area: float = 0.0
    tracklet: float = 0.0

    @property
    def total(self) -> float:
        """Return the total ranking contribution."""

        return (
            self.presence + self.newly_visible + self.predecessor + self.active_area + self.tracklet
        )

    def add(self, other: VisualEvidenceScore) -> VisualEvidenceScore:
        """Add two branch score contributions."""

        return VisualEvidenceScore(
            presence=self.presence + other.presence,
            newly_visible=self.newly_visible + other.newly_visible,
            predecessor=self.predecessor + other.predecessor,
            active_area=self.active_area + other.active_area,
            tracklet=self.tracklet + other.tracklet,
        )


def score_observed_card(
    card: ObservedCard,
    *,
    action: Literal["select", "ignore"],
    selected_observed_card_ids: frozenset[str] = frozenset(),
    selected_tracklet_ids: frozenset[str] = frozenset(),
    weights: VisualEvidenceWeights | None = None,
) -> VisualEvidenceScore:
    """Score one observation action while keeping unavailable fields neutral.

    Presence, newly-visible, and active-area values are centered at 0.5. Selecting a high-score
    card and ignoring a low-score card therefore receive positive contributions. A predecessor
    association favors ignoring the current card when its predecessor is already selected.
    """

    selected_weights = weights or VisualEvidenceWeights()
    direction = 1.0 if action == "select" else -1.0
    predecessor_score = max(
        (
            candidate.score
            for candidate in card.association_candidates or ()
            if candidate.observed_card_id in selected_observed_card_ids
        ),
        default=0.0,
    )
    repeated_tracklet = (
        card.card_tracklet_id is not None and card.card_tracklet_id in selected_tracklet_ids
    )
    return VisualEvidenceScore(
        presence=(
            direction * (card.presence_score - 0.5) * selected_weights.presence
            if card.presence_score is not None
            else 0.0
        ),
        newly_visible=(
            direction * (card.newly_visible_score - 0.5) * selected_weights.newly_visible
            if card.newly_visible_score is not None
            else 0.0
        ),
        predecessor=(
            (-predecessor_score if action == "select" else predecessor_score)
            * selected_weights.predecessor
        ),
        active_area=(
            direction * (card.active_area_score - 0.5) * selected_weights.active_area
            if card.active_area_score is not None
            else 0.0
        ),
        tracklet=(selected_weights.tracklet if action == "ignore" and repeated_tracklet else 0.0),
    )


__all__ = [
    "EVIDENCE_FAMILIES",
    "EvidenceFamily",
    "VisualEvidenceScore",
    "VisualEvidenceWeights",
    "score_observed_card",
]
