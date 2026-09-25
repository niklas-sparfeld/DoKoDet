from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from table_evidence_analyzer import (
    AnalyzerEvidence,
    AnalyzerFrame,
    CardClassificationResult,
    IdentityCandidate,
    ProviderResult,
    normalize_prediction,
    parse_observation_bytes,
)
from test_round_analysis_api import (
    _analysis_payload,
    _upload_linked_package,
    _write_recording_bundle,
)

from dokodetector_backend import gemini_analyzer
from dokodetector_backend.app import create_app
from dokodetector_backend.config import ConfigurationError, Settings

BACKEND_ROOT = Path(__file__).parents[1]


def _settings(tmp_path: Path, **values: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "evidence_root": tmp_path / "runtime",
        "evidence_package_intake_root": tmp_path / "intake" / "evidence-packages",
        "repository_intake_root": tmp_path / "intake" / "recordings",
        "pending_video_root": tmp_path / "pending-videos",
        "gemini_api_key": "test-key",
        "visible_card_provider": "gemini",
        "visible_card_bundle_path": None,
        "visible_card_device": None,
        "visible_card_identity_classifier": "gemini",
        "visible_card_identity_bundle_path": None,
        "visible_card_identity_device": None,
    }
    defaults.update(values)
    return Settings(**defaults)


class FakeLocalVisibleCardProvider:
    name = "local"
    version = "local-visible-cards-test-v1"
    proposals = ()

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
            proposals=self.proposals,
            latency_ms=3.25,
        )


class FakeLocalSegmentationProvider(FakeLocalVisibleCardProvider):
    name = "local-rfdetr-segmentation"
    version = "local-visible-card-segmentation-test-v1"


class FakeLocalIdentityClassifier:
    name = "local-dinov3"
    version = "dinov3-local-identity-test-v1"
    calibration = "uncalibrated"

    def __init__(self, bundle: Path, *, device: str) -> None:
        self.bundle = bundle
        self.device = device
        self.load_latency_ms = 18.75

    @property
    def bundle_identity(self) -> dict[str, str]:
        return {
            "schema_version": "dinov3-identity-bundle/v1",
            "bundle_digest": "f" * 64,
            "head_sha256": "e" * 64,
            "model_id": "facebook/dinov3-vits16-pretrain-lvd1689m",
            "model_revision": "test-revision",
        }

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        assert crop_bytes.startswith(b"P6\n")
        return CardClassificationResult(
            status="ok",
            candidates=(IdentityCandidate(card="CLUBS_NINE", probability=1.0),),
            latency_ms=4.5,
            raw_response={
                "provider": self.name,
                "version": self.version,
                "device": self.device,
                "bundle_identity": self.bundle_identity,
            },
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


def test_local_identity_settings_require_bundle_and_explicit_device(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="VISIBLE_CARD_IDENTITY_BUNDLE_PATH"):
        create_app(
            _settings(
                tmp_path,
                visible_card_identity_classifier="local",
                visible_card_identity_device="cpu",
            )
        )

    with pytest.raises(ConfigurationError, match="VISIBLE_CARD_IDENTITY_DEVICE"):
        create_app(
            _settings(
                tmp_path,
                visible_card_identity_classifier="local",
                visible_card_identity_bundle_path=tmp_path / "identity-bundle",
            )
        )


def test_local_processors_are_deferred_until_analyzer_use(tmp_path: Path, monkeypatch) -> None:
    detector_bundle = tmp_path / "detector-bundle"
    detector_bundle.mkdir()
    identity_bundle = tmp_path / "identity-bundle"
    identity_bundle.mkdir()
    constructed: list[str] = []

    def create_detector(*args, **kwargs):
        constructed.append("detector")
        return FakeLocalVisibleCardProvider(*args, **kwargs)

    def create_classifier(*args, **kwargs):
        constructed.append("identity")
        return FakeLocalIdentityClassifier(*args, **kwargs)

    monkeypatch.setattr(gemini_analyzer, "LocalVisibleCardProvider", create_detector)
    monkeypatch.setattr(gemini_analyzer, "DinoV3IdentityClassifier", create_classifier)

    app = create_app(
        _settings(
            tmp_path,
            gemini_api_key=None,
            visible_card_provider="local",
            visible_card_bundle_path=detector_bundle,
            visible_card_device="cpu",
            visible_card_identity_classifier="local",
            visible_card_identity_bundle_path=identity_bundle,
            visible_card_identity_device="cpu",
        )
    )

    assert constructed == []
    assert app.state.analyzer.name == "visible-card-table-analyzer"
    assert constructed == []

    provider = app.state.analyzer.provider

    assert constructed == ["detector", "identity"]
    assert provider is app.state.visible_card_pipeline_service.detector_providers["local"]


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
            visible_card_identity_classifier="gemini",
        )
    )

    assert app.state.analyzer.provider.provider.name == "local"
    assert app.state.analyzer.provider.provider.device == "cpu"
    assert app.state.analyzer.classifier.classifier.name == "gemini"


