from doko_operations.pipeline_reference import PipelineReferenceDraft

from dokodetector_backend.lineage_draft_projection import project_draft


def test_projection_preserves_negative_decisions_and_pending_content() -> None:
    draft = PipelineReferenceDraft.from_mapping(
        {
            "schema_version": "pipeline-reference-draft/v2",
            "recording_id": "recording-1",
            "content_type": "events",
            "revision": 2,
            "source_revision_id": "source-1",
            "items": [
                {
                    "item_id": "e1",
                    "base_item_id": "e1",
                    "review_state": "accepted",
                    "item": {
                        "event_id": "e1",
                        "event_type": "card_state_changed",
                        "start_us": 1,
                        "end_us": 1,
                    },
                },
                {
                    "item_id": "e2",
                    "base_item_id": "e2",
                    "review_state": "rejected",
                    "item": {
                        "event_id": "e2",
                        "event_type": "card_state_changed",
                        "start_us": 2,
                        "end_us": 2,
                    },
                },
                {
                    "item_id": "e3",
                    "base_item_id": None,
                    "review_state": "pending",
                    "item": {
                        "event_id": "e3",
                        "event_type": "card_state_changed",
                        "start_us": 3,
                        "end_us": 3,
                    },
                },
            ],
            "coverage": None,
            "impact": [],
            "updated_at": "2026-11-05T10:00:00Z",
        }
    )
    projected = project_draft(draft)
    assert [event["event_id"] for event in projected["content"]["events"]] == ["e1", "e3"]
    assert projected["pointers"] == {"e1": "/events/0", "e3": "/events/1"}
    assert draft.items[1].review_state == "rejected"
    assert draft.items[1].item["event_id"] == "e2"
    assert draft.items[2].review_state == "pending"


def test_import_draft_creates_replay_safe_copy_and_preserves_review(tmp_path) -> None:
    from dokodetector_backend.lineage_draft_migration import import_draft
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    source = {
        "schema_version": "recording-video/v1",
        "recording_id": "recording-1",
        "relative_path": "data/intake/recordings/recording-1/video.mov",
        "video_sha256": "a" * 64,
        "byte_length": 100,
        "duration_us": 1000,
    }
    store = PipelineNodeStore(tmp_path)
    base = store.create(
        "base",
        "Source",
        "events",
        source,
        {
            "schema_version": "event-data/v1",
            "events": [
                {"event_id": "e1", "event_type": "card_state_changed", "start_us": 1, "end_us": 1}
            ],
        },
        {"legacy_revision_id": "legacy-1"},
        revision_id="base-revision",
    )
    draft = PipelineReferenceDraft.from_mapping(
        {
            "schema_version": "pipeline-reference-draft/v2",
            "recording_id": "recording-1",
            "content_type": "events",
            "revision": 1,
            "source_revision_id": "legacy-1",
            "items": [
                {
                    "item_id": "e1",
                    "base_item_id": "e1",
                    "review_state": "corrected",
                    "item": {
                        "event_id": "e1",
                        "event_type": "card_state_changed",
                        "start_us": 1,
                        "end_us": 1,
                    },
                }
            ],
            "coverage": {"kind": "full_recording", "intervals": [{"start_us": 0, "end_us": 1000}]},
            "impact": [],
            "updated_at": "2026-11-05T10:00:00Z",
        }
    )
    result = import_draft(store, draft, "draft-1", "base", base.revision_id)
    assert import_draft(store, draft, "draft-1", "base", base.revision_id) == result
    revision = store.read_revision(result["node_id"], result["revision_id"])
    assert revision.metadata["copied_from"] == {"node_id": "base", "revision_id": "base-revision"}
    assert revision.metadata["scene_only_frame_ids"] == []
    assert "legacy_review" not in revision.metadata
    reviews = PipelineNodeReviews(store).list_for_revision(result["node_id"], result["revision_id"])
    assert {r["kind"] for r in reviews} == {"item", "coverage"}
    assert next(r for r in reviews if r["kind"] == "item")["decision"] == "corrected"
    assert all(r["reviewer"] == {"kind": "not_recorded", "id": None} for r in reviews)


