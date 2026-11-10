from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from app_factory import create_test_app
from doko_operations.pipeline_data import RecordingVideoSource
from fastapi.testclient import TestClient
from test_round_analysis_api import RECORDING_ID, _backend

from dokodetector_backend.pipeline_node_transactions import PipelineNodeTransactions


def test_recording_route_uses_catalog_node_and_selection_publication_after_restart(
    tmp_path,
    monkeypatch,
) -> None:
    client, app = _backend(tmp_path, synchronous=False, recording_catalog_test_activation=True)
    with client:
        recording = app.state.recording_bundle_store.get_metadata(RECORDING_ID)
        assert recording is not None
        source = RecordingVideoSource(
            recording_id=RECORDING_ID,
            relative_path=f"recordings/{RECORDING_ID}/videos/video-both.mov",
            video_sha256=recording.source_sha256,
            byte_length=recording.video_byte_length,
            duration_us=1_000_000,
        ).to_mapping()
        node_store = app.state.pipeline_lineage_writer.node_store
        catalog = app.state.recording_catalog_index

        # The revision outbox is the durable recovery source if the process stops after
        # the node commit and before the catalog applies its compact contribution.
        publish_latest = catalog.publish_latest

        def fail_after_node_commit(**kwargs):
            raise OSError("simulated catalog publication interruption")

        monkeypatch.setattr(catalog, "publish_latest", fail_after_node_commit)
        try:
            node_store.create(
                "catalog-table-observation",
                "Catalog observation",
                "table_observations",
                source,
                {"schema_version": "table-observation-data/v1", "observations": []},
                {},
                revision_id="catalog-observation-r0",
            )
        except OSError:
            pass
        else:
            raise AssertionError("the injected publication interruption did not occur")
        monkeypatch.setattr(catalog, "publish_latest", publish_latest)

    # Restart recovery consumes the named node outbox. The list route then reads
    # the catalog projection and does not enumerate node manifests or histories.
    app = create_test_app(app.state.settings, recording_catalog_test_activation=True)
    with TestClient(app) as restarted:
        node_store = app.state.pipeline_lineage_writer.node_store
        selection_store = app.state.pipeline_selection_store
        before_selection = restarted.get("/v1/recordings")
        before_row = next(
            item
            for item in before_selection.json()["recordings"]
            if item["recording_id"] == RECORDING_ID
        )
        assert before_row["can_start_analysis"] is False
        assert before_row["analysis_blocker"] == (
            "No selected table observations or linked evidence packages are available."
        )
        exact = {
            "node_id": "catalog-table-observation",
            "revision_id": "catalog-observation-r0",
        }
        completed = {
            "node_id": "catalog-completed-observation",
            "revision_id": "catalog-observation-r0",
        }
        node_store.create(
            completed["node_id"],
            "Completed observation",
            "table_observations",
            source,
            {"schema_version": "table-observation-data/v1", "observations": []},
            {},
            revision_id=completed["revision_id"],
        )
        selection_store.update_exact(
            RECORDING_ID,
            "table_observations",
            expected_revision=0,
            selected_generated=exact,
            selected_completed_reference=completed,
        )

        def update_selection():
            return restarted.put(
                f"/api/recordings/{RECORDING_ID}/pipeline/observations/selection",
                json={"expected_revision": 1, "selected_generated": exact},
            )

        def create_concurrent_node():
            return node_store.create(
                "catalog-concurrent-observation",
                "Concurrent observation",
                "table_observations",
                source,
                {"schema_version": "table-observation-data/v1", "observations": []},
                {},
                revision_id="catalog-observation-r0",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            selection_future = executor.submit(update_selection)
            node_future = executor.submit(create_concurrent_node)
            assert selection_future.result().status_code == 200
            node_future.result()

        def disabled_discovery(*args, **kwargs):
            raise AssertionError("the recordings route used node discovery")

        monkeypatch.setattr(node_store, "list_nodes", disabled_discovery)
        monkeypatch.setattr(
            app.state.pipeline_workspace_service,
            "get_statuses",
            disabled_discovery,
        )
        response = restarted.get("/v1/recordings")
        assert response.status_code == 200, response.text
        row = next(
            item for item in response.json()["recordings"] if item["recording_id"] == RECORDING_ID
        )
        states = {stage["key"]: stage["state"] for stage in row["pipeline_status"]["stages"]}
        assert states["table_observations"] == "data-available"
        assert row["can_start_analysis"] is True
        assert row["analysis_blocker"] is None
        catalog_row = app.state.recording_catalog_index.read(RECORDING_ID)
        assert catalog_row is not None
        assert catalog_row["counters"]["pipeline_node:table_observations"] == 3
        selection = catalog_row["metadata"]["selection:table_observations"]
        assert selection == {
            "selected_generated": exact,
            "selected_completed_reference": completed,
        }
        with pytest.raises(FileNotFoundError):
            selection_store.update_exact(
                RECORDING_ID,
                "table_observations",
                expected_revision=2,
                selected_generated={"node_id": "missing", "revision_id": "missing"},
                selected_completed_reference=None,
            )
        monkeypatch.setattr(selection_store, "get_exact", disabled_discovery)
        response = restarted.get("/v1/recordings")
        assert response.status_code == 200, response.text

    # A second app instance retains both node availability and the exact selection.
    app = create_test_app(app.state.settings, recording_catalog_test_activation=True)
    with TestClient(app) as restarted:
        response = restarted.get("/v1/recordings")
        assert response.status_code == 200
        row = next(
            item for item in response.json()["recordings"] if item["recording_id"] == RECORDING_ID
        )
        assert row["can_start_analysis"] is True
        assert row["analysis_blocker"] is None


def test_standalone_selection_gap_recovers_from_existing_transaction_journal(tmp_path, monkeypatch):
    _, app = _backend(tmp_path, recording_catalog_test_activation=True)
    recording = app.state.recording_bundle_store.get_metadata(RECORDING_ID)
    assert recording is not None
    source = RecordingVideoSource(
        recording_id=RECORDING_ID,
        relative_path=f"recordings/{RECORDING_ID}/videos/video-both.mov",
        video_sha256=recording.source_sha256,
        byte_length=recording.video_byte_length,
        duration_us=1_000_000,
    ).to_mapping()
    nodes = app.state.pipeline_lineage_writer.node_store
    selections = app.state.pipeline_selection_store
    nodes.create(
        "standalone-selection-node",
        "Observation",
        "table_observations",
        source,
        {"schema_version": "table-observation-data/v1", "observations": []},
        {},
        revision_id="standalone-selection-r0",
    )
    catalog = app.state.recording_catalog_index
    publish = catalog.publish_latest
    monkeypatch.setattr(
        catalog,
        "publish_latest",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("selection index interruption")),
    )
    pointer = {"node_id": "standalone-selection-node", "revision_id": "standalone-selection-r0"}
    with pytest.raises(OSError, match="selection index interruption"):
        selections.update_exact(
            RECORDING_ID,
            "table_observations",
            expected_revision=0,
            selected_generated=pointer,
            selected_completed_reference=None,
        )
    monkeypatch.setattr(catalog, "publish_latest", publish)

    restarted = create_test_app(app.state.settings, recording_catalog_test_activation=True)
    recovered = restarted.state.recording_catalog_index.read(RECORDING_ID)
    assert recovered is not None
    assert recovered["metadata"]["selection:table_observations"] == {
        "selected_generated": pointer,
        "selected_completed_reference": None,
    }
    retry = restarted.state.pipeline_selection_store.update_exact(
        RECORDING_ID,
        "table_observations",
        expected_revision=0,
        selected_generated=pointer,
        selected_completed_reference=None,
    )
    assert retry.revision == 1


