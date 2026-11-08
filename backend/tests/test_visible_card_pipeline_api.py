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
    CARD_STATE_CHANGED_EVENT_TYPE,
    DataRevision,
    EventData,
    EventDataRevision,
    EventRecord,
    HumanProducer,
    RecordingVideoSource,
    RunItemOutcome,
    RunProgress,
    canonical_event_data_bytes,
    sha256_bytes,
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
    return result["state"]["output_revision_ids"][0]


def _selected_node_input(
    client: TestClient, content_type: str, revision_id: str | None = None
) -> dict[str, object]:
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
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]
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


def test_visible_card_run_accepts_exact_node_event_revision_without_legacy_input(
    tmp_path: Path, monkeypatch
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "native-source-events"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        legacy_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]
        legacy = app.state.pipeline_selection_store.require_processor_revision(legacy_id)
        nodes = app.state.visible_card_pipeline_service.node_store
        node = nodes.create(
            "native-event-node",
            "Node events",
            "events",
            legacy.manifest.source.to_mapping(),
            legacy.content.to_mapping(),
            {},
            revision_id="native-event-revision",
        )
        historical_id = node.revision_id
        edited_events = legacy.content.to_mapping()
        edited_events["events"][0]["end_us"] += 1
        nodes.save(
            node.node_id,
            nodes.get(node.node_id).head_revision_id,
            edited_events,
            {"edit": "historical fixture"},
        )
        current = nodes.get(node.node_id)
        workspace = client.get(f"/api/recordings/{RECORDING_ID}/pipeline?stage=events").json()
        option = next(
            item
            for item in workspace["stages"][0]["input_options"]
            if item["node_id"] == node.node_id and item["node_revision_id"] == historical_id
        )
        assert option["node_revision_id"] == historical_id
        assert option["is_current_head"] is False

        native_revision_id = historical_id
        assert not hasattr(app.state, "pipeline_revision_store")
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-node-historical",
                "input_node_ref": {
                    "node_id": node.node_id,
                    "revision_id": native_revision_id,
                    "revision_policy": "historical",
                },
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert _wait(client, run_id)["state"]["status"] == "complete"

        service = app.state.visible_card_pipeline_service
        job = app.state.job_manager_service.get_manager().get(run_id)
        job_envelope = {"context": job.context, "request": job.request}
        assert service.verify_job(run_id, job_envelope)
        accepted_use_path = service._job_use_path(run_id)
        accepted_use = _read_json(accepted_use_path)
        accepted_use["event_node_ref"]["node_id"] = "different-node"
        accepted_use_path.write_text(_json(accepted_use), encoding="utf-8")
        assert not service.verify_job(run_id, job_envelope)

        accepted = _read_json(nodes.root / ".accepted-uses" / f"{run_id}.json")
        assert accepted["inputs"] == [{"node_id": node.node_id, "revision_id": native_revision_id}]
        lineage_path = nodes.root / ".lineage-runs" / f"{run_id}.json"
        for _ in range(100):
            if lineage_path.is_file():
                break
            time.sleep(0.01)
        lineage = _read_json(lineage_path)
        assert lineage["inputs"] == [
            {
                "kind": "revision",
                "node_id": node.node_id,
                "revision_id": native_revision_id,
                "role": "events",
            }
        ]
        assert lineage["context"]["request"]["input_node_ref"] == {
            "node_id": node.node_id,
            "revision_id": native_revision_id,
            "revision_policy": "historical",
        }
        assert native_revision_id != legacy_id
        assert current.head_revision_id != native_revision_id

        current_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-node-current-head",
                "input_node_ref": {
                    "node_id": node.node_id,
                    "revision_id": current.head_revision_id,
                    "revision_policy": "current_head",
                },
            },
        )
        assert current_response.status_code == 202
        current_run_id = current_response.json()["run_id"]
        assert _wait(client, current_run_id)["state"]["status"] == "complete"
        current_lineage_path = nodes.root / ".lineage-runs" / f"{current_run_id}.json"
        for _ in range(100):
            if current_lineage_path.is_file():
                break
            time.sleep(0.01)
        current_lineage = _read_json(current_lineage_path)
        assert current_lineage["inputs"][0]["node_id"] == node.node_id
        assert current_lineage["inputs"][0]["revision_id"] == current.head_revision_id
        assert current_lineage["inputs"][0]["role"] == "events"
        assert current_lineage["context"]["request"]["input_node_ref"]["revision_policy"] == (
            "current_head"
        )

        conflicting_input = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-node-conflicting-input",
                "event_revision_id": legacy_id,
                "input_node_ref": {
                    "node_id": node.node_id,
                    "revision_id": current.head_revision_id,
                    "revision_policy": "current_head",
                },
            },
        )
        assert conflicting_input.status_code == 422


