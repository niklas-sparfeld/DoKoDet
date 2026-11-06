from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from doko_operations.card_plane_calibration_refinement import CalibrationRefinementError
from doko_operations.pipeline_data import RecordingVideoSource
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    ProposedCardSceneFrame,
    VisibleCardData,
)

from dokodetector_backend.calibration_refinement_service import (
    CalibrationRefinementInputError,
    CalibrationRefinementNotFound,
    CalibrationRefinementService,
)


class _DraftStore:
    def __init__(self, drafts: dict[str, SimpleNamespace]) -> None:
        self.drafts = drafts
        self.reset_ids: list[str] = []

    def load(self, recording_id: str, draft_id: str) -> SimpleNamespace:
        assert recording_id == "recording-1"
        try:
            return self.drafts[draft_id]
        except KeyError as error:
            raise CalibrationRefinementError("calibration draft is missing") from error

    def reset(self, recording_id: str, draft_id: str) -> SimpleNamespace:
        self.reset_ids.append(draft_id)
        return self.load(recording_id, draft_id)


def _service(drafts: dict[str, SimpleNamespace]) -> CalibrationRefinementService:
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.store = _DraftStore(drafts)
    source = SimpleNamespace(
        manifest=SimpleNamespace(revision_id="detector-new", content_sha256="b" * 64)
    )
    service._proposal = lambda recording_id, proposal_revision_id: (None, source, None)
    service._response = lambda recording_id, proposal_revision_id, draft, data, **kwargs: {
        "draft_id": draft.draft_id
    }
    return service


def _draft(draft_id: str, detector_revision_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        draft_id=draft_id,
        detector_revision_id=detector_revision_id,
        detector_revision_digest="b" * 64,
    )


def test_get_does_not_load_another_proposals_draft() -> None:
    old_id = "calibration-draft-proposal-old"
    service = _service({old_id: _draft(old_id, "detector-old")})
    service._proposal = Mock()

    with pytest.raises(CalibrationRefinementNotFound):
        service.get("recording-1", "proposal-new", None)

    service._proposal.assert_not_called()


def test_get_rejects_an_explicit_stale_draft() -> None:
    old_id = "calibration-draft-proposal-old"
    service = _service({old_id: _draft(old_id, "detector-old")})

    with pytest.raises(CalibrationRefinementInputError, match="different detector revision"):
        service.get("recording-1", "proposal-new", old_id)


def test_get_loads_the_current_proposals_draft() -> None:
    current_id = "calibration-draft-proposal-new"
    service = _service({current_id: _draft(current_id, "detector-new")})

    assert service.get("recording-1", "proposal-new", None) == {"draft_id": current_id}


def test_discard_does_not_reset_a_stale_draft() -> None:
    old_id = "calibration-draft-proposal-old"
    service = _service({old_id: _draft(old_id, "detector-old")})

    with pytest.raises(CalibrationRefinementInputError, match="different detector revision"):
        service.discard("recording-1", "proposal-new", old_id)

    assert service.store.reset_ids == []


def test_pending_response_does_not_calculate_calibration_preview() -> None:
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service._frame_scenes = Mock(side_effect=AssertionError("preview was calculated"))
    draft = SimpleNamespace(
        draft_id="draft-1",
        draft_digest="a" * 64,
        base_calibration_revision_id="calibration-1",
        base_calibration_digest="b" * 64,
        anchors=(),
        to_mapping=lambda: {"draft_id": "draft-1"},
    )

    response = service._response(
        "recording-1",
        "proposal-1",
        draft,
        None,
        include_frame_scenes=False,
    )

    assert response["preview_complete"] is False
    assert response["preview"]["candidate_calibration"] is None
    assert response["preview"]["failure"]["code"] == "preview_not_run"
    service._frame_scenes.assert_not_called()


