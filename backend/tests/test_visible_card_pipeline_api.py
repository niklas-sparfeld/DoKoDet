from __future__ import annotations

import hashlib
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from app_factory import create_test_app
from doko_operations.derived_view import (
    DerivedViewMissingFrameError,
    ExactEventRequest,
    ResolvedFrame,
)
from doko_operations.pipeline_data import (
    EventData,
    RecordingVideoSource,
    RunItemOutcome,
    RunProgress,
)
from fastapi.testclient import TestClient
from PIL import Image
from table_evidence_analyzer.visible_cards import (
    NormalizedPoint,
    ProviderResult,
    VisibleCardPileProposal,
    normalize_prediction,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.recording_folder_store import RecordingFolderStore

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
    recordings_root = tmp_path / "data" / "recordings"
    if not (recordings_root / RECORDING_ID).exists():
        RecordingFolderStore(recordings_root).publish_bundle(bundle, recording_id=RECORDING_ID)


def _json(value: object) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


def _enqueue_event(client: TestClient, payload: dict[str, object]):
    return client.post(
        "/api/jobs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "type": "event_processing",
            "context": {"recording_id": RECORDING_ID},
            "request": payload,
        },
    )


def _run_event_job(client: TestClient, run_id: str) -> str:
    response = _enqueue_event(client, {"run_id": run_id})
    assert response.status_code == 202, response.text
    result = _wait_event(client, response.json()["id"])
    assert result["state"]["status"] == "complete", result
    assert result["state"]["output_revision_ids"] == []
    return response.json()["id"]


def _event_set_reference(client: TestClient, run_id: str | None = None) -> dict[str, str]:
    listing = client.get(f"/api/recordings/{RECORDING_ID}/event-sets").json()
    event_sets = listing["event_sets"]
    expected_id = None if run_id is None else f"run-{run_id}"
    event_set = next(
        item for item in event_sets if expected_id is None or item["set_id"] == expected_id
    )
    content = client.get(
        f"/api/recordings/{RECORDING_ID}/event-sets/{event_set['set_id']}/versions/{event_set['version']}"
    ).json()
    reference = {
        "set_id": event_set["set_id"],
        "version": event_set["version"],
        "content_sha256": content["content_sha256"],
    }
    selected = client.put(
        f"/api/recordings/{RECORDING_ID}/event-sets/selection",
        json={
            "choice": "generated",
            "reference": {"set_id": reference["set_id"], "version": reference["version"]},
            "expected_recording_version": listing["recording_version"],
        },
    )
    assert selected.status_code == 200, selected.text
    return reference


def _selected_node_input(
    client: TestClient, content_type: str, revision_id: str | None = None
) -> dict[str, object]:
    if content_type == "events":
        return {"input_event_set_ref": _event_set_reference(client, revision_id)}
    response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline?stage={content_type}")
    assert response.status_code == 200, response.text
    workspace = response.json()
    stage = next(item for item in workspace["stages"] if item["key"] == content_type)
    selected = revision_id or (stage["selected_completed_reference"] or stage["selected_generated"])
    selected_revision_id = selected["revision_id"] if isinstance(selected, dict) else selected
    option = next(
        item for item in stage["input_options"] if item["node_revision_id"] == selected_revision_id
    )
    revision_id = option["node_revision_id"]
    return {
        "input_node_ref": {
            "node_id": option["node_id"],
            "revision_id": revision_id,
            "revision_policy": "current_head" if option["is_current_head"] else "historical",
        },
    }


def _read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


