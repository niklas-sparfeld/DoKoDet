"""FastAPI application factory."""

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from dokodetector_backend.api import router
from dokodetector_backend.config import Settings
from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.pending_video_api import router as pending_video_router
from dokodetector_backend.pending_video_storage import PendingVideoStorage
from dokodetector_backend.persistence import EvidencePackagePersister
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer
from dokodetector_backend.repository import (
    EvidenceRepository,
    create_database_engine,
    upgrade_database,
)
from dokodetector_backend.repository_bundle_api import router as repository_bundle_router
from dokodetector_backend.repository_bundle_repository import RepositoryBundleRepository
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.storage import EvidenceStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local backend application."""

    app_settings = settings or Settings()
    upgrade_database(Path(__file__).resolve().parents[2], app_settings.database_url)
    app = FastAPI(title="DokoDetector Backend", version="0.1.0")
    app.state.settings = app_settings
    app.state.engine = create_database_engine(app_settings.database_url)
    app.state.repository = EvidenceRepository(app.state.engine)
    app.state.storage = EvidenceStorage(app_settings.evidence_root)
    app.state.evidence_package_storage = EvidencePackageStorage(
        app_settings.evidence_package_intake_root
    )
    app.state.persister = EvidencePackagePersister(
        app.state.repository,
        app.state.evidence_package_storage,
    )
    app.state.repository_bundle_repository = RepositoryBundleRepository(app.state.engine)
    app.state.repository_bundle_storage = RepositoryBundleStorage(
        app_settings.repository_intake_root
    )
    app.state.pending_video_storage = PendingVideoStorage(app_settings.pending_video_root)
    app.state.analyzer = create_local_poc_analyzer()
    app.state.repository.rebuild_from_intake(app.state.evidence_package_storage)
    app.state.repository_bundle_repository.rebuild_from_intake(app.state.repository_bundle_storage)
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(repository_bundle_router)
    app.include_router(pending_video_router)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        """Report that the process is running."""

        return {"status": "ok"}

    @app.get("/health/ready", response_model=None)
    def readiness() -> dict[str, str] | JSONResponse:
        """Check the local database and evidence directory."""

        try:
            with app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            _check_evidence_directory(app.state.storage.table_observations_root)
            _check_evidence_directory(app.state.evidence_package_storage.root)
            _check_evidence_directory(app.state.repository_bundle_storage.root)
            _check_evidence_directory(app.state.pending_video_storage.root)
        except (OSError, SQLAlchemyError):
            return JSONResponse(status_code=503, content={"status": "not_ready"})

        return {"status": "ok"}

    return app


def _check_evidence_directory(directory: os.PathLike[str] | str) -> None:
    """Verify that the evidence directory supports local reads and writes."""

    evidence_directory = os.fspath(directory)
    os.makedirs(evidence_directory, exist_ok=True)
    if not os.path.isdir(evidence_directory) or not os.access(
        evidence_directory, os.R_OK | os.X_OK | os.W_OK
    ):
        raise OSError("The evidence directory is not accessible.")

    with tempfile.NamedTemporaryFile(
        mode="w+b", prefix=".readiness-", dir=evidence_directory
    ) as probe:
        probe.write(b"ready")
        probe.flush()
        probe.seek(0)
        if probe.read() != b"ready":
            raise OSError("The evidence directory failed its write check.")
