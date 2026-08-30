from pathlib import Path

import pytest
from alembic.config import Config
from app_factory import create_test_app
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from starlette.requests import ClientDisconnect

from alembic import command
from dokodetector_backend.app import create_app
from dokodetector_backend.config import ConfigurationError, Settings
from dokodetector_backend.errors import ContractError
from dokodetector_backend.repository import (
    RoundAnalysisRepository,
    StoredRoundAnalysis,
    create_database_engine,
    upgrade_database,
)
from dokodetector_backend.round_analysis_contract import RoundAnalysisCreateRequest

BACKEND_ROOT = Path(__file__).parents[1]


def test_health_routes_report_process_status() -> None:
    client = TestClient(create_test_app(Settings(_env_file=None)))

    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}


def test_packaged_frontend_serves_entry_route_and_hashed_assets(tmp_path: Path) -> None:
    frontend_dist = tmp_path / "frontend-dist"
    assets = frontend_dist / "assets"
    assets.mkdir(parents=True)
    (frontend_dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root">smoke</div>'
        '<script type="module" src="/round-analyses/assets/index-test.js"></script>'
        "</body></html>",
        encoding="utf-8",
    )
    (assets / "index-test.js").write_text("console.log('smoke');", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'frontend.sqlite'}",
        evidence_root=tmp_path / "runtime",
        frontend_dist=frontend_dist,
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )

    client = TestClient(create_test_app(settings))

    entry = client.get("/round-analyses/550e8400-e29b-41d4-a716-446655440033")
    refresh = client.get("/round-analyses/550e8400-e29b-41d4-a716-446655440033")
    asset = client.get("/round-analyses/assets/index-test.js")

    assert entry.status_code == 200
    assert entry.headers["content-type"].startswith("text/html")
    assert "id=\"root\"" in entry.text
    assert refresh.status_code == 200
    assert asset.status_code == 200
    assert asset.text == "console.log('smoke');"


def test_readiness_reports_an_unusable_evidence_directory(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    evidence_root = tmp_path / "evidence-root"
    evidence_root.write_text("not a directory")
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=evidence_root,
    )

    response = TestClient(create_test_app(settings)).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_factory_exposes_injected_settings() -> None:
    settings = Settings(_env_file=None, evidence_root=Path("test-evidence"))

    app = create_test_app(settings)

    assert app.state.settings is settings


def test_factory_configures_the_gemini_analyzer(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        database_url=f"sqlite:///{tmp_path / 'gemini.sqlite'}",
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
    )
    app = create_app(settings)

    assert app.state.analyzer.name == "visible-card-table-analyzer"
    assert app.state.analyzer.provider.provider.name == "gemini"
    assert app.state.analyzer.classifier.classifier.name == "gemini"


def test_factory_requires_the_gemini_api_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'missing-key.sqlite'}",
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
    )

    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY is required"):
        create_app(settings)


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

    app = create_test_app(settings)

    assert settings.repository_root == BACKEND_ROOT.parent
    assert app.state.storage.evidence_root == BACKEND_ROOT.parent / ".runtime" / "evidence"
    assert app.state.repository_bundle_storage.root == (
        BACKEND_ROOT.parent / "data" / "intake" / "recordings"
    )
    assert app.state.pending_video_storage.root == (
        BACKEND_ROOT.parent / "data" / "incoming" / "videos"
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

    app = create_test_app(settings)

    assert inspect(app.state.engine).has_table("repository_bundles")


def test_factory_converts_interrupted_round_analysis_to_failed(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    request = RoundAnalysisCreateRequest.model_validate(
        {
            "analysis_id": "00000000-0000-0000-0000-000000000032",
            "recording_id": "recording-0032",
            "round_id": "round-0032",
            "session_id": "00000000-0000-0000-0000-000000000033",
            "round_setup": {
                "game_id": "game-0032",
                "round_id": "round-0032",
                "ruleset": {"name": "doko-normal", "version": "v1"},
                "deck_variant": "doko-40-v1",
                "active_players": ["seat-1", "seat-2", "seat-3", "seat-4"],
                "dealer": "seat-1",
                "first_trick_leader": "seat-2",
            },
            "evidence_package_ids": ["00000000-0000-0000-0000-000000000034"],
            "search": {
                "max_missing_plays": 2,
                "max_hypotheses": 8,
                "max_search_nodes": 1000,
            },
        }
    )
    repository = RoundAnalysisRepository(create_database_engine(database_url))
    repository.insert(StoredRoundAnalysis.from_request(request))

    app = create_test_app(
        Settings(
            _env_file=None,
            database_url=database_url,
            evidence_root=tmp_path / "runtime",
            repository_intake_root=tmp_path / "recordings",
            evidence_package_intake_root=tmp_path / "evidence-packages",
        )
    )

    stored = app.state.round_analysis_repository.get(request.analysis_id)
    assert stored is not None
    assert stored.state == "failed"
    assert stored.error == "The analysis did not finish before the backend restarted."


def test_contract_errors_use_a_stable_response_shape() -> None:
    app = create_test_app(Settings(_env_file=None))

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
    app = create_test_app(Settings(_env_file=None))

    @app.get("/test-client-disconnect")
    async def client_disconnect_route() -> None:
        raise ClientDisconnect()

    response = TestClient(app).get("/test-client-disconnect")

    assert response.status_code == 499
    assert response.content == b""
