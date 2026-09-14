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
from doko_operations.cardevent_interval_pilot import (
    CardEventNetIntervalPilotError,
    run_cardeventnet_interval_pilot,
)
from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    ImportProducer,
    RecordingVideoSource,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_base_revision(root: Path, recording_id: str, *, partition: str) -> dict[str, object]:
    source_path = root / "data" / "intake" / "recordings" / recording_id / "videos" / "video.mov"
    source_bytes = f"video-{recording_id}".encode()
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_bytes)
    source = RecordingVideoSource(
        recording_id=recording_id,
        relative_path=source_path.relative_to(root).as_posix(),
        video_sha256=_sha256(source_bytes),
        byte_length=len(source_bytes),
        duration_us=10_000_000,
    )
    content = EventData.from_mapping(
        {
            "schema_version": "event-data/v1",
            "events": [
                {
                    "event_id": f"point-{recording_id}",
                    "event_type": "card_state_changed",
                    "start_us": 2_000_000,
                    "end_us": 2_000_000,
                }
            ],
        },
        duration_us=source.duration_us,
    )
    content_bytes = canonical_event_data_bytes(content)
    manifest = DataRevision.from_mapping(
        {
            "schema_version": "data-revision/v1",
            "revision_id": f"base-{recording_id}",
            "content_type": "events",
            "content_schema": "event-data/v1",
            "recording_id": recording_id,
            "source": source.to_mapping(),
            "content_sha256": _sha256(content_bytes),
            "input_revision_ids": [],
            "origin": "processor",
            "producer": ImportProducer(
                run_id=f"import-{recording_id}",
                artifact_id=f"artifact-{recording_id}",
                artifact_sha256=_sha256(b"legacy-annotation"),
                source_schema="cardevent-annotation/v2",
            ).to_mapping(),
            "coverage": {"kind": "full_recording", "duration_us": source.duration_us},
            "created_at": "2026-09-13T00:00:00Z",
        }
    )
    revision_root = (
        root
        / "data"
        / "operations"
        / "pipeline"
        / "revisions"
        / recording_id
        / manifest.revision_id
    )
    manifest_bytes = canonical_data_revision_bytes(manifest)
    _write_json_bytes(revision_root / "manifest.json", manifest_bytes)
    _write_json_bytes(revision_root / "content.json", content_bytes)
    return {
        "recording_id": recording_id,
        "source_path": source.relative_path,
        "source_sha256": source.video_sha256,
        "event_revision_manifest_path": revision_root.joinpath("manifest.json")
        .relative_to(root)
        .as_posix(),
        "event_revision_manifest_sha256": _sha256(manifest_bytes),
        "event_revision_content_path": revision_root.joinpath("content.json")
        .relative_to(root)
        .as_posix(),
        "event_revision_content_sha256": _sha256(content_bytes),
        "event_count": 1,
        "duration_us": source.duration_us,
        "partition": partition,
        "group_keys": [["session_id", f"session-{recording_id}"]],
        "review_coverage": {"coverage_complete": True},
        "task": "cardevent_event_detection",
    }


def _write_json_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _write_dataset(root: Path) -> Path:
    entries = [
        _write_base_revision(root, "pilot-train", partition="train"),
        _write_base_revision(root, "pilot-validation", partition="validation"),
        _write_base_revision(root, "pilot-test", partition="test"),
    ]
    dataset_core = {
        "schema_version": CARD_EVENTNET_DATASET_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "readiness_digest": _sha256(b"readiness-0063"),
        "split_version_id": "split-0063",
        "split_version_digest": _sha256(b"split-0063"),
        "test_sealed": True,
        "entries": entries,
    }
    dataset_digest = _digest(dataset_core)
    dataset = {
        **dataset_core,
        "dataset_version_id": "cardeventnet-dataset-0063-fixture",
        "dataset_version_digest": dataset_digest,
    }
    split_core = {
        "schema_version": CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
        "task": "cardevent_event_detection",
        "dataset_version_id": dataset["dataset_version_id"],
        "dataset_version_digest": dataset_digest,
        "group_key_names": ["session_id"],
        "train": ["pilot-train"],
        "validation": ["pilot-validation"],
        "test": ["pilot-test"],
        "unassigned": [],
        "test_sealed": True,
    }
    split_digest = _digest(split_core)
    split = {
        **split_core,
        "split_version_id": "split-0063-fixture",
        "split_version_digest": split_digest,
    }
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
        "receipt_id": "receipt-0063-fixture",
        "receipt_digest": _digest(receipt_core),
    }
    dataset_dir = (
        root
        / "data"
        / "operations"
        / "cardevent-datasets"
        / dataset["dataset_version_id"]
    )
    for name, payload in (
        ("dataset.json", dataset),
        ("split.json", split),
        ("coverage.json", coverage),
        ("receipt.json", receipt),
    ):
        _write_json(dataset_dir / name, payload)
    return dataset_dir


