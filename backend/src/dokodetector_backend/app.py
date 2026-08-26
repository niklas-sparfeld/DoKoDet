"""FastAPI application factory."""

from fastapi import FastAPI

from dokodetector_backend.api import router
from dokodetector_backend.config import Settings
from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.persistence import EvidencePackagePersister
from dokodetector_backend.repository import EvidenceRepository, create_database_engine
from dokodetector_backend.storage import EvidenceStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local backend application."""

    app_settings = settings or Settings()
    app = FastAPI(title="DokoDetector Backend", version="0.1.0")
    app.state.settings = app_settings
    app.state.engine = create_database_engine(app_settings.database_url)
    app.state.repository = EvidenceRepository(app.state.engine)
    app.state.storage = EvidenceStorage(app_settings.evidence_root)
    app.state.persister = EvidencePackagePersister(app.state.repository, app.state.storage)
    register_error_handlers(app)
    app.include_router(router)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        """Report that the process is running."""

        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness() -> dict[str, str]:
        """Report local readiness until storage checks are added in M4."""

        return {"status": "ok"}

    return app
