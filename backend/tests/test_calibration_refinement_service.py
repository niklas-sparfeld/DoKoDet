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
from dokodetector_backend.calibration_reflow_context import build_calibration_reflow_context


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


def test_calibration_reflow_saves_new_detection_version_with_exact_parent() -> None:
    frame_identity = {"frame": "identity"}
    input_frames = [{"frame_id": "frame-1", "frame_identity": frame_identity, "detections": []}]
    input_ref = {
        "set_id": "detector-run-1",
        "version": "2",
        "content_sha256": "a" * 64,
    }
    source_set = {
        "recording_id": "recording-1",
        "content_sha256": "a" * 64,
        "source": {"source_video_sha256": "b" * 64},
        "producer": {"run_id": "run-1"},
        "event_sets": [],
        "content": {"frames": input_frames},
    }

    class DetectionSets:
        values = {("recording-1", "detector-run-1", "2"): source_set}

        def get(self, recording_id: str, set_id: str, version: str):
            return self.values.get((recording_id, set_id, version))

        def save(self, recording_id: str, **kwargs):
            result = {
                "recording_id": recording_id,
                "set_id": kwargs["set_id"],
                "version": kwargs["version"],
                "origin": kwargs["origin"],
                "producer": kwargs["producer"],
                "source": kwargs["source"],
                "event_sets": kwargs["event_sets"],
                "content": {"frames": kwargs["frames"]},
                "content_sha256": "c" * 64,
            }
            self.values[(recording_id, kwargs["set_id"], kwargs["version"])] = result
            return result

    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.detection_set_store = DetectionSets()
    source = SimpleNamespace(
        manifest=SimpleNamespace(
            revision_id="visible-cards-run-1-attempt-2",
            producer={"run_id": "run-1"},
            source=SimpleNamespace(video_sha256="b" * 64),
        ),
        content=SimpleNamespace(
            outcomes=[
                SimpleNamespace(
                    event_id="frame-1",
                    status="empty",
                    frame_identity=SimpleNamespace(to_mapping=lambda: frame_identity),
                )
            ]
        ),
    )
    receipt = SimpleNamespace(
        receipt_id="reflow-1",
        proposal_revision_id="proposal-1",
        target_calibration_revision_id="calibration-1",
    )

    with pytest.raises(CalibrationRefinementInputError, match="content digest"):
        service._resolve_calibration_detection_set(
            "recording-1", source, {**input_ref, "content_sha256": "f" * 64}
        )
    with pytest.raises(CalibrationRefinementInputError, match="must identify set"):
        service._resolve_calibration_detection_set(
            "recording-1", source, {"set_id": input_ref["set_id"], "version": "2"}
        )
    service._proposal = Mock(return_value=(None, source, None))
    service.store = Mock()
    apply_payload = {
        "draft_id": "draft-1",
        "expected_revision": 0,
        "preview_digest": "preview-1",
        "operator_id": "operator-1",
        "confirm_affected": False,
    }
    with pytest.raises(
        CalibrationRefinementInputError, match="input_detection_set_ref is required"
    ):
        service.apply("recording-1", "proposal-1", apply_payload)
    service._proposal.assert_not_called()
    with pytest.raises(CalibrationRefinementInputError, match="content digest"):
        service.apply(
            "recording-1",
            "proposal-1",
            {
                **apply_payload,
                "input_detection_set_ref": {**input_ref, "content_sha256": "f" * 64},
            },
        )
    service.store.load.assert_not_called()

    output_ref = service._publish_detection_set_reflow("recording-1", source, input_ref, receipt)
    reopened = service.detection_set_store.get(
        "recording-1", output_ref["set_id"], output_ref["version"]
    )

    assert output_ref == {
        "set_id": "calibration-reflow-reflow-1",
        "version": "1",
        "content_sha256": "c" * 64,
    }
    assert reopened["producer"]["input_detection_set_ref"] == {
        **input_ref,
    }
    assert reopened["content"]["frames"] == input_frames


