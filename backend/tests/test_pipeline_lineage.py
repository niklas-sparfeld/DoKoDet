from pathlib import Path

import pytest

from dokodetector_backend.pipeline_lineage import PipelineLineage
from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10000000,
}
HUMAN = {"kind": "human", "id": "reviewer"}
PROCESSOR = {
    "implementation": {"name": "fixture", "version": "v1"},
    "model": None,
    "configuration": {"threshold": 0.5},
    "policies": {"crop": "v1"},
}


def ref(node, revision, role):
    return {"kind": "revision", "node_id": node, "revision_id": revision, "role": role}


def artifact(name, digest, role):
    return {"kind": "artifact", "artifact_id": name, "sha256": digest * 64, "role": role}


def node(store, node_id, kind, content):
    return store.create(node_id, node_id, kind, SOURCE, content, {})


def event(start):
    return {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "e",
                "event_type": "card_state_changed",
                "start_us": start,
                "end_us": start + 10,
            }
        ],
    }


def finish(service, run, inputs, outputs, **kwargs):
    service.start(
        run,
        inputs=inputs,
        run_kind=kwargs.get("run_kind", "processor"),
        processor=PROCESSOR,
        context=kwargs.get("context", {}),
    )
    return service.finish(
        run,
        inputs=inputs,
        outputs=outputs,
        status=kwargs.get("status", "succeeded"),
        run_kind=kwargs.get("run_kind", "processor"),
        result=kwargs.get("result", "nonempty"),
        processor=PROCESSOR,
        context=kwargs.get("context", {}),
        failure=kwargs.get("failure"),
    )