def test_migrated_event_draft_is_selectable_as_exact_visible_card_input(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "events-for-migrated-draft"})
        assert event_response.status_code == 202
        event_run_id = event_response.json()["id"]
        _wait_event(client, event_run_id)
        legacy_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]
        legacy = app.state.pipeline_selection_store.require_processor_revision(legacy_id)
        nodes = app.state.visible_card_pipeline_service.node_store
        draft_node = nodes.create(
            "migrated-event-draft",
            "Imported event draft",
            "events",
            legacy.manifest.source.to_mapping(),
            legacy.content.to_mapping(),
            {"migration": {"legacy_key": "fixture/event-draft"}},
            revision_id="migrated-event-draft-revision",
        )

        workspace = client.get(f"/api/recordings/{RECORDING_ID}/pipeline?stage=events")
        assert workspace.status_code == 200
        option = next(
            item
            for item in workspace.json()["stages"][0]["input_options"]
            if item["node_id"] == draft_node.node_id
            and item["node_revision_id"] == draft_node.revision_id
        )
        assert option["node_revision_id"] == draft_node.revision_id
        assert option["display_label"] == "Imported draft events"

        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-from-migrated-event-draft",
                "input_node_ref": {
                    "node_id": draft_node.node_id,
                    "revision_id": draft_node.revision_id,
                    "revision_policy": "current_head",
                },
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert _wait(client, run_id)["state"]["status"] == "complete"

        lineage = _read_json(nodes.root / ".lineage-runs" / f"{run_id}.json")
        assert lineage["inputs"] == [
            {
                "kind": "revision",
                "node_id": draft_node.node_id,
                "revision_id": draft_node.revision_id,
                "role": "events",
            }
        ]


def test_visible_card_node_request_rejects_invalid_node_type_and_policy(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "invalid-node-events"})
        _wait_event(client, event_response.json()["id"])
        event_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_response.json()['id']}/result"
        ).json()["state"]["output_revision_ids"][0]
        legacy = app.state.pipeline_selection_store.require_processor_revision(event_id)
        nodes = app.state.visible_card_pipeline_service.node_store
        wrong_type = nodes.create(
            "wrong-event-type",
            "Wrong type",
            "visible_cards",
            legacy.manifest.source.to_mapping(),
            {"schema_version": "visible-card-data/v2", "outcomes": []},
            {},
        )
        other_source = dict(legacy.manifest.source.to_mapping())
        other_source["video_sha256"] = "f" * 64
        wrong_source = nodes.create(
            "wrong-event-source",
            "Wrong source",
            "events",
            other_source,
            legacy.content.to_mapping(),
            {},
        )
        cases = (
            {
                "node_id": wrong_type.node_id,
                "revision_id": nodes.get(wrong_type.node_id).head_revision_id,
                "revision_policy": "current_head",
            },
            {
                "node_id": wrong_type.node_id,
                "revision_id": "missing-revision",
                "revision_policy": "historical",
            },
            {
                "node_id": wrong_source.node_id,
                "revision_id": wrong_source.revision_id,
                "revision_policy": "current_head",
            },
            {
                "node_id": wrong_source.node_id,
                "revision_id": wrong_source.revision_id,
                "revision_policy": "historical",
            },
            {
                "node_id": wrong_type.node_id,
                "revision_id": nodes.get(wrong_type.node_id).head_revision_id,
                "revision_policy": "guess",
            },
        )
        for index, node_ref in enumerate(cases):
            response = client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
                json={
                    "run_id": f"visible-invalid-node-{index}",
                    "input_node_ref": node_ref,
                },
            )
            assert response.status_code == 422


