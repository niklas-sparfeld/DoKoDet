"""Bonjour advertisement for the local backend."""

import socket
import subprocess
from collections.abc import Callable
from types import TracebackType

from zeroconf import ServiceInfo, Zeroconf

SERVICE_TYPE = "_dokodetector._tcp.local."
API_VERSION = "v1"


def discover_local_hostname(
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    socket_hostname: Callable[[], str] = socket.gethostname,
) -> str:
    """Get the host label that macOS publishes in the local Bonjour domain."""

    try:
        result = command_runner(
            ("scutil", "--get", "LocalHostName"),
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    return socket_hostname().split(".", maxsplit=1)[0]


def build_service_info(
    *,
    service_name: str,
    hostname: str,
    port: int,
) -> ServiceInfo:
    """Build the DNS-SD records that identify a compatible backend."""

    local_hostname = _local_hostname(hostname)
    base_url_hostname = local_hostname.removesuffix(".")
    return ServiceInfo(
        SERVICE_TYPE,
        f"{service_name}.{SERVICE_TYPE}",
        port=port,
        properties={
            "api": API_VERSION,
            "url": f"http://{base_url_hostname}:{port}",
        },
        server=local_hostname,
    )


class BonjourAdvertiser:
    """Register one Bonjour service for the lifetime of a context."""

    def __init__(
        self,
        info: ServiceInfo,
        *,
        zeroconf_factory: Callable[[], Zeroconf] = Zeroconf,
    ) -> None:
        self._info = info
        self._zeroconf_factory = zeroconf_factory
        self._zeroconf: Zeroconf | None = None
        self._registered = False

    def __enter__(self) -> "BonjourAdvertiser":
        zeroconf = self._zeroconf_factory()
        self._zeroconf = zeroconf
        try:
            zeroconf.register_service(self._info, allow_name_change=True)
            self._registered = True
        except BaseException:
            zeroconf.close()
            self._zeroconf = None
            raise
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._zeroconf is None:
            return
        try:
            if self._registered:
                self._zeroconf.unregister_service(self._info)
        finally:
            self._zeroconf.close()
            self._zeroconf = None
            self._registered = False


def _local_hostname(hostname: str) -> str:
    normalized = hostname.rstrip(".")
    if not normalized.lower().endswith(".local"):
        normalized = f"{normalized}.local"
    return f"{normalized}."
