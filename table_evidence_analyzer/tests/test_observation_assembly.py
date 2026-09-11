from dataclasses import replace
from types import SimpleNamespace

import pytest

from table_evidence_analyzer import (
    DetectorBoxGeometry,
    ObservationAssemblyError,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardOutcome,
    VisualIdentityCandidate,
    VisualIdentityClassifierIdentity,
    VisualIdentityCropIdentity,
    VisualIdentityData,
    VisualIdentityOutcome,
    assemble_table_observations,
    canonical_table_observation_data_bytes,
    parse_table_observation_data_bytes,
)

DIGEST = "a" * 64
FRAME = VisibleCardFrameIdentity(
    source_video_sha256=DIGEST,
    requested_time_us=1_000_000,
    frame_index=10,
    presentation_timestamp_us=1_000_000,
    width=100,
    height=100,
    decoder_version="fixture-decoder/v1",
    transform_version="fixture-transform/v1",
    output_encoding="png",
    content_type="image/png",
    image_sha256=DIGEST,
)
GEOMETRY = DetectorBoxGeometry(100, 100, 900, 900)
CROP = VisualIdentityCropIdentity(
    status="usable",
    frame_identity=FRAME,
    geometry=GEOMETRY,
    pixel_bounds={"x_min": 10, "y_min": 10, "x_max": 90, "y_max": 90},
    crop_policy="raw_rectangular",
    output_encoding="ppm",
    content_type="image/x-portable-pixmap",
    decoder_version="fixture-decoder/v1",
    transform_version="fixture-transform/v1",
    image_sha256=DIGEST,
    unusable_reason=None,
)
CLASSIFIER = VisualIdentityClassifierIdentity(
    provider="fixture",
    implementation_name="fixture-assembler",
    implementation_version="v1",
    model_name="fixture-model",
    model_version="v1",
)


def _inputs() -> tuple[object, VisibleCardData, VisualIdentityData]:
    events = SimpleNamespace(
        events=(
            SimpleNamespace(
                event_id="event-01",
                event_type="card_played",
                start_us=1_000_000,
                end_us=1_100_000,
            ),
            SimpleNamespace(
                event_id="event-02",
                event_type="card_played",
                start_us=2_000_000,
                end_us=2_100_000,
            ),
        )
    )
    visible = VisibleCardData(
        outcomes=(
            VisibleCardOutcome(
                event_id="event-01",
                frame_identity=FRAME,
                status="detected",
                candidates=(
                    VisibleCardCandidate(
                        card_id="card-01",
                        geometry=GEOMETRY,
                        normalization={"width": 100, "height": 100, "policy_id": "fixture/v1"},
                        side="face_up",
                    ),
                ),
            ),
            VisibleCardOutcome(
                event_id="event-02",
                frame_identity=FRAME,
                status="empty",
                candidates=(),
            ),
        )
    )
    identities = VisualIdentityData(
        outcomes=(
            VisualIdentityOutcome(
                card_id="card-01",
                frame_identity=FRAME,
                geometry=GEOMETRY,
                crop_identity=CROP,
                classifier=CLASSIFIER,
                status="classified",
                candidates=(
                    VisualIdentityCandidate(
                        identity="HEARTS_TEN",
                        score=0.75,
                        score_meaning="probability",
                        producer_id="fixture-model-v1",
                    ),
                    VisualIdentityCandidate(
                        identity="CLUBS_NINE",
                        score=0.25,
                        score_meaning="probability",
                        producer_id="fixture-model-v1",
                    ),
                ),
            ),
        )
    )
    return events, visible, identities


def test_assembler_preserves_order_lineage_and_detected_empty_evidence() -> None:
    events, visible, identities = _inputs()

    result = assemble_table_observations(
        events,
        visible,
        identities,
        recording_id="recording-01",
        video_sha256=DIGEST,
        assembly_run_id="assembly-01",
        input_revision_ids=("events-01", "visible-01", "identity-01"),
    )

    assert [item.observed_at_ms for item in result.observations] == [1000, 2000]
    assert result.observations[0].source.package_id is None
    assert result.observations[0].source.recording_id == "recording-01"
    assert result.observations[0].source.input_revision_ids == [
        "events-01",
        "visible-01",
        "identity-01",
    ]
    assert result.observations[0].cards[0].side == "face_up"
    assert result.observations[0].cards[0].identity_candidates[0].card == "HEARTS_TEN"
    assert result.observations[1].status == "observed"
    assert result.observations[1].cards == []

    parsed = parse_table_observation_data_bytes(canonical_table_observation_data_bytes(result))
    assert parsed == result


