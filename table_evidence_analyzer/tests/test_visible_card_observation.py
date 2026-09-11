from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image

from table_evidence_analyzer.analyzer import AnalyzerEvidence, AnalyzerFrame
from table_evidence_analyzer.card_classification import CardClassificationResult
from table_evidence_analyzer.cli import main
from table_evidence_analyzer.export import BUNDLE_SCHEMA, CapabilityBundle
from table_evidence_analyzer.table_observation import IdentityCandidate, parse_observation_bytes
from table_evidence_analyzer.visible_card_observation import (
    ObservationAdapterError,
    VisibleCardTableAnalyzer,
    adapt_visible_card_result,
    polygon_to_ppm,
    write_observation,
)
from table_evidence_analyzer.visible_cards import (
    FakeVisibleCardProvider,
    ProviderResult,
    VisibleCardRequest,
    normalize_prediction,
)

PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


def _jpeg(size: tuple[int, int] = (20, 20), color: tuple[int, int, int] = (240, 20, 20)) -> bytes:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format="JPEG", quality=100)
    return output.getvalue()


def _proposal(x_min: int = 0, y_min: int = 0, x_max: int = 1000, y_max: int = 1000) -> dict:
    return {
        "box_2d": {
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max,
        },
        "polygon": [
            {"x": x_min, "y": y_min},
            {"x": x_max, "y": y_min},
            {"x": x_max, "y": y_max},
            {"x": x_min, "y": y_max},
        ],
        "side": "face_up",
        "label": "provider label is not used as identity",
    }


def _bundle() -> CapabilityBundle:
    return CapabilityBundle(
        root=Path("."),
        manifest={
            "schema_version": "table-analyzer-bundle/v1",
            "calibration": "uncalibrated",
            "run_id": "run-fixture",
        },
        centroids={
            "CLUBS_NINE": [240.0, 20.0, 20.0],
            "HEARTS_TEN": [20.0, 240.0, 20.0],
        },
    )


def _evidence(image: bytes, *, actual_offset_ms: int = 0) -> AnalyzerEvidence:
    return AnalyzerEvidence(
        package_id=PACKAGE_ID,
        event_time_ms=42125,
        frames=[
            AnalyzerFrame(
                part_name="frame_00",
                actual_offset_ms=actual_offset_ms,
                width=20,
                height=20,
                jpeg_bytes=image,
            )
        ],
    )


def test_polygon_to_ppm_uses_polygon_extent_and_decodes_jpeg() -> None:
    crop, bounds = polygon_to_ppm(
        _jpeg(),
        normalize_prediction({"cards": [_proposal(100, 200, 600, 800)]}).cards[0],
        width=20,
        height=20,
    )

    assert bounds.to_mapping() == {"x_min": 2, "y_min": 4, "x_max": 12, "y_max": 16}
    assert crop.startswith(b"P6\n10 12\n255\n")
    with Image.open(BytesIO(crop)) as image:
        assert image.size == (10, 12)
        assert image.getpixel((5, 5))[0] > 200


def test_polygon_to_ppm_rejects_unusable_crop() -> None:
    proposal = normalize_prediction({"cards": [_proposal(0, 0, 100, 100)]}).cards[0]

    with pytest.raises(ObservationAdapterError, match="at least 4x4"):
        polygon_to_ppm(_jpeg(), proposal, width=20, height=20)


