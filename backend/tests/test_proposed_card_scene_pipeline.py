from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

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

from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import JobCancelled, JobManager
from dokodetector_backend.jobs_api import JobTypeRegistry
from dokodetector_backend.pipeline_lineage import PipelineLineage
from dokodetector_backend.pipeline_lineage_writer import PipelineLineageWriter
from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.pipeline_revision_store import PipelineRevisionStore
from dokodetector_backend.pipeline_storage import PipelineRuntimeStorage
from dokodetector_backend.processor_run_store import ProcessorRunStore
from dokodetector_backend.proposed_card_scene_jobs import ProposedCardSceneJobParticipant
from dokodetector_backend.proposed_card_scene_pipeline_service import (
    ProposedCardScenePipelineInputError,
    ProposedCardScenePipelineService,
)

DIGEST = "a" * 64
TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)


def test_reconcile_fails_only_interrupted_proposal_runs(tmp_path: Path) -> None:
    runs = Mock()
    runs.get.return_value = SimpleNamespace(state=SimpleNamespace(status="running"))
    service = ProposedCardScenePipelineService(
        _Settings(tmp_path), run_store=runs, selection_store=Mock()
    )

    service.reconcile_job_states(
        [
            SimpleNamespace(
                type="proposed_card_scene_creation", id="proposal-1", state="interrupted"
            ),
            SimpleNamespace(type="visible_card_detection", id="detector-1", state="interrupted"),
            SimpleNamespace(
                type="proposed_card_scene_creation", id="proposal-2", state="succeeded"
            ),
        ]
    )

    assert runs.fail.call_count == 1
    assert runs.fail.call_args.args[0] == "proposal-1"
    assert runs.fail.call_args.args[1].code == "backend_restarted"


class _Settings:
    def __init__(self, root: Path) -> None:
        self.evidence_root = root / "runtime"
        self.operations_root = root / "operations"


def _node_ref(nodes: PipelineNodeStore, revision_id: str) -> dict[str, str]:
    node, _ = nodes.find_revision(revision_id)
    return {
        "node_id": node.node_id,
        "revision_id": revision_id,
        "revision_policy": "current_head" if node.head_revision_id == revision_id else "historical",
    }


def _publish_input_node(
    tmp_path: Path,
    revisions: PipelineRevisionStore,
    runs: ProcessorRunStore,
    manifest: DataRevision,
    content: VisibleCardData,
) -> tuple[PipelineNodeStore, PipelineNodeSelectionStore]:
    nodes = PipelineNodeStore(tmp_path / "operations" / "pipeline-nodes")
    lineage = PipelineLineage(nodes)
    writer = PipelineLineageWriter(nodes, lineage, PipelineNodeUses(nodes))
    runs.lineage_writer = writer
    selections = PipelineNodeSelectionStore(nodes, writer)
    writer.publish_processor_revision(manifest, content)
    return nodes, selections


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
                        "model_scores": [{"producer_id": "local-rfdetr-fine-frame", "score": 0.98}],
                    }
                ],
                "ignored_regions": [],
                "error": None,
            }
        )
    return VisibleCardData.from_mapping(
        {"schema_version": "visible-card-data/v1", "outcomes": outcomes}
    )


class _CancellationToken:
    def check(self) -> None:
        return


class _CancelDuringProcessor(_CancellationToken):
    def __init__(self) -> None:
        self.check_count = 0

    def check(self) -> None:
        self.check_count += 1
        if self.check_count == 2:
            raise JobCancelled("cancel requested")


def _run_proposal_job(
    service: ProposedCardScenePipelineService,
    recording_id: str,
    revision_id: str,
    token: _CancellationToken | None = None,
):
    registry = JobTypeRegistry(service.settings.operations_root)
    participant = ProposedCardSceneJobParticipant(service)
    registry.register(
        "proposed_card_scene_creation",
        lambda _request: None,
        participant,
        lambda _job, _claims, _token: None,
        Claims(cpu=1),
    )
    manager = JobManager(
        service.settings.operations_root,
        registry,
        verify_publication=registry.verify_publication,
    )
    with manager:
        job = manager.accept(
            str(uuid4()),
            {
                "type": "proposed_card_scene_creation",
                "context": {"recording_id": recording_id},
                "request": {
                    "input_node_ref": _node_ref(service.node_store, revision_id),
                },
            },
        )
        job = manager.transition(job.id, "running")
        try:
            service.execute_job(job, token or _CancellationToken(), manager)
        except JobCancelled:
            manager.transition(job.id, "cancelling")
            manager.transition(job.id, "cancelled")
        return manager.get(job.id)


