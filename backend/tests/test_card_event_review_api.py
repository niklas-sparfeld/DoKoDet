from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from app_factory import create_test_app
from doko_operations.cardevent_review import (
    CardEventReviewConflict,
    CardEventReviewSource,
    CardEventReviewStore,
    CardEventReviewWriteError,
)
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


def _backend(tmp_path: Path) -> tuple[TestClient, Settings, Path]:
    intake_root = tmp_path / "data" / "intake" / "recordings"
    shutil.copytree(FIXTURE_ROOT, intake_root / "recording-both")
    settings = Settings(
        _env_file=None,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "data" / "operations",
        repository_intake_root=intake_root,
        evidence_package_intake_root=tmp_path / "data" / "intake" / "evidence-packages",
        pending_video_root=tmp_path / "data" / "incoming" / "videos",
    )
    return TestClient(create_test_app(settings)), settings, intake_root


def _annotation(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "cardevent-annotation/v2",
        "video": "video-both.mov",
        "events": events,
    }


def _file_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_new_review_reads_empty_annotation_and_bundled_proposals(tmp_path: Path) -> None:
    client, settings, intake_root = _backend(tmp_path)
    source_before = _file_digests(intake_root / "recording-both")

    response = client.get("/v1/recordings/recording-both/card-event-review")

    assert response.status_code == 200
    body = response.json()
    assert body["review_state"] == "not_started"
    assert body["draft_revision"] == 0
    assert body["annotation"] == _annotation([])
    assert len(body["proposals"]) == 1
    assert body["proposals"][0]["decision"] == "undecided"
    assert body["proposals"][0]["proposal_generator_run_id"] == "proposal-both"
    assert _file_digests(intake_root / "recording-both") == source_before
    assert not (
        settings.operations_root / "cardevent-reviews" / "recording-both" / "draft.json"
    ).exists()


def test_draft_transitions_survive_restart_and_reject_stale_or_foreign_updates(
    tmp_path: Path,
) -> None:
    client, settings, intake_root = _backend(tmp_path)
    source_before = _file_digests(intake_root / "recording-both")
    initial = client.get("/v1/recordings/recording-both/card-event-review").json()
    proposal = initial["proposals"][0]
    payload = {
        "annotation": _annotation([]),
        "proposals": [{"proposal_id": proposal["proposal_id"], "decision": "accepted"}],
        "expected_revision": 0,
    }

    saved = client.put("/v1/recordings/recording-both/card-event-review/draft", json=payload)
    assert saved.status_code == 200
    assert saved.json()["review_state"] == "draft"
    assert saved.json()["draft_revision"] == 1
    detail = client.get("/v1/recordings/recording-both")
    assert detail.status_code == 200
    assert detail.json()["card_event_review"] == {
        "state": "draft",
        "event_count": 1,
        "reviewed_at": None,
    }

    stale = dict(payload)
    stale["annotation"] = _annotation(
        [{"time_s": 1.2, "type": "card_played", "confidence": "confirmed"}]
    )
    assert (
        client.put("/v1/recordings/recording-both/card-event-review/draft", json=stale).status_code
        == 409
    )

    foreign = dict(payload)
    foreign["expected_revision"] = 1
    foreign["proposals"] = [{"proposal_id": "foreign-proposal", "decision": "accepted"}]
    rejected = client.put("/v1/recordings/recording-both/card-event-review/draft", json=foreign)
    assert rejected.status_code == 422
    assert (
        client.get("/v1/recordings/recording-both/card-event-review").json()["draft_revision"] == 1
    )

    restarted = TestClient(create_test_app(settings))
    persisted = restarted.get("/v1/recordings/recording-both/card-event-review")
    assert persisted.status_code == 200
    assert persisted.json()["annotation"]["events"] == [
        {"confidence": "confirmed", "time_s": 1.0, "type": "card_played"}
    ]
    assert _file_digests(intake_root / "recording-both") == source_before


