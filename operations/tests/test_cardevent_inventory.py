from __future__ import annotations

import hashlib
import json
from pathlib import Path

from doko_operations.cardevent_inventory import audit_cardeventnet
from doko_operations.cli import main


def test_cardevent_audit_cli_supports_human_and_json_reports(tmp_path: Path, capsys) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "cli", b"cli-video", annotation=True)

    assert (
        main(
            [
                "data",
                "cardevent",
                "audit",
                "--repository-root",
                str(tmp_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "cardeventnet-inventory/v1"
    assert payload["counts"]["recordings"] == 1

    assert (
        main(
            [
                "data",
                "cardevent",
                "audit",
                "--repository-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert "CardEventNet legacy inventory" in capsys.readouterr().out


def test_inventory_separates_missing_annotation_conflict_and_migrated_source(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "complete", b"complete-video", annotation=True)
    _write_legacy(legacy, "partial", b"partial-video", annotation=False)
    _write_legacy(legacy, "conflict", b"conflict-video", annotation=True)
    intake = tmp_path / "data" / "intake" / "recordings"
    _write_shared_bundle(intake, "complete", b"complete-video")
    _write_shared_bundle(intake, "conflict", b"other-video")

    report = audit_cardeventnet(tmp_path)
    recordings = {item.video_id: item for item in report.recordings}

    assert recordings["complete"].source_digest_match is True
    assert recordings["complete"].migration_state == "already_migrated_review_required"
    assert recordings["complete"].annotation_present
    assert not recordings["complete"].human_review_complete
    assert recordings["partial"].migration_state == "annotation_missing"
    assert not recordings["partial"].annotation_present
    assert recordings["partial"].human_review_complete is False
    assert recordings["conflict"].source_digest_match is False
    assert recordings["conflict"].migration_state == "source_digest_conflict"
    assert any(
        item.kind == "shared_recording_missing" and item.video_id == "partial"
        for item in report.discrepancies
    )


def _write_legacy(root: Path, video_id: str, video: bytes, *, annotation: bool) -> None:
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "annotations").mkdir(parents=True, exist_ok=True)
    (root / "splits").mkdir(parents=True, exist_ok=True)
    (root / "raw" / f"{video_id}.mov").write_bytes(video)
    if annotation:
        (root / "annotations" / f"{video_id}.json").write_text(
            json.dumps(
                {
                    "schema_version": "cardevent-annotation/v2",
                    "video": f"{video_id}.mov",
                    "events": [],
                }
            ),
            encoding="utf-8",
        )
    manifest_path = root / "dataset-manifest.v1.yaml"
    existing_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if not existing_manifest:
        existing_manifest = "schema_version: cardevent-video-metadata/v1\nvideos:\n"
    manifest_path.write_text(
        existing_manifest
        + f"  - video_id: {video_id}\n"
        + f"    file_name: {video_id}.mov\n"
        + "    duration_s: 1.0\n"
        + f"    session_id: session-{video_id}\n"
        + f"    table_setup: setup-{video_id}\n"
        + "    source_permission: training_and_evaluation\n",
        encoding="utf-8",
    )
    split_path = root / "splits" / "default.yaml"
    existing = split_path.read_text(encoding="utf-8") if split_path.exists() else "train:\n"
    split_path.write_text(existing + f"- {video_id}\n", encoding="utf-8")


def _write_shared_bundle(root: Path, video_id: str, video: bytes) -> None:
    recording_id = f"recording-{video_id}"
    bundle = root / recording_id
    videos = bundle / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    video_path = videos / f"video-{recording_id}.mov"
    video_path.write_bytes(video)
    video_digest = hashlib.sha256(video).hexdigest()
    source = {
        "schema_version": "source-record/v1",
        "source_asset_id": f"source-{video_id}",
        "sha256": video_digest,
        "byte_length": len(video),
        "media_type": "video/quicktime",
        "original_filename": f"{video_id}.mov",
        "acquisition_method": "fixture",
        "source_permission": "training_and_evaluation",
        "allowed_uses": ["train", "validation", "evaluation"],
        "session_id": f"session-{video_id}",
        "recording_id": recording_id,
        "video_id": f"video-{video_id}",
        "game_id": None,
        "round_id": None,
        "table_setup": f"setup-{video_id}",
        "content_type": "staged_trick_sequence",
        "retention_state": "active",
        "notes": None,
    }
    enrollment = {
        "schema_version": "task-enrollment/v1",
        "source_asset_id": f"source-{video_id}",
        "enrollments": [
            {
                "task_enrollment_id": f"{recording_id}-cardevent_event_detection",
                "task": "cardevent_event_detection",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "fixture",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "reason": None,
            },
            {
                "task_enrollment_id": f"{recording_id}-table_evidence_analysis",
                "task": "table_evidence_analysis",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "fixture",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "reason": None,
            },
        ],
    }

    def encoded(value: object) -> bytes:
        return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()

    source_bytes = encoded(source)
    enrollment_bytes = encoded(enrollment)
    manifest = {
        "schema_version": "repository-bundle/v1",
        "source_asset_id": f"source-{video_id}",
        "recording_id": recording_id,
        "video_id": f"video-{video_id}",
        "session_id": f"session-{video_id}",
        "state": "complete",
        "source_sha256": video_digest,
        "files": {
            "video": {
                "relative_path": f"videos/video-{recording_id}.mov",
                "type": "video/quicktime",
                "byte_length": len(video),
                "sha256": video_digest,
            },
            "source_record": {
                "relative_path": "source-record.json",
                "type": "application/json",
                "byte_length": len(source_bytes),
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
            "task_enrollment": {
                "relative_path": "initial-task-enrollment.json",
                "type": "application/json",
                "byte_length": len(enrollment_bytes),
                "sha256": hashlib.sha256(enrollment_bytes).hexdigest(),
            },
            "proposal_generator_runs": [],
        },
    }
    (bundle / "source-record.json").write_bytes(source_bytes)
    (bundle / "initial-task-enrollment.json").write_bytes(enrollment_bytes)
    (bundle / "manifest.json").write_bytes(encoded(manifest))