def test_review_batch_loads_its_revision_once(tmp_path, monkeypatch) -> None:
    from test_virtual_scene_data import SOURCE

    from dokodetector_backend.pipeline_item_provenance import ItemProvenanceService
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    store = PipelineNodeStore(tmp_path)
    content = {
        "schema_version": "event-data/v1",
        "events": [
            {"event_id": "e1", "event_type": "card_state_changed", "start_us": 1, "end_us": 1},
            {"event_id": "e2", "event_type": "card_state_changed", "start_us": 2, "end_us": 2},
        ],
    }
    revision = ItemProvenanceService(store).create(
        "node",
        "Events",
        "events",
        SOURCE,
        content,
        {"e1": "/events/0", "e2": "/events/1"},
        {"kind": "processor", "id": "tool"},
    )
    original = store.read_revision
    calls = []

    def read(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(store, "read_revision", read)
    reviews = PipelineNodeReviews(store)
    decisions = [
        {"review_id": item, "item_id": item, "decision": "accepted"} for item in ("e1", "e2")
    ]
    records = reviews.items(
        "node",
        revision.revision_id,
        decisions,
        "Retained decision",
        {"kind": "not_recorded", "id": None},
        {"policy": "import/v1", "source": "fixture"},
    )
    assert len(records) == 2
    assert len(calls) == 1
    assert {record["item_id"] for record in records} == {"e1", "e2"}
    assert (
        reviews.items(
            "node",
            revision.revision_id,
            decisions,
            "Retained decision",
            {"kind": "not_recorded", "id": None},
            {"policy": "import/v1", "source": "fixture"},
        )
        == records
    )


def test_project_legacy_scene_keeps_exact_geometry_and_review_facts() -> None:
    from test_virtual_scene_data import FRAME, pose, scene

    from dokodetector_backend.lineage_draft_migration import project_scene_review_facts
    from dokodetector_backend.lineage_draft_projection import project_scene_frame

    geometry = scene([pose("card-1")], ["card-1"]).to_mapping()
    frame = {
        "event_id": "frame-1",
        "frame_identity": FRAME,
        "pile_regions": [],
        "ignored_regions": [],
        "card_scene": {
            "schema_version": "reviewed-card-scene-editor/v1",
            "scene": geometry,
            "initialized_scene": geometry,
            "card_review_states": [],
            "completion_state": "complete",
            "completion_reason": None,
            "projection": {},
            "derived_region_receipt": None,
        },
    }
    result = project_scene_frame(frame)
    assert result["content"]["frames"][0]["scene"] == geometry
    assert project_scene_review_facts(frame["card_scene"])["completion_state"] == "complete"


def test_unusable_scene_with_missing_manual_geometry_stays_unavailable() -> None:
    from table_evidence_analyzer.card_scene_contract import (
        CardReviewState,
        CardSceneDraft,
        FrameReviewCompletion,
    )
    from test_virtual_scene_data import FRAME, pose, proposal, scene

    from dokodetector_backend.lineage_draft_migration import project_scene_review_facts
    from dokodetector_backend.lineage_draft_projection import project_scene_frame

    initial = scene([pose("card-1")], ["card-1"])
    prop = proposal(initial)
    states = [
        CardReviewState.create(
            card_id="card-1", source="proposal", proposal_id=prop.proposal_id, state="pending"
        ),
        CardReviewState.create(
            card_id="manual", source="manual", proposal_id=None, state="pending"
        ),
    ]
    draft = CardSceneDraft.create(
        proposal=prop,
        reviewed=None,
        card_states=states,
        completion=FrameReviewCompletion.create(
            state="unusable", unresolved_card_ids=["card-1", "manual"], reason="unusable frame"
        ),
    )
    result = project_scene_frame(
        {"event_id": "frame-1", "frame_identity": FRAME, "card_scene": draft.to_mapping()}
    )
    assert result["content"]["frames"][0]["scene"] is None
    review_facts = project_scene_review_facts(draft.to_mapping())
    assert review_facts["completion"]["state"] == "unusable"
    assert review_facts["completion"]["unresolved_card_ids"] == ["card-1", "manual"]


def test_scene_import_keeps_proposal_lineage_and_replays(tmp_path) -> None:
    from table_evidence_analyzer.card_scene_contract import (
        CardReviewState,
        CardSceneDraft,
        FrameReviewCompletion,
    )
    from table_evidence_analyzer.pipeline_data import (
        ProposedCardSceneData,
        ProposedCardSceneFrame,
        VisibleCardFrameIdentity,
    )
    from test_virtual_scene_data import FRAME, SOURCE, pose, proposal, scene

    from dokodetector_backend.lineage_draft_migration import import_draft_scenes
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    prop = proposal(scene([pose("card-1")], ["card-1"]))
    raw = ProposedCardSceneData.create(
        detector_revision_id="detector-1",
        detector_revision_digest="d" * 64,
        calibration_revision_id="calibration-1",
        calibration_digest="c" * 64,
        calibration={"value": "fixture"},
        calibration_diagnostics={"status": "pass"},
        frames=[
            ProposedCardSceneFrame(
                "frame-1",
                "b" * 64,
                "supported",
                prop,
                None,
                VisibleCardFrameIdentity.from_mapping(FRAME),
            )
        ],
    )
    store = PipelineNodeStore(tmp_path)
    store.create(
        "proposal",
        "Proposal",
        "card_scene_proposals",
        SOURCE,
        raw.to_mapping(),
        {"legacy_revision_id": "old-proposal"},
        revision_id="proposal-revision",
    )
    scene_draft = CardSceneDraft.create(
        proposal=prop,
        reviewed=None,
        card_states=[
            CardReviewState.create(
                card_id="card-1", source="proposal", proposal_id=prop.proposal_id, state="pending"
            )
        ],
        completion=FrameReviewCompletion.create(state="pending", unresolved_card_ids=["card-1"]),
    )
    draft = PipelineReferenceDraft.from_mapping(
        {
            "schema_version": "pipeline-reference-draft/v2",
            "recording_id": "recording-01",
            "content_type": "visible_cards",
            "revision": 0,
            "source_revision_id": "old-detector",
            "proposal_revision_id": "old-proposal",
            "items": [
                {
                    "item_id": "frame-1",
                    "base_item_id": None,
                    "review_state": "pending",
                    "item": {
                        "event_id": "frame-1",
                        "frame_identity": FRAME,
                        "card_scene": scene_draft.to_mapping(),
                    },
                }
            ],
            "coverage": None,
            "impact": [],
            "updated_at": "2026-11-05T10:00:00Z",
        }
    )
    result = import_draft_scenes(store, draft, "draft-1", "proposal", "proposal-revision")
    assert result == import_draft_scenes(store, draft, "draft-1", "proposal", "proposal-revision")
    revision = store.read_revision(result["node_id"], result["revision_id"])
    assert revision.metadata["copied_from"] == {
        "node_id": "proposal",
        "revision_id": "proposal-revision",
    }
    assert revision.content["frames"][0]["scene"] == prop.initialized_scene
    assert revision.metadata["migration"]["geometry_unavailable_frame_ids"] == []
    assert "legacy_scenes" not in revision.metadata
    frame_review = next(
        review
        for review in PipelineNodeReviews(store).list_for_revision(
            result["node_id"], result["revision_id"]
        )
        if review["item_id"] == "frame-1"
    )
    assert frame_review["decision"] == "pending"
    assert "card-1: pending" in frame_review["question"]


def test_staged_import_checks_snapshot_and_uses_exact_mapped_source(tmp_path) -> None:
    import hashlib
    import json

    import pytest
    from doko_operations.pipeline_data import canonical_json_bytes
    from test_virtual_scene_data import SOURCE

    from dokodetector_backend.lineage_draft_migration import (
        activate_staged_drafts,
        import_staged_drafts,
        verify_active_draft_snapshot,
        verify_staged_drafts,
    )
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    package = tmp_path / "package"
    root = tmp_path / "nodes"
    store = PipelineNodeStore(root)
    store.create(
        "source",
        "Source",
        "events",
        SOURCE,
        {"schema_version": "event-data/v1", "events": []},
        {"legacy_revision_id": "old-source", "legacy_content_schema": "event-data/v1"},
        revision_id="source-revision",
    )
    draft = {
        "schema_version": "pipeline-reference-draft/v2",
        "recording_id": "recording-01",
        "content_type": "events",
        "revision": 0,
        "source_revision_id": "old-source",
        "items": [],
        "coverage": None,
        "impact": [],
        "updated_at": "2026-11-05T10:00:00Z",
    }
    path = "pipeline-references/recording-01/events/draft.json"
    payload = canonical_json_bytes(draft)
    target = package / "evidence/operations" / path
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    state_path = "pipeline-references/recording-01/events/state.json"
    state = {
        "schema_version": "pipeline-reference-state/v1",
        "recording_id": "recording-01",
        "content_type": "events",
        "draft_revision": 0,
        "draft_state": "completed",
        "source_revision_id": "old-source",
        "selected_completed_revision_id": "old-source",
        "updated_at": "2026-11-05T10:00:00Z",
    }
    state_payload = canonical_json_bytes(state)
    (package / "evidence/operations" / state_path).write_bytes(state_payload)
    manifest = {
        "schema_version": "lineage-migration-stage/v1",
        "activation_ready": True,
        "snapshot_sha256": "a" * 64,
        "resources": [
            {
                "kind": "maintained_draft",
                "old_id": "recording-01/events",
                "old_root_id": "operations",
                "files": [
                    {"path": path, "sha256": hashlib.sha256(payload).hexdigest()},
                    {"path": state_path, "sha256": hashlib.sha256(state_payload).hexdigest()},
                ],
                "references": [
                    {
                        "old_revision_id": "old-source",
                        "target_id": "source",
                        "target_revision_id": "source-revision",
                    }
                ],
            }
        ],
    }
    (package / "migration.json").write_bytes(canonical_json_bytes(manifest))
    (root / ".legacy-revision-map.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "legacy-revision-map/v1",
                "snapshot_sha256": "a" * 64,
                "revisions": {
                    "old-source": {"node_id": "source", "revision_id": "source-revision"}
                },
            }
        )
    )
    reader_root = root / ".migrated-readers"
    (reader_root / path).parent.mkdir(parents=True)
    (reader_root / path).write_bytes(payload)
    (reader_root / state_path).write_bytes(state_payload)
    assert verify_active_draft_snapshot(package, root) == 2
    (reader_root / state_path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        verify_active_draft_snapshot(package, root)
    (reader_root / state_path).write_bytes(state_payload)
    extra = reader_root / "pipeline-references/recording-01/events/unexpected.json"
    extra.write_bytes(b"{}")
    with pytest.raises(ValueError, match="changed"):
        verify_active_draft_snapshot(package, root)
    extra.unlink()
    import shutil

    active = tmp_path / "active"
    shutil.copytree(root, active)
    assert import_staged_drafts(package, root) == {"drafts": 1, "scene_nodes": 0}
    assert import_staged_drafts(package, root) == {"drafts": 1, "scene_nodes": 0}
    assert verify_active_draft_snapshot(package, root) == 2
    assert verify_staged_drafts(package, root) == {"drafts": 1, "scene_nodes": 0, "reviews": 1}
    assert activate_staged_drafts(package, root, active) == {
        "drafts": 1,
        "scene_nodes": 0,
        "reviews": 1,
    }
    assert activate_staged_drafts(package, root, active) == {
        "drafts": 1,
        "scene_nodes": 0,
        "reviews": 1,
    }
    review_path = next((root / ".review-records").glob("*.json"))
    original_review = review_path.read_bytes()
    altered_review = json.loads(original_review)
    altered_review["decision"] = "rejected"
    review_path.write_bytes(canonical_json_bytes(altered_review))
    with pytest.raises(ValueError, match="review differs"):
        verify_staged_drafts(package, root)
    review_path.write_bytes(original_review)
    source_path = root / "source/revisions/source-revision/revision.json"
    original_source = source_path.read_bytes()
    altered_source = json.loads(original_source)
    altered_source["metadata"]["legacy_revision_id"] = "wrong-source"
    source_path.write_bytes(canonical_json_bytes(altered_source))
    with pytest.raises(ValueError, match="source identity"):
        verify_staged_drafts(package, root)
    source_path.write_bytes(original_source)
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews

    imported = next(node for node in store.list_nodes() if node.node_id != "source")
    assert (
        PipelineNodeReviews(store).list_for_revision(imported.node_id, imported.head_revision_id)[
            0
        ]["decision"]
        == "complete"
    )
    manifest["snapshot_sha256"] = "b" * 64
    (package / "migration.json").write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ValueError, match="snapshot"):
        import_staged_drafts(package, root)
    assert (
        json.loads((root / ".legacy-revision-map.json").read_bytes())["snapshot_sha256"] == "a" * 64
    )


