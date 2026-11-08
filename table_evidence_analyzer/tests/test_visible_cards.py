import fcntl
import json
import multiprocessing
import os
import threading
import time
from pathlib import Path

import pytest

from table_evidence_analyzer import visible_cards as visible_cards_module
from table_evidence_analyzer.provider_response_cache import (
    ProviderResponseCacheLifecycle,
    ProviderResponseCacheRetention,
)
from table_evidence_analyzer.visible_cards import (
    CACHE_SCHEMA_VERSION,
    DEFAULT_MODEL,
    GEMINI_THINKING_LEVEL,
    GEMINI_VISIBLE_CARD_THINKING_LEVEL,
    IMPROVED_PROMPT,
    IMPROVED_REQUEST_SCHEMA_VERSION,
    PROMPT,
    RESPONSE_SCHEMA_V2,
    CachedVisibleCardProvider,
    FakeVisibleCardProvider,
    GeminiVisibleCardProvider,
    ProviderResult,
    VisibleCardRequest,
    VisibleCardValidationError,
    build_request_from_image,
    build_review_queue,
    load_review_queue,
    normalize_prediction,
    record_review,
    render_overlay_svg,
)


def _provider_cache_reader_worker(
    root: str,
    path: str,
    started: object,
    release: object,
    results: object,
) -> None:
    lifecycle = ProviderResponseCacheLifecycle(root, ProviderResponseCacheRetention())
    cache_path = Path(path)

    def loader() -> str:
        started.set()
        if not release.wait(timeout=10):
            raise TimeoutError("reader release was not signaled")
        return cache_path.read_text(encoding="utf-8")

    results.put(lifecycle.load(cache_path, loader))


def _provider_cache_writer_worker(
    root: str,
    path: str,
    attempting: object,
    entered_writer: object,
    finished: object,
) -> None:
    lifecycle = ProviderResponseCacheLifecycle(root, ProviderResponseCacheRetention())
    cache_path = Path(path)
    original_flock = fcntl.flock

    def flock_with_handshake(descriptor: int, operation: int) -> None:
        if operation & fcntl.LOCK_EX:
            attempting.set()
        original_flock(descriptor, operation)

    fcntl.flock = flock_with_handshake  # type: ignore[assignment]

    def writer() -> None:
        entered_writer.set()
        cache_path.write_text("new", encoding="utf-8")

    lifecycle.store(cache_path, writer)
    finished.set()


def _crash_visible_cache_writer(root: str, ready: object) -> None:
    def block_publish(*_args, **_kwargs) -> None:
        ready.set()
        while True:
            time.sleep(1)

    visible_cards_module.os.replace = block_publish
    request = _request()
    lifecycle = ProviderResponseCacheLifecycle(root, ProviderResponseCacheRetention())
    cached = CachedVisibleCardProvider(
        FakeVisibleCardProvider({request.image_sha256: _prediction()}),
        Path(root) / "visible-cards",
        lifecycle=lifecycle,
    )
    cached.propose_fresh(request)


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


def _improved_request() -> VisibleCardRequest:
    return VisibleCardRequest(
        package_id="package-001",
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=b"frame",
        width=1920,
        height=1080,
        prompt=IMPROVED_PROMPT,
        response_schema=RESPONSE_SCHEMA_V2,
        request_version=IMPROVED_REQUEST_SCHEMA_VERSION,
    )


def test_request_key_covers_image_and_provider_inputs() -> None:
    first = _request()

    assert first.model == DEFAULT_MODEL == "gemini-3.8-flash"
    assert GEMINI_THINKING_LEVEL == "low"
    assert GEMINI_VISIBLE_CARD_THINKING_LEVEL == "medium"
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


def test_improved_request_is_versioned_and_changes_cache_identity() -> None:
    improved = VisibleCardRequest(
        package_id="package-001",
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=b"frame",
        width=1920,
        height=1080,
        prompt=IMPROVED_PROMPT,
        response_schema=RESPONSE_SCHEMA_V2,
        request_version=IMPROVED_REQUEST_SCHEMA_VERSION,
    )
    legacy = _request()

    assert improved.to_mapping()["schema_version"] == IMPROVED_REQUEST_SCHEMA_VERSION
    assert "inferred full-card extent" in improved.prompt
    assert "tight axis-aligned bounding box" in improved.prompt
    assert improved.request_key != legacy.request_key


