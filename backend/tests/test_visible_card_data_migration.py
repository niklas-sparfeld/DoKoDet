from __future__ import annotations

import json
from pathlib import Path

from doko_operations.pipeline_data import (
    DataRevision,
    ProcessorProducer,
    RecordingVideoSource,
    canonical_data_revision_bytes,
    canonical_json_bytes,
    sha256_bytes,
)
from table_evidence_analyzer.pipeline_data import parse_visible_card_data_bytes

from dokodetector_backend.visible_card_data_migration import (
    migrate_visible_card_revisions,
)

SOURCE = RecordingVideoSource(
    recording_id="recording-01",
    relative_path="data/intake/recordings/recording-01/videos/video.mov",
    video_sha256="a" * 64,
    byte_length=100,
    duration_us=10_000_000,
)


def _frame() -> dict[str, object]:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "a" * 64,
        "requested_time_us": 1_000,
        "frame_index": 1,
        "presentation_timestamp_us": 1_000,
        "width": 1_000,
        "height": 1_000,
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "output_encoding": "jpeg",
        "content_type": "image/jpeg",
        "image_sha256": "b" * 64,
        "policy": "exact-event/v1",
    }


def _content(*, current: bool) -> dict[str, object]:
    outcome: dict[str, object] = {
        "event_id": "event-01",
        "frame_identity": _frame(),
        "status": "empty",
        "candidates": [],
        "error": None,
    }
    if current:
        outcome["ignored_regions"] = []
    return {"schema_version": "visible-card-data/v1", "outcomes": [outcome]}


def _write_revision(root: Path, *, revision_id: str, current: bool) -> Path:
    revision_path = root / revision_id
    revision_path.mkdir(parents=True)
    content = _content(current=current)
    content_bytes = canonical_json_bytes(content)
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=sha256_bytes(content_bytes),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="run-01",
            processor_type="visible-card-detection",
            implementation_id="fixture.v1",
        ),
        coverage={"kind": "visible_frames", "frames": []},
        created_at="2026-09-14T07:00:00Z",
    )
    (revision_path / "content.json").write_bytes(content_bytes)
    (revision_path / "manifest.json").write_bytes(canonical_data_revision_bytes(manifest))
    return revision_path


def test_migration_adds_missing_regions_updates_digest_and_is_idempotent(tmp_path: Path) -> None:
    revisions_root = tmp_path / "revisions"
    revisions_root.mkdir()
    revision_path = _write_revision(revisions_root, revision_id="revision-old", current=False)

    report = migrate_visible_card_revisions(revisions_root)

    assert report.revisions_scanned == 1
    assert report.revisions_changed == 1
    assert report.outcomes_added == 1
    assert report.revisions_already_current == 0
    migrated_content = parse_visible_card_data_bytes((revision_path / "content.json").read_bytes())
    assert migrated_content.outcomes[0].ignored_regions == ()
    migrated_manifest = json.loads((revision_path / "manifest.json").read_text())
    assert migrated_manifest["content_sha256"] == sha256_bytes(
        (revision_path / "content.json").read_bytes()
    )

    second = migrate_visible_card_revisions(revisions_root)
    assert second.revisions_changed == 0
    assert second.outcomes_added == 0
    assert second.revisions_already_current == 1


def test_migration_check_does_not_write(tmp_path: Path) -> None:
    revisions_root = tmp_path / "revisions"
    revisions_root.mkdir()
    revision_path = _write_revision(revisions_root, revision_id="revision-old", current=False)
    old_content = (revision_path / "content.json").read_bytes()
    old_manifest = (revision_path / "manifest.json").read_bytes()

    report = migrate_visible_card_revisions(revisions_root, apply=False)

    assert report.revisions_changed == 1
    assert report.outcomes_added == 1
    assert (revision_path / "content.json").read_bytes() == old_content
    assert (revision_path / "manifest.json").read_bytes() == old_manifest