def test_multi_input_analysis_alternative_runs_copies_and_failures(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    uses = PipelineNodeUses(store)
    graph = PipelineLineage(store)
    event_revision = node(store, "events", "events", event(10))
    scene_revision = node(
        store, "scene", "virtual_scenes", {"schema_version": "virtual-scene-data/v1", "frames": []}
    )
    identity_revision = node(
        store,
        "identity",
        "visual_identities",
        {"schema_version": "visual-identity-data/v2", "outcomes": []},
    )
    observation = node(
        store,
        "observation",
        "table_observations",
        {"schema_version": "table-observation-data/v1", "observations": []},
    )
    refs = [
        ref("events", event_revision.revision_id, "events"),
        ref("scene", scene_revision.revision_id, "scene"),
        ref("identity", identity_revision.revision_id, "identity"),
    ]
    uses.accept("assemble", [(r["node_id"], r["revision_id"]) for r in refs])
    pending = graph.snapshot()
    assert next(r for r in pending["runs"] if r["run_id"] == "assemble")["status"] == "accepted"
    graph.start(
        "assemble",
        inputs=refs,
        run_kind="processor",
        processor=PROCESSOR,
        context={"fixture": "frozen"},
    )
    pending = graph.snapshot()
    assert next(r for r in pending["runs"] if r["run_id"] == "assemble")["context"] == {
        "fixture": "frozen"
    }
    record = finish(
        graph,
        "assemble",
        refs,
        [ref("observation", observation.revision_id, "observations")],
        result="empty",
        context={"fixture": "frozen"},
    )
    assert (
        finish(
            graph,
            "assemble",
            refs,
            [ref("observation", observation.revision_id, "observations")],
            result="empty",
            context={"fixture": "frozen"},
        )
        == record
    )
    uses.accept("analysis", [("observation", observation.revision_id)])
    context = {
        "round_context": {"dealer": "north"},
        "rules": {"version": "v1"},
        "search_settings": {"limit": 100},
    }
    analysis_ref = artifact("round-analyses/analysis/result.json", "f", "result")
    finish(
        graph,
        "analysis",
        [
            ref("observation", observation.revision_id, "observations"),
            artifact("round-analyses/analysis/input.json", "e", "round-input"),
        ],
        [analysis_ref],
        run_kind="analysis",
        context=context,
    )
    copy1 = PipelineNodeEdits(store).copy("events", event_revision.revision_id, "one", HUMAN)
    copy2 = PipelineNodeEdits(store).copy("events", event_revision.revision_id, "two", HUMAN)
    uses.accept("failed", [(copy1["node_id"], copy1["revision_id"])])
    finish(
        graph,
        "failed",
        [ref(copy1["node_id"], copy1["revision_id"], "events")],
        [],
        status="failed",
        result=None,
        failure={"message": "failed"},
    )
    other = node(
        store,
        "other",
        "table_observations",
        {"schema_version": "table-observation-data/v1", "observations": []},
    )
    uses.accept("alternative", [(copy2["node_id"], copy2["revision_id"])])
    finish(
        graph,
        "alternative",
        [ref(copy2["node_id"], copy2["revision_id"], "events")],
        [ref("other", other.revision_id, "observations")],
        result="empty",
    )
    snapshot = PipelineLineage(PipelineNodeStore(tmp_path)).snapshot()
    assert snapshot == graph.snapshot()
    assert len([n for n in snapshot["nodes"] if n["node_id"] == "events"]) == 1
    copies = [e for e in snapshot["edges"] if e["kind"] == "copied"]
    assert len(copies) == 2 and {e["to"][1] for e in copies} == {copy1["node_id"], copy2["node_id"]}
    used = [e for e in snapshot["edges"] if e["kind"] == "used" and e["to"] == ["run", "assemble"]]
    assert {e["role"] for e in used} == {"events", "scene", "identity"}
    runs = {r["run_id"]: r for r in snapshot["runs"]}
    assert runs["assemble"]["result"] == "empty" and runs["failed"]["status"] == "failed"
    assert runs["analysis"]["context"] == context
    assert {a["artifact_id"] for a in snapshot["artifacts"]} == {
        "round-analyses/analysis/input.json",
        "round-analyses/analysis/result.json",
    }
    assert store.get("events").head_revision_id == event_revision.revision_id


def test_cycle_duplicate_producer_and_unaccepted_inputs_are_rejected(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    first = node(store, "a", "events", event(1))
    second = node(store, "b", "events", event(2))
    uses = PipelineNodeUses(store)
    graph = PipelineLineage(store)
    uses.accept("one", [("a", first.revision_id)])
    finish(
        graph,
        "one",
        [ref("a", first.revision_id, "input")],
        [ref("b", second.revision_id, "output")],
    )
    uses.accept("cycle", [("b", second.revision_id)])
    with pytest.raises(ValueError, match="cycle"):
        finish(
            graph,
            "cycle",
            [ref("b", second.revision_id, "input")],
            [ref("a", first.revision_id, "output")],
        )
    assert (
        next(r for r in graph.snapshot()["runs"] if r["run_id"] == "cycle")["status"] == "accepted"
    )
    uses.accept("duplicate", [("a", first.revision_id)])
    with pytest.raises(ValueError, match="multiple producer"):
        finish(
            graph,
            "duplicate",
            [ref("a", first.revision_id, "input")],
            [ref("b", second.revision_id, "output")],
        )
    uses.accept("wrong-input", [("a", first.revision_id)])
    with pytest.raises(ValueError, match="accepted exact revisions"):
        finish(
            graph,
            "wrong-input",
            [ref("b", second.revision_id, "input")],
            [],
            status="failed",
            result=None,
            failure={"message": "failed"},
        )
    with pytest.raises(NodeConflict):
        finish(
            graph,
            "one",
            [ref("a", first.revision_id, "input")],
            [ref("b", second.revision_id, "other")],
        )


def test_revision_and_restore_edges_and_analysis_context(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    first = node(store, "a", "events", event(1))
    second = store.save("a", first.revision_id, event(20), {})
    restored = PipelineNodeEdits(store).restore(
        "a", second.revision_id, first.revision_id, "restore", HUMAN
    )
    graph = PipelineLineage(store)
    edges = graph.snapshot()["edges"]
    assert len([e for e in edges if e["kind"] == "revised"]) == 2
    assert next(e for e in edges if e["kind"] == "restored")["from"] == [
        "revision",
        "a",
        first.revision_id,
    ]
    PipelineNodeUses(store).accept("analysis", [("a", restored["revision_id"])])
    with pytest.raises(ValueError, match="round context"):
        finish(
            graph,
            "analysis",
            [ref("a", restored["revision_id"], "observations")],
            [artifact("result", "f", "result")],
            run_kind="analysis",
        )


def test_recording_snapshot_excludes_nodes_from_other_recordings(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    node(store, "recording-01-events", "events", event(1))
    other_source = {**SOURCE, "recording_id": "recording-02"}
    store.create("recording-02-events", "other", "events", other_source, event(2), {})

    graph = PipelineLineage(store).snapshot("recording-01")

    assert [item["node_id"] for item in graph["nodes"]] == ["recording-01-events"]
    assert len(graph["revisions"]) == 1
    assert graph["runs"] == []


def test_recording_snapshot_retains_all_inputs_of_a_multi_input_run(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    first = node(store, "first", "events", event(1))
    second = node(store, "second", "events", event(2))
    output = node(store, "output", "events", event(3))
    uses = PipelineNodeUses(store)
    uses.accept("joined-run", [("first", first.revision_id), ("second", second.revision_id)])
    lineage = PipelineLineage(store)
    finish(
        lineage,
        "joined-run",
        [
            ref("first", first.revision_id, "left_events"),
            ref("second", second.revision_id, "right_events"),
        ],
        [ref("output", output.revision_id, "events")],
    )

    graph = lineage.snapshot("recording-01")

    assert {item["node_id"] for item in graph["nodes"]} == {"first", "second", "output"}
    assert [edge["kind"] for edge in graph["edges"]].count("used") == 2
    assert [edge["kind"] for edge in graph["edges"]].count("produced") == 1