def test_node_reflow_recovers_after_first_head_and_replays_exactly(tmp_path, monkeypatch) -> None:
    from dataclasses import replace
    from uuid import NAMESPACE_URL, uuid5

    from doko_operations.pipeline_data import canonical_json_bytes, sha256_bytes
    from doko_operations.pipeline_reference import PipelineReferenceDraft, PipelineReferenceState
    from test_virtual_scene_data import FRAME, HUMAN, SOURCE

    from dokodetector_backend.lineage_draft_projection import project_draft
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore
    from dokodetector_backend.pipeline_node_transactions import PipelineNodeTransactions

    recording_id = "recording-1"
    key = f"maintained_draft/{recording_id}/visible_cards"
    visible_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{key}"))
    scene_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-scenes:{key}"))
    draft = PipelineReferenceDraft.from_mapping(
        {
            "schema_version": "pipeline-reference-draft/v2",
            "recording_id": recording_id,
            "content_type": "visible_cards",
            "revision": 0,
            "source_revision_id": "source-revision",
            "items": [
                {
                    "item_id": item_id,
                    "base_item_id": item_id,
                    "review_state": "accepted",
                    "item": {
                        "event_id": item_id,
                        "frame_identity": {**FRAME, "image_sha256": digest_value},
                        "status": "empty",
                        "candidates": [],
                        "ignored_regions": [],
                        "pile_regions": [],
                        "pile_detection_status": "unsupported",
                        "error": None,
                    },
                }
                for item_id, digest_value in (("frame-1", "b" * 64), ("frame-2", "c" * 64))
            ],
            "coverage": None,
            "impact": [],
            "updated_at": "2026-11-06T10:00:00Z",
            "proposal_revision_id": "proposal-source",
        }
    )
    projection = project_draft(draft)
    digest = sha256_bytes(canonical_json_bytes(draft.to_mapping()))
    nodes = PipelineNodeStore(tmp_path / "nodes")
    visible = nodes.create(
        visible_id,
        "Imported visible-card draft",
        "visible_cards",
        SOURCE,
        projection["content"],
        {
            "migration": {"legacy_key": key, "draft_sha256": digest},
            "legacy_review": {"items": projection["legacy_items"]},
        },
        revision_id="visible-imported",
    )
    reviews = PipelineNodeReviews(nodes)
    for review_id, item_id in (
        ("unchanged-frame-review", "frame-1"),
        ("changed-frame-review", "frame-2"),
    ):
        reviews.item(
            review_id,
            visible_id,
            visible.revision_id,
            item_id,
            "frame is correct",
            "accepted",
            HUMAN,
            {"frame_sha256": "e" * 64, "policy": "calibration-frame/v1"},
        )
    reviews.overall(
        "visible-overall-review",
        visible_id,
        visible.revision_id,
        "draft complete",
        "complete",
        HUMAN,
        {"frame_sha256": "e" * 64, "policy": "calibration-frame/v1"},
    )
    scene = nodes.create(
        scene_id,
        "Imported virtual-scene draft",
        "virtual_scenes",
        SOURCE,
        {"schema_version": "virtual-scene-data/v1", "frames": []},
        {"migration": {"legacy_key": key}},
        revision_id="scene-imported",
    )
    reviews.overall(
        "scene-overall-review",
        scene_id,
        scene.revision_id,
        "scene complete",
        "complete",
        HUMAN,
        {"frame_sha256": "e" * 64, "policy": "calibration-scene/v1"},
    )
    current = SimpleNamespace(
        draft=draft,
        state=PipelineReferenceState(
            recording_id=recording_id,
            content_type="visible_cards",
            draft_revision=0,
            draft_state="draft",
            source_revision_id="source-revision",
            selected_completed_revision_id=None,
            updated_at=draft.updated_at,
        ),
    )
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.node_store = nodes
    service.node_transactions = PipelineNodeTransactions(nodes)
    reflowed_items = (
        draft.items[0],
        replace(
            draft.items[1],
            item={
                **draft.items[1].item,
                "frame_identity": {**FRAME, "image_sha256": "d" * 64},
            },
        ),
    )
    import dokodetector_backend.pipeline_node_transactions as transaction_module

    original_replace = transaction_module.atomic_replace_json

    def interrupt_before_scene_head(path, value):
        if path.parent.name == scene_id and path.name == "head.json":
            raise RuntimeError("simulated interruption after visible-card publication")
        original_replace(path, value)

    monkeypatch.setattr(transaction_module, "atomic_replace_json", interrupt_before_scene_head)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        service._publish_node_reflow(
            recording_id,
            current,
            reflowed_items,
            "proposal-target",
            "calibration-reflow-1",
        )

    monkeypatch.setattr(transaction_module, "atomic_replace_json", original_replace)
    nodes = PipelineNodeStore(tmp_path / "nodes")
    service.node_store = nodes
    service.node_transactions = PipelineNodeTransactions(nodes)

    visible_head = nodes.get(visible_id).head_revision_id
    scene_head = nodes.get(scene_id).head_revision_id
    assert visible_head != visible.revision_id
    assert scene_head != scene.revision_id
    assert (
        nodes.read_revision_record(visible_id, visible_head).parent_revision_id
        == visible.revision_id
    )
    assert nodes.read_revision_record(scene_id, scene_head).parent_revision_id == scene.revision_id
    evidence = {"frame_sha256": "e" * 64, "policy": "calibration-frame/v1"}
    assert (
        reviews.applicability("unchanged-frame-review", visible_id, visible_head, evidence)[
            "status"
        ]
        == "applicable"
    )
    assert (
        reviews.applicability("changed-frame-review", visible_id, visible_head, evidence)["status"]
        == "inapplicable"
    )
    assert (
        reviews.applicability("visible-overall-review", visible_id, visible_head, evidence)[
            "status"
        ]
        == "inapplicable"
    )
    assert (
        reviews.applicability(
            "scene-overall-review",
            scene_id,
            scene_head,
            {"frame_sha256": "e" * 64, "policy": "calibration-scene/v1"},
        )["status"]
        == "inapplicable"
    )
    reference = service._node_reflow_reference(recording_id, current, "proposal-target")
    assert reference is not None
    assert reference["draft"]["proposal_revision_id"] == "proposal-target"
    service._publish_node_reflow(
        recording_id,
        current,
        reflowed_items,
        "proposal-target",
        "calibration-reflow-1",
    )
    assert nodes.get(visible_id).head_revision_id == visible_head
    assert nodes.get(scene_id).head_revision_id == scene_head


