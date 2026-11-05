import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from dokodetector_backend.frame_review_api import _editor_target
from dokodetector_backend.frame_review_queue import FrameReviewItem


def test_queue_target_selects_exact_node_revision_and_item() -> None:
    item = FrameReviewItem(
        queue_id="0096-M4",
        queue_digest="a" * 64,
        recording_id="recording-1",
        stage="visible_cards",
        item_id="frame-1",
        source_revision_id="old-revision",
        source_revision_sha256="b" * 64,
        scene_run_id=None,
        scene_revision_id=None,
        comparison_reference_revision_id=None,
        reasons=("fixture",),
        eligible=True,
        comparison_eligible=False,
    )
    store = SimpleNamespace(
        has_revision=lambda node_id, revision_id: (
            (node_id, revision_id) == ("node-1", "revision-1")
        ),
        get=lambda _: SimpleNamespace(
            content_type="visible_cards", source={"recording_id": "recording-1"}
        ),
    )
    writer = SimpleNamespace(
        migrated_revisions={"old-revision": {"node_id": "node-1", "revision_id": "revision-1"}},
        node_store=store,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pipeline_lineage_writer=writer))
    )
    target = _editor_target(request, item)
    params = parse_qs(urlparse(target.path).query)
    assert params["item"] == ["frame-1"]
    assert json.loads(params["lineage"][0])["selected"]["visible_cards"] == {
        "node_id": "node-1",
        "revision_id": "revision-1",
    }
    assert "view" not in params and "revision" not in params
