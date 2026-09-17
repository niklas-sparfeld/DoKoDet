import hashlib
import json
import shutil
from pathlib import Path
from uuid import UUID

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient
from table_evidence_analyzer import TableObservation, canonical_json_bytes, parse_observation_bytes

from dokodetector_backend.analyzer_runner import AnalyzerRunner
from dokodetector_backend.config import Settings
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.evidence_package_store import EvidencePackageStore
from dokodetector_backend.storage import EvidenceStorage
from dokodetector_backend.table_observation_store import (
    TableObservationConflict,
    TableObservationStore,
)

PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
REPOSITORY_FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "repository-intake"
    / "v1"
    / "evidence-package-complete"
)
OBSERVATION_FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "game-engine"
    / "v1"
    / "observations"
    / "minimal.json"
)


def test_package_store_reads_complete_bundles_without_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "evidence-packages"
    shutil.copytree(REPOSITORY_FIXTURE, root / str(PACKAGE_ID))
    store = EvidencePackageStore(EvidencePackageStorage(root))

    first = store.get(PACKAGE_ID)
    restarted = EvidencePackageStore(EvidencePackageStorage(root)).get(PACKAGE_ID)

    assert first is not None
    assert restarted == first
    assert store.get_by_logical_event(first.session_id, first.event_sequence) == first
    assert store.list() == (first,)


def test_metadata_reads_do_not_open_media_members(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "evidence-packages"
    shutil.copytree(REPOSITORY_FIXTURE, root / str(PACKAGE_ID))
    store = EvidencePackageStore(EvidencePackageStorage(root))
    original_open = Path.open

    def reject_media_open(path: Path, *args, **kwargs):
        if path.suffix in {".jpg", ".mp4"}:
            raise AssertionError("metadata reads must not open media members")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_media_open)

    stored = store.get_metadata(PACKAGE_ID)
    listed = store.list_metadata()

    assert stored is not None
    assert listed == (stored,)


def test_package_store_accepts_harmless_extra_files(tmp_path: Path) -> None:
    root = tmp_path / "evidence-packages"
    package_root = root / str(PACKAGE_ID)
    shutil.copytree(REPOSITORY_FIXTURE, package_root)
    (package_root / "operator-note.txt").write_text("local note", encoding="utf-8")
    (package_root / ".DS_Store").write_bytes(b"finder metadata")
    store = EvidencePackageStore(EvidencePackageStorage(root))

    packages = store.list()

    assert [item.package_id for item in packages] == [PACKAGE_ID]


def test_package_storage_does_not_publish_without_bundle_manifest(tmp_path: Path) -> None:
    storage = EvidencePackageStorage(tmp_path / "evidence-packages")

    with storage.start_package(PACKAGE_ID) as upload:
        upload.write_part("frames/frame_00.jpg", b"frame")
        with pytest.raises(ValueError, match="manifest.json must be written"):
            upload.commit()

    assert not storage.package_path(PACKAGE_ID).exists()
    assert list(storage.root.glob(".upload-*")) == []


def test_package_store_excludes_incomplete_bundles_and_reports_diagnostics(
    tmp_path: Path, caplog
) -> None:
    root = tmp_path / "evidence-packages"
    package_root = root / str(PACKAGE_ID)
    shutil.copytree(REPOSITORY_FIXTURE, package_root)
    (package_root / "frames" / "frame_00.jpg").unlink()
    store = EvidencePackageStore(EvidencePackageStorage(root))

    assert store.get(PACKAGE_ID) is None
    assert store.list() == ()
    assert "evidence_package_catalog_skipped" in caplog.text


def test_observation_store_enforces_replay_and_analyzer_uniqueness(tmp_path: Path) -> None:
    observation_payload = json.loads(OBSERVATION_FIXTURE.read_bytes())
    observation_payload["observation_id"] = "observation-filesystem-001"
    observation_payload["source"]["package_id"] = str(PACKAGE_ID)
    observation = TableObservation.model_validate(observation_payload)
    observation_bytes = canonical_json_bytes(observation)
    store = TableObservationStore(EvidenceStorage(tmp_path / "runtime"))

    first, created = store.publish(observation, observation_bytes)
    replay, replay_created = store.publish(observation, observation_bytes)

    assert created is True
    assert replay_created is False
    assert replay == first
    assert store.get(first.observation_id) == first
    assert store.list_for_package(PACKAGE_ID) == (first,)
    assert first.observation_sha256 == hashlib.sha256(observation_bytes).hexdigest()
    assert parse_observation_bytes(first.observation_json.encode()) == observation

    changed_id = TableObservation.model_validate(
        observation_payload | {"observation_id": "observation-filesystem-002"}
    )
    with pytest.raises(TableObservationConflict):
        store.publish(changed_id, canonical_json_bytes(changed_id))


def test_observation_store_reloads_from_files_without_sql_metadata(tmp_path: Path) -> None:
    observation_payload = json.loads(OBSERVATION_FIXTURE.read_bytes())
    observation_payload["observation_id"] = "observation-filesystem-restart"
    observation_payload["source"]["package_id"] = str(PACKAGE_ID)
    observation = TableObservation.model_validate(observation_payload)
    storage = EvidenceStorage(tmp_path / "runtime")
    TableObservationStore(storage).publish(observation, canonical_json_bytes(observation))

    reloaded = TableObservationStore(storage).get(observation.observation_id)

    assert reloaded is not None
    assert reloaded.observation_json.encode() == canonical_json_bytes(observation)
    assert reloaded.relative_path == (
        f"table-observations/{observation.observation_id}/observation.json"
    )


def test_api_and_analyzer_use_only_filesystem_metadata(tmp_path: Path) -> None:
    from test_api import load_upload_fixture, multipart_parts

    settings = Settings(
        _env_file=None,
        evidence_root=tmp_path / "runtime",
        evidence_package_intake_root=tmp_path / "intake" / "evidence-packages",
    )
    app = create_test_app(settings)

    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture(
        "example-complete"
    )
    with TestClient(app) as client:
        uploaded = client.put(
            f"/v1/evidence-packages/{payload['package_id']}",
            files=multipart_parts(manifest_bytes, frame_sources, video_source),
        )
        metadata = client.get(f"/v1/evidence-packages/{payload['package_id']}")
        observation = AnalyzerRunner(
            app.state.evidence_package_store,
            app.state.analyzer,
            observation_store=app.state.table_observation_store,
        ).run_once(payload["package_id"])
        observations = client.get(
            f"/v1/evidence-packages/{payload['package_id']}/table-observations"
        )

    assert uploaded.status_code == 201
    assert metadata.status_code == 200
    assert observation is not None
    assert observations.status_code == 200