@pytest.mark.parametrize(
    "annotation, message",
    [
        (_annotation([{"time_s": 1.0, "type": "unknown"}]), "Unknown CardEvent event type"),
        (
            _annotation(
                [
                    {"time_s": 1.0, "type": "card_played"},
                    {"time_s": 1.005, "type": "card_played"},
                ]
            ),
            "more than 10 ms",
        ),
    ],
)
def test_invalid_annotation_fails_without_creating_or_changing_draft(
    tmp_path: Path, annotation: dict[str, object], message: str
) -> None:
    client, settings, _ = _backend(tmp_path)
    initial = client.get("/v1/recordings/recording-both/card-event-review").json()
    payload = {
        "annotation": annotation,
        "proposals": [
            {"proposal_id": initial["proposals"][0]["proposal_id"], "decision": "undecided"}
        ],
        "expected_revision": 0,
    }

    response = client.put("/v1/recordings/recording-both/card-event-review/draft", json=payload)

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]
    assert not (
        settings.operations_root / "cardevent-reviews" / "recording-both" / "draft.json"
    ).exists()


def test_completion_writes_immutable_digests_and_revision_preserves_parent_lineage(
    tmp_path: Path,
) -> None:
    client, settings, _ = _backend(tmp_path)
    initial = client.get("/v1/recordings/recording-both/card-event-review").json()
    proposal_id = initial["proposals"][0]["proposal_id"]
    incomplete = client.post(
        "/v1/recordings/recording-both/card-event-review/complete",
        json={
            "reviewer": "operator",
            "expected_revision": 0,
            "full_video_acknowledged": True,
        },
    )
    assert incomplete.status_code == 422
    saved = client.put(
        "/v1/recordings/recording-both/card-event-review/draft",
        json={
            "annotation": _annotation(
                [{"time_s": 1.0, "type": "card_played", "confidence": "confirmed"}]
            ),
            "proposals": [{"proposal_id": proposal_id, "decision": "dismissed"}],
            "expected_revision": 0,
        },
    ).json()

    missing_ack = client.post(
        "/v1/recordings/recording-both/card-event-review/complete",
        json={
            "reviewer": "operator",
            "expected_revision": saved["draft_revision"],
            "full_video_acknowledged": False,
        },
    )
    assert missing_ack.status_code == 422

    completed = client.post(
        "/v1/recordings/recording-both/card-event-review/complete",
        json={
            "reviewer": "operator",
            "expected_revision": saved["draft_revision"],
            "full_video_acknowledged": True,
        },
    )
    assert completed.status_code == 200
    body = completed.json()
    assert body["review_state"] == "completed"
    assert body["reviewer"] == "operator"
    assert body["completed_version_id"]
    assert body["completed_version_digest"]
    assert body["completion_receipt_id"]
    detail = client.get("/v1/recordings/recording-both")
    assert detail.status_code == 200
    assert detail.json()["card_event_review"] == {
        "state": "completed",
        "event_count": 1,
        "reviewed_at": body["completed_at"],
    }
    assert detail.json()["training_use"]["eligibility"] == "eligible"
    assert detail.json()["training_use"]["blocker"] is None
    assert detail.json()["next_action"] == "Assign a development partition"

    review_root = settings.operations_root / "cardevent-reviews" / "recording-both"
    version_path = review_root / "versions" / f"{body['completed_version_id']}.json"
    receipt_path = review_root / "receipts" / f"{body['completion_receipt_id']}.json"
    version = json.loads(version_path.read_text(encoding="utf-8"))
    version_before = version_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert version["input_draft_digest"] == saved["draft_digest"]
    assert version["source_digest"] == body["source_sha256"]
    assert version["reviewed_annotation_digest"] == body["reviewed_annotation_digest"]
    assert version["proposal_decision_digest"] == body["proposal_decision_digest"]
    assert receipt["metadata"]["input_draft_digest"] == saved["draft_digest"]

    repeated = client.post(
        "/v1/recordings/recording-both/card-event-review/complete",
        json={
            "reviewer": "operator",
            "expected_revision": saved["draft_revision"],
            "full_video_acknowledged": True,
        },
    )
    assert repeated.status_code == 200
    assert repeated.json() == body

    revision = client.post(
        "/v1/recordings/recording-both/card-event-review/revisions",
        json={
            "parent_version_id": body["completed_version_id"],
            "expected_revision": body["draft_revision"],
        },
    )
    assert revision.status_code == 200
    assert revision.json()["review_state"] == "draft"
    assert revision.json()["parent_version_id"] == body["completed_version_id"]
    assert revision.json()["parent_digest"] == body["completed_version_digest"]
    assert version_path.read_text(encoding="utf-8") == version_before
    revised_detail = client.get("/v1/recordings/recording-both")
    assert revised_detail.json()["training_use"]["eligibility"] == "review_required"
    assert (
        revised_detail.json()["training_use"]["blocker"]
        == "Complete the full recording CardEvent review before training use."
    )


