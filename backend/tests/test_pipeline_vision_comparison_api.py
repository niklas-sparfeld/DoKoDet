from __future__ import annotations

from pathlib import Path
from typing import Any

from app_factory import create_test_app
from doko_operations.pipeline_comparison import canonical_pipeline_comparison_bytes
from doko_operations.pipeline_data import (
    DataRevision,
    ImplementationIdentity,
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    sha256_bytes,
)
from fastapi.testclient import TestClient
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
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_store import PipelineRevisionStore, ProcessorRunStore

RECORDING_ID = "recording-vision"
SOURCE = RecordingVideoSource(
    recording_id=RECORDING_ID,
    relative_path="recordings/vision/video.mov",
    video_sha256="a" * 64,
    byte_length=100,
    duration_us=2_000_000,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=tmp_path,
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )


def _frame(time_us: int, suffix: str = "a") -> VisibleCardFrameIdentity:
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
            "image_sha256": (suffix * 64)[:64],
            "policy": "exact-event/v1",
        }
    )


def _publish(
    revisions: PipelineRevisionStore,
    revision_id: str,
    content_type: str,
    content: Any,
    *,
    origin: str = "processor",
    input_revision_ids: tuple[str, ...] = (),
    run_id: str | None = None,
) -> None:
    if content_type == "visible_cards":
        content_bytes = canonical_visible_card_data_bytes(content)
        content_schema = "visible-card-data/v1"
    else:
        content_bytes = canonical_visual_identity_data_bytes(content)
        content_schema = "visual-identity-data/v1"
    producer: Any = (
        ProcessorProducer(
            run_id=run_id or "fixture-run",
            processor_type=(
                "visible-card-detection"
                if content_type == "visible_cards"
                else "visual-card-identity"
            ),
            implementation_id="fixture.v1",
        )
        if origin == "processor"
        else {
            "kind": "human",
            "review_id": "review-1",
            "operator_id": "operator-1",
            "base_revision_id": input_revision_ids[0] if origin == "corrected" else None,
        }
    )
    if isinstance(producer, dict):
        from doko_operations.pipeline_data import HumanProducer

        producer = HumanProducer.from_mapping(producer)
    revisions.publish(
        DataRevision(
            revision_id=revision_id,
            content_type=content_type,
            content_schema=content_schema,
            recording_id=RECORDING_ID,
            source=SOURCE,
            content_sha256=sha256_bytes(content_bytes),
            input_revision_ids=input_revision_ids,
            origin=origin,
            producer=producer,
            coverage={"kind": "visible_frames", "frames": []},
            created_at="2026-09-06T10:00:00Z",
        ),
        content,
    )


def _create_run(
    runs: ProcessorRunStore,
    revisions: PipelineRevisionStore,
    *,
    run_id: str,
    revision_id: str,
    processor_type: str,
    content_type: str,
    content: Any,
    input_revision_ids: tuple[str, ...] = (),
) -> None:
    request = ProcessorRunRequest(
        run_id=run_id,
        processor_type=processor_type,
        source=SOURCE,
        input_revision_ids=input_revision_ids,
        implementation=ImplementationIdentity(name="fixture", version=run_id),
        model=None,
        configuration={"fixture": True},
        extraction_policy={"policy_id": "exact-event/v1"},
        crop_policy={"policy_id": "raw_rectangular"},
    )
    runs.create(request, created_at="2026-09-06T10:00:00Z")
    runs.start(run_id, started_at="2026-09-06T10:00:01Z")
    _publish(
        revisions,
        revision_id,
        content_type,
        content,
        run_id=run_id,
        input_revision_ids=input_revision_ids,
    )
    runs.complete(run_id, [revision_id], completed_at="2026-09-06T10:00:02Z")


def _visible_candidate(card_id: str, geometry: Any) -> VisibleCardCandidate:
    return VisibleCardCandidate(
        card_id=card_id,
        geometry=geometry,
        normalization={"width": 1_000, "height": 1_000, "policy_id": "full-frame-0-1000/v1"},
    )


def _visible_content(geometry: Any) -> VisibleCardData:
    return VisibleCardData(
        outcomes=(
            VisibleCardOutcome(
                event_id="event-1",
                frame_identity=_frame(100_000),
                status="detected",
                candidates=(_visible_candidate("card-1", geometry),),
            ),
        )
    )