@pytest.mark.parametrize("device", ["cpu", "mps"])
def test_reviewed_segmentation_backend_selection_is_explicit_and_non_default(
    tmp_path: Path, monkeypatch, device: str
) -> None:
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    monkeypatch.setattr(
        gemini_analyzer,
        "LocalVisibleCardSegmentationProvider",
        FakeLocalSegmentationProvider,
    )
    app = create_app(
        _settings(
            tmp_path,
            visible_card_provider="local-rfdetr-segmentation",
            visible_card_bundle_path=bundle_path,
            visible_card_device=device,
            visible_card_identity_classifier="gemini",
        )
    )

    selected = app.state.analyzer.provider.provider
    assert selected.name == "local-rfdetr-segmentation"
    assert selected.device == device
    monkeypatch.delenv("VISIBLE_CARD_PROVIDER", raising=False)
    assert Settings(_env_file=None, gemini_api_key="key").visible_card_provider == "gemini"


def test_local_pipeline_selection_detects_segmentation_bundle_with_cloud_default(
    tmp_path: Path, monkeypatch
) -> None:
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "manifest.json").write_text(
        '{"schema_version":"rfdetr-segmentation-bundle/v1"}', encoding="utf-8"
    )
    monkeypatch.setattr(
        gemini_analyzer,
        "LocalVisibleCardSegmentationProvider",
        FakeLocalSegmentationProvider,
    )
    monkeypatch.setattr(
        gemini_analyzer,
        "LocalVisibleCardProvider",
        lambda *args, **kwargs: pytest.fail("segmentation bundle selected the detector adapter"),
    )

    visible, _ = gemini_analyzer.create_configured_processor_registries(
        _settings(
            tmp_path,
            visible_card_bundle_path=bundle_path,
            visible_card_device="cpu",
        )
    )

    selected = visible["local"].provider
    assert selected.name == "local-rfdetr-segmentation"


def test_retired_cascade_provider_is_not_registered(tmp_path: Path) -> None:
    visible, _ = gemini_analyzer.create_configured_processor_registries(_settings(tmp_path))

    assert "local-rfdetr-cascade" not in visible
    assert "local-rfdetr-cascade-0068" not in visible
    assert "local-rfdetr-cascade-0070" not in visible


def test_local_identity_selection_does_not_require_gemini_or_construct_gemini(
    tmp_path: Path, monkeypatch
) -> None:
    detector_bundle = tmp_path / "detector-bundle"
    detector_bundle.mkdir()
    identity_bundle = tmp_path / "identity-bundle"
    identity_bundle.mkdir()
    monkeypatch.setattr(gemini_analyzer, "LocalVisibleCardProvider", FakeLocalVisibleCardProvider)
    monkeypatch.setattr(gemini_analyzer, "DinoV3IdentityClassifier", FakeLocalIdentityClassifier)
    monkeypatch.setattr(
        gemini_analyzer,
        "GeminiVisibleCardProvider",
        lambda *args, **kwargs: pytest.fail("local detector must not construct Gemini"),
    )
    monkeypatch.setattr(
        gemini_analyzer,
        "GeminiCardClassifier",
        lambda *args, **kwargs: pytest.fail("local identity must not construct Gemini"),
    )

    app = create_app(
        _settings(
            tmp_path,
            gemini_api_key=None,
            visible_card_provider="local",
            visible_card_bundle_path=detector_bundle,
            visible_card_device="cpu",
            visible_card_identity_classifier="local",
            visible_card_identity_bundle_path=identity_bundle,
            visible_card_identity_device="cpu",
        )
    )

    assert app.state.analyzer.provider.provider.name == "local"
    assert app.state.analyzer.classifier.name == "local-dinov3"
    assert app.state.analyzer.classifier.device == "cpu"


