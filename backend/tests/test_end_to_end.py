import hashlib
import json
from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient
from test_api import load_upload_fixture, multipart_parts

from dokodetector_backend.config import Settings
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.repository import EvidenceRepository, upgrade_database

BACKEND_ROOT = Path(__file__).parents[1]


def test_shared_fixture_round_trip_uses_http_sqlite_and_filesystem(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        repository_root=tmp_path,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
        evidence_package_intake_root=tmp_path / "repository-intake" / "evidence-packages",
    )
    app = create_test_app(settings)
    repository = EvidenceRepository(app.state.engine)
    storage = EvidencePackageStorage(settings.evidence_package_intake_root)
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    files = multipart_parts(manifest_bytes, frame_sources, video_source)
    assert video_source is not None

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ok"}
        upload = client.put(
            f"/v1/evidence-packages/{payload['package_id']}",
            files=files,
        )
        read_back = client.get(f"/v1/evidence-packages/{payload['package_id']}")

    assert upload.status_code == 201
    assert read_back.status_code == 200
    metadata = read_back.json()
    assert metadata["package_id"] == payload["package_id"]
    assert metadata["session"] == payload["session"]
    assert metadata["event"] == payload["event"]
    assert metadata["manifest"] == json.loads(manifest_bytes)
    assert metadata["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()

    stored = repository.get_package(payload["package_id"])
    assert stored is not None
    package_path = storage.package_path(payload["package_id"])
    assert (package_path / "evidence-manifest.json").read_bytes() == manifest_bytes
    for frame in payload["frames"]:
        stored_frame_path = package_path / "frames" / f"{frame['part_name']}.jpg"
        assert stored_frame_path.read_bytes() == frame_sources[frame["part_name"]]