def test_operations_store_keeps_the_winning_draft_on_write_failure_and_source_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = CardEventReviewSource(
        recording_id="recording-1",
        source_asset_id="source-1",
        source_sha256="a" * 64,
        video="video-both.mov",
    )
    store = CardEventReviewStore(tmp_path / "operations")
    annotation = _annotation([{"time_s": 1.0, "type": "card_played", "confidence": "confirmed"}])
    store.update_draft(
        source,
        annotation=annotation,
        proposals=[],
        expected_revision=0,
    )
    draft_path = tmp_path / "operations" / "cardevent-reviews" / "recording-1" / "draft.json"
    draft_before = draft_path.read_bytes()

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("simulated atomic write failure")

    monkeypatch.setattr("doko_operations.cardevent_review._atomic_write_json", fail)
    with pytest.raises(CardEventReviewWriteError):
        store.update_draft(
            source,
            annotation=_annotation(
                [{"time_s": 2.0, "type": "card_played", "confidence": "confirmed"}]
            ),
            proposals=[],
            expected_revision=1,
        )
    assert draft_path.read_bytes() == draft_before

    changed_source = CardEventReviewSource(
        recording_id=source.recording_id,
        source_asset_id=source.source_asset_id,
        source_sha256="b" * 64,
        video=source.video,
    )
    with pytest.raises(CardEventReviewConflict):
        store.read(changed_source)


