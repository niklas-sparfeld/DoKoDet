from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from doko_operations.cardevent_interval_readiness import (
    build_cardeventnet_interval_readiness,
    write_cardeventnet_zero_interval_attestation,
    write_legacy_device_exclusion_receipt,
)
from doko_operations.source_exclusion import (
    LEGACY_DEVICE_RECORDING_IDS,
    LEGACY_DEVICE_SOURCE_ASSET_IDS,
    LEGACY_DEVICE_SOURCE_DIGESTS,
    SourceExclusionError,
    ensure_source_allowed,
    read_legacy_device_exclusion,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_revision(
    root: Path,
    recording_id: str,
    revision_id: str,
    *,
    source_asset_id: str = "source-normal",
    source_sha256: str | None = None,
    interval: bool = False,
) -> tuple[str, str]:
    duration_us = 10_000_000
    source_sha256 = source_sha256 or hashlib.sha256(recording_id.encode()).hexdigest()
    content = {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": f"event-{recording_id}",
                "event_type": "card_state_changed",
                "start_us": 3_000_000 if interval else 2_000_000,
                "end_us": 4_000_000 if interval else 2_000_000,
            }
        ],
    }
    content_bytes = json.dumps(content, separators=(",", ":"), sort_keys=True).encode()
    manifest = {
        "schema_version": "data-revision/v1",
        "revision_id": revision_id,
        "content_type": "events",
        "source": {
            "schema_version": "recording-video/v1",
            "recording_id": recording_id,
            "relative_path": f"data/intake/recordings/{recording_id}/videos/video.mov",
            "video_sha256": source_sha256,
            "byte_length": 10,
            "duration_us": duration_us,
        },
        "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
        "input_revision_ids": [],
        "origin": "manual",
        "producer": {"kind": "human", "review_id": "review-1", "operator_id": "operator-1"},
        "coverage": {
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": duration_us}],
            "source_duration_us": duration_us,
        },
        "created_at": "2026-09-16T00:00:00Z",
        "recording_id": recording_id,
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode()
    revision_root = root / "data" / "operations" / "pipeline" / "revisions" / revision_id
    (revision_root / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (revision_root / "manifest.json").write_bytes(manifest_bytes)
    (revision_root / "content.json").write_bytes(content_bytes)
    source_root = root / "data" / "intake" / "recordings" / recording_id
    _write_json(
        source_root / "source-record.json",
        {
            "recording_id": recording_id,
            "source_asset_id": source_asset_id,
            "sha256": source_sha256,
        },
    )
    _write_json(
        root
        / "data"
        / "operations"
        / "pipeline-references"
        / recording_id
        / "events"
        / "state.json",
        {
            "recording_id": recording_id,
            "content_type": "events",
            "draft_state": "completed",
            "draft_revision": 1,
            "source_revision_id": revision_id,
            "selected_completed_revision_id": revision_id,
        },
    )
    return (
        f"data/operations/pipeline/revisions/{revision_id}/manifest.json",
        f"data/operations/pipeline/revisions/{revision_id}/content.json",
    )


def _write_dataset(root: Path, entries: list[dict[str, object]]) -> Path:
    dataset_dir = root / "data" / "operations" / "cardevent-datasets" / "fixture"
    _write_json(
        dataset_dir / "dataset.json",
        {
            "schema_version": "cardeventnet-dataset/v1",
            "dataset_version_id": "cardeventnet-dataset-fixture",
            "dataset_version_digest": "fixture",
            "entries": entries,
        },
    )
    return dataset_dir


def _entry(
    recording_id: str,
    revision_id: str,
    manifest_path: str,
    content_path: str,
    *,
    partition: str,
    source_asset_id: str = "source-normal",
    source_sha256: str | None = None,
) -> dict[str, object]:
    source_sha256 = source_sha256 or hashlib.sha256(recording_id.encode()).hexdigest()
    return {
        "recording_id": recording_id,
        "source_asset_id": source_asset_id,
        "source_sha256": source_sha256,
        "source_path": f"data/intake/recordings/{recording_id}/videos/video.mov",
        "partition": partition,
        "content_type": "events",
        "event_revision_id": revision_id,
        "event_revision_manifest_path": manifest_path,
        "event_revision_content_path": content_path,
    }


def test_interval_readiness_distinguishes_points_intervals_and_zero_decisions(
    tmp_path: Path,
) -> None:
    point_manifest, point_content = _write_revision(tmp_path, "point", "revision-point")
    interval_manifest, interval_content = _write_revision(
        tmp_path, "interval", "revision-interval", interval=True
    )
    dataset_dir = _write_dataset(
        tmp_path,
        [
            _entry(
                "point",
                "revision-point",
                point_manifest,
                point_content,
                partition="train",
            ),
            _entry(
                "interval",
                "revision-interval",
                interval_manifest,
                interval_content,
                partition="validation",
            ),
        ],
    )

    report = build_cardeventnet_interval_readiness(tmp_path, dataset_path=dataset_dir)
    records = {item["recording_id"]: item for item in report["recordings"]}

    assert report["state"] == "blocked"
    assert records["point"]["point_count"] == 1
    assert records["point"]["interval_count"] == 0
    assert records["point"]["decision"] == "interval_decision_required"
    assert records["interval"]["point_count"] == 0
    assert records["interval"]["interval_count"] == 1
    assert records["interval"]["decision"] == "interval_reviewed"
    assert records["point"]["operator_action"]["recording_id"] == "point"

    attestation = write_cardeventnet_zero_interval_attestation(
        tmp_path,
        "point",
        operator="operator-1",
        dataset_path=dataset_dir,
        created_at_utc="2026-09-16T00:00:00Z",
    )
    assert attestation["decision"] == "no_card_state_change_interval"
    report = build_cardeventnet_interval_readiness(tmp_path, dataset_path=dataset_dir)
    point = next(item for item in report["recordings"] if item["recording_id"] == "point")
    assert point["decision"] == "attested_no_interval"
    assert point["classification"] == "eligible"


def test_legacy_exclusion_receipt_is_digest_bound_and_blocks_sources(tmp_path: Path) -> None:
    entries: list[dict[str, object]] = []
    for recording_id, source_asset_id in zip(
        LEGACY_DEVICE_RECORDING_IDS, LEGACY_DEVICE_SOURCE_ASSET_IDS, strict=True
    ):
        source_sha256 = LEGACY_DEVICE_SOURCE_DIGESTS[source_asset_id]
        source_root = tmp_path / "data" / "intake" / "recordings" / recording_id
        _write_json(
            source_root / "source-record.json",
            {
                "recording_id": recording_id,
                "source_asset_id": source_asset_id,
                "sha256": source_sha256,
            },
        )
        entries.append(
            {
                "recording_id": recording_id,
                "source_asset_id": source_asset_id,
                "source_sha256": source_sha256,
                "source_path": f"data/intake/recordings/{recording_id}/videos/video.mov",
                "partition": "validation",
            }
        )
    dataset_dir = _write_dataset(tmp_path, entries)

    receipt = write_legacy_device_exclusion_receipt(
        tmp_path,
        operator="operator-1",
        dataset_path=dataset_dir,
        created_at_utc="2026-09-16T00:00:00Z",
    )
    loaded, file_digest = read_legacy_device_exclusion(tmp_path)

    assert receipt["role"] == "legacy_device_diagnostic"
    assert loaded is not None
    assert file_digest == hashlib.sha256(
        (tmp_path / receipt["path"]).read_bytes()
    ).hexdigest()
    with pytest.raises(SourceExclusionError, match="legacy-device diagnostic-only"):
        ensure_source_allowed(
            source_asset_id="source-cardeventnet-IMG_2777",
            source_sha256=LEGACY_DEVICE_SOURCE_DIGESTS["source-cardeventnet-IMG_2777"],
            recording_id="cardeventnet-IMG_2777",
            context="validation dataset",
        )
