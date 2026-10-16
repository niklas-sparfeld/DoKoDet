from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_0092_m4_refit.py"
SPEC = importlib.util.spec_from_file_location("prepare_0092_m4_refit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
prepare_m4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_m4)


def _source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "m1"
    manifest_path = tmp_path / "m0.json"
    recording_ids = [f"recording-{index:02d}" for index in range(20)]
    partitions = {
        "train": recording_ids[:16],
        "validation": recording_ids[16:18],
        "sealed_test": recording_ids[18:],
    }
    manifest = {
        "campaign_id": "0092-m0-expanded-reviewed-rfdetr-campaign",
        "manifest_sha256": "frozen-m0-digest",
        "partitions": {
            name: {"recordings": [{"recording_id": item} for item in ids]}
            for name, ids in partitions.items()
        },
    }
    manifest_path.write_text(json.dumps(manifest))
    split = {name: ids for name, ids in partitions.items()}
    (source / "split.json").parent.mkdir(parents=True)
    (source / "split.json").write_text(json.dumps(split))
    (source / "exclusions.json").write_text("{}")
    (source / "materialization.json").write_text(
        json.dumps(
            {
                "campaign_manifest": {"manifest_digest": "frozen-m0-digest"},
                "materialization_digest": "frozen-m1-digest",
                "counts": {"images": 20, "annotations": 20},
            }
        )
    )

    for partition_name, ids in partitions.items():
        directory = "valid" if partition_name == "validation" else partition_name
        images = []
        annotations = []
        for index, recording_id in enumerate(ids):
            file_name = f"images/{recording_id}.jpg"
            images.append(
                {
                    "id": index + 1,
                    "file_name": file_name,
                    "recording_id": recording_id,
                    "event_id": f"event-{recording_id}",
                    "width": 10,
                    "height": 10,
                }
            )
            annotations.append({"id": index + 1, "image_id": index + 1})
            image_path = source / directory / file_name
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(recording_id.encode())
        coco = {
            "images": images,
            "annotations": annotations,
            "categories": [{"id": 1, "name": "visible_card"}],
        }
        (source / directory / "_annotations.coco.json").write_text(json.dumps(coco))
    return source, manifest_path


def test_m4_view_trains_and_monitors_on_all_twenty_recordings(tmp_path: Path) -> None:
    source, manifest = _source(tmp_path)
    output = tmp_path / "m4"

    receipt = prepare_m4.prepare(tmp_path, source, output, manifest)

    train = json.loads((output / "train/_annotations.coco.json").read_text())
    valid = json.loads((output / "valid/_annotations.coco.json").read_text())
    trained_ids = {image["recording_id"] for image in train["images"]}
    monitored_ids = {image["recording_id"] for image in valid["images"]}
    assert trained_ids == monitored_ids == set(receipt["recording_ids"])
    assert len(train["images"]) == len(valid["images"]) == 20
    assert len(train["annotations"]) == len(valid["annotations"]) == 20
    assert receipt["recording_count"] == 20
    assert receipt["training_frame_count"] == 20
    assert receipt["training_annotation_count"] == 20
    assert receipt["in_sample_monitoring"] is True
    assert receipt["sealed_test_evaluation"] is False


def test_m4_view_rejects_a_split_that_omits_a_frozen_recording(tmp_path: Path) -> None:
    source, manifest = _source(tmp_path)
    split_path = source / "split.json"
    split = json.loads(split_path.read_text())
    split["sealed_test"].pop()
    split_path.write_text(json.dumps(split))
    output = tmp_path / "m4"

    with pytest.raises(ValueError, match="exactly the 20 frozen M0 recordings"):
        prepare_m4.prepare(tmp_path, source, output, manifest)

    assert not output.exists()
