from __future__ import annotations

import hashlib
import json
from pathlib import Path

from table_evidence_analyzer.export import BUNDLE_SCHEMA
from table_evidence_analyzer.visible_card_batch import (
    VisibleCardBatchConfig,
    run_visible_card_batch,
)


def _evidence_fixture(root: Path) -> Path:
    package_id = "package-001"
    package_root = root / package_id
    frames_root = package_root / "frames"
    frames_root.mkdir(parents=True)
    (frames_root / "frame_00.jpg").write_bytes(b"P6\n4 4\n255\n" + bytes([240, 20, 20] * 16))
    (package_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "cardevent-evidence/v2",
                "frames": [
                    {
                        "part_name": "frame_00",
                        "target_offset_ms": 0,
                        "actual_offset_ms": 0,
                        "width": 4,
                        "height": 4,
                    }
                ],
                "event": {"event_time_ms": 1234},
                "session": {"session_id": "session-001", "event_sequence": 1},
            }
        ),
        encoding="utf-8",
    )
    (root / "extraction-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "annotation-evidence-extraction/v1",
                "packages": [{"package_id": package_id, "relative_path": package_id}],
            }
        ),
        encoding="utf-8",
    )
    return root


def _write_bundle(root: Path) -> Path:
    bundle = root / "bundle"
    bundle.mkdir()
    model = bundle / "model.json"
    model.write_text(
        json.dumps(
            {
                "schema_version": "rgb-nearest-centroid-v1",
                "centroids": {"CLUBS_NINE": [240.0, 20.0, 20.0]},
            }
        ),
        encoding="utf-8",
    )
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": BUNDLE_SCHEMA,
                "capabilities": ["identity_candidates"],
                "calibration": "uncalibrated",
                "card_set_version": "doko-german-suited-v1",
                "run_id": "run-001",
                "dataset_version_digest": "dataset-digest",
                "split_version_digest": "split-digest",
                "model_file": "model.json",
                "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return bundle


def _prediction_file(root: Path, image: bytes) -> Path:
    prediction = root / "prediction.json"
    prediction.write_text(
        json.dumps(
            {
                hashlib.sha256(image).hexdigest(): {
                    "cards": [
                        {
                            "box_2d": {"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
                            "polygon": [
                                {"x": 0, "y": 0},
                                {"x": 1000, "y": 0},
                                {"x": 1000, "y": 1000},
                                {"x": 0, "y": 1000},
                            ],
                            "side": "face_up",
                            "label": "ignored provider label",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return prediction


def test_visible_card_batch_is_local_and_resumable(tmp_path: Path) -> None:
    evidence_root = _evidence_fixture(tmp_path / "evidence")
    output_dir = tmp_path / "batch"
    config = VisibleCardBatchConfig(
        evidence_root=evidence_root,
        output_dir=output_dir,
        cache_dir=tmp_path / "cache",
    )

    report = run_visible_card_batch(config)

    assert report["status"] == "completed"
    assert report["package_count"] == 1
    assert report["result_count"] == 1
    assert report["failure_count"] == 0
    assert report["status_counts"] == {"ok": 1, "unavailable": 0}
    result_path = Path(report["results"][0]["result"])
    assert json.loads(result_path.read_text(encoding="utf-8"))["prediction"] == {"cards": []}

    resumed = run_visible_card_batch(
        VisibleCardBatchConfig(
            evidence_root=evidence_root,
            output_dir=output_dir,
            cache_dir=tmp_path / "cache",
            resume=True,
        )
    )

    assert resumed["resumed_result_count"] == 1
    assert resumed["result_count"] == 1
    assert json.loads((output_dir / "batch-state.json").read_text())["status"] == "completed"


def test_visible_card_batch_can_emit_table_observations(tmp_path: Path) -> None:
    evidence_root = _evidence_fixture(tmp_path / "evidence")
    image = (evidence_root / "package-001" / "frames" / "frame_00.jpg").read_bytes()
    output_dir = tmp_path / "batch-with-observations"

    report = run_visible_card_batch(
        VisibleCardBatchConfig(
            evidence_root=evidence_root,
            output_dir=output_dir,
            cache_dir=tmp_path / "cache",
            fake_prediction=_prediction_file(tmp_path, image),
            identity_bundle=_write_bundle(tmp_path),
        )
    )

    assert report["observation_count"] == 1
    observation_path = Path(report["results"][0]["observation"])
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    assert observation["schema_version"] == "table-observation/v1"
    assert observation["session"] == {"session_id": "session-001", "event_sequence": 1}
    assert observation["cards"][0]["identity_candidates"][0]["card"] == "CLUBS_NINE"