def test_coordinated_selection_gap_recovers_from_existing_transaction_journal(
    tmp_path, monkeypatch
):
    _, app = _backend(tmp_path, recording_catalog_test_activation=True)
    recording = app.state.recording_bundle_store.get_metadata(RECORDING_ID)
    assert recording is not None
    source = RecordingVideoSource(
        recording_id=RECORDING_ID,
        relative_path=f"recordings/{RECORDING_ID}/videos/video-both.mov",
        video_sha256=recording.source_sha256,
        byte_length=recording.video_byte_length,
        duration_us=1_000_000,
    ).to_mapping()
    nodes = app.state.pipeline_lineage_writer.node_store
    catalog = app.state.recording_catalog_index
    initial = nodes.create(
        "coordinated-selection-node",
        "Observation",
        "table_observations",
        source,
        {"schema_version": "table-observation-data/v1", "observations": []},
        {},
        revision_id="coordinated-selection-r0",
    )
    publish = catalog.publish_latest

    def interrupt_selection_publish(**kwargs):
        if kwargs["source_key"].startswith("pipeline-selection:"):
            raise OSError("coordinated selection index interruption")
        return publish(**kwargs)

    monkeypatch.setattr(catalog, "publish_latest", interrupt_selection_publish)
    next_id = "coordinated-selection-r1"
    pointer = {"node_id": "coordinated-selection-node", "revision_id": next_id}
    with pytest.raises(OSError, match="coordinated selection index interruption"):
        PipelineNodeTransactions(nodes).commit(
            "coordinated-selection-gap",
            node_updates=[
                {
                    "node_id": "coordinated-selection-node",
                    "expected_revision_id": initial.revision_id,
                    "revision_id": next_id,
                    "content": {
                        "schema_version": "table-observation-data/v1",
                        "observations": [],
                    },
                    "metadata": {"revision": 1},
                }
            ],
            selection_updates=[
                {
                    "recording_id": RECORDING_ID,
                    "content_type": "table_observations",
                    "expected_revision": 0,
                    "selected_generated": pointer,
                    "selected_completed_reference": None,
                }
            ],
        )
    monkeypatch.setattr(catalog, "publish_latest", publish)

    restarted = create_test_app(app.state.settings, recording_catalog_test_activation=True)
    recovered = restarted.state.recording_catalog_index.read(RECORDING_ID)
    assert recovered is not None
    assert recovered["metadata"]["selection:table_observations"] == {
        "selected_generated": pointer,
        "selected_completed_reference": None,
    }