def test_service_publishes_proposal_without_changing_detector_input(
    tmp_path: Path,
) -> None:
    runtime = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(runtime)
    runs = ProcessorRunStore(runtime)
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
            implementation_id="local-rfdetr-fine-frame/v1",
            model_id="local-rfdetr-fine-frame",
        ),
        coverage={"kind": "requested-event-frames"},
        created_at="2026-09-21T10:00:00Z",
    )
    nodes, selections = _publish_input_node(tmp_path, revisions, runs, input_revision, content)
    original_bytes = canonical_json_bytes(content.to_mapping())

    service = ProposedCardScenePipelineService(
        _Settings(tmp_path),
        run_store=runs,
        selection_store=selections,
        node_store=nodes,
    )
    started = _run_proposal_job(service, source.recording_id, input_revision.revision_id)
    result = service.get_run(source.recording_id, started.id)

    assert result.state.status == "complete"
    assert [run.run_id for run in service.list_runs(source.recording_id)] == [started.id]
    assert started.state == "succeeded"
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
        entry["message"] == "Calibrating virtual cards" for entry in result.state.metrics["logs"]
    )
    assert (
        selections.require_processor_revision(
            result.state.output_revision_ids[0]
        ).manifest.content_type
        == "card_scene_proposals"
    )
    assert (
        canonical_json_bytes(
            selections.require_processor_revision(input_revision.revision_id).content.to_mapping()
        )
        == original_bytes
    )


def test_proposal_request_uses_exact_canonical_visible_card_node(tmp_path: Path) -> None:
    source = RecordingVideoSource(
        recording_id="recording-node-input",
        relative_path="recordings/recording-node-input/video.mov",
        video_sha256=DIGEST,
        byte_length=100,
        duration_us=10_000_000,
    )
    content = _visible_data()
    nodes = PipelineNodeStore(tmp_path / "nodes")
    producer = ProcessorProducer(
        run_id="detector-run-node",
        processor_type="visible-card-detection",
        implementation_id="local-rfdetr-fine-frame/v1",
        model_id="local-rfdetr-fine-frame",
    )
    node = nodes.create(
        "visible-node",
        "Visible cards",
        "visible_cards",
        source.to_mapping(),
        content.to_mapping(),
        {"origin": "processor", "producer": producer.to_mapping()},
        revision_id="visible-node-revision",
    )
    service = ProposedCardScenePipelineService(
        _Settings(tmp_path),
        run_store=Mock(),
        selection_store=Mock(),
        node_store=nodes,
    )

    frozen = service.freeze_job_request(
        source.recording_id,
        {
            "run_id": "proposal-node-run",
            "input_node_ref": {
                "node_id": node.node_id,
                "revision_id": node.revision_id,
                "revision_policy": "current_head",
            },
        },
    )
    service.validate_frozen_job_request(source.recording_id, frozen)
    assert frozen["processor_request"]["input_revision_ids"] == [node.revision_id]
    assert frozen["processor_request"]["input_node_ref"] == {
        "node_id": node.node_id,
        "revision_id": node.revision_id,
        "revision_policy": "current_head",
    }


