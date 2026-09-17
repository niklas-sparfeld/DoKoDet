"""Train and bundle the epic 0067 RF-DETR instance-segmentation candidates.

The adapter consumes only the disposable COCO view emitted by the operations materializer.  It
keeps the detection-only RF-DETR bundle contract separate from the segmentation contract and
records every input, argument, stage, and failure needed to resume a local run.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .rfdetr_import import block_pyav_import

RFDETR_SEGMENTATION_TRAINING_RUN_SCHEMA = "rfdetr-segmentation-training-run/v1"
RFDETR_SEGMENTATION_CAMPAIGN_RUN_SCHEMA = "rfdetr-segmentation-campaign-training-run/v1"
RFDETR_SEGMENTATION_CAMPAIGN_DATASET_SCHEMA = "rfdetr-segmentation-campaign-dataset/v1"
RFDETR_SEGMENTATION_BUNDLE_SCHEMA = "rfdetr-segmentation-bundle/v1"
RFDETR_SEGMENTATION_MODEL_CLASS = "RFDETRSegMedium"
RFDETR_SEGMENTATION_MODEL_VARIANT = "rfdetr-seg-medium"
RFDETR_SEGMENTATION_PACKAGE_VERSION = "1.9.4"
RFDETR_SEGMENTATION_INPUT_SIZE = 432
RFDETR_SEGMENTATION_CHECKPOINT_NAME = "rf-detr-seg-medium.pt"
RFDETR_SEGMENTATION_FINAL_CHECKPOINT = "checkpoint_best_total.pth"
RFDETR_SEGMENTATION_CONFIDENCE_THRESHOLD = 0.5
RFDETR_SEGMENTATION_MATERIALIZATION_SCHEMA = "rfdetr-segmentation-materialization/v1"
RFDETR_SEGMENTATION_RECIPE_SCHEMA = "rfdetr-segmentation-training-recipe/v1"
RFDETR_SEGMENTATION_PROVIDER_MODEL = "rfdetr-seg-medium"
RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID = "0068-m0-reviewed-rfdetr-local-visible-card-detector"
RFDETR_REVIEWED_DETECTOR_MANIFEST_SCHEMA = "rfdetr-visible-card-detector-manifest/v1"
RFDETR_REVIEWED_DETECTOR_SMOKE_RUN_SCHEMA = "rfdetr-visible-card-detector-smoke-run/v1"
RFDETR_REVIEWED_DETECTOR_CAMPAIGN_RUN_SCHEMA = "rfdetr-visible-card-detector-training-run/v1"
RFDETR_REVIEWED_DETECTOR_DATASET_SCHEMA = "rfdetr-visible-card-detector-training-dataset/v1"
_SHA256_LENGTH = 64
_RUNNERS = frozenset({"fixture", "rfdetr"})
_DEVICES = frozenset({"cpu", "mps", "cuda"})


class RfdetrSegmentationTrainingError(ValueError):
    """The RF-DETR segmentation smoke run cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationTrainingConfig:
    """Inputs and fixed M2 controls for one segmentation smoke run."""

    dataset_dir: Path
    pretrained_checkpoint: Path
    output_dir: Path
    campaign_manifest: Path | None = None
    runner: Literal["fixture", "rfdetr"] = "rfdetr"
    device: Literal["cpu", "mps", "cuda"] = "mps"
    train_image_count: int = 6
    validation_image_count: int = 1

    def __post_init__(self) -> None:
        if self.runner not in _RUNNERS:
            raise RfdetrSegmentationTrainingError("runner must be fixture or rfdetr")
        if self.device not in _DEVICES:
            raise RfdetrSegmentationTrainingError("device must be cpu, mps, or cuda")
        for name, value in (
            ("train_image_count", self.train_image_count),
            ("validation_image_count", self.validation_image_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise RfdetrSegmentationTrainingError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationCampaignTrainingConfig:
    """Inputs for the full M3 candidate training run."""

    dataset_dir: Path
    campaign_manifest: Path
    pretrained_checkpoint: Path
    output_dir: Path
    runner: Literal["fixture", "rfdetr"] = "rfdetr"
    device: Literal["cpu", "mps", "cuda"] = "mps"
    resume: Path | None = None

    def __post_init__(self) -> None:
        if self.runner not in _RUNNERS:
            raise RfdetrSegmentationTrainingError("runner must be fixture or rfdetr")
        if self.device not in _DEVICES:
            raise RfdetrSegmentationTrainingError("device must be cpu, mps, or cuda")


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationBundle:
    """A digest-checked native segmentation checkpoint bundle."""

    root: Path
    manifest: dict[str, Any]
    checkpoint_path: Path


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RfdetrSegmentationTrainingError("training values must be finite JSON") from error


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
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    temporary.replace(path)


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RfdetrSegmentationTrainingError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise RfdetrSegmentationTrainingError(f"{context} must be a JSON object: {path}")
    return value


def _safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RfdetrSegmentationTrainingError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RfdetrSegmentationTrainingError(f"{field} must stay below its mounted root")
    return path.as_posix()


def _assert_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise RfdetrSegmentationTrainingError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise RfdetrSegmentationTrainingError(f"{field} must be a SHA-256 digest") from error
    return value


def _load_materialization_view(root_value: str | Path) -> dict[str, Any]:
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise RfdetrSegmentationTrainingError(f"materialized dataset does not exist: {root}")
    materialization = _read_json(root / "materialization.json", "M1 materialization manifest")
    if materialization.get("schema_version") != RFDETR_SEGMENTATION_MATERIALIZATION_SCHEMA:
        raise RfdetrSegmentationTrainingError("M1 materialization schema is unsupported")
    declared_digest = _assert_sha256(
        materialization.get("materialization_digest"), "materialization_digest"
    )
    core = {key: value for key, value in materialization.items() if key != "materialization_digest"}
    if declared_digest != _digest(core):
        raise RfdetrSegmentationTrainingError("M1 materialization digest does not match contents")
    campaign_id = materialization.get("campaign_id")
    if campaign_id not in {
        "0067-m0-rfdetr-segmentation",
        RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID,
    }:
        raise RfdetrSegmentationTrainingError(
            "M1 materialization belongs to an unsupported campaign"
        )
    generated_files = materialization.get("generated_files")
    if not isinstance(generated_files, list) or not generated_files:
        raise RfdetrSegmentationTrainingError("M1 materialization has no generated file index")
    for item in generated_files:
        if not isinstance(item, Mapping):
            raise RfdetrSegmentationTrainingError("M1 generated file entry is not an object")
        relative = _safe_relative(item.get("path"), "M1 generated file path")
        path = root / relative
        if not path.is_file():
            raise RfdetrSegmentationTrainingError(f"M1 generated file is missing: {relative}")
        if _assert_sha256(item.get("sha256"), f"M1 generated file {relative}") != _file_digest(
            path
        ):
            raise RfdetrSegmentationTrainingError(
                f"M1 generated file digest does not match: {relative}"
            )

    partitions: dict[str, list[dict[str, Any]]] = {}
    partition_names = ("train", "valid")
    if campaign_id == RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID:
        partition_names += ("sealed_test",)
    for partition in partition_names:
        coco = _read_json(root / partition / "_annotations.coco.json", f"{partition} COCO data")
        if coco.get("categories") != [{"id": 1, "name": "visible_card", "supercategory": "card"}]:
            raise RfdetrSegmentationTrainingError(
                f"{partition} COCO data does not contain the visible_card category"
            )
        images = coco.get("images")
        annotations = coco.get("annotations")
        if not isinstance(images, list) or not images:
            raise RfdetrSegmentationTrainingError(f"{partition} COCO data has no images")
        if not isinstance(annotations, list):
            raise RfdetrSegmentationTrainingError(f"{partition} COCO annotations must be a list")
        image_ids: set[int] = set()
        annotation_image_ids: set[int] = set()
        for image in images:
            if not isinstance(image, Mapping) or not isinstance(image.get("id"), int):
                raise RfdetrSegmentationTrainingError(f"{partition} COCO image is invalid")
            image_id = int(image["id"])
            if image_id in image_ids:
                raise RfdetrSegmentationTrainingError(f"{partition} COCO image IDs are not unique")
            image_ids.add(image_id)
            relative = _safe_relative(image.get("file_name"), f"{partition} image.file_name")
            image_path = root / partition / relative
            if not image_path.is_file():
                raise RfdetrSegmentationTrainingError(
                    f"{partition} COCO image is missing: {relative}"
                )
            expected_image_digest = _assert_sha256(image.get("sha256"), f"{partition} image.sha256")
            if expected_image_digest != _file_digest(image_path):
                raise RfdetrSegmentationTrainingError(
                    f"{partition} COCO image digest does not match: {relative}"
                )
        for annotation in annotations:
            if not isinstance(annotation, Mapping):
                raise RfdetrSegmentationTrainingError(f"{partition} COCO annotation is invalid")
            image_id = annotation.get("image_id")
            if not isinstance(image_id, int) or image_id not in image_ids:
                raise RfdetrSegmentationTrainingError(
                    f"{partition} COCO annotation references an unknown image"
                )
            annotation_image_ids.add(image_id)
        if annotation_image_ids != image_ids:
            raise RfdetrSegmentationTrainingError(
                f"{partition} COCO data has an image without a reviewed target"
            )
        partitions[partition] = [dict(image) for image in images]
    return {"root": root, "manifest": materialization, "partitions": partitions}


def _representative_images(images: Sequence[Mapping[str, Any]], count: int) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(image) for image in images),
        key=lambda image: (
            str(image.get("recording_id", "")),
            str(image.get("event_id", "")),
            int(image["id"]),
        ),
    )
    by_recording: dict[str, dict[str, Any]] = {}
    for image in ordered:
        by_recording.setdefault(str(image.get("recording_id", "")), image)
    selected: list[dict[str, Any]] = list(by_recording.values())
    selected_ids = {int(image["id"]) for image in selected}
    selected.extend(image for image in ordered if int(image["id"]) not in selected_ids)
    if count > len(selected):
        raise RfdetrSegmentationTrainingError(
            f"requested {count} representative images but the M1 view has only {len(selected)}"
        )
    return selected[:count]


