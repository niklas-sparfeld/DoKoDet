import json

from table_evidence_analyzer.card_classification import CachedCardClassifier, GeminiCardClassifier


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


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