def test_service_publishes_zero_card_and_pile_only_frames_without_calibration(
    tmp_path: Path,
) -> None:
    runtime = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(runtime)
    runs = ProcessorRunStore(runtime)
    source = RecordingVideoSource(
        recording_id="recording-0073",
        relative_path="recordings/recording-0073/video.mov",
        video_sha256=DIGEST,
        byte_length=100,
        duration_us=20_000_000,
    )
    mapping = _visible_data().to_mapping()
    mapping["schema_version"] = "visible-card-data/v2"
    outcomes = mapping["outcomes"]
    for index, outcome in enumerate(outcomes):
        outcome["candidates"] = []
        outcome["status"] = "detected" if index == 0 else "empty"
        outcome["pile_regions"] = []
    outcomes[0]["pile_regions"] = [
        {
            "pile_id": "pile-001",
            "geometry": {
                "kind": "pile-region/v1",
                "polygons": [
                    [
                        {"x": 100, "y": 100},
                        {"x": 300, "y": 100},
                        {"x": 300, "y": 250},
                        {"x": 100, "y": 250},
                    ]
                ],
            },
            "normalization": {
                "width": 1920,
                "height": 1080,
                "policy_id": "full-frame-0-1000/v1",
            },
            "source_candidates": [],
        }
    ]
    content = VisibleCardData.from_mapping(mapping)
    input_revision = DataRevision(
        revision_id="visible-cards-zero-only",
        content_type="visible_cards",
        content_schema="visible-card-data/v2",
        recording_id=source.recording_id,
        source=source,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="detector-run-zero-only",
            processor_type="visible-card-detection",
            implementation_id="local-rfdetr-fine-frame/v1",
            model_id="local-rfdetr-fine-frame",
        ),
        coverage={"kind": "requested-event-frames"},
        created_at="2026-09-21T10:00:00Z",
    )
    nodes, selections = _publish_input_node(tmp_path, revisions, runs, input_revision, content)
    service = ProposedCardScenePipelineService(
        _Settings(tmp_path),
        run_store=runs,
        selection_store=selections,
        node_store=nodes,
    )

    started = _run_proposal_job(service, source.recording_id, input_revision.revision_id)
    result = service.get_run(source.recording_id, started.id)

    assert result.state.status == "complete"
    assert result.state.terminal_failure is None
    assert not any(
        entry["message"] == "Calibrating virtual cards" for entry in result.state.metrics["logs"]
    )
    output_revision = selections.require_processor_revision(result.state.output_revision_ids[0])
    output = output_revision.content
    assert output_revision.manifest.producer.implementation_id == (
        "proposed-card-scene-processor/v2"
    )
    assert output_revision.manifest.coverage["no_card_frame_count"] == len(output.frames)
    assert output.calibration is None
    assert output.calibration_revision_id is None
    assert output.frames[0].status == "no_cards_detected"
    assert output.frames[0].pile_regions[0].pile_id == "pile-001"
    assert output.frames[0].source_identity is not None
    assert all(frame.status == "no_cards_detected" for frame in output.frames)


def test_cancelled_proposal_does_not_publish_a_completed_revision(tmp_path: Path) -> None:
    runtime = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(runtime)
    runs = ProcessorRunStore(runtime)
    source = RecordingVideoSource(
        recording_id="recording-cancel",
        relative_path="recordings/recording-cancel/video.mov",
        video_sha256=DIGEST,
        byte_length=100,
        duration_us=20_000_000,
    )
    content = _visible_data()
    input_revision = DataRevision(
        revision_id="visible-cards-cancel",
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=source.recording_id,
        source=source,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="detector-run-cancel",
            processor_type="visible-card-detection",
            implementation_id="local-rfdetr-fine-frame/v1",
            model_id="local-rfdetr-fine-frame",
        ),
        coverage={"kind": "requested-event-frames"},
        created_at="2026-09-21T10:00:00Z",
    )
    nodes, selections = _publish_input_node(tmp_path, revisions, runs, input_revision, content)
    service = ProposedCardScenePipelineService(
        _Settings(tmp_path),
        run_store=runs,
        selection_store=selections,
        node_store=nodes,
    )

    job = _run_proposal_job(
        service,
        source.recording_id,
        input_revision.revision_id,
        _CancelDuringProcessor(),
    )

    run = service.get_run(source.recording_id, job.id)
    assert job.state == "cancelled"
    assert run.state.status == "failed"
    assert run.state.output_revision_ids == ()
    assert not any(node.content_type == "card_scene_proposals" for node in nodes.list_nodes())


def test_service_rejects_non_local_visible_card_revisions(tmp_path: Path) -> None:
    runtime = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(runtime)
    runs = ProcessorRunStore(runtime)
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
            implementation_id="gemini/v1",
            model_id="gemini",
        ),
        coverage={"kind": "requested-event-frames"},
        created_at="2026-09-21T10:00:00Z",
    )
    nodes, selections = _publish_input_node(tmp_path, revisions, runs, input_revision, content)
    service = ProposedCardScenePipelineService(
        _Settings(tmp_path),
        run_store=runs,
        selection_store=selections,
        node_store=nodes,
    )

    with pytest.raises(ProposedCardScenePipelineInputError, match="generated local RF-DETR"):
        service.freeze_job_request(
            source.recording_id,
            {
                "run_id": "proposal-run-gemini",
                "input_node_ref": _node_ref(nodes, input_revision.revision_id),
            },
        )