def test_polygon_prompt_prefers_simple_card_geometry() -> None:
    for prompt in (PROMPT, IMPROVED_PROMPT):
        normalized_prompt = " ".join(prompt.split())
        assert "Prefer the fewest points" in normalized_prompt
        assert "exactly four points" in normalized_prompt
        assert "usually by another card" in normalized_prompt
        assert "keep the visible card" in normalized_prompt
        assert "edges straight" in normalized_prompt
        assert "lie flat on the same table" in normalized_prompt
        assert "similar physical rectangle" in normalized_prompt
        assert "Perspective can make farther cards smaller" in normalized_prompt
        assert "non-right or non-parallel" in normalized_prompt
        assert "Do not require equal image sizes" in normalized_prompt
        assert "Do not invent a card" in normalized_prompt


def test_improved_request_can_repair_box_that_is_not_tight_to_visible_polygon() -> None:
    invalid = _prediction()
    invalid["cards"][0]["box_2d"]["x_min"] = 201

    with pytest.raises(VisibleCardValidationError, match="tight bounds"):
        normalize_prediction(invalid, require_tight_boxes=True)

    repaired = normalize_prediction(invalid, repair_tight_boxes=True)
    assert repaired.cards[0].box_2d == normalize_prediction(_prediction()).cards[0].box_2d

    assert normalize_prediction(_prediction(), require_tight_boxes=True).cards


def test_gemini_improved_response_repairs_non_tight_box_for_review() -> None:
    invalid = _prediction()
    invalid["cards"][0]["box_2d"]["x_min"] = 201

    def urlopen(_request: object, timeout: float) -> _FakeHTTPResponse:
        del timeout
        return _FakeHTTPResponse(
            {"candidates": [{"content": {"parts": [{"text": json.dumps(invalid)}]}}]}
        )

    result = GeminiVisibleCardProvider(
        api_key="runtime-secret",
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).propose(_improved_request())

    assert result.status == "ok"
    assert result.proposals[0].box_2d.x_min == 200
    assert normalize_prediction(result.prediction.to_mapping(), require_tight_boxes=True).cards
    assert result.raw_response is not None


def test_cached_old_tight_box_failure_is_retried_for_improved_request(tmp_path: Path) -> None:
    class _OldGeminiProvider:
        name = "gemini"
        version = "gemini-visible-cards-v1"

        def propose(self, _request: VisibleCardRequest) -> ProviderResult:
            return ProviderResult(
                status="unavailable",
                error=(
                    "Gemini returned a malformed response: card 1 "
                    "box_2d must be the tight bounds of its visible polygon."
                ),
            )

    request = _improved_request()
    cache_dir = tmp_path / "cache"
    first = CachedVisibleCardProvider(_OldGeminiProvider(), cache_dir).propose(request)
    assert first.status == "unavailable"

    invalid = _prediction()
    invalid["cards"][0]["box_2d"]["x_min"] = 201
    second = CachedVisibleCardProvider(
        FakeVisibleCardProvider({request.image_sha256: invalid}), cache_dir
    ).propose(request)

    assert second.status == "ok"
    assert second.cache_hit is False
    assert second.proposals[0].box_2d.x_min == 200


def test_improved_request_still_rejects_invalid_polygon_geometry() -> None:
    invalid = _prediction()
    invalid["cards"][0]["polygon"][0]["x"] = True

    with pytest.raises(VisibleCardValidationError, match="normalized integer"):
        normalize_prediction(invalid, repair_tight_boxes=True)


def test_normalize_prediction_returns_strict_proposals() -> None:
    prediction = normalize_prediction(_prediction())

    assert len(prediction.cards) == 1
    assert prediction.cards[0].box_2d.x_min == 200
    assert prediction.cards[0].polygon[2].y == 400

    invalid = _prediction()
    invalid["cards"][0]["polygon"][0]["x"] = True
    with pytest.raises(VisibleCardValidationError, match="normalized integer"):
        normalize_prediction(invalid)


def test_normalize_prediction_preserves_disconnected_visible_components() -> None:
    prediction = _prediction()
    card = prediction["cards"][0]
    card["polygons"] = [
        card["polygon"],
        [
            {"x": 700, "y": 600},
            {"x": 900, "y": 600},
            {"x": 900, "y": 900},
            {"x": 700, "y": 900},
        ],
    ]
    card["box_2d"] = {"y_min": 100, "x_min": 200, "y_max": 900, "x_max": 900}

    proposal = normalize_prediction(prediction, require_tight_boxes=True).cards[0]

    assert proposal.polygons is not None
    assert len(proposal.polygons) == 2
    assert proposal.box_2d.to_mapping() == {
        "y_min": 100,
        "x_min": 200,
        "y_max": 900,
        "x_max": 900,
    }


def test_fake_provider_is_deterministic_and_cache_stores_raw_and_normalized_outputs(
    tmp_path: Path,
) -> None:
    request = _request()
    fake = FakeVisibleCardProvider({request.image_sha256: _prediction()})
    first = fake.propose(request)
    assert first.status == "ok"
    assert first.proposals[0].label == "patterned card back"
    assert first.estimated_cost_usd == 0.0

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


