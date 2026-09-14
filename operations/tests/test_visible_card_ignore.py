from __future__ import annotations

from table_evidence_analyzer.pipeline_data import (
    DetectorBoxGeometry,
    ReviewedIgnoreRegionGeometry,
)

from doko_operations.visible_card_ignore import geometry_is_within


def _box(x_min: int, y_min: int, x_max: int, y_max: int) -> DetectorBoxGeometry:
    return DetectorBoxGeometry(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


def _region(*polygons: tuple[tuple[int, int], ...]) -> ReviewedIgnoreRegionGeometry:
    return ReviewedIgnoreRegionGeometry(polygons=polygons)


def test_geometry_is_within_accepts_a_candidate_inside_an_ignore_region() -> None:
    assert geometry_is_within(
        _region(((100, 100), (900, 100), (900, 900), (100, 900))),
        _box(200, 200, 800, 800),
    )


def test_geometry_is_within_rejects_a_candidate_that_crosses_the_boundary() -> None:
    assert not geometry_is_within(
        _region(((100, 100), (900, 100), (900, 900), (100, 900))),
        _box(50, 200, 800, 800),
    )


def test_geometry_is_within_rejects_a_candidate_between_disconnected_regions() -> None:
    assert not geometry_is_within(
        _region(
            ((100, 100), (400, 100), (400, 900), (100, 900)),
            ((600, 100), (900, 100), (900, 900), (600, 900)),
        ),
        _box(300, 300, 700, 700),
    )
