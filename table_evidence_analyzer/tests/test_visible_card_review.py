from __future__ import annotations

import pytest

from table_evidence_analyzer.visible_card_review import (
    DerivedBox,
    IdentityUsability,
    ReviewedVisibleCard,
    VisibleCardReviewContractError,
    VisibleRegion,
    derive_tight_box,
    validate_reviewed_visible_card,
)
from table_evidence_analyzer.visible_cards import NormalizedBox, NormalizedPoint


def _polygon(*points: tuple[int, int]) -> tuple[NormalizedPoint, ...]:
    return tuple(NormalizedPoint(x=x, y=y) for x, y in points)


def test_review_contract_supports_disconnected_visible_regions_and_derives_one_box() -> None:
    region = VisibleRegion(
        polygons=(
            _polygon((100, 100), (400, 100), (400, 400), (100, 400)),
            _polygon((600, 200), (800, 200), (700, 500)),
        )
    )
    reviewed = ReviewedVisibleCard(
        card_id="card-001",
        visible_region=region,
        derived_box=DerivedBox.from_visible_region(region),
        identity_usability=IdentityUsability(False, "crop_contamination"),
    )

    assert derive_tight_box(region) == NormalizedBox(x_min=100, y_min=100, x_max=800, y_max=500)
    assert ReviewedVisibleCard.from_mapping(reviewed.to_mapping()) == reviewed
    assert validate_reviewed_visible_card(reviewed.to_mapping()) == reviewed.to_mapping()


def test_review_contract_rejects_a_box_inconsistent_with_the_visible_region() -> None:
    region = VisibleRegion(polygons=(_polygon((100, 100), (400, 100), (400, 400), (100, 400)),))

    with pytest.raises(VisibleCardReviewContractError, match="tight bounds"):
        ReviewedVisibleCard(
            card_id="card-001",
            visible_region=region,
            derived_box=DerivedBox(NormalizedBox(x_min=101, y_min=100, x_max=400, y_max=400)),
            identity_usability=IdentityUsability(True, "sufficient_identity_evidence"),
        )


@pytest.mark.parametrize(
    ("usable", "reason"),
    [
        (True, "crop_contamination"),
        (False, "sufficient_identity_evidence"),
        (False, "not-a-contract-reason"),
    ],
)
def test_identity_usability_requires_one_consistent_declared_reason(
    usable: bool, reason: str
) -> None:
    with pytest.raises(VisibleCardReviewContractError):
        IdentityUsability(usable, reason)