def test_local_identity_classifies_a_fixture_crop_through_the_backend_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    detector_bundle = tmp_path / "detector-bundle"
    detector_bundle.mkdir()
    identity_bundle = tmp_path / "identity-bundle"
    identity_bundle.mkdir()
    fixture_frame = (
        BACKEND_ROOT.parent
        / "fixtures"
        / "evidence"
        / "v2"
        / "example-complete"
        / "frames"
        / "frame_00.jpg"
    )
    fixture_bytes = fixture_frame.read_bytes()
    monkeypatch.setattr(
        FakeLocalVisibleCardProvider,
        "proposals",
        normalize_prediction(
            {
                "cards": [
                    {
                        "box_2d": {"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
                        "polygon": [
                            {"x": 0, "y": 0},
                            {"x": 1000, "y": 0},
                            {"x": 1000, "y": 1000},
                            {"x": 0, "y": 1000},
                        ],
                        "side": "face_up",
                        "label": "fixture card",
                    }
                ]
            }
        ).cards,
    )
    monkeypatch.setattr(gemini_analyzer, "LocalVisibleCardProvider", FakeLocalVisibleCardProvider)
    monkeypatch.setattr(gemini_analyzer, "DinoV3IdentityClassifier", FakeLocalIdentityClassifier)
    settings = _settings(
        tmp_path,
        gemini_api_key=None,
        visible_card_provider="local",
        visible_card_bundle_path=detector_bundle,
        visible_card_device="cpu",
        visible_card_identity_classifier="local",
        visible_card_identity_bundle_path=identity_bundle,
        visible_card_identity_device="cpu",
    )
    app = create_app(settings)

    from PIL import Image

    with Image.open(fixture_frame) as image:
        width, height = image.size
    observation = app.state.analyzer.analyze(
        AnalyzerEvidence(
            package_id="550e8400-e29b-41d4-a716-446655440041",
            event_time_ms=0,
            frames=[
                AnalyzerFrame(
                    part_name="frame_00",
                    actual_offset_ms=0,
                    width=width,
                    height=height,
                    jpeg_bytes=fixture_bytes,
                )
            ],
        )
    )

    assert observation.status == "observed"
    assert observation.cards[0].identity_candidates[0].card == "CLUBS_NINE"
    assert observation.diagnostics["identity_run_record"]["one_frame_inference_latency_ms"] == 4.5


def test_local_identity_reaches_worker_persistence_with_a_schema_valid_observation(
    tmp_path: Path, monkeypatch
) -> None:
    detector_bundle = tmp_path / "detector-bundle"
    detector_bundle.mkdir()
    identity_bundle = tmp_path / "identity-bundle"
    identity_bundle.mkdir()
    monkeypatch.setattr(gemini_analyzer, "LocalVisibleCardProvider", FakeLocalVisibleCardProvider)
    monkeypatch.setattr(
        gemini_analyzer,
        "GeminiVisibleCardProvider",
        lambda *args, **kwargs: pytest.fail("local mode called Gemini visible-card detection"),
    )
    monkeypatch.setattr(gemini_analyzer, "DinoV3IdentityClassifier", FakeLocalIdentityClassifier)
    settings = _settings(
        tmp_path,
        gemini_api_key=None,
        visible_card_provider="local",
        visible_card_bundle_path=detector_bundle,
        visible_card_device="cpu",
        visible_card_identity_classifier="local",
        visible_card_identity_bundle_path=identity_bundle,
        visible_card_identity_device="cpu",
    )
    app = create_app(settings, run_round_analysis_synchronously=True)
    _write_recording_bundle(app)

    with TestClient(app) as client:
        package_id = _upload_linked_package(client)
        response = client.post(
            "/v1/round-analyses",
            json=_analysis_payload(package_ids=[package_id]),
        )

    assert response.status_code == 202
    assert response.json()["state"] == "complete"
    stored = app.state.table_observation_store.list_for_package(package_id)[0]
    observation = parse_observation_bytes(stored.observation_json.encode())
    assert observation.schema_version == "table-observation/v1"
    assert observation.status == "observed"
    assert observation.cards == []
    assert observation.diagnostics["provider"]["name"] == "local"
    assert observation.diagnostics["identity_classifier"]["name"] == "local-dinov3"
    assert observation.diagnostics["identity_classifier"]["bundle_identity"] == {
        "schema_version": "dinov3-identity-bundle/v1",
        "bundle_digest": "f" * 64,
        "head_sha256": "e" * 64,
        "model_id": "facebook/dinov3-vits16-pretrain-lvd1689m",
        "model_revision": "test-revision",
    }
    assert observation.diagnostics["identity_run_record"] == {
        "classifier": "local-dinov3",
        "load_latency_ms": 18.75,
        "one_frame_inference_latency_ms": 0.0,
        "interpretation": "one-frame measurement; not a latency or quality evaluation",
    }
    assert observation.diagnostics["run_record"] == {
        "provider": "local",
        "load_latency_ms": 12.5,
        "one_frame_inference_latency_ms": 3.25,
        "interpretation": "one-frame measurement; not a latency or quality evaluation",
    }
