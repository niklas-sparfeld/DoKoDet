import hashlib
import multiprocessing
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
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


def _crash_coordinated_transaction(root: str, boundary: str) -> None:
    nodes = PipelineNodeStore(Path(root) / "nodes")

    def terminate(target: str) -> None:
        if target == boundary:
            os._exit(72)

    nodes._after_durable_boundary = terminate
    PipelineNodeTransactions(nodes).commit(
        "reflow-crash",
        node_updates=[
            {
                "node_id": "visible-node",
                "expected_revision_id": "visible-r1",
                "revision_id": "visible-r2",
                "content": VISIBLE,
                "metadata": {"reflow": True},
            },
            {
                "node_id": "scene-node",
                "expected_revision_id": "scene-r1",
                "revision_id": "scene-r2",
                "content": SCENES,
                "metadata": {"reflow": True},
            },
        ],
        selection_updates=[],
    )


def _paused_coordinated_transaction(root: str, pause_at: str, ready, release, results) -> None:
    nodes = PipelineNodeStore(root)
    transaction = PipelineNodeTransactions(nodes)
    prepare_plan = transaction._prepare_plan
    recover = transaction.recover

    def pause() -> None:
        ready.set()
        if not release.wait(10):
            raise TimeoutError("save interleaving test did not release transaction")

    def prepare_with_pause(node_updates, selection_updates):
        plan = prepare_plan(node_updates, selection_updates)
        if pause_at == "after_plan":
            pause()
        return plan

    def recover_with_pause() -> None:
        if pause_at == "after_journal":
            pause()
        recover()

    transaction._prepare_plan = prepare_with_pause
    transaction.recover = recover_with_pause
    try:
        transaction.commit(
            "interleaving-transaction",
            node_updates=[
                {
                    "node_id": "visible-node",
                    "expected_revision_id": "visible-r1",
                    "revision_id": "visible-r2",
                    "content": VISIBLE,
                    "metadata": {"interleaving": True},
                }
            ],
            selection_updates=[],
        )
        results.put("committed")
    except Exception as error:  # pragma: no cover - reported to the parent process
        results.put(f"error: {error!r}")


def _competing_ordinary_save(root: str, lock_attempt, finished, results) -> None:
    from dokodetector_backend import pipeline_node_store

    original_lock = pipeline_node_store._process_lock

    @contextmanager
    def observe_lock(path, thread_lock):
        if Path(path) == Path(root) / ".transactions.lock":
            lock_attempt.set()
        with original_lock(path, thread_lock):
            yield

    pipeline_node_store._process_lock = observe_lock
    store = PipelineNodeStore(root)
    try:
        store.save("visible-node", "visible-r1", VISIBLE, {"ordinary_save": True})
    except Exception as error:
        results.put(type(error).__name__)
    else:
        results.put("saved")
    finally:
        finished.set()


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
    assert nodes.read_authorized_revision("visible-node", visible_new).revision_id == visible_new
    assert nodes.read_authorized_revision("scene-node", scenes_new).revision_id == scenes_new


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
    assert nodes.read_authorized_revision("visible-node", "visible-r2").revision_id == (
        "visible-r2"
    )
    assert nodes.read_authorized_revision("scene-node", "scene-r2").revision_id == "scene-r2"


@pytest.mark.parametrize("boundary", ["head", "publication"])
def test_coordinated_transaction_recovers_authority_after_process_death(
    tmp_path: Path, boundary: str
) -> None:
    nodes = PipelineNodeStore(tmp_path / "nodes")
    nodes.create(
        "visible-node", "Visible", "visible_cards", SOURCE, VISIBLE, {}, revision_id="visible-r1"
    )
    nodes.create(
        "scene-node", "Scenes", "virtual_scenes", SOURCE, SCENES, {}, revision_id="scene-r1"
    )
    context = multiprocessing.get_context("spawn")
    worker = context.Process(target=_crash_coordinated_transaction, args=(str(tmp_path), boundary))
    worker.start()
    worker.join(10)
    assert worker.exitcode == 72

    reopened = PipelineNodeStore(tmp_path / "nodes")
    assert reopened.read_authorized_revision("visible-node", "visible-r2").revision_id == (
        "visible-r2"
    )
    assert reopened.read_authorized_revision("scene-node", "scene-r2").revision_id == "scene-r2"


@pytest.mark.parametrize("pause_at", ["after_plan", "after_journal"])
def test_ordinary_save_serializes_with_coordinated_transaction(
    tmp_path: Path, pause_at: str
) -> None:
    nodes = PipelineNodeStore(tmp_path)
    nodes.create(
        "visible-node", "Visible", "visible_cards", SOURCE, VISIBLE, {}, revision_id="visible-r1"
    )
    context = multiprocessing.get_context("spawn")
    transaction_ready = context.Event()
    release_transaction = context.Event()
    lock_attempt = context.Event()
    save_finished = context.Event()
    transaction_results = context.Queue()
    save_results = context.Queue()
    transaction = context.Process(
        target=_paused_coordinated_transaction,
        args=(str(tmp_path), pause_at, transaction_ready, release_transaction, transaction_results),
    )
    transaction.start()
    assert transaction_ready.wait(10), "transaction did not reach the selected interleaving"
    if pause_at == "after_journal":
        journal = tmp_path / ".coordinated-transactions" / "interleaving-transaction.json"
        assert journal.is_file()

    saver = context.Process(
        target=_competing_ordinary_save,
        args=(str(tmp_path), lock_attempt, save_finished, save_results),
    )
    saver.start()
    assert lock_attempt.wait(10), "ordinary save did not attempt the store transaction lock"
    assert not save_finished.wait(0.1)
    assert (tmp_path / "visible-node" / "head.json").read_text() == '{"revision_id":"visible-r1"}'

    release_transaction.set()
    transaction.join(10)
    saver.join(10)
    assert transaction.exitcode == 0
    assert saver.exitcode == 0
    assert transaction_results.get(timeout=2) == "committed"
    assert save_results.get(timeout=2) == "NodeConflict"

    reopened = PipelineNodeStore(tmp_path)
    assert reopened.get("visible-node").head_revision_id == "visible-r2"
    assert reopened.read_authorized_revision("visible-node", "visible-r2").revision_id == (
        "visible-r2"
    )
    assert reopened.save("visible-node", "visible-r2", VISIBLE, {"after": True}).revision_id