def test_visible_card_current_head_edit_copy_and_retry_keep_exact_node_revision(
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
        service = app.state.visible_card_pipeline_service
        nodes = service.node_store
        _, source = service._accepted_source(RECORDING_ID)
        input_content = EventData(
            events=(
                EventRecord(
                    event_id="node-event-1",
                    event_type=CARD_STATE_CHANGED_EVENT_TYPE,
                    start_us=100_000,
                    end_us=200_000,
                ),
            )
        )
        node = nodes.create(
            "retry-event-node",
            "Retry events",
            "events",
            source.to_mapping(),
            input_content.to_mapping(),
            {},
            revision_id="retry-event-revision-1",
        )
        accepted_pair = (node.node_id, node.revision_id)

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
            json={
                "run_id": "visible-current-head-retry",
                "input_node_ref": {
                    "node_id": accepted_pair[0],
                    "revision_id": accepted_pair[1],
                    "revision_policy": "current_head",
                },
            },
        )
        assert response.status_code == 202
        failed_run_id = response.json()["run_id"]
        assert publish_reached.wait(5), "visible-card fixture did not reach publication"

        edited_content = input_content.to_mapping()
        edited_content["events"][0]["end_us"] += 1
        edit_response = client.post(
            f"/api/pipeline/nodes/{accepted_pair[0]}/edit",
            json={
                "expected_revision_id": accepted_pair[1],
                "idempotency_key": "retry-event-edit-1",
                "actor": {"kind": "human", "id": "workspace-operator"},
                "content": edited_content,
            },
        )
        assert edit_response.status_code == 200
        copied = edit_response.json()
        assert copied["copied"] is True
        assert copied["node_id"] != accepted_pair[0]
        assert nodes.get(accepted_pair[0]).head_revision_id == accepted_pair[1]

        release_failure.set()
        failed_terminal = _wait_for_terminal_job(terminal_jobs, failed_run_id)
        assert failed_terminal == "failed"
        assert client.get(f"/api/jobs/{failed_run_id}").json()["state"] == "failed"
        initial_run = app.state.pipeline_run_store.require(failed_run_id)
        assert initial_run.request.input_node_ref == {
            "node_id": accepted_pair[0],
            "revision_id": accepted_pair[1],
            "revision_policy": "current_head",
        }

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
        assert retried_run.request.input_node_ref == initial_run.request.input_node_ref
        assert retried_run.request.input_revision_ids == (accepted_pair[1],)

        for run_id in (failed_run_id, retry_run_id):
            accepted_use = _read_json(nodes.root / ".accepted-uses" / f"{run_id}.json")
            assert accepted_use["inputs"] == [
                {"node_id": accepted_pair[0], "revision_id": accepted_pair[1]}
            ]
            lineage = _read_json(nodes.root / ".lineage-runs" / f"{run_id}.json")
            assert lineage["inputs"] == [
                {
                    "kind": "revision",
                    "node_id": accepted_pair[0],
                    "revision_id": accepted_pair[1],
                    "role": "events",
                }
            ]

        stale_node = nodes.create(
            "stale-current-head-node",
            "Stale current head",
            "events",
            source.to_mapping(),
            input_content.to_mapping(),
            {},
            revision_id="stale-event-revision-1",
        )
        stale_pair = (stale_node.node_id, stale_node.revision_id)
        stale_request = {
            "run_id": "visible-stale-current-head",
            "input_revision_ids": [stale_pair[1]],
            "input_node_ref": {
                "node_id": stale_pair[0],
                "revision_id": stale_pair[1],
                "revision_policy": "current_head",
            },
        }
        stale_edit = input_content.to_mapping()
        stale_edit["events"][0]["end_us"] += 2
        changed_head = client.post(
            f"/api/pipeline/nodes/{stale_pair[0]}/edit",
            json={
                "expected_revision_id": stale_pair[1],
                "idempotency_key": "stale-event-edit-1",
                "actor": {"kind": "human", "id": "workspace-operator"},
                "content": stale_edit,
            },
        )
        assert changed_head.status_code == 200
        assert changed_head.json()["node_id"] == stale_pair[0]
        assert nodes.get(stale_pair[0]).head_revision_id != stale_pair[1]

        accepted_job_ids = {job.id for job in manager.list_jobs()}
        rejected = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json=stale_request,
        )
        assert rejected.status_code == 422
        assert {job.id for job in manager.list_jobs()} == accepted_job_ids


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
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]
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


