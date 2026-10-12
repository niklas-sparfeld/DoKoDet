from __future__ import annotations

import pytest

from doko_operations.rfdetr_pile_targets import (
    RfdetrPileTargetError,
    decode_uncompressed_rle,
    project_pile_masks,
)


def _polygon(x1: int, y1: int, x2: int, y2: int) -> list[dict[str, int]]:
    return [
        {"x": x1, "y": y1},
        {"x": x2, "y": y1},
        {"x": x2, "y": y2},
        {"x": x1, "y": y2},
    ]


def _pile(pile_id: str, polygon: list[dict[str, int]]) -> dict[str, object]:
    return {
        "pile_id": pile_id,
        "geometry": {"kind": "pile-region/v1", "polygons": [polygon]},
        "source_candidates": [],
        "grouped_candidates": [],
    }


def _card(polygon: list[dict[str, int]]) -> dict[str, object]:
    return {
        "card_id": "card-1",
        "geometry": {
            "kind": "visible-region/v1",
            "visible_region": {"polygons": [polygon]},
        },
    }


def test_pile_projection_subtracts_card_pixels_and_emits_decodable_rle() -> None:
    result = project_pile_masks(
        [_card(_polygon(0, 0, 200, 200))],
        [_pile("pile-1", _polygon(0, 0, 500, 500))],
        width=10,
        height=10,
    )[0]

    mask = decode_uncompressed_rle(result["segmentation"])
    assert result["area"] == 21
    assert int(mask.sum()) == 21
    assert not mask[:2, :2].any()
    assert result["bbox"] == [0, 0, 5, 5]
    assert result["pixel_ownership"]["card_pixels_removed"] == 4


def test_pile_projection_rejects_intersecting_piles() -> None:
    with pytest.raises(RfdetrPileTargetError, match="intersect"):
        project_pile_masks(
            [],
            [
                _pile("pile-1", _polygon(0, 0, 500, 500)),
                _pile("pile-2", _polygon(400, 400, 800, 800)),
            ],
            width=10,
            height=10,
        )


def test_pile_projection_rejects_empty_effective_footprint() -> None:
    region = _polygon(0, 0, 500, 500)
    with pytest.raises(RfdetrPileTargetError, match="empty effective footprint"):
        project_pile_masks([_card(region)], [_pile("pile-1", region)], width=10, height=10)


def test_uncompressed_rle_requires_exact_dimensions() -> None:
    with pytest.raises(RfdetrPileTargetError, match="do not match"):
        decode_uncompressed_rle({"size": [2, 2], "counts": [3]})
