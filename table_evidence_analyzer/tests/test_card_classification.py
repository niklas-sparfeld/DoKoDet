import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from table_evidence_analyzer.card_classification import CachedCardClassifier, GeminiCardClassifier
from table_evidence_analyzer.gemini_concurrency import GeminiRequestLimiter
from table_evidence_analyzer.visible_cards import GeminiVisibleCardProvider, VisibleCardRequest


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _blocking_response(request: object) -> _Response:
    payload = json.loads(request.data)  # type: ignore[attr-defined]
    schema = payload["generationConfig"]["responseJsonSchema"]
    body = {"card": "HEARTS_TEN"} if "card" in schema.get("properties", {}) else {"cards": []}
    return _Response({"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]})


def test_gemini_classifier_sends_transformed_ppm_as_png_and_returns_identity() -> None:
    calls: list[tuple[object, float]] = []

    def urlopen(request: object, timeout: float) -> _Response:
        calls.append((request, timeout))
        return _Response(
            {
                "candidates": [{"content": {"parts": [{"text": '{"card":"HEARTS_TEN"}'}]}}],
                "usageMetadata": {
                    "promptTokenCount": 101,
                    "candidatesTokenCount": 7,
                    "totalTokenCount": 108,
                },
            }
        )

    result = GeminiCardClassifier(
        api_key="runtime-secret", urlopen=urlopen, sleep=lambda _seconds: None
    ).classify_ppm(b"P6\n4 4\n255\n" + bytes([255, 0, 0] * 16))

    assert result.status == "ok"
    assert result.candidates[0].card == "HEARTS_TEN"
    assert result.candidates[0].probability == 1.0
    assert result.usage.total_tokens == 108
    request, timeout = calls[0]
    assert timeout == 120.0
    assert request.headers["X-goog-api-key"] == "runtime-secret"
    payload = json.loads(request.data)
    assert payload["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_classifier_turns_unknown_response_into_no_identity() -> None:
    def urlopen(_request: object, timeout: float) -> _Response:
        del timeout
        return _Response({"candidates": [{"content": {"parts": [{"text": '{"card":"UNKNOWN"}'}]}}]})

    result = GeminiCardClassifier(
        api_key="runtime-secret", urlopen=urlopen, sleep=lambda _seconds: None
    ).classify_ppm(b"P6\n4 4\n255\n" + bytes([255, 0, 0] * 16))

    assert result.status == "ok"
    assert result.candidates == ()


def test_cached_classifier_does_not_repeat_a_transformed_crop_request(tmp_path) -> None:
    calls: list[int] = []

    def urlopen(_request: object, timeout: float) -> _Response:
        del timeout
        calls.append(1)
        return _Response(
            {"candidates": [{"content": {"parts": [{"text": '{"card":"CLUBS_NINE"}'}]}}]}
        )

    classifier = CachedCardClassifier(
        GeminiCardClassifier(api_key="runtime-secret", urlopen=urlopen), tmp_path / "cache"
    )
    crop = b"P6\n4 4\n255\n" + bytes([255, 0, 0] * 16)

    assert classifier.classify_ppm(crop).cache_hit is False
    assert classifier.classify_ppm(crop).cache_hit is True
    assert len(calls) == 1


def test_shared_gemini_limiter_bounds_detector_and_identity_http_calls() -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()
    started_two = threading.Event()
    release = threading.Event()

    def urlopen(request: object, timeout: float) -> _Response:
        nonlocal active, maximum
        del timeout
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                started_two.set()
        try:
            assert release.wait(2)
            return _blocking_response(request)
        finally:
            with lock:
                active -= 1

    limiter = GeminiRequestLimiter(2)
    detector = GeminiVisibleCardProvider(
        api_key="runtime-secret",
        urlopen=urlopen,
        request_limiter=limiter,
    )
    classifier = GeminiCardClassifier(
        api_key="runtime-secret",
        urlopen=urlopen,
        request_limiter=limiter,
    )
    detector_request = VisibleCardRequest(
        package_id="package-1",
        frame_part_name="frame-1",
        target_offset_ms=0,
        image_bytes=b"image",
        width=1,
        height=1,
        provider="gemini",
    )
    crop = b"P6\n4 4\n255\n" + bytes([255, 0, 0] * 16)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(detector.propose, detector_request),
            executor.submit(classifier.classify_ppm, crop),
            executor.submit(detector.propose, detector_request),
            executor.submit(classifier.classify_ppm, crop),
        ]
        assert started_two.wait(2)
        assert maximum == 2
        release.set()
        results = [future.result() for future in futures]

    assert all(result.status in {"ok", "unavailable"} for result in results)
    assert maximum == 2


def test_shared_gemini_limiter_cap_one_is_serial() -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()
    started_two = threading.Event()
    release = threading.Event()

    def urlopen(request: object, timeout: float) -> _Response:
        nonlocal active, maximum
        del timeout
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                started_two.set()
        try:
            assert release.wait(2)
            return _blocking_response(request)
        finally:
            with lock:
                active -= 1

    provider = GeminiVisibleCardProvider(
        api_key="runtime-secret",
        urlopen=urlopen,
        request_limiter=GeminiRequestLimiter(1),
    )
    request = VisibleCardRequest(
        package_id="package-1",
        frame_part_name="frame-1",
        target_offset_ms=0,
        image_bytes=b"image",
        width=1,
        height=1,
        provider="gemini",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(provider.propose, request) for _ in range(2)]
        time.sleep(0.05)
        assert maximum == 1
        assert not started_two.is_set()
        release.set()
        assert [future.result().status for future in futures] == ["ok", "ok"]

    assert maximum == 1
