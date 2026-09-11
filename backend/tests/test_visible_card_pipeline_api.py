from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
import time
from pathlib import Path

from app_factory import create_test_app
from doko_operations.derived_view import (
    DerivedViewMissingFrameError,
    ExactEventRequest,
    ResolvedFrame,
)
from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    EventDataRevision,
    EventRecord,
    HumanProducer,
    RunProgress,
    canonical_event_data_bytes,
    sha256_bytes,
)
from fastapi.testclient import TestClient
from PIL import Image
from table_evidence_analyzer.visible_cards import ProviderResult, normalize_prediction

from dokodetector_backend.config import Settings

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"
RECORDING_ID = "recording-both"


def _settings(tmp_path: Path, **values: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "repository_root": tmp_path,
        "evidence_root": tmp_path / "runtime",
        "repository_intake_root": tmp_path / "recordings",
        "evidence_package_intake_root": tmp_path / "evidence-packages",
        "pending_video_root": tmp_path / "pending-videos",
    }
    defaults.update(values)
    return Settings(**defaults)


def _install_recording(tmp_path: Path) -> None:
    bundle = tmp_path / "recordings" / RECORDING_ID
    shutil.copytree(FIXTURE_ROOT, bundle)
    video_path = bundle / "videos" / "video-both.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=2",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(video_path),
        ],
        check=True,
    )
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    byte_length = video_path.stat().st_size
    manifest_path = bundle / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["source_sha256"] = digest
    manifest["files"]["video"].update(byte_length=byte_length, sha256=digest)
    manifest_path.write_text(_json(manifest), encoding="utf-8")

    source_path = bundle / "source-record.json"
    source = _read_json(source_path)
    source.update(byte_length=byte_length, sha256=digest)
    source_path.write_text(_json(source), encoding="utf-8")
    proposal_path = bundle / "predictions" / "proposal-both.json"
    proposal = _read_json(proposal_path)
    proposal["source_sha256"] = digest
    proposal_path.write_text(_json(proposal), encoding="utf-8")
    manifest = _read_json(manifest_path)
    for relative_path, path in (
        ("source_record", source_path),
        ("proposal_generator_runs", proposal_path),
    ):
        descriptor = (
            manifest["files"][relative_path]
            if relative_path == "source_record"
            else manifest["files"][relative_path][0]
        )
        raw = path.read_bytes()
        descriptor.update(byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(_json(manifest), encoding="utf-8")


def _json(value: object) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


def _read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


class _EventProvider:
    def infer(self, video_path: Path, *, request: object) -> dict[str, object]:
        del video_path, request
        return {
            "events": [
                {"time_s": 0.1, "probability": 0.9},
                {"time_s": 0.3, "probability": 0.8},
                {"time_s": 0.4, "probability": 0.7},
                {"time_s": 0.5, "probability": 0.6},
                {"time_s": 0.6, "probability": 0.5, "event_type": "trick_taken"},
            ]
        }


class _FrameResolver:
    decoder_version = "fixture-decoder/v1"
    transform_version = "fixture-frame/v1"

    def resolve(self, request: ExactEventRequest, video_path: Path) -> ResolvedFrame:
        del video_path
        if request.requested_time_us == 500_000:
            raise DerivedViewMissingFrameError("fixture has no frame")
        image = Image.new("RGB", (64, 64), (40, 50, 60))
        from io import BytesIO

        output = BytesIO()
        image.save(output, format="JPEG")
        image_bytes = output.getvalue()
        return ResolvedFrame(
            requested_time_us=request.requested_time_us,
            frame_index=request.requested_time_us // 100_000,
            presentation_timestamp_us=request.requested_time_us,
            source_video_sha256=request.source.video_sha256,
            width=64,
            height=64,
            decoder_version=self.decoder_version,
            transform_version=self.transform_version,
            output_encoding="jpeg",
            image_bytes=image_bytes,
        )


class _Detector:
    name = "fixture-detector"
    version = "fixture-detector/v1"

    def propose(self, request: object) -> ProviderResult:
        package_id = request.package_id  # type: ignore[attr-defined]
        if package_id.endswith("event-000002"):
            return ProviderResult(status="unavailable", error="fixture detector failed")
        if package_id.endswith("event-000000"):
            prediction = normalize_prediction(
                {
                    "cards": [
                        {
                            "box_2d": {
                                "x_min": 100,
                                "y_min": 200,
                                "x_max": 700,
                                "y_max": 800,
                            },
                            "polygon": [
                                {"x": 100, "y": 200},
                                {"x": 700, "y": 200},
                                {"x": 560, "y": 800},
                                {"x": 100, "y": 800},
                            ],
                            "side": "unknown",
                            "label": "visible card",
                        }
                    ]
                }
            )
            return ProviderResult(status="ok", proposals=prediction.cards)
        return ProviderResult(status="ok")


class _GeminiDetector(_Detector):
    name = "gemini"
    version = "gemini-visible-cards-v1"


def _run_blocking_visible_detection(tmp_path: Path, cap: int) -> tuple[int, list[str]]:
    _install_recording(tmp_path)
    active = 0
    maximum = 0
    calls = 0
    lock = threading.Lock()
    started_one = threading.Event()
    started_two = threading.Event()
    release = threading.Event()

    class BlockingDetector:
        name = "blocking-detector"
        version = "blocking-detector/v1"

        def propose(self, request: object) -> ProviderResult:
            nonlocal active, maximum, calls
            del request
            with lock:
                active += 1
                calls += 1
                maximum = max(maximum, active)
                started_one.set()
                if active == 2:
                    started_two.set()
            try:
                assert release.wait(2)
                return ProviderResult(status="ok")
            finally:
                with lock:
                    active -= 1

    app = create_test_app(
        _settings(tmp_path, gemini_max_concurrent_requests=cap),
        event_provider=_EventProvider(),
        visible_card_provider=BlockingDetector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json={"run_id": "events-blocking"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-blocking")
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/events-blocking/result"
        ).json()["state"]["output_revision_ids"][0]
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "visible-blocking", "event_revision_id": event_revision_id},
        )
        assert visible_response.status_code == 202
        assert started_one.wait(2)
        if cap == 1:
            time.sleep(0.05)
            assert calls == 1
            assert not started_two.is_set()
        else:
            assert started_two.wait(2)
            assert maximum == 2
        release.set()
        assert _wait(client, "visible-blocking")["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-blocking/result"
        ).json()
        event_ids = [
            outcome["event_id"] for outcome in result["revisions"][0]["content"]["outcomes"]
        ]
    return maximum, event_ids


