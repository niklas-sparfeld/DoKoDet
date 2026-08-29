import json
from pathlib import Path

import pytest

from table_evidence_analyzer.visible_cards import (
    CACHE_SCHEMA_VERSION,
    DEFAULT_MODEL,
    FakeVisibleCardProvider,
    GeminiVisibleCardProvider,
    VisibleCardRequest,
    VisibleCardValidationError,
    build_request_from_image,
    build_review_queue,
    load_review_queue,
    normalize_prediction,
    record_review,
    render_overlay_svg,
)


def _prediction() -> dict:
    return {
        "cards": [
            {
                "box_2d": {"y_min": 100, "x_min": 200, "y_max": 400, "x_max": 500},
                "polygon": [
                    {"x": 200, "y": 100},
                    {"x": 500, "y": 100},
                    {"x": 500, "y": 400},
                    {"x": 200, "y": 400},
                ],
                "side": "face_down",
                "label": "patterned card back",
            }
        ]
    }


def _request(*, image: bytes = b"frame", target_offset_ms: int = 0) -> VisibleCardRequest:
    return VisibleCardRequest(
        package_id="package-001",
        frame_part_name="frame_00",
        target_offset_ms=target_offset_ms,
        image_bytes=image,
        width=1920,
        height=1080,
    )


def test_request_key_covers_image_and_provider_inputs() -> None:
    first = _request()

    assert first.model == DEFAULT_MODEL
    assert first.request_key != _request(image=b"other").request_key
    assert first.request_key != _request(target_offset_ms=150).request_key
    assert (
        first.request_key
        != VisibleCardRequest(
            package_id=first.package_id,
            frame_part_name=first.frame_part_name,
            target_offset_ms=first.target_offset_ms,
            image_bytes=first.image_bytes,
            width=first.width,
            height=first.height,
            provider="fake",
        ).request_key
    )
    assert (
        first.request_key
        != VisibleCardRequest(
            package_id=first.package_id,
            frame_part_name=first.frame_part_name,
            target_offset_ms=first.target_offset_ms,
            image_bytes=first.image_bytes,
            width=first.width,
            height=first.height,
            prompt="different prompt",
        ).request_key
    )
    assert first.to_mapping()["image_sha256"]
    assert "image_bytes" not in first.to_mapping()


def test_normalize_prediction_returns_strict_proposals() -> None:
    prediction = normalize_prediction(_prediction())

    assert len(prediction.cards) == 1
    assert prediction.cards[0].box_2d.x_min == 200
    assert prediction.cards[0].polygon[2].y == 400

    invalid = _prediction()
    invalid["cards"][0]["polygon"][0]["x"] = True
    with pytest.raises(VisibleCardValidationError, match="normalized integer"):
        normalize_prediction(invalid)


def test_fake_provider_is_deterministic_and_cache_stores_raw_and_normalized_outputs(
    tmp_path: Path,
) -> None:
    request = _request()
    fake = FakeVisibleCardProvider({request.image_sha256: _prediction()})
    first = fake.propose(request)
    assert first.status == "ok"
    assert first.proposals[0].label == "patterned card back"
    assert first.estimated_cost_usd == 0.0

    from table_evidence_analyzer.visible_cards import CachedVisibleCardProvider

    cached = CachedVisibleCardProvider(fake, tmp_path / "cache")
    cached_first = cached.propose(request)
    cached_second = cached.propose(request)
    assert cached_first.cache_hit is False
    assert cached_second.cache_hit is True
    assert cached_second.proposals == cached_first.proposals
    cache_files = list((tmp_path / "cache").rglob("*.json"))
    assert len(cache_files) == 1
    cache = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert cache["schema_version"] == CACHE_SCHEMA_VERSION
    assert cache["raw_response"]["prediction"] == _prediction()
    assert cache["prediction"] == _prediction()


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_gemini_provider_builds_structured_request_and_records_usage() -> None:
    calls: list[tuple[object, float]] = []

    def urlopen(request: object, timeout: float) -> _FakeHTTPResponse:
        calls.append((request, timeout))
        return _FakeHTTPResponse(
            {
                "candidates": [{"content": {"parts": [{"text": json.dumps(_prediction())}]}}],
                "usageMetadata": {
                    "promptTokenCount": 1295,
                    "candidatesTokenCount": 178,
                    "totalTokenCount": 1473,
                },
            }
        )

    result = GeminiVisibleCardProvider(
        api_key="runtime-secret",
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).propose(_request())

    assert result.status == "ok"
    assert result.retry_count == 0
    assert result.usage.input_tokens == 1295
    assert result.usage.output_tokens == 178
    assert result.estimated_cost_usd == pytest.approx(0.00163875)
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 120.0
    assert request.headers["X-goog-api-key"] == "runtime-secret"
    payload = json.loads(request.data)
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_provider_returns_bounded_unavailable_result_for_malformed_response() -> None:
    attempts: list[int] = []

    def urlopen(_request: object, timeout: float) -> _FakeHTTPResponse:
        del timeout
        attempts.append(1)
        return _FakeHTTPResponse({"candidates": []})

    result = GeminiVisibleCardProvider(
        api_key="runtime-secret",
        max_retries=2,
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).propose(_request())

    assert result.status == "unavailable"
    assert result.retry_count == 2
    assert len(attempts) == 3
    assert "malformed" in result.error


def test_overlay_is_a_self_contained_svg() -> None:
    svg = render_overlay_svg(_request(), normalize_prediction(_prediction()))

    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "data:image/jpeg;base64," in svg
    assert "patterned card back" in svg
    assert 'points="384,108 960,108 960,432 384,432"' in svg


def test_build_request_from_image_infers_jpeg_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    # Minimal JPEG containing a baseline SOF0 segment. The image need not decode for the request.
    image.write_bytes(
        b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x30\x00\x40\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    )

    request = build_request_from_image(
        image,
        package_id="package-001",
        frame_part_name="frame_00",
        target_offset_ms=0,
    )

    assert (request.width, request.height) == (64, 48)


def test_review_queue_is_resumable_and_atomic(tmp_path: Path) -> None:
    result = FakeVisibleCardProvider().propose(_request())
    queue_path = tmp_path / "queue.json"
    build_review_queue(
        [
            {
                "package_id": "package-001",
                "frame_part_name": "frame_00",
                "target_offset_ms": 0,
                "image": "frames/frame_00.jpg",
                "overlay": "overlays/frame_00.svg",
                "prediction": result,
            }
        ],
        queue_path,
        run_id="run-001",
    )
    queue = load_review_queue(queue_path)
    assert queue.schema_version == "visible-card-review-queue/v1"
    assert queue.items[0].decision is None

    record_review(queue_path, "package-001:frame_00", "GOOD", reviewer="operator")
    updated = load_review_queue(queue_path)
    assert updated.items[0].decision == "GOOD"
    assert updated.items[0].reviewer == "operator"
    assert load_review_queue(queue_path).items[0].decision == "GOOD"
