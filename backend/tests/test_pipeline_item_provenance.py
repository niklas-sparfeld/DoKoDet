from pathlib import Path

import pytest

from dokodetector_backend.pipeline_item_provenance import ItemProvenanceService
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
TOOL = {"kind": "processor", "id": "detector"}
HUMAN = {"kind": "human", "id": "operator"}
UNKNOWN = {"kind": "not_recorded", "id": None}


def content(*ids: str) -> dict:
    return {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": item,
                "event_type": "card_state_changed",
                "start_us": n * 1000,
                "end_us": n * 1000 + 100,
            }
            for n, item in enumerate(ids, 1)
        ],
    }


def pointers(*ids: str) -> dict:
    return {item: f"/events/{n}" for n, item in enumerate(ids)}


def op(kind: str, before: list[str], after: list[str]) -> dict:
    return {"kind": kind, "before": before, "after": after}


def test_creation_corrections_split_merge_delete_and_copy(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    service = ItemProvenanceService(store)
    a = service.create("n", "Events", "events", SOURCE, content("a"), pointers("a"), TOOL)
    b = service.save(
        "n", a.revision_id, content("b"), pointers("b"), [op("replace", ["a"], ["b"])], HUMAN
    )
    c = service.save(
        "n", b.revision_id, content("c"), pointers("c"), [op("replace", ["b"], ["c"])], TOOL
    )
    d = service.save(
        "n",
        c.revision_id,
        content("d", "e"),
        pointers("d", "e"),
        [op("split", ["c"], ["d", "e"])],
        HUMAN,
    )
    e = service.save(
        "n", d.revision_id, content("f"), pointers("f"), [op("merge", ["d", "e"], ["f"])], UNKNOWN
    )
    f = service.save("n", e.revision_id, content(), {}, [op("delete", ["f"], [])], HUMAN)
    copy = service.copy_unchanged("copy", "Copy", "n", f.revision_id, HUMAN)
    provenance = copy.metadata["item_provenance"]
    assert provenance == f.metadata["item_provenance"]
    assert [x["kind"] for x in provenance["changes"]] == [
        "insert",
        "replace",
        "replace",
        "split",
        "merge",
        "delete",
    ]
    assert [x["actor"] for x in provenance["changes"]] == [TOOL, HUMAN, TOOL, HUMAN, UNKNOWN, HUMAN]
    assert provenance["changes"][0]["after"]["a"]["sha256"]
    assert provenance["items"] == {}
    assert provenance["changes"][0]["after_revision"] == {
        "node_id": "n",
        "revision_id": a.revision_id,
    }
    assert provenance["changes"][1]["before_revision"]["revision_id"] == a.revision_id
    assert provenance["changes"][1]["after_revision"]["revision_id"] == b.revision_id
    assert copy.metadata["copied_from"]["revision_id"] == f.revision_id
    assert PipelineNodeStore(tmp_path).read_revision("n", a.revision_id).metadata == a.metadata


def test_unaccounted_change_and_stale_writer_rejected(tmp_path: Path) -> None:
    service = ItemProvenanceService(PipelineNodeStore(tmp_path))
    a = service.create("n", "Events", "events", SOURCE, content("a"), pointers("a"), TOOL)
    with pytest.raises(ValueError, match="account"):
        service.save("n", a.revision_id, content("b"), pointers("b"), [], HUMAN)
    b = service.save(
        "n", a.revision_id, content("b"), pointers("b"), [op("replace", ["a"], ["b"])], HUMAN
    )
    with pytest.raises(NodeConflict):
        service.save(
            "n", a.revision_id, content("c"), pointers("c"), [op("replace", ["a"], ["c"])], HUMAN
        )
    assert service.store.get("n").head_revision_id == b.revision_id


def test_copy_retains_original_attribution_through_later_edit(tmp_path: Path) -> None:
    service = ItemProvenanceService(PipelineNodeStore(tmp_path))
    original = service.create("n", "Events", "events", SOURCE, content("a"), pointers("a"), TOOL)
    copied = service.copy_unchanged("copy", "Copy", "n", original.revision_id, HUMAN)
    modified = content("a")
    modified["events"][0]["end_us"] += 10
    updated = service.save(
        "copy", copied.revision_id, modified, pointers("a"), [op("replace", ["a"], ["a"])], HUMAN
    )
    changes = updated.metadata["item_provenance"]["changes"]
    assert changes[0]["actor"] == TOOL
    assert changes[0]["after_revision"]["node_id"] == "n"
    assert changes[1]["before_revision"]["node_id"] == "copy"
    assert changes[1]["after_revision"]["revision_id"] == updated.revision_id
