import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.repository import EvidenceRepository, upgrade_database
from dokodetector_backend.storage import EvidenceStorage
from dokodetector_backend.upload_fixture import prepare_fixture

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v1"


def test_shared_fixture_round_trip_uses_http_sqlite_and_filesystem(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
    )
    app = create_app(settings)
    repository = EvidenceRepository(app.state.engine)
    storage = EvidenceStorage(settings.evidence_root)
    manifest_bytes, manifest, frame_sources = prepare_fixture(FIXTURE_ROOT / "example-complete")
    files = {
        "manifest": ("manifest.json", manifest_bytes, "application/json"),
        **{
            frame.part_name: (
                f"{frame.part_name}.jpg",
                frame_sources[frame.part_name],
                "image/jpeg",
            )
            for frame in manifest.frames
        },
    }

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ok"}
        upload = client.put(
            f"/v1/evidence-packages/{manifest.package_id}",
            files=files,
        )
        read_back = client.get(f"/v1/evidence-packages/{manifest.package_id}")

    assert upload.status_code == 201
    assert read_back.status_code == 200
    metadata = read_back.json()
    assert metadata["package_id"] == str(manifest.package_id)
    assert metadata["session"] == manifest.session.model_dump(mode="json")
    assert metadata["event"] == manifest.event.model_dump(mode="json")
    assert metadata["manifest"] == json.loads(manifest_bytes)
    assert metadata["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()

    stored = repository.get_package(manifest.package_id)
    assert stored is not None
    stored_manifest_path = storage.root / "evidence" / str(manifest.package_id) / "manifest.json"
    assert stored_manifest_path.read_bytes() == manifest_bytes
    for frame in manifest.frames:
        stored_frame_path = (
            storage.root
            / "evidence"
            / str(manifest.package_id)
            / "frames"
            / f"{frame.part_name}.jpg"
        )
        assert stored_frame_path.read_bytes() == frame_sources[frame.part_name]
