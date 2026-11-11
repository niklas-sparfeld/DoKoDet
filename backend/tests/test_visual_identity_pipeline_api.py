from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

import pytest
from app_factory import create_test_app
from doko_operations.pipeline_data import (
    DataRevision,
    ProcessorProducer,
    sha256_bytes,
)
from fastapi.testclient import TestClient
from table_evidence_analyzer import (
    CardClassificationResult,
    PredictedVisibleRegionGeometry,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardOutcome,
    VisualIdentityRequest,
    canonical_visible_card_data_bytes,
)
from table_evidence_analyzer.table_observation import IdentityCandidate
from test_visible_card_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
    _FrameResolver,
    _install_recording,
    _run_event_job,
    _selected_node_input,
    _settings,
    _wait,
)

from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineError,
)


class _IdentityProvider:
    name = "fixture-identity"
    version = "fixture-identity/v1"
    model = "fixture-model/v1"

    def __init__(self) -> None:
        self.requests: list[VisualIdentityRequest] = []

    def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
        self.requests.append(request)
        if request.card_id.endswith("empty"):
            return CardClassificationResult(status="ok", classification="unknown")
        if request.card_id.endswith("failed"):
            return CardClassificationResult(status="unavailable", error="fixture failure")
        return CardClassificationResult(
            status="ok",
            candidates=(
                IdentityCandidate(card="CLUBS_NINE", probability=0.75),
                IdentityCandidate(card="SPADES_NINE", probability=0.25),
            ),
        )


class _LocalPpmIdentityClassifier:
    name = "local-dinov3"
    version = "dinov3-local-identity-test-v1"
    model = "facebook/dinov3-vits16-pretrain-lvd1689m"
    calibration = "uncalibrated"

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        raise AssertionError("the resolver test must not classify a crop")