def _manual_event_revision(
    app,
    source,
    base: EventDataRevision,
    *,
    event_types: tuple[str, ...] | None = None,
    start_offset_us: int = 0,
) -> str:
    if event_types is not None:
        assert len(event_types) == len(base.content.events)
    content = EventData(
        events=tuple(
            EventRecord(
                event_id=event.event_id,
                event_type=(event.event_type if event_types is None else event_types[index]),
                start_us=max(0, event.start_us - start_offset_us),
                end_us=event.end_us,
            )
            for index, event in enumerate(base.content.events)
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
    stored, _ = app.state.pipeline_selection_store.publish_processor_revision(
        revision.manifest, revision.content
    )
    current = app.state.pipeline_selection_store.get_exact(RECORDING_ID, "events")
    app.state.pipeline_selection_store.update_exact(
        RECORDING_ID,
        "events",
        expected_revision=0 if current is None else current.revision,
        selected_generated=app.state.pipeline_selection_store.reference_for_processor_output(
            base.manifest.revision_id, RECORDING_ID, "events"
        ),
        selected_completed_reference=app.state.pipeline_selection_store.reference_for_processor_output(
            stored.manifest.revision_id, RECORDING_ID, "events"
        ),
    )
    return stored.manifest.revision_id


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
        event_response = _enqueue_event(client, {"run_id": "events-selected-without-input"})
        _wait_event(client, event_response.json()["id"])
        event_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_response.json()['id']}/result"
        ).json()
        base_revision = app.state.pipeline_selection_store.require_processor_revision(
            event_result["state"]["output_revision_ids"][0]
        )
        selected_revision_id = _manual_event_revision(
            app,
            base_revision.manifest.source,
            base_revision,
        )

        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "visible-no-event-input"},
        )

    assert app.state.pipeline_selection_store.get_exact(RECORDING_ID, "events") is not None
    assert selected_revision_id == "events-manual-reference"
    assert response.status_code == 422
    assert "input_node_ref" in response.json()["error"]["message"]


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
        event_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()
        generated_event_revision_id = event_result["state"]["output_revision_ids"][0]
        generated_event_revision = app.state.pipeline_selection_store.require_processor_revision(
            generated_event_revision_id
        )

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
        assert generated_result["request"]["input_revision_ids"] == [generated_event_revision_id]
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
        generated_card_id = generated_content["outcomes"][0]["candidates"][0]["card_id"]
        assert generated_result["request"]["configuration"]["detector"] == {
            "name": "local-rfdetr-segmentation",
            "version": "local-rfdetr-segmentation-v1",
        }

        manual_revision_id = _manual_event_revision(
            app,
            generated_event_revision.manifest.source,
            generated_event_revision,
            event_types=(CARD_STATE_CHANGED_EVENT_TYPE,)
            * len(generated_event_revision.content.events),
            start_offset_us=1,
        )
        manual = app.state.pipeline_selection_store.require_processor_revision(manual_revision_id)
        manual_node = app.state.visible_card_pipeline_service.node_store.create(
            "manual-events-node",
            "Manual event draft",
            "events",
            manual.manifest.source.to_mapping(),
            manual.content.to_mapping(),
            {"fixture": "manual event draft"},
        )
        visible_reference = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-reference",
                "input_node_ref": {
                    "node_id": manual_node.node_id,
                    "revision_id": manual_node.revision_id,
                    "revision_policy": "current_head",
                },
                "configuration": {"threshold": 0.6},
                "extraction_policy": {
                    "policy_id": "exact-event/v1",
                    "output_encoding": "jpeg",
                    "event_time_anchor": "end_us",
                },
            },
        )
        assert visible_reference.status_code == 202
        reference_run_id = visible_reference.json()["run_id"]
        _wait(client, reference_run_id)
        reference_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{reference_run_id}/result"
        ).json()
        assert reference_result["request"]["input_revision_ids"] == [manual_node.revision_id]
        assert reference_result["request"]["extraction_policy"]["event_time_anchor"] == "end_us"
        reference_content = reference_result["revisions"][0]["content"]
        assert (
            reference_content["outcomes"][0]["frame_identity"]["requested_time_us"]
            == generated_event_revision.content.events[0].end_us
        )
        assert [outcome["status"] for outcome in reference_content["outcomes"]] == [
            "detected",
            "empty",
            "failed",
            "failed",
            "empty",
        ]
        assert [outcome["event_id"] for outcome in reference_content["outcomes"]] == [
            "event-000000",
            "event-000001",
            "event-000002",
            "event-000003",
            "event-000004",
        ]
        reference_card_id = reference_content["outcomes"][0]["candidates"][0]["card_id"]
        assert reference_card_id != generated_card_id
        selection = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/selection"
        ).json()
        for _ in range(100):
            if (
                selection["selection"]["selected_generated"]["revision_id"]
                == reference_result["state"]["output_revision_ids"][0]
            ):
                break
            time.sleep(0.01)
            selection = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/selection"
            ).json()
        assert (
            selection["selection"]["selected_generated"]["revision_id"]
            == reference_result["state"]["output_revision_ids"][0]
        )

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
        event_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()
        event_revision_id = event_result["state"]["output_revision_ids"][0]

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
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]

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
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]

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
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]

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
