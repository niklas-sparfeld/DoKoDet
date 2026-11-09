import hashlib
import multiprocessing
import os
import threading
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


def _install_prepared_two_node_journal(root: Path, selection_updates=None) -> None:
    if selection_updates is None:
        selection_updates = []
    nodes = PipelineNodeStore(root)
    plan = PipelineNodeTransactions(nodes)._prepare_plan(
        [
            {
                "node_id": "visible-node",
                "expected_revision_id": "visible-r1",
                "revision_id": "visible-r2",
                "content": VISIBLE,
                "metadata": {"recovery": True},
            },
            {
                "node_id": "scene-node",
                "expected_revision_id": "scene-r1",
                "revision_id": "scene-r2",
                "content": SCENES,
                "metadata": {"recovery": True},
            },
        ],
        selection_updates,
    )
    digest = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    atomic_replace_json(
        root / ".coordinated-transactions" / "recovery-test.json",
        {
            "schema_version": "pipeline-node-transaction/v1",
            "request_digest": "test",
            "digest": digest,
            "plan": plan,
            "status": "prepared",
        },
    )


def _paused_recovery(root: str, ready, release, results) -> None:
    store = PipelineNodeStore(root)

    def pause(boundary: str) -> None:
        if boundary == "head":
            ready.set()
            if not release.wait(10):
                raise TimeoutError("recovery test did not release")

    store._after_durable_boundary = pause
    try:
        store.recover_transactions()
        results.put("recovered")
    except Exception as error:  # pragma: no cover - reported to parent process
        results.put(f"error: {error!r}")


def _competing_authorized_read(root: str, attempted, finished, results) -> None:
    from dokodetector_backend import pipeline_node_store

    original = pipeline_node_store._transaction_lock

    @contextmanager
    def observe(store):
        if store.root == Path(root):
            attempted.set()
        with original(store):
            yield

    pipeline_node_store._transaction_lock = observe
    try:
        revision = PipelineNodeStore(root).read_authorized_revision("scene-node", "scene-r2")
        results.put(revision.revision_id)
    except Exception as error:
        results.put(f"error: {error!r}")
    finally:
        finished.set()


def _paused_two_node_commit(root: str, started, partial, release, results) -> None:
    nodes = PipelineNodeStore(root)

    def pause(boundary: str) -> None:
        if boundary == "head":
            partial.set()
            if not release.wait(10):
                raise TimeoutError("read interleaving test did not release writer")

    nodes._after_durable_boundary = pause
    started.set()
    try:
        PipelineNodeTransactions(nodes).commit(
            "read-interleaving",
            node_updates=[
                {
                    "node_id": "visible-node",
                    "expected_revision_id": "visible-r1",
                    "revision_id": "visible-r2",
                    "content": VISIBLE,
                    "metadata": {"interleaving": True},
                },
                {
                    "node_id": "scene-node",
                    "expected_revision_id": "scene-r1",
                    "revision_id": "scene-r2",
                    "content": SCENES,
                    "metadata": {"interleaving": True},
                },
            ],
            selection_updates=[],
        )
        results.put("committed")
    except Exception as error:  # pragma: no cover - reported to the parent process
        results.put(f"error: {error!r}")


def _competing_selection_write(root: str, started, lock_acquired, finished, results) -> None:
    from dokodetector_backend import pipeline_node_selection_store

    original_lock = pipeline_node_selection_store._process_lock

    @contextmanager
    def observe_lock(path, thread_lock):
        if Path(path).name == ".visible_cards.lock":
            lock_acquired.set()
        with original_lock(path, thread_lock):
            yield

    pipeline_node_selection_store._process_lock = observe_lock
    nodes = PipelineNodeStore(root)
    selections = PipelineNodeSelectionStore(nodes)
    started.set()
    try:
        saved = selections.update_exact(
            "recording-01",
            "visible_cards",
            expected_revision=1,
            selected_generated={"node_id": "visible-node", "revision_id": "visible-r1"},
            selected_completed_reference=None,
        )
        results.put(saved.revision)
    except Exception as error:  # pragma: no cover - reported to the parent process
        results.put(f"error: {error!r}")
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


def _two_nodes(root: Path) -> PipelineNodeStore:
    nodes = PipelineNodeStore(root)
    nodes.create(
        "visible-node", "Visible", "visible_cards", SOURCE, VISIBLE, {}, revision_id="visible-r1"
    )
    nodes.create(
        "scene-node", "Scenes", "virtual_scenes", SOURCE, SCENES, {}, revision_id="scene-r1"
    )
    _install_prepared_two_node_journal(root)
    return nodes


