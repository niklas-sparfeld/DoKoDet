from __future__ import annotations

import json
from pathlib import Path

from doko_operations.cardevent_migration import migrate_cardeventnet
from doko_operations.cli import main
from doko_operations.intake import inspect_repository
from doko_operations.pipeline_data import ImportProducer, parse_data_revision_bytes
from doko_operations.pipeline_reference import (
    parse_reference_draft_bytes,
    parse_reference_state_bytes,
)


def test_migration_publishes_current_bundles_and_unreviewed_drafts(tmp_path: Path) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"video-1", [("card_state_changed", 1.25)])
    _write_legacy(legacy, "IMG_0002", b"video-2", [])

    result = migrate_cardeventnet(tmp_path, operator="operator-a")

    assert result.source_count == 2
    assert result.annotation_count == 2
    assert result.draft_reference_count == 2
    assert {item.bundle_action for item in result.items} == {"published"}
    assert {item.reference_action for item in result.items} == {"draft_created"}
    inspection = inspect_repository(
        tmp_path,
        bundle_root=tmp_path / "data" / "intake" / "recordings",
        artifacts_root=tmp_path / "data" / "operations" / "validation-artifacts",
    )
    assert inspection.valid
    assert len(inspection.bundles) == 2

    item = next(item for item in result.items if item.video_id == "IMG_0001")
    revision_path = tmp_path / "data" / "operations" / "pipeline" / "revisions" / item.revision_id
    revision = parse_data_revision_bytes(
        (revision_path / "manifest.json").read_bytes(),
        (revision_path / "content.json").read_bytes(),
    )
    assert revision.recording_id == item.recording_id
    assert revision.coverage["review_state"] == "unreviewed"
    assert isinstance(revision.producer, ImportProducer)

    reference_root = (
        tmp_path / "data" / "operations" / "pipeline-references" / item.recording_id / "events"
    )
    state = parse_reference_state_bytes((reference_root / "state.json").read_bytes())
    draft = parse_reference_draft_bytes((reference_root / "draft.json").read_bytes())
    assert state.draft_state == "draft"
    assert state.selected_completed_revision_id is None
    assert draft.source_revision_id == item.revision_id
    assert [entry.review_state for entry in draft.items] == ["pending"]

    annotation = (
        tmp_path
        / "data"
        / "operations"
        / "cardeventnet-imports"
        / item.recording_id
        / "annotation.json"
    )
    assert annotation.read_bytes() == (legacy / "annotations" / "IMG_0001.json").read_bytes()
    assert (
        tmp_path
        / "data"
        / "operations"
        / "cardeventnet-imports"
        / "legacy"
        / "dataset-manifest.v1.yaml"
    ).is_file()


def test_migration_is_a_no_op_after_a_complete_receipt(tmp_path: Path) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"stable-video", [])

    first = migrate_cardeventnet(tmp_path, operator="operator-a")
    receipt = tmp_path / first.receipt_path
    before = receipt.read_bytes()

    second = migrate_cardeventnet(tmp_path, operator="operator-b")

    assert second.no_op
    assert second.state == "complete"
    assert receipt.read_bytes() == before


def test_migration_keeps_missing_annotation_as_an_empty_unreviewed_draft(tmp_path: Path) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"missing-annotation", [], annotation=False)

    result = migrate_cardeventnet(tmp_path, operator="operator-a")

    assert result.source_count == 1
    assert result.annotation_count == 0
    item = result.items[0]
    reference_root = (
        tmp_path / "data" / "operations" / "pipeline-references" / item.recording_id / "events"
    )
    state = parse_reference_state_bytes((reference_root / "state.json").read_bytes())
    draft = parse_reference_draft_bytes((reference_root / "draft.json").read_bytes())
    assert state.draft_state == "draft"
    assert draft.source_revision_id is None
    assert draft.items == ()


