"""Local backend process entry point."""

import logging
from contextlib import nullcontext

import uvicorn

from dokodetector_backend.bonjour import (
    BonjourAdvertiser,
    build_service_info,
    discover_local_hostname,
)
from dokodetector_backend.config import Settings

LOGGER = logging.getLogger(__name__)


def run() -> None:
    """Run the HTTP server and advertise it on the local network."""

    settings = Settings()
    hostname = settings.bonjour_hostname or discover_local_hostname()
    info = build_service_info(
        service_name=settings.bonjour_name,
        hostname=hostname,
        port=settings.server_port,
    )
    advertisement = BonjourAdvertiser(info) if settings.bonjour_enabled else nullcontext()

    with advertisement:
        if settings.bonjour_enabled:
            LOGGER.info("Advertised DokoDetector backend at %s", info.properties[b"url"].decode())
        uvicorn.run(
            "dokodetector_backend.app:create_app",
            factory=True,
            host=settings.server_host,
            port=settings.server_port,
        )


if __name__ == "__main__":
    run()
