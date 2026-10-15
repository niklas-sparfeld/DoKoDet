from types import SimpleNamespace

from dokodetector_backend import server


def test_run_limits_http_concurrency_and_bounds_graceful_shutdown(monkeypatch) -> None:
    settings = SimpleNamespace(
        bonjour_address=None,
        bonjour_enabled=False,
        bonjour_hostname=None,
        bonjour_name="DokoDetector",
        server_host="127.0.0.1",
        server_port=8000,
    )
    call: dict[str, object] = {}

    monkeypatch.setattr(server, "_configure_logging", lambda: None)
    monkeypatch.setattr(server, "Settings", lambda: settings)
    monkeypatch.setattr(server, "discover_local_hostname", lambda: "localhost")
    monkeypatch.setattr(server, "discover_local_ipv4_address", lambda: "127.0.0.1")
    monkeypatch.setattr(server, "build_service_info", lambda **_: object())
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: call.update(kwargs))

    server.run()

    assert call["limit_concurrency"] == server.MAX_CONCURRENT_HTTP_REQUESTS
    assert call["timeout_graceful_shutdown"] == server.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
