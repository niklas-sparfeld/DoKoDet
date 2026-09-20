"""Train and bundle the epic 0071 M5 cluster-crop segmentation candidate.

The campaign consumes the frozen M4 crop view.  Real rows retain their 0072 scene lineage and
synthetic rows retain their frozen 0070 receipt.  The staged dataset links the materialized crop
bytes directly, so the fine-stage trainer never resizes a complete source frame.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .rfdetr_segmentation_training import (
    RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID,
    RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
    RFDETR_SEGMENTATION_CHECKPOINT_NAME,
    RFDETR_SEGMENTATION_FINAL_CHECKPOINT,
    RFDETR_SEGMENTATION_INPUT_SIZE,
    RFDETR_SEGMENTATION_MODEL_CLASS,
    RFDETR_SEGMENTATION_MODEL_VARIANT,
    RFDETR_SEGMENTATION_PACKAGE_VERSION,
    _code_revision,
    _environment,
    _import_segmentation_model,
    _install_mps_memory_guard,
    _requested_device_available,
    _resource_facts,
    _write_json,
    load_rfdetr_segmentation_bundle,
)

RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA = "rfdetr-cluster-crop-materialization/v1"
RFDETR_CLUSTER_CROP_CAMPAIGN_ID = "0071-m5-rfdetr-cluster-crop-segmentation"
RFDETR_CLUSTER_CROP_TRAINING_RUN_SCHEMA = "rfdetr-cluster-crop-training-run/v1"
RFDETR_CLUSTER_CROP_DATASET_SCHEMA = "rfdetr-cluster-crop-training-dataset/v1"
RFDETR_CLUSTER_CROP_RECIPE_SCHEMA = "rfdetr-cluster-crop-training-recipe/v1"
RFDETR_CLUSTER_CROP_PERTURBATION_POLICY = "quarter-span-diagonal-shift-v1"
RFDETR_CLUSTER_CROP_WALL_CLOCK_SECONDS = 7200
RFDETR_CLUSTER_CROP_SEED = 7102
_RUNNERS = frozenset({"fixture", "rfdetr"})
_DEVICES = frozenset({"cpu", "mps", "cuda"})
_SHA256_LENGTH = 64


class RfdetrClusterCropTrainingError(ValueError):
    """The frozen M5 cluster-crop campaign cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class RfdetrClusterCropTrainingConfig:
    """Inputs for the one bounded M5 fine-stage training campaign."""

    dataset_dir: Path
    initializer_bundle: Path
    output_dir: Path
    runner: Literal["fixture", "rfdetr"] = "rfdetr"
    device: Literal["cpu", "mps", "cuda"] = "mps"
    seed: int = RFDETR_CLUSTER_CROP_SEED

    def __post_init__(self) -> None:
        if self.runner not in _RUNNERS:
            raise RfdetrClusterCropTrainingError("runner must be fixture or rfdetr")
        if self.device not in _DEVICES:
            raise RfdetrClusterCropTrainingError("device must be cpu, mps, or cuda")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise RfdetrClusterCropTrainingError("seed must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class RfdetrClusterCropView:
    """Digest-checked M4 crop view with its two trainer partitions."""

    root: Path
    materialization: dict[str, Any]
    coco: dict[str, dict[str, Any]]
    lineage: dict[str, Any]
    materialization_digest: str


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RfdetrClusterCropTrainingError("campaign values must be finite JSON") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RfdetrClusterCropTrainingError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise RfdetrClusterCropTrainingError(f"{context} must be a JSON object: {path}")
    return value


def _safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RfdetrClusterCropTrainingError(f"{field} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RfdetrClusterCropTrainingError(f"{field} must stay below the dataset root")
    return path.as_posix()


def _assert_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise RfdetrClusterCropTrainingError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise RfdetrClusterCropTrainingError(f"{field} must be a SHA-256 digest") from error
    return value


def _load_coco(root: Path, partition: str) -> dict[str, Any]:
    coco = _read_json(root / partition / "_annotations.coco.json", f"M4 {partition} COCO")
    if coco.get("categories") != [{"id": 1, "name": "visible_card", "supercategory": "card"}]:
        raise RfdetrClusterCropTrainingError(f"M4 {partition} COCO category is not visible_card")
    images = coco.get("images")
    annotations = coco.get("annotations")
    if not isinstance(images, list) or not images or not isinstance(annotations, list):
        raise RfdetrClusterCropTrainingError(f"M4 {partition} COCO data is incomplete")
    image_ids: set[int] = set()
    crop_ids: set[str] = set()
    for image in images:
        if not isinstance(image, Mapping) or not isinstance(image.get("id"), int):
            raise RfdetrClusterCropTrainingError(f"M4 {partition} image is invalid")
        image_id = int(image["id"])
        if image_id in image_ids:
            raise RfdetrClusterCropTrainingError(f"M4 {partition} image IDs are not unique")
        image_ids.add(image_id)
        crop_id = image.get("crop_id")
        if not isinstance(crop_id, str) or not crop_id or crop_id in crop_ids:
            raise RfdetrClusterCropTrainingError(f"M4 {partition} crop IDs are not unique")
        crop_ids.add(crop_id)
        relative = _safe_relative(image.get("file_name"), f"M4 {partition} image.file_name")
        image_path = root / partition / relative
        if not image_path.is_file() or _file_digest(image_path) != _assert_digest(
            image.get("sha256"), f"M4 {partition} image.sha256"
        ):
            raise RfdetrClusterCropTrainingError(f"M4 image is missing or changed: {relative}")
        required = (
            "source_frame",
            "source_frame_sha256",
            "source_group_key",
            "cluster",
            "cluster_id",
            "transform",
            "perturbation",
            "dataset_origin",
        )
        if any(field not in image for field in required):
            raise RfdetrClusterCropTrainingError(
                f"M4 image {image_id} is missing crop or source lineage"
            )
        origin = image.get("dataset_origin")
        if origin not in {"real_0072", "synthetic_0070"}:
            raise RfdetrClusterCropTrainingError(f"M4 image {image_id} has an unknown origin")
        if partition == "valid" and origin != "real_0072":
            raise RfdetrClusterCropTrainingError("M4 validation must contain real 0072 crops only")
        if origin == "real_0072":
            if image.get("split") not in {"train", "validation"}:
                raise RfdetrClusterCropTrainingError("M4 real crop has an invalid split")
        elif partition != "train":
            raise RfdetrClusterCropTrainingError("0070 synthetic crops must be train-only")
    annotation_ids: set[int] = set()
    for annotation in annotations:
        if not isinstance(annotation, Mapping):
            raise RfdetrClusterCropTrainingError(f"M4 {partition} annotation is invalid")
        annotation_id = annotation.get("id")
        if not isinstance(annotation_id, int) or annotation_id in annotation_ids:
            raise RfdetrClusterCropTrainingError(f"M4 {partition} annotation IDs are not unique")
        annotation_ids.add(annotation_id)
        if annotation.get("image_id") not in image_ids or annotation.get("category_id") != 1:
            raise RfdetrClusterCropTrainingError(
                f"M4 {partition} annotation references an unknown image"
            )
        for field in (
            "crop_id",
            "cluster_id",
            "source_box",
            "crop_box",
            "source_geometry",
            "source_frame_sha256",
        ):
            if field not in annotation:
                raise RfdetrClusterCropTrainingError(
                    f"M4 annotation {annotation_id} is missing {field}"
                )
    return coco


def load_rfdetr_cluster_crop_view(path: str | Path) -> RfdetrClusterCropView:
    """Load the frozen M4 view and verify its generated files and target authority."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise RfdetrClusterCropTrainingError(f"M4 materialization does not exist: {root}")
    materialization = _read_json(root / "materialization.json", "M4 materialization")
    if materialization.get("schema_version") != RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA:
        raise RfdetrClusterCropTrainingError("dataset is not the 0071 M4 cluster-crop view")
    declared = _assert_digest(
        materialization.get("materialization_digest"), "materialization_digest"
    )
    core = {key: value for key, value in materialization.items() if key != "materialization_digest"}
    if declared != _digest(core):
        raise RfdetrClusterCropTrainingError("M4 materialization digest does not match contents")
    if materialization.get("campaign_id") != "0071-m4-rfdetr-cluster-crop-segmentation":
        raise RfdetrClusterCropTrainingError("M4 materialization belongs to another campaign")
    generated = materialization.get("generated_files")
    if not isinstance(generated, list) or not generated:
        raise RfdetrClusterCropTrainingError("M4 materialization has no generated file index")
    for entry in generated:
        if not isinstance(entry, Mapping):
            raise RfdetrClusterCropTrainingError("M4 generated file entry is invalid")
        relative = _safe_relative(entry.get("path"), "M4 generated file.path")
        generated_path = root / relative
        if not generated_path.is_file() or _file_digest(generated_path) != _assert_digest(
            entry.get("sha256"), f"M4 generated file {relative}.sha256"
        ):
            raise RfdetrClusterCropTrainingError(
                f"M4 generated file is missing or changed: {relative}"
            )
    lineage = _read_json(root / "lineage.json", "M4 lineage")
    if lineage.get("schema_version") != "rfdetr-cluster-crop-lineage/v1":
        raise RfdetrClusterCropTrainingError("M4 lineage schema is unsupported")
    if lineage.get("lineage_digest") != _digest(
        {key: value for key, value in lineage.items() if key != "lineage_digest"}
    ):
        raise RfdetrClusterCropTrainingError("M4 lineage digest does not match contents")
    records = lineage.get("records")
    if not isinstance(records, list):
        raise RfdetrClusterCropTrainingError("M4 lineage has no crop records")
    lineage_by_crop = {
        record.get("crop_id"): record for record in records if isinstance(record, Mapping)
    }
    if len(lineage_by_crop) != len(records):
        raise RfdetrClusterCropTrainingError("M4 lineage crop IDs are not unique")
    coco = {partition: _load_coco(root, partition) for partition in ("train", "valid")}
    source_groups: dict[str, str] = {}
    for partition, partition_coco in coco.items():
        for image in partition_coco["images"]:
            crop_id = str(image["crop_id"])
            record = lineage_by_crop.get(crop_id)
            if record is None:
                raise RfdetrClusterCropTrainingError(f"M4 lineage has no record for {crop_id}")
            if record.get("dataset_origin") != image.get("dataset_origin"):
                raise RfdetrClusterCropTrainingError(f"M4 lineage origin differs for {crop_id}")
            if image.get("dataset_origin") == "real_0072":
                scene_lineage = record.get("scene_lineage")
                if not isinstance(scene_lineage, Mapping) or scene_lineage.get("authority") != (
                    "0072_reviewed_card_scene_derived_visible_regions"
                ):
                    raise RfdetrClusterCropTrainingError(
                        f"real M4 crop {crop_id} has no 0072 scene authority"
                    )
                for field in (
                    "calibration_revision_id",
                    "calibration_digest",
                    "derived_region_receipt",
                ):
                    if field not in scene_lineage:
                        raise RfdetrClusterCropTrainingError(
                            f"real M4 crop {crop_id} is missing {field} lineage"
                        )
            else:
                scene_lineage = record.get("scene_lineage")
                if not isinstance(scene_lineage, Mapping) or scene_lineage.get("authority") != (
                    "0070_frozen_scene_receipt"
                ):
                    raise RfdetrClusterCropTrainingError(
                        f"synthetic M4 crop {crop_id} has no 0070 receipt authority"
                    )
                if not isinstance(scene_lineage.get("receipt"), Mapping):
                    raise RfdetrClusterCropTrainingError(
                        f"synthetic M4 crop {crop_id} has no receipt"
                    )
            group = image.get("source_group_key")
            if not isinstance(group, str) or not group:
                raise RfdetrClusterCropTrainingError(f"M4 crop {crop_id} has no source group")
            label = "train" if partition == "train" else "validation"
            previous = source_groups.setdefault(group, label)
            if previous != label:
                raise RfdetrClusterCropTrainingError(
                    f"M4 source group crosses train and validation: {group}"
                )
    return RfdetrClusterCropView(
        root=root,
        materialization=materialization,
        coco=coco,
        lineage=lineage,
        materialization_digest=declared,
    )


def _stage_dataset(view: RfdetrClusterCropView, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise RfdetrClusterCropTrainingError(f"staged dataset already exists: {destination}")
    destination.mkdir(parents=True)
    partition_images: dict[str, list[dict[str, Any]]] = {}
    annotation_ids: dict[str, list[int]] = {}
    for source_partition, trainer_partition in (("train", "train"), ("valid", "valid")):
        source_coco = view.coco[source_partition]
        image_root = destination / trainer_partition / "images"
        image_root.mkdir(parents=True)
        staged_images: list[dict[str, Any]] = []
        for image in source_coco["images"]:
            relative = _safe_relative(image["file_name"], f"M4 {source_partition} image.file_name")
            source = view.root / source_partition / relative
            target_name = Path(relative).name
            staged_path = image_root / target_name
            staged_path.symlink_to(source)
            staged_image = dict(image)
            staged_image["file_name"] = f"images/{target_name}"
            staged_images.append(staged_image)
        staged_annotations = [dict(annotation) for annotation in source_coco["annotations"]]
        annotation_ids[trainer_partition] = [
            int(annotation["id"]) for annotation in staged_annotations
        ]
        _write_json(
            destination / trainer_partition / "_annotations.coco.json",
            {
                "info": source_coco.get("info", {}),
                "licenses": source_coco.get("licenses", []),
                "images": staged_images,
                "annotations": staged_annotations,
                "categories": source_coco["categories"],
            },
        )
        partition_images[trainer_partition] = staged_images
    subset_core = {
        "schema_version": RFDETR_CLUSTER_CROP_DATASET_SCHEMA,
        "materialization_digest": view.materialization_digest,
        "train_image_count": len(partition_images["train"]),
        "validation_image_count": len(partition_images["valid"]),
        "train_image_ids": [int(image["id"]) for image in partition_images["train"]],
        "validation_image_ids": [int(image["id"]) for image in partition_images["valid"]],
        "train_source_groups": sorted(
            {str(image["source_group_key"]) for image in partition_images["train"]}
        ),
        "validation_source_groups": sorted(
            {str(image["source_group_key"]) for image in partition_images["valid"]}
        ),
        "synthetic_train_image_ids": [
            int(image["id"])
            for image in partition_images["train"]
            if image.get("dataset_origin") == "synthetic_0070"
        ],
        "annotation_ids": annotation_ids,
    }
    subset = {**subset_core, "subset_digest": _digest(subset_core)}
    _write_json(destination / "subset.json", subset)
    return {"subset": subset, "images": partition_images}


def _training_arguments(
    staged_dataset: Path, output: Path, device: str, seed: int
) -> dict[str, Any]:
    return {
        "dataset_dir": str(staged_dataset),
        "dataset_file": "roboflow",
        "output_dir": str(output),
        "epochs": 40,
        "batch_size": 1,
        "grad_accum_steps": 4,
        "num_workers": 0,
        "seed": seed,
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


def _fixture_checkpoint(inputs: Mapping[str, Any], output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / RFDETR_SEGMENTATION_FINAL_CHECKPOINT
    checkpoint.write_bytes(
        b"fixture-rfdetr-cluster-crop/v1\n"
        + hashlib.sha256(
            _canonical(
                {
                    "subset_digest": inputs["subset"]["subset_digest"],
                    "initializer_sha256": inputs["initializer_sha256"],
                    "model": RFDETR_SEGMENTATION_MODEL_CLASS,
                }
            )
        ).digest()
    )
    _write_json(output / "losses.json", {"train_loss": 0.19, "runner": "fixture"})
    _write_json(
        output / "metrics.json",
        {
            "val/mask_ap_50_95": 0.31,
            "val/recall": 0.72,
            "val/duplicate_predictions": 1,
            "val/exact_card_count_rate": 0.67,
            "val/overlap_separation_rate": 0.5,
        },
    )
    return checkpoint


def _rfdetr_checkpoint(inputs: Mapping[str, Any], output: Path) -> Path:
    if not _requested_device_available(str(inputs["device"])):
        raise RfdetrClusterCropTrainingError(
            f"requested training device is unavailable: {inputs['device']}; "
            "no fallback is permitted"
        )
    model_class = _import_segmentation_model()
    output.mkdir(parents=True, exist_ok=True)
    model = model_class(**inputs["model_arguments"])
    try:
        with _install_mps_memory_guard(str(inputs["device"]), output):
            model.train(**inputs["training_arguments"])
    except Exception as error:
        raise RfdetrClusterCropTrainingError(
            f"RF-DETR cluster-crop training failed: {error}"
        ) from error
    checkpoint = output / RFDETR_SEGMENTATION_FINAL_CHECKPOINT
    if not checkpoint.is_file():
        raise RfdetrClusterCropTrainingError(
            f"RF-DETR did not emit {RFDETR_SEGMENTATION_FINAL_CHECKPOINT}"
        )
    return checkpoint


def _bundle_manifest(
    destination: Path,
    *,
    inputs: Mapping[str, Any],
    checkpoint: Path,
    checkpoint_sha256: str,
    run_id: str,
    initializer: Mapping[str, Any],
) -> dict[str, Any]:
    if destination.exists():
        raise RfdetrClusterCropTrainingError(f"bundle directory already exists: {destination}")
    destination.mkdir(parents=True)
    bundled = destination / RFDETR_SEGMENTATION_FINAL_CHECKPOINT
    shutil.copy2(checkpoint, bundled)
    if _file_digest(bundled) != checkpoint_sha256:
        raise RfdetrClusterCropTrainingError("cluster-crop checkpoint changed during bundling")
    recipe = {
        "schema_version": RFDETR_CLUSTER_CROP_RECIPE_SCHEMA,
        "model": inputs["model"],
        "package": {"name": "rfdetr", "version": RFDETR_SEGMENTATION_PACKAGE_VERSION},
        "initializer_bundle": dict(initializer),
        "training_arguments": inputs["training_arguments"],
        "materialization_digest": inputs["materialization_digest"],
        "subset_digest": inputs["subset"]["subset_digest"],
        "crop_view": {
            "schema_version": RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA,
            "perturbation_policy": RFDETR_CLUSTER_CROP_PERTURBATION_POLICY,
            "train_only_synthetic": True,
        },
    }
    recipe["recipe_digest"] = _digest(recipe)
    manifest: dict[str, Any] = {
        "schema_version": RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
        "component": "visible-card-segmentation",
        "quality_state": "unreviewed",
        "campaign_id": RFDETR_CLUSTER_CROP_CAMPAIGN_ID,
        "model": inputs["model"],
        "model_variant": RFDETR_SEGMENTATION_MODEL_VARIANT,
        "package": {"name": "rfdetr", "version": RFDETR_SEGMENTATION_PACKAGE_VERSION},
        "class_map": {"1": "visible_card"},
        "input_size": [RFDETR_SEGMENTATION_INPUT_SIZE, RFDETR_SEGMENTATION_INPUT_SIZE],
        "confidence_threshold": 0.5,
        "materialization_digest": inputs["materialization_digest"],
        "subset_digest": inputs["subset"]["subset_digest"],
        "training_device": inputs["device"],
        "runner": inputs["runner"],
        "run_id": run_id,
        "initializer_bundle": dict(initializer),
        "pretrained_checkpoint": {
            "name": RFDETR_SEGMENTATION_CHECKPOINT_NAME,
            "sha256": inputs["initializer_sha256"],
        },
        "recipe": recipe,
        "checkpoint_file": bundled.name,
        "checkpoint_sha256": checkpoint_sha256,
        "files": {bundled.name: checkpoint_sha256},
        "dependency_versions": _environment()["packages"],
        "code_revision": _code_revision(),
    }
    manifest["bundle_digest"] = _digest(manifest)
    _write_json(destination / "manifest.json", manifest)
    return manifest


def _initializer_identity(path: Path) -> tuple[dict[str, Any], Path, str]:
    try:
        bundle = load_rfdetr_segmentation_bundle(path)
    except Exception as error:
        raise RfdetrClusterCropTrainingError(
            f"could not validate selected 0068 initializer bundle: {error}"
        ) from error
    if bundle.manifest.get("campaign_id") != RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID:
        raise RfdetrClusterCropTrainingError("initializer bundle is not the selected 0068 bundle")
    if bundle.manifest.get("model", {}).get("class") != RFDETR_SEGMENTATION_MODEL_CLASS:
        raise RfdetrClusterCropTrainingError("0068 initializer is not RFDETRSegMedium")
    checkpoint_sha256 = _file_digest(bundle.checkpoint_path)
    if bundle.manifest.get("checkpoint_sha256") != checkpoint_sha256:
        raise RfdetrClusterCropTrainingError("0068 initializer checkpoint digest is stale")
    identity = {
        "path": str(bundle.root),
        "schema_version": bundle.manifest["schema_version"],
        "bundle_digest": bundle.manifest["bundle_digest"],
        "manifest_sha256": _file_digest(bundle.root / "manifest.json"),
        "checkpoint_file": bundle.checkpoint_path.name,
        "checkpoint_sha256": checkpoint_sha256,
        "campaign_id": bundle.manifest.get("campaign_id"),
    }
    return identity, bundle.checkpoint_path, checkpoint_sha256


def _record_base(config: RfdetrClusterCropTrainingConfig, started: float) -> dict[str, Any]:
    output = config.output_dir.expanduser().resolve()
    return {
        "schema_version": RFDETR_CLUSTER_CROP_TRAINING_RUN_SCHEMA,
        "run_id": f"rfdetr-cluster-crop-m5-training-{int(started)}",
        "status": "failed",
        "campaign_id": RFDETR_CLUSTER_CROP_CAMPAIGN_ID,
        "runner": config.runner,
        "device": config.device,
        "config": {
            "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
            "initializer_bundle": str(config.initializer_bundle.expanduser().resolve()),
            "output_dir": str(output),
            "seed": config.seed,
        },
        "stages": {
            name: "pending" for name in ("inputs", "dataset", "training", "bundle", "reload")
        },
        "started_at": datetime.fromtimestamp(started, tz=UTC).isoformat(),
        "environment": _environment(),
        "resource_facts": _resource_facts(config.device),
        "code_revision": _code_revision(),
        "resumable": {
            "supported": True,
            "run_path": str(output / "run.json"),
            "next_stage": "inputs",
        },
    }


def _mark(record: dict[str, Any], stage: str, status: str) -> None:
    record["stages"][stage] = status
    record["resumable"]["next_stage"] = next(
        (name for name, value in record["stages"].items() if value == "pending"), None
    )


def run_rfdetr_cluster_crop_training(config: RfdetrClusterCropTrainingConfig) -> dict[str, Any]:
    """Run one frozen M5 fine-stage candidate and write a digest-checked bundle."""

    started = time.time()
    output = config.output_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise RfdetrClusterCropTrainingError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    record = _record_base(config, started)
    try:
        view = load_rfdetr_cluster_crop_view(config.dataset_dir)
        initializer, checkpoint, initializer_sha256 = _initializer_identity(
            config.initializer_bundle.expanduser().resolve()
        )
        _mark(record, "inputs", "completed")
        staged_dataset = output / "campaign-dataset"
        staged = _stage_dataset(view, staged_dataset)
        _mark(record, "dataset", "completed")
        training_output = output / "rfdetr"
        model = {
            "class": RFDETR_SEGMENTATION_MODEL_CLASS,
            "variant": RFDETR_SEGMENTATION_MODEL_VARIANT,
            "num_classes": 1,
            "resolution": RFDETR_SEGMENTATION_INPUT_SIZE,
        }
        model_arguments = {
            "num_classes": 1,
            "pretrain_weights": str(checkpoint),
            "resolution": RFDETR_SEGMENTATION_INPUT_SIZE,
            "amp": False,
        }
        training_arguments = _training_arguments(
            staged_dataset, training_output, config.device, config.seed
        )
        inputs = {
            "runner": config.runner,
            "device": config.device,
            "materialization_digest": view.materialization_digest,
            "initializer_sha256": initializer_sha256,
            "initializer": initializer,
            "subset": staged["subset"],
            "model": model,
            "model_arguments": model_arguments,
            "training_arguments": training_arguments,
        }
        checkpoint_path = (
            _fixture_checkpoint(inputs, training_output)
            if config.runner == "fixture"
            else _rfdetr_checkpoint(inputs, training_output)
        )
        _mark(record, "training", "completed")
        checkpoint_sha256 = _file_digest(checkpoint_path)
        if checkpoint_sha256 == initializer_sha256:
            raise RfdetrClusterCropTrainingError(
                "trained cluster-crop checkpoint is identical to the selected 0068 initializer"
            )
        bundle_manifest = _bundle_manifest(
            output / "bundle",
            inputs=inputs,
            checkpoint=checkpoint_path,
            checkpoint_sha256=checkpoint_sha256,
            run_id=record["run_id"],
            initializer=initializer,
        )
        bundle = load_rfdetr_segmentation_bundle(output / "bundle")
        _mark(record, "bundle", "completed")
        if config.runner == "fixture":
            reload_result = {
                "status": "fixture_skipped",
                "model_class": RFDETR_SEGMENTATION_MODEL_CLASS,
            }
            _mark(record, "reload", "skipped")
        else:
            model_class = _import_segmentation_model()
            loaded = model_class.from_checkpoint(
                str(bundle.checkpoint_path),
                num_classes=1,
                resolution=RFDETR_SEGMENTATION_INPUT_SIZE,
                device=config.device,
            )
            if type(loaded).__name__ != RFDETR_SEGMENTATION_MODEL_CLASS:
                raise RfdetrClusterCropTrainingError(
                    f"cluster-crop checkpoint reloaded as {type(loaded).__name__}, "
                    f"not {RFDETR_SEGMENTATION_MODEL_CLASS}"
                )
            reload_result = {"status": "reloaded", "model_class": type(loaded).__name__}
            _mark(record, "reload", "completed")
        train_images = staged["subset"]["train_image_count"]
        real_train = sum(
            1 for image in staged["images"]["train"] if image.get("dataset_origin") == "real_0072"
        )
        synthetic_train = train_images - real_train
        record.update(
            {
                "status": "completed",
                "duration_seconds": round(time.time() - started, 3),
                "budget_seconds": RFDETR_CLUSTER_CROP_WALL_CLOCK_SECONDS,
                "model": model,
                "model_arguments": model_arguments,
                "training_arguments": training_arguments,
                "initializer_bundle": initializer,
                "materialization_digest": view.materialization_digest,
                "target_authority": {
                    "real": "0072_reviewed_card_scene_derived_visible_regions",
                    "synthetic": "0070_frozen_scene_receipt",
                },
                "dataset": {
                    **staged["subset"],
                    "real_train_image_count": real_train,
                    "synthetic_train_image_count": synthetic_train,
                    "validation_real_only": True,
                },
                "checkpoint": {
                    "file": checkpoint_path.name,
                    "sha256": checkpoint_sha256,
                    "initializer_sha256": initializer_sha256,
                    "weights_differ": True,
                },
                "bundle": {
                    "path": str(bundle.root),
                    "schema_version": bundle_manifest["schema_version"],
                    "bundle_digest": bundle_manifest["bundle_digest"],
                    "manifest_sha256": _file_digest(bundle.root / "manifest.json"),
                },
                "reload": reload_result,
            }
        )
        record["resumable"]["next_stage"] = None
    except Exception as error:
        record["failure"] = {"type": type(error).__name__, "message": str(error)}
    record["finished_at"] = datetime.now(UTC).isoformat()
    _write_json(output / "run.json", record)
    if record["status"] != "completed":
        raise RfdetrClusterCropTrainingError(record["failure"]["message"])
    return record


__all__ = [
    "RFDETR_CLUSTER_CROP_CAMPAIGN_ID",
    "RFDETR_CLUSTER_CROP_DATASET_SCHEMA",
    "RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA",
    "RFDETR_CLUSTER_CROP_RECIPE_SCHEMA",
    "RFDETR_CLUSTER_CROP_TRAINING_RUN_SCHEMA",
    "RfdetrClusterCropTrainingConfig",
    "RfdetrClusterCropTrainingError",
    "RfdetrClusterCropView",
    "load_rfdetr_cluster_crop_view",
    "run_rfdetr_cluster_crop_training",
]
