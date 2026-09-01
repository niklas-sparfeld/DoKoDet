from __future__ import annotations

import json
from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.repository import upgrade_database

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


def fixture_parts() -> tuple[str, list[tuple[str, tuple[str, bytes, str]]]]:
    manifest = (FIXTURE_ROOT / "manifest.json").read_bytes()
    source = (FIXTURE_ROOT / "source-record.json").read_bytes()
    enrollment = (FIXTURE_ROOT / "initial-task-enrollment.json").read_bytes()
    proposal_path = next((FIXTURE_ROOT / "predictions").glob("*.json"))
    video_path = FIXTURE_ROOT / "videos" / "video-both.mov"
    recording_id = json.loads(manifest)["recording_id"]
    return recording_id, [
        ("manifest", ("manifest.json", manifest, "application/json")),
        ("source_record", ("source-record.json", source, "application/json")),
        ("task_enrollment", ("initial-task-enrollment.json", enrollment, "application/json")),
        ("video", (video_path.name, video_path.read_bytes(), "video/quicktime")),
        ("proposal", (proposal_path.name, proposal_path.read_bytes(), "application/json")),
    ]


def test_preview_apply_and_detail_projection_use_immutable_split_versions(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )
    app = create_test_app(settings)
    client = TestClient(app)
    recording_id, parts = fixture_parts()
    assert client.put(f"/v1/repository-bundles/{recording_id}", files=parts).status_code == 201
    bundle_path = app.state.repository_bundle_storage.bundle_path(recording_id)
    immutable_bundle_bytes = {
        path.relative_to(bundle_path): path.read_bytes()
        for path in bundle_path.rglob("*")
        if path.is_file()
    }

    initial_detail = client.get(f"/v1/recordings/{recording_id}").json()
    review = client.get(f"/v1/recordings/{recording_id}/card-event-review").json()
    saved = client.put(
        f"/v1/recordings/{recording_id}/card-event-review/draft",
        json={
            "annotation": review["annotation"],
            "proposals": [
                {"proposal_id": proposal["proposal_id"], "decision": "dismissed"}
                for proposal in review["proposals"]
            ],
            "expected_revision": review["draft_revision"],
            "full_video_acknowledged": True,
        },
    ).json()
    completed = client.post(
        f"/v1/recordings/{recording_id}/card-event-review/complete",
        json={
            "reviewer": "operator",
            "expected_revision": saved["draft_revision"],
            "full_video_acknowledged": True,
        },
    )
    assert completed.status_code == 200

    detail = client.get(f"/v1/recordings/{recording_id}").json()
    assert detail["training_use"]["eligibility"] == "eligible"
    active_digest = detail["training_use"]["active_split_digest"]
    assert active_digest
    assert active_digest == initial_detail["training_use"]["active_split_digest"]
    assert detail["training_use"]["development_group_keys"]

    preview = client.post(
        "/v1/data/cardevent-development-split/preview",
        json={
            "recording_id": recording_id,
            "destination": "train",
            "expected_active_split_digest": active_digest,
        },
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["validation"] == {"valid": True, "blockers": []}
    assert [item["recording_id"] for item in preview_body["affected_recordings"]] == [
        recording_id
    ]

    applied = client.post(
        "/v1/data/cardevent-development-split/apply",
        json={
            "recording_id": recording_id,
            "destination": "train",
            "expected_active_split_digest": active_digest,
            "preview_digest": preview_body["preview_digest"],
            "operator": "operator",
        },
    )
    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["counts"]["train"] == 1
    assert applied_body["receipt_id"]
    first_split_version_path = (
        app.state.card_event_development_split_store.version_root
        / f"{applied_body['split_version_id']}.json"
    )
    first_split_version_bytes = first_split_version_path.read_bytes()

    updated_detail = client.get(f"/v1/recordings/{recording_id}").json()
    assert updated_detail["training_use"]["development_partition"] == "train"
    assert (
        updated_detail["training_use"]["active_split_digest"]
        == applied_body["split_version_digest"]
    )
    catalog = client.get("/v1/recordings").json()["recordings"][0]
    assert catalog["card_event_review_state"] == "completed"
    assert catalog["card_event_event_count"] == 0
    assert catalog["development_partition"] == "train"

    restore_preview = client.post(
        "/v1/data/cardevent-development-split/preview",
        json={
            "recording_id": recording_id,
            "destination": "unassigned",
            "expected_active_split_digest": applied_body["split_version_digest"],
        },
    )
    assert restore_preview.status_code == 200
    restore_preview_body = restore_preview.json()
    restored = client.post(
        "/v1/data/cardevent-development-split/apply",
        json={
            "recording_id": recording_id,
            "destination": "unassigned",
            "expected_active_split_digest": applied_body["split_version_digest"],
            "preview_digest": restore_preview_body["preview_digest"],
            "operator": "operator",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["counts"]["unassigned"] == 1
    assert first_split_version_path.read_bytes() == first_split_version_bytes
    assert {
        path.relative_to(bundle_path): path.read_bytes()
        for path in bundle_path.rglob("*")
        if path.is_file()
    } == immutable_bundle_bytes

    stale = client.post(
        "/v1/data/cardevent-development-split/preview",
        json={
            "recording_id": recording_id,
            "destination": "validation",
            "expected_active_split_digest": active_digest,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "development_split_conflict"
