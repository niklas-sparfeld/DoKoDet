from __future__ import annotations

import hashlib
import json
from pathlib import Path

from doko_operations.cardevent_migration import migrate_cardeventnet
from doko_operations.cardevent_readiness import (
    build_cardeventnet_readiness,
    write_cardeventnet_readiness_receipt,
)
from doko_operations.cli import main


def test_readiness_distinguishes_imported_annotation_from_missing_annotation(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"review-video", annotation=True)
    _write_legacy(legacy, "IMG_0002", b"missing-video", annotation=False)
    migrate_cardeventnet(tmp_path, operator="operator-a")

    report = build_cardeventnet_readiness(tmp_path)
    data = report.to_mapping()
    records = {item["recording_id"]: item for item in data["recordings"]}

    imported = records["cardeventnet-IMG_0001"]
    assert imported["primary_state"] == "annotation_imported_review_required"
    assert imported["annotation_present"] is True
    assert imported["action"]["workspace_route"] == (
        "/recordings/cardeventnet-IMG_0001/pipeline/events?view=reviewed"
    )

    missing = records["cardeventnet-IMG_0002"]
    assert missing["primary_state"] == "annotation_missing"
    assert missing["annotation_present"] is False
    assert data["counts"]["review_queue"] == 2
    assert data["migration"]["not_migrated"] == []

    assert data == build_cardeventnet_readiness(tmp_path).to_mapping()


def test_readiness_reports_durable_progress_and_completed_coverage(tmp_path: Path) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"progress-video", annotation=True)
    migrate_cardeventnet(tmp_path, operator="operator-a")
    reference_root = (
        tmp_path
        / "data"
        / "operations"
        / "pipeline-references"
        / "cardeventnet-IMG_0001"
        / "events"
    )
    draft_path = reference_root / "draft.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["items"][0]["review_state"] = "accepted"
    draft["coverage"] = {
        "kind": "event_intervals",
        "intervals": [{"start_us": 0, "end_us": 5_000_000}],
    }
    draft_path.write_text(json.dumps(draft), encoding="utf-8")

    progress = build_cardeventnet_readiness(tmp_path).to_mapping()["recordings"][0]
    assert progress["primary_state"] == "review_in_progress"
    assert progress["review_progress"]["reviewed_item_count"] == 1
    assert progress["review_progress"]["coverage_percent"] == 50
    assert progress["review_progress"]["coverage_complete"] is False

    state_path = reference_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["draft_state"] = "completed"
    state["selected_completed_revision_id"] = state["source_revision_id"]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    draft["coverage"]["intervals"] = [{"start_us": 0, "end_us": 10_000_000}]
    draft_path.write_text(json.dumps(draft), encoding="utf-8")

    completed = build_cardeventnet_readiness(tmp_path).to_mapping()["recordings"][0]
    assert completed["primary_state"] == "review_complete"
    assert completed["review_progress"]["coverage_complete"] is True
    assert completed["action"] is None


def test_readiness_receipt_is_digest_backed_and_cli_writes_it(tmp_path: Path, capsys) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"receipt-video", annotation=True)
    migrate_cardeventnet(tmp_path, operator="operator-a")
    report = build_cardeventnet_readiness(tmp_path)
    receipt_path = tmp_path / "readiness.json"

    receipt = write_cardeventnet_readiness_receipt(
        report,
        receipt_path,
        operator="operator-a",
    )
    saved = json.loads(receipt_path.read_text(encoding="utf-8"))
    core = {key: value for key, value in saved.items() if key != "receipt_sha256"}
    assert receipt["path"] == str(receipt_path)
    assert saved["receipt_sha256"] == hashlib.sha256(
        json.dumps(core, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert (
        main(
            [
                "data",
                "cardevent",
                "readiness",
                "--repository-root",
                str(tmp_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "cardeventnet-readiness/v1"
    assert "receipt" not in output

    assert (
        main(
            [
                "data",
                "cardevent",
                "readiness",
                "--repository-root",
                str(tmp_path),
                "--operator",
                "operator-b",
                "--receipt",
                "receipt-from-cli.json",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["receipt"]["operator"] == "operator-b"
    assert (tmp_path / "receipt-from-cli.json").is_file()


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
                    "events": [{"type": "card_state_changed", "time_s": 1.25}],
                }
            ),
            encoding="utf-8",
        )
    manifest_path = root / "dataset-manifest.v1.yaml"
    existing = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if not existing:
        existing = "schema_version: cardevent-video-metadata/v1\nvideos:\n"
    manifest_path.write_text(
        existing
        + f"  - video_id: {video_id}\n"
        + f"    file_name: {video_id}.mov\n"
        + "    content_type: staged_trick_sequence\n"
        + f"    session_id: session-{video_id}\n"
        + "    duration_s: 10.0\n"
        + f"    table_setup: setup-{video_id}\n"
        + "    source_permission: training_and_evaluation\n",
        encoding="utf-8",
    )
    split = root / "splits" / "default.yaml"
    current = split.read_text(encoding="utf-8") if split.exists() else "train:\n"
    split.write_text(current + f"- {video_id}\n", encoding="utf-8")