class _EventProvider:
    def infer(
        self,
        video_path: Path,
        *,
        request: object,
        progress_callback: object | None = None,
    ) -> dict[str, object]:
        del video_path, request, progress_callback
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

    def resolve_frame_index(
        self, video_path: Path, source: RecordingVideoSource, frame_index: int, **_: object
    ) -> ResolvedFrame:
        return self.resolve(
            ExactEventRequest(
                source=source,
                requested_time_us=frame_index * 100_000,
            ),
            video_path,
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


class _PileDetector(_Detector):
    name = "local-rfdetr-segmentation"
    version = "local-rfdetr-segmentation-v1"

    def propose(self, request: object) -> ProviderResult:
        result = super().propose(request)
        package_id = request.package_id  # type: ignore[attr-defined]
        if result.status != "ok" or not package_id.endswith("event-000000"):
            return result
        return ProviderResult(
            status="ok",
            proposals=result.proposals,
            pile_proposals=(
                VisibleCardPileProposal(
                    polygon=(
                        NormalizedPoint(150, 150),
                        NormalizedPoint(850, 150),
                        NormalizedPoint(850, 850),
                        NormalizedPoint(150, 850),
                    ),
                    confidence=0.87,
                    model_lineage={
                        "provider": self.name,
                        "bundle_identity": {"bundle_digest": "a" * 64},
                    },
                ),
            ),
            raw_response={"pile_detection_supported": True},
        )


def _run_blocking_visible_detection(
    tmp_path: Path, cap: int, *, event_limit: int | None = None
) -> tuple[int, list[str]]:
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

    if event_limit is not None:
        BlockingDetector.event_concurrency_limit = event_limit

    app = create_test_app(
        _settings(tmp_path, gemini_max_concurrent_requests=cap),
        event_provider=_EventProvider(),
        visible_card_provider=BlockingDetector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "events-blocking"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        event_revision_id = event_run_id
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-blocking",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert visible_response.status_code == 202
        visible_run_id = visible_response.json()["run_id"]
        assert started_one.wait(2)
        expected = min(1, cap, event_limit or cap)
        if expected == 1:
            time.sleep(0.05)
            assert calls == 1
            assert not started_two.is_set()
        else:
            assert started_two.wait(2)
            assert maximum == 2
        release.set()
        assert _wait(client, visible_run_id)["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
        ).json()
        event_ids = [
            outcome["event_id"] for outcome in result["revisions"][0]["content"]["outcomes"]
        ]
    return maximum, event_ids


def test_visible_card_run_uses_exact_event_set_without_event_node_reads(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    recordings_root = tmp_path / "data" / "recordings"
    app = create_test_app(
        _settings(tmp_path, recordings_root=recordings_root),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "events-exact-set"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        event_sets = client.get(f"/api/recordings/{RECORDING_ID}/event-sets").json()["event_sets"]
        event_set = event_sets[0]
        event_set_content = client.get(
            f"/api/recordings/{RECORDING_ID}/event-sets/{event_set['set_id']}/versions/{event_set['version']}"
        ).json()
        listing = client.get(f"/api/recordings/{RECORDING_ID}/event-sets").json()
        selected = client.put(
            f"/api/recordings/{RECORDING_ID}/event-sets/selection",
            json={
                "choice": "generated",
                "reference": {"set_id": event_set["set_id"], "version": event_set["version"]},
                "expected_recording_version": listing["recording_version"],
            },
        )
        assert selected.status_code == 200, selected.text
        node_store = app.state.visible_card_pipeline_service.node_store
        original_read = node_store.read_revision
        original_history = node_store.history

        def forbid_event_node_read(node_id: str, revision_id: str):
            if node_store.get(node_id).content_type == "events":
                raise AssertionError("visible-card workflow read a legacy event node")
            return original_read(node_id, revision_id)

        def forbid_event_node_history(node_id: str):
            if node_store.get(node_id).content_type == "events":
                raise AssertionError("workspace enumerated legacy event-node history")
            return original_history(node_id)

        node_store.read_revision = forbid_event_node_read
        node_store.history = forbid_event_node_history
        workspace = client.get(f"/api/recordings/{RECORDING_ID}/pipeline").json()
        node_store.history = original_history
        selected_from_workspace = workspace["stages"][0]["selected_event_set_generated"]
        assert selected_from_workspace == {
            "set_id": event_set["set_id"],
            "version": event_set["version"],
        }
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-exact-event-set",
                "input_event_set_ref": {
                    **selected_from_workspace,
                    "content_sha256": event_set_content["content_sha256"],
                },
            },
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        assert _wait(client, run_id)["state"]["status"] == "complete"
        run = app.state.visible_card_pipeline_service.run_store.require(run_id)
        assert run.request.input_event_set_ref == {
            "set_id": event_set["set_id"],
            "version": event_set["version"],
            "content_sha256": event_set_content["content_sha256"],
        }
        assert run.request.input_revision_ids == ()
        lineage = _read_json(node_store.root / ".lineage-runs" / f"{run_id}.json")
        assert lineage["inputs"][0] == {
            "kind": "artifact",
            "artifact_id": f"event-set/{event_set['set_id']}/versions/{event_set['version']}",
            "sha256": event_set_content["content_sha256"],
            "role": "events",
        }


def test_visible_card_run_rejects_legacy_event_node_input(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_run_id = _run_event_job(client, "legacy-node-input")
        nodes = app.state.pipeline_selection_store.node_store
        source = app.state.event_pipeline_service.get_recording_source(RECORDING_ID).to_mapping()
        node = nodes.create(
            "legacy-events",
            "Legacy event node",
            "events",
            source,
            EventData(events=()).to_mapping(),
            {},
        )
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-reject-legacy-node",
                "input_node_ref": {
                    "node_id": node.node_id,
                    "revision_id": node.revision_id,
                    "revision_policy": "current_head",
                },
            },
        )
    assert event_run_id
    assert response.status_code == 422
    assert "event-set" in response.json()["error"]["message"]


def test_visible_card_retry_keeps_exact_event_set_after_head_selection_changes(
    tmp_path: Path, monkeypatch
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    terminal_jobs: queue.Queue[tuple[str, str]] = queue.Queue()

    with TestClient(app) as client:
        event_run_id = _run_event_job(client, "events-retry-input")
        input_ref = _event_set_reference(client, event_run_id)
        service = app.state.visible_card_pipeline_service
        manager = app.state.job_manager_service.get_manager()
        original_transition = manager.transition

        def record_terminal_transition(job_id: str, state: str):
            result = original_transition(job_id, state)
            if state in {"succeeded", "failed", "cancelled", "interrupted"}:
                terminal_jobs.put((job_id, state))
            return result

        monkeypatch.setattr(manager, "transition", record_terminal_transition)
        publish_reached = threading.Event()
        release_failure = threading.Event()
        original_publish = service._publish_revision
        publish_attempts = 0

        def fail_first_publish(run, content):
            nonlocal publish_attempts
            publish_attempts += 1
            if publish_attempts == 1:
                publish_reached.set()
                assert release_failure.wait(5), "test did not release the fixture failure"
                raise RuntimeError("fixture publication failure")
            return original_publish(run, content)

        monkeypatch.setattr(service, "_publish_revision", fail_first_publish)
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "visible-exact-retry", "input_event_set_ref": input_ref},
        )
        assert response.status_code == 202
        failed_run_id = response.json()["run_id"]
        assert publish_reached.wait(5), "visible-card fixture did not reach publication"

        alternate = app.state.event_set_store.save(
            RECORDING_ID,
            set_id="manual-alternate",
            version="1",
            content=EventData(events=()).to_mapping(),
            origin="manual",
            provenance={"source": {"recording_id": RECORDING_ID}},
        )
        listing = client.get(f"/api/recordings/{RECORDING_ID}/event-sets").json()
        selected = client.put(
            f"/api/recordings/{RECORDING_ID}/event-sets/selection",
            json={
                "choice": "generated",
                "reference": {"set_id": alternate["set_id"], "version": alternate["version"]},
                "expected_recording_version": listing["recording_version"],
            },
        )
        assert selected.status_code == 200, selected.text

        release_failure.set()
        assert _wait_for_terminal_job(terminal_jobs, failed_run_id) == "failed"
        initial_run = app.state.pipeline_run_store.require(failed_run_id)
        assert initial_run.request.input_event_set_ref == input_ref
        assert initial_run.request.input_revision_ids == ()

        retry_response = client.post(
            f"/api/jobs/{failed_run_id}/retry",
            headers={"Idempotency-Key": str(uuid4())},
            json={},
        )
        assert retry_response.status_code == 202
        retry_run_id = retry_response.json()["id"]
        assert _wait_for_terminal_job(terminal_jobs, retry_run_id) == "succeeded"
        retry_job = client.get(f"/api/jobs/{retry_run_id}").json()
        assert retry_job["retry_of"] == failed_run_id
        retried_run = app.state.pipeline_run_store.require(retry_run_id)
        assert retried_run.request.input_event_set_ref == input_ref
        assert retried_run.request.input_revision_ids == ()
        assert retry_job["inputs"][-1] == {
            "kind": "artifact",
            "id": f"event-set/{input_ref['set_id']}/versions/{input_ref['version']}",
            "digest": input_ref["content_sha256"],
        }


def test_visible_card_events_respect_the_single_worker_budget(tmp_path: Path) -> None:
    maximum, event_ids = _run_blocking_visible_detection(tmp_path, 2)

    assert maximum == 1
    assert event_ids == [
        "event-000000",
        "event-000001",
        "event-000002",
        "event-000003",
        "event-000004",
    ]


def test_visible_card_cap_one_remains_serial(tmp_path: Path) -> None:
    maximum, _ = _run_blocking_visible_detection(tmp_path, 1)

    assert maximum == 1


def test_visible_card_provider_event_limit_overrides_global_cap(tmp_path: Path) -> None:
    maximum, _ = _run_blocking_visible_detection(tmp_path, 2, event_limit=1)

    assert maximum == 1


def _wait(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    body: dict = {}
    while time.monotonic() < deadline:
        job_response = client.get(f"/api/jobs/{run_id}")
        if job_response.status_code == 200:
            job = job_response.json()
            if job["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                result = client.get(
                    f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{run_id}/result"
                )
                if result.status_code == 200:
                    return result.json()
                return {
                    "state": {
                        "status": "complete" if job["state"] == "succeeded" else job["state"],
                        "progress": {"completed": 0, "total": 0},
                        "items": [],
                    },
                    "failure": job.get("failure"),
                }
        time.sleep(0.01)
    return body


def _wait_for_terminal_job(terminal_jobs: queue.Queue[tuple[str, str]], job_id: str) -> str:
    deadline = time.monotonic() + 5
    pending: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        try:
            completed_id, state = terminal_jobs.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            break
        if completed_id == job_id:
            for item in pending:
                terminal_jobs.put(item)
            return state
        pending.append((completed_id, state))
    for item in pending:
        terminal_jobs.put(item)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def test_visible_card_run_status_uses_shared_job_resource(
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
        event_response = _enqueue_event(client, {"run_id": "events-for-visible-status"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        event_revision_id = event_run_id
        service = app.state.visible_card_pipeline_service
        request = service._build_request(
            RECORDING_ID,
            {
                "run_id": "visible-status-metadata",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        stored, created = app.state.pipeline_run_store.create(request)
        assert created
        app.state.pipeline_run_store.start(stored.run_id)
        app.state.pipeline_run_store.record_item_progress(
            stored.run_id,
            progress=RunProgress(completed=1, total=5),
            item=RunItemOutcome(
                item_id="event-000000",
                status="succeeded",
                result={"event_id": "event-000000"},
                failure=None,
            ),
        )

        legacy_response = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{stored.run_id}"
        )

    assert legacy_response.status_code == 404


def test_visible_card_run_requires_an_explicit_event_input_when_a_selection_exists(
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
        event_run_id = _run_event_job(client, "events-selected-without-input")
        _event_set_reference(client, event_run_id)
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "visible-no-event-input"},
        )
    assert response.status_code == 422
    assert "event-set" in response.json()["error"]["message"]


def test_visible_card_pipeline_uses_explicit_event_revisions_and_retains_outcomes(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_PileDetector(),
        visible_card_frame_resolver=_FrameResolver(),
    )

    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "events-generated"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        generated_event_revision_id = event_run_id
        generated_event_set_ref = _event_set_reference(client, event_run_id)

        visible_generated = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-generated",
                **_selected_node_input(client, "events", generated_event_revision_id),
                "configuration": {"threshold": 0.5},
            },
        )
        assert visible_generated.status_code == 202
        generated_run_id = visible_generated.json()["run_id"]
        generated_status = _wait(client, generated_run_id)
        assert generated_status["state"]["status"] == "complete"
        generated_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{generated_run_id}/result"
        ).json()
        assert not hasattr(app.state, "pipeline_revision_store")
        generated_content = generated_result["revisions"][0]["content"]
        assert generated_result["request"]["input_revision_ids"] == []
        assert generated_result["request"]["input_event_set_ref"] == generated_event_set_ref
        detection_ref = generated_result["detection_set_ref"]
        assert detection_ref["set_id"] == f"detector-{generated_run_id}"
        assert detection_ref["version"] == "1"
        detection_set = client.get(
            f"/api/recordings/{RECORDING_ID}/detection-sets/{detection_ref['set_id']}/versions/{detection_ref['version']}"
        ).json()
        assert detection_ref["content_sha256"] == detection_set["content_sha256"]
        assert detection_set["event_sets"] == [generated_event_set_ref]
        assert [frame["frame_id"] for frame in detection_set["content"]["frames"]] == [
            "event-000000",
            "event-000001",
            "event-000004",
        ]
        assert detection_set["content"]["frames"][0]["detections"][0]["kind"] == "visible_card"
        assert detection_set["content"]["frames"][0]["detections"][0]["segments"][0]["polygon"] == [
            {"x": 6, "y": 13},
            {"x": 45, "y": 13},
            {"x": 36, "y": 51},
            {"x": 6, "y": 51},
        ]
        assert detection_set["content"]["frames"][1]["detections"] == []
        assert "event-000002" not in detection_set["frames"]
        assert "event-000003" not in detection_set["frames"]
        assert [outcome["status"] for outcome in generated_content["outcomes"]] == [
            "detected",
            "empty",
            "failed",
            "failed",
            "empty",
        ]
        assert [outcome["event_id"] for outcome in generated_content["outcomes"]] == [
            "event-000000",
            "event-000001",
            "event-000002",
            "event-000003",
            "event-000004",
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
        assert generated_content["outcomes"][0]["candidates"][0]["side"] == "unknown"
        assert generated_content["outcomes"][0]["pile_detection_status"] == "supported"
        pile = generated_content["outcomes"][0]["pile_regions"][0]
        assert pile["origin"] == "model_prediction"
        assert pile["confidence"] == 0.87
        assert pile["model_lineage"]["bundle_identity"]["bundle_digest"] == "a" * 64
        assert pile["geometry"]["polygons"][0][0] == {"x": 150, "y": 150}
        assert generated_content["outcomes"][1]["pile_detection_status"] == "unsupported"
        assert generated_content["outcomes"][2]["error"] == "fixture detector failed"
        assert generated_content["outcomes"][2]["frame_identity"] is not None
        assert generated_content["outcomes"][3]["frame_identity"] is None
        assert generated_result["request"]["configuration"]["detector"] == {
            "name": "local-rfdetr-segmentation",
            "version": "local-rfdetr-segmentation-v1",
        }

    restarted = create_test_app(
        _settings(tmp_path),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(restarted) as client:
        persisted = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{generated_run_id}/result"
        )
        assert persisted.status_code == 200
        assert [
            outcome["status"] for outcome in persisted.json()["revisions"][0]["content"]["outcomes"]
        ] == ["detected", "empty", "failed", "failed", "empty"]
        persisted_detection_set = client.get(
            f"/api/recordings/{RECORDING_ID}/detection-sets/{detection_ref['set_id']}/versions/{detection_ref['version']}"
        )
        assert persisted_detection_set.status_code == 200
        assert persisted_detection_set.json() == detection_set


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
        event_response = _enqueue_event(client, {"run_id": "events-for-model"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        event_revision_id = event_run_id

        request = app.state.visible_card_pipeline_service._build_request(
            RECORDING_ID,
            {
                "run_id": "visible-for-model",
                **_selected_node_input(client, "events", event_revision_id),
                "model": {"name": "gemini", "version": "gemini-visible-cards-v1"},
            },
        )

    assert request.model is not None
    assert request.model.name == "gemini-test-model"
    assert request.model.version == "gemini-visible-cards-v1"


def test_visible_card_pipeline_retry_creates_a_linked_managed_job(tmp_path: Path) -> None:
    _install_recording(tmp_path)

    class RetryableDetector(_Detector):
        event_concurrency_limit = False

    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=RetryableDetector(),
        visible_card_frame_resolver=_FrameResolver(),
    )

    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "events-for-visible-retry"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        event_revision_id = event_run_id

        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-retry",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert response.status_code == 202
        source_job_id = response.json()["run_id"]
        failed_status = _wait(client, source_job_id)
        assert failed_status["state"]["status"] == "failed"
        app.state.visible_card_pipeline_service.detector_provider.event_concurrency_limit = 1

        retry_response = client.post(
            f"/api/jobs/{source_job_id}/retry",
            headers={"Idempotency-Key": str(uuid4())},
            json={},
        )
        assert retry_response.status_code == 202
        retried_run_id = retry_response.json()["id"]
        status = _wait(client, retried_run_id)
        retried_job = client.get(f"/api/jobs/{retried_run_id}").json()

    assert status["state"]["status"] == "complete"
    assert status["state"]["progress"] == {"completed": 5, "total": 5}
    assert len(status["state"]["items"]) == 5
    assert retried_job["retry_of"] == source_job_id


def test_visible_card_cancellation_prevents_result_publication(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    started = threading.Event()
    release = threading.Event()

    class BlockingDetector:
        name = "blocking-detector"
        version = "blocking-detector/v1"

        def propose(self, request: object) -> ProviderResult:
            del request
            started.set()
            assert release.wait(3)
            return ProviderResult(status="ok")

    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=BlockingDetector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_job = _enqueue_event(client, {"run_id": "events-for-visible-cancel"})
        assert event_job.status_code == 202
        event_run_id = event_job.json()["id"]
        _wait_event(client, event_run_id)
        event_revision_id = event_run_id

        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-cancel",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert response.status_code == 202
        job_id = response.json()["run_id"]
        assert started.wait(2)
        cancelling = client.post(f"/api/jobs/{job_id}/cancel", json={})
        assert cancelling.status_code == 200
        assert cancelling.json()["state"] == "cancelling"
        release.set()
        job = _wait(client, job_id)
        detail = client.get(f"/api/jobs/{job_id}").json()
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{job_id}/result"
        )

    assert detail["state"] == "cancelled"
    assert job["state"]["status"] == "failed"
    assert result.status_code == 200
    assert result.json()["revisions"] == []


def test_visible_card_runs_queue_fairly_under_the_single_worker_budget(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    active = 0
    maximum = 0
    lock = threading.Lock()
    started_one = threading.Event()
    release = threading.Event()

    class BlockingDetector:
        name = "blocking-detector"
        version = "blocking-detector/v1"

        def propose(self, request: object) -> ProviderResult:
            nonlocal active, maximum
            del request
            with lock:
                active += 1
                maximum = max(maximum, active)
                started_one.set()
            try:
                assert release.wait(2)
                return ProviderResult(status="ok")
            finally:
                with lock:
                    active -= 1

    app = create_test_app(
        _settings(tmp_path, gemini_max_concurrent_requests=2),
        event_provider=_EventProvider(),
        visible_card_provider=BlockingDetector(),
        visible_card_frame_resolver=_FrameResolver(),
    )

    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "events-for-visible-queue"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        event_revision_id = event_run_id

        first_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-queue-first",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert first_response.status_code == 202
        first_run_id = first_response.json()["run_id"]
        assert started_one.wait(2)

        second_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-queue-second",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert second_response.status_code == 202
        second_run_id = second_response.json()["run_id"]

        second_status = client.get(f"/api/jobs/{second_run_id}").json()
        assert second_status["state"] == "queued"

        release.set()
        assert _wait(client, first_run_id)["state"]["status"] == "complete"
        assert _wait(client, second_run_id)["state"]["status"] == "complete"

    assert maximum == 1


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
        assert re.fullmatch(r"[a-f0-9]{64}", first.headers["x-dokodetector-source-sha256"])
        assert first.headers["x-dokodetector-frame-index"] == "4"
        assert first.headers["x-dokodetector-frame-width"] == "64"
        assert first.headers["x-dokodetector-frame-height"] == "64"
        assert first.headers["x-dokodetector-requested-time-us"] == "400000"
        assert first.headers["x-dokodetector-frame-time-us"] == "400000"

        previous = client.get(f"{path}?frame_index=3")
        assert previous.status_code == 200
        assert previous.headers["x-dokodetector-frame-index"] == "3"
        assert previous.headers["x-dokodetector-requested-time-us"] == "400000"
        assert previous.headers["x-dokodetector-frame-time-us"] == "300000"

        cache_root = tmp_path / "runtime" / "pipeline" / "derived-views"
        assert any(cache_root.rglob("*"))
        shutil.rmtree(cache_root)

        second = client.get(path)
        assert second.status_code == 200
        assert second.content == first.content
        assert second.headers["etag"] == first.headers["etag"]


def test_sampled_event_frame_route_reuses_one_250_ms_cache(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        visible_card_frame_resolver=_FrameResolver(),
    )

    first_path = (
        f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/exact-event/100000"
        "?preview=sampled_250ms"
    )
    second_path = (
        f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/exact-event/400000"
        "?preview=sampled_250ms"
    )
    with TestClient(app) as client:
        first = client.get(first_path)
        warm = client.get(first_path)
        second = client.get(second_path)

    assert first.status_code == 200
    assert warm.status_code == 200
    assert second.status_code == 200
    assert first.headers["x-dokodetector-frame-interval-us"] == "250000"
    assert first.headers["x-dokodetector-requested-time-us"] == "100000"
    assert first.headers["x-dokodetector-frame-time-us"] == "250000"
    assert first.headers["x-dokodetector-frame-width"] == "64"
    assert first.headers["x-dokodetector-frame-height"] == "64"
    assert warm.content == first.content
    assert (
        warm.headers["x-dokodetector-frame-time-us"]
        == first.headers["x-dokodetector-frame-time-us"]
    )
    assert second.headers["x-dokodetector-frame-time-us"] == "500000"
    cache_root = tmp_path / "runtime" / "pipeline" / "derived-views" / "sampled-frames"
    assert len(list(cache_root.rglob("manifest.json"))) == 1


def _wait_event(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    body: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{run_id}")
        job = response.json()
        status = job["state"]
        body = {
            "state": {
                "status": "complete" if status == "succeeded" else status,
                "output_revision_ids": [result["id"] for result in job["results"]],
            }
        }
        if status in {"succeeded", "failed", "cancelled", "interrupted"}:
            return body
        time.sleep(0.01)
    return body
