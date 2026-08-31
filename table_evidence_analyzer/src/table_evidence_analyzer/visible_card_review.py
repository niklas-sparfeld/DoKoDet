"""Reviewed visible-card geometry and identity-usability contracts.

These types separate the reviewed visible pixels from an inferred full-card extent. A derived
detector box is accepted only when it is the tight axis-aligned bounds of the reviewed region.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .visible_cards import NormalizedBox, NormalizedPoint, VisibleCardError

VISIBLE_CARD_REVIEW_SCHEMA = "visible-card-review/v2"
VISIBLE_CARD_SIDES = frozenset({"face_up", "face_down", "unknown"})
VISIBLE_CARD_FAILURE_TAGS = frozenset(
    {
        "small_card",
        "occlusion",
        "human_hand",
        "blur",
        "glare",
        "crop_boundary",
        "duplicate",
    }
)
IDENTITY_USABILITY_REASONS = frozenset(
    {
        "sufficient_identity_evidence",
        "insufficient_identity_evidence",
        "crop_contamination",
        "unknown_side",
        "occluded",
        "other",
    }
)


class VisibleCardReviewContractError(VisibleCardError, ValueError):
    """Raised when reviewed visible-card geometry or usability is invalid."""


def _polygon_area(points: tuple[NormalizedPoint, ...]) -> float:
    return abs(
        sum(
            points[index].x * points[(index + 1) % len(points)].y
            - points[(index + 1) % len(points)].x * points[index].y
            for index in range(len(points))
        )
        / 2.0
    )


def _require_identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for character in value
        )
    ):
        raise VisibleCardReviewContractError(f"{field} must be a simple non-empty identifier.")
    return value


@dataclass(frozen=True, slots=True)
class VisibleRegion:
    """One or more polygons containing only the visible pixels of one card."""

    polygons: tuple[tuple[NormalizedPoint, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.polygons, tuple) or not self.polygons:
            raise VisibleCardReviewContractError("visible_region must contain one polygon")
        for index, polygon in enumerate(self.polygons):
            if not isinstance(polygon, tuple) or len(polygon) < 3:
                raise VisibleCardReviewContractError(
                    f"visible_region polygon {index} needs at least three points"
                )
            if any(not isinstance(point, NormalizedPoint) for point in polygon):
                raise VisibleCardReviewContractError(
                    f"visible_region polygon {index} contains an invalid point"
                )
            if _polygon_area(polygon) <= 0.0:
                raise VisibleCardReviewContractError(
                    f"visible_region polygon {index} must have positive area"
                )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "polygons": [[point.to_mapping() for point in polygon] for polygon in self.polygons]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleRegion":
        if not isinstance(value, dict) or set(value) != {"polygons"}:
            raise VisibleCardReviewContractError("visible_region has unexpected fields")
        polygons_value = value["polygons"]
        if not isinstance(polygons_value, list):
            raise VisibleCardReviewContractError("visible_region.polygons must be a list")
        polygons: list[tuple[NormalizedPoint, ...]] = []
        for polygon_index, polygon_value in enumerate(polygons_value):
            if not isinstance(polygon_value, list):
                raise VisibleCardReviewContractError(
                    f"visible_region polygon {polygon_index} must be a list"
                )
            points: list[NormalizedPoint] = []
            for point_index, point_value in enumerate(polygon_value):
                if not isinstance(point_value, dict) or set(point_value) != {"x", "y"}:
                    raise VisibleCardReviewContractError(
                        f"visible_region polygon {polygon_index} point {point_index} "
                        "has unexpected fields"
                    )
                try:
                    points.append(NormalizedPoint(x=point_value["x"], y=point_value["y"]))
                except (TypeError, VisibleCardError) as error:
                    raise VisibleCardReviewContractError(
                        f"visible_region polygon {polygon_index} point {point_index} is invalid"
                    ) from error
            polygons.append(tuple(points))
        try:
            return cls(polygons=tuple(polygons))
        except (TypeError, VisibleCardError) as error:
            raise VisibleCardReviewContractError("visible_region is invalid") from error


def derive_tight_box(visible_region: VisibleRegion) -> NormalizedBox:
    """Derive one tight axis-aligned box over all visible-region polygons."""

    points = [point for polygon in visible_region.polygons for point in polygon]
    return NormalizedBox(
        y_min=min(point.y for point in points),
        x_min=min(point.x for point in points),
        y_max=max(point.y for point in points),
        x_max=max(point.x for point in points),
    )


@dataclass(frozen=True, slots=True)
class DerivedBox:
    """The detector box derived from a reviewed visible region."""

    box_2d: NormalizedBox

    def __post_init__(self) -> None:
        if not isinstance(self.box_2d, NormalizedBox):
            raise VisibleCardReviewContractError("derived_box must contain a normalized box")

    @classmethod
    def from_visible_region(cls, visible_region: VisibleRegion) -> "DerivedBox":
        return cls(box_2d=derive_tight_box(visible_region))

    def to_mapping(self) -> dict[str, int]:
        return self.box_2d.to_mapping()

    @classmethod
    def from_mapping(cls, value: Any) -> "DerivedBox":
        if not isinstance(value, dict) or set(value) != {"y_min", "x_min", "y_max", "x_max"}:
            raise VisibleCardReviewContractError("derived_box has unexpected fields")
        try:
            return cls(
                box_2d=NormalizedBox(
                    y_min=value["y_min"],
                    x_min=value["x_min"],
                    y_max=value["y_max"],
                    x_max=value["x_max"],
                )
            )
        except (TypeError, VisibleCardError) as error:
            raise VisibleCardReviewContractError("derived_box is invalid") from error


@dataclass(frozen=True, slots=True)
class IdentityUsability:
    """The review decision on whether a visible-card crop can support identity."""

    usable: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.usable, bool):
            raise VisibleCardReviewContractError("identity usability must be a boolean")
        if not isinstance(self.reason, str):
            raise VisibleCardReviewContractError("identity usability reason must be a string")
        if self.reason not in IDENTITY_USABILITY_REASONS:
            raise VisibleCardReviewContractError(
                f"identity usability reason is unknown: {self.reason!r}"
            )
        if self.usable and self.reason != "sufficient_identity_evidence":
            raise VisibleCardReviewContractError(
                "usable identity must use sufficient_identity_evidence"
            )
        if not self.usable and self.reason == "sufficient_identity_evidence":
            raise VisibleCardReviewContractError(
                "unusable identity needs a reason other than sufficient_identity_evidence"
            )

    def to_mapping(self) -> dict[str, Any]:
        return {"usable": self.usable, "reason": self.reason}

    @classmethod
    def from_mapping(cls, value: Any) -> "IdentityUsability":
        if not isinstance(value, dict) or set(value) != {"usable", "reason"}:
            raise VisibleCardReviewContractError("identity_usability has unexpected fields")
        try:
            return cls(usable=value["usable"], reason=value["reason"])
        except (TypeError, VisibleCardError) as error:
            raise VisibleCardReviewContractError("identity_usability is invalid") from error


@dataclass(frozen=True, slots=True)
class ReviewedVisibleCard:
    """Reviewed geometry and crop usability for one visible card instance."""

    card_id: str
    visible_region: VisibleRegion
    derived_box: DerivedBox
    identity_usability: IdentityUsability
    side: Literal["face_up", "face_down", "unknown"] = "unknown"
    failure_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.card_id, "card_id")
        if not isinstance(self.visible_region, VisibleRegion):
            raise VisibleCardReviewContractError("visible_region must use the review contract")
        if not isinstance(self.derived_box, DerivedBox):
            raise VisibleCardReviewContractError("derived_box must use the review contract")
        if not isinstance(self.identity_usability, IdentityUsability):
            raise VisibleCardReviewContractError("identity_usability must use the review contract")
        if self.side not in VISIBLE_CARD_SIDES:
            raise VisibleCardReviewContractError("side must be face_up, face_down, or unknown")
        if not isinstance(self.failure_tags, tuple):
            raise VisibleCardReviewContractError("failure_tags must be a tuple")
        if len(set(self.failure_tags)) != len(self.failure_tags):
            raise VisibleCardReviewContractError("failure_tags must be unique")
        if any(tag not in VISIBLE_CARD_FAILURE_TAGS for tag in self.failure_tags):
            raise VisibleCardReviewContractError("failure_tags contains an unknown tag")
        expected = derive_tight_box(self.visible_region)
        if self.derived_box.box_2d != expected:
            raise VisibleCardReviewContractError(
                "derived_box must equal the tight bounds of visible_region"
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "visible_region": self.visible_region.to_mapping(),
            "derived_box": self.derived_box.to_mapping(),
            "identity_usability": self.identity_usability.to_mapping(),
            "side": self.side,
            "failure_tags": list(self.failure_tags),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "ReviewedVisibleCard":
        fields = {
            "card_id",
            "visible_region",
            "derived_box",
            "identity_usability",
            "side",
            "failure_tags",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise VisibleCardReviewContractError("reviewed visible card has unexpected fields")
        try:
            return cls(
                card_id=value["card_id"],
                visible_region=VisibleRegion.from_mapping(value["visible_region"]),
                derived_box=DerivedBox.from_mapping(value["derived_box"]),
                identity_usability=IdentityUsability.from_mapping(value["identity_usability"]),
                side=value["side"],
                failure_tags=tuple(value["failure_tags"]),
            )
        except (TypeError, VisibleCardError) as error:
            raise VisibleCardReviewContractError("reviewed visible card is invalid") from error


def validate_reviewed_visible_card(value: Any) -> dict[str, Any]:
    """Validate and return the canonical reviewed visible-card mapping."""

    return ReviewedVisibleCard.from_mapping(value).to_mapping()


__all__ = [
    "DerivedBox",
    "VISIBLE_CARD_FAILURE_TAGS",
    "VISIBLE_CARD_SIDES",
    "IDENTITY_USABILITY_REASONS",
    "IdentityUsability",
    "VISIBLE_CARD_REVIEW_SCHEMA",
    "ReviewedVisibleCard",
    "VisibleCardReviewContractError",
    "VisibleRegion",
    "derive_tight_box",
    "validate_reviewed_visible_card",
]
