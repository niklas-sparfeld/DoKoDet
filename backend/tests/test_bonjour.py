import subprocess
from unittest.mock import Mock

from dokodetector_backend.bonjour import (
    BonjourAdvertiser,
    build_service_info,
    discover_local_hostname,
)


def test_service_info_advertises_the_api_endpoint() -> None:
    info = build_service_info(
        service_name="DokoDetector Test",
        hostname="test-mac",
        port=8123,
    )

    assert info.type == "_dokodetector._tcp.local."
    assert info.name == "DokoDetector Test._dokodetector._tcp.local."
    assert info.server == "test-mac.local."
    assert info.port == 8123
    assert info.properties == {
        b"api": b"v1",
        b"url": b"http://test-mac.local:8123",
    }


def test_advertiser_unregisters_and_closes_on_exit() -> None:
    zeroconf = Mock()
    info = build_service_info(
        service_name="DokoDetector Test",
        hostname="test-mac.local.",
        port=8000,
    )

    with BonjourAdvertiser(info, zeroconf_factory=lambda: zeroconf):
        zeroconf.register_service.assert_called_once_with(info, allow_name_change=True)

    zeroconf.unregister_service.assert_called_once_with(info)
    zeroconf.close.assert_called_once_with()


def test_advertiser_closes_when_registration_fails() -> None:
    zeroconf = Mock()
    zeroconf.register_service.side_effect = OSError("registration failed")
    info = build_service_info(
        service_name="DokoDetector Test",
        hostname="test-mac",
        port=8000,
    )

    try:
        with BonjourAdvertiser(info, zeroconf_factory=lambda: zeroconf):
            raise AssertionError("The context must not start.")
    except OSError as error:
        assert str(error) == "registration failed"
    else:
        raise AssertionError("The registration error was not raised.")

    zeroconf.unregister_service.assert_not_called()
    zeroconf.close.assert_called_once_with()


def test_local_hostname_uses_the_macos_bonjour_name() -> None:
    result = subprocess.CompletedProcess(
        args=["scutil", "--get", "LocalHostName"],
        returncode=0,
        stdout="development-mac\n",
        stderr="",
    )

    hostname = discover_local_hostname(command_runner=lambda *args, **kwargs: result)

    assert hostname == "development-mac"


def test_local_hostname_falls_back_to_the_short_socket_hostname() -> None:
    def missing_command(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    hostname = discover_local_hostname(
        command_runner=missing_command,
        socket_hostname=lambda: "development-mac.example.test",
    )

    assert hostname == "development-mac"