def test_visible_card_analyzer_emits_schema_valid_identity_observation() -> None:
    image = _jpeg()
    request = VisibleCardRequest(
        package_id=str(PACKAGE_ID),
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=image,
        width=20,
        height=20,
        provider="fake",
    )
    provider = FakeVisibleCardProvider({request.image_sha256: {"cards": [_proposal()]}})
    observation = VisibleCardTableAnalyzer(
        provider,
        _bundle(),
        session_id="session-fixture",
        event_sequence=7,
    ).analyze(_evidence(image))

    assert observation.status == "observed"
    assert observation.session.session_id == "session-fixture"
    assert observation.session.event_sequence == 7
    assert len(observation.cards) == 1
    assert observation.cards[0].side == "face_up"
    assert observation.cards[0].identity_candidates[0].card == "CLUBS_NINE"
    probabilities = [
        candidate.probability for candidate in observation.cards[0].identity_candidates
    ]
    assert sum(probabilities) == pytest.approx(1.0)
    assert observation.diagnostics["classified_proposal_count"] == 1
    assert observation.diagnostics["classified_proposals"][0]["crop_bounds"] == {
        "x_min": 0,
        "y_min": 0,
        "x_max": 20,
        "y_max": 20,
    }


def test_unavailable_provider_becomes_insufficient_evidence() -> None:
    image = _jpeg()

    class UnavailableProvider:
        name = "fake"
        version = "fake-v1"

        def propose(self, request: VisibleCardRequest) -> ProviderResult:
            del request
            return ProviderResult(status="unavailable", error="test unavailable")

    provider = UnavailableProvider()
    observation = VisibleCardTableAnalyzer(provider, _bundle()).analyze(_evidence(image))

    assert observation.status == "insufficient_evidence"
    assert observation.cards == []


def test_provider_proposal_without_usable_crop_is_retained_as_failed_identity() -> None:
    image = _jpeg()
    request = VisibleCardRequest(
        package_id=str(PACKAGE_ID),
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=image,
        width=20,
        height=20,
        provider="fake",
    )
    provider = FakeVisibleCardProvider(
        {request.image_sha256: {"cards": [_proposal(0, 0, 100, 100)]}}
    )
    observation = VisibleCardTableAnalyzer(provider, _bundle()).analyze(_evidence(image))

    assert observation.status == "observed"
    assert len(observation.cards) == 1
    assert observation.cards[0].identity_status == "failed"
    assert observation.cards[0].identity_candidates == []
    assert observation.diagnostics["dropped_proposal_count"] == 1


def test_mixed_identity_outcomes_keep_every_visible_card_proposal() -> None:
    image = _jpeg()
    request = VisibleCardRequest(
        package_id=str(PACKAGE_ID),
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=image,
        width=20,
        height=20,
        provider="fake",
    )

    class MixedClassifier:
        name = "mixed"
        version = "mixed-v1"
        calibration = "uncalibrated"

        def __init__(self) -> None:
            self.calls = 0

        def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
            del crop_bytes
            self.calls += 1
            if self.calls == 1:
                return CardClassificationResult(
                    status="ok",
                    candidates=(IdentityCandidate(card="CLUBS_NINE", probability=1.0),),
                )
            if self.calls == 2:
                return CardClassificationResult(status="ok", classification="face_down")
            return CardClassificationResult(status="unavailable", error="fixture timeout")

    proposals = [_proposal(), _proposal(100, 100, 900, 900), _proposal(200, 200, 800, 800)]
    observation = adapt_visible_card_result(
        request,
        ProviderResult(
            status="ok",
            proposals=tuple(normalize_prediction({"cards": proposals}).cards),
        ),
        MixedClassifier(),
        observed_at_ms=1,
        session_id="session-mixed",
        event_sequence=1,
    )

    assert [card.identity_status for card in observation.cards] == [
        "classified",
        "face_down",
        "failed",
    ]
    assert [card.side for card in observation.cards] == ["face_up", "face_down", "face_up"]
    assert observation.diagnostics["dropped_proposals"][0]["source_side"] == "face_up"
    assert observation.diagnostics["dropped_proposals"][0]["side"] == "face_down"
    assert len(observation.cards) == 3