def test_recording_owned_reviews_have_stable_identity_and_single_draft(
    tmp_path: Path,
) -> None:
    client, settings, _ = _backend(tmp_path)

    empty = client.get("/v1/recordings/recording-both/card-event-reviews")
    assert empty.status_code == 200
    assert empty.json()["schema_version"] == "cardevent-review-collection/v1"
    assert empty.json()["reviews"] == []
    assert empty.json()["current_review_id"] is None

    created = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Niklas"},
    )
    assert created.status_code == 201
    draft = created.json()
    review_id = draft["review_id"]
    assert review_id.startswith("cardevent-review-")
    assert draft["review_url"] == f"/card-event-reviews/{review_id}"
    assert draft["operator"] == "Niklas"
    assert draft["review_state"] == "draft"

    duplicate = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Another operator"},
    )
    assert duplicate.status_code == 409
    collection = client.get("/v1/recordings/recording-both/card-event-reviews").json()
    assert [item["review_id"] for item in collection["reviews"]] == [review_id]

    proposal = draft["proposals"][0]["proposal_id"]
    saved = client.put(
        f"/v1/card-event-reviews/{review_id}",
        json={
            "annotation": _annotation([]),
            "proposals": [{"proposal_id": proposal, "decision": "accepted"}],
            "expected_revision": 0,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["draft_revision"] == 1

    completed = client.post(
        f"/v1/card-event-reviews/{review_id}/complete",
        json={
            "reviewer": "Niklas",
            "expected_revision": 1,
            "full_video_acknowledged": True,
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert completed_body["review_state"] == "completed"
    assert completed_body["completed_version_id"]
    assert completed_body["completed_version_digest"]
    assert completed_body["completion_receipt_id"]

    review_root = settings.operations_root / "cardevent-reviews" / review_id
    version_path = review_root / "versions" / f"{completed_body['completed_version_id']}.json"
    version_before = version_path.read_bytes()
    collection = client.get("/v1/recordings/recording-both/card-event-reviews").json()
    assert collection["latest_completed_review_id"] == review_id
    assert collection["reviews"][0]["reviewer"] == "Niklas"
    assert collection["reviews"][0]["event_counts"] == {
        "reviewed": 1,
        "proposed": 0,
        "dismissed": 0,
    }

    revision = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Niklas"},
    )
    assert revision.status_code == 201
    revision_body = revision.json()
    assert revision_body["review_id"] != review_id
    assert revision_body["parent_review_id"] == review_id
    assert revision_body["parent_version_id"] == completed_body["completed_version_id"]
    assert revision_body["parent_digest"] == completed_body["completed_version_digest"]
    assert revision_body["annotation"] == completed_body["annotation"]
    assert version_path.read_bytes() == version_before
    revised_collection = client.get("/v1/recordings/recording-both/card-event-reviews").json()
    assert revised_collection["current_review_id"] == review_id
    assert revised_collection["draft_review_id"] == revision_body["review_id"]

    restarted = TestClient(create_test_app(settings))
    persisted = restarted.get(f"/v1/card-event-reviews/{revision_body['review_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["parent_review_id"] == review_id


def test_review_resource_uses_one_idempotent_event_collection_and_preserves_lineage(
    tmp_path: Path,
) -> None:
    client, settings, _ = _backend(tmp_path)
    created = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Niklas"},
    )
    assert created.status_code == 201
    review = created.json()
    review_id = review["review_id"]
    proposed = review["events"][0]
    assert proposed["state"] == "proposed"
    assert proposed["origin"] == "model"
    assert proposed["proposal"]["proposal_id"] == review["proposals"][0]["proposal_id"]
    assert proposed["proposal"]["proposal_time_s"] == 1.0

    manual = client.post(
        f"/v1/card-event-reviews/{review_id}/events",
        json={
            "client_command_id": "command-manual-1",
            "expected_revision": 0,
            "effective_time_s": 1.2,
            "type": "card_played",
            "confidence": "confirmed",
        },
    )
    assert manual.status_code == 200
    manual_body = manual.json()
    assert manual_body["draft_revision"] == 1
    assert manual_body["changed_event"]["origin"] == "manual"
    assert manual_body["changed_event"]["state"] == "reviewed"
    manual_event_id = manual_body["changed_event"]["event_id"]
    assert manual_body["event_counts"] == {"reviewed": 1, "proposed": 1, "dismissed": 0}

    replay = client.post(
        f"/v1/card-event-reviews/{review_id}/events",
        json={
            "client_command_id": "command-manual-1",
            "expected_revision": 0,
            "effective_time_s": 1.2,
            "type": "card_played",
            "confidence": "confirmed",
        },
    )
    assert replay.status_code == 200
    assert replay.json() == manual_body
    conflict = client.post(
        f"/v1/card-event-reviews/{review_id}/events",
        json={
            "client_command_id": "command-manual-1",
            "expected_revision": 0,
            "effective_time_s": 1.3,
            "type": "card_played",
            "confidence": "confirmed",
        },
    )
    assert conflict.status_code == 409

    nearby_manual = client.post(
        f"/v1/card-event-reviews/{review_id}/events",
        json={
            "client_command_id": "command-manual-2",
            "expected_revision": 1,
            "effective_time_s": 1.02,
            "type": "card_played",
            "confidence": "confirmed",
        },
    )
    assert nearby_manual.status_code == 200
    assert nearby_manual.json()["changed_event"]["proposal"] is None

    accept = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{proposed['event_id']}",
        json={
            "client_command_id": "command-accept-1",
            "expected_revision": 2,
            "action": "accept",
        },
    )
    assert accept.status_code == 200
    accepted_body = accept.json()
    assert accepted_body["changed_event"]["event_id"] == proposed["event_id"]
    assert accepted_body["changed_event"]["state"] == "reviewed"
    assert (
        accepted_body["changed_event"]["proposal"]["proposal_id"]
        == proposed["proposal"]["proposal_id"]
    )
    assert accepted_body["event_counts"] == {"reviewed": 3, "proposed": 0, "dismissed": 0}
    assert "review" not in accepted_body
    assert len(client.get(f"/v1/card-event-reviews/{review_id}").json()["events"]) == 3

    fresh = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Niklas"},
    )
    assert fresh.status_code == 409

    retime = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{manual_event_id}",
        json={
            "client_command_id": "command-retime-1",
            "expected_revision": 3,
            "action": "retime",
            "effective_time_s": 1.25,
        },
    )
    assert retime.status_code == 200
    assert retime.json()["changed_event"]["event_id"] == manual_event_id
    assert retime.json()["changed_event"]["proposal"] is None

    versionless = client.post(
        f"/v1/card-event-reviews/{review_id}/complete",
        json={
            "reviewer": "Niklas",
            "expected_revision": 4,
            "full_video_acknowledged": True,
        },
    )
    assert versionless.status_code == 200
    version_id = versionless.json()["completed_version_id"]
    version_path = (
        settings.operations_root
        / "cardevent-reviews"
        / review_id
        / "versions"
        / f"{version_id}.json"
    )
    published = json.loads(version_path.read_text(encoding="utf-8"))
    assert [event["time_s"] for event in published["annotation"]["events"]] == [
        1.0,
        1.02,
        1.25,
    ]


