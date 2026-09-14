from __future__ import annotations

import hashlib
import json
from pathlib import Path

from doko_operations.cardevent_dataset import (
    CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
    CARD_EVENTNET_DATASET_SCHEMA_VERSION,
    CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
    CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
    _coverage,
    _digest,
)
from doko_operations.cardevent_materialization import materialize_cardeventnet_dataset


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_frozen_dataset(root: Path) -> Path:
    entries: list[dict[str, object]] = []
    for index, partition in enumerate(("train", "validation", "test"), start=1):
        recording_id = f"recording-{partition}"
        source_path = (
            root
            / "data"
            / "intake"
            / "recordings"
            / recording_id
            / "videos"
            / f"video-{recording_id}.mov"
        )
        source_bytes = f"source-{recording_id}".encode()
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(source_bytes)
        content = {
            "events": [
                {
                    "end_us": index * 1_000_000,
                    "event_id": f"event-{recording_id}",
                    "event_type": "card_state_changed",
                    "start_us": index * 1_000_000 - (250_000 if index == 2 else 0),
                }
            ]
        }
        revision_root = root / "data" / "operations" / "pipeline" / "revisions" / recording_id
        revision_root.mkdir(parents=True, exist_ok=True)
        content_bytes = (json.dumps(content, separators=(",", ":")) + "\n").encode()
        content_path = revision_root / "content.json"
        content_path.write_bytes(content_bytes)
        manifest_bytes = b'{"content_type":"events"}\n'
        manifest_path = revision_root / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        entries.append(
            {
                "recording_id": recording_id,
                "source_path": source_path.relative_to(root).as_posix(),
                "source_sha256": _sha256(source_bytes),
                "event_revision_manifest_path": manifest_path.relative_to(root).as_posix(),
                "event_revision_manifest_sha256": _sha256(manifest_bytes),
                "event_revision_content_path": content_path.relative_to(root).as_posix(),
                "event_revision_content_sha256": _sha256(content_bytes),
                "event_count": 1,
                "duration_us": 10_000_000,
                "partition": partition,
                "group_keys": [["session_id", f"session-{recording_id}"]],
            }
        )

    dataset_core = {
        "schema_version": CARD_EVENTNET_DATASET_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "readiness_digest": _sha256(b"readiness"),
        "split_version_id": "development-split-placeholder",
        "split_version_digest": _sha256(b"development-split-placeholder"),
        "test_sealed": True,
        "entries": entries,
    }
    dataset_digest = _digest(dataset_core)
    dataset = {
        **dataset_core,
        "dataset_version_id": "dataset-materialization-fixture",
        "dataset_version_digest": dataset_digest,
    }
    split_core = {
        "schema_version": CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "dataset_version_id": dataset["dataset_version_id"],
        "dataset_version_digest": dataset_digest,
        "group_key_names": ["session_id"],
        "train": ["recording-train"],
        "validation": ["recording-validation"],
        "test": ["recording-test"],
        "unassigned": [],
        "test_sealed": True,
    }
    split_digest = _digest(split_core)
    split = {
        **split_core,
        "split_version_id": "split-materialization-fixture",
        "split_version_digest": split_digest,
    }
    split["dataset_version_digest"] = dataset_digest
    coverage_core = {
        "schema_version": CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "dataset_version_id": dataset["dataset_version_id"],
        "dataset_version_digest": dataset_digest,
        "partitions": _coverage(entries),
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
        "receipt_id": "receipt-materialization-fixture",
        "receipt_digest": _digest(receipt_core),
    }
    dataset_dir = (
        root / "data" / "operations" / "cardevent-datasets" / dataset["dataset_version_id"]
    )
    dataset_dir.mkdir(parents=True)
    for name, payload in (
        ("dataset.json", dataset),
        ("split.json", split),
        ("coverage.json", coverage),
        ("receipt.json", receipt),
    ):
        (dataset_dir / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return dataset_dir


def test_materialization_rebuild_is_deterministic_and_loadable(tmp_path: Path) -> None:
    dataset_dir = _write_frozen_dataset(tmp_path)
    first = materialize_cardeventnet_dataset(dataset_dir, repository_root=tmp_path)
    first_manifest = (first.view_root / "materialization.json").read_bytes()

    second = materialize_cardeventnet_dataset(dataset_dir, repository_root=tmp_path)

    assert first.manifest_digest == second.manifest_digest
    assert first_manifest == (second.view_root / "materialization.json").read_bytes()
    assert (second.view_root / "videos" / "recording-train.mov").is_symlink()
    assert (second.view_root / "annotations" / "recording-validation.json").read_text(
        encoding="utf-8"
    ).find('"start_s": 1.75') >= 0
    assert '"time_s": 2.0' in (
        second.view_root / "annotations" / "recording-validation.json"
    ).read_text(encoding="utf-8")
    manifest = json.loads((second.view_root / "materialization.json").read_text(encoding="utf-8"))
    assert manifest["event_target_policy"] == {
        "version": "stable-end-anchor-v1",
        "anchor": "end_us",
        "interval_interior": "exclude_from_negative_evidence",
    }
    assert (second.view_root / "split.yaml").read_text(encoding="utf-8") == (
        "train:\n- recording-train\nval:\n- recording-validation\ntest:\n- recording-test\n"
    )


def test_materialization_rebuild_preserves_disposable_cache(tmp_path: Path) -> None:
    dataset_dir = _write_frozen_dataset(tmp_path)
    first = materialize_cardeventnet_dataset(dataset_dir, repository_root=tmp_path)
    marker = first.view_root / "cache" / "recording-train" / "marker.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("cache retained\n", encoding="utf-8")

    second = materialize_cardeventnet_dataset(dataset_dir, repository_root=tmp_path)

    assert (second.view_root / "cache" / "recording-train" / "marker.txt").read_text(
        encoding="utf-8"
    ) == "cache retained\n"


def test_materialization_replaces_changed_derived_files(tmp_path: Path) -> None:
    dataset_dir = _write_frozen_dataset(tmp_path)
    result = materialize_cardeventnet_dataset(dataset_dir, repository_root=tmp_path)
    annotation = result.view_root / "annotations" / "recording-train.json"
    annotation.write_text("{}\n", encoding="utf-8")

    rebuilt = materialize_cardeventnet_dataset(dataset_dir, repository_root=tmp_path)

    assert rebuilt.manifest_digest == result.manifest_digest
    assert '"card_state_changed"' in annotation.read_text(encoding="utf-8")
