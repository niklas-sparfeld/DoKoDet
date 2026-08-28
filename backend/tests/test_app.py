from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from starlette.requests import ClientDisconnect

from alembic import command
from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.errors import ContractError

BACKEND_ROOT = Path(__file__).parents[1]


def test_health_routes_report_process_status() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))

    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}


def test_readiness_reports_an_unusable_evidence_directory(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    evidence_root = tmp_path / "evidence-root"
    evidence_root.write_text("not a directory")
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=evidence_root,
    )

    response = TestClient(create_app(settings)).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_factory_exposes_injected_settings() -> None:
    settings = Settings(_env_file=None, evidence_root=Path("test-evidence"))

    app = create_app(settings)

    assert app.state.settings is settings


@pytest.mark.parametrize("working_directory", [BACKEND_ROOT.parent, BACKEND_ROOT])
def test_factory_resolves_default_storage_from_repository_root(
    tmp_path: Path, monkeypatch, working_directory: Path
) -> None:
    monkeypatch.chdir(working_directory)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'repository.sqlite'}",
        evidence_root=Path(".runtime"),
        repository_intake_root=Path("data/intake/recordings"),
    )

    app = create_app(settings)

    assert settings.repository_root == BACKEND_ROOT.parent
    assert app.state.storage.evidence_root == BACKEND_ROOT.parent / ".runtime" / "evidence"
    assert app.state.repository_bundle_storage.root == (
        BACKEND_ROOT.parent / "data" / "intake" / "recordings"
    )
    assert not (BACKEND_ROOT / "backend" / "data" / "intake").exists()


def test_factory_applies_pending_repository_bundle_migration(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0003_training_recordings")

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "evidence",
        repository_intake_root=tmp_path / "intake",
    )

    app = create_app(settings)

    assert inspect(app.state.engine).has_table("repository_bundles")


def test_contract_errors_use_a_stable_response_shape() -> None:
    app = create_app(Settings(_env_file=None))

    @app.get("/test-contract-error")
    def contract_error_route() -> None:
        raise ContractError("invalid_manifest", "The manifest failed validation.")

    response = TestClient(app).get("/test-contract-error")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_manifest",
            "message": "The manifest failed validation.",
            "details": [],
        }
    }


def test_client_disconnect_returns_499() -> None:
    app = create_app(Settings(_env_file=None))

    @app.get("/test-client-disconnect")
    async def client_disconnect_route() -> None:
        raise ClientDisconnect()

    response = TestClient(app).get("/test-client-disconnect")

    assert response.status_code == 499
    assert response.content == b""