def test_fresh_cached_provider_run_bypasses_and_refreshes_response_cache(
    tmp_path: Path,
) -> None:
    class _CountingProvider:
        name = "gemini"
        version = "gemini-visible-cards-v1"

        def __init__(self) -> None:
            self.calls = 0

        def propose(self, request: VisibleCardRequest) -> ProviderResult:
            self.calls += 1
            return FakeVisibleCardProvider({request.image_sha256: _prediction()}).propose(request)

    underlying = _CountingProvider()
    cached = CachedVisibleCardProvider(underlying, tmp_path / "cache")
    request = _request()

    cached.propose(request)
    assert cached.propose(request).cache_hit is True
    fresh = cached.propose_fresh(request)

    assert fresh.cache_hit is False
    assert underlying.calls == 2
    assert cached.propose(request).cache_hit is True


def test_bounded_provider_cache_replays_after_restart_without_provider_call(tmp_path: Path) -> None:
    request = _request()
    cache_root = tmp_path / "cache"
    lifecycle = ProviderResponseCacheLifecycle(cache_root, ProviderResponseCacheRetention())
    first = CachedVisibleCardProvider(
        FakeVisibleCardProvider({request.image_sha256: _prediction()}),
        cache_root / "visible-cards",
        lifecycle=lifecycle,
    )
    original = first.propose(request)

    class _NoProviderCall:
        name = "fake"
        version = "fake-v1"

        def propose(self, _request: VisibleCardRequest) -> ProviderResult:
            raise AssertionError("a replayed cache request called the provider")

    restarted = CachedVisibleCardProvider(
        _NoProviderCall(),
        cache_root / "visible-cards",
        lifecycle=ProviderResponseCacheLifecycle(cache_root, ProviderResponseCacheRetention()),
    )
    replay = restarted.propose(request)

    assert original.status == "ok"
    assert replay.cache_hit is True
    assert replay.proposals == original.proposals


def test_provider_cache_expiry_and_budget_preserve_pins(tmp_path: Path) -> None:
    now = [1_000_000.0]
    root = tmp_path / "cache"
    retention = ProviderResponseCacheRetention(
        max_bytes=4,
        idle_seconds=100,
        clock=lambda: now[0],
        sweep_interval_seconds=10,
    )
    lifecycle = ProviderResponseCacheLifecycle(root, retention)
    older = root / "visible-cards" / "aa" / "older.json"
    newer = root / "card-classification" / "bb" / "newer.json"
    pinned = root / "visible-cards" / "cc" / "pinned.json"
    for path in (older, newer, pinned):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1234", encoding="utf-8")
    os.utime(older, (now[0] - 3, now[0] - 3))
    os.utime(newer, (now[0] - 2, now[0] - 2))
    os.utime(pinned, (now[0] - 1, now[0] - 1))
    pinned.with_name("pinned.json.pin").write_text("pinned\n", encoding="utf-8")

    lifecycle.stored()
    assert not older.exists()
    assert newer.exists()
    assert pinned.exists()

    now[0] += 101
    assert lifecycle.load(pinned, lambda: pinned.read_text(encoding="utf-8")) == "1234"
    assert pinned.exists()

    stale = root / "visible-cards" / "dd" / "stale.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale", encoding="utf-8")
    os.utime(stale, (now[0] - 101, now[0] - 101))
    stale_value = lifecycle.load(
        stale,
        lambda: stale.read_text(encoding="utf-8") if stale.exists() else None,
    )
    assert stale_value is None
    assert not stale.exists()


def test_provider_cache_prune_recovers_after_interruption(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cache"
    lifecycle = ProviderResponseCacheLifecycle(
        root,
        ProviderResponseCacheRetention(
            max_bytes=4,
            idle_seconds=1000,
            clock=lambda: 1_000_010.0,
        ),
    )
    now = 1_000_000.0
    entries = [root / "visible-cards" / f"{index:02}.json" for index in range(3)]
    for index, path in enumerate(entries):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")
        os.utime(path, (now + index, now + index))

    real_unlink = Path.unlink
    interrupted = False

    def unlink_with_interruption(path: Path, *args, **kwargs) -> None:
        nonlocal interrupted
        if path == entries[1] and not interrupted:
            interrupted = True
            raise OSError("simulated interruption during cache pruning")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_with_interruption)
    with pytest.raises(OSError, match="simulated interruption"):
        lifecycle.stored()
    assert not entries[0].exists()
    assert entries[1].exists() and entries[2].exists()

    lifecycle.stored()
    assert not entries[0].exists()
    assert not entries[1].exists()
    assert entries[2].exists()


