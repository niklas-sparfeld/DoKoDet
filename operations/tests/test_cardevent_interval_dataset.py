from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from doko_operations.cardevent_dataset import (
    CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
    CARD_EVENTNET_DATASET_SCHEMA_VERSION,
    CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
    CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
    _coverage,
    _digest,
)
from doko_operations.cardevent_interval_dataset import (
    CardEventNetIntervalDatasetError,
    build_cardeventnet_interval_sampling_report,
    freeze_cardeventnet_interval_dataset,
)
from doko_operations.cardevent_materialization import materialize_cardeventnet_dataset


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    operations = tmp_path / "data" / "operations"
    source_root = tmp_path / "data" / "intake" / "recordings"
    revision_root = operations / "pipeline" / "revisions"
    records: list[dict[str, object]] = []
    partitions = {
        "train": ["recording-a"],
        "validation": ["recording-b"],
        "test": ["recording-c"],
    }
    all_ids = ["recording-a", "recording-b", "recording-c", "cardeventnet-IMG_2777"]
    for recording_id in all_ids:
        source_bytes = f"source-{recording_id}".encode()
        source_path = source_root / recording_id / "videos" / f"video-{recording_id}.mov"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(source_bytes)
        old_content = {
            "events": [
                {"event_type": "card_state_changed", "start_us": 1_000_000, "end_us": 1_000_000}
            ]
        }
        new_content = {
            "events": [
                {"event_type": "card_state_changed", "start_us": 1_000_000, "end_us": 1_000_000},
                {"event_type": "card_state_changed", "start_us": 2_000_000, "end_us": 3_000_000},
            ]
        }
        old_root = revision_root / f"old-{recording_id}"
        new_root = revision_root / f"new-{recording_id}"
        old_manifest = {
            "content_type": "events",
            "revision_id": f"old-{recording_id}",
            "source": {"video_sha256": _sha256(source_bytes), "duration_us": 4_000_000},
            "coverage": {"intervals": [{"start_us": 0, "end_us": 4_000_000}]},
        }
        new_manifest = {
            "content_type": "events",
            "revision_id": f"new-{recording_id}",
            "source": {"video_sha256": _sha256(source_bytes), "duration_us": 4_000_000},
            "coverage": {"intervals": [{"start_us": 0, "end_us": 4_000_000}]},
        }
        for root, manifest, content in (
            (old_root, old_manifest, old_content),
            (new_root, new_manifest, new_content),
        ):
            _write_json(root / "manifest.json", manifest)
            _write_json(root / "content.json", content)
        partition = (
            next(name for name, values in partitions.items() if recording_id in values)
            if recording_id != "cardeventnet-IMG_2777"
            else "validation"
        )
        records.append(
            {
                "recording_id": recording_id,
                "source_asset_id": f"source-{recording_id}",
                "source_path": source_path.relative_to(tmp_path).as_posix(),
                "source_sha256": _sha256(source_bytes),
                "source_permission": "project_use",
                "content_type": "staged_activity",
                "group_keys": [["session_id", f"session-{recording_id}"]],
                "partition": partition,
                "event_revision_id": f"old-{recording_id}",
                "event_revision_manifest_path": old_root.relative_to(tmp_path).as_posix()
                + "/manifest.json",
                "event_revision_manifest_sha256": _sha256(
                    (old_root / "manifest.json").read_bytes()
                ),
                "event_revision_content_path": old_root.relative_to(tmp_path).as_posix()
                + "/content.json",
                "event_revision_content_sha256": _sha256((old_root / "content.json").read_bytes()),
                "event_count": 1,
                "duration_us": 4_000_000,
                "review_coverage": {"coverage_complete": True},
                "allowed_uses": ["train", "validation", "test"],
                "retention_state": "active",
                "task": "cardevent_event_detection",
            }
        )

    dataset_core = {
        "schema_version": CARD_EVENTNET_DATASET_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "readiness_digest": "a" * 64,
        "split_version_id": "source-split",
        "split_version_digest": "b" * 64,
        "test_sealed": True,
        "entries": records,
    }
    dataset = {
        **dataset_core,
        "dataset_version_id": "dataset-m3-fixture",
        "dataset_version_digest": _digest(dataset_core),
    }
    split_core = {
        "schema_version": CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "dataset_version_id": dataset["dataset_version_id"],
        "dataset_version_digest": dataset["dataset_version_digest"],
        "group_key_names": ["session_id"],
        "train": partitions["train"],
        "validation": ["recording-b", "cardeventnet-IMG_2777"],
        "test": partitions["test"],
        "unassigned": [],
        "test_sealed": True,
    }
    split = {
        **split_core,
        "split_version_id": "split-m3-fixture",
        "split_version_digest": _digest(split_core),
    }
    coverage_core = {
        "schema_version": CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "dataset_version_id": dataset["dataset_version_id"],
        "dataset_version_digest": dataset["dataset_version_digest"],
        "partitions": _coverage(records),
    }
    coverage = {**coverage_core, "coverage_digest": _digest(coverage_core)}
    receipt_core = {
        "schema_version": CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
        "receipt_type": "cardeventnet_dataset_freeze",
        "operator": "fixture",
        "inputs": [],
        "outputs": [],
    }
    receipt = {
        **receipt_core,
        "receipt_id": "receipt-m3-fixture",
        "receipt_digest": _digest(receipt_core),
    }
    dataset_dir = operations / "cardevent-datasets" / str(dataset["dataset_version_id"])
    for name, payload in (
        ("dataset.json", dataset),
        ("split.json", split),
        ("coverage.json", coverage),
        ("receipt.json", receipt),
    ):
        _write_json(dataset_dir / name, payload)

    readiness_items = []
    for record in records:
        recording_id = str(record["recording_id"])
        new_root = revision_root / f"new-{recording_id}"
        readiness_items.append(
            {
                "recording_id": recording_id,
                "partition": record["partition"],
                "classification": (
                    "diagnostic_only" if recording_id == "cardeventnet-IMG_2777" else "eligible"
                ),
                "decision": (
                    "legacy_device_diagnostic"
                    if recording_id == "cardeventnet-IMG_2777"
                    else "interval_reviewed"
                ),
                "selected_revision_id": f"new-{recording_id}",
                "revision_manifest_sha256": _sha256((new_root / "manifest.json").read_bytes()),
                "revision_content_sha256": _sha256((new_root / "content.json").read_bytes()),
                "point_count": 1,
                "interval_count": 1,
                "event_count": 2,
                "reviewed_coverage_complete": True,
                "reviewed_duration_us": 4_000_000,
                "blockers": [],
            }
        )
    exclusion = {
        "schema_version": "legacy-device-exclusion/v1",
        "receipt_digest": "c" * 64,
        "sources": [{"recording_id": "cardeventnet-IMG_2777"}],
    }
    readiness_core = {
        "schema_version": "cardeventnet-interval-readiness/v1",
        "state": "ready",
        "global_blockers": [],
        "blocked_recordings": [],
        "recordings": readiness_items,
        "exclusion": {"receipt_digest": exclusion["receipt_digest"]},
    }
    readiness = {**readiness_core, "report_digest": _digest(readiness_core)}
    readiness_path = operations / "cardeventnet-interval-readiness" / "report.json"
    _write_json(readiness_path, readiness)
    exclusion_path = operations / "source-exclusions" / "legacy-device-diagnostic.json"
    _write_json(exclusion_path, exclusion)

    monkeypatch.setattr(
        "doko_operations.cardevent_interval_dataset.read_legacy_device_exclusion",
        lambda repository, path: (exclusion, _sha256(exclusion_path.read_bytes())),
    )
    return dataset_dir, readiness_path, exclusion_path