def test_visible_card_comparison_route_uses_exact_frame_and_geometry_policy(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    revisions = app.state.pipeline_revision_store
    runs = app.state.pipeline_run_store
    reviewed_geometry = ReviewedVisibleRegionGeometry(
        polygons=(((100, 100), (200, 100), (200, 200), (100, 200)),)
    )
    detector_geometry = DetectorBoxGeometry(100, 100, 200, 200)
    _publish(
        revisions,
        "reference-vision",
        "visible_cards",
        _visible_content(reviewed_geometry),
        origin="manual",
    )
    _create_run(
        runs,
        revisions,
        run_id="left-vision",
        revision_id="left-vision-output",
        processor_type="visible-card-detection",
        content_type="visible_cards",
        content=_visible_content(detector_geometry),
    )
    _create_run(
        runs,
        revisions,
        run_id="right-vision",
        revision_id="right-vision-output",
        processor_type="visible-card-detection",
        content_type="visible_cards",
        content=_visible_content(detector_geometry),
    )

    payload = {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": RECORDING_ID,
        "content_type": "visible_cards",
        "left_run_id": "left-vision",
        "right_run_id": "right-vision",
        "reference_revision_id": "reference-vision",
        "matching_policy": {
            "policy_id": "visible-card-geometry/v1",
            "kind": "visible_card_geometry",
            "iou_threshold": 0.5,
            "derived_box_policy": "bounding_box",
        },
    }
    with TestClient(app) as client:
        response = client.post(f"/api/recordings/{RECORDING_ID}/pipeline/comparisons", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_type"] == "visible_cards"
    assert body["items"][0]["outcome"] == "match"
    assert body["items"][0]["iou"] == 1.0
    assert body["scope"]["common_frame_identities"]
    assert canonical_pipeline_comparison_bytes(body)


def _identity_outcome(
    card_id: str,
    identity: str,
    *,
    input_geometry: Any,
    frame: VisibleCardFrameIdentity | None = None,
) -> VisualIdentityOutcome:
    frame = frame or _frame(100_000)
    crop = VisualIdentityCropIdentity(
        status="usable",
        frame_identity=frame,
        geometry=input_geometry,
        pixel_bounds={"x_min": 1, "y_min": 1, "x_max": 10, "y_max": 10},
        crop_policy="raw_rectangular",
        output_encoding="ppm",
        content_type="image/x-portable-pixmap",
        decoder_version="decoder.v1",
        transform_version="transform.v1",
        image_sha256="b" * 64,
        unusable_reason=None,
    )
    return VisualIdentityOutcome(
        card_id=card_id,
        frame_identity=frame,
        geometry=input_geometry,
        crop_identity=crop,
        classifier=VisualIdentityClassifierIdentity(
            provider="fixture",
            implementation_name="fixture",
            implementation_version="v1",
            model_name="fixture",
            model_version="v1",
        ),
        status="classified",
        candidates=(
            VisualIdentityCandidate(
                identity=identity,
                score=None,
                score_meaning=None,
                producer_id="fixture",
            ),
        ),
    )


def test_visual_identity_comparison_route_reports_upstream_experiment(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    revisions = app.state.pipeline_revision_store
    runs = app.state.pipeline_run_store
    visible_input = _visible_content(DetectorBoxGeometry(100, 100, 200, 200))
    _publish(revisions, "visible-input-1", "visible_cards", visible_input, origin="manual")
    _publish(revisions, "visible-input-2", "visible_cards", visible_input, origin="manual")
    reference_content = VisualIdentityData(
        outcomes=(
            _identity_outcome(
                "card-1", "CLUBS_NINE", input_geometry=DetectorBoxGeometry(100, 100, 200, 200)
            ),
        )
    )
    changed_content = VisualIdentityData(
        outcomes=(
            _identity_outcome(
                "other-card", "SPADES_ACE", input_geometry=DetectorBoxGeometry(100, 100, 200, 200)
            ),
        )
    )
    _publish(
        revisions,
        "identity-reference",
        "visual_identities",
        reference_content,
        origin="corrected",
        input_revision_ids=("visible-input-1",),
    )
    _create_run(
        runs,
        revisions,
        run_id="identity-left",
        revision_id="identity-left-output",
        processor_type="visual-card-identity",
        content_type="visual_identities",
        content=reference_content,
        input_revision_ids=("visible-input-1",),
    )
    _create_run(
        runs,
        revisions,
        run_id="identity-right",
        revision_id="identity-right-output",
        processor_type="visual-card-identity",
        content_type="visual_identities",
        content=changed_content,
        input_revision_ids=("visible-input-2",),
    )
    payload = {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": RECORDING_ID,
        "content_type": "visual_identities",
        "left_run_id": "identity-left",
        "right_run_id": "identity-right",
        "reference_revision_id": "identity-reference",
        "matching_policy": {
            "policy_id": "identity-geometry/v1",
            "kind": "visual_identity_geometry",
            "iou_threshold": 0.5,
            "derived_box_policy": "bounding_box",
        },
    }
    with TestClient(app) as client:
        response = client.post(f"/api/recordings/{RECORDING_ID}/pipeline/comparisons", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "upstream_experiment"
    assert body["paired_delta"] is None
    assert {item["outcome"] for item in body["items"]} == {"match", "disagreement"}