def test_migration_stops_on_a_conflicting_existing_source(tmp_path: Path) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"source-a", [])
    bundle = tmp_path / "data" / "intake" / "recordings" / "cardeventnet-IMG_0001"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(
        json.dumps({"source_sha256": _sha256(b"source-b")}),
        encoding="utf-8",
    )

    try:
        migrate_cardeventnet(tmp_path, operator="operator-a")
    except RuntimeError as error:
        assert "different source digest" in str(error)
    else:
        raise AssertionError("conflicting source was accepted")
    assert not (
        tmp_path / "data" / "operations" / "cardeventnet-imports" / "migration.json"
    ).exists()


def test_migration_repairs_an_imported_noncanonical_video_descriptor(tmp_path: Path) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"repair-me", [])
    first = migrate_cardeventnet(tmp_path, operator="operator-a")
    (tmp_path / first.receipt_path).unlink()

    bundle = tmp_path / "data" / "intake" / "recordings" / "cardeventnet-IMG_0001"
    video = bundle / "videos" / "video-cardeventnet-IMG_0001.mov"
    repaired_source = video.with_suffix(".m4v")
    video.rename(repaired_source)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["video"]["relative_path"] = "videos/video-cardeventnet-IMG_0001.m4v"
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = migrate_cardeventnet(tmp_path, operator="operator-b")

    assert result.items[0].bundle_action == "repaired"
    assert (bundle / "videos" / "video-cardeventnet-IMG_0001.mov").is_file()
    assert not repaired_source.exists()
    inspection = inspect_repository(
        tmp_path,
        bundle_root=tmp_path / "data" / "intake" / "recordings",
        artifacts_root=tmp_path / "data" / "operations" / "validation-artifacts",
    )
    assert inspection.valid


def test_cli_migration_reports_json_and_preserves_completed_reference(
    tmp_path: Path, capsys
) -> None:
    legacy = tmp_path / "card_event_net" / "data"
    _write_legacy(legacy, "IMG_0001", b"completed-video", [])
    reference_root = (
        tmp_path
        / "data"
        / "operations"
        / "pipeline-references"
        / "cardeventnet-IMG_0001"
        / "events"
    )
    state = {
        "schema_version": "pipeline-reference-state/v1",
        "recording_id": "cardeventnet-IMG_0001",
        "content_type": "events",
        "draft_revision": 0,
        "draft_state": "completed",
        "source_revision_id": None,
        "selected_completed_revision_id": None,
        "updated_at": "2026-01-01T00:00:00Z",
    }
    draft = {
        "schema_version": "pipeline-reference-draft/v1",
        "recording_id": "cardeventnet-IMG_0001",
        "content_type": "events",
        "revision": 0,
        "source_revision_id": None,
        "items": [],
        "coverage": {"kind": "full_recording"},
        "impact": [],
        "updated_at": "2026-01-01T00:00:00Z",
    }
    reference_root.mkdir(parents=True)
    (reference_root / "state.json").write_bytes(_canonical_json(state))
    (reference_root / "draft.json").write_bytes(_canonical_json(draft))
    before = (reference_root / "state.json").read_bytes()

    assert (
        main(
            [
                "data",
                "cardevent",
                "migrate",
                "--repository-root",
                str(tmp_path),
                "--operator",
                "operator-a",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["source_count"] == 1
    assert output["items"][0]["reference_action"] == "completed_preserved"
    assert (reference_root / "state.json").read_bytes() == before


def _write_legacy(
    root: Path,
    video_id: str,
    video: bytes,
    events: list[tuple[str, float]],
    *,
    annotation: bool = True,
) -> None:
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
                    "events": [
                        {"type": event_type, "time_s": time_s} for event_type, time_s in events
                    ],
                }
            ),
            encoding="utf-8",
        )
    manifest = root / "dataset-manifest.v1.yaml"
    existing = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
    if not existing:
        existing = "schema_version: cardevent-video-metadata/v1\nvideos:\n"
    manifest.write_text(
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
    existing_split = split.read_text(encoding="utf-8") if split.exists() else "train:\n"
    split.write_text(existing_split + f"- {video_id}\n", encoding="utf-8")


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()
