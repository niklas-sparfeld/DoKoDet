from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from table_evidence_analyzer import ProviderResult, parse_observation_bytes
from test_round_analysis_api import (
    RECORDING_ID,
    SESSION_ID,
    _analysis_payload,
    _upload_linked_package,
)

from dokodetector_backend import gemini_analyzer
from dokodetector_backend.app import create_app
from dokodetector_backend.config import ConfigurationError, Settings
from dokodetector_backend.repository import upgrade_database
from dokodetector_backend.repository_bundle_repository import StoredRepositoryBundle

BACKEND_ROOT = Path(__file__).parents[1]


def _settings(tmp_path: Path, **values: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "database_url": f"sqlite:///{tmp_path / 'backend.sqlite'}",
        "evidence_root": tmp_path / "runtime",
        "evidence_package_intake_root": tmp_path / "intake" / "evidence-packages",
        "repository_intake_root": tmp_path / "intake" / "recordings",
        "pending_video_root": tmp_path / "pending-videos",
        "gemini_api_key": "test-key",
    }
    defaults.update(values)
    return Settings(**defaults)


class FakeLocalVisibleCardProvider:
    name = "local"
    version = "local-visible-cards-test-v1"

    def __init__(self, bundle: Path, *, device: str) -> None:
        self.bundle = bundle
        self.device = device

    def propose(self, request) -> ProviderResult:
        assert request.provider == self.name
        return ProviderResult(
            status="ok",
            raw_response={
                "provider": self.name,
                "version": self.version,
                "device": self.device,
                "load_latency_ms": 12.5,
            },
            latency_ms=3.25,
        )


def test_local_settings_require_bundle_and_explicit_device(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="VISIBLE_CARD_BUNDLE_PATH"):
        create_app(
            _settings(
                tmp_path,
                visible_card_provider="local",
                visible_card_device="cpu",
            )
        )

    with pytest.raises(ConfigurationError, match="VISIBLE_CARD_DEVICE"):
        create_app(
            _settings(
                tmp_path,
                visible_card_provider="local",
                visible_card_bundle_path=tmp_path / "bundle",
            )
        )


def test_local_backend_selection_keeps_gemini_identity_and_does_not_construct_gemini_provider(
    tmp_path: Path, monkeypatch
) -> None:
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    monkeypatch.setattr(gemini_analyzer, "LocalVisibleCardProvider", FakeLocalVisibleCardProvider)

    def fail_gemini_provider(*args, **kwargs):
        raise AssertionError("local mode constructed the Gemini visible-card provider")

    monkeypatch.setattr(gemini_analyzer, "GeminiVisibleCardProvider", fail_gemini_provider)
    app = create_app(
        _settings(
            tmp_path,
            visible_card_provider="local",
            visible_card_bundle_path=bundle_path,
            visible_card_device="cpu",
        )
    )

    assert app.state.analyzer.provider.provider.name == "local"
    assert app.state.analyzer.provider.provider.device == "cpu"
    assert app.state.analyzer.classifier.classifier.name == "gemini"


def test_local_provider_reaches_worker_persistence_with_a_schema_valid_observation(
    tmp_path: Path, monkeypatch
) -> None:
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    monkeypatch.setattr(gemini_analyzer, "LocalVisibleCardProvider", FakeLocalVisibleCardProvider)
    monkeypatch.setattr(
        gemini_analyzer,
        "GeminiVisibleCardProvider",
        lambda *args, **kwargs: pytest.fail("local mode called Gemini visible-card detection"),
    )
    settings = _settings(
        tmp_path,
        visible_card_provider="local",
        visible_card_bundle_path=bundle_path,
        visible_card_device="cpu",
    )
    upgrade_database(BACKEND_ROOT, settings.database_url)
    app = create_app(settings, run_round_analysis_synchronously=True)
    app.state.repository_bundle_repository.insert(
        StoredRepositoryBundle(
            recording_id=RECORDING_ID,
            source_asset_id="source-local-provider",
            video_id="video-local-provider",
            session_id=SESSION_ID,
            source_sha256="a" * 64,
            manifest_sha256="b" * 64,
            source_record_sha256="c" * 64,
            task_enrollment_sha256="d" * 64,
            proposal_run_ids=(),
            bundle_fingerprint="e" * 64,
            state="complete",
            received_at=datetime.now(timezone.utc),
        )
    )

    with TestClient(app) as client:
        package_id = _upload_linked_package(client)
        response = client.post(
            "/v1/round-analyses",
            json=_analysis_payload(package_ids=[package_id]),
        )

    assert response.status_code == 202
    assert response.json()["state"] == "complete"
    stored = app.state.repository.list_table_observations(package_id)[0]
    observation = parse_observation_bytes(stored.observation_json.encode())
    assert observation.schema_version == "table-observation/v1"
    assert observation.status == "observed"
    assert observation.cards == []
    assert observation.diagnostics["provider"]["name"] == "local"
    assert observation.diagnostics["identity_classifier"]["name"] == "gemini"
    assert observation.diagnostics["run_record"] == {
        "provider": "local",
        "load_latency_ms": 12.5,
        "one_frame_inference_latency_ms": 3.25,
        "interpretation": "one-frame measurement; not a latency or quality evaluation",
    }
