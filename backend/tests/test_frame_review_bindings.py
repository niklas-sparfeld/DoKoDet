from pathlib import Path
from types import SimpleNamespace

import pytest

from dokodetector_backend.frame_review_bindings import (
    build_frame_review_bindings,
    load_frame_review_bindings,
    write_frame_review_bindings,
)

QUEUE = Path(__file__).resolve().parents[2] / "docs/reports/0096-M4_Human_Review_Queue.json"


def test_binding_uses_exact_mapped_revision_and_leaves_missing_source_unavailable() -> None:
    import json

    from dokodetector_backend.frame_review_queue import parse_frozen_queue

    raw = json.loads(QUEUE.read_bytes())
    items = parse_frozen_queue(raw)
    first = items[0]
    target = {"node_id": "node-1", "revision_id": "revision-1"}
    store = SimpleNamespace(
        get=lambda _: SimpleNamespace(
            content_type="visible_cards", source={"recording_id": first.recording_id}
        ),
        read_revision=lambda *_: SimpleNamespace(
            metadata={
                "legacy_revision_id": first.source_revision_id,
                "legacy_content_sha256": first.source_revision_sha256,
            }
        ),
    )
    result = build_frame_review_bindings(raw, {first.source_revision_id: target}, store)
    bound = next(
        entry
        for entry in result["items"]
        if entry["recording_id"] == first.recording_id and entry["item_id"] == first.item_id
    )
    assert bound["source"] == target
    assert result["queue_digest"] == first.queue_digest
    assert any(entry["source"] is None for entry in result["items"])
    store.read_revision = lambda *_: SimpleNamespace(
        metadata={
            "legacy_revision_id": "other",
            "legacy_content_sha256": first.source_revision_sha256,
        }
    )
    with pytest.raises(ValueError, match="source identity"):
        build_frame_review_bindings(raw, {first.source_revision_id: target}, store)


def test_binding_file_is_replay_safe_and_bound_to_queue_digest(tmp_path: Path) -> None:
    bindings = {
        "schema_version": "frame-review-node-bindings/v1",
        "queue_id": "0096-M4",
        "queue_digest": "a" * 64,
        "items": [
            {
                "recording_id": "rec-1",
                "item_id": "frame-1",
                "source": {"node_id": "node-1", "revision_id": "revision-1"},
            }
        ],
    }
    write_frame_review_bindings(tmp_path, bindings)
    write_frame_review_bindings(tmp_path, bindings)
    assert load_frame_review_bindings(tmp_path, "a" * 64) == {
        ("rec-1", "frame-1"): {"node_id": "node-1", "revision_id": "revision-1"}
    }
    with pytest.raises(ValueError, match="digest"):
        load_frame_review_bindings(tmp_path, "b" * 64)
    with pytest.raises(ValueError, match="conflict"):
        write_frame_review_bindings(tmp_path, {**bindings, "queue_digest": "b" * 64})
