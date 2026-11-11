from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest
from app_factory import create_test_app
from doko_operations.pipeline_comparison_contract import canonical_pipeline_comparison_bytes
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
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_revision_store import PipelineRevisionStore
from dokodetector_backend.processor_run_store import ProcessorRunStore

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


def _frame(
    time_us: int,
    suffix: str = "a",
    **identity_changes: Any,
) -> VisibleCardFrameIdentity:
    identity = {
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
    identity.update(identity_changes)
    return VisibleCardFrameIdentity.from_mapping(identity)


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
        content_schema = "visual-identity-data/v2"
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
    manifest = DataRevision(
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
    )
    node_id = "data-" + hashlib.sha256(revision_id.encode("utf-8")).hexdigest()[:32]
    PipelineNodeStore(revisions.storage.operations_root / "pipeline-nodes").create(
        node_id,
        f"{content_type} {revision_id[:8]}",
        manifest.content_type,
        manifest.source.to_mapping(),
        content.to_mapping(),
        {
            "origin": manifest.origin,
            "input_revision_ids": list(manifest.input_revision_ids),
            "producer": manifest.producer.to_mapping(),
            "coverage": manifest.coverage,
            "data_revision": manifest.to_mapping(),
        },
        revision_id=revision_id,
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
    input_node_refs = []
    for input_revision_id in input_revision_ids:
        node, _ = runs.lineage_writer.node_store.find_revision(input_revision_id)
        input_node_refs.append(
            {
                "node_id": node.node_id,
                "revision_id": input_revision_id,
                "revision_policy": "historical",
            }
        )
    request = ProcessorRunRequest(
        run_id=run_id,
        processor_type=processor_type,
        source=SOURCE,
        input_revision_ids=input_revision_ids,
        input_node_refs=tuple(input_node_refs),
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
        side="unknown",
    )


def _visible_content(
    geometry: Any,
    *,
    frame: VisibleCardFrameIdentity | None = None,
    event_id: str = "event-1",
) -> VisibleCardData:
    return VisibleCardData(
        outcomes=(
            VisibleCardOutcome(
                event_id=event_id,
                frame_identity=frame or _frame(100_000),
                status="detected",
                candidates=(_visible_candidate("card-1", geometry),),
            ),
        )
    )


def test_visible_card_comparison_route_uses_exact_frame_and_geometry_policy(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    revisions = PipelineRevisionStore(app.state.pipeline_run_store.storage)
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
        "reference_event_set_ref": None,
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


def test_visible_card_comparison_uses_exact_saved_detection_set_reference(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    revisions = PipelineRevisionStore(app.state.pipeline_run_store.storage)
    runs = app.state.pipeline_run_store
    geometry = DetectorBoxGeometry(100, 100, 200, 200)
    for run_id in ("left-detection-alternative", "right-detection-alternative"):
        _create_run(
            runs,
            revisions,
            run_id=run_id,
            revision_id=f"{run_id}-output",
            processor_type="visible-card-detection",
            content_type="visible_cards",
            content=_visible_content(geometry),
        )
    identity = _frame(100_000)
    reference = {
        "set_id": "reviewed-alternative",
        "version": "2",
        "content_sha256": "b" * 64,
    }

    class DetectionSetFixture:
        def get(self, recording_id: str, set_id: str, version: str):
            if (recording_id, set_id, version) != (
                RECORDING_ID,
                reference["set_id"],
                reference["version"],
            ):
                return None
            return {
                "recording_id": recording_id,
                "set_id": set_id,
                "version": version,
                "origin": "manual",
                "source": {
                    "recording_id": RECORDING_ID,
                    "source_video_sha256": SOURCE.video_sha256,
                },
                "content_sha256": reference["content_sha256"],
                "content": {
                    "frames": [
                        {
                            "frame_id": "frame-1",
                            "frame_identity": identity.to_mapping(),
                            "event_ids": [{"event_id": "event-1"}],
                            "detections": [
                                {
                                    "object_id": "card-1",
                                    "kind": "visible_card",
                                    "side": "unknown",
                                    "segments": [
                                        {
                                            "segment_id": "segment-1",
                                            "polygon": [
                                                {"x": 100, "y": 100},
                                                {"x": 200, "y": 100},
                                                {"x": 200, "y": 200},
                                                {"x": 100, "y": 200},
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                },
            }

    app.state.pipeline_comparison_service.detection_set_store = DetectionSetFixture()
    payload = {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": RECORDING_ID,
        "content_type": "visible_cards",
        "left_run_id": "left-detection-alternative",
        "right_run_id": "right-detection-alternative",
        "reference_revision_id": None,
        "reference_event_set_ref": None,
        "reference_detection_set_ref": reference,
        "matching_policy": {
            "policy_id": "visible-card-geometry/v1",
            "kind": "visible_card_geometry",
            "iou_threshold": 0.5,
            "derived_box_policy": "bounding_box",
        },
    }

    result = app.state.pipeline_comparison_service.compare(RECORDING_ID, payload).to_mapping()

    assert result["reference"]["detection_set_ref"] == reference
    assert result["counts"]["left"]["matches"] == 1
    assert result["counts"]["right"]["matches"] == 1
    with pytest.raises(ValueError, match="exact digest"):
        app.state.pipeline_comparison_service.compare(
            RECORDING_ID,
            {
                **payload,
                "reference_detection_set_ref": {
                    **reference,
                    "content_sha256": "c" * 64,
                },
            },
        )


@pytest.mark.parametrize(
    ("frame_index", "requested_time_us", "presentation_timestamp_us", "image_sha256"),
    [
        (
            300,
            5_000_000,
            5_005_000,
            "bfc307c47fcb232270eed4b37b12c926bc1bd68cc192442bc660bdef88fbbcd0",
        ),
        (
            375,
            6_250_000,
            6_256_667,
            "f9a4fc3dc5f4460fa649b73882325db422544d53b739be93572fb7639805565f",
        ),
    ],
)
def test_visible_card_comparison_pairs_request_time_only_differences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frame_index: int,
    requested_time_us: int,
    presentation_timestamp_us: int,
    image_sha256: str,
) -> None:
    source_digest = "2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7"
    monkeypatch.setattr(
        sys.modules[__name__],
        "SOURCE",
        RecordingVideoSource(
            recording_id=RECORDING_ID,
            relative_path="recordings/recording-1/video.mov",
            video_sha256=source_digest,
            byte_length=158_680_194,
            duration_us=94_875_000,
        ),
    )
    app = create_test_app(_settings(tmp_path))
    revisions = PipelineRevisionStore(app.state.pipeline_run_store.storage)
    runs = app.state.pipeline_run_store
    reviewed_time_us = requested_time_us + (4_836 if frame_index == 300 else 6_044)
    reviewed_frame = _frame(
        reviewed_time_us,
        source_video_sha256=source_digest,
        frame_index=frame_index,
        presentation_timestamp_us=presentation_timestamp_us,
        image_sha256=image_sha256,
    )
    predicted_frame = _frame(
        requested_time_us,
        source_video_sha256=source_digest,
        frame_index=frame_index,
        presentation_timestamp_us=presentation_timestamp_us,
        image_sha256=image_sha256,
    )
    reviewed_geometry = ReviewedVisibleRegionGeometry(
        polygons=(((100, 100), (200, 100), (200, 200), (100, 200)),)
    )
    detector_geometry = DetectorBoxGeometry(100, 100, 200, 200)
    _publish(
        revisions,
        "reference-request-time",
        "visible_cards",
        _visible_content(reviewed_geometry, frame=reviewed_frame, event_id="review-event"),
        origin="manual",
    )
    for run_id, revision_id, event_id in (
        ("left-request-time", "left-request-time-output", "predicted-event"),
        ("right-request-time", "right-request-time-output", "predicted-event"),
    ):
        _create_run(
            runs,
            revisions,
            run_id=run_id,
            revision_id=revision_id,
            processor_type="visible-card-detection",
            content_type="visible_cards",
            content=_visible_content(detector_geometry, frame=predicted_frame, event_id=event_id),
        )

    payload = {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": RECORDING_ID,
        "content_type": "visible_cards",
        "left_run_id": "left-request-time",
        "right_run_id": "right-request-time",
        "reference_revision_id": "reference-request-time",
        "reference_event_set_ref": None,
        "matching_policy": {
            "policy_id": "visible-card-geometry/v1",
            "kind": "visible_card_geometry",
            "iou_threshold": 0.5,
            "derived_box_policy": "bounding_box",
        },
    }
    comparison = app.state.pipeline_comparison_service.compare(RECORDING_ID, payload)
    result = comparison.to_mapping()
    match = next(item for item in result["items"] if item["outcome"] == "match")

    assert result["counts"]["left"]["matches"] == 1
    assert result["scope"]["reviewed_frame_identities"] == [reviewed_frame.to_mapping()]
    assert match["reference_event_id"] == "review-event"
    assert match["run_event_id"] == "predicted-event"
    assert match["reference_frame_identity"] == reviewed_frame.to_mapping()
    assert match["run_frame_identity"] == predicted_frame.to_mapping()


@pytest.mark.parametrize(
    "change",
    [
        {"image_sha256": "b" * 64},
        {"frame_index": 101},
        {"presentation_timestamp_us": 100_001},
        {"width": 1_001},
        {"height": 1_001},
        {"decoder_version": "decoder.v2"},
        {"transform_version": "transform.v2"},
        {"output_encoding": "png"},
        {"content_type": "image/png"},
    ],
)
def test_visible_card_comparison_rejects_other_frame_identity_changes(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    app = create_test_app(_settings(tmp_path))
    revisions = PipelineRevisionStore(app.state.pipeline_run_store.storage)
    runs = app.state.pipeline_run_store
    geometry = ReviewedVisibleRegionGeometry(
        polygons=(((100, 100), (200, 100), (200, 200), (100, 200)),)
    )
    reviewed_frame = _frame(100_000)
    changed_frame = _frame(100_000, **change)
    _publish(
        revisions,
        "reference-identity-change",
        "visible_cards",
        _visible_content(geometry, frame=reviewed_frame),
        origin="manual",
    )
    for run_id in ("left-identity-change", "right-identity-change"):
        _create_run(
            runs,
            revisions,
            run_id=run_id,
            revision_id=f"{run_id}-output",
            processor_type="visible-card-detection",
            content_type="visible_cards",
            content=_visible_content(DetectorBoxGeometry(100, 100, 200, 200), frame=changed_frame),
        )
    payload = {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": RECORDING_ID,
        "content_type": "visible_cards",
        "left_run_id": "left-identity-change",
        "right_run_id": "right-identity-change",
        "reference_revision_id": "reference-identity-change",
        "reference_event_set_ref": None,
        "matching_policy": {
            "policy_id": "visible-card-geometry/v1",
            "kind": "visible_card_geometry",
            "iou_threshold": 0.5,
            "derived_box_policy": "bounding_box",
        },
    }

    result = app.state.pipeline_comparison_service.compare(RECORDING_ID, payload).to_mapping()

    assert result["counts"]["left"]["matches"] == 0
    assert result["counts"]["left"]["not_reviewed"] == 1
    assert result["items"][0]["outcome"] == "not_reviewed"


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
    revisions = PipelineRevisionStore(app.state.pipeline_run_store.storage)
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
        "reference_event_set_ref": None,
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
