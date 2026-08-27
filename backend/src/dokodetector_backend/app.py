"""FastAPI application factory."""

import os
import tempfile

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from dokodetector_backend.api import router
from dokodetector_backend.config import Settings
from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.persistence import EvidencePackagePersister
from dokodetector_backend.recording_repository import TrainingRecordingRepository
from dokodetector_backend.recording_storage import TrainingRecordingStorage
from dokodetector_backend.repository import EvidenceRepository, create_database_engine
from dokodetector_backend.storage import EvidenceStorage
from dokodetector_backend.training_recording_api import router as training_recording_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local backend application."""

    app_settings = settings or Settings()
    app = FastAPI(title="DokoDetector Backend", version="0.1.0")
    app.state.settings = app_settings
    app.state.engine = create_database_engine(app_settings.database_url)
    app.state.repository = EvidenceRepository(app.state.engine)
    app.state.storage = EvidenceStorage(app_settings.evidence_root)
    app.state.persister = EvidencePackagePersister(app.state.repository, app.state.storage)
    app.state.training_repository = TrainingRecordingRepository(app.state.engine)
    app.state.training_storage = TrainingRecordingStorage(app_settings.evidence_root)
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(training_recording_router)

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
            _check_evidence_directory(app.state.storage.evidence_root)
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
