"""Prepare and run the epic 0070 all-recordings RF-DETR candidate.

The candidate keeps the frozen 0068 validation and sealed-test partitions.  It appends the
train-only M5 scenes to the reviewed 0068 train partition and records the resulting view as a
normal RF-DETR materialization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from .reviewed_rfdetr_detector_campaign import canonical_json_bytes

REAL_MATERIALIZATION_DEFAULT = ".runtime/rfdetr-segmentation-0068"
REAL_MANIFEST_DEFAULT = "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
SYNTHETIC_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-all-recordings.json"
SYNTHETIC_OUTPUT_DEFAULT = ".runtime/synthetic-visible-region-0070-all-recordings"
VIEW_OUTPUT_DEFAULT = ".runtime/synthetic-visible-region-0070-all-recordings-training-view"
TRAINING_OUTPUT_DEFAULT = ".runtime/synthetic-visible-region-0070-all-recordings-training"
PRETRAINED_CHECKPOINT_DEFAULT = ".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt"
_SCHEMA = "synthetic-visible-region-all-recordings-training-view/v1"


class SyntheticVisibleRegionAllRecordingsTrainingError(ValueError):
    """The all-recordings RF-DETR candidate view is invalid."""


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            f"could not read {field}: {path}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionAllRecordingsTrainingError(f"{field} must be an object")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(value) + b"\n")
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            f"could not hash file: {path}"
        ) from error
    return digest.hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
            "byte_length": path.stat().st_size,
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]


def _symlink_directory(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            f"missing source directory: {source}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source.resolve(), target_is_directory=True)


def _copy_image_entry(image: Mapping[str, Any], *, prefix: str, image_id: int) -> dict[str, Any]:
    relative = Path(str(image["file_name"]))
    if relative.parts[:1] != ("images",) or len(relative.parts) != 2:
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            f"COCO image path must be images/<file>: {image['file_name']}"
        )
    result = dict(image)
    result["id"] = image_id
    result["file_name"] = f"{prefix}/{relative.name}"
    return result


def _copy_annotation_entry(
    annotation: Mapping[str, Any], *, image_id_map: Mapping[int, int], annotation_id: int
) -> dict[str, Any]:
    old_image_id = annotation.get("image_id")
    if not isinstance(old_image_id, int) or old_image_id not in image_id_map:
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            "synthetic COCO annotation references an unknown image"
        )
    result = dict(annotation)
    result["id"] = annotation_id
    result["image_id"] = image_id_map[old_image_id]
    return result


def build_synthetic_visible_region_all_recordings_training_view(
    repository_root: str | Path,
    *,
    real_materialization: str | Path = REAL_MATERIALIZATION_DEFAULT,
    synthetic_manifest: str | Path = SYNTHETIC_MANIFEST_DEFAULT,
    synthetic_output: str | Path = SYNTHETIC_OUTPUT_DEFAULT,
    output_directory: str | Path = VIEW_OUTPUT_DEFAULT,
) -> dict[str, Any]:
    """Create a digest-checked 0068 train-plus-M5 view for RF-DETR."""

    repository = Path(repository_root).expanduser().resolve()
    real_root = _resolve(repository, real_materialization)
    manifest_path = _resolve(repository, synthetic_manifest)
    synthetic_root = _resolve(repository, synthetic_output)
    output = _resolve(repository, output_directory)
    real_materialization_manifest = _read_json(
        real_root / "materialization.json", "0068 materialization"
    )
    synthetic_manifest_value = _read_json(manifest_path, "M5 all-recordings manifest")
    if synthetic_manifest_value.get("schema_version") != (
        "synthetic-visible-region-all-recordings/v1"
    ):
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            "M5 manifest schema is unsupported"
        )
    coco_receipt = synthetic_manifest_value.get("outputs", {}).get("coco", {})
    coco_path = _resolve(repository, coco_receipt.get("path", ""))
    if coco_path != synthetic_root / "_annotations.coco.json":
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            "M5 manifest COCO path does not match the mounted synthetic output"
        )
    if _sha256_file(coco_path) != coco_receipt.get("sha256"):
        raise SyntheticVisibleRegionAllRecordingsTrainingError("M5 COCO digest is stale")

    real_train_path = real_root / "train" / "_annotations.coco.json"
    real_coco = _read_json(real_train_path, "0068 train COCO")
    synthetic_coco = _read_json(coco_path, "M5 train COCO")
    categories = [{"id": 1, "name": "visible_card", "supercategory": "card"}]
    if real_coco.get("categories") != categories or synthetic_coco.get("categories") != categories:
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            "real and synthetic COCO categories do not match"
        )
    if output.exists() and any(output.iterdir()):
        materialization_path = output / "materialization.json"
        if materialization_path.is_file():
            return {
                "root": output,
                "materialization": _read_json(
                    materialization_path, "all-recordings training materialization"
                ),
                "reused": True,
            }
        raise SyntheticVisibleRegionAllRecordingsTrainingError(
            f"training view is not empty: {output}"
        )

    output.mkdir(parents=True, exist_ok=True)
    for partition in ("valid", "sealed_test"):
        _symlink_directory(real_root / partition, output / partition)
    for filename in ("split.json", "exclusions.json"):
        source = real_root / filename
        if not source.is_file():
            raise SyntheticVisibleRegionAllRecordingsTrainingError(
                f"0068 receipt is missing: {source}"
            )
        (output / filename).symlink_to(source.resolve())
    _symlink_directory(real_root / "train" / "images", output / "train" / "real-images")
    _symlink_directory(synthetic_root / "images", output / "train" / "synthetic-images")

    real_images = list(real_coco.get("images", []))
    real_annotations = list(real_coco.get("annotations", []))
    synthetic_images = list(synthetic_coco.get("images", []))
    synthetic_annotations = list(synthetic_coco.get("annotations", []))
    if not all(isinstance(item, Mapping) for item in (*real_images, *real_annotations)):
        raise SyntheticVisibleRegionAllRecordingsTrainingError("0068 train COCO is invalid")
    if not all(isinstance(item, Mapping) for item in (*synthetic_images, *synthetic_annotations)):
        raise SyntheticVisibleRegionAllRecordingsTrainingError("M5 train COCO is invalid")

    real_image_ids = [int(image["id"]) for image in real_images]
    real_annotation_ids = [int(annotation["id"]) for annotation in real_annotations]
    image_offset = max(real_image_ids, default=0)
    annotation_offset = max(real_annotation_ids, default=0)
    image_id_map = {
        int(image["id"]): image_offset + index
        for index, image in enumerate(synthetic_images, start=1)
    }
    merged_images = [
        _copy_image_entry(image, prefix="real-images", image_id=int(image["id"]))
        for image in real_images
    ]
    merged_images.extend(
        _copy_image_entry(image, prefix="synthetic-images", image_id=image_id_map[int(image["id"])])
        for image in synthetic_images
    )
    merged_annotations = [dict(annotation) for annotation in real_annotations]
    merged_annotations.extend(
        _copy_annotation_entry(
            annotation,
            image_id_map=image_id_map,
            annotation_id=annotation_offset + index,
        )
        for index, annotation in enumerate(synthetic_annotations, start=1)
    )
    merged_coco = {
        "info": {
            **dict(real_coco.get("info", {})),
            "campaign_id": "0070-m5-synthetic-visible-region-all-recordings",
            "trainer_partition": "train",
            "synthetic_addition": {
                "manifest_digest": synthetic_manifest_value["manifest_digest"],
                "image_count": len(synthetic_images),
                "annotation_count": len(synthetic_annotations),
            },
        },
        "licenses": real_coco.get("licenses", []),
        "images": merged_images,
        "annotations": merged_annotations,
        "categories": categories,
    }
    from .rfdetr_segmentation_materialization import validate_rfdetr_coco_annotations

    validate_rfdetr_coco_annotations(merged_coco)
    _write_json(output / "train" / "_annotations.coco.json", merged_coco)

    base_core = {
        key: value
        for key, value in real_materialization_manifest.items()
        if key not in {"materialization_digest", "generated_files"}
    }
    counts = dict(base_core.get("counts", {}))
    counts.update(
        {
            "train_images": len(merged_images),
            "train_annotations": len(merged_annotations),
            "images": int(counts.get("images", 0)) + len(synthetic_images),
            "annotations": int(counts.get("annotations", 0)) + len(synthetic_annotations),
        }
    )
    base_core["counts"] = counts
    base_core["materializer_version"] = "synthetic-visible-region-all-recordings-training-view/v1"
    base_core["synthetic_training_view"] = {
        "schema_version": _SCHEMA,
        "manifest_digest": synthetic_manifest_value["manifest_digest"],
        "manifest_sha256": _sha256_file(manifest_path),
        "manifest_path": _relative(manifest_path, repository),
        "coco_sha256": _sha256_file(coco_path),
        "real_train_coco_sha256": _sha256_file(real_train_path),
        "synthetic_image_count": len(synthetic_images),
        "synthetic_annotation_count": len(synthetic_annotations),
    }
    generated_files = []
    for relative in ("split.json", "exclusions.json"):
        path = output / relative
        generated_files.append({"path": relative, "sha256": _sha256_file(path)})
    for partition in ("train", "valid", "sealed_test"):
        for path in sorted(item for item in (output / partition).rglob("*") if item.is_file()):
            generated_files.append(
                {"path": path.relative_to(output).as_posix(), "sha256": _sha256_file(path)}
            )
    base_core["generated_files"] = generated_files
    materialization = {**base_core, "materialization_digest": _digest(base_core)}
    _write_json(output / "materialization.json", materialization)
    return {"root": output, "materialization": materialization, "reused": False}


def run_synthetic_visible_region_all_recordings_training(
    repository_root: str | Path,
    *,
    real_manifest: str | Path = REAL_MANIFEST_DEFAULT,
    real_materialization: str | Path = REAL_MATERIALIZATION_DEFAULT,
    synthetic_manifest: str | Path = SYNTHETIC_MANIFEST_DEFAULT,
    synthetic_output: str | Path = SYNTHETIC_OUTPUT_DEFAULT,
    view_output: str | Path = VIEW_OUTPUT_DEFAULT,
    training_output: str | Path = TRAINING_OUTPUT_DEFAULT,
    pretrained_checkpoint: str | Path = PRETRAINED_CHECKPOINT_DEFAULT,
    runner: Literal["fixture", "rfdetr"] = "rfdetr",
    device: Literal["cpu", "mps", "cuda"] = "mps",
    seed: int = 7001,
) -> dict[str, Any]:
    """Prepare the merged view and run one frozen RF-DETR candidate."""

    repository = Path(repository_root).expanduser().resolve()
    view = build_synthetic_visible_region_all_recordings_training_view(
        repository,
        real_materialization=real_materialization,
        synthetic_manifest=synthetic_manifest,
        synthetic_output=synthetic_output,
        output_directory=view_output,
    )
    from table_evidence_analyzer.rfdetr_segmentation_training import (
        RfdetrSegmentationCampaignTrainingConfig,
        run_rfdetr_segmentation_campaign_training,
    )

    run = run_rfdetr_segmentation_campaign_training(
        RfdetrSegmentationCampaignTrainingConfig(
            dataset_dir=view["root"],
            campaign_manifest=_resolve(repository, real_manifest),
            pretrained_checkpoint=_resolve(repository, pretrained_checkpoint),
            output_dir=_resolve(repository, training_output),
            runner=runner,
            device=device,
            seed=seed,
        )
    )
    return {"view": view, "run": run}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--real-manifest", type=Path, default=Path(REAL_MANIFEST_DEFAULT))
    parser.add_argument(
        "--real-materialization", type=Path, default=Path(REAL_MATERIALIZATION_DEFAULT)
    )
    parser.add_argument("--synthetic-manifest", type=Path, default=Path(SYNTHETIC_MANIFEST_DEFAULT))
    parser.add_argument("--synthetic-output", type=Path, default=Path(SYNTHETIC_OUTPUT_DEFAULT))
    parser.add_argument("--view-output", type=Path, default=Path(VIEW_OUTPUT_DEFAULT))
    parser.add_argument("--training-output", type=Path, default=Path(TRAINING_OUTPUT_DEFAULT))
    parser.add_argument(
        "--pretrained-checkpoint", type=Path, default=Path(PRETRAINED_CHECKPOINT_DEFAULT)
    )
    parser.add_argument("--runner", choices=("fixture", "rfdetr"), default="rfdetr")
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="mps")
    parser.add_argument("--seed", type=int, default=7001)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = run_synthetic_visible_region_all_recordings_training(
            args.repository_root,
            real_manifest=args.real_manifest,
            real_materialization=args.real_materialization,
            synthetic_manifest=args.synthetic_manifest,
            synthetic_output=args.synthetic_output,
            view_output=args.view_output,
            training_output=args.training_output,
            pretrained_checkpoint=args.pretrained_checkpoint,
            runner=args.runner,
            device=args.device,
            seed=args.seed,
        )
    except (OSError, SyntheticVisibleRegionAllRecordingsTrainingError, ValueError) as error:
        print(f"error: {error}")
        return 2
    print(json.dumps(result, default=str, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PRETRAINED_CHECKPOINT_DEFAULT",
    "REAL_MANIFEST_DEFAULT",
    "REAL_MATERIALIZATION_DEFAULT",
    "SYNTHETIC_MANIFEST_DEFAULT",
    "SYNTHETIC_OUTPUT_DEFAULT",
    "TRAINING_OUTPUT_DEFAULT",
    "VIEW_OUTPUT_DEFAULT",
    "SyntheticVisibleRegionAllRecordingsTrainingError",
    "build_synthetic_visible_region_all_recordings_training_view",
    "run_synthetic_visible_region_all_recordings_training",
]
