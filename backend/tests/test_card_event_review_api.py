from __future__ import annotations

import hashlib
import json
import shutil
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
from dokodetector_backend.repository import upgrade_database

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


def _backend(tmp_path: Path) -> tuple[TestClient, Settings, Path]:
    intake_root = tmp_path / "data" / "intake" / "recordings"
    shutil.copytree(FIXTURE_ROOT, intake_root / "recording-both")
    database_url = f"sqlite:///{tmp_path / 'review.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
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

    saved = client.put(
        "/v1/recordings/recording-both/card-event-review/draft", json=payload
    )
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
        client.put(
            "/v1/recordings/recording-both/card-event-review/draft", json=stale
        ).status_code
        == 409
    )

    foreign = dict(payload)
    foreign["expected_revision"] = 1
    foreign["proposals"] = [{"proposal_id": "foreign-proposal", "decision": "accepted"}]
    rejected = client.put(
        "/v1/recordings/recording-both/card-event-review/draft", json=foreign
    )
    assert rejected.status_code == 422
    assert (
        client.get("/v1/recordings/recording-both/card-event-review").json()["draft_revision"]
        == 1
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

    response = client.put(
        "/v1/recordings/recording-both/card-event-review/draft", json=payload
    )

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
    annotation = _annotation(
        [{"time_s": 1.0, "type": "card_played", "confidence": "confirmed"}]
    )
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
