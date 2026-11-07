from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app_factory import create_test_app
from fastapi.testclient import TestClient
from test_round_analysis_api import (
    ANALYSIS_ID,
    _analysis_payload,
    _upload_linked_package,
)
from test_round_analysis_api import (
    RECORDING_ID as ROUND_RECORDING_ID,
)
from test_round_analysis_api import (
    _backend as _round_backend,
)
from test_visible_card_pipeline_api import (
    _install_recording,
    _run_event_job,
    _settings,
    _wait,
)
from test_visual_identity_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
    _fixture_generated_visible_revision,
    _FrameResolver,
    _IdentityProvider,
    _selected_node_input,
    _wait_identity,
)

SAMPLES: list[dict[str, Any]] = []


def _sample(client: TestClient, name: str, url: str, *, headers: dict[str, str] | None = None):
    started = time.perf_counter_ns()
    response = client.get(url, headers=headers)
    elapsed = time.perf_counter_ns() - started
    assert response.status_code in {200, 206}, (name, response.status_code, response.text[:200])
    assert response.content, name
    return {
        "case": name,
        "method": "GET",
        "path": url,
        "status": response.status_code,
        "elapsed_ns": elapsed,
        "response_bytes": len(response.content),
        "response_sha256": hashlib.sha256(response.content).hexdigest(),
        "etag": response.headers.get("etag"),
        "content_type": response.headers.get("content-type"),
    }, response


def _retain(samples: list[dict[str, Any]]) -> None:
    SAMPLES.extend(samples)


def test_registered_catalog_media_routes_have_named_real_backend_cases(
    tmp_path: Any, monkeypatch: Any
) -> None:
    client, app = _round_backend(tmp_path)
    package_id = _upload_linked_package(client, fixture_name="example-complete")
    created = client.post("/v1/round-analyses", json=_analysis_payload(package_ids=[package_id]))
    assert created.status_code == 202, created.text
    assert created.json()["state"] == "complete"
    prefix = f"/v1/round-analyses/{ANALYSIS_ID}/evidence-packages/{package_id}/frames"

    samples = []
    samples.append(_sample(client, "evidence_frame", f"{prefix}/frame_03")[0])
    samples.append(
        _sample(
            client, "evidence_video_snippet", f"/v1/evidence-packages/{package_id}/video-snippet"
        )[0]
    )
    samples.append(
        _sample(
            client, "recording_video_full", f"/v1/repository-bundles/{ROUND_RECORDING_ID}/video"
        )[0]
    )
    ranged, range_response = _sample(
        client,
        "recording_video_range_64k",
        f"/v1/repository-bundles/{ROUND_RECORDING_ID}/video",
        headers={"Range": "bytes=0-65535"},
    )
    assert range_response.status_code == 206
    assert len(range_response.content) <= 65_536
    samples.append(ranged)
    render_calls = 0

    def render_first_frame(_path: Any, *, timeout_seconds: float) -> bytes:
        nonlocal render_calls
        render_calls += 1
        assert timeout_seconds > 0
        return b"\xff\xd8\xffm9-thumbnail"

    monkeypatch.setattr(
        "dokodetector_backend.recording_thumbnail._render_first_frame", render_first_frame
    )
    cold, cold_response = _sample(
        client, "recording_thumbnail_cold", f"/v1/repository-bundles/{ROUND_RECORDING_ID}/thumbnail"
    )
    warm, warm_response = _sample(
        client, "recording_thumbnail_warm", f"/v1/repository-bundles/{ROUND_RECORDING_ID}/thumbnail"
    )
    assert cold_response.content == warm_response.content
    assert cold_response.headers.get("etag") == warm_response.headers.get("etag")
    assert render_calls == 1
    samples.extend((cold, warm))

    boundary = client.get("/api/recordings/unregistered-m9/video")
    assert boundary.status_code == 404
    assert {item["case"] for item in samples} == {
        "evidence_frame",
        "evidence_video_snippet",
        "recording_video_full",
        "recording_video_range_64k",
        "recording_thumbnail_cold",
        "recording_thumbnail_warm",
    }
    assert app.state.round_analysis_store.get(ANALYSIS_ID) is not None
    _retain(samples)