def test_assembler_retains_classified_unusable_and_failed_proposals() -> None:
    events, visible, identities = _inputs()
    visible = VisibleCardData(
        outcomes=(
            replace(
                visible.outcomes[0],
                candidates=(
                    visible.outcomes[0].candidates[0],
                    VisibleCardCandidate(
                        card_id="card-02",
                        geometry=GEOMETRY,
                        normalization={"width": 100, "height": 100, "policy_id": "fixture/v1"},
                        side="face_down",
                    ),
                    VisibleCardCandidate(
                        card_id="card-03",
                        geometry=GEOMETRY,
                        normalization={"width": 100, "height": 100, "policy_id": "fixture/v1"},
                        side="unknown",
                    ),
                ),
            ),
            visible.outcomes[1],
        )
    )
    identities = VisualIdentityData(
        outcomes=(
            identities.outcomes[0],
            replace(
                identities.outcomes[0],
                card_id="card-02",
                status="unusable",
                candidates=(),
                unusable_reason="UNKNOWN",
                crop_identity=CROP,
            ),
            replace(
                identities.outcomes[0],
                card_id="card-03",
                status="failed",
                candidates=(),
                crop_identity=None,
                error="timeout",
            ),
        )
    )

    result = assemble_table_observations(
        events,
        visible,
        identities,
        recording_id="recording-01",
        video_sha256=DIGEST,
        assembly_run_id="assembly-mixed-01",
        input_revision_ids=("events-01", "visible-01", "identity-01"),
    )

    cards = result.observations[0].cards
    assert [card.observed_card_id for card in cards] == ["card-01", "card-02", "card-03"]
    assert [card.side for card in cards] == ["face_up", "face_down", "unknown"]
    assert [card.identity_status for card in cards] == ["classified", "unusable", "failed"]
    assert cards[1].identity_candidates == []
    assert cards[2].identity_candidates == []
    assert result.observations[0].status == "observed"
    assert result.observations[0].diagnostics["assembly"]["retained_card_count"] == 3
    assert result.observations[0].diagnostics["assembly"]["identity_details"]["card-02"] == {
        "side": "face_down",
        "status": "unusable",
        "unusable_reason": "UNKNOWN",
    }
    assert result.observations[0].diagnostics["assembly"]["identity_details"]["card-03"] == {
        "side": "unknown",
        "status": "failed",
        "error": "timeout",
    }


def test_face_down_side_forces_unusable_identity_at_assembly_boundary() -> None:
    events, visible, identities = _inputs()
    visible = VisibleCardData(
        outcomes=(
            replace(
                visible.outcomes[0],
                candidates=(replace(visible.outcomes[0].candidates[0], side="face_down"),),
            ),
            visible.outcomes[1],
        )
    )

    result = assemble_table_observations(
        events,
        visible,
        identities,
        recording_id="recording-01",
        video_sha256=DIGEST,
        assembly_run_id="assembly-face-down-01",
        input_revision_ids=("events-01", "visible-01", "identity-01"),
    )

    card = result.observations[0].cards[0]
    assert card.side == "face_down"
    assert card.identity_status == "unusable"
    assert card.identity_candidates == []


@pytest.mark.parametrize(
    "change",
    [
        "event",
        "frame",
        "geometry",
        "unknown-card",
    ],
)
def test_assembler_rejects_incompatible_lineage(change: str) -> None:
    events, visible, identities = _inputs()
    if change == "event":
        visible = VisibleCardData(
            outcomes=(
                visible.outcomes[0].__class__(
                    event_id="event-missing",
                    frame_identity=FRAME,
                    status="detected",
                    candidates=visible.outcomes[0].candidates,
                ),
            )
        )
    elif change == "frame":
        altered = replace(FRAME, frame_index=11)
        identities = VisualIdentityData(
            outcomes=(
                identities.outcomes[0].__class__(
                    card_id="card-01",
                    frame_identity=altered,
                    geometry=GEOMETRY,
                    crop_identity=None,
                    classifier=CLASSIFIER,
                    status="failed",
                    candidates=(),
                    error="fixture",
                ),
            )
        )
    elif change == "geometry":
        altered = DetectorBoxGeometry(200, 200, 900, 900)
        identities = VisualIdentityData(
            outcomes=(
                identities.outcomes[0].__class__(
                    card_id="card-01",
                    frame_identity=FRAME,
                    geometry=altered,
                    crop_identity=None,
                    classifier=CLASSIFIER,
                    status="failed",
                    candidates=(),
                    error="fixture",
                ),
            )
        )
    else:
        identities = VisualIdentityData(
            outcomes=(
                identities.outcomes[0].__class__(
                    card_id="unknown-card",
                    frame_identity=FRAME,
                    geometry=GEOMETRY,
                    crop_identity=None,
                    classifier=CLASSIFIER,
                    status="failed",
                    candidates=(),
                    error="fixture",
                ),
            )
        )

    with pytest.raises(ObservationAssemblyError):
        assemble_table_observations(
            events,
            visible,
            identities,
            recording_id="recording-01",
            video_sha256=DIGEST,
            assembly_run_id="assembly-01",
            input_revision_ids=("events-01", "visible-01", "identity-01"),
        )