def _clean_two_nodes(root: Path) -> PipelineNodeStore:
    nodes = PipelineNodeStore(root)
    nodes.create(
        "visible-node", "Visible", "visible_cards", SOURCE, VISIBLE, {}, revision_id="visible-r1"
    )
    nodes.create(
        "scene-node", "Scenes", "virtual_scenes", SOURCE, SCENES, {}, revision_id="scene-r1"
    )
    return nodes


def test_same_instance_reader_waits_for_transaction_recovery(tmp_path: Path) -> None:
    nodes = _two_nodes(tmp_path)
    recovery_paused = threading.Event()
    release = threading.Event()
    reader_done = threading.Event()
    outcomes: list[str] = []

    def pause(boundary: str) -> None:
        if boundary == "head":
            recovery_paused.set()
            assert release.wait(10)

    nodes._after_durable_boundary = pause
    recovery = threading.Thread(target=nodes.recover_transactions)
    recovery.start()
    assert recovery_paused.wait(10)

    def read() -> None:
        outcomes.append(nodes.read_authorized_revision("scene-node", "scene-r2").revision_id)
        reader_done.set()

    reader = threading.Thread(target=read)
    reader.start()
    assert not reader_done.wait(0.1)
    release.set()
    recovery.join(10)
    reader.join(10)
    assert not recovery.is_alive() and not reader.is_alive()
    assert outcomes == ["scene-r2"]


def test_separate_process_reader_waits_for_transaction_recovery(tmp_path: Path) -> None:
    _two_nodes(tmp_path)
    context = multiprocessing.get_context("spawn")
    recovery_ready = context.Event()
    release_recovery = context.Event()
    recovery_results = context.Queue()
    recovery = context.Process(
        target=_paused_recovery,
        args=(str(tmp_path), recovery_ready, release_recovery, recovery_results),
    )
    recovery.start()
    assert recovery_ready.wait(10)

    attempted = context.Event()
    finished = context.Event()
    reader_results = context.Queue()
    reader = context.Process(
        target=_competing_authorized_read,
        args=(str(tmp_path), attempted, finished, reader_results),
    )
    reader.start()
    assert attempted.wait(10)
    assert not finished.wait(0.1)
    release_recovery.set()
    recovery.join(10)
    reader.join(10)
    assert recovery.exitcode == 0 and reader.exitcode == 0
    assert recovery_results.get(timeout=2) == "recovered"
    assert reader_results.get(timeout=2) == "scene-r2"


def test_same_instance_authorized_read_holds_root_lock_after_recovery(tmp_path: Path) -> None:
    nodes = _clean_two_nodes(tmp_path)
    recovered = threading.Event()
    continue_read = threading.Event()
    original_recover = nodes.recover_transactions

    def recover_then_pause() -> None:
        original_recover()
        recovered.set()
        assert continue_read.wait(10)

    nodes.recover_transactions = recover_then_pause
    read_result: list[str] = []
    reader = threading.Thread(
        target=lambda: read_result.append(
            nodes.read_authorized_revision("scene-node", "scene-r1").revision_id
        )
    )
    reader.start()
    assert recovered.wait(10)

    writer_started = threading.Event()
    writer_partial = threading.Event()
    release_writer = threading.Event()
    writer_results: list[str] = []
    writer = threading.Thread(
        target=lambda: _thread_two_node_commit(
            tmp_path, writer_started, writer_partial, release_writer, writer_results
        )
    )
    writer.start()
    assert writer_started.wait(10)
    assert not writer_partial.wait(0.1), "writer published during the recovery/read gap"
    continue_read.set()
    reader.join(10)
    assert not reader.is_alive()
    assert read_result == ["scene-r1"]
    assert writer_partial.wait(10)
    release_writer.set()
    writer.join(10)
    assert not writer.is_alive() and writer_results == ["committed"]


