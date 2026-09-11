from __future__ import annotations

from table_evidence_analyzer.pipeline_data import (
    DetectorBoxGeometry,
    ReviewedVisibleRegionGeometry,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardOutcome,
    VisualIdentityCandidate,
    VisualIdentityClassifierIdentity,
    VisualIdentityCropIdentity,
    VisualIdentityData,
    VisualIdentityOutcome,
)

from doko_operations.pipeline_comparison_contract import (
    EventMatchingPolicy,
    build_frame_comparison_scope,
)
from doko_operations.pipeline_comparison_execution import (
    compare_visible_card_data,
    compare_visual_identity_data,
    geometry_box,
    geometry_iou,
)


def _frame(time_us: int, image_suffix: str = "a") -> VisibleCardFrameIdentity:
    return VisibleCardFrameIdentity.from_mapping(
        {
            "schema_version": "exact-event/v1",
            "source_video_sha256": "a" * 64,
            "requested_time_us": time_us,
            "frame_index": time_us // 1_000,
            "presentation_timestamp_us": time_us,
            "width": 1_000,
            "height": 1_000,
            "decoder_version": "decoder.v1",
            "transform_version": "transform.v1",
            "output_encoding": "jpeg",
            "content_type": "image/jpeg",
            "image_sha256": (image_suffix * 64)[:64],
            "policy": "exact-event/v1",
        }
    )