def test_identity_crops_from_one_detection_run_in_parallel_and_keep_order() -> None:
    image = _jpeg()
    request = VisibleCardRequest(
        package_id=str(PACKAGE_ID),
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=image,
        width=20,
        height=20,
        provider="fake",
    )
    proposals = tuple(
        normalize_prediction({"cards": [_proposal(0, 0, 1000 - index * 100, 1000)]}).cards[0]
        for index in range(3)
    )
    active = 0
    maximum = 0
    lock = threading.Lock()
    started_three = threading.Event()
    release = threading.Event()

    class BlockingClassifier:
        name = "blocking"
        version = "blocking-v1"
        calibration = "uncalibrated"

        def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
            nonlocal active, maximum
            del crop_bytes
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 3:
                    started_three.set()
            try:
                assert release.wait(2)
                return CardClassificationResult(
                    status="ok",
                    candidates=(IdentityCandidate(card="CLUBS_NINE", probability=1.0),),
                )
            finally:
                with lock:
                    active -= 1

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            adapt_visible_card_result,
            request,
            ProviderResult(status="ok", proposals=proposals),
            BlockingClassifier(),
            observed_at_ms=1,
            session_id="session-blocking",
            event_sequence=1,
            max_concurrent_requests=3,
        )
        assert started_three.wait(2)
        assert maximum == 3
        release.set()
        observation = future.result()

    assert [card.observed_card_id for card in observation.cards] == [
        f"observation-{PACKAGE_ID}-frame_00-card-01",
        f"observation-{PACKAGE_ID}-frame_00-card-02",
        f"observation-{PACKAGE_ID}-frame_00-card-03",
    ]
    assert [card.identity_status for card in observation.cards] == [
        "classified",
        "classified",
        "classified",
    ]


def test_observation_write_is_canonical_and_parseable(tmp_path: Path) -> None:
    image = _jpeg()
    request = VisibleCardRequest(
        package_id=str(PACKAGE_ID),
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=image,
        width=20,
        height=20,
        provider="fake",
    )
    observation = VisibleCardTableAnalyzer(
        FakeVisibleCardProvider({request.image_sha256: {"cards": [_proposal()]}}),
        _bundle(),
    ).analyze(_evidence(image))
    output = write_observation(observation, tmp_path / "observation.json")

    parsed = parse_observation_bytes(output.read_bytes())
    assert parsed == observation
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == (
        "table-observation/v1"
    )


def test_visible_card_observe_cli_runs_detection_and_identity(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(_jpeg())
    model_path = tmp_path / "model.json"
    model_path.write_text(
        json.dumps(
            {
                "schema_version": "rgb-nearest-centroid-v1",
                "centroids": _bundle().centroids,
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    model_path.rename(bundle_path / "model.json")
    model_digest = hashlib.sha256((bundle_path / "model.json").read_bytes()).hexdigest()
    (bundle_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": BUNDLE_SCHEMA,
                "capabilities": ["identity_candidates"],
                "calibration": "uncalibrated",
                "card_set_version": "doko-german-suited-v1",
                "run_id": "run-cli",
                "dataset_version_digest": "dataset-digest",
                "split_version_digest": "split-digest",
                "model_file": "model.json",
                "model_sha256": model_digest,
            }
        ),
        encoding="utf-8",
    )
    prediction_path = tmp_path / "prediction.json"
    prediction_path.write_text(json.dumps({"cards": [_proposal()]}), encoding="utf-8")
    output = tmp_path / "observation.json"

    assert (
        main(
            [
                "visible-card-observe",
                "--image",
                str(image_path),
                "--package-id",
                str(PACKAGE_ID),
                "--bundle",
                str(bundle_path),
                "--output",
                str(output),
                "--fake-prediction",
                str(prediction_path),
                "--session-id",
                "session-cli",
                "--event-sequence",
                "3",
            ]
        )
        == 0
    )
    observation = parse_observation_bytes(output.read_bytes())
    assert observation.status == "observed"
    assert observation.session.event_sequence == 3
    assert observation.cards[0].identity_candidates[0].card == "CLUBS_NINE"