def test_visible_card_events_are_bounded_and_ordered(tmp_path: Path) -> None:
    maximum, event_ids = _run_blocking_visible_detection(tmp_path, 2)

    assert maximum == 2
    assert event_ids == [
        "event-000000",
        "event-000001",
        "event-000002",
        "event-000003",
    ]


def test_visible_card_cap_one_remains_serial(tmp_path: Path) -> None:
    maximum, _ = _run_blocking_visible_detection(tmp_path, 1)

    assert maximum == 1


def _wait(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    body: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{run_id}")
        body = response.json()
        if body["state"]["status"] in {"complete", "failed"}:
            return body
        time.sleep(0.01)
    return body


def _manual_event_revision(app, source, base: EventDataRevision) -> str:
    content = EventData(
        events=tuple(
            EventRecord(
                event_id=event.event_id,
                event_type=event.event_type,
                start_us=event.start_us,
                end_us=event.end_us,
            )
            for event in base.content.events
        )
    )
    revision_id = "events-manual-reference"
    revision = EventDataRevision(
        manifest=DataRevision(
            revision_id=revision_id,
            content_type="events",
            content_schema="event-data/v1",
            recording_id=RECORDING_ID,
            source=source,
            content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
            input_revision_ids=(),
            origin="manual",
            producer=HumanProducer(review_id="review-1", operator_id="operator-1"),
            coverage={"kind": "fixture"},
            created_at="2026-01-01T00:00:00Z",
        ),
        content=content,
    )
    stored, _ = app.state.pipeline_revision_store.publish(revision)
    current = app.state.pipeline_selection_store.get(RECORDING_ID, "events")
    app.state.pipeline_selection_store.update_pointers(
        RECORDING_ID,
        "events",
        expected_revision=0 if current is None else current.revision,
        selected_generated_revision_id=base.manifest.revision_id,
        selected_completed_reference_revision_id=stored.manifest.revision_id,
    )
    return stored.manifest.revision_id


def test_visible_card_pipeline_uses_selected_event_revisions_and_retains_outcomes(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )

    with TestClient(app) as client:
        event_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json={"run_id": "events-generated"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-generated")
        event_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/events-generated/result"
        ).json()
        generated_event_revision_id = event_result["state"]["output_revision_ids"][0]
        generated_event_revision = app.state.pipeline_revision_store.require(
            generated_event_revision_id
        )

        visible_generated = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-generated",
                "event_revision_id": generated_event_revision_id,
                "input_revision_ids": [generated_event_revision_id],
                "configuration": {"threshold": 0.5},
            },
        )
        assert visible_generated.status_code == 202
        generated_status = _wait(client, "visible-generated")
        assert generated_status["state"]["status"] == "complete"
        generated_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-generated/result"
        ).json()
        generated_content = generated_result["revisions"][0]["content"]
        assert generated_result["request"]["input_revision_ids"] == [generated_event_revision_id]
        assert [outcome["status"] for outcome in generated_content["outcomes"]] == [
            "detected",
            "empty",
            "failed",
            "failed",
        ]
        assert [outcome["event_id"] for outcome in generated_content["outcomes"]] == [
            "event-000000",
            "event-000001",
            "event-000002",
            "event-000003",
        ]
        assert generated_content["outcomes"][0]["candidates"][0]["geometry"]["kind"] == (
            "visible-region/v1"
        )
        assert generated_content["outcomes"][0]["candidates"][0]["geometry"]["visible_region"][
            "polygons"
        ] == [
            [
                {"x": 100, "y": 200},
                {"x": 700, "y": 200},
                {"x": 560, "y": 800},
                {"x": 100, "y": 800},
            ]
        ]
        assert generated_content["outcomes"][2]["error"] == "fixture detector failed"
        assert generated_content["outcomes"][2]["frame_identity"] is not None
        assert generated_content["outcomes"][3]["frame_identity"] is None
        generated_card_id = generated_content["outcomes"][0]["candidates"][0]["card_id"]
        assert generated_result["request"]["configuration"]["detector"] == {
            "name": "fixture-detector",
            "version": "fixture-detector/v1",
        }

        manual_revision_id = _manual_event_revision(
            app, generated_event_revision.manifest.source, generated_event_revision
        )
        visible_reference = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "visible-reference", "configuration": {"threshold": 0.6}},
        )
        assert visible_reference.status_code == 202
        _wait(client, "visible-reference")
        reference_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-reference/result"
        ).json()
        assert reference_result["request"]["input_revision_ids"] == [manual_revision_id]
        reference_card_id = reference_result["revisions"][0]["content"]["outcomes"][0][
            "candidates"
        ][0]["card_id"]
        assert reference_card_id != generated_card_id
        selection = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/selection"
        ).json()
        assert (
            selection["selection"]["selected_generated_revision_id"]
            == reference_result["state"]["output_revision_ids"][0]
        )

    restarted = create_test_app(
        _settings(tmp_path),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(restarted) as client:
        persisted = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-generated/result"
        )
        assert persisted.status_code == 200
        assert [
            outcome["status"] for outcome in persisted.json()["revisions"][0]["content"]["outcomes"]
        ] == ["detected", "empty", "failed", "failed"]


