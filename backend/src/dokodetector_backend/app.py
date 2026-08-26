"""FastAPI application factory."""

from fastapi import FastAPI

from dokodetector_backend.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local backend application."""

    app_settings = settings or Settings()
    app = FastAPI(title="DokoDetector Backend", version="0.1.0")
    app.state.settings = app_settings

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        """Report that the process is running."""

        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness() -> dict[str, str]:
        """Report local readiness until storage checks are added in M4."""

        return {"status": "ok"}

    return app