def test_provider_cache_serializes_independent_process_reader_and_writer(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    root = tmp_path / "cache"
    path = root / "visible-cards" / "entry.json"
    path.parent.mkdir(parents=True)
    path.write_text("old", encoding="utf-8")
    started = context.Event()
    release = context.Event()
    results = context.Queue()
    process = context.Process(
        target=_provider_cache_reader_worker,
        args=(str(root), str(path), started, release, results),
    )
    process.start()
    assert started.wait(timeout=10)
    writer_attempting = context.Event()
    writer_entered = context.Event()
    writer_finished = context.Event()
    writer = context.Process(
        target=_provider_cache_writer_worker,
        args=(str(root), str(path), writer_attempting, writer_entered, writer_finished),
    )
    writer.start()
    assert writer_attempting.wait(timeout=10)
    # Keep the reader lock held for a sustained interval after the writer announces
    # its lock attempt. The callback must remain unreachable during that interval.
    assert not writer_entered.wait(timeout=0.25)
    assert not writer_finished.is_set()
    release.set()
    process.join(timeout=10)
    assert process.exitcode == 0
    writer.join(timeout=10)
    assert writer.exitcode == 0
    assert writer_entered.is_set()
    assert writer_finished.is_set()
    assert results.get(timeout=2) == "old"
    assert path.read_text(encoding="utf-8") == "new"


def test_killed_provider_write_leaves_replayable_old_response(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    root = tmp_path / "cache"
    lifecycle = ProviderResponseCacheLifecycle(root, ProviderResponseCacheRetention())
    request = _request()
    cached = CachedVisibleCardProvider(
        FakeVisibleCardProvider({request.image_sha256: _prediction()}),
        root / "visible-cards",
        lifecycle=lifecycle,
    )
    original = cached.propose(request)
    path = cached._cache_path(request)
    original_bytes = path.read_bytes()

    ready = context.Event()
    process = context.Process(target=_crash_visible_cache_writer, args=(str(root), ready))
    process.start()
    assert ready.wait(timeout=10)
    process.terminate()
    process.join(timeout=10)
    assert process.exitcode is not None and process.exitcode != 0

    restarted = CachedVisibleCardProvider(
        _NoVisibleCardProviderCall(),
        root / "visible-cards",
        lifecycle=ProviderResponseCacheLifecycle(root, ProviderResponseCacheRetention()),
    )
    replay = restarted.propose(request)
    assert replay.cache_hit is True
    assert path.read_bytes() == original_bytes
    assert not list(path.parent.glob(f".{path.name}.*"))
    assert replay.proposals == original.proposals


class _NoVisibleCardProviderCall:
    name = "fake"
    version = "fake-v1"

    def propose(self, _request: VisibleCardRequest) -> ProviderResult:
        raise AssertionError("fresh-lifecycle recovery called the provider")


def test_interrupted_provider_cache_write_keeps_previous_response(
    tmp_path: Path, monkeypatch
) -> None:
    request = _request()
    cache_root = tmp_path / "cache"
    lifecycle = ProviderResponseCacheLifecycle(cache_root, ProviderResponseCacheRetention())
    cached = CachedVisibleCardProvider(
        FakeVisibleCardProvider({request.image_sha256: _prediction()}),
        cache_root / "visible-cards",
        lifecycle=lifecycle,
    )
    cached.propose(request)
    path = cached._cache_path(request)
    original = path.read_bytes()

    def interrupt_replace(*_args, **_kwargs) -> None:
        raise OSError("simulated interruption before cache publish")

    with monkeypatch.context() as patcher:
        patcher.setattr(visible_cards_module.os, "replace", interrupt_replace)
        with pytest.raises(OSError, match="simulated interruption"):
            cached.propose_fresh(request)

    assert path.read_bytes() == original
    assert not list(path.parent.glob(f".{path.name}.*"))
    replay = cached.propose(request)
    assert replay.cache_hit is True


def test_provider_cache_lifecycle_waits_for_active_cache_access(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    lifecycle = ProviderResponseCacheLifecycle(root, ProviderResponseCacheRetention())
    attempted = threading.Event()
    finished = threading.Event()

    def store() -> None:
        attempted.set()
        lifecycle.stored()
        finished.set()

    with lifecycle.access():
        worker = threading.Thread(target=store)
        worker.start()
        assert attempted.wait(timeout=2)
        assert not finished.is_set()

    worker.join(timeout=2)
    assert finished.is_set()


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
    assert (
        request.full_url == "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.8-flash:generateContent"
    )
    payload = json.loads(request.data)
    assert payload["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": GEMINI_VISIBLE_CARD_THINKING_LEVEL
    }
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