def _write_cache(view: Path, recording_id: str) -> None:
    _write_json(
        view / "cache" / recording_id / "metadata.json",
        {
            "source_video": f"{recording_id}.mov",
            "cache_fps": 10.0,
            "duration_s": 4.0,
            "frame_timestamps_s": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
        },
    )


def test_interval_freeze_filters_diagnostics_and_sampling_is_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_dir, readiness_path, _ = _fixture(tmp_path, monkeypatch)
    result = freeze_cardeventnet_interval_dataset(
        tmp_path,
        operator="epic-0063-m7",
        baseline_dataset_path=baseline_dir,
        interval_readiness_path=readiness_path,
    )

    assert result["partition_counts"] == {"train": 1, "validation": 1, "test": 1}
    dataset_dir = tmp_path / result["path"]
    dataset = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    split = json.loads((dataset_dir / "split.json").read_text(encoding="utf-8"))
    assert "cardeventnet-IMG_2777" not in {item["recording_id"] for item in dataset["entries"]}
    assert split["validation"] == ["recording-b"]
    assert dataset["test_sealed"] is True
    assert dataset["lineage"]["diagnostic_exclusion"]["receipt_digest"] == "c" * 64

    baseline_view = tmp_path / ".runtime" / "m3"
    for recording_id in ("recording-a", "recording-b", "recording-c", "cardeventnet-IMG_2777"):
        _write_cache(baseline_view, recording_id)
    view = materialize_cardeventnet_dataset(
        dataset_dir,
        repository_root=tmp_path,
        cache_source_root=baseline_view,
    )
    report = build_cardeventnet_interval_sampling_report(
        tmp_path,
        dataset_path=dataset_dir,
        materialized_view_path=view.view_root,
        baseline_dataset_path=baseline_dir,
        baseline_view_path=baseline_view,
    )
    rebuilt = materialize_cardeventnet_dataset(
        dataset_dir,
        repository_root=tmp_path,
        cache_source_root=baseline_view,
    )
    rebuilt_report = build_cardeventnet_interval_sampling_report(
        tmp_path,
        dataset_path=dataset_dir,
        materialized_view_path=rebuilt.view_root,
        baseline_dataset_path=baseline_dir,
        baseline_view_path=baseline_view,
    )

    assert report == rebuilt_report
    assert report["sampling_policy"]["version"] == "stable-end-anchor-v1"
    assert report["partitions"]["train"]["interval_targets"] == 1
    assert report["partitions"]["train"]["positive_samples"] > 0
    assert report["partitions"]["train"]["ignored_interval_samples"] > 0
    assert report["comparison"]["changed_recordings"] == [
        "cardeventnet-IMG_2777",
        "recording-a",
        "recording-b",
        "recording-c",
    ]
    annotation = json.loads(
        (view.view_root / "annotations" / "recording-a.json").read_text(encoding="utf-8")
    )
    assert annotation["events"][1]["start_s"] == 2.0
    assert annotation["events"][1]["end_s"] == 3.0


def test_interval_freeze_rejects_non_ready_m6_report(tmp_path: Path, monkeypatch) -> None:
    baseline_dir, readiness_path, _ = _fixture(tmp_path, monkeypatch)
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["state"] = "blocked"
    readiness["report_digest"] = _digest(
        {key: value for key, value in readiness.items() if key != "report_digest"}
    )
    _write_json(readiness_path, readiness)

    with pytest.raises(CardEventNetIntervalDatasetError, match="M6 interval readiness is blocked"):
        freeze_cardeventnet_interval_dataset(
            tmp_path,
            operator="epic-0063-m7",
            baseline_dataset_path=baseline_dir,
            interval_readiness_path=readiness_path,
        )