def _thread_two_node_commit(root: Path, started, partial, release, results) -> None:
    # Reuse the process helper's transaction body while keeping thread synchronization events.
    nodes = PipelineNodeStore(root)

    def pause(boundary: str) -> None:
        if boundary == "head":
            partial.set()
            if not release.wait(10):
                raise TimeoutError("read interleaving test did not release writer")

    nodes._after_durable_boundary = pause
    started.set()
    try:
        PipelineNodeTransactions(nodes).commit(
            "thread-read-interleaving",
            node_updates=[
                {
                    "node_id": "visible-node",
                    "expected_revision_id": "visible-r1",
                    "revision_id": "visible-r2",
                    "content": VISIBLE,
                    "metadata": {},
                },
                {
                    "node_id": "scene-node",
                    "expected_revision_id": "scene-r1",
                    "revision_id": "scene-r2",
                    "content": SCENES,
                    "metadata": {},
                },
            ],
            selection_updates=[],
        )
        results.append("committed")
    except Exception as error:
        results.append(f"error: {error!r}")


def test_separate_process_authorized_read_holds_root_lock_after_recovery(tmp_path: Path) -> None:
    _clean_two_nodes(tmp_path)
    context = multiprocessing.get_context("spawn")
    recovered = context.Event()
    continue_read = context.Event()
    read_results = context.Queue()
    reader = context.Process(
        target=_paused_authorized_read,
        args=(str(tmp_path), recovered, continue_read, read_results),
    )
    reader.start()
    assert recovered.wait(10)

    writer_started = context.Event()
    writer_partial = context.Event()
    release_writer = context.Event()
    writer_results = context.Queue()
    writer = context.Process(
        target=_paused_two_node_commit,
        args=(str(tmp_path), writer_started, writer_partial, release_writer, writer_results),
    )
    writer.start()
    assert writer_started.wait(10)
    assert not writer_partial.wait(0.1), "writer published during the recovery/read gap"
    continue_read.set()
    reader.join(10)
    assert reader.exitcode == 0
    assert read_results.get(timeout=2) == "scene-r1"
    assert writer_partial.wait(10)
    release_writer.set()
    writer.join(10)
    assert writer.exitcode == 0
    assert writer_results.get(timeout=2) == "committed"


def test_selection_writer_takes_root_lock_before_selection_lock(tmp_path: Path) -> None:
    _clean_two_nodes(tmp_path)
    nodes = PipelineNodeStore(tmp_path)
    plan = PipelineNodeTransactions(nodes)._prepare_plan(
        [
            {
                "node_id": "visible-node",
                "expected_revision_id": "visible-r1",
                "revision_id": "visible-r2",
                "content": VISIBLE,
                "metadata": {"recovery": True},
            }
        ],
        [
            {
                "recording_id": "recording-01",
                "content_type": "visible_cards",
                "expected_revision": 0,
                "selected_generated": {"node_id": "visible-node", "revision_id": "visible-r2"},
                "selected_completed_reference": None,
            }
        ],
    )
    digest = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    atomic_replace_json(
        tmp_path / ".coordinated-transactions" / "selection-lock-order.json",
        {
            "schema_version": "pipeline-node-transaction/v1",
            "request_digest": "test",
            "digest": digest,
            "plan": plan,
            "status": "prepared",
        },
    )

    context = multiprocessing.get_context("spawn")
    recovery_ready = context.Event()
    release_recovery = context.Event()
    recovery_results = context.Queue()
    recovery = context.Process(
        target=_paused_recovery,
        args=(str(tmp_path), recovery_ready, release_recovery, recovery_results),
    )
    recovery.start()
    assert recovery_ready.wait(10)

    writer_started = context.Event()
    lock_acquired = context.Event()
    finished = context.Event()
    writer_results = context.Queue()
    writer = context.Process(
        target=_competing_selection_write,
        args=(str(tmp_path), writer_started, lock_acquired, finished, writer_results),
    )
    writer.start()
    assert writer_started.wait(10)
    assert not lock_acquired.wait(0.2), "selection lock was acquired before the root lock"
    release_recovery.set()
    recovery.join(10)
    writer.join(10)
    assert recovery.exitcode == 0 and writer.exitcode == 0
    assert recovery_results.get(timeout=2) == "recovered"
    assert writer_results.get(timeout=2) == 2


def _paused_authorized_read(root: str, recovered, continue_read, results) -> None:
    store = PipelineNodeStore(root)
    original_recover = store.recover_transactions

    def recover_then_pause() -> None:
        original_recover()
        recovered.set()
        if not continue_read.wait(10):
            raise TimeoutError("read interleaving test did not release reader")

    store.recover_transactions = recover_then_pause
    try:
        results.put(store.read_authorized_revision("scene-node", "scene-r1").revision_id)
    except Exception as error:  # pragma: no cover - reported to the parent process
        results.put(f"error: {error!r}")