def _box(x_min: int, y_min: int, x_max: int, y_max: int) -> DetectorBoxGeometry:
    return DetectorBoxGeometry(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


def _reviewed_box() -> ReviewedVisibleRegionGeometry:
    return ReviewedVisibleRegionGeometry(
        polygons=(
            ((100, 100), (200, 100), (200, 200), (100, 200)),
            ((300, 300), (400, 300), (400, 400), (300, 400)),
        )
    )


def _visible_candidate(card_id: str, geometry: object) -> VisibleCardCandidate:
    return VisibleCardCandidate(
        card_id=card_id,
        geometry=geometry,  # type: ignore[arg-type]
        normalization={"width": 1_000, "height": 1_000, "policy_id": "full-frame-0-1000/v1"},
        side="unknown",
    )


def _visible_outcome(
    event_id: str,
    frame: VisibleCardFrameIdentity | None,
    status: str,
    candidates: tuple[VisibleCardCandidate, ...] = (),
    error: str | None = None,
) -> VisibleCardOutcome:
    return VisibleCardOutcome(
        event_id=event_id,
        frame_identity=frame,
        status=status,  # type: ignore[arg-type]
        candidates=candidates,
        error=error,
    )


def _geometry_policy(kind: str, threshold: float = 0.5) -> EventMatchingPolicy:
    return EventMatchingPolicy(
        policy_id=f"{kind}/v1",
        iou_threshold=threshold,
        derived_box_policy="bounding_box",
        kind=kind,  # type: ignore[arg-type]
    )


def test_visible_card_comparison_uses_derived_box_and_includes_iou_boundary() -> None:
    frame = _frame(100_000)
    reference = VisibleCardData(
        outcomes=(
            _visible_outcome(
                "event-1",
                frame,
                "detected",
                (_visible_candidate("reference-card", _reviewed_box()),),
            ),
        )
    )
    run = VisibleCardData(
        outcomes=(
            _visible_outcome(
                "event-1",
                frame,
                "detected",
                (_visible_candidate("run-card", _box(100, 100, 400, 250)),),
            ),
        )
    )
    assert geometry_box(_reviewed_box()) == (100, 100, 400, 400)
    assert geometry_iou(_reviewed_box(), _box(100, 100, 400, 250)) == 0.5
    scope = build_frame_comparison_scope(
        reviewed=[frame.to_mapping()], left=[frame.to_mapping()], right=[frame.to_mapping()]
    )

    counts, metrics, items = compare_visible_card_data(
        recording_id="recording-1",
        reference=reference,
        left=run,
        right=run,
        policy=_geometry_policy("visible_card_geometry"),
        scope=scope,
    )

    assert counts["left"].matches == 1
    assert metrics["left"].precision == 1.0
    assert [item.outcome for item in items].count("match") == 2
    assert all(item.iou == 0.5 for item in items)


def test_visible_card_comparison_keeps_empty_failed_unreviewed_and_unpaired_distinct() -> None:
    reviewed_frame = _frame(100_000)
    unreviewed_frame = _frame(200_000, "b")
    missing_frame = _frame(300_000, "c")
    reference = VisibleCardData(
        outcomes=(
            _visible_outcome("empty-event", reviewed_frame, "empty"),
            _visible_outcome(
                "missing-event",
                missing_frame,
                "detected",
                (_visible_candidate("reference-card", _box(100, 100, 200, 200)),),
            ),
        )
    )
    run = VisibleCardData(
        outcomes=(
            _visible_outcome("empty-event", reviewed_frame, "empty"),
            _visible_outcome("failed-event", reviewed_frame, "failed", error="source unavailable"),
            _visible_outcome(
                "unreviewed-event",
                unreviewed_frame,
                "detected",
                (_visible_candidate("unreviewed-card", _box(600, 600, 700, 700)),),
            ),
        )
    )
    scope = build_frame_comparison_scope(
        reviewed=[reviewed_frame.to_mapping(), missing_frame.to_mapping()],
        left=[reviewed_frame.to_mapping(), unreviewed_frame.to_mapping()],
        right=[reviewed_frame.to_mapping()],
    )

    counts, metrics, items = compare_visible_card_data(
        recording_id="recording-1",
        reference=reference,
        left=run,
        right=VisibleCardData(outcomes=(run.outcomes[0],)),
        policy=_geometry_policy("visible_card_geometry"),
        scope=scope,
    )

    outcomes = {item.outcome for item in items}
    assert {"empty", "failure", "not_reviewed", "unpaired_input"} <= outcomes
    assert counts["left"].not_reviewed == 1
    assert counts["left"].failures == 1
    assert metrics["left"].precision is None


def _classifier() -> VisualIdentityClassifierIdentity:
    return VisualIdentityClassifierIdentity(
        provider="fixture",
        implementation_name="fixture-classifier",
        implementation_version="v1",
        model_name="fixture-model",
        model_version="v1",
    )


def _crop(frame: VisibleCardFrameIdentity, geometry: object) -> VisualIdentityCropIdentity:
    return VisualIdentityCropIdentity(
        status="usable",
        frame_identity=frame,
        geometry=geometry,  # type: ignore[arg-type]
        pixel_bounds={"x_min": 1, "y_min": 1, "x_max": 10, "y_max": 10},
        crop_policy="raw_rectangular",
        output_encoding="ppm",
        content_type="image/x-portable-pixmap",
        decoder_version="decoder.v1",
        transform_version="transform.v1",
        image_sha256="b" * 64,
        unusable_reason=None,
    )


def _identity_outcome(
    card_id: str,
    frame: VisibleCardFrameIdentity,
    geometry: object,
    candidates: tuple[VisualIdentityCandidate, ...],
    *,
    status: str = "classified",
    error: str | None = None,
) -> VisualIdentityOutcome:
    return VisualIdentityOutcome(
        card_id=card_id,
        frame_identity=frame,
        geometry=geometry,  # type: ignore[arg-type]
        crop_identity=None if status == "failed" else _crop(frame, geometry),  # type: ignore[arg-type]
        classifier=_classifier(),
        status=status,  # type: ignore[arg-type]
        candidates=candidates,
        error=error,
    )


def _identity(identity: str, producer_id: str = "fixture") -> VisualIdentityCandidate:
    return VisualIdentityCandidate(
        identity=identity,
        score=None,
        score_meaning=None,
        producer_id=producer_id,
    )


def test_identity_comparison_uses_exact_upstream_card_or_geometry_and_reports_disagreement() -> (
    None
):
    frame = _frame(100_000)
    reference_outcome = _identity_outcome(
        "card-1", frame, _reviewed_box(), (_identity("CLUBS_NINE"),)
    )
    exact = _identity_outcome("card-1", frame, _box(100, 100, 400, 400), (_identity("CLUBS_NINE"),))
    disagreement = _identity_outcome(
        "different-card", frame, _box(100, 100, 400, 400), (_identity("SPADES_ACE"),)
    )
    reference = VisualIdentityData(outcomes=(reference_outcome,))
    scope = build_frame_comparison_scope(
        reviewed=[frame.to_mapping()], left=[frame.to_mapping()], right=[frame.to_mapping()]
    )

    counts, _, items = compare_visual_identity_data(
        recording_id="recording-1",
        reference=reference,
        left=VisualIdentityData(outcomes=(exact,)),
        right=VisualIdentityData(outcomes=(disagreement,)),
        policy=_geometry_policy("visual_identity_geometry"),
        scope=scope,
        left_exact_upstream=True,
        right_exact_upstream=False,
    )

    assert counts["left"].matches == 1
    assert counts["right"].misses == 1
    assert {item.outcome for item in items} == {"match", "disagreement"}
    disagreement_item = next(item for item in items if item.outcome == "disagreement")
    assert disagreement_item.reference_candidates is not None
    assert disagreement_item.run_identity == "SPADES_ACE"


def test_identity_comparison_reports_empty_candidates_source_failure_and_unpaired_geometry() -> (
    None
):
    frame = _frame(100_000)
    reference = VisualIdentityData(
        outcomes=(
            _identity_outcome("card-empty", frame, _box(100, 100, 200, 200), ()),
            _identity_outcome(
                "card-unpaired", frame, _box(300, 300, 400, 400), (_identity("CLUBS_NINE"),)
            ),
        )
    )
    run = VisualIdentityData(
        outcomes=(
            _identity_outcome("card-empty", frame, _box(100, 100, 200, 200), ()),
            _identity_outcome(
                "card-unpaired-run", frame, _box(700, 700, 800, 800), (_identity("CLUBS_NINE"),)
            ),
            _identity_outcome(
                "card-failed", frame, _box(500, 500, 600, 600), (), status="failed", error="crop"
            ),
        )
    )
    scope = build_frame_comparison_scope(
        reviewed=[frame.to_mapping()], left=[frame.to_mapping()], right=[frame.to_mapping()]
    )

    _, _, items = compare_visual_identity_data(
        recording_id="recording-1",
        reference=reference,
        left=run,
        right=VisualIdentityData(outcomes=(run.outcomes[0],)),
        policy=_geometry_policy("visual_identity_geometry"),
        scope=scope,
        left_exact_upstream=False,
        right_exact_upstream=False,
    )

    assert {item.outcome for item in items} >= {"empty", "failure", "unpaired_input"}