def test_production_default_recordings_route_keeps_existing_pipeline_reader(tmp_path, monkeypatch):
    client, app = _backend(tmp_path)
    with client:
        recording = app.state.recording_bundle_store.get_metadata(RECORDING_ID)
        assert recording is not None
        source = RecordingVideoSource(
            recording_id=RECORDING_ID,
            relative_path=f"recordings/{RECORDING_ID}/videos/video-both.mov",
            video_sha256=recording.source_sha256,
            byte_length=recording.video_byte_length,
            duration_us=1_000_000,
        ).to_mapping()
        app.state.pipeline_lineage_writer.node_store.create(
            "production-default-event-node",
            "Events",
            "events",
            source,
            {
                "schema_version": "event-data/v1",
                "events": [
                    {
                        "event_id": "event-1",
                        "event_type": "card_state_changed",
                        "start_us": 0,
                        "end_us": 1,
                    }
                ],
            },
            {},
        )

        def unexpected_catalog_read(_recording_id):
            raise AssertionError("the production-default route read the catalog")

        monkeypatch.setattr(app.state.recording_catalog_index, "read", unexpected_catalog_read)
        response = client.get("/v1/recordings")
        assert response.status_code == 200, response.text
        row = next(
            item for item in response.json()["recordings"] if item["recording_id"] == RECORDING_ID
        )
        states = {stage["key"]: stage["state"] for stage in row["pipeline_status"]["stages"]}
        assert states["events"] == "data-available"
