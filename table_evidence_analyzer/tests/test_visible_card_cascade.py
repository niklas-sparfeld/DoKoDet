from __future__ import annotations

import math

import pytest

from table_evidence_analyzer.visible_card_cascade import (
    CASCADE_COARSE_INPUT_SIZE,
    CASCADE_COARSE_MODEL_CLASS,
    CASCADE_FINE_INPUT_SIZE,
    CASCADE_FINE_MODEL_CLASS,
    CASCADE_RFDETR_VERSION,
    CascadeContractError,
    CoarseProposal,
    CoordinateTransform,
    MappedPrediction,
    PixelBox,
    PixelPoint,
    StageBundleIdentity,
    build_cascade_layout,
    reconcile_predictions,
)


def _proposal(proposal_id: str, box: tuple[float, float, float, float], score: float = 0.9):
    return CoarseProposal(
        proposal_id=proposal_id,
        box=PixelBox(*box),
        score=score,
    )


def test_transitive_proposal_chain_forms_one_cluster() -> None:
    layout = build_cascade_layout(
        [
            _proposal("a", (10, 10, 30, 30)),
            _proposal("b", (28, 10, 48, 30)),
            _proposal("c", (46, 10, 66, 30)),
        ],
        frame_width=100,
        frame_height=80,
    )

    assert len(layout.clusters) == 1
    assert layout.clusters[0].proposal_ids == ("a", "b", "c")
    assert layout.clusters[0].source_box == PixelBox(10, 10, 66, 30)


def test_separated_proposals_get_stable_square_crops_and_edge_padding() -> None:
    layout = build_cascade_layout(
        [
            _proposal("edge", (0, 0, 8, 12)),
            _proposal("far", (70, 40, 80, 50)),
        ],
        frame_width=80,
        frame_height=60,
        model_input_size=CASCADE_FINE_INPUT_SIZE,
    )

    assert [cluster.cluster_id for cluster in layout.clusters] == ["cluster-0001", "cluster-0002"]
    edge = layout.clusters[0]
    assert edge.padded_square_box.width == edge.padded_square_box.height
    assert edge.padding.left > 0
    assert edge.padding.top > 0
    assert edge.crop_width == edge.crop_height
    assert edge.transform.source_to_model(PixelPoint(0, 0)) == PixelPoint(
        edge.padding.left * edge.transform.scale_x,
        edge.padding.top * edge.transform.scale_y,
    )


def test_no_proposals_has_no_reference_span_or_clusters() -> None:
    layout = build_cascade_layout([], frame_width=100, frame_height=80)

    assert layout.reference_span is None
    assert layout.clusters == ()


def test_coordinate_transform_round_trips_points_boxes_and_components() -> None:
    transform = CoordinateTransform(
        source_width=100,
        source_height=80,
        crop_x_min=-12,
        crop_y_min=7,
        crop_width=64,
        crop_height=64,
        model_width=432,
        model_height=432,
    )
    source_point = PixelPoint(18.25, 42.5)
    model_point = transform.source_to_model(source_point)
    restored_point = transform.model_to_source(model_point)
    assert math.isclose(restored_point.x, source_point.x)
    assert math.isclose(restored_point.y, source_point.y)

    source_box = PixelBox(18.25, 42.5, 40.75, 60.0)
    assert transform.model_to_source_box(transform.source_to_model_box(source_box)) == source_box

    components = (
        (PixelPoint(1, 2), PixelPoint(4, 2), PixelPoint(4, 5)),
        (PixelPoint(8, 9), PixelPoint(11, 9), PixelPoint(11, 12)),
    )
    assert transform.model_to_source_polygons(transform.source_to_model_polygons(components)) == (
        components
    )


def test_invalid_geometry_and_non_invertible_transform_fail_before_inference() -> None:
    with pytest.raises(CascadeContractError, match="finite"):
        build_cascade_layout(
            [_proposal("bad", (0, 0, math.inf, 10))], frame_width=100, frame_height=80
        )
    with pytest.raises(CascadeContractError, match="inside the source frame"):
        build_cascade_layout([_proposal("bad", (0, 0, 101, 10))], frame_width=100, frame_height=80)
    with pytest.raises(CascadeContractError, match="positive"):
        PixelBox(10, 10, 10, 20)
    with pytest.raises(CascadeContractError, match="positive"):
        CoordinateTransform(
            source_width=100,
            source_height=80,
            crop_x_min=0,
            crop_y_min=0,
            crop_width=0,
            crop_height=10,
            model_width=432,
            model_height=432,
        )