def test_proposal_dismiss_undo_and_edit_keep_the_same_event_lineage(
    tmp_path: Path,
) -> None:
    client, _, _ = _backend(tmp_path)
    created = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Niklas"},
    ).json()
    review_id = created["review_id"]
    proposed = created["events"][0]

    blocked = client.post(
        f"/v1/card-event-reviews/{review_id}/complete",
        json={
            "reviewer": "Niklas",
            "expected_revision": 0,
            "full_video_acknowledged": True,
        },
    )
    assert blocked.status_code == 422
    assert "proposed" in blocked.json()["error"]["message"]

    dismissed = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{proposed['event_id']}",
        json={
            "client_command_id": "command-dismiss-1",
            "expected_revision": 0,
            "action": "dismiss",
        },
    ).json()["changed_event"]
    assert dismissed["event_id"] == proposed["event_id"]
    assert dismissed["state"] == "dismissed"
    assert dismissed["proposal"] == proposed["proposal"]

    undone = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{proposed['event_id']}",
        json={
            "client_command_id": "command-undo-1",
            "expected_revision": 1,
            "action": "undo",
        },
    ).json()["changed_event"]
    assert undone["event_id"] == proposed["event_id"]
    assert undone["state"] == "proposed"
    assert undone["proposal"] == proposed["proposal"]

    edited = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{proposed['event_id']}",
        json={
            "client_command_id": "command-edit-1",
            "expected_revision": 2,
            "action": "edit",
            "type": "trick_cleared",
            "notes": "Human correction",
        },
    ).json()["changed_event"]
    assert edited["event_id"] == proposed["event_id"]
    assert edited["state"] == "reviewed"
    assert edited["effective_time_s"] == proposed["effective_time_s"]
    assert edited["proposal"] == proposed["proposal"]

    retimed = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{proposed['event_id']}",
        json={
            "client_command_id": "command-retime-1",
            "expected_revision": 3,
            "action": "retime",
            "effective_time_s": 1.5,
        },
    ).json()["changed_event"]
    assert retimed["event_id"] == proposed["event_id"]
    assert retimed["effective_time_s"] == 1.5
    assert retimed["proposal"]["proposal_time_s"] == 1.0

    removed = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{proposed['event_id']}",
        json={
            "client_command_id": "command-remove-1",
            "expected_revision": 4,
            "action": "remove",
        },
    ).json()
    assert removed["changed_event"] is None
    assert removed["event_counts"] == {"reviewed": 0, "proposed": 0, "dismissed": 0}
    completed = client.post(
        f"/v1/card-event-reviews/{review_id}/complete",
        json={
            "reviewer": "Niklas",
            "expected_revision": 5,
            "full_video_acknowledged": True,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["annotation"]["events"] == []


def test_event_command_write_failure_keeps_the_previous_resource_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = CardEventReviewSource(
        recording_id="recording-1",
        source_asset_id="source-1",
        source_sha256="a" * 64,
        video="video.mov",
    )
    store = CardEventReviewStore(tmp_path / "operations")
    created = store.create_review(source, operator="Niklas")
    before = store.get_review(created["review_id"], source)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("simulated atomic write failure")

    monkeypatch.setattr("doko_operations.cardevent_review._atomic_write_json", fail)
    with pytest.raises(CardEventReviewWriteError):
        store.add_event(
            created["review_id"],
            source,
            client_command_id="command-write-failure",
            expected_revision=0,
            effective_time_s=1.0,
            event_type="card_played",
        )

    after = store.get_review(created["review_id"], source)
    assert after["draft_revision"] == before["draft_revision"] == 0
    assert after["events"] == before["events"] == []


def test_source_context_cache_skips_bundle_verification_and_media_probe_on_warm_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = _backend(tmp_path)
    app = client.app
    first = client.get("/v1/recordings/recording-both/card-event-reviews")
    assert first.status_code == 200
    cold_timing = app.state.card_event_review_source_cache.recent_timings()[-1]
    assert cold_timing["cache_hit"] is False
    assert cold_timing["bundle_metadata_read_ms"] >= 0.0
    assert cold_timing["bundle_member_verification_ms"] >= 0.0
    assert cold_timing["media_probe_ms"] >= 0.0

    def unexpected_verification(*args: object, **kwargs: object) -> None:
        raise AssertionError("warm review commands must not verify bundle members")

    def unexpected_probe(*args: object, **kwargs: object) -> None:
        raise AssertionError("warm review commands must not probe video")

    monkeypatch.setattr(
        "dokodetector_backend.card_event_review_api._verify_bundle_members",
        unexpected_verification,
    )
    monkeypatch.setattr(
        "dokodetector_backend.card_event_review_api._video_duration",
        unexpected_probe,
    )
    review = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Niklas"},
    ).json()
    command = client.post(
        f"/v1/card-event-reviews/{review['review_id']}/events",
        json={
            "client_command_id": "warm-command-1",
            "expected_revision": 0,
            "effective_time_s": 1.2,
            "type": "card_played",
        },
    )
    assert command.status_code == 200
    assert "review" not in command.json()
    warm_timing = app.state.card_event_review_source_cache.recent_timings()[-1]
    assert warm_timing["cache_hit"] is True
    assert warm_timing["bundle_metadata_read_ms"] == 0.0
    assert warm_timing["bundle_member_verification_ms"] == 0.0
    assert warm_timing["media_probe_ms"] == 0.0


def test_source_context_cache_invalidates_on_accepted_source_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = _backend(tmp_path)
    app = client.app
    assert client.get("/v1/recordings/recording-both/card-event-reviews").status_code == 200
    stored = app.state.recording_bundle_store.get("recording-both")
    assert stored is not None
    replacement = replace(
        stored,
        source_sha256="b" * 64,
        bundle_fingerprint="c" * 64,
    )
    monkeypatch.setattr(
        app.state.recording_bundle_store,
        "get",
        lambda recording_id: replacement if recording_id == "recording-both" else None,
    )

    response = client.get("/v1/recordings/recording-both/card-event-reviews")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "recording_metadata_invalid"
    timing = app.state.card_event_review_source_cache.recent_timings()[-1]
    assert timing["cache_hit"] is False
