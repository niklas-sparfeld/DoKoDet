"""The recording row carries identity and selected-data metadata only."""

import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.recording_folder_store import RecordingFolderStore
from dokodetector_backend.recordings_api import (
    RecordingListResponse,
    RecordingSelectionSummary,
    RecordingSummary,
)


def test_recording_row_does_not_expose_process_history() -> None:
    selections = [
        RecordingSelectionSummary(
            content_type=content_type,
            state="not-selected",
            selected_generated=None,
            selected_completed_reference=None,
        )
        for content_type in (
            "events",
            "visible_cards",
            "virtual_scenes",
            "card_scene_proposals",
            "visual_identities",
            "table_observations",
        )
    ]
    row = RecordingSummary(
        recording_id="recording-growth",
        source_asset_id="source-growth",
        video_id="video-growth",
        session_id="session-growth",
        display_name="round.mov",
        received_at=datetime(2026, 11, 10, tzinfo=UTC),
        thumbnail_url="/v1/repository-bundles/recording-growth/thumbnail",
        metadata_state="available",
        selections=selections,
    )

    response = RecordingListResponse(recordings=[row]).model_dump(mode="json")
    payload = response["recordings"][0]
    assert set(payload) == {
        "recording_id",
        "source_asset_id",
        "video_id",
        "session_id",
        "display_name",
        "received_at",
        "thumbnail_url",
        "metadata_state",
        "selections",
    }
    assert len(payload["selections"]) == 6


@pytest.mark.parametrize(
    "history_family",
    ("node_versions", "lineage", "runs", "analyses", "packages", "proposals"),
)
def test_list_reads_do_not_grow_with_independent_history_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, history_family: str
) -> None:
    """Tenfold history growth does not change list file opens, bytes, or directory visits."""
    repository_root = Path(__file__).parents[2]
    recording_id = "recording-both"
    recording_root = tmp_path / "recordings"
    recording_transport = tmp_path / "transport" / recording_id
    shutil.copytree(repository_root / "fixtures/repository-bundle/v1/both", recording_transport)
    RecordingFolderStore(recording_root).publish_bundle(
        recording_transport, recording_id=recording_id
    )
    settings = Settings(
        _env_file=None,
        repository_root=repository_root,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        repository_intake_root=recording_root,
        recordings_root=recording_root,
        evidence_package_intake_root=tmp_path / "packages",
        pending_video_root=tmp_path / "incoming",
        frontend_dist=tmp_path / "frontend",
    )
    app = create_test_app(settings)
    recording_bundle = recording_root / recording_id
    node_store = app.state.pipeline_selection_store.node_store
    node_store.create(
        "growth-node",
        "History growth",
        "events",
        {
            "schema_version": "recording-video/v1",
            "recording_id": recording_id,
            "relative_path": "data/intake/recordings/recording-both/video.mov",
            "video_sha256": "a" * 64,
            "byte_length": 100,
            "duration_us": 10_000_000,
        },
        {"schema_version": "event-data/v1", "events": []},
        {},
    )
    history_root = {
        "node_versions": node_store.revision_path("growth-node", "first-revision").parent,
        "lineage": app.state.pipeline_selection_store.node_store.root / ".lineage-runs",
        "runs": tmp_path / "operations/pipeline/runs",
        "analyses": tmp_path / "operations/round-analyses",
        "packages": tmp_path / "packages",
        "proposals": recording_bundle / "proposal-inputs",
    }[history_family]
    history_root.mkdir(parents=True, exist_ok=True)

    def grow(start: int, count: int) -> None:
        for index in range(start, start + count):
            path = history_root / f"growth-{index:04d}"
            if history_family in ("node_versions", "runs", "analyses", "packages"):
                path.mkdir(parents=True, exist_ok=True)
                document = {
                    "node_versions": "revision.json",
                    "runs": "request.json",
                    "analyses": "input.json",
                    "packages": "manifest.json",
                }[history_family]
                (path / document).write_text('{"history":true}')
            elif history_family == "lineage":
                path.with_suffix(".json").write_text('{"history":true}')
            else:
                path.with_suffix(".json").write_text('{"proposal":true}')
            if history_family == "runs":
                automated_path = (
                    tmp_path
                    / "operations/pipeline/automated-runs/runs"
                    / f"growth-{index:04d}.json"
                )
                automated_path.parent.mkdir(parents=True, exist_ok=True)
                automated_path.write_text('{"history":true}')

    def measure(client: TestClient) -> tuple[dict[str, int], bytes]:
        counts = {"opens": 0, "bytes": 0, "directory_visits": 0}
        original_open = Path.open
        original_iterdir = Path.iterdir

        class TrackedFile:
            def __init__(self, file):
                self.file = file

            def __enter__(self):
                self.file.__enter__()
                return self

            def __exit__(self, *args):
                return self.file.__exit__(*args)

            def read(self, size=-1):
                raw = self.file.read(size)
                counts["bytes"] += len(raw)
                return raw

            def __getattr__(self, name):
                return getattr(self.file, name)

        def tracked_open(path: Path, *args, **kwargs):
            try:
                path.relative_to(tmp_path)
            except ValueError:
                return original_open(path, *args, **kwargs)
            counts["opens"] += 1
            return TrackedFile(original_open(path, *args, **kwargs))

        def tracked_iterdir(path: Path):
            try:
                path.relative_to(tmp_path)
            except ValueError:
                return original_iterdir(path)
            counts["directory_visits"] += 1
            return original_iterdir(path)

        with monkeypatch.context() as patcher:
            patcher.setattr(Path, "open", tracked_open)
            patcher.setattr(Path, "iterdir", tracked_iterdir)
            response = client.get("/v1/recordings")
        assert response.status_code == 200, response.text
        assert len(response.content) < 20_000
        return counts, response.content

    with TestClient(app) as client:
        grow(0, 10)
        low_counts, low_response = measure(client)
        grow(10, 90)
        high_counts, high_response = measure(client)

    assert high_counts == low_counts
    assert high_response == low_response
    assert low_counts["opens"] == 8
    assert low_counts["directory_visits"] == 1
    assert low_counts["bytes"] == (recording_bundle / "recording.json").stat().st_size
    assert len(high_response) < 20_000


