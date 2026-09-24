from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from doko_operations.card_plane_geometry import project_fixed_card
from doko_operations.pipeline_data import (
    DataRevision,
    ProcessorProducer,
    RecordingVideoSource,
    canonical_json_bytes,
    sha256_bytes,
)
from table_evidence_analyzer.pipeline_data import (
    VisibleCardData,
    canonical_visible_card_data_bytes,
)

from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
    ProcessorRunStore,
)
from dokodetector_backend.proposed_card_scene_pipeline_service import (
    ProposedCardScenePipelineInputError,
    ProposedCardScenePipelineService,
)

DIGEST = "a" * 64
TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)


def test_start_fails_only_interrupted_proposal_runs(tmp_path: Path) -> None:
    runs = Mock()
    runs.list_statuses.return_value = (
        SimpleNamespace(
            run_id="proposal-1", processor_type="visible-card-scene-proposal", status="running"
        ),
        SimpleNamespace(
            run_id="detector-1", processor_type="visible-card-detection", status="running"
        ),
        SimpleNamespace(
            run_id="proposal-2", processor_type="visible-card-scene-proposal", status="complete"
        ),
    )
    service = ProposedCardScenePipelineService(
        _Settings(tmp_path), revision_store=Mock(), run_store=runs, selection_store=Mock()
    )

    asyncio.run(service.start())

    assert runs.fail.call_count == 1
    assert runs.fail.call_args.args[0] == "proposal-1"
    assert runs.fail.call_args.args[1].code == "backend_restarted"
    asyncio.run(service.stop())


class _Settings:
    def __init__(self, root: Path) -> None:
        self.evidence_root = root / "runtime"
        self.operations_root = root / "operations"


def _visible_data() -> VisibleCardData:
    positions = [
        (0.0, 0.0),
        (4.0, 0.0),
        (8.0, 0.0),
        (0.0, 3.0),
        (4.0, 3.0),
        (8.0, 3.0),
        (0.0, 6.0),
        (4.0, 6.0),
        (8.0, 6.0),
        (2.0, 1.5),
        (6.0, 4.5),
        (8.0, 5.5),
    ]
    outcomes: list[dict[str, object]] = []
    for index, center in enumerate(positions):
        polygon = project_fixed_card(TABLE_TO_IMAGE, center, (index % 3) * 8.0, 1.0, 1.5)
        normalized = [
            {"x": round(float(point[0]) * 1000 / 1920), "y": round(float(point[1]) * 1000 / 1080)}
            for point in polygon
        ]
        outcomes.append(
            {
                "event_id": f"event-{index:03d}",
                "frame_identity": {
                    "schema_version": "exact-event/v1",
                    "source_video_sha256": DIGEST,
                    "requested_time_us": index * 1_000_000,
                    "frame_index": index * 30,
                    "presentation_timestamp_us": index * 1_000_000,
                    "width": 1920,
                    "height": 1080,
                    "decoder_version": "decoder/v1",
                    "transform_version": "transform/v1",
                    "output_encoding": "jpeg",
                    "content_type": "image/jpeg",
                    "image_sha256": DIGEST,
                    "policy": "exact-event/v1",
                },
                "status": "detected",
                "candidates": [
                    {
                        "card_id": f"card-{index:03d}",
                        "geometry": {
                            "kind": "visible-region/v1",
                            "visible_region": {"polygons": [normalized]},
                        },
                        "normalization": {
                            "width": 1920,
                            "height": 1080,
                            "policy_id": "full-frame-0-1000/v1",
                        },
                        "side": "unknown",
                        "model_scores": [{"producer_id": "local-rfdetr-cascade", "score": 0.98}],
                    }
                ],
                "ignored_regions": [],
                "error": None,
            }
        )
    return VisibleCardData.from_mapping(
        {"schema_version": "visible-card-data/v1", "outcomes": outcomes}
    )


def test_service_publishes_proposal_without_changing_detector_input(
    tmp_path: Path,
) -> None:
    runtime = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(runtime)
    runs = ProcessorRunStore(runtime, revision_store=revisions)
    selections = PipelineSelectionStore(runtime, revision_store=revisions, run_store=runs)
    source = RecordingVideoSource(
        recording_id="recording-0073",
        relative_path="recordings/recording-0073/video.mov",
        video_sha256=DIGEST,
        byte_length=100,
        duration_us=20_000_000,
    )
    content = _visible_data()
    input_revision = DataRevision(
        revision_id="visible-cards-001",
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=source.recording_id,
        source=source,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="detector-run-001",
            processor_type="visible-card-detection",
            implementation_id="local-rfdetr-cascade/v1",
            model_id="local-rfdetr-cascade",
        ),
        coverage={"kind": "requested-event-frames"},
        created_at="2026-09-21T10:00:00Z",
    )
    revisions.publish(input_revision, content)
    original_bytes = canonical_json_bytes(content.to_mapping())

    service = ProposedCardScenePipelineService(
        _Settings(tmp_path), revision_store=revisions, run_store=runs, selection_store=selections
    )
    started = service.start_proposal(
        source.recording_id,
        {"run_id": "proposal-run-001", "visible_card_revision_id": input_revision.revision_id},
    )
    asyncio.run(service.stop())
    result = service.get_run(source.recording_id, started.run_id)

    assert result.state.status == "complete"
    assert [run.run_id for run in service.list_runs(source.recording_id)] == [started.run_id]
    assert len(result.state.output_revision_ids) == 1
    assert result.state.terminal_failure is None
    assert result.state.progress.completed == result.state.progress.total == len(content.outcomes)
    assert result.state.metrics["activity"] == {
        "phase": "complete",
        "message": "Proposed card scenes are ready",
        "step": 3,
        "steps": 3,
    }
    assert any(
        entry["message"] == "Calibrating virtual cards"
        for entry in result.state.metrics["logs"]
    )
    assert revisions.require(result.state.output_revision_ids[0]).manifest.content_type == (
        "card_scene_proposals"
    )
    assert (
        canonical_json_bytes(revisions.require(input_revision.revision_id).content.to_mapping())
        == original_bytes
    )


def test_service_rejects_non_cascade_visible_card_revisions(tmp_path: Path) -> None:
    runtime = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(runtime)
    runs = ProcessorRunStore(runtime, revision_store=revisions)
    selections = PipelineSelectionStore(runtime, revision_store=revisions, run_store=runs)
    source = RecordingVideoSource(
        recording_id="recording-0073",
        relative_path="recordings/recording-0073/video.mov",
        video_sha256=DIGEST,
        byte_length=100,
        duration_us=20_000_000,
    )
    content = _visible_data()
    input_revision = DataRevision(
        revision_id="visible-cards-segmentation",
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=source.recording_id,
        source=source,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="detector-run-segmentation",
            processor_type="visible-card-detection",
            implementation_id="local-rfdetr-segmentation/v1",
            model_id="local-rfdetr-segmentation",
        ),
        coverage={"kind": "requested-event-frames"},
        created_at="2026-09-21T10:00:00Z",
    )
    revisions.publish(input_revision, content)
    service = ProposedCardScenePipelineService(
        _Settings(tmp_path), revision_store=revisions, run_store=runs, selection_store=selections
    )

    with pytest.raises(ProposedCardScenePipelineInputError, match="generated local cascade"):
        service.start_proposal(
            source.recording_id,
            {
                "run_id": "proposal-run-segmentation",
                "visible_card_revision_id": input_revision.revision_id,
            },
        )
    asyncio.run(service.stop())