def test_derived_media_cache_cold_warm_revision_and_restart(tmp_path: Any) -> None:
    _install_recording(tmp_path)
    provider = _IdentityProvider()
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=provider,
    )
    with TestClient(app) as client:
        _run_event_job(client, "m9-events")
        client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/m9-events/result")
        visible = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "m9-visible", **_selected_node_input(client, "events")},
        )
        assert visible.status_code == 202, visible.text
        visible_run = visible.json()["run_id"]
        assert _wait(client, visible_run)["state"]["status"] == "complete"
        visible_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run}/result"
        ).json()
        visible_revision = visible_result["state"]["output_revision_ids"][0]
        visible_source = app.state.pipeline_selection_store.require_processor_revision(
            visible_revision
        ).manifest.source
        generated_revision = _fixture_generated_visible_revision(
            app,
            visible_source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
            visible_run,
        )
        identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "m9-identity",
                **_selected_node_input(client, "visible_cards", generated_revision),
            },
        )
        assert identity.status_code == 202, identity.text
        identity_run = identity.json()["run_id"]
        assert _wait_identity(client, identity_run)["state"]["status"] == "complete"
        identity_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{identity_run}/result"
        ).json()
        identity_revision = identity_result["state"]["output_revision_ids"][0]
        outcome = identity_result["revisions"][0]["content"]["outcomes"][0]
        crop_url = (
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{identity_revision}/{outcome['card_id']}?preview=browser"
        )
        frame_url = f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/exact-event/0"
        frame_cold, frame_first = _sample(client, "derived_event_frame_cold", frame_url)
        frame_warm, frame_second = _sample(client, "derived_event_frame_warm", frame_url)
        assert frame_first.content == frame_second.content
        assert frame_first.headers.get("etag") == frame_second.headers.get("etag")
        crop_cold, crop_first = _sample(client, "identity_crop_cold", crop_url)
        crop_warm, crop_second = _sample(client, "identity_crop_warm", crop_url)
        assert crop_first.content == crop_second.content
        assert crop_first.headers.get("etag") == crop_second.headers.get("etag")
        assert crop_cold["response_sha256"] == crop_warm["response_sha256"]

        # A new immutable revision must select its own crop identity, not the previous cache entry.
        saved = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "m9-identity-revision",
                **_selected_node_input(client, "visible_cards", generated_revision),
            },
        )
        assert saved.status_code == 202, saved.text
        saved_run = saved.json()["run_id"]
        assert _wait_identity(client, saved_run)["state"]["status"] == "complete"
        changed = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{saved_run}/result"
        ).json()
        changed_revision = changed["state"]["output_revision_ids"][0]
        changed_outcome = changed["revisions"][0]["content"]["outcomes"][0]
        changed_url = (
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{changed_revision}/{changed_outcome['card_id']}?preview=browser"
        )
        revision_sample, revision_response = _sample(
            client, "identity_crop_new_revision", changed_url
        )
        assert revision_response.status_code == 200
        assert changed_revision != identity_revision

        node_id = app.state.visual_identity_pipeline_service.node_store.find_revision(
            changed_revision
        )[0].node_id
        review_saved = client.post(
            f"/api/pipeline/nodes/{node_id}/reviews/item",
            json={
                "review_id": "m9-media-review-save",
                "revision_id": changed_revision,
                "item_id": changed_outcome["card_id"],
                "question": "Is this saved crop usable for identity review?",
                "decision": "accepted",
                "reviewer": {"kind": "human", "id": "m9-test"},
                "evidence": {
                    "policy": "m9-media-cache/v1",
                    "source": "deterministic fixture crop response",
                },
            },
        )
        assert review_saved.status_code == 200, review_saved.text
        after_save, save_response = _sample(client, "identity_crop_after_review_save", changed_url)
        assert save_response.content == revision_response.content

    restarted = create_test_app(
        _settings(tmp_path),
        visible_card_identity_classifier=_IdentityProvider(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(restarted) as client:
        after_restart, restart_response = _sample(
            client, "identity_crop_after_restart", changed_url
        )
        assert restart_response.status_code == 200
        assert after_restart["response_sha256"] == revision_sample["response_sha256"]
        assert frame_cold["response_sha256"] == frame_warm["response_sha256"]
        _retain(
            [
                frame_cold,
                frame_warm,
                crop_cold,
                crop_warm,
                revision_sample,
                after_save,
                after_restart,
            ]
        )


def test_media_case_names_reconcile_with_inventory() -> None:
    inventory_path = (
        Path(__file__).parents[2] / "docs/reports/0114-M0_Interactive_UI_Performance_Inventory.json"
    )
    inventory = json.loads(inventory_path.read_text())
    ui_routes = {
        row["route"]
        for row in inventory["operations"]
        if row["method"] == "GET"
        and row["classification"] == "ui"
        and any(
            token in row["route"]
            for token in ("/video", "thumbnail", "/frames/", "derived-views/", "video-snippet")
        )
    }
    covered = {
        "/v1/round-analyses/{analysis_id}/evidence-packages/{package_id}/frames/{part_name}",
        "/v1/evidence-packages/{package_id}/video-snippet",
        "/v1/repository-bundles/{recording_id}/video",
        "/v1/repository-bundles/{recording_id}/thumbnail",
        "/api/recordings/{recording_id}/pipeline/derived-views/exact-event/{requested_time_us}",
        "/api/recordings/{recording_id}/pipeline/derived-views/identity-crops/{revision_id}/{item_id}",
    }
    unregistered_boundary = {"/api/recordings/{recording_id}/video"}
    assert ui_routes == covered | unregistered_boundary