def _stage_smoke_dataset(
    view: Mapping[str, Any],
    destination: Path,
    *,
    train_count: int,
    validation_count: int,
    subset_schema: str = "rfdetr-segmentation-smoke-subset/v1",
) -> dict[str, Any]:
    if destination.exists():
        raise RfdetrSegmentationTrainingError(f"staged dataset already exists: {destination}")
    root = view["root"]
    partitions = view["partitions"]
    selected = {
        "train": _representative_images(partitions["train"], train_count),
        "valid": _representative_images(partitions["valid"], validation_count),
    }
    destination.mkdir(parents=True)
    selected_ids = {
        partition: {int(image["id"]) for image in images} for partition, images in selected.items()
    }
    subset_images: dict[str, list[dict[str, Any]]] = {}
    subset_annotations: dict[str, list[dict[str, Any]]] = {}
    for partition in ("train", "valid"):
        output_images = destination / partition / "images"
        output_images.mkdir(parents=True)
        source_coco = _read_json(
            root / partition / "_annotations.coco.json", f"{partition} COCO data"
        )
        annotations = [
            dict(annotation)
            for annotation in source_coco["annotations"]
            if annotation.get("image_id") in selected_ids[partition]
        ]
        subset_annotations[partition] = annotations
        subset_images[partition] = []
        for image in selected[partition]:
            relative = _safe_relative(image["file_name"], f"{partition} image.file_name")
            source = root / partition / relative
            image_name = Path(relative).name
            link = output_images / image_name
            link.symlink_to(source)
            subset_image = dict(image)
            subset_image["file_name"] = f"images/{image_name}"
            subset_images[partition].append(subset_image)
        _write_json(
            destination / partition / "_annotations.coco.json",
            {
                "info": source_coco.get("info", {}),
                "licenses": source_coco.get("licenses", []),
                "images": subset_images[partition],
                "annotations": subset_annotations[partition],
                "categories": source_coco["categories"],
            },
        )
    subset_core = {
        "schema_version": subset_schema,
        "materialization_digest": view["manifest"]["materialization_digest"],
        "train_image_count": len(selected["train"]),
        "validation_image_count": len(selected["valid"]),
        "train_image_ids": [int(image["id"]) for image in selected["train"]],
        "validation_image_ids": [int(image["id"]) for image in selected["valid"]],
        "train_recording_ids": [str(image.get("recording_id")) for image in selected["train"]],
        "validation_recording_ids": [str(image.get("recording_id")) for image in selected["valid"]],
        "annotation_ids": {
            partition: [int(annotation["id"]) for annotation in subset_annotations[partition]]
            for partition in ("train", "valid")
        },
    }
    subset = {**subset_core, "subset_digest": _digest(subset_core)}
    _write_json(destination / "subset.json", subset)
    return {
        "subset": subset,
        "images": subset_images,
        "annotations": subset_annotations,
        "validation_frame": selected["valid"][0],
    }


def _stage_campaign_dataset(
    view: Mapping[str, Any],
    destination: Path,
    *,
    subset_schema: str = RFDETR_SEGMENTATION_CAMPAIGN_DATASET_SCHEMA,
) -> dict[str, Any]:
    """Stage every reviewed M1 image for the one-candidate M3 training run."""

    return _stage_smoke_dataset(
        view,
        destination,
        train_count=len(view["partitions"]["train"]),
        validation_count=len(view["partitions"]["valid"]),
        subset_schema=subset_schema,
    )


def _load_staged_campaign_dataset(
    view: Mapping[str, Any],
    destination: Path,
    *,
    subset_schema: str,
) -> dict[str, Any]:
    """Validate and load a campaign dataset left by an interrupted run."""

    if not destination.is_dir():
        raise RfdetrSegmentationTrainingError(
            f"resumed campaign dataset does not exist: {destination}"
        )
    subset = _read_json(destination / "subset.json", "resumed campaign subset")
    if subset.get("schema_version") != subset_schema:
        raise RfdetrSegmentationTrainingError(
            "resumed campaign dataset uses a different subset schema"
        )
    if subset.get("materialization_digest") != view["manifest"]["materialization_digest"]:
        raise RfdetrSegmentationTrainingError(
            "resumed campaign dataset does not match the current M1 materialization"
        )

    expected_images = {
        partition: _representative_images(
            view["partitions"][partition], len(view["partitions"][partition])
        )
        for partition in ("train", "valid")
    }
    expected_ids = {
        partition: {int(image["id"]) for image in images}
        for partition, images in expected_images.items()
    }
    expected_annotation_ids: dict[str, list[int]] = {}
    for partition in ("train", "valid"):
        subset_prefix = "train" if partition == "train" else "validation"
        subset_ids = {int(image_id) for image_id in subset.get(f"{subset_prefix}_image_ids", [])}
        if subset_ids != expected_ids[partition]:
            raise RfdetrSegmentationTrainingError(
                f"resumed campaign subset has different {partition} image IDs"
            )
        if subset.get(f"{subset_prefix}_image_count") != len(expected_ids[partition]):
            raise RfdetrSegmentationTrainingError(
                f"resumed campaign subset has a different {partition} image count"
            )

        source_coco = _read_json(
            view["root"] / partition / "_annotations.coco.json",
            f"{partition} M1 COCO data",
        )
        staged_coco = _read_json(
            destination / partition / "_annotations.coco.json",
            f"resumed {partition} COCO data",
        )
        source_images = {int(image["id"]): image for image in source_coco.get("images", [])}
        staged_images = staged_coco.get("images")
        staged_annotations = staged_coco.get("annotations")
        if not isinstance(staged_images, list) or not isinstance(staged_annotations, list):
            raise RfdetrSegmentationTrainingError(f"resumed {partition} COCO data is incomplete")
        if staged_coco.get("categories") != source_coco.get("categories"):
            raise RfdetrSegmentationTrainingError(
                f"resumed {partition} COCO categories differ from the M1 view"
            )
        if {int(image["id"]) for image in staged_images} != expected_ids[partition]:
            raise RfdetrSegmentationTrainingError(
                f"resumed {partition} COCO data has different image IDs"
            )
        source_annotations = [
            annotation
            for annotation in source_coco.get("annotations", [])
            if int(annotation["image_id"]) in expected_ids[partition]
        ]
        expected_annotation_ids[partition] = [
            int(annotation["id"]) for annotation in source_annotations
        ]
        staged_annotations_by_id = {
            int(annotation["id"]): annotation for annotation in staged_annotations
        }
        source_annotations_by_id = {
            int(annotation["id"]): annotation for annotation in source_annotations
        }
        if len(staged_annotations_by_id) != len(staged_annotations) or staged_annotations_by_id != (
            source_annotations_by_id
        ):
            raise RfdetrSegmentationTrainingError(
                f"resumed {partition} COCO annotations differ from the M1 view"
            )
        for image in staged_images:
            image_id = int(image["id"])
            source_image = source_images.get(image_id)
            if source_image is None:
                raise RfdetrSegmentationTrainingError(
                    f"resumed {partition} COCO data references an unknown image"
                )
            for key, value in source_image.items():
                if key != "file_name" and image.get(key) != value:
                    raise RfdetrSegmentationTrainingError(
                        f"resumed {partition} image {image_id} differs from the M1 view"
                    )
            relative = _safe_relative(image.get("file_name"), f"{partition} image.file_name")
            staged_path = destination / partition / relative
            if not staged_path.is_file() or _file_digest(staged_path) != image.get("sha256"):
                raise RfdetrSegmentationTrainingError(
                    f"resumed {partition} image {image_id} is missing or has a different digest"
                )

    expected_subset_core = {
        "schema_version": subset_schema,
        "materialization_digest": view["manifest"]["materialization_digest"],
        "train_image_count": len(expected_images["train"]),
        "validation_image_count": len(expected_images["valid"]),
        "train_image_ids": [int(image["id"]) for image in expected_images["train"]],
        "validation_image_ids": [int(image["id"]) for image in expected_images["valid"]],
        "train_recording_ids": [
            str(image.get("recording_id")) for image in expected_images["train"]
        ],
        "validation_recording_ids": [
            str(image.get("recording_id")) for image in expected_images["valid"]
        ],
        "annotation_ids": expected_annotation_ids,
    }
    subset_core = {key: value for key, value in subset.items() if key != "subset_digest"}
    if subset_core != expected_subset_core:
        raise RfdetrSegmentationTrainingError(
            "resumed campaign subset differs from the current M1 view"
        )
    if subset.get("subset_digest") != _digest(subset_core):
        raise RfdetrSegmentationTrainingError("resumed campaign subset digest does not match")
    valid_images = _read_json(
        destination / "valid" / "_annotations.coco.json", "resumed valid COCO data"
    )["images"]
    return {
        "subset": subset,
        "images": {partition: expected_images[partition] for partition in ("train", "valid")},
        "annotations": {},
        "validation_frame": dict(valid_images[0]),
    }