def test_calibration_reflow_detection_version_reopens_from_recording_folder(tmp_path) -> None:
    import shutil
    from pathlib import Path

    from dokodetector_backend.detection_set_store import DetectionSetStore
    from dokodetector_backend.event_set_store import EventSetStore
    from dokodetector_backend.operator_corpus_import import import_recordings
    from dokodetector_backend.recording_folder_store import RecordingFolderStore

    fixture = Path(__file__).parents[2] / "fixtures/repository-bundle/v1/both"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copytree(fixture, corpus / "recording-both")
    recording_root = tmp_path / "recordings"
    import_recordings(corpus, recording_root, ("recording-both",))
    recording_store = RecordingFolderStore(recording_root)
    event_store = EventSetStore(recording_store)
    detection_store = DetectionSetStore(recording_store, event_store)
    video_digest = recording_store.get("recording-both").media["sha256"]
    frames = [
        {
            "frame_id": "frame-1",
            "frame_identity": {
                "schema_version": "exact-event/v1",
                "source_video_sha256": video_digest,
                "requested_time_us": 100,
                "frame_index": 1,
                "presentation_timestamp_us": 100,
                "width": 640,
                "height": 480,
                "decoder_version": "fixture/1",
                "transform_version": "identity/1",
                "output_encoding": "jpeg",
                "content_type": "image/jpeg",
                "image_sha256": "a" * 64,
                "policy": "exact-event/v1",
            },
            "event_ids": [],
            "detections": [
                {
                    "object_id": "card-1",
                    "kind": "visible_card",
                    "side": "unknown",
                    "segments": [
                        {
                            "segment_id": "segment-1",
                            "polygon": [
                                {"x": 10, "y": 10},
                                {"x": 30, "y": 10},
                                {"x": 30, "y": 40},
                                {"x": 10, "y": 40},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    input_set = detection_store.save(
        "recording-both",
        set_id="edited-alternative",
        version="2",
        origin="manual",
        source={"source_video_sha256": video_digest},
        producer={"editor": "operator"},
        event_sets=[],
        frames=frames,
    )
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.detection_set_store = detection_store
    source = SimpleNamespace(
        manifest=SimpleNamespace(
            revision_id="visible-cards-run-1-attempt-2",
            producer={"run_id": "run-1"},
            source=SimpleNamespace(video_sha256=video_digest),
        ),
        content=SimpleNamespace(
            outcomes=[
                SimpleNamespace(
                    event_id="frame-1",
                    status="detected",
                    frame_identity=SimpleNamespace(to_mapping=lambda: frames[0]["frame_identity"]),
                )
            ]
        ),
    )
    receipt = SimpleNamespace(
        receipt_id="reflow-persisted",
        proposal_revision_id="proposal-1",
        target_calibration_revision_id="calibration-1",
    )

    input_ref = {
        "set_id": "edited-alternative",
        "version": "2",
        "content_sha256": input_set["content_sha256"],
    }
    output_ref = service._publish_detection_set_reflow("recording-both", source, input_ref, receipt)
    restarted_store = DetectionSetStore(
        RecordingFolderStore(recording_root),
        EventSetStore(RecordingFolderStore(recording_root)),
    )
    reopened = restarted_store.get("recording-both", output_ref["set_id"], output_ref["version"])

    assert reopened is not None
    assert reopened["content"]["frames"] == frames
    assert reopened["producer"]["input_detection_set_ref"] == {
        "set_id": "edited-alternative",
        "version": "2",
        "content_sha256": input_set["content_sha256"],
    }


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
    from doko_operations.pipeline_reference import PipelineReferenceDraft
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
        {**SOURCE, "recording_id": recording_id},
        projection["content"],
        {
            "migration": {"legacy_key": key, "draft_sha256": digest},
            "calibration_reflow_context": build_calibration_reflow_context(draft),
            "scene_only_frame_ids": projection["scene_only_items"],
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
    current = draft
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.node_store = nodes
    service.node_transactions = PipelineNodeTransactions(nodes)
    source = SimpleNamespace(manifest=SimpleNamespace(revision_id="source-revision", source=SOURCE))
    service._proposal = lambda *_args: (None, source, None)
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
    node_ref = service._node_reflow_node_ref(recording_id, "proposal-target")
    assert node_ref is not None
    assert node_ref == {"node_id": visible_id, "revision_id": visible_head}
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
    from doko_operations.pipeline_reference import PipelineReferenceDraft

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
    draft = PipelineReferenceDraft.from_mapping(
        {
            "schema_version": "pipeline-reference-draft/v2",
            "recording_id": "recording-1",
            "content_type": "visible_cards",
            "revision": 3,
            "source_revision_id": "detector-node-revision",
            "proposal_revision_id": "source-proposal",
            "items": [],
            "coverage": None,
            "impact": [],
            "updated_at": "2026-11-06T10:00:00Z",
        }
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
            "calibration_reflow_context": build_calibration_reflow_context(draft),
            "scene_only_frame_ids": [],
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

    current = service._current_node_draft("recording-1", "source-proposal")

    assert current.source_revision_id == "detector-node-revision"
    assert current.revision == 3
    assert current.proposal_revision_id == "source-proposal"
    assert current.items == ()
    assert current.to_mapping()["schema_version"] == "visible-card-node-draft/v1"
    service._proposal.assert_called_once_with("recording-1", "source-proposal")


def test_visible_card_reflow_keeps_node_item_type() -> None:
    from doko_operations.card_plane_calibration_refinement import reflow_visible_card_items

    from dokodetector_backend.visible_card_node_draft import VisibleCardNodeDraftItem

    item = VisibleCardNodeDraftItem(
        item_id="frame-1",
        base_item_id="frame-1",
        review_state="accepted",
        item={"event_id": "frame-1", "status": "empty"},
    )

    reflowed, reinitialized, rebased, affected = reflow_visible_card_items(
        (item,),
        (VisibleCardNodeDraftItem("frame-1", None, "pending", item.item),),
        {},
        {},
        target_proposal_revision_id="proposal-target",
        target_proposal_data_digest="a" * 64,
    )

    assert reflowed == (item,)
    assert reinitialized == ()
    assert rebased == ()
    assert affected == ()