def test_list_reads_during_concurrent_selection_updates_are_atomic(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[2]
    recording_id = "recording-both"
    recording_root = tmp_path / "recordings"
    recording_transport = tmp_path / "transport" / recording_id
    shutil.copytree(repository_root / "fixtures/repository-bundle/v1/both", recording_transport)
    RecordingFolderStore(recording_root).publish_bundle(
        recording_transport, recording_id=recording_id
    )
    app = create_test_app(
        Settings(
            _env_file=None,
            repository_root=repository_root,
            evidence_root=tmp_path / "runtime",
            operations_root=tmp_path / "operations",
            repository_intake_root=recording_root,
            recordings_root=recording_root,
            evidence_package_intake_root=tmp_path / "packages",
            pending_video_root=tmp_path / "incoming",
            frontend_dist=tmp_path / "frontend",
        )
    )
    selection_store = app.state.pipeline_selection_store
    node_store = selection_store.node_store
    source = {
        "schema_version": "recording-video/v1",
        "recording_id": recording_id,
        "relative_path": "data/intake/recordings/recording-both/video.mov",
        "video_sha256": "a" * 64,
        "byte_length": 100,
        "duration_us": 10_000_000,
    }
    revisions = [
        node_store.create(
            f"events-{index}",
            "Events",
            "events",
            source,
            {"schema_version": "event-data/v1", "events": []},
            {},
        )
        for index in range(2)
    ]
    pointers = [
        {"node_id": f"events-{index}", "revision_id": revision.revision_id}
        for index, revision in enumerate(revisions)
    ]
    transaction_pending = Event()
    continue_transaction = Event()

    def pause_after_locator(boundary: str) -> None:
        if boundary == "locator":
            transaction_pending.set()
            assert continue_transaction.wait(timeout=5)

    node_store._after_durable_boundary = pause_after_locator

    def writer() -> None:
        for index in range(20):
            selection_store.update_exact(
                recording_id,
                "events",
                expected_revision=index,
                selected_generated=pointers[index % 2],
                selected_completed_reference=None,
            )

    def read(client: TestClient) -> list[dict]:
        response = client.get("/v1/recordings")
        assert response.status_code == 200, response.text
        return response.json()["recordings"][0]["selections"]

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        writer_task = pool.submit(writer)
        assert transaction_pending.wait(timeout=5)
        pending = read(client)
        assert all(item["state"] == "unavailable" for item in pending)
        continue_transaction.set()
        observations = [read(client) for _ in range(30)]
        writer_task.result()

    for selections in observations:
        events = next(item for item in selections if item["content_type"] == "events")
        assert events["state"] in {"not-selected", "selected", "unavailable"}
        if events["state"] == "selected":
            assert events["selected_generated"] in pointers
        elif events["state"] == "unavailable":
            assert all(item["state"] == "unavailable" for item in selections)
        else:
            assert all(
                item["state"] == "not-selected"
                for item in selections
                if item["content_type"] != "events"
            )
