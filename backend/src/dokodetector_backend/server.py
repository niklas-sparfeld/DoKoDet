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
from dokodetector_backend.logging_config import configure_logging, log_event

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
            log_event(
                LOGGER,
                logging.INFO,
                "bonjour_advertised",
                service_name=info.name,
                service_type=info.type,
                endpoint=info.properties[b"url"].decode(),
            )
            if endpoint_host is None:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "bonjour_endpoint_fallback",
                    reason="private_ipv4_unavailable",
                )
        else:
            log_event(LOGGER, logging.WARNING, "bonjour_disabled")
        log_event(
            LOGGER,
            logging.INFO,
            "backend_http_starting",
            host=settings.server_host,
            port=settings.server_port,
        )
        uvicorn.run(
            "dokodetector_backend.app:create_app",
            factory=True,
            host=settings.server_host,
            port=settings.server_port,
        )


def _configure_logging() -> None:
    """Configure backend logging before Uvicorn constructs the application."""

    configure_logging()


if __name__ == "__main__":
    run()