def test_calibration_target_proposal_publishes_and_resolves_from_nodes(tmp_path) -> None:
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    source_mapping = {
        "schema_version": "recording-video/v1",
        "recording_id": "recording-1",
        "relative_path": "recordings/recording-1/video.mov",
        "video_sha256": "a" * 64,
        "byte_length": 100,
        "duration_us": 10_000_000,
    }
    source = RecordingVideoSource.from_mapping(source_mapping)
    visible = VisibleCardData.from_mapping(
        {"schema_version": "visible-card-data/v2", "outcomes": []}
    )
    nodes = PipelineNodeStore(tmp_path / "nodes")
    producer = {
        "run_id": "detector-run",
        "processor_type": "visible-card-detection",
        "implementation_id": "local-rfdetr-fine-frame/v1",
        "model_id": "local-rfdetr-fine-frame",
    }
    detector = nodes.create(
        "detector-node",
        "Detector",
        "visible_cards",
        source_mapping,
        visible.to_mapping(),
        {"origin": "processor", "producer": producer},
        revision_id="detector-revision",
    )
    proposal_data = ProposedCardSceneData.create(
        detector_revision_id=detector.revision_id,
        detector_revision_digest=detector.content_sha256,
        calibration_revision_id=None,
        calibration_digest=None,
        calibration=None,
        calibration_diagnostics={"status": "skipped", "reason": "no_card_candidates"},
        frames=(
            ProposedCardSceneFrame(
                frame_id="frame-1",
                source_frame_digest=None,
                status="unsupported",
                proposal=None,
                unsupported_reason="no detector evidence",
            ),
        ),
    )
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.node_store = nodes
    service.revision_store = Mock(side_effect=AssertionError("legacy revision store used"))
    service._publish_target_proposal_node(
        "recording-1",
        "card-scene-reflow-receipt-1",
        SimpleNamespace(manifest=SimpleNamespace(revision_id=detector.revision_id, source=source)),
        proposal_data,
        SimpleNamespace(
            calibration_revision_id="calibration-target",
            calibration_digest="b" * 64,
        ),
        "proposal-source",
    )
    service._publish_target_proposal_node(
        "recording-1",
        "card-scene-reflow-receipt-1",
        SimpleNamespace(manifest=SimpleNamespace(revision_id=detector.revision_id, source=source)),
        proposal_data,
        SimpleNamespace(
            calibration_revision_id="calibration-target",
            calibration_digest="b" * 64,
        ),
        "proposal-source",
    )

    proposal, input_revision, resolved = service._proposal(
        "recording-1", "card-scene-reflow-receipt-1"
    )

    assert proposal[1].revision_id == "card-scene-reflow-receipt-1"
    assert input_revision.manifest.revision_id == detector.revision_id
    assert input_revision.manifest.content_sha256 == detector.content_sha256
    assert resolved.data_digest == proposal_data.data_digest
    service.revision_store.assert_not_called()
    mismatched_data = ProposedCardSceneData.create(
        detector_revision_id=detector.revision_id,
        detector_revision_digest="b" * 64,
        calibration_revision_id=None,
        calibration_digest=None,
        calibration=None,
        calibration_diagnostics={"status": "skipped", "reason": "no_card_candidates"},
        frames=proposal_data.frames,
    )
    service._publish_target_proposal_node(
        "recording-1",
        "card-scene-reflow-receipt-bad",
        SimpleNamespace(manifest=SimpleNamespace(revision_id=detector.revision_id, source=source)),
        mismatched_data,
        SimpleNamespace(
            calibration_revision_id="calibration-target",
            calibration_digest="c" * 64,
        ),
        "proposal-source",
    )
    with pytest.raises(CalibrationRefinementInputError, match="detector digest"):
        service._proposal("recording-1", "card-scene-reflow-receipt-bad")