def _prediction(
    prediction_id: str,
    cluster_id: str,
    score: float,
    box: tuple[float, float, float, float],
    mask: set[tuple[int, int]],
    proposal_order: int = 0,
) -> MappedPrediction:
    return MappedPrediction(
        prediction_id=prediction_id,
        cluster_id=cluster_id,
        proposal_order=proposal_order,
        score=score,
        box=PixelBox(*box),
        polygons=(
            (PixelPoint(box[0], box[1]), PixelPoint(box[2], box[1]), PixelPoint(box[2], box[3])),
        ),
        mask=frozenset(mask),
    )


def test_reconciliation_requires_both_box_and_visible_mask_iou() -> None:
    duplicate = _prediction(
        "duplicate",
        "cluster-0002",
        0.8,
        (0, 0, 10, 10),
        {(x, y) for x in range(10) for y in range(10)},
    )
    stronger = _prediction(
        "stronger",
        "cluster-0001",
        0.9,
        (0, 0, 10, 10),
        {(x, y) for x in range(10) for y in range(10)},
    )
    same_box_different_mask = _prediction(
        "different-card",
        "cluster-0003",
        0.95,
        (0, 0, 10, 10),
        {(x, y) for x in range(5) for y in range(10)},
    )

    result = reconcile_predictions(
        [duplicate, stronger, same_box_different_mask], frame_width=20, frame_height=20
    )

    assert [prediction.prediction_id for prediction in result.retained] == [
        "stronger",
        "different-card",
    ]
    duplicate_decisions = [decision for decision in result.decisions if decision.duplicate]
    assert len(duplicate_decisions) == 1
    assert duplicate_decisions[0].kept_prediction_id == "stronger"
    assert duplicate_decisions[0].discarded_prediction_id == "duplicate"
    assert all(
        not decision.duplicate
        for decision in result.decisions
        if {decision.left_prediction_id, decision.right_prediction_id}
        == {"different-card", "stronger"}
    )


def test_reconciliation_ties_use_cluster_then_proposal_order() -> None:
    first = _prediction(
        "later-id",
        "cluster-0001",
        0.8,
        (0, 0, 10, 10),
        {(x, y) for x in range(10) for y in range(10)},
        1,
    )
    second = _prediction(
        "earlier-order",
        "cluster-0001",
        0.8,
        (0, 0, 10, 10),
        {(x, y) for x in range(10) for y in range(10)},
        0,
    )

    result = reconcile_predictions([first, second], frame_width=20, frame_height=20)

    assert [prediction.prediction_id for prediction in result.retained] == ["earlier-order"]


def test_stage_bundle_identity_freezes_both_model_contracts() -> None:
    coarse = StageBundleIdentity(
        stage="coarse",
        model_class=CASCADE_COARSE_MODEL_CLASS,
        input_size=CASCADE_COARSE_INPUT_SIZE,
        bundle_digest="a" * 64,
        checkpoint_sha256="b" * 64,
        device="mps",
    )
    fine = StageBundleIdentity(
        stage="fine",
        model_class=CASCADE_FINE_MODEL_CLASS,
        input_size=CASCADE_FINE_INPUT_SIZE,
        bundle_digest="c" * 64,
        checkpoint_sha256="d" * 64,
        device="mps",
    )

    assert coarse.package_version == CASCADE_RFDETR_VERSION
    assert fine.class_names == ("visible_card",)
    with pytest.raises(CascadeContractError, match="coarse stage"):
        StageBundleIdentity(
            stage="coarse",
            model_class=CASCADE_FINE_MODEL_CLASS,
            input_size=CASCADE_COARSE_INPUT_SIZE,
            bundle_digest="a" * 64,
            checkpoint_sha256="b" * 64,
            device="mps",
        )
