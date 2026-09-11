from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from doko_operations.cardevent_dataset import (
    CardEventNetDatasetFreezeError,
    build_cardeventnet_freeze_report,
    freeze_cardeventnet_dataset,
)


def test_freeze_preflight_reports_exact_test_and_group_gaps() -> None:
    readiness = {"report_digest": "a" * 64, "recordings": [_record("recording-a")]}
    split = _split(train=["recording-a"], validation=[], test=[], unassigned=[])

    report = build_cardeventnet_freeze_report(readiness, split)

    assert report["state"] == "blocked"
    assert "validation partition is empty" in report["blockers"]
    assert (
        "independent sealed test source-lineage group is required; collect, migrate, annotate, "
        "and assign a new group to test"
    ) in report["blockers"]

    missing_lineage = dict(_record("recording-a"))
    missing_lineage["source_metadata"] = {
        **missing_lineage["source_metadata"],
        "source_lineage": None,
    }
    missing_lineage["group_keys"] = [
        ["session_id", "session-1"],
        ["table_setup", "table-recording-a"],
    ]
    report = build_cardeventnet_freeze_report(
        {"report_digest": "a" * 64, "recordings": [missing_lineage]},
        split,
    )
    assert "recording recording-a is missing group metadata: source_lineage" in report[
        "blockers"
    ]


def test_freeze_preflight_rejects_group_crossing_and_accepts_three_independent_partitions() -> None:
    records = [
        _record("recording-a", session_id="session-development"),
        _record("recording-b", session_id="session-development"),
        _record("recording-c", session_id="session-test"),
    ]
    readiness = {"report_digest": "a" * 64, "recordings": records}

    blocked = build_cardeventnet_freeze_report(
        readiness,
        _split(train=["recording-a"], validation=["recording-b"], test=["recording-c"]),
    )
    assert blocked["state"] == "blocked"
    assert any(
        "split crosses leakage group session_id:session-development" in item
        for item in blocked["blockers"]
    )

    ready = build_cardeventnet_freeze_report(
        readiness,
        _split(train=["recording-a"], validation=["recording-b"], test=["recording-c"]),
    )
    records[1]["source_metadata"] = {
        **records[1]["source_metadata"],
        "session_id": "session-validation",
    }
    records[1]["group_keys"] = _group_keys(records[1]["source_metadata"])
    ready = build_cardeventnet_freeze_report(
        {"report_digest": "a" * 64, "recordings": records},
        _split(train=["recording-a"], validation=["recording-b"], test=["recording-c"]),
    )
    assert ready["state"] == "ready"
    assert ready["test_sealed"] is True
    assert {item["partition"] for item in ready["entries"]} == {
        "train",
        "validation",
        "test",
    }


def test_freeze_publication_is_immutable_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    report = {
        "state": "ready",
        "readiness_digest": "a" * 64,
        "split": {
            "split_version_id": "split-1",
            "split_version_digest": "b" * 64,
            "partitions": {
                "train": ["recording-a"],
                "validation": ["recording-b"],
                "test": ["recording-c"],
                "unassigned": [],
            },
        },
        "entries": [
            {
                "recording_id": "recording-a",
                "partition": "train",
                "event_count": 1,
                "duration_us": 10,
            },
            {
                "recording_id": "recording-b",
                "partition": "validation",
                "event_count": 1,
                "duration_us": 10,
            },
            {
                "recording_id": "recording-c",
                "partition": "test",
                "event_count": 1,
                "duration_us": 10,
            },
        ],
        "coverage": {
            "train": {"recording_ids": ["recording-a"]},
            "validation": {"recording_ids": ["recording-b"]},
            "test": {"recording_ids": ["recording-c"]},
        },
    }
    monkeypatch.setattr(
        "doko_operations.cardevent_dataset.build_cardeventnet_freeze",
        lambda *args, **kwargs: report,
    )

    first = freeze_cardeventnet_dataset(tmp_path, operator="operator")
    second = freeze_cardeventnet_dataset(tmp_path, operator="operator")

    assert first == second
    dataset_dir = tmp_path / first["path"]
    assert (dataset_dir / "dataset.json").is_file()
    assert (dataset_dir / "split.json").is_file()
    assert (dataset_dir / "coverage.json").is_file()
    assert (dataset_dir / "receipt.json").is_file()

    with pytest.raises(CardEventNetDatasetFreezeError):
        freeze_cardeventnet_dataset(tmp_path, operator="another-operator")


def _record(recording_id: str, *, session_id: str = "session-1") -> dict[str, object]:
    source_metadata = {
        "allowed_uses": ["train", "validation", "test"],
        "content_type": "staged_trick_sequence",
        "retention_state": "active",
        "session_id": session_id,
        "source_lineage": f"lineage-{recording_id}",
        "table_setup": f"table-{recording_id}",
    }
    return {
        "recording_id": recording_id,
        "primary_state": "review_complete",
        "blockers": [],
        "source_sha256": hashlib.sha256(recording_id.encode()).hexdigest(),
        "source_path": f"videos/{recording_id}.mov",
        "source_exists": True,
        "source_metadata": source_metadata,
        "group_keys": _group_keys(source_metadata),
        "allowed_partitions": ["train", "validation", "test"],
        "source_permission": "training_and_evaluation",
        "retention_state": "active",
        "review_progress": {"coverage_complete": True},
        "event_revision": {
            "revision_id": f"revision-{recording_id}",
            "source_sha256": hashlib.sha256(recording_id.encode()).hexdigest(),
            "duration_us": 10,
        },
    }


def _split(
    *,
    train: list[str],
    validation: list[str] | None = None,
    test: list[str],
    unassigned: list[str] | None = None,
) -> dict[str, object]:
    return {
        "split_version_id": "split-1",
        "split_version_digest": "b" * 64,
        "train": train,
        "validation": validation or [],
        "test": test,
        "unassigned": unassigned or [],
    }


def _group_keys(source: dict[str, object]) -> list[list[str]]:
    return [
        [name, source[name]]
        for name in ("session_id", "source_lineage", "table_setup")
        if isinstance(source.get(name), str)
    ]
