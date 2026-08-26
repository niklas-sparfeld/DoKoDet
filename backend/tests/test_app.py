from pathlib import Path

from fastapi.testclient import TestClient

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.errors import ContractError


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