def _write_review(root: Path, dataset_dir: Path) -> Path:
    dataset = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    entry = next(item for item in dataset["entries"] if item["recording_id"] == "pilot-train")
    review = {
        "schema_version": "cardeventnet-interval-pilot-request/v1",
        "pilot_id": "pilot-0066-m4-fixture",
        "recording_id": "pilot-train",
        "operator_id": "reviewer-01",
        "reviewed_revision_id": "reviewed-pilot-train-01",
        "created_at": "2026-09-14T00:00:00Z",
        "base_revision": {
            "revision_id": "base-pilot-train",
            "manifest_sha256": entry["event_revision_manifest_sha256"],
            "content_sha256": entry["event_revision_content_sha256"],
        },
        "coverage": {
            "kind": "full_recording",
            "intervals": [{"start_us": 0, "end_us": 10_000_000}],
        },
        "events": [
            {
                "event_id": "point-pilot-train",
                "event_type": "card_state_changed",
                "start_us": 2_000_000,
                "end_us": 2_000_000,
            },
            {
                "event_id": "trick-clear-01",
                "event_type": "card_state_changed",
                "start_us": 3_000_000,
                "end_us": 4_250_000,
            },
        ],
        "interval_evidence": [
            {
                "event_id": "trick-clear-01",
                "source_frames": [
                    {"frame_id": "frame-start-01", "role": "start", "time_us": 3_000_000},
                    {
                        "frame_id": "frame-end-01",
                        "role": "stable_end",
                        "time_us": 4_250_000,
                    },
                ],
            }
        ],
        "candidates": [
            {
                "candidate_id": "candidate-missed-01",
                "kind": "missed_hard_negative",
                "decision": "missed_event",
                "event_id": "trick-clear-01",
                "source_frames": [
                    {"frame_id": "frame-start-01", "time_us": 3_000_000},
                    {"frame_id": "frame-end-01", "time_us": 4_250_000},
                ],
            },
            {
                "candidate_id": "candidate-no-event-01",
                "kind": "uncertain",
                "decision": "no_event",
                "source_frames": [{"frame_id": "frame-no-event-01", "time_us": 8_000_000}],
            },
        ],
        "predictions": [
            {"prediction_id": "prediction-in-progress", "time_s": 3.5},
            {"prediction_id": "prediction-stable-end", "time_s": 4.25},
            {"prediction_id": "prediction-no-event", "time_s": 8.0},
        ],
    }
    path = root / "pilot-review.json"
    _write_json(path, review)
    return path


def _write_sampling_reports(root: Path) -> tuple[Path, Path]:
    baseline = {
        "available": {"positive": 10, "ordinary_negative": 30, "ignore": 4, "total": 44},
        "selected": {"positive": 10, "ordinary_negative": 30, "ignore": 0, "total": 40},
    }
    pilot = {
        "available": {"positive": 10, "ordinary_negative": 25, "ignore": 9, "total": 44},
        "selected": {"positive": 10, "ordinary_negative": 25, "ignore": 0, "total": 35},
    }
    baseline_path = root / "sampling-0063.json"
    pilot_path = root / "sampling-pilot.json"
    _write_json(baseline_path, baseline)
    _write_json(pilot_path, pilot)
    return baseline_path, pilot_path


def test_interval_pilot_publishes_lineage_and_keeps_0063_immutable(tmp_path: Path) -> None:
    dataset_dir = _write_dataset(tmp_path)
    review_path = _write_review(tmp_path, dataset_dir)
    baseline_sampling, pilot_sampling = _write_sampling_reports(tmp_path)
    before = {
        name: (dataset_dir / name).read_bytes()
        for name in ("dataset.json", "split.json", "coverage.json", "receipt.json")
    }

    report = run_cardeventnet_interval_pilot(
        tmp_path,
        baseline_dataset_path=dataset_dir,
        review_path=review_path,
        output_root=tmp_path / ".runtime" / "cardevent" / "interval-pilot",
        baseline_sampling_report_path=baseline_sampling,
        pilot_sampling_report_path=pilot_sampling,
    )

    assert report["review"]["coverage"]["coverage_complete"] is True
    assert report["review"]["interval_count"] == 1
    assert report["review"]["ambiguous_hard_negative_candidates"] == {
        "input": 2,
        "interval_resolved": 1,
        "confirmed_no_event": 1,
        "remaining_uncertain": 0,
        "reduced_by": 1,
    }
    assert report["review"]["source_frame_evidence"][0]["source_frames"][0]["role"] == "start"
    assert report["reviewed_revision"]["base_revision_id"] == "base-pilot-train"
    assert report["pilot_dataset"]["dataset_version_id"].startswith("cardeventnet-interval-pilot-")
    assert report["sampling_comparison"]["available_delta"]["ignore"] == 5
    assert report["diagnostics"]["counts"] == {
        "stable_end_match": 1,
        "in_progress_trick_clear": 1,
        "confirmed_no_event_trigger": 1,
    }
    assert report["frozen_0063_artifacts"]["all_unchanged"] is True
    assert {
        name: (dataset_dir / name).read_bytes()
        for name in before
    } == before
    assert (tmp_path / ".runtime" / "cardevent" / "interval-pilot" / "report.json").is_file()
    assert (
        tmp_path
        / ".runtime"
        / "cardevent"
        / "interval-pilot"
        / "view"
        / "annotations"
        / "pilot-train.json"
    ).is_file()


def test_interval_pilot_rejects_test_recording(tmp_path: Path) -> None:
    dataset_dir = _write_dataset(tmp_path)
    review_path = _write_review(tmp_path, dataset_dir)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["recording_id"] = "pilot-test"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    baseline_sampling, pilot_sampling = _write_sampling_reports(tmp_path)

    try:
        run_cardeventnet_interval_pilot(
            tmp_path,
            baseline_dataset_path=dataset_dir,
            review_path=review_path,
            output_root=tmp_path / ".runtime" / "cardevent" / "interval-pilot",
            baseline_sampling_report_path=baseline_sampling,
            pilot_sampling_report_path=pilot_sampling,
        )
    except CardEventNetIntervalPilotError as error:
        assert "sealed test" in str(error)
    else:
        raise AssertionError("the pilot must not change the sealed test partition")
