"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.staticfiles import StaticFiles

from dokodetector_backend.api import router
from dokodetector_backend.config import Settings
from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.gemini_analyzer import create_gemini_analyzer
from dokodetector_backend.logging_config import get_or_create_request_id, log_event
from dokodetector_backend.pending_video_api import router as pending_video_router
from dokodetector_backend.pending_video_storage import PendingVideoStorage
from dokodetector_backend.persistence import EvidencePackagePersister
from dokodetector_backend.repository import (
    EvidenceRepository,
    RoundAnalysisRepository,
    create_database_engine,
    upgrade_database,
)
from dokodetector_backend.repository_bundle_api import router as repository_bundle_router
from dokodetector_backend.repository_bundle_repository import RepositoryBundleRepository
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.round_analysis_api import router as round_analysis_router
from dokodetector_backend.round_analysis_service import RoundAnalysisService
from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage
from dokodetector_backend.storage import EvidenceStorage

if TYPE_CHECKING:
    from table_evidence_analyzer import TableEvidenceAnalyzer


LOGGER = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    run_round_analysis_synchronously: bool = False,
    analyzer: TableEvidenceAnalyzer | None = None,
) -> FastAPI:
    """Create the local backend application."""

    app_settings = settings or Settings()
    upgrade_database(Path(__file__).resolve().parents[2], app_settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await application.state.round_analysis_service.start()
        log_event(
            LOGGER,
            logging.INFO,
            "backend_started",
            host=app_settings.server_host,
            port=app_settings.server_port,
        )
        try:
            yield
        finally:
            await application.state.round_analysis_service.stop()

    app = FastAPI(title="DokoDetector Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.engine = create_database_engine(app_settings.database_url)
    app.state.repository = EvidenceRepository(app.state.engine)
    app.state.round_analysis_repository = RoundAnalysisRepository(app.state.engine)
    app.state.storage = EvidenceStorage(app_settings.evidence_root)
    app.state.round_analysis_storage = RoundAnalysisArtifactStorage(app_settings.evidence_root)
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
    app.state.readiness_state = "unknown"
    app.state.analyzer = analyzer or create_gemini_analyzer(app_settings)
    app.state.run_round_analysis_synchronously = run_round_analysis_synchronously
    app.state.repository.rebuild_from_intake(app.state.evidence_package_storage)
    app.state.repository_bundle_repository.rebuild_from_intake(app.state.repository_bundle_storage)
    app.state.round_analysis_repository.fail_non_terminal()
    app.state.round_analysis_service = RoundAnalysisService(
        app.state.round_analysis_repository,
        app.state.repository,
        app.state.evidence_package_storage,
        app.state.storage,
        app.state.round_analysis_storage,
        app.state.repository_bundle_repository,
        app.state.analyzer,
    )
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(repository_bundle_router)
    app.include_router(pending_video_router)
    app.include_router(round_analysis_router)
    _mount_frontend(app, app_settings.frontend_dist)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        """Report that the process is running."""

        return {"status": "ok"}

    @app.get("/health/ready", response_model=None)
    def readiness(request: Request) -> dict[str, str] | JSONResponse:
        """Check the local database and evidence directory."""

        request_id = get_or_create_request_id(request)
        try:
            with app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            _check_evidence_directory(app.state.storage.table_observations_root)
            _check_evidence_directory(app.state.round_analysis_storage.root)
            _check_evidence_directory(app.state.evidence_package_storage.root)
            _check_evidence_directory(app.state.repository_bundle_storage.root)
            _check_evidence_directory(app.state.pending_video_storage.root)
        except (OSError, SQLAlchemyError):
            log_event(
                LOGGER,
                logging.DEBUG,
                "backend_readiness_checked",
                request_id=request_id,
                result="not_ready",
            )
            if app.state.readiness_state != "not_ready":
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "backend_not_ready",
                    request_id=request_id,
                    reason="local_dependency_unavailable",
                )
            app.state.readiness_state = "not_ready"
            return JSONResponse(status_code=503, content={"status": "not_ready"})

        log_event(
            LOGGER,
            logging.DEBUG,
            "backend_readiness_checked",
            request_id=request_id,
            result="ready",
        )
        if app.state.readiness_state != "ready":
            log_event(LOGGER, logging.INFO, "backend_ready", request_id=request_id)
        app.state.readiness_state = "ready"
        return {"status": "ok"}

    return app


def _mount_frontend(app: FastAPI, frontend_dist: Path) -> None:
    """Serve the built browser application when its package is present."""

    entrypoint = frontend_dist / "index.html"
    assets = frontend_dist / "assets"
    if not entrypoint.is_file() or not assets.is_dir():
        return

    app.mount(
        "/round-analyses/assets",
        StaticFiles(directory=assets),
        name="frontend-assets",
    )

    @app.get("/round-analyses/{analysis_id}", include_in_schema=False)
    def frontend_entrypoint(analysis_id: str) -> FileResponse:
        """Return the SPA entry document for a direct analysis load or refresh."""

        del analysis_id
        return FileResponse(
            entrypoint,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )


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
