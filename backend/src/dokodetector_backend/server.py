"""Local backend process entry point."""

import logging
from contextlib import nullcontext

import uvicorn

from dokodetector_backend.bonjour import (
    BonjourAdvertiser,
    build_service_info,
    discover_local_hostname,
    discover_local_ipv4_address,
)
from dokodetector_backend.config import Settings

LOGGER = logging.getLogger(__name__)


def run() -> None:
    """Run the HTTP server and advertise it on the local network."""

    _configure_logging()
    settings = Settings()
    hostname = settings.bonjour_hostname or discover_local_hostname()
    endpoint_host = settings.bonjour_address or discover_local_ipv4_address()
    info = build_service_info(
        service_name=settings.bonjour_name,
        hostname=hostname,
        port=settings.server_port,
        endpoint_host=endpoint_host,
    )
    advertisement = BonjourAdvertiser(info) if settings.bonjour_enabled else nullcontext()

    with advertisement:
        if settings.bonjour_enabled:
            LOGGER.info(
                "Advertised DokoDetector backend: service=%s type=%s endpoint=%s",
                info.name,
                info.type,
                info.properties[b"url"].decode(),
            )
            if endpoint_host is None:
                LOGGER.warning(
                    "Could not find a private IPv4 address. "
                    "The advertised endpoint uses the .local hostname. "
                    "Set BONJOUR_ADDRESS to a reachable private IPv4 address if needed."
                )
        else:
            LOGGER.warning("Bonjour advertisement is disabled.")
        LOGGER.info("Starting HTTP server on %s:%s", settings.server_host, settings.server_port)
        uvicorn.run(
            "dokodetector_backend.app:create_app",
            factory=True,
            host=settings.server_host,
            port=settings.server_port,
        )


def _configure_logging() -> None:
    """Enable useful startup logs before Uvicorn configures its own loggers."""

    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    run()
