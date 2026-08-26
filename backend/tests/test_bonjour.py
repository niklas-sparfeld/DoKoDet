import subprocess
from unittest.mock import Mock

from dokodetector_backend.bonjour import (
    BonjourAdvertiser,
    build_service_info,
    discover_local_hostname,
    discover_local_ipv4_address,
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


def test_service_info_can_advertise_a_private_ip_endpoint() -> None:
    info = build_service_info(
        service_name="DokoDetector Test",
        hostname="test-mac",
        port=8123,
        endpoint_host="192.168.1.42",
    )

    assert info.server == "test-mac.local."
    assert info.properties[b"url"] == b"http://192.168.1.42:8123"


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


def test_local_ipv4_address_uses_the_default_route() -> None:
    socket = Mock()
    socket.getsockname.return_value = ("192.168.1.42", 54321)

    address = discover_local_ipv4_address(socket_factory=lambda *args: socket)

    assert address == "192.168.1.42"
    socket.connect.assert_called_once_with(("192.0.2.1", 9))
    socket.close.assert_called_once_with()


def test_local_ipv4_address_returns_none_without_a_route() -> None:
    socket = Mock()
    socket.connect.side_effect = OSError("Network is unreachable")

    address = discover_local_ipv4_address(socket_factory=lambda *args: socket)

    assert address is None
    socket.close.assert_called_once_with()
