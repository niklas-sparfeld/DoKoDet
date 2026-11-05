from pathlib import Path

from dokodetector_backend.pipeline_item_provenance import ItemProvenanceService
from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import PipelineNodeStore

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10000000,
}
HUMAN = {"kind": "human", "id": "reviewer"}
EVIDENCE = {"frame_sha256": "b" * 64, "policy": "frame/v1"}


def content(end: int) -> dict:
    return {
        "schema_version": "event-data/v1",
        "events": [
            {"event_id": "e", "event_type": "card_state_changed", "start_us": 100, "end_us": end}
        ],
    }


def test_review_coverage_and_overall_are_independent(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    rev = ItemProvenanceService(store).create(
        "n", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, HUMAN
    )
    reviews = PipelineNodeReviews(store)
    item = reviews.item("i", "n", rev.revision_id, "e", "correct event?", "yes", HUMAN, EVIDENCE)
    coverage = reviews.coverage(
        "c",
        "n",
        rev.revision_id,
        "missing events?",
        {"frame": 1, "result": "empty"},
        HUMAN,
        EVIDENCE,
    )
    assert len(reviews.list_for_revision("n", rev.revision_id)) == 2
    assert item["kind"] == "item" and coverage["kind"] == "coverage"
    assert not any(r["kind"] == "overall" for r in reviews.list_for_revision("n", rev.revision_id))
    reviews.overall("o", "n", rev.revision_id, "complete?", "yes", HUMAN, EVIDENCE)
    assert (
        len(
            PipelineNodeReviews(PipelineNodeStore(tmp_path)).list_for_revision("n", rev.revision_id)
        )
        == 3
    )
    assert store.get("n").head_revision_id == rev.revision_id


def test_latest_review_precedes_older_decision(tmp_path: Path, monkeypatch) -> None:
    store = PipelineNodeStore(tmp_path)
    rev = ItemProvenanceService(store).create(
        "n", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, HUMAN
    )
    reviews = PipelineNodeReviews(store)
    times = iter(["2026-11-05T10:00:00Z", "2026-11-05T11:00:00Z"])
    monkeypatch.setattr(
        "dokodetector_backend.pipeline_node_reviews._canonical_timestamp", lambda _: next(times)
    )
    reviews.item("a-old", "n", rev.revision_id, "e", "correct?", "accepted", HUMAN, EVIDENCE)
    reviews.item("z-new", "n", rev.revision_id, "e", "correct?", "rejected", HUMAN, EVIDENCE)
    assert [record["review_id"] for record in reviews.list_for_revision("n", rev.revision_id)] == [
        "z-new",
        "a-old",
    ]


def test_applicability_on_copy_and_change(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    rev = ItemProvenanceService(store).create(
        "n", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, HUMAN
    )
    reviews = PipelineNodeReviews(store)
    reviews.item("i", "n", rev.revision_id, "e", "correct?", "yes", HUMAN, EVIDENCE)
    reviews.overall("o", "n", rev.revision_id, "complete?", "yes", HUMAN, EVIDENCE)
    copy = PipelineNodeEdits(store).copy("n", rev.revision_id, "copy", HUMAN)
    assert (
        reviews.applicability("i", copy["node_id"], copy["revision_id"], EVIDENCE)["status"]
        == "applicable"
    )
    assert (
        reviews.applicability("o", copy["node_id"], copy["revision_id"], EVIDENCE)["status"]
        == "inapplicable"
    )
    changed = PipelineNodeEdits(store).edit(
        copy["node_id"],
        copy["revision_id"],
        content(300),
        "edit",
        HUMAN,
        pointers={"e": "/events/0"},
        operations=[{"kind": "replace", "before": ["e"], "after": ["e"]}],
    )
    assert (
        reviews.applicability("i", changed["node_id"], changed["revision_id"], EVIDENCE)["status"]
        == "inapplicable"
    )
    assert (
        reviews.applicability("i", copy["node_id"], copy["revision_id"], None)["status"]
        == "unknown"
    )


def test_review_idempotency_conflicts_and_no_inferred_review(tmp_path: Path) -> None:
    import pytest

    from dokodetector_backend.pipeline_node_store import NodeConflict

    store = PipelineNodeStore(tmp_path)
    first = ItemProvenanceService(store).create(
        "n", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, HUMAN
    )
    reviews = PipelineNodeReviews(store)
    original = reviews.item("i", "n", first.revision_id, "e", "correct?", "yes", HUMAN, EVIDENCE)
    assert (
        reviews.item("i", "n", first.revision_id, "e", "correct?", "yes", HUMAN, EVIDENCE)
        == original
    )
    with pytest.raises(NodeConflict):
        reviews.item("i", "n", first.revision_id, "e", "correct?", "no", HUMAN, EVIDENCE)
    with pytest.raises(ValueError, match="evidence and policy"):
        reviews.overall("bad", "n", first.revision_id, "complete?", "yes", HUMAN, {"policy": "v1"})
    unrelated = ItemProvenanceService(store).create(
        "other", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, HUMAN
    )
    assert reviews.list_for_revision("other", unrelated.revision_id) == ()
    assert (
        reviews.applicability("i", "other", unrelated.revision_id, EVIDENCE)["status"]
        == "inapplicable"
    )
    assert (
        reviews.applicability(
            "i", "n", first.revision_id, {"policy": "different", "frame_sha256": "b" * 64}
        )["status"]
        == "inapplicable"
    )


def test_partial_coverage_and_deleted_item_decision_remain_durable(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    first = ItemProvenanceService(store).create(
        "n", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, HUMAN
    )
    reviews = PipelineNodeReviews(store)
    reviews.item("i", "n", first.revision_id, "e", "correct?", "no", HUMAN, EVIDENCE)
    reviews.coverage(
        "partial",
        "n",
        first.revision_id,
        "missing?",
        {"start_us": 0, "end_us": 1000},
        HUMAN,
        EVIDENCE,
    )
    deleted = PipelineNodeEdits(store).edit(
        "n",
        first.revision_id,
        {"schema_version": "event-data/v1", "events": []},
        "delete",
        HUMAN,
        pointers={},
        operations=[{"kind": "delete", "before": ["e"], "after": []}],
    )
    assert (
        reviews.applicability("i", "n", deleted["revision_id"], EVIDENCE)["status"]
        == "inapplicable"
    )
    assert (
        reviews.applicability("partial", "n", deleted["revision_id"], EVIDENCE)["status"]
        == "inapplicable"
    )
    assert reviews.get("i")["decision"] == "no"
    assert reviews.get("partial")["coverage"] == {"start_us": 0, "end_us": 1000}


def test_review_after_use_does_not_copy_node(tmp_path: Path) -> None:
    from dokodetector_backend.pipeline_node_uses import PipelineNodeUses

    store = PipelineNodeStore(tmp_path)
    rev = ItemProvenanceService(store).create(
        "n", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, HUMAN
    )
    PipelineNodeUses(store).accept("run", [("n", rev.revision_id)])
    PipelineNodeReviews(store).item(
        "i", "n", rev.revision_id, "e", "correct?", "yes", HUMAN, EVIDENCE
    )
    assert len(store.list_nodes()) == 1
    assert store.get("n").head_revision_id == rev.revision_id