def test_reflow_planner_reads_current_content_from_canonical_node(tmp_path) -> None:
    from uuid import NAMESPACE_URL, uuid5

    from doko_operations.pipeline_data import parse_source
    from doko_operations.pipeline_reference import PipelineReferenceState

    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    source_mapping = {
        "schema_version": "recording-video/v1",
        "recording_id": "recording-1",
        "relative_path": "recordings/recording-1/video.mov",
        "video_sha256": "a" * 64,
        "byte_length": 100,
        "duration_us": 10_000_000,
    }
    key = "maintained_draft/recording-1/visible_cards"
    node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{key}"))
    state = PipelineReferenceState(
        recording_id="recording-1",
        content_type="visible_cards",
        draft_revision=3,
        draft_state="draft",
        source_revision_id="detector-node-revision",
        selected_completed_revision_id=None,
        updated_at="2026-11-06T10:00:00Z",
    )
    nodes = PipelineNodeStore(tmp_path / "nodes")
    nodes.create(
        node_id,
        "Imported visible-card draft",
        "visible_cards",
        source_mapping,
        {"schema_version": "visible-card-data/v2", "outcomes": []},
        {
            "migration": {"legacy_key": key},
            "legacy_review": {
                "items": [],
                "coverage": None,
                "impact": [],
                "scene_only_items": [],
                "state": state.to_mapping(),
            },
        },
        revision_id="visible-draft-revision",
    )
    source = SimpleNamespace(
        manifest=SimpleNamespace(
            revision_id="detector-node-revision",
            source=parse_source(source_mapping),
        )
    )
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.node_store = nodes
    service._proposal = Mock(return_value=(None, source, None))

    current = service._current_node_reference("recording-1", "source-proposal")

    assert current.state == state
    assert current.draft.revision == 3
    assert current.draft.proposal_revision_id == "source-proposal"
    assert current.draft.items == ()
    service._proposal.assert_called_once_with("recording-1", "source-proposal")
