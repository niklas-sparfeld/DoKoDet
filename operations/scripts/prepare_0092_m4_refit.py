#!/usr/bin/env python3
"""Build the isolated all-recording training view for the 0092 M4 refit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def prepare(repository: Path, source: Path, output: Path, manifest_path: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    m0 = json.loads(manifest_path.read_text())
    materialization = json.loads((source / "materialization.json").read_text())
    split = json.loads((source / "split.json").read_text())
    if m0.get("campaign_id") != "0092-m0-expanded-reviewed-rfdetr-campaign":
        raise ValueError("M0 manifest is not the frozen 0092 campaign")
    if materialization.get("campaign_manifest", {}).get("manifest_digest") != m0.get(
        "manifest_sha256"
    ):
        raise ValueError("M1 materialization does not reference the frozen M0 manifest")

    all_recordings = [
        row["recording_id"]
        for partition in ("train", "validation", "sealed_test")
        for row in m0["partitions"][partition]["recordings"]
    ]
    if len(all_recordings) != 20 or len(set(all_recordings)) != 20:
        raise ValueError("frozen M0 does not contain the expected 20 distinct recordings")
    if set(all_recordings) != set(split["train"] + split["validation"] + split["sealed_test"]):
        raise ValueError("M1 split does not contain exactly the 20 frozen M0 recordings")

    output.mkdir(parents=True)
    coco_by_split: dict[str, dict[str, Any]] = {}
    for partition in ("train", "valid", "sealed_test"):
        source_partition = "validation" if partition == "valid" else partition
        coco = json.loads((source / partition / "_annotations.coco.json").read_text())
        coco_by_split[source_partition] = coco
        for image in coco["images"]:
            file_name = Path(image["file_name"])
            if file_name.is_absolute() or ".." in file_name.parts:
                raise ValueError("M1 COCO image path is unsafe")
            source_image = source / partition / file_name
            _link_or_copy(source_image, output / "train" / file_name)
            _link_or_copy(source_image, output / "valid" / file_name)
            if partition == "sealed_test":
                _link_or_copy(source_image, output / partition / file_name)

    all_images: list[dict[str, Any]] = []
    all_annotations: list[dict[str, Any]] = []
    for partition in ("train", "validation", "sealed_test"):
        coco = coco_by_split[partition]
        all_images.extend(dict(image, split="train") for image in coco["images"])
        all_annotations.extend(coco["annotations"])
    all_images.sort(key=lambda image: int(image["id"]))
    all_annotations.sort(key=lambda item: (int(item["image_id"]), int(item["id"])))
    combined = {
        "images": all_images,
        "annotations": all_annotations,
        "categories": coco_by_split["train"]["categories"],
    }
    _write_json(output / "train" / "_annotations.coco.json", combined)

    # The trainer requires a validation loader. Use the same all-recording set for
    # in-sample loss monitoring only; it is not an evaluation partition or gate.
    valid_images = [dict(image, split="validation") for image in all_images]
    valid = {**combined, "images": valid_images}
    _write_json(output / "valid" / "_annotations.coco.json", valid)
    _link_or_copy(
        source / "sealed_test" / "_annotations.coco.json",
        output / "sealed_test" / "_annotations.coco.json",
    )
    for entry in ("exclusions.json", "split.json"):
        _link_or_copy(source / entry, output / entry)

    counts = dict(materialization["counts"])
    counts.update(
        images=len(all_images),
        annotations=len(all_annotations),
        train_images=len(all_images),
        validation_images=len(valid_images),
        sealed_test_images=len(coco_by_split["sealed_test"]["images"]),
        train_annotations=len(all_annotations),
        validation_annotations=len(all_annotations),
    )
    refit = {
        "schema_version": "0092-m4-all-recording-refit-view/v1",
        "source_materialization_digest": materialization["materialization_digest"],
        "recording_ids": sorted(all_recordings),
        "recording_count": len(all_recordings),
        "training_frame_count": len(all_images),
        "training_annotation_count": len(all_annotations),
        "in_sample_monitoring": True,
        "sealed_test_evaluation": False,
    }
    result = {
        **materialization,
        "counts": counts,
        "generated_files": [],
        "m4_refit": refit,
    }
    for relative in ("exclusions.json", "split.json"):
        result["generated_files"].append(
            {
                "kind": "refit_source_receipt",
                "path": relative,
                "sha256": _file_digest(output / relative),
            }
        )
    for partition in ("train", "valid", "sealed_test"):
        coco_path = output / partition / "_annotations.coco.json"
        result["generated_files"].append(
            {
                "kind": "coco_annotations",
                "path": coco_path.relative_to(output).as_posix(),
                "sha256": _file_digest(coco_path),
                "split": partition,
            }
        )
        coco = json.loads(coco_path.read_text())
        for image in coco["images"]:
            relative = (Path(partition) / image["file_name"]).as_posix()
            result["generated_files"].append(
                {
                    "kind": "extracted_frame",
                    "path": relative,
                    "recording_id": image["recording_id"],
                    "event_id": image.get("event_id"),
                    "sha256": _file_digest(output / relative),
                }
            )
    result.pop("materialization_digest", None)
    result["materialization_digest"] = _digest(result)
    _write_json(output / "materialization.json", result)
    return {
        "output": str(output),
        "materialization_digest": result["materialization_digest"],
        **refit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, default=Path(".runtime/rfdetr-segmentation-0092-m1"))
    parser.add_argument(
        "--output", type=Path, default=Path(".runtime/rfdetr-segmentation-0092-m4-view")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json"),
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    try:
        result = prepare(root, resolve(args.source), resolve(args.output), resolve(args.manifest))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