def _fixture_generated_visible_revision(
    app: Any, source: Any, frame: dict[str, Any], producer_run_id: str
) -> str:
    frame_identity = VisibleCardFrameIdentity.from_mapping(frame)
    candidates = (
        VisibleCardCandidate(
            card_id="card-classified",
            geometry=PredictedVisibleRegionGeometry(
                polygons=(((100, 100), (900, 100), (900, 900), (100, 900)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="face_up",
        ),
        VisibleCardCandidate(
            card_id="card-empty",
            geometry=PredictedVisibleRegionGeometry(
                polygons=(((100, 100), (900, 100), (900, 900), (100, 900)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="unknown",
        ),
        VisibleCardCandidate(
            card_id="card-unusable",
            geometry=PredictedVisibleRegionGeometry(
                polygons=(((0, 0), (10, 0), (10, 10), (0, 10)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="face_down",
        ),
        VisibleCardCandidate(
            card_id="card-failed",
            geometry=PredictedVisibleRegionGeometry(
                polygons=(((100, 100), (900, 100), (900, 900), (100, 900)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="unknown",
        ),
    )
    content = VisibleCardData(
        outcomes=(
            VisibleCardOutcome(
                event_id="event-000000",
                frame_identity=frame_identity,
                status="detected",
                candidates=candidates,
            ),
        )
    )
    revision_id = "visible-cards-completed-reference"
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=RECORDING_ID,
        source=source,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id=producer_run_id,
            processor_type="visible-card-detection",
            implementation_id="visible-card-detector-adapter.v1",
        ),
        coverage={"kind": "completed-reference", "card_ids": [item.card_id for item in candidates]},
        created_at="2026-01-01T00:00:00Z",
    )
    stored, _ = app.state.pipeline_lineage_writer.publish_processor_revision(manifest, content)
    return stored.manifest.revision_id


def _node_input(app: Any, revision_id: str) -> dict[str, object]:
    nodes = app.state.visual_identity_pipeline_service.node_store
    node, _ = nodes.find_revision(revision_id)
    return {
        "input_node_ref": {
            "node_id": node.node_id,
            "revision_id": revision_id,
            "revision_policy": "current_head"
            if node.head_revision_id == revision_id
            else "historical",
        }
    }


def _wait_identity(client: TestClient, run_id: str) -> dict[str, Any]:

    deadline = time.monotonic() + 5
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        job_response = client.get(f"/api/jobs/{run_id}")
        if job_response.status_code == 200:
            job = job_response.json()
            if job["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                response = client.get(
                    f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{run_id}/result"
                )
                if response.status_code == 200:
                    body = response.json()
                else:
                    body = {"state": {"progress": {"completed": 0, "total": 0}, "items": []}}
                status = "complete" if job["state"] == "succeeded" else job["state"]
                body.setdefault("state", {})["status"] = status
                body["state"].setdefault("progress", {"completed": 0, "total": 0})
                body["state"].setdefault("items", [])
                return body
        time.sleep(0.01)
    return body


def test_local_pipeline_requests_record_actual_bundle_and_crop(tmp_path: Any) -> None:
    _install_recording(tmp_path)
    detector = _Detector()
    detector.name = "local-rfdetr-segmentation"
    detector.bundle_identity = {"bundle_digest": "a" * 64}
    detector.device = "cpu"
    identity = _IdentityProvider()
    identity.name = "local-dinov3"
    identity.bundle_identity = {"bundle_digest": "b" * 64}
    identity.device = "cpu"
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=detector,
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=identity,
    )
    with TestClient(app) as client:
        assert _run_event_job(client, "events-local")
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "cards-local",
                **_selected_node_input(client, "events"),
                "configuration": {"provider": detector.name},
            },
        )
        assert response.status_code == 202, response.text
        assert (
            response.json()["request"]["configuration"]["bundle_identity"]
            == detector.bundle_identity
        )
        assert response.json()["request"]["configuration"]["device"] == "cpu"
        visible_run_id = response.json()["run_id"]
        _wait(client, visible_run_id)
        revision = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-local",
                **_selected_node_input(client, "visible_cards", revision),
                "configuration": {"provider": "local"},
                "crop_policy": {"policy_id": "predicted_visible_region", "output_encoding": "ppm"},
            },
        )
        assert response.status_code == 202, response.text
        saved = response.json()["request"]
        assert saved["configuration"]["provider"] == identity.name
        assert saved["configuration"]["bundle_identity"] == identity.bundle_identity
        assert saved["configuration"]["device"] == "cpu"
        assert saved["crop_policy"]["policy_id"] == "predicted_visible_region"
        identity_run_id = response.json()["run_id"]
        assert _wait_identity(client, identity_run_id)["state"]["status"] == "complete"
        request = app.state.visual_identity_pipeline_service.run_store.require(
            identity_run_id
        ).request
        identity.device = "mps"
        with pytest.raises(VisualIdentityPipelineError, match="device changed"):
            app.state.visual_identity_pipeline_service._classifier_for_request(request)


def test_identity_run_uses_exact_detection_set_without_node_input(tmp_path: Any) -> None:
    _install_recording(tmp_path)
    detector = _Detector()
    identity = _IdentityProvider()
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=detector,
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=identity,
    )
    with TestClient(app) as client:
        _run_event_job(client, "events-for-exact-detections")
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "cards-for-exact-identity",
                **_selected_node_input(client, "events"),
                "configuration": {"provider": detector.name},
            },
        )
        assert visible_response.status_code == 202, visible_response.text
        _wait(client, visible_response.json()["run_id"])
        visible = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/"
            f"{visible_response.json()['run_id']}/result"
        ).json()
        reference = visible["detection_set_ref"]
        stale_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-from-stale-detections",
                "input_detection_set_ref": {**reference, "content_sha256": "f" * 64},
                "configuration": {"provider": identity.name},
            },
        )
        assert stale_response.status_code == 422
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-from-exact-detections",
                "input_detection_set_ref": reference,
                "configuration": {"provider": identity.name},
            },
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        assert _wait_identity(client, run_id)["state"]["status"] == "complete"
        run = app.state.visual_identity_pipeline_service.run_store.require(run_id)
        assert run.request.input_detection_set_ref == reference
        assert run.request.input_revision_ids == ()
        revision = app.state.pipeline_lineage_writer.require_revision(
            run.state.output_revision_ids[0]
        )
        assert revision.manifest.coverage["detection_set_ref"] == reference
        lineage_run = next(
            item
            for item in app.state.pipeline_lineage_writer.lineage.snapshot(RECORDING_ID)["runs"]
            if item["run_id"] == run_id
        )
        assert lineage_run["inputs"][0]["artifact_id"] == (
            f"detection-set/{reference['set_id']}/versions/{reference['version']}"
        )
        original = app.state.detection_set_store.get(
            RECORDING_ID, reference["set_id"], reference["version"]
        )
        edited_frames = deepcopy(original["content"]["frames"])
        edited_frames[0]["detections"][0]["segments"][0]["polygon"][0]["x"] += 1
        app.state.detection_set_store.save(
            RECORDING_ID,
            set_id=reference["set_id"],
            version="2",
            origin="corrected",
            source=original["source"],
            producer={"tool": "edit-after-classification"},
            event_sets=original["event_sets"],
            frames=edited_frames,
        )
        restarted = create_test_app(
            _settings(tmp_path),
            event_provider=_EventProvider(),
            visible_card_provider=detector,
            visible_card_frame_resolver=_FrameResolver(),
            visible_card_identity_classifier=identity,
        )
        reopened = restarted.state.visual_identity_pipeline_service.run_store.require(run_id)
        assert reopened.request.input_detection_set_ref == reference
        reopened_revision = restarted.state.pipeline_lineage_writer.require_revision(
            reopened.state.output_revision_ids[0]
        )
        assert reopened_revision.manifest.coverage["detection_set_ref"] == reference
        assert (
            restarted.state.detection_set_store.get(
                RECORDING_ID, reference["set_id"], reference["version"]
            )
            == original
        )