def _environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("rfdetr", "torch", "torchvision", "supervision"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {"python": sys.version, "platform": platform.platform(), "packages": packages}


def _resource_facts(device: str) -> dict[str, Any]:
    facts: dict[str, Any] = {"requested_device": device, "selected_device": device}
    try:
        import torch
    except ImportError:
        facts["torch_available"] = False
        facts["device_available"] = device == "cpu"
        return facts
    facts["torch_available"] = True
    facts["device_available"] = {
        "cpu": True,
        "mps": bool(torch.backends.mps.is_available()),
        "cuda": bool(torch.cuda.is_available()),
    }[device]
    if device == "mps":
        facts["mps_built"] = bool(torch.backends.mps.is_built())
    if device == "cuda":
        facts["cuda_device_count"] = int(torch.cuda.device_count())
    return facts


def _code_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _model_arguments(checkpoint: Path) -> dict[str, Any]:
    return {
        "num_classes": 1,
        "pretrain_weights": str(checkpoint),
        "resolution": RFDETR_SEGMENTATION_INPUT_SIZE,
    }


def _verify_reviewed_detector_manifest(
    view: Mapping[str, Any], campaign_manifest_path: Path, pretrained_sha256: str
) -> dict[str, Any]:
    """Verify the frozen 0068 M0 manifest without importing the operations package."""

    path = campaign_manifest_path.expanduser().resolve()
    if not path.is_file():
        raise RfdetrSegmentationTrainingError(f"campaign manifest does not exist: {path}")
    manifest = _read_json(path, "0068 M0 campaign manifest")
    declared_digest = _assert_sha256(manifest.get("manifest_digest"), "M0 manifest_digest")
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if declared_digest != _digest(core):
        raise RfdetrSegmentationTrainingError(
            "0068 M0 campaign manifest digest does not match contents"
        )
    if (
        manifest.get("schema_version") != RFDETR_REVIEWED_DETECTOR_MANIFEST_SCHEMA
        or manifest.get("campaign_id") != RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID
        or manifest.get("milestone") != "M0"
        or manifest.get("read_only") is not True
        or manifest.get("freeze_state") != "frozen"
    ):
        raise RfdetrSegmentationTrainingError("0068 M0 campaign manifest is not frozen")
    recipe = manifest.get("recipe")
    if not isinstance(recipe, Mapping) or manifest.get("recipe_sha256") != _digest(recipe):
        raise RfdetrSegmentationTrainingError("0068 M0 recipe digest does not match contents")
    if recipe.get("package") != {
        "name": "rfdetr",
        "version": RFDETR_SEGMENTATION_PACKAGE_VERSION,
    }:
        raise RfdetrSegmentationTrainingError("0068 M0 RF-DETR package pin changed")
    model = recipe.get("model")
    if not isinstance(model, Mapping) or {
        "class": model.get("class"),
        "variant": model.get("variant"),
        "resolution": model.get("resolution"),
    } != {
        "class": RFDETR_SEGMENTATION_MODEL_CLASS,
        "variant": RFDETR_SEGMENTATION_MODEL_VARIANT,
        "resolution": [RFDETR_SEGMENTATION_INPUT_SIZE, RFDETR_SEGMENTATION_INPUT_SIZE],
    }:
        raise RfdetrSegmentationTrainingError("0068 M0 RF-DETR model or resolution pin changed")
    checkpoint = recipe.get("pretrained_checkpoint")
    if not isinstance(checkpoint, Mapping) or checkpoint.get("sha256") != pretrained_sha256:
        raise RfdetrSegmentationTrainingError(
            "pretrained checkpoint does not match the frozen 0068 M0 checkpoint digest"
        )
    training = recipe.get("training")
    if not isinstance(training, Mapping) or {
        key: training.get(key)
        for key in (
            "batch_size",
            "grad_accum_steps",
            "epochs",
            "seed",
            "num_workers",
            "mixed_precision",
        )
    } != {
        "batch_size": 1,
        "grad_accum_steps": 4,
        "epochs": 40,
        "seed": 6701,
        "num_workers": 0,
        "mixed_precision": False,
    }:
        raise RfdetrSegmentationTrainingError("0068 M0 training recipe is not locked")
    augmentation = recipe.get("augmentation")
    if not isinstance(augmentation, Mapping) or {
        key: augmentation.get(key)
        for key in ("multi_scale", "expanded_scales", "do_random_resize_via_padding", "use_ema")
    } != {
        "multi_scale": True,
        "expanded_scales": True,
        "do_random_resize_via_padding": False,
        "use_ema": True,
    }:
        raise RfdetrSegmentationTrainingError("0068 M0 augmentation recipe is not locked")
    early_stopping = recipe.get("early_stopping")
    if not isinstance(early_stopping, Mapping) or {
        "enabled": early_stopping.get("enabled"),
        "patience": early_stopping.get("patience"),
        "min_delta": early_stopping.get("min_delta"),
    } != {"enabled": True, "patience": 8, "min_delta": 0.001}:
        raise RfdetrSegmentationTrainingError("0068 M0 early-stopping recipe is not locked")
    if recipe.get("data_contract", {}).get("test_partition") != "sealed_test":
        raise RfdetrSegmentationTrainingError("0068 M0 does not define the sealed_test partition")
    if recipe.get("validation", {}).get("checkpoint_selection") != (
        "highest_validation_mask_ap_50_95_then_recall"
    ):
        raise RfdetrSegmentationTrainingError("0068 M0 checkpoint selection rule is not locked")
    if view["manifest"].get("campaign_id") != RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID:
        raise RfdetrSegmentationTrainingError("M1 materialization is not the 0068 view")
    split = _read_json(view["root"] / "split.json", "0068 M1 split")
    if split.get("campaign_manifest_digest") != declared_digest:
        raise RfdetrSegmentationTrainingError("0068 M1 split points to another M0 manifest")
    campaign_reference = view["manifest"].get("campaign_manifest")
    if not isinstance(campaign_reference, Mapping):
        raise RfdetrSegmentationTrainingError("M1 materialization has no M0 manifest receipt")
    if campaign_reference.get("manifest_digest") != declared_digest:
        raise RfdetrSegmentationTrainingError(
            "M1 materialization points to another 0068 M0 manifest"
        )
    file_digest = campaign_reference.get("file_sha256")
    if file_digest != _file_digest(path):
        raise RfdetrSegmentationTrainingError("0068 M0 manifest file digest does not match M1")
    return {
        "path": str(path),
        "campaign_id": RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID,
        "schema_version": RFDETR_REVIEWED_DETECTOR_MANIFEST_SCHEMA,
        "manifest_digest": declared_digest,
        "file_sha256": file_digest,
        "recipe_sha256": manifest["recipe_sha256"],
        "checkpoint_selection": recipe["validation"]["checkpoint_selection"],
    }


def _verify_campaign_manifest(
    view: Mapping[str, Any], campaign_manifest_path: Path, pretrained_sha256: str
) -> dict[str, Any]:
    """Verify that the M1 view and the supplied frozen M0 manifest are the same input."""

    path = campaign_manifest_path.expanduser().resolve()
    if not path.is_file():
        raise RfdetrSegmentationTrainingError(f"campaign manifest does not exist: {path}")
    manifest = _read_json(path, "M0 campaign manifest")
    if manifest.get("schema_version") == RFDETR_REVIEWED_DETECTOR_MANIFEST_SCHEMA:
        return _verify_reviewed_detector_manifest(view, path, pretrained_sha256)
    declared_digest = _assert_sha256(manifest.get("manifest_digest"), "M0 manifest_digest")
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if declared_digest != _digest(core):
        raise RfdetrSegmentationTrainingError("M0 campaign manifest digest does not match contents")
    if manifest.get("schema_version") != "rfdetr-segmentation-campaign-manifest/v1":
        raise RfdetrSegmentationTrainingError("M0 campaign manifest schema is unsupported")
    if manifest.get("campaign_id") != "0067-m0-rfdetr-segmentation":
        raise RfdetrSegmentationTrainingError("M0 campaign manifest belongs to another campaign")
    if (
        manifest.get("milestone") != "M0"
        or manifest.get("read_only") is not True
        or manifest.get("freeze_state") != "frozen"
    ):
        raise RfdetrSegmentationTrainingError("M0 campaign manifest is not frozen")
    recipe = manifest.get("recipe")
    if not isinstance(recipe, Mapping):
        raise RfdetrSegmentationTrainingError("M0 campaign manifest has no recipe")
    if manifest.get("recipe_sha256") != _digest(recipe):
        raise RfdetrSegmentationTrainingError("M0 recipe digest does not match contents")
    if recipe.get("package") != {
        "name": "rfdetr",
        "version": RFDETR_SEGMENTATION_PACKAGE_VERSION,
    }:
        raise RfdetrSegmentationTrainingError("M0 RF-DETR package pin changed")
    model = recipe.get("model")
    if not isinstance(model, Mapping):
        raise RfdetrSegmentationTrainingError("M0 model recipe is invalid")
    if (
        model.get("class") != RFDETR_SEGMENTATION_MODEL_CLASS
        or model.get("variant") != RFDETR_SEGMENTATION_MODEL_VARIANT
    ):
        raise RfdetrSegmentationTrainingError("M0 RF-DETR segmentation model pin changed")
    if model.get("resolution") != [
        RFDETR_SEGMENTATION_INPUT_SIZE,
        RFDETR_SEGMENTATION_INPUT_SIZE,
    ]:
        raise RfdetrSegmentationTrainingError("M0 RF-DETR input resolution pin changed")
    checkpoint = recipe.get("pretrained_checkpoint")
    if not isinstance(checkpoint, Mapping) or checkpoint.get("sha256") != pretrained_sha256:
        raise RfdetrSegmentationTrainingError(
            "pretrained checkpoint does not match the frozen M0 checkpoint digest"
        )
    training = recipe.get("training")
    if not isinstance(training, Mapping) or {
        "batch_size": training.get("batch_size"),
        "grad_accum_steps": training.get("grad_accum_steps"),
        "epochs": training.get("epochs"),
        "seed": training.get("seed"),
        "num_workers": training.get("num_workers"),
        "mixed_precision": training.get("mixed_precision"),
    } != {
        "batch_size": 1,
        "grad_accum_steps": 4,
        "epochs": 40,
        "seed": 6701,
        "num_workers": 0,
        "mixed_precision": False,
    }:
        raise RfdetrSegmentationTrainingError(
            "M0 training recipe is not the locked campaign recipe"
        )
    augmentation = recipe.get("augmentation")
    if not isinstance(augmentation, Mapping) or {
        key: augmentation.get(key)
        for key in ("multi_scale", "expanded_scales", "do_random_resize_via_padding", "use_ema")
    } != {
        "multi_scale": True,
        "expanded_scales": True,
        "do_random_resize_via_padding": False,
        "use_ema": True,
    }:
        raise RfdetrSegmentationTrainingError("M0 augmentation recipe is not locked")
    early_stopping = recipe.get("early_stopping")
    if not isinstance(early_stopping, Mapping) or {
        "enabled": early_stopping.get("enabled"),
        "patience": early_stopping.get("patience"),
        "min_delta": early_stopping.get("min_delta"),
    } != {"enabled": True, "patience": 8, "min_delta": 0.001}:
        raise RfdetrSegmentationTrainingError("M0 early-stopping recipe is not locked")
    campaign_reference = view["manifest"].get("campaign_manifest")
    if not isinstance(campaign_reference, Mapping):
        raise RfdetrSegmentationTrainingError("M1 materialization has no M0 manifest receipt")
    if campaign_reference.get("manifest_digest") != declared_digest:
        raise RfdetrSegmentationTrainingError("M1 materialization points to another M0 manifest")
    recorded_file_digest = campaign_reference.get("file_sha256")
    if not isinstance(recorded_file_digest, str) or recorded_file_digest != _file_digest(path):
        raise RfdetrSegmentationTrainingError("M0 campaign manifest file digest does not match M1")
    return {
        "path": str(path),
        "manifest_digest": declared_digest,
        "file_sha256": _file_digest(path),
        "recipe_sha256": manifest["recipe_sha256"],
    }


def _training_arguments(staged_dataset: Path, output: Path, device: str) -> dict[str, Any]:
    return {
        "dataset_dir": str(staged_dataset),
        "dataset_file": "roboflow",
        "output_dir": str(output),
        "epochs": 1,
        "batch_size": 1,
        "grad_accum_steps": 4,
        "num_workers": 0,
        "seed": 6701,
        "resolution": RFDETR_SEGMENTATION_INPUT_SIZE,
        "device": device,
        "class_names": ["visible_card"],
        "run_test": False,
        "use_ema": True,
        "multi_scale": True,
        "expanded_scales": True,
        "do_random_resize_via_padding": False,
        "tensorboard": False,
        "wandb": False,
        "progress_bar": None,
    }


def _campaign_model_arguments(checkpoint: Path) -> dict[str, Any]:
    """Return model arguments that implement the frozen no-mixed-precision recipe."""

    return {
        **_model_arguments(checkpoint),
        "amp": False,
    }


def _campaign_training_arguments(
    staged_dataset: Path,
    output: Path,
    device: str,
    *,
    resume: Path | None = None,
) -> dict[str, Any]:
    """Return the exact RF-DETR arguments for the one-candidate M3 run."""

    arguments = {
        "dataset_dir": str(staged_dataset),
        "dataset_file": "roboflow",
        "output_dir": str(output),
        "epochs": 40,
        "batch_size": 1,
        "grad_accum_steps": 4,
        "num_workers": 0,
        "seed": 6701,
        "resolution": RFDETR_SEGMENTATION_INPUT_SIZE,
        "device": device,
        "class_names": ["visible_card"],
        "run_test": False,
        "use_ema": True,
        "multi_scale": True,
        "expanded_scales": True,
        "do_random_resize_via_padding": False,
        "early_stopping": True,
        "early_stopping_patience": 8,
        "early_stopping_min_delta": 0.001,
        "tensorboard": False,
        "wandb": False,
        "progress_bar": None,
        "eval_interval": 1,
        "save_dataset_grids": False,
    }
    if resume is not None:
        arguments["resume"] = str(resume)
    return arguments


def _requested_device_available(device: str) -> bool:
    try:
        import torch
    except ImportError as error:
        raise RfdetrSegmentationTrainingError(
            "RF-DETR segmentation requires PyTorch; install the training dependency group"
        ) from error
    if device == "cpu":
        return True
    if device == "mps":
        return bool(torch.backends.mps.is_available())
    return bool(torch.cuda.is_available())


def _import_segmentation_model() -> Any:
    try:
        with block_pyav_import():
            from rfdetr import RFDETRSegMedium
    except ImportError as error:
        raise RfdetrSegmentationTrainingError(
            "RF-DETR segmentation requires rfdetr 1.9.4 with training extras"
        ) from error
    try:
        version = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError as error:
        raise RfdetrSegmentationTrainingError(
            "RF-DETR package metadata is not installed"
        ) from error
    if version != RFDETR_SEGMENTATION_PACKAGE_VERSION:
        raise RfdetrSegmentationTrainingError(
            f"rfdetr version {version} does not match the frozen "
            f"{RFDETR_SEGMENTATION_PACKAGE_VERSION}"
        )
    return RFDETRSegMedium


def _run_fixture(inputs: Mapping[str, Any], staged_dataset: Path, training_output: Path) -> Path:
    training_output.mkdir(parents=True, exist_ok=True)
    seed_material = {
        "subset_digest": inputs["subset"]["subset_digest"],
        "pretrained_sha256": inputs["pretrained_sha256"],
        "model": RFDETR_SEGMENTATION_MODEL_CLASS,
    }
    checkpoint = training_output / RFDETR_SEGMENTATION_FINAL_CHECKPOINT
    checkpoint.write_bytes(
        b"fixture-rfdetr-segmentation/v1\n" + hashlib.sha256(_canonical(seed_material)).digest()
    )
    _write_json(
        training_output / "losses.json",
        {"train_loss": 0.25, "runner": "fixture", "dataset_dir": str(staged_dataset)},
    )
    _write_json(
        training_output / "metrics.json",
        {
            "val/segm_mAP_50_95": 0.125,
            "val/segm_mAP_50": 0.25,
            "val/mAP_50_95": 0.15,
            "val/recall": 0.5,
        },
    )
    return checkpoint


def _run_rfdetr(inputs: Mapping[str, Any], staged_dataset: Path, training_output: Path) -> Path:
    if not _requested_device_available(str(inputs["device"])):
        raise RfdetrSegmentationTrainingError(
            f"requested training device is unavailable: {inputs['device']}"
        )
    model_class = _import_segmentation_model()
    training_output.mkdir(parents=True, exist_ok=True)
    model = model_class(**inputs["model_arguments"])
    model.train(**inputs["training_arguments"])
    checkpoint = training_output / RFDETR_SEGMENTATION_FINAL_CHECKPOINT
    if not checkpoint.is_file():
        raise RfdetrSegmentationTrainingError(
            f"RF-DETR did not emit {RFDETR_SEGMENTATION_FINAL_CHECKPOINT}"
        )
    return checkpoint


def _numeric_values(value: Any, *, keywords: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                any(keyword in str(key).lower() for keyword in keywords)
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
            ):
                values.append(float(item))
            else:
                values.extend(_numeric_values(item, keywords=keywords))
    elif isinstance(value, list):
        for item in value:
            values.extend(_numeric_values(item, keywords=keywords))
    return values


def _metric_evidence(training_output: Path, *, keywords: tuple[str, ...]) -> dict[str, Any]:
    values: list[float] = []
    evidence: list[str] = []
    for path in sorted(training_output.rglob("*")):
        if not path.is_file() or path.name == RFDETR_SEGMENTATION_FINAL_CHECKPOINT:
            continue
        found: list[float] = []
        if path.suffix == ".json":
            try:
                found = _numeric_values(
                    json.loads(path.read_text(encoding="utf-8")), keywords=keywords
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        elif path.suffix == ".csv":
            try:
                with path.open(newline="", encoding="utf-8") as stream:
                    for row in csv.DictReader(stream):
                        for key, raw in row.items():
                            if not any(keyword in str(key).lower() for keyword in keywords):
                                continue
                            try:
                                found.append(float(raw))
                            except (TypeError, ValueError):
                                continue
            except OSError:
                continue
        if found:
            evidence.append(path.name)
            values.extend(found)
    if not values:
        raise RfdetrSegmentationTrainingError(
            "RF-DETR emitted no numeric " + ("loss" if "loss" in keywords else "validation metric")
        )
    if not all(math.isfinite(value) for value in values):
        raise RfdetrSegmentationTrainingError(
            "RF-DETR emitted a non-finite "
            + ("loss" if "loss" in keywords else "validation metric")
        )
    return {"finite": True, "sample_count": len(values), "evidence": evidence, "values": values}


def _stable_bundle_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "bundle_digest"}


def _write_bundle(
    destination: Path,
    *,
    inputs: Mapping[str, Any],
    checkpoint: Path,
    checkpoint_sha256: str,
    run_id: str,
    campaign_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if destination.exists():
        raise RfdetrSegmentationTrainingError(f"bundle directory already exists: {destination}")
    destination.mkdir(parents=True)
    bundled_checkpoint = destination / RFDETR_SEGMENTATION_FINAL_CHECKPOINT
    shutil.copy2(checkpoint, bundled_checkpoint)
    if _file_digest(bundled_checkpoint) != checkpoint_sha256:
        raise RfdetrSegmentationTrainingError("segmentation checkpoint changed during bundling")
    recipe = {
        "schema_version": RFDETR_SEGMENTATION_RECIPE_SCHEMA,
        "model": inputs["model"],
        "package": {"name": "rfdetr", "version": RFDETR_SEGMENTATION_PACKAGE_VERSION},
        "pretrained_checkpoint": {
            "name": RFDETR_SEGMENTATION_CHECKPOINT_NAME,
            "sha256": inputs["pretrained_sha256"],
        },
        "training_arguments": inputs["training_arguments"],
        "subset_digest": inputs["subset"]["subset_digest"],
        "materialization_digest": inputs["materialization_digest"],
    }
    recipe["recipe_digest"] = _digest(recipe)
    manifest: dict[str, Any] = {
        "schema_version": RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
        "component": "visible-card-segmentation",
        "quality_state": "unreviewed",
        "model": inputs["model"],
        "model_variant": RFDETR_SEGMENTATION_MODEL_VARIANT,
        "package": {"name": "rfdetr", "version": RFDETR_SEGMENTATION_PACKAGE_VERSION},
        "class_map": {"1": "visible_card"},
        "input_size": [RFDETR_SEGMENTATION_INPUT_SIZE, RFDETR_SEGMENTATION_INPUT_SIZE],
        "confidence_threshold": RFDETR_SEGMENTATION_CONFIDENCE_THRESHOLD,
        "materialization_digest": inputs["materialization_digest"],
        "subset_digest": inputs["subset"]["subset_digest"],
        "training_device": inputs["device"],
        "runner": inputs["runner"],
        "run_id": run_id,
        "pretrained_checkpoint": {
            "name": RFDETR_SEGMENTATION_CHECKPOINT_NAME,
            "sha256": inputs["pretrained_sha256"],
        },
        "recipe": recipe,
        "checkpoint_file": bundled_checkpoint.name,
        "checkpoint_sha256": checkpoint_sha256,
        "files": {bundled_checkpoint.name: checkpoint_sha256},
        "dependency_versions": _environment()["packages"],
        "code_revision": _code_revision(),
    }
    if campaign_receipt is not None:
        manifest["campaign_id"] = campaign_receipt["campaign_id"]
        manifest["campaign_manifest"] = {
            "manifest_digest": campaign_receipt["manifest_digest"],
            "file_sha256": campaign_receipt["file_sha256"],
        }
    manifest["bundle_digest"] = _digest(_stable_bundle_manifest(manifest))
    _write_json(destination / "manifest.json", manifest)
    return manifest


def _base_record(config: RfdetrSegmentationTrainingConfig, started: float) -> dict[str, Any]:
    output = config.output_dir.expanduser().resolve()
    reviewed = config.campaign_manifest is not None
    stages = {
        "inputs": "pending",
        "subset": "pending",
        "training": "pending",
        "metrics": "pending",
        "bundle": "pending",
        "reload": "pending",
        "inference": "pending",
    }
    return {
        "schema_version": (
            RFDETR_REVIEWED_DETECTOR_SMOKE_RUN_SCHEMA
            if reviewed
            else RFDETR_SEGMENTATION_TRAINING_RUN_SCHEMA
        ),
        "run_id": (
            f"rfdetr-visible-card-detector-m2-smoke-{int(started)}"
            if reviewed
            else f"rfdetr-segmentation-m2-{int(started)}"
        ),
        "status": "failed",
        "runner": config.runner,
        "device": config.device,
        "config": {
            "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
            "pretrained_checkpoint": str(config.pretrained_checkpoint.expanduser().resolve()),
            "output_dir": str(output),
            "campaign_manifest": (
                str(config.campaign_manifest.expanduser().resolve())
                if config.campaign_manifest is not None
                else None
            ),
            "train_image_count": config.train_image_count,
            "validation_image_count": config.validation_image_count,
        },
        "stages": stages,
        "started_at": datetime.fromtimestamp(started, tz=UTC).isoformat(),
        "environment": _environment(),
        "command": ["table-analyzer", *sys.argv[1:]],
        "resource_facts": _resource_facts(config.device),
        "code_revision": _code_revision(),
        "resumable": {
            "supported": True,
            "run_path": str(output / "run.json"),
            "next_stage": "inputs",
        },
    }


def _campaign_base_record(
    config: RfdetrSegmentationCampaignTrainingConfig, started: float
) -> dict[str, Any]:
    output = config.output_dir.expanduser().resolve()
    return {
        "schema_version": RFDETR_SEGMENTATION_CAMPAIGN_RUN_SCHEMA,
        "run_id": f"rfdetr-segmentation-m3-training-{int(started)}",
        "status": "failed",
        "runner": config.runner,
        "device": config.device,
        "config": _campaign_config(config, output),
        "stages": {
            "inputs": "pending",
            "dataset": "pending",
            "training": "pending",
            "metrics": "pending",
            "bundle": "pending",
        },
        "started_at": datetime.fromtimestamp(started, tz=UTC).isoformat(),
        "environment": _environment(),
        "command": ["table-analyzer", *sys.argv[1:]],
        "resource_facts": _resource_facts(config.device),
        "code_revision": _code_revision(),
        "resumable": {
            "supported": True,
            "run_path": str(output / "run.json"),
            "next_stage": "inputs",
        },
    }


def _campaign_config(
    config: RfdetrSegmentationCampaignTrainingConfig, output: Path
) -> dict[str, Any]:
    values = {
        "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
        "campaign_manifest": str(config.campaign_manifest.expanduser().resolve()),
        "pretrained_checkpoint": str(config.pretrained_checkpoint.expanduser().resolve()),
        "output_dir": str(output),
    }
    if config.resume is not None:
        values["resume"] = str(config.resume.expanduser().resolve())
    return values


def _validate_campaign_resume(
    config: RfdetrSegmentationCampaignTrainingConfig, output: Path
) -> Path | None:
    if config.resume is None:
        return None
    resume = config.resume.expanduser().resolve()
    if not resume.is_file() or resume.stat().st_size == 0:
        raise RfdetrSegmentationTrainingError(
            f"resume checkpoint does not exist or is empty: {resume}"
        )
    training_output = (output / "rfdetr").resolve()
    try:
        resume.relative_to(training_output)
    except ValueError as error:
        raise RfdetrSegmentationTrainingError(
            "resume checkpoint must be inside the campaign output's rfdetr directory"
        ) from error
    return resume


def _mark_stage(record: dict[str, Any], stage: str, status: str) -> None:
    record["stages"][stage] = status
    pending = next(
        (name for name, value in record["stages"].items() if value == "pending"),
        None,
    )
    record["resumable"]["next_stage"] = pending


def _real_frame_request(image: Mapping[str, Any], image_path: Path, *, campaign_id: str) -> Any:
    from .visible_cards import VisibleCardRequest

    return VisibleCardRequest(
        package_id=f"{campaign_id}:{image['recording_id']}",
        frame_part_name=str(image["event_id"]),
        target_offset_ms=0,
        image_bytes=image_path.read_bytes(),
        width=int(image["width"]),
        height=int(image["height"]),
        provider="local-rfdetr-segmentation",
        model=RFDETR_SEGMENTATION_PROVIDER_MODEL,
    )


def _run_real_inference(
    bundle_path: Path,
    validation_image: Mapping[str, Any],
    staged_dataset: Path,
    device: str,
    *,
    campaign_id: str,
) -> dict[str, Any]:
    from .visible_cards import LocalVisibleCardSegmentationProvider

    image_path = (
        staged_dataset
        / "valid"
        / _safe_relative(validation_image["file_name"], "validation image.file_name")
    )
    provider = LocalVisibleCardSegmentationProvider(bundle_path, device=device)  # type: ignore[arg-type]
    result = provider.propose(
        _real_frame_request(validation_image, image_path, campaign_id=campaign_id)
    )
    if result.status != "ok" or not result.proposals:
        raise RfdetrSegmentationTrainingError(
            f"segmentation provider did not return a visible-region mask: {result.error}"
        )
    first = result.proposals[0]
    return {
        "status": result.status,
        "provider": provider.name,
        "bundle_schema": provider.bundle_identity["schema_version"],
        "frame": {
            "recording_id": validation_image["recording_id"],
            "event_id": validation_image["event_id"],
            "image_sha256": validation_image["sha256"],
        },
        "proposal_count": len(result.proposals),
        "polygon_point_count": len(first.polygon),
        "box": first.box_2d.to_mapping(),
        "geometry_source": result.raw_response["detections"][0]["geometry_source"],
        "latency_ms": result.latency_ms,
    }


def _reload_checkpoint(checkpoint: Path, device: str) -> dict[str, Any]:
    model_class = _import_segmentation_model()
    model = model_class.from_checkpoint(
        str(checkpoint),
        num_classes=1,
        resolution=RFDETR_SEGMENTATION_INPUT_SIZE,
        device=device,
    )
    if type(model).__name__ != RFDETR_SEGMENTATION_MODEL_CLASS:
        raise RfdetrSegmentationTrainingError(
            f"segmentation checkpoint reloaded as {type(model).__name__}, "
            f"not {RFDETR_SEGMENTATION_MODEL_CLASS}"
        )
    return {"status": "reloaded", "model_class": type(model).__name__}


def run_rfdetr_segmentation_training(
    config: RfdetrSegmentationTrainingConfig,
) -> dict[str, Any]:
    """Run the one-epoch segmentation smoke path and write a resumable run record."""

    started = time.time()
    output = config.output_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise RfdetrSegmentationTrainingError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    record = _base_record(config, started)
    run_path = output / "run.json"
    try:
        view = _load_materialization_view(config.dataset_dir)
        pretrained = config.pretrained_checkpoint.expanduser().resolve()
        if not pretrained.is_file():
            raise RfdetrSegmentationTrainingError(
                f"pretrained checkpoint does not exist: {pretrained}"
            )
        pretrained_sha256 = _file_digest(pretrained)
        campaign_receipt = None
        if config.campaign_manifest is not None:
            campaign_receipt = _verify_campaign_manifest(
                view, config.campaign_manifest, pretrained_sha256
            )
        _mark_stage(record, "inputs", "completed")
        staged_dataset = output / "smoke-dataset"
        staged = _stage_smoke_dataset(
            view,
            staged_dataset,
            train_count=config.train_image_count,
            validation_count=config.validation_image_count,
            subset_schema=(
                "rfdetr-visible-card-detector-smoke-subset/v1"
                if campaign_receipt is not None
                else "rfdetr-segmentation-smoke-subset/v1"
            ),
        )
        _mark_stage(record, "subset", "completed")
        training_output = output / "rfdetr"
        model_arguments = _model_arguments(pretrained)
        training_arguments = _training_arguments(staged_dataset, training_output, config.device)
        inputs = {
            "runner": config.runner,
            "device": config.device,
            "materialization_digest": view["manifest"]["materialization_digest"],
            "pretrained_sha256": pretrained_sha256,
            "subset": staged["subset"],
            "model": {
                "class": RFDETR_SEGMENTATION_MODEL_CLASS,
                "variant": RFDETR_SEGMENTATION_MODEL_VARIANT,
                "num_classes": 1,
                "resolution": RFDETR_SEGMENTATION_INPUT_SIZE,
            },
            "model_arguments": model_arguments,
            "training_arguments": training_arguments,
        }
        if campaign_receipt is not None:
            inputs["campaign_manifest"] = campaign_receipt
        checkpoint = (
            _run_fixture(inputs, staged_dataset, training_output)
            if config.runner == "fixture"
            else _run_rfdetr(inputs, staged_dataset, training_output)
        )
        _mark_stage(record, "training", "completed")
        if _file_digest(checkpoint) == pretrained_sha256:
            raise RfdetrSegmentationTrainingError(
                "trained segmentation checkpoint is identical to pretrained input"
            )
        losses = _metric_evidence(training_output, keywords=("loss",))
        metrics = _metric_evidence(
            training_output,
            keywords=("map", "ap", "recall", "false", "duplicate", "empty"),
        )
        _mark_stage(record, "metrics", "completed")
        checkpoint_sha256 = _file_digest(checkpoint)
        bundle_manifest = _write_bundle(
            output / "bundle",
            inputs=inputs,
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha256,
            run_id=record["run_id"],
            campaign_receipt=campaign_receipt,
        )
        bundle = load_rfdetr_segmentation_bundle(output / "bundle")
        _mark_stage(record, "bundle", "completed")
        if config.runner == "fixture":
            reload_result = {
                "status": "fixture_skipped",
                "model_class": RFDETR_SEGMENTATION_MODEL_CLASS,
            }
            inference_result = {"status": "fixture_skipped"}
            _mark_stage(record, "reload", "skipped")
            _mark_stage(record, "inference", "skipped")
        else:
            reload_result = _reload_checkpoint(bundle.checkpoint_path, config.device)
            _mark_stage(record, "reload", "completed")
            inference_result = _run_real_inference(
                bundle.root,
                staged["validation_frame"],
                staged_dataset,
                config.device,
                campaign_id=(
                    campaign_receipt["campaign_id"]
                    if campaign_receipt is not None
                    else "0067-m0-rfdetr-segmentation"
                ),
            )
            _mark_stage(record, "inference", "completed")
        record.update(
            {
                "status": "completed",
                "campaign_id": (
                    campaign_receipt["campaign_id"]
                    if campaign_receipt is not None
                    else "0067-m0-rfdetr-segmentation"
                ),
                "model": inputs["model"],
                "model_arguments": model_arguments,
                "training_arguments": training_arguments,
                "materialization_digest": inputs["materialization_digest"],
                "campaign_manifest": campaign_receipt,
                "pretrained_checkpoint": {
                    "path": str(pretrained),
                    "name": RFDETR_SEGMENTATION_CHECKPOINT_NAME,
                    "sha256": pretrained_sha256,
                },
                "subset": staged["subset"],
                "loss_confirmation": losses,
                "validation_metrics": metrics,
                "checkpoint": {
                    "file": checkpoint.name,
                    "sha256": checkpoint_sha256,
                    "pretrained_sha256": pretrained_sha256,
                    "weights_differ": True,
                },
                "bundle": {
                    "path": str(bundle.root),
                    "schema_version": bundle_manifest["schema_version"],
                    "bundle_digest": bundle_manifest["bundle_digest"],
                    "manifest_sha256": _file_digest(bundle.root / "manifest.json"),
                },
                "reload": reload_result,
                "inference": inference_result,
            }
        )
        record["resumable"]["next_stage"] = None
    except Exception as error:
        record["failure"] = {"type": type(error).__name__, "message": str(error)}
    record["finished_at"] = datetime.now(UTC).isoformat()
    _write_json(run_path, record)
    if record["status"] != "completed":
        raise RfdetrSegmentationTrainingError(record["failure"]["message"])
    return record


def run_rfdetr_segmentation_campaign_training(
    config: RfdetrSegmentationCampaignTrainingConfig,
) -> dict[str, Any]:
    """Run one frozen RF-DETR candidate on every M1 training sample."""

    started = time.time()
    output = config.output_dir.expanduser().resolve()
    resume = _validate_campaign_resume(config, output)
    manifest_schema = None
    if config.campaign_manifest.expanduser().is_file():
        with contextlib.suppress(RfdetrSegmentationTrainingError):
            manifest_schema = _read_json(
                config.campaign_manifest.expanduser().resolve(), "M0 campaign manifest"
            ).get("schema_version")
    reviewed = manifest_schema == RFDETR_REVIEWED_DETECTOR_MANIFEST_SCHEMA
    expected_schema = (
        RFDETR_REVIEWED_DETECTOR_CAMPAIGN_RUN_SCHEMA
        if reviewed
        else RFDETR_SEGMENTATION_CAMPAIGN_RUN_SCHEMA
    )
    if output.exists() and any(output.iterdir()):
        if resume is not None:
            existing_run = output / "run.json"
            if existing_run.is_file():
                existing_record = _read_json(existing_run, "RF-DETR campaign run record")
                if existing_record.get("status") == "completed":
                    raise RfdetrSegmentationTrainingError(
                        "campaign output is already completed; omit --resume to reuse it"
                    )
        else:
            existing_run = output / "run.json"
            if existing_run.is_file():
                record = _read_json(existing_run, "RF-DETR campaign run record")
                expected_config = _campaign_config(config, output)
                if (
                    record.get("schema_version") == expected_schema
                    and record.get("status") == "completed"
                    and record.get("runner") == config.runner
                    and record.get("device") == config.device
                    and record.get("config") == expected_config
                ):
                    try:
                        view = _load_materialization_view(config.dataset_dir)
                        pretrained = config.pretrained_checkpoint.expanduser().resolve()
                        current_receipt = _verify_campaign_manifest(
                            view, config.campaign_manifest, _file_digest(pretrained)
                        )
                        bundle_path = record.get("bundle", {}).get("path")
                        bundle = load_rfdetr_segmentation_bundle(bundle_path)
                        if (
                            record.get("materialization_digest")
                            == view["manifest"]["materialization_digest"]
                            and record.get("campaign_manifest", {}).get("manifest_digest")
                            == current_receipt["manifest_digest"]
                            and record.get("pretrained_checkpoint", {}).get("sha256")
                            == _file_digest(pretrained)
                            and (
                                not reviewed
                                or bundle.manifest.get("campaign_manifest", {}).get(
                                    "manifest_digest"
                                )
                                == current_receipt["manifest_digest"]
                            )
                        ):
                            return record
                    except (OSError, TypeError, ValueError, KeyError):
                        pass
            raise RfdetrSegmentationTrainingError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    record = _campaign_base_record(config, started)
    run_path = output / "run.json"
    try:
        view = _load_materialization_view(config.dataset_dir)
        pretrained = config.pretrained_checkpoint.expanduser().resolve()
        if not pretrained.is_file():
            raise RfdetrSegmentationTrainingError(
                f"pretrained checkpoint does not exist: {pretrained}"
            )
        pretrained_sha256 = _file_digest(pretrained)
        campaign_receipt = _verify_campaign_manifest(
            view, config.campaign_manifest, pretrained_sha256
        )
        reviewed = campaign_receipt.get("campaign_id") == RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID
        if reviewed:
            record["schema_version"] = RFDETR_REVIEWED_DETECTOR_CAMPAIGN_RUN_SCHEMA
            record["run_id"] = f"rfdetr-visible-card-detector-m2-training-{int(started)}"
            record["campaign_id"] = RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID
        _mark_stage(record, "inputs", "completed")
        staged_dataset = output / "campaign-dataset"
        subset_schema = (
            RFDETR_REVIEWED_DETECTOR_DATASET_SCHEMA
            if reviewed
            else RFDETR_SEGMENTATION_CAMPAIGN_DATASET_SCHEMA
        )
        staged = (
            _load_staged_campaign_dataset(view, staged_dataset, subset_schema=subset_schema)
            if resume is not None
            else _stage_campaign_dataset(view, staged_dataset, subset_schema=subset_schema)
        )
        _mark_stage(record, "dataset", "completed")
        training_output = output / "rfdetr"
        model_arguments = _campaign_model_arguments(pretrained)
        training_arguments = _campaign_training_arguments(
            staged_dataset, training_output, config.device, resume=resume
        )
        inputs = {
            "runner": config.runner,
            "device": config.device,
            "materialization_digest": view["manifest"]["materialization_digest"],
            "pretrained_sha256": pretrained_sha256,
            "subset": staged["subset"],
            "model": {
                "class": RFDETR_SEGMENTATION_MODEL_CLASS,
                "variant": RFDETR_SEGMENTATION_MODEL_VARIANT,
                "num_classes": 1,
                "resolution": RFDETR_SEGMENTATION_INPUT_SIZE,
            },
            "model_arguments": model_arguments,
            "training_arguments": training_arguments,
            "campaign_manifest": campaign_receipt,
        }
        if resume is not None:
            record["resumed_from"] = str(resume)
        checkpoint = (
            _run_fixture(inputs, staged_dataset, training_output)
            if config.runner == "fixture"
            else _run_rfdetr(inputs, staged_dataset, training_output)
        )
        _mark_stage(record, "training", "completed")
        if _file_digest(checkpoint) == pretrained_sha256:
            raise RfdetrSegmentationTrainingError(
                "trained segmentation checkpoint is identical to pretrained input"
            )
        losses = _metric_evidence(training_output, keywords=("loss",))
        metrics = _metric_evidence(
            training_output,
            keywords=("map", "ap", "recall", "false", "duplicate", "empty"),
        )
        _mark_stage(record, "metrics", "completed")
        checkpoint_sha256 = _file_digest(checkpoint)
        bundle_manifest = _write_bundle(
            output / "bundle",
            inputs=inputs,
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha256,
            run_id=record["run_id"],
            campaign_receipt=campaign_receipt if reviewed else None,
        )
        bundle = load_rfdetr_segmentation_bundle(output / "bundle")
        _mark_stage(record, "bundle", "completed")
        record.update(
            {
                "status": "completed",
                "campaign_id": campaign_receipt.get("campaign_id", "0067-m0-rfdetr-segmentation"),
                "duration_seconds": round(time.time() - started, 3),
                "budget_seconds": 7200,
                "checkpoint_selection": campaign_receipt.get(
                    "checkpoint_selection",
                    "RF-DETR checkpoint_best_total.pth",
                ),
                "campaign_manifest": campaign_receipt,
                "model": inputs["model"],
                "model_arguments": model_arguments,
                "training_arguments": training_arguments,
                "materialization_digest": inputs["materialization_digest"],
                "pretrained_checkpoint": {
                    "path": str(pretrained),
                    "name": RFDETR_SEGMENTATION_CHECKPOINT_NAME,
                    "sha256": pretrained_sha256,
                },
                "dataset": staged["subset"],
                "loss_confirmation": losses,
                "validation_metrics": metrics,
                "checkpoint": {
                    "file": checkpoint.name,
                    "sha256": checkpoint_sha256,
                    "pretrained_sha256": pretrained_sha256,
                    "weights_differ": True,
                },
                "bundle": {
                    "path": str(bundle.root),
                    "schema_version": bundle_manifest["schema_version"],
                    "bundle_digest": bundle_manifest["bundle_digest"],
                    "manifest_sha256": _file_digest(bundle.root / "manifest.json"),
                },
            }
        )
        record["resumable"]["next_stage"] = None
    except Exception as error:
        record["failure"] = {"type": type(error).__name__, "message": str(error)}
    record["finished_at"] = datetime.now(UTC).isoformat()
    _write_json(run_path, record)
    if record["status"] != "completed":
        raise RfdetrSegmentationTrainingError(record["failure"]["message"])
    return record


def load_rfdetr_segmentation_bundle(path: str | Path) -> RfdetrSegmentationBundle:
    """Validate a segmentation bundle before a provider loads its native checkpoint."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise RfdetrSegmentationTrainingError(f"segmentation bundle does not exist: {root}")
    manifest = _read_json(root / "manifest.json", "segmentation bundle manifest")
    if manifest.get("schema_version") != RFDETR_SEGMENTATION_BUNDLE_SCHEMA:
        raise RfdetrSegmentationTrainingError("segmentation bundle schema is unsupported")
    if manifest.get("component") != "visible-card-segmentation":
        raise RfdetrSegmentationTrainingError("segmentation bundle component is invalid")
    if manifest.get("quality_state") != "unreviewed":
        raise RfdetrSegmentationTrainingError("segmentation bundle quality state is invalid")
    if manifest.get("model", {}).get("class") != RFDETR_SEGMENTATION_MODEL_CLASS:
        raise RfdetrSegmentationTrainingError("segmentation bundle model class is invalid")
    if manifest.get("model_variant") != RFDETR_SEGMENTATION_MODEL_VARIANT:
        raise RfdetrSegmentationTrainingError("segmentation bundle model variant is invalid")
    if manifest.get("package") != {
        "name": "rfdetr",
        "version": RFDETR_SEGMENTATION_PACKAGE_VERSION,
    }:
        raise RfdetrSegmentationTrainingError("segmentation bundle package is not rfdetr 1.9.4")
    if manifest.get("class_map") != {"1": "visible_card"}:
        raise RfdetrSegmentationTrainingError("segmentation bundle class map is invalid")
    if manifest.get("input_size") != [
        RFDETR_SEGMENTATION_INPUT_SIZE,
        RFDETR_SEGMENTATION_INPUT_SIZE,
    ]:
        raise RfdetrSegmentationTrainingError("segmentation bundle input size is invalid")
    if manifest.get("confidence_threshold") != RFDETR_SEGMENTATION_CONFIDENCE_THRESHOLD:
        raise RfdetrSegmentationTrainingError("segmentation bundle confidence threshold is invalid")
    recipe = manifest.get("recipe")
    if not isinstance(recipe, dict) or recipe.get("recipe_digest") != _digest(
        {key: value for key, value in recipe.items() if key != "recipe_digest"}
    ):
        raise RfdetrSegmentationTrainingError("segmentation bundle recipe digest is stale")
    if manifest.get("bundle_digest") != _digest(_stable_bundle_manifest(manifest)):
        raise RfdetrSegmentationTrainingError("segmentation bundle digest does not match contents")
    files = manifest.get("files")
    checkpoint_name = manifest.get("checkpoint_file")
    if not isinstance(files, dict) or checkpoint_name not in files:
        raise RfdetrSegmentationTrainingError("segmentation bundle checkpoint is undeclared")
    for relative_name, expected in files.items():
        safe_name = _safe_relative(relative_name, "segmentation bundle file")
        file_path = root / safe_name
        if not file_path.is_file() or _assert_sha256(
            expected, f"bundle file {safe_name}"
        ) != _file_digest(file_path):
            raise RfdetrSegmentationTrainingError(
                f"segmentation bundle file is missing or has a different digest: {safe_name}"
            )
    if manifest.get("checkpoint_sha256") != files[checkpoint_name]:
        raise RfdetrSegmentationTrainingError("segmentation checkpoint digest is inconsistent")
    return RfdetrSegmentationBundle(
        root=root, manifest=manifest, checkpoint_path=root / checkpoint_name
    )


__all__ = [
    "RFDETR_SEGMENTATION_BUNDLE_SCHEMA",
    "RFDETR_SEGMENTATION_CAMPAIGN_DATASET_SCHEMA",
    "RFDETR_SEGMENTATION_CAMPAIGN_RUN_SCHEMA",
    "RFDETR_SEGMENTATION_CHECKPOINT_NAME",
    "RFDETR_SEGMENTATION_CONFIDENCE_THRESHOLD",
    "RFDETR_SEGMENTATION_FINAL_CHECKPOINT",
    "RFDETR_SEGMENTATION_INPUT_SIZE",
    "RFDETR_SEGMENTATION_MODEL_CLASS",
    "RFDETR_SEGMENTATION_MODEL_VARIANT",
    "RFDETR_SEGMENTATION_PACKAGE_VERSION",
    "RFDETR_SEGMENTATION_TRAINING_RUN_SCHEMA",
    "RfdetrSegmentationBundle",
    "RfdetrSegmentationCampaignTrainingConfig",
    "RfdetrSegmentationTrainingConfig",
    "RfdetrSegmentationTrainingError",
    "load_rfdetr_segmentation_bundle",
    "run_rfdetr_segmentation_campaign_training",
    "run_rfdetr_segmentation_training",
]