def test_scene_only_outcome_does_not_become_an_empty_visible_frame() -> None:
    draft = PipelineReferenceDraft.from_mapping(
        {
            "schema_version": "pipeline-reference-draft/v2",
            "recording_id": "recording-1",
            "content_type": "visible_cards",
            "revision": 0,
            "source_revision_id": "old-detector",
            "proposal_revision_id": "old-proposal",
            "items": [
                {
                    "item_id": "frame-1",
                    "base_item_id": None,
                    "review_state": "pending",
                    "item": {
                        "event_id": "frame-1",
                        "frame_identity": {},
                        "status": "detected",
                        "candidates": [],
                        "ignored_regions": [],
                        "pile_regions": [],
                        "error": None,
                        "card_scene": {"schema_version": "old"},
                    },
                }
            ],
            "coverage": None,
            "impact": [],
            "updated_at": "2026-11-05T10:00:00Z",
        }
    )
    result = project_draft(draft)
    assert result["content"]["outcomes"] == []
    assert result["scene_only_items"] == ["frame-1"]
    assert draft.items[0].item["card_scene"]["schema_version"] == "old"


def test_workspace_offers_an_imported_draft_as_processor_output(tmp_path) -> None:
    from types import SimpleNamespace

    from test_virtual_scene_data import SOURCE

    from dokodetector_backend.pipeline_node_store import PipelineNodeStore
    from dokodetector_backend.pipeline_workspace_service import RecordingPipelineWorkspaceService

    store = PipelineNodeStore(tmp_path)
    content = {"schema_version": "event-data/v1", "events": []}
    store.create(
        "source",
        "Source",
        "events",
        SOURCE,
        content,
        {"legacy_revision_id": "old-source", "legacy_content_schema": "event-data/v1"},
        revision_id="source-revision",
    )
    store.create(
        "draft",
        "Imported draft",
        "events",
        SOURCE,
        content,
        {"migration": {"legacy_key": "maintained_draft/recording-01/events"}},
        revision_id="draft-revision",
    )
    service = RecordingPipelineWorkspaceService(
        recording_source_provider=lambda _: None,
        run_store=None,
        selection_store=None,
        round_analysis_store=None,
        node_store=store,
        lineage_service=SimpleNamespace(root=tmp_path / ".lineage"),
    )
    revisions = service._node_revisions_for_recording("recording-01")
    assert {r.node_id for r in revisions} == {"source", "draft"}
    draft = next(r for r in revisions if r.node_id == "draft")
    assert draft.migrated_draft is True
