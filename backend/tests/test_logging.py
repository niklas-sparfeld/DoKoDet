import io
import logging
import sys
from types import SimpleNamespace

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.logging_config import (
    LoggingConfigurationError,
    configure_logging,
    get_or_create_request_id,
    log_event,
    parse_log_level,
)


@pytest.fixture()
def clean_root_logging():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    original_backend_level = logging.getLogger("dokodetector_backend").level
    root.handlers.clear()
    try:
        yield
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
        logging.getLogger("dokodetector_backend").setLevel(original_backend_level)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("debug", logging.DEBUG),
        ("INFO", logging.INFO),
        ("Warning", logging.WARNING),
        ("error", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ],
)
def test_parse_log_level_accepts_case_insensitive_standard_levels(value, expected) -> None:
    assert parse_log_level(value) == expected


def test_parse_log_level_reads_info_default_and_environment(monkeypatch) -> None:
    monkeypatch.delenv("DOKO_LOG_LEVEL", raising=False)
    assert parse_log_level() == logging.INFO

    monkeypatch.setenv("DOKO_LOG_LEVEL", "dEbUg")
    assert parse_log_level() == logging.DEBUG


def test_invalid_log_level_has_a_clear_configuration_error() -> None:
    with pytest.raises(
        LoggingConfigurationError,
        match="DOKO_LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, or CRITICAL",
    ):
        parse_log_level("verbose")


def test_default_configuration_emits_info_and_filters_debug(
    clean_root_logging, monkeypatch
) -> None:
    logging.getLogger().handlers.clear()
    output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", output)
    configure_logging()

    logger = logging.getLogger("dokodetector_backend.test")
    log_event(logger, logging.INFO, "info_event", request_id="request-001")
    log_event(logger, logging.DEBUG, "debug_event", request_id="request-001")

    text = output.getvalue()
    assert " INFO dokodetector_backend.test info_event request_id=request-001" in text
    assert "debug_event" not in text
    assert text.count("\n") == 1


def test_debug_configuration_emits_debug_records(clean_root_logging, monkeypatch) -> None:
    logging.getLogger().handlers.clear()
    output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", output)
    configure_logging("DEBUG")

    log_event(logging.getLogger("dokodetector_backend.test"), logging.DEBUG, "debug_event")

    assert " DEBUG dokodetector_backend.test debug_event\n" in output.getvalue()


def test_formatter_uses_utc_iso_timestamp_and_single_line_fields(
    clean_root_logging, monkeypatch
) -> None:
    logging.getLogger().handlers.clear()
    output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", output)
    configure_logging()

    log_event(
        logging.getLogger("dokodetector_backend.test"),
        logging.INFO,
        "request_rejected",
        request_id="request 001",
        status_code=422,
        reason="line one\nline two",
    )

    line = output.getvalue()
    assert line.startswith("20")
    assert "Z INFO dokodetector_backend.test request_rejected" in line
    assert "request_id='request 001'" in line
    assert "status_code=422" in line
    assert "reason='line one line two'" in line
    assert line.endswith("\n")
    assert line.count("\n") == 1


def test_configuration_preserves_existing_handlers(clean_root_logging) -> None:
    logging.getLogger().handlers.clear()
    existing = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    root.addHandler(existing)

    configure_logging()

    assert root.handlers == [existing]


def test_request_id_helper_reuses_supplied_and_generated_ids() -> None:
    supplied_request = SimpleNamespace(
        headers={"x-dokodetector-request-id": "request-001"},
        state=SimpleNamespace(),
    )
    assert get_or_create_request_id(supplied_request) == "request-001"
    assert get_or_create_request_id(supplied_request) == "request-001"

    generated_request = SimpleNamespace(headers={}, state=SimpleNamespace())
    generated = get_or_create_request_id(generated_request)
    assert generated
    assert get_or_create_request_id(generated_request) == generated


def test_backend_startup_emits_backend_started(caplog, tmp_path) -> None:
    caplog.set_level(logging.INFO, logger="dokodetector_backend")
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'backend.sqlite'}",
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )

    with TestClient(create_test_app(settings)):
        pass

    started = [record for record in caplog.records if record.msg == "backend_started"]
    assert len(started) == 1
    assert started[0].levelno == logging.INFO
    assert started[0].event_name == "backend_started"