def test_visible_card_pipeline_uses_configured_gemini_model_for_provider_placeholder(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path, gemini_model="gemini-test-model"),
        event_provider=_EventProvider(),
        visible_card_provider=_GeminiDetector(),
        visible_card_frame_resolver=_FrameResolver(),
    )

    with TestClient(app) as client:
        event_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json={"run_id": "events-for-model"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-for-model")
        event_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/events-for-model/result"
        ).json()
        event_revision_id = event_result["state"]["output_revision_ids"][0]

        request = app.state.visible_card_pipeline_service._build_request(
            RECORDING_ID,
            {
                "run_id": "visible-for-model",
                "event_revision_id": event_revision_id,
                "model": {"name": "gemini", "version": "gemini-visible-cards-v1"},
            },
        )

    assert request.model is not None
    assert request.model.name == "gemini-test-model"
    assert request.model.version == "gemini-visible-cards-v1"


def test_visible_card_pipeline_retry_resumes_retained_items(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )

    with TestClient(app) as client:
        event_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json={"run_id": "events-for-visible-retry"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-for-visible-retry")
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/events-for-visible-retry/result"
        ).json()["state"]["output_revision_ids"][0]

        baseline_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-retry-baseline",
                "event_revision_id": event_revision_id,
            },
        )
        assert baseline_response.status_code == 202
        assert _wait(client, "visible-retry-baseline")["state"]["status"] == "complete"
        baseline = app.state.pipeline_run_store.require("visible-retry-baseline")

        request = app.state.visible_card_pipeline_service._build_request(
            RECORDING_ID,
            {"run_id": "visible-retry", "event_revision_id": event_revision_id},
        )
        stored, created = app.state.pipeline_run_store.create(request)
        assert created
        app.state.pipeline_run_store.start(stored.run_id)
        app.state.pipeline_run_store.partial(
            stored.run_id,
            progress=RunProgress(completed=1, total=4),
            items=(baseline.state.items[0],),
        )

        retry_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-retry/retry"
        )
        assert retry_response.status_code == 202
        status = _wait(client, "visible-retry")

    assert status["state"]["status"] == "complete"
    assert status["state"]["progress"] == {"completed": 4, "total": 4}
    assert len(status["state"]["items"]) == 4


def test_exact_event_derived_view_route_retrieves_a_cold_cache_frame(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        visible_card_frame_resolver=_FrameResolver(),
    )

    path = f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/exact-event/400000"
    with TestClient(app) as client:
        first = client.get(path)
        assert first.status_code == 200
        assert first.headers["content-type"] == "image/jpeg"
        assert first.headers["cache-control"] == "private, max-age=31536000, immutable"
        assert first.headers["etag"].startswith('"')

        cache_root = tmp_path / "runtime" / "pipeline" / "derived-views"
        assert any(cache_root.rglob("*"))
        shutil.rmtree(cache_root)

        second = client.get(path)
        assert second.status_code == 200
        assert second.content == first.content
        assert second.headers["etag"] == first.headers["etag"]


def _wait_event(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    body: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/{run_id}")
        body = response.json()
        if body["state"]["status"] == "complete":
            return body
        time.sleep(0.01)
    return body
