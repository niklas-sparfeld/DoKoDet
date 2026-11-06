import hashlib
from pathlib import Path

from doko_operations.pipeline_data import canonical_json_bytes

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_node_transactions import PipelineNodeTransactions

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
VISIBLE = {"schema_version": "visible-card-data/v2", "outcomes": []}
SCENES = {"schema_version": "virtual-scene-data/v1", "frames": []}


def test_coordinated_transaction_publishes_both_nodes_and_exact_selections(
    tmp_path: Path,
) -> None:
    nodes = PipelineNodeStore(tmp_path / "nodes")
    selections = PipelineNodeSelectionStore(nodes)
    visible = nodes.create("visible-node", "Visible", "visible_cards", SOURCE, VISIBLE, {})
    scenes = nodes.create("scene-node", "Scenes", "virtual_scenes", SOURCE, SCENES, {})
    visible_new = "visible-reflow-r2"
    scenes_new = "scene-reflow-r2"

    result = PipelineNodeTransactions(nodes).commit(
        "reflow-01",
        node_updates=[
            {
                "node_id": "visible-node",
                "expected_revision_id": visible.revision_id,
                "revision_id": visible_new,
                "content": VISIBLE,
                "metadata": {"calibration_reflow": "reflow-01"},
            },
            {
                "node_id": "scene-node",
                "expected_revision_id": scenes.revision_id,
                "revision_id": scenes_new,
                "content": SCENES,
                "metadata": {"calibration_reflow": "reflow-01"},
            },
        ],
        selection_updates=[
            {
                "recording_id": "recording-01",
                "content_type": "visible_cards",
                "expected_revision": 0,
                "selected_generated": {"node_id": "visible-node", "revision_id": visible_new},
                "selected_completed_reference": None,
            },
            {
                "recording_id": "recording-01",
                "content_type": "virtual_scenes",
                "expected_revision": 0,
                "selected_generated": {"node_id": "scene-node", "revision_id": scenes_new},
                "selected_completed_reference": None,
            },
        ],
    )

    assert result["status"] == "committed"
    assert nodes.get("visible-node").head_revision_id == visible_new
    assert nodes.get("scene-node").head_revision_id == scenes_new
    assert selections.get_exact("recording-01", "visible_cards").selected_generated == {
        "node_id": "visible-node",
        "revision_id": visible_new,
    }
    assert selections.get_exact("recording-01", "virtual_scenes").selected_generated == {
        "node_id": "scene-node",
        "revision_id": scenes_new,
    }


def test_reader_recovers_interrupted_publication_before_returning_mixed_state(
    tmp_path: Path,
) -> None:
    nodes = PipelineNodeStore(tmp_path / "nodes")
    selections = PipelineNodeSelectionStore(nodes)
    visible = nodes.create("visible-node", "Visible", "visible_cards", SOURCE, VISIBLE, {})
    scenes = nodes.create("scene-node", "Scenes", "virtual_scenes", SOURCE, SCENES, {})
    transactions = PipelineNodeTransactions(nodes)
    plan = transactions._prepare_plan(
        [
            {
                "node_id": "visible-node",
                "expected_revision_id": visible.revision_id,
                "revision_id": "visible-r2",
                "content": VISIBLE,
                "metadata": {"reflow": True},
            },
            {
                "node_id": "scene-node",
                "expected_revision_id": scenes.revision_id,
                "revision_id": "scene-r2",
                "content": SCENES,
                "metadata": {"reflow": True},
            },
        ],
        [
            {
                "recording_id": "recording-01",
                "content_type": "visible_cards",
                "expected_revision": 0,
                "selected_generated": {"node_id": "visible-node", "revision_id": "visible-r2"},
                "selected_completed_reference": None,
            },
            {
                "recording_id": "recording-01",
                "content_type": "virtual_scenes",
                "expected_revision": 0,
                "selected_generated": {"node_id": "scene-node", "revision_id": "scene-r2"},
                "selected_completed_reference": None,
            },
        ],
    )
    digest = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    journal = tmp_path / "nodes" / ".coordinated-transactions" / "reflow-interrupted.json"
    atomic_replace_json(
        journal,
        {
            "schema_version": "pipeline-node-transaction/v1",
            "request_digest": "fixture-request-digest",
            "digest": digest,
            "plan": plan,
            "status": "prepared",
        },
    )
    first = plan["nodes"][0]
    revision = nodes._new_revision(
        first["node_id"],
        first["parent_revision_id"],
        first["content"],
        first["metadata"],
        first["created_at"],
        first["revision_id"],
    )
    nodes._publish_revision(nodes._node_path(first["node_id"]), revision)
    atomic_replace_json(
        nodes._node_path(first["node_id"]) / "head.json", {"revision_id": first["revision_id"]}
    )

    # The first observer finishes the journal before it can return a selection or node head.
    assert selections.get_exact("recording-01", "visible_cards").selected_generated == {
        "node_id": "visible-node",
        "revision_id": "visible-r2",
    }
    assert nodes.get("visible-node").head_revision_id == "visible-r2"
    assert nodes.get("scene-node").head_revision_id == "scene-r2"
    assert selections.get_exact("recording-01", "virtual_scenes").selected_generated == {
        "node_id": "scene-node",
        "revision_id": "scene-r2",
    }
    import json

    assert json.loads(journal.read_bytes())["status"] == "committed"
