"""Train, evaluate, and bundle the epic 0071 coarse card-cluster detector.

The module consumes only the deterministic M2 full-frame COCO view.  It has one frozen
``RFDETRSmall`` candidate, one validation threshold calibration, and one native checkpoint
bundle.  The fixture runner exists for contract tests; the real runner never falls back to a
different device or model when a local resource is unavailable.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from PIL import Image

from .rfdetr_import import block_pyav_import
from .visible_card_cascade import CoarseProposal, PixelBox, build_cascade_layout

RFDETR_CARD_CLUSTER_TRAINING_RUN_SCHEMA = "rfdetr-card-cluster-training-run/v1"
RFDETR_CARD_CLUSTER_EVALUATION_SCHEMA = "rfdetr-card-cluster-validation/v1"
RFDETR_CARD_CLUSTER_BUNDLE_SCHEMA = "rfdetr-card-cluster-bundle/v1"
RFDETR_CARD_CLUSTER_RECIPE_SCHEMA = "rfdetr-card-cluster-training-recipe/v1"
RFDETR_CARD_CLUSTER_MATERIALIZATION_SCHEMA = "rfdetr-card-cluster-materialization/v1"
RFDETR_CARD_CLUSTER_MODEL_CLASS = "RFDETRSmall"
RFDETR_CARD_CLUSTER_MODEL_VARIANT = "rfdetr-small"
RFDETR_CARD_CLUSTER_PACKAGE_VERSION = "1.9.4"
RFDETR_CARD_CLUSTER_INPUT_SIZE = 512
RFDETR_CARD_CLUSTER_CHECKPOINT_NAME = "rf-detr-small.pt"
RFDETR_CARD_CLUSTER_FINAL_CHECKPOINT = "checkpoint_best_total.pth"
RFDETR_CARD_CLUSTER_CLASS_MAP = {"1": "card_cluster"}
RFDETR_CARD_CLUSTER_MATCH_IOU = 0.5
RFDETR_CARD_CLUSTER_CONTAINMENT_FLOOR = 0.98
RFDETR_CARD_CLUSTER_THRESHOLDS = tuple(round(0.05 + index * 0.05, 2) for index in range(19))
RFDETR_CARD_CLUSTER_WALL_CLOCK_SECONDS = 7200
RFDETR_CARD_CLUSTER_SEED = 7101
_DEVICES = frozenset({"cpu", "mps", "cuda"})
_RUNNERS = frozenset({"fixture", "rfdetr"})
_SHA256 = 64


class RfdetrCardClusterTrainingError(ValueError):
    """The frozen card-cluster campaign cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class RfdetrCardClusterTrainingConfig:
    """Inputs for the one bounded M3 training campaign."""

    dataset_dir: Path
    pretrained_checkpoint: Path
    output_dir: Path
    runner: Literal["fixture", "rfdetr"] = "rfdetr"
    device: Literal["cpu", "mps", "cuda"] = "mps"
    seed: int = RFDETR_CARD_CLUSTER_SEED
    resume: Path | None = None

    def __post_init__(self) -> None:
        if self.runner not in _RUNNERS:
            raise RfdetrCardClusterTrainingError("runner must be fixture or rfdetr")
        if self.device not in _DEVICES:
            raise RfdetrCardClusterTrainingError("device must be cpu, mps, or cuda")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise RfdetrCardClusterTrainingError("seed must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class RfdetrCardClusterEvaluationConfig:
    """Inputs for validation threshold calibration."""

    dataset_dir: Path
    checkpoint: Path
    output_dir: Path
    device: Literal["cpu", "mps", "cuda"] = "mps"
    runner: Literal["fixture", "rfdetr"] = "rfdetr"


@dataclass(frozen=True, slots=True)
class RfdetrCardClusterBundle:
    """A digest-checked native RF-DETR Small checkpoint bundle."""

    root: Path
    manifest: dict[str, Any]
    checkpoint_path: Path


PredictionProvider = Callable[[Path, int, int], Sequence[Mapping[str, Any]]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RfdetrCardClusterTrainingError("campaign values must be finite JSON") from error


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
        raise RfdetrCardClusterTrainingError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise RfdetrCardClusterTrainingError(f"{context} must be a JSON object")
    return value


def _safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RfdetrCardClusterTrainingError(f"{field} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RfdetrCardClusterTrainingError(f"{field} must stay below its dataset root")
    return path.as_posix()


def _assert_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256:
        raise RfdetrCardClusterTrainingError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise RfdetrCardClusterTrainingError(f"{field} must be a SHA-256 digest") from error
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RfdetrCardClusterTrainingError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise RfdetrCardClusterTrainingError(f"{field} must be finite")
    return result


def default_rfdetr_card_cluster_recipe(
    *, pretrained_checkpoint: str | Path | None = None, device: str = "mps"
) -> dict[str, Any]:
    """Return the frozen M3 model, recipe, budget, and threshold policy."""

    if device not in _DEVICES:
        raise RfdetrCardClusterTrainingError("device must be cpu, mps, or cuda")
    checkpoint = (
        Path(pretrained_checkpoint).expanduser().resolve() if pretrained_checkpoint else None
    )
    checkpoint_digest = (
        _file_digest(checkpoint) if checkpoint is not None and checkpoint.is_file() else None
    )
    return {
        "schema_version": RFDETR_CARD_CLUSTER_RECIPE_SCHEMA,
        "model": {
            "class": RFDETR_CARD_CLUSTER_MODEL_CLASS,
            "variant": RFDETR_CARD_CLUSTER_MODEL_VARIANT,
            "class_names": ["card_cluster"],
            "num_classes": 1,
            "resolution": [RFDETR_CARD_CLUSTER_INPUT_SIZE, RFDETR_CARD_CLUSTER_INPUT_SIZE],
        },
        "package": {"name": "rfdetr", "version": RFDETR_CARD_CLUSTER_PACKAGE_VERSION},
        "pretrained_checkpoint": {
            "name": RFDETR_CARD_CLUSTER_CHECKPOINT_NAME,
            "path": str(checkpoint) if checkpoint else None,
            "sha256": checkpoint_digest,
        },
        "augmentation": {
            "policy_id": "rfdetr-default-v1",
            "multi_scale": True,
            "expanded_scales": True,
            "do_random_resize_via_padding": False,
            "use_ema": True,
        },
        "training": {
            "batch_size": 1,
            "grad_accum_steps": 4,
            "effective_batch_size": 4,
            "epochs": 40,
            "seed": RFDETR_CARD_CLUSTER_SEED,
            "num_workers": 0,
            "device": device,
            "mixed_precision": False,
            "output_dir_name": "rfdetr-card-cluster-0071",
        },
        "early_stopping": {
            "enabled": True,
            "monitor": "val/box_ap_50_95",
            "patience": 8,
            "min_delta": 0.001,
        },
        "budget": {
            "wall_clock_seconds": RFDETR_CARD_CLUSTER_WALL_CLOCK_SECONDS,
            "candidate_count": 1,
            "sweep": False,
        },
        "validation": {
            "thresholds": list(RFDETR_CARD_CLUSTER_THRESHOLDS),
            "match_iou": RFDETR_CARD_CLUSTER_MATCH_IOU,
            "crop_containment_recall_floor": RFDETR_CARD_CLUSTER_CONTAINMENT_FLOOR,
            "checkpoint_selection": "highest_validation_box_ap_50_95_then_cluster_recall",
            "threshold_selection": "highest_confidence_meeting_crop_containment_floor",
            "metrics": [
                "cluster_recall",
                "reviewed_card_crop_containment_recall",
                "missed_cards",
                "extra_clusters",
                "clusters_per_frame",
                "crop_area_relative_to_source_area",
                "coarse_latency_ms",
            ],
        },
        "data_contract": {
            "category": "card_cluster",
            "target_source": "reviewed_visible_card_tight_box_connected_components",
            "train_partition": "train",
            "validation_partition": "validation",
            "test_partition": None,
            "processor_predictions_as_targets": False,
        },
    }


def _environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("rfdetr", "torch", "torchvision", "supervision"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {"python": sys.version, "platform": platform.platform(), "packages": packages}


def _code_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _resource_facts(device: str) -> dict[str, Any]:
    facts: dict[str, Any] = {"requested_device": device, "selected_device": device}
    try:
        import torch
    except ImportError:
        facts.update({"torch_available": False, "device_available": device == "cpu"})
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


def _requested_device_available(device: str) -> bool:
    return bool(_resource_facts(device)["device_available"])


@contextmanager
def _resource_guard(device: str, output: Path, *, budget_seconds: int) -> Any:
    """Guard one run against unavailable devices and an exceeded wall-clock budget."""

    if not _requested_device_available(device):
        raise RfdetrCardClusterTrainingError(
            f"requested training device is unavailable: {device}; no fallback is permitted"
        )
    started = time.monotonic()
    yield
    elapsed = time.monotonic() - started
    _write_json(
        output / "resource-guard.json",
        {
            "requested_device": device,
            "selected_device": device,
            "wall_clock_seconds": budget_seconds,
            "elapsed_wall_clock_seconds": round(elapsed, 3),
            "within_budget": elapsed <= budget_seconds,
        },
    )
    if elapsed > budget_seconds:
        raise RfdetrCardClusterTrainingError(
            f"training exceeded the {budget_seconds}s wall-clock resource bound"
        )


def _load_materialization_view(root_value: str | Path) -> dict[str, Any]:
    """Load and hash-check the M2 train/validation view."""

    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise RfdetrCardClusterTrainingError(f"card-cluster materialization does not exist: {root}")
    materialization = _read_json(root / "materialization.json", "M2 materialization")
    if materialization.get("schema_version") != RFDETR_CARD_CLUSTER_MATERIALIZATION_SCHEMA:
        raise RfdetrCardClusterTrainingError("dataset is not the 0071 M2 card-cluster view")
    declared = _assert_digest(
        materialization.get("materialization_digest"), "materialization_digest"
    )
    core = {key: value for key, value in materialization.items() if key != "materialization_digest"}
    if declared != _digest(core):
        raise RfdetrCardClusterTrainingError("M2 materialization digest does not match contents")
    generated = materialization.get("generated_files")
    if not isinstance(generated, list) or not generated:
        raise RfdetrCardClusterTrainingError("M2 materialization has no generated file index")
    for entry in generated:
        if not isinstance(entry, Mapping):
            raise RfdetrCardClusterTrainingError("M2 generated file entry is invalid")
        relative = _safe_relative(entry.get("path"), "M2 generated file path")
        path = root / relative
        if not path.is_file() or _assert_digest(entry.get("sha256"), relative) != _file_digest(
            path
        ):
            raise RfdetrCardClusterTrainingError(
                f"M2 generated file is missing or changed: {relative}"
            )
    coco_by_partition: dict[str, dict[str, Any]] = {}
    for partition in ("train", "valid"):
        coco = _read_json(root / partition / "_annotations.coco.json", f"M2 {partition} COCO")
        if coco.get("categories") != [{"id": 1, "name": "card_cluster", "supercategory": "card"}]:
            raise RfdetrCardClusterTrainingError(
                f"M2 {partition} COCO category is not card_cluster"
            )
        images = coco.get("images")
        annotations = coco.get("annotations")
        if not isinstance(images, list) or not images or not isinstance(annotations, list):
            raise RfdetrCardClusterTrainingError(f"M2 {partition} COCO data is incomplete")
        image_ids = set()
        for image in images:
            if not isinstance(image, Mapping) or not isinstance(image.get("id"), int):
                raise RfdetrCardClusterTrainingError(f"M2 {partition} image is invalid")
            image_id = int(image["id"])
            if image_id in image_ids:
                raise RfdetrCardClusterTrainingError(f"M2 {partition} image IDs are not unique")
            image_ids.add(image_id)
            relative = _safe_relative(image.get("file_name"), f"{partition}.file_name")
            path = root / partition / relative
            if not path.is_file() or _assert_digest(
                image.get("sha256"), "image.sha256"
            ) != _file_digest(path):
                raise RfdetrCardClusterTrainingError(f"M2 image is missing or changed: {relative}")
        if any(
            not isinstance(annotation, Mapping)
            or annotation.get("image_id") not in image_ids
            or annotation.get("category_id") != 1
            for annotation in annotations
        ):
            raise RfdetrCardClusterTrainingError(f"M2 {partition} annotations are invalid")
        coco_by_partition[partition] = coco
    lineage = _read_json(root / "lineage.json", "M2 lineage")
    if not isinstance(lineage.get("frames"), list):
        raise RfdetrCardClusterTrainingError("M2 lineage has no frames")
    lineage_by_image_path = {frame.get("image_path"): frame for frame in lineage["frames"]}
    for coco in coco_by_partition.values():
        for image in coco["images"]:
            if image.get("file_name") not in lineage_by_image_path:
                partition = str(image.get("trainer_partition"))
                expected = f"{partition}/{image['file_name']}"
                if expected not in lineage_by_image_path:
                    raise RfdetrCardClusterTrainingError(
                        f"M2 lineage has no source frame for image {image['id']}"
                    )
    return {
        "root": root,
        "materialization": materialization,
        "coco": coco_by_partition,
        "lineage": lineage,
        "materialization_digest": declared,
    }


def _stage_dataset(view: Mapping[str, Any], destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise RfdetrCardClusterTrainingError(f"staged dataset already exists: {destination}")
    root = Path(view["root"])
    destination.mkdir(parents=True)
    image_ids: dict[str, list[int]] = {}
    for source_partition, trainer_partition in (("train", "train"), ("valid", "valid")):
        source_coco = view["coco"][source_partition]
        image_root = destination / trainer_partition / "images"
        image_root.mkdir(parents=True)
        image_ids[trainer_partition] = []
        for image in source_coco["images"]:
            relative = _safe_relative(image["file_name"], "M2 image.file_name")
            source = root / source_partition / relative
            target = image_root / Path(relative).name
            target.symlink_to(source)
            image_ids[trainer_partition].append(int(image["id"]))
        _write_json(destination / trainer_partition / "_annotations.coco.json", source_coco)
    core = {
        "schema_version": "rfdetr-card-cluster-campaign-dataset/v1",
        "materialization_digest": view["materialization_digest"],
        "train_image_ids": image_ids["train"],
        "validation_image_ids": image_ids["valid"],
    }
    subset = {**core, "subset_digest": _digest(core)}
    _write_json(destination / "subset.json", subset)
    return {"root": destination, "subset": subset}


def _model_arguments(checkpoint: Path) -> dict[str, Any]:
    return {
        "num_classes": 1,
        "pretrain_weights": str(checkpoint),
        "resolution": RFDETR_CARD_CLUSTER_INPUT_SIZE,
        "amp": False,
    }


def _training_arguments(
    staged_dataset: Path, training_output: Path, device: str, seed: int
) -> dict[str, Any]:
    return {
        "dataset_dir": str(staged_dataset),
        "dataset_file": "roboflow",
        "output_dir": str(training_output),
        "epochs": 40,
        "batch_size": 1,
        "grad_accum_steps": 4,
        "num_workers": 0,
        "seed": seed,
        "resolution": RFDETR_CARD_CLUSTER_INPUT_SIZE,
        "device": device,
        "class_names": ["card_cluster"],
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


def _import_model() -> Any:
    try:
        with block_pyav_import():
            from rfdetr import RFDETRSmall
    except ImportError as error:
        raise RfdetrCardClusterTrainingError(
            "RF-DETR Small training requires rfdetr 1.9.4 with training extras"
        ) from error
    try:
        version = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError as error:
        raise RfdetrCardClusterTrainingError("RF-DETR package metadata is not installed") from error
    if version != RFDETR_CARD_CLUSTER_PACKAGE_VERSION:
        raise RfdetrCardClusterTrainingError(
            f"rfdetr version {version} does not match the frozen "
            f"{RFDETR_CARD_CLUSTER_PACKAGE_VERSION}"
        )
    return RFDETRSmall


def _run_fixture(view: Mapping[str, Any], pretrained: str, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / RFDETR_CARD_CLUSTER_FINAL_CHECKPOINT
    checkpoint.write_bytes(
        b"fixture-rfdetr-small-card-cluster/v1\n"
        + hashlib.sha256(
            _canonical(
                {"materialization": view["materialization_digest"], "pretrained": pretrained}
            )
        ).digest()
    )
    _write_json(output / "losses.json", {"loss": [1.0, 0.5, 0.25], "runner": "fixture"})
    _write_json(output / "metrics.json", {"val/box_ap_50_95": 0.25, "val/cluster_recall": 1.0})
    return checkpoint


def _run_rfdetr(
    staged_dataset: Path,
    pretrained: Path,
    output: Path,
    device: str,
    seed: int,
) -> Path:
    model_class = _import_model()
    output.mkdir(parents=True, exist_ok=True)
    model = model_class(**_model_arguments(pretrained))
    model.train(**_training_arguments(staged_dataset, output, device, seed))
    checkpoint = output / RFDETR_CARD_CLUSTER_FINAL_CHECKPOINT
    if not checkpoint.is_file():
        raise RfdetrCardClusterTrainingError(
            f"RF-DETR did not emit {RFDETR_CARD_CLUSTER_FINAL_CHECKPOINT}"
        )
    return checkpoint


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _as_sequence(value: Any, field: str) -> list[Any]:
    if value is None:
        raise RfdetrCardClusterTrainingError(f"RF-DETR output has no {field}")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (str, bytes)):
        raise RfdetrCardClusterTrainingError(f"RF-DETR {field} is not a sequence")
    try:
        return list(value)
    except TypeError as error:
        raise RfdetrCardClusterTrainingError(f"RF-DETR {field} is not a sequence") from error


def _prediction_rows(model: Any, image_path: Path, width: int, height: int) -> list[dict[str, Any]]:
    try:
        with Image.open(image_path) as source:
            image = source.convert("RGB").copy()
        result = model.predict(
            image,
            threshold=min(RFDETR_CARD_CLUSTER_THRESHOLDS),
            shape=(RFDETR_CARD_CLUSTER_INPUT_SIZE, RFDETR_CARD_CLUSTER_INPUT_SIZE),
            include_source_image=False,
        )
        boxes = _as_sequence(_field(result, "xyxy"), "xyxy")
        scores = _as_sequence(_field(result, "confidence"), "confidence")
        classes = _as_sequence(_field(result, "class_id"), "class_id")
    except RfdetrCardClusterTrainingError:
        raise
    except Exception as error:
        raise RfdetrCardClusterTrainingError(
            f"RF-DETR inference failed for {image_path.name}: {error}"
        ) from error
    if not (len(boxes) == len(scores) == len(classes)):
        raise RfdetrCardClusterTrainingError("RF-DETR output fields have different lengths")
    rows: list[dict[str, Any]] = []
    for index, (box, score, class_id) in enumerate(zip(boxes, scores, classes, strict=True)):
        coordinates = _as_sequence(box, f"xyxy[{index}]")
        if len(coordinates) != 4:
            raise RfdetrCardClusterTrainingError("RF-DETR box must have four coordinates")
        values = [_finite(item, f"xyxy[{index}]") for item in coordinates]
        confidence = _finite(score, f"confidence[{index}]")
        if not 0 <= confidence <= 1:
            raise RfdetrCardClusterTrainingError("RF-DETR confidence is outside [0, 1]")
        if int(class_id) not in {0, 1}:
            raise RfdetrCardClusterTrainingError("RF-DETR returned an unsupported class")
        box_value = PixelBox(*values)
        if (
            box_value.x_min < 0
            or box_value.y_min < 0
            or box_value.x_max > width
            or box_value.y_max > height
        ):
            raise RfdetrCardClusterTrainingError("RF-DETR box is outside the source frame")
        rows.append(
            {
                "prediction_id": f"prediction-{index + 1:04d}",
                "score": confidence,
                "box": box_value.to_mapping(),
            }
        )
    return rows


def _fixture_prediction_rows(coco: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    return {
        int(image["id"]): [
            {
                "prediction_id": f"prediction-{annotation['id']:04d}",
                "score": 0.9,
                "box": {
                    "x_min": annotation["bbox"][0],
                    "y_min": annotation["bbox"][1],
                    "x_max": annotation["bbox"][0] + annotation["bbox"][2],
                    "y_max": annotation["bbox"][1] + annotation["bbox"][3],
                },
            }
            for annotation in coco["annotations"]
            if int(annotation["image_id"]) == int(image["id"])
        ]
        for image in coco["images"]
    }


def _box(value: Mapping[str, Any] | Sequence[Any]) -> PixelBox:
    if isinstance(value, Mapping):
        return PixelBox(value["x_min"], value["y_min"], value["x_max"], value["y_max"])
    if len(value) != 4:
        raise RfdetrCardClusterTrainingError("box must have four coordinates")
    return PixelBox(value[0], value[1], value[0] + value[2], value[1] + value[3])


def _box_iou(left: PixelBox, right: PixelBox) -> float:
    intersection = left.intersection(right)
    if intersection is None:
        return 0.0
    area = left.width * left.height + right.width * right.height
    return (
        intersection.width * intersection.height / (area - intersection.width * intersection.height)
    )


def _match(
    targets: Sequence[PixelBox], predictions: Sequence[Mapping[str, Any]]
) -> tuple[set[int], set[int]]:
    pairs = sorted(
        (
            _box_iou(target, _box(prediction["box"])),
            prediction_index,
            target_index,
        )
        for prediction_index, prediction in enumerate(predictions)
        for target_index, target in enumerate(targets)
        if _box_iou(target, _box(prediction["box"])) >= RFDETR_CARD_CLUSTER_MATCH_IOU
    )
    matched_predictions: set[int] = set()
    matched_targets: set[int] = set()
    for _iou, prediction_index, target_index in sorted(pairs, reverse=True):
        if prediction_index not in matched_predictions and target_index not in matched_targets:
            matched_predictions.add(prediction_index)
            matched_targets.add(target_index)
    return matched_predictions, matched_targets


def _lineage_frame(
    view: Mapping[str, Any], image: Mapping[str, Any], partition: str
) -> Mapping[str, Any]:
    relative = f"{partition}/{image['file_name']}"
    for frame in view["lineage"]["frames"]:
        if frame.get("image_path") in {image["file_name"], relative}:
            return frame
    raise RfdetrCardClusterTrainingError(f"M2 lineage does not contain {relative}")


def _evaluate_threshold(
    view: Mapping[str, Any],
    coco: Mapping[str, Any],
    prediction_map: Mapping[int, Sequence[Mapping[str, Any]]],
    threshold: float,
) -> dict[str, Any]:
    frame_rows: list[dict[str, Any]] = []
    matched_targets = 0
    target_count = 0
    contained_cards = 0
    card_count = 0
    extra_clusters = 0
    cluster_count = 0
    area_ratios: list[float] = []
    for image in sorted(coco["images"], key=lambda item: int(item["id"])):
        image_id = int(image["id"])
        predictions = [
            dict(prediction)
            for prediction in prediction_map.get(image_id, ())
            if _finite(prediction.get("score"), "prediction score") >= threshold
        ]
        targets = [
            _box(annotation["bbox"])
            for annotation in coco["annotations"]
            if int(annotation["image_id"]) == image_id
        ]
        matched_predictions, matched = _match(targets, predictions)
        matched_targets += len(matched)
        target_count += len(targets)
        extra = len(predictions) - len(matched_predictions)
        extra_clusters += extra
        cluster_count += len(predictions)
        proposals = tuple(
            CoarseProposal(
                proposal_id=str(prediction["prediction_id"]),
                box=_box(prediction["box"]),
                score=float(prediction["score"]),
            )
            for prediction in predictions
        )
        layout = build_cascade_layout(
            proposals,
            frame_width=int(image["width"]),
            frame_height=int(image["height"]),
            coarse_threshold=threshold,
            model_input_size=432,
        )
        frame_area = int(image["width"]) * int(image["height"])
        area_ratios.extend(
            crop.crop_width * crop.crop_height / frame_area for crop in layout.clusters
        )
        lineage = _lineage_frame(view, image, "valid")
        cards = [card for card in lineage.get("source_cards", []) if isinstance(card, Mapping)]
        card_count += len(cards)
        contained = 0
        missed_cards: list[dict[str, Any]] = []
        for card in cards:
            card_box = _box(card["tight_box"])
            if any(crop.padded_square_box.contains(card_box) for crop in layout.clusters):
                contained += 1
            else:
                missed_cards.append(
                    {
                        "card_id": card.get("card_id"),
                        "proposal_id": card.get("proposal_id"),
                        "tight_box": card.get("tight_box"),
                        "source_frame_sha256": card.get("source_frame_sha256"),
                    }
                )
        contained_cards += contained
        frame_rows.append(
            {
                "image_id": image_id,
                "recording_id": image.get("recording_id"),
                "event_id": image.get("event_id"),
                "image_sha256": image.get("sha256"),
                "prediction_count": len(predictions),
                "target_count": len(targets),
                "matched_target_count": len(matched),
                "reviewed_card_count": len(cards),
                "contained_card_count": contained,
                "missed_cards": missed_cards,
                "extra_clusters": [
                    {
                        "prediction_id": prediction["prediction_id"],
                        "score": prediction["score"],
                        "box": prediction["box"],
                    }
                    for index, prediction in enumerate(predictions)
                    if index not in matched_predictions
                ],
                "coarse_latency_ms": prediction_map.get(f"latency:{image_id}", 0.0),
                "crop_count": len(layout.clusters),
            }
        )
    frame_count = len(frame_rows)
    return {
        "threshold": threshold,
        "cluster_recall": round(matched_targets / target_count, 6) if target_count else 0.0,
        "reviewed_card_crop_containment_recall": round(contained_cards / card_count, 6)
        if card_count
        else 0.0,
        "missed_cards": [card for frame in frame_rows for card in frame["missed_cards"]],
        "extra_clusters": [cluster for frame in frame_rows for cluster in frame["extra_clusters"]],
        "clusters_per_frame": round(cluster_count / frame_count, 6) if frame_count else 0.0,
        "crop_area_relative_to_source_area": round(sum(area_ratios) / frame_count, 6)
        if frame_count
        else 0.0,
        "coarse_latency_ms": round(
            sum(float(frame["coarse_latency_ms"]) for frame in frame_rows) / frame_count, 6
        )
        if frame_count
        else 0.0,
        "target_count": target_count,
        "frame_count": frame_count,
        "frames": frame_rows,
    }


def evaluate_rfdetr_card_cluster_validation(
    config: RfdetrCardClusterEvaluationConfig,
    *,
    prediction_provider: PredictionProvider | None = None,
) -> dict[str, Any]:
    """Evaluate validation boxes and select the highest threshold meeting the containment floor."""

    view = _load_materialization_view(config.dataset_dir)
    checkpoint = config.checkpoint.expanduser().resolve()
    if not checkpoint.is_file():
        raise RfdetrCardClusterTrainingError(
            f"card-cluster checkpoint does not exist: {checkpoint}"
        )
    output = config.output_dir.expanduser().resolve()
    report_path = output / "report.json"
    expected_config = {
        "dataset_dir": str(Path(config.dataset_dir).expanduser().resolve()),
        "checkpoint": str(checkpoint),
        "output_dir": str(output),
        "device": config.device,
        "runner": config.runner,
    }
    if report_path.is_file():
        report = _read_json(report_path, "card-cluster validation report")
        if report.get("config") == expected_config:
            return report
        raise RfdetrCardClusterTrainingError("validation output belongs to another run")
    if output.exists() and any(output.iterdir()):
        raise RfdetrCardClusterTrainingError(f"validation output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    model: Any | None = None
    try:
        if prediction_provider is None:
            if config.runner == "fixture":
                prediction_map: dict[int, Sequence[Mapping[str, Any]]] = _fixture_prediction_rows(
                    view["coco"]["valid"]
                )
            else:
                if not _requested_device_available(config.device):
                    raise RfdetrCardClusterTrainingError(
                        f"requested validation device is unavailable: {config.device}; "
                        "no fallback is permitted"
                    )
                model_class = _import_model()
                model = model_class.from_checkpoint(
                    str(checkpoint),
                    num_classes=1,
                    resolution=RFDETR_CARD_CLUSTER_INPUT_SIZE,
                    device=config.device,
                )
                if type(model).__name__ != RFDETR_CARD_CLUSTER_MODEL_CLASS:
                    raise RfdetrCardClusterTrainingError(
                        f"checkpoint reloaded as {type(model).__name__}, not "
                        f"{RFDETR_CARD_CLUSTER_MODEL_CLASS}"
                    )
                prediction_map = {}
                for image in view["coco"]["valid"]["images"]:
                    image_path = (
                        Path(view["root"])
                        / "valid"
                        / _safe_relative(image["file_name"], "validation image.file_name")
                    )
                    started = time.monotonic()
                    rows = _prediction_rows(
                        model, image_path, int(image["width"]), int(image["height"])
                    )
                    prediction_map[int(image["id"])] = rows
                    prediction_map[f"latency:{image['id']}"] = (time.monotonic() - started) * 1000  # type: ignore[index]
        else:
            prediction_map = {}
            for image in view["coco"]["valid"]["images"]:
                image_path = (
                    Path(view["root"])
                    / "valid"
                    / _safe_relative(image["file_name"], "validation image.file_name")
                )
                prediction_map[int(image["id"])] = prediction_provider(
                    image_path, int(image["width"]), int(image["height"])
                )
        metrics_by_threshold = {
            str(threshold): _evaluate_threshold(
                view, view["coco"]["valid"], prediction_map, threshold
            )
            for threshold in RFDETR_CARD_CLUSTER_THRESHOLDS
        }
        eligible = [
            value
            for value in metrics_by_threshold.values()
            if value["reviewed_card_crop_containment_recall"]
            >= RFDETR_CARD_CLUSTER_CONTAINMENT_FLOOR
        ]
        if not eligible:
            raise RfdetrCardClusterTrainingError(
                "no validation threshold meets the frozen reviewed-card "
                "crop-containment recall floor"
            )
        selected = max(eligible, key=lambda value: float(value["threshold"]))
        report_core = {
            "schema_version": RFDETR_CARD_CLUSTER_EVALUATION_SCHEMA,
            "status": "completed",
            "config": expected_config,
            "materialization_digest": view["materialization_digest"],
            "checkpoint_sha256": _file_digest(checkpoint),
            "input_size": [RFDETR_CARD_CLUSTER_INPUT_SIZE, RFDETR_CARD_CLUSTER_INPUT_SIZE],
            "threshold_policy": {
                "candidates": list(RFDETR_CARD_CLUSTER_THRESHOLDS),
                "selected": selected["threshold"],
                "selection": "highest_confidence_meeting_crop_containment_floor",
                "containment_floor": RFDETR_CARD_CLUSTER_CONTAINMENT_FLOOR,
                "match_iou": RFDETR_CARD_CLUSTER_MATCH_IOU,
            },
            "metrics": {"selected": selected, "by_threshold": metrics_by_threshold},
            "limitations": {
                "sealed_test_evaluated": False,
                "note": "0068 sealed_test is not used for threshold calibration.",
            },
        }
        report = {**report_core, "report_digest": _digest(report_core)}
        _write_json(report_path, report)
        return report
    finally:
        del model


def _write_bundle(
    destination: Path,
    *,
    checkpoint: Path,
    pretrained_sha256: str,
    view: Mapping[str, Any],
    recipe: Mapping[str, Any],
    report_path: Path,
    run_id: str,
    device: str,
    runner: str,
) -> dict[str, Any]:
    if destination.exists():
        raise RfdetrCardClusterTrainingError(f"bundle directory already exists: {destination}")
    destination.mkdir(parents=True)
    bundled_checkpoint = destination / RFDETR_CARD_CLUSTER_FINAL_CHECKPOINT
    bundled_report = destination / "validation-report.json"
    shutil.copy2(checkpoint, bundled_checkpoint)
    shutil.copy2(report_path, bundled_report)
    checkpoint_sha256 = _file_digest(bundled_checkpoint)
    report = _read_json(report_path, "validation report")
    manifest_core: dict[str, Any] = {
        "schema_version": RFDETR_CARD_CLUSTER_BUNDLE_SCHEMA,
        "component": "card-cluster-detection",
        "quality_state": "unreviewed",
        "model": recipe["model"],
        "model_variant": RFDETR_CARD_CLUSTER_MODEL_VARIANT,
        "package": {"name": "rfdetr", "version": RFDETR_CARD_CLUSTER_PACKAGE_VERSION},
        "class_map": RFDETR_CARD_CLUSTER_CLASS_MAP,
        "input_size": [RFDETR_CARD_CLUSTER_INPUT_SIZE, RFDETR_CARD_CLUSTER_INPUT_SIZE],
        "confidence_threshold": report["threshold_policy"]["selected"],
        "materialization_digest": view["materialization_digest"],
        "split_digest": view["materialization"]["split"]["digest"],
        "recipe": {**recipe, "recipe_digest": _digest(recipe)},
        "validation_report": {
            "file": bundled_report.name,
            "sha256": _file_digest(bundled_report),
            "report_digest": report["report_digest"],
        },
        "training_device": device,
        "runner": runner,
        "run_id": run_id,
        "pretrained_checkpoint": {
            "name": RFDETR_CARD_CLUSTER_CHECKPOINT_NAME,
            "sha256": pretrained_sha256,
        },
        "checkpoint_file": bundled_checkpoint.name,
        "checkpoint_sha256": checkpoint_sha256,
        "files": {
            bundled_checkpoint.name: checkpoint_sha256,
            bundled_report.name: _file_digest(bundled_report),
        },
        "dependency_versions": _environment()["packages"],
        "code_revision": _code_revision(),
    }
    manifest = {**manifest_core, "bundle_digest": _digest(manifest_core)}
    _write_json(destination / "manifest.json", manifest)
    return manifest


def load_rfdetr_card_cluster_bundle(path: str | Path) -> RfdetrCardClusterBundle:
    """Validate the native checkpoint, calibration report, and bundle digests."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise RfdetrCardClusterTrainingError(f"card-cluster bundle does not exist: {root}")
    manifest = _read_json(root / "manifest.json", "card-cluster bundle manifest")
    if manifest.get("schema_version") != RFDETR_CARD_CLUSTER_BUNDLE_SCHEMA:
        raise RfdetrCardClusterTrainingError("card-cluster bundle schema is unsupported")
    if (
        manifest.get("component") != "card-cluster-detection"
        or manifest.get("quality_state") != "unreviewed"
    ):
        raise RfdetrCardClusterTrainingError("card-cluster bundle identity is invalid")
    if manifest.get("model", {}).get("class") != RFDETR_CARD_CLUSTER_MODEL_CLASS:
        raise RfdetrCardClusterTrainingError("card-cluster bundle model class is invalid")
    if manifest.get("model_variant") != RFDETR_CARD_CLUSTER_MODEL_VARIANT:
        raise RfdetrCardClusterTrainingError("card-cluster bundle model variant is invalid")
    if manifest.get("package") != {
        "name": "rfdetr",
        "version": RFDETR_CARD_CLUSTER_PACKAGE_VERSION,
    }:
        raise RfdetrCardClusterTrainingError("card-cluster bundle package is not rfdetr 1.9.4")
    if manifest.get("class_map") != RFDETR_CARD_CLUSTER_CLASS_MAP:
        raise RfdetrCardClusterTrainingError("card-cluster bundle class map is invalid")
    if manifest.get("input_size") != [
        RFDETR_CARD_CLUSTER_INPUT_SIZE,
        RFDETR_CARD_CLUSTER_INPUT_SIZE,
    ]:
        raise RfdetrCardClusterTrainingError("card-cluster bundle input size is not 512 x 512")
    recipe = manifest.get("recipe")
    if not isinstance(recipe, Mapping) or recipe.get("recipe_digest") != _digest(
        {key: value for key, value in recipe.items() if key != "recipe_digest"}
    ):
        raise RfdetrCardClusterTrainingError("card-cluster bundle recipe digest is stale")
    if manifest.get("bundle_digest") != _digest(
        {key: value for key, value in manifest.items() if key != "bundle_digest"}
    ):
        raise RfdetrCardClusterTrainingError("card-cluster bundle digest does not match contents")
    files = manifest.get("files")
    checkpoint_name = manifest.get("checkpoint_file")
    if (
        not isinstance(files, Mapping)
        or not isinstance(checkpoint_name, str)
        or checkpoint_name not in files
    ):
        raise RfdetrCardClusterTrainingError("card-cluster bundle files are invalid")
    for relative, expected in files.items():
        safe = _safe_relative(relative, "bundle file")
        file_path = root / safe
        if not file_path.is_file() or _assert_digest(expected, safe) != _file_digest(file_path):
            raise RfdetrCardClusterTrainingError(
                f"card-cluster bundle file is missing or changed: {safe}"
            )
    report = manifest.get("validation_report")
    if not isinstance(report, Mapping) or report.get("file") not in files:
        raise RfdetrCardClusterTrainingError("card-cluster bundle validation report is undeclared")
    report_payload = _read_json(root / str(report["file"]), "bundled validation report")
    if report_payload.get("report_digest") != report.get("report_digest"):
        raise RfdetrCardClusterTrainingError("bundled validation report digest is stale")
    if manifest.get("checkpoint_sha256") != files[checkpoint_name]:
        raise RfdetrCardClusterTrainingError("card-cluster checkpoint digest is inconsistent")
    if manifest.get("checkpoint_sha256") == manifest.get("pretrained_checkpoint", {}).get("sha256"):
        raise RfdetrCardClusterTrainingError(
            "card-cluster checkpoint is identical to pretrained input"
        )
    return RfdetrCardClusterBundle(root, manifest, root / checkpoint_name)


def _reload_checkpoint(checkpoint: Path, device: str) -> dict[str, Any]:
    model_class = _import_model()
    if not _requested_device_available(device):
        raise RfdetrCardClusterTrainingError(
            f"requested inference device is unavailable: {device}; no fallback is permitted"
        )
    model = model_class.from_checkpoint(
        str(checkpoint),
        num_classes=1,
        resolution=RFDETR_CARD_CLUSTER_INPUT_SIZE,
        device=device,
    )
    if type(model).__name__ != RFDETR_CARD_CLUSTER_MODEL_CLASS:
        raise RfdetrCardClusterTrainingError(
            f"checkpoint reloaded as {type(model).__name__}, not {RFDETR_CARD_CLUSTER_MODEL_CLASS}"
        )
    return {"status": "reloaded", "model_class": type(model).__name__}


def run_rfdetr_card_cluster_training(config: RfdetrCardClusterTrainingConfig) -> dict[str, Any]:
    """Run exactly one bounded coarse detector candidate and write its bundle and receipts."""

    started = time.time()
    output = config.output_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        existing = output / "run.json"
        if existing.is_file() and config.resume is None:
            record = _read_json(existing, "card-cluster training run")
            if (
                record.get("status") == "completed"
                and record.get("config", {}).get("seed") == config.seed
            ):
                load_rfdetr_card_cluster_bundle(record["bundle"]["path"])
                return record
        raise RfdetrCardClusterTrainingError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "schema_version": RFDETR_CARD_CLUSTER_TRAINING_RUN_SCHEMA,
        "run_id": f"rfdetr-card-cluster-m3-training-{int(started)}",
        "status": "failed",
        "runner": config.runner,
        "device": config.device,
        "config": {
            "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
            "pretrained_checkpoint": str(config.pretrained_checkpoint.expanduser().resolve()),
            "output_dir": str(output),
            "seed": config.seed,
            "resume": str(config.resume.expanduser().resolve()) if config.resume else None,
        },
        "stages": {
            name: "pending"
            for name in ("inputs", "dataset", "training", "reload", "evaluation", "bundle")
        },
        "started_at": datetime.fromtimestamp(started, tz=UTC).isoformat(),
        "environment": _environment(),
        "resource_facts": _resource_facts(config.device),
        "code_revision": _code_revision(),
    }
    try:
        view = _load_materialization_view(config.dataset_dir)
        pretrained = config.pretrained_checkpoint.expanduser().resolve()
        if not pretrained.is_file() or pretrained.stat().st_size == 0:
            raise RfdetrCardClusterTrainingError(
                f"pretrained checkpoint does not exist or is empty: {pretrained}"
            )
        pretrained_sha256 = _file_digest(pretrained)
        recipe = default_rfdetr_card_cluster_recipe(
            pretrained_checkpoint=pretrained, device=config.device
        )
        record["stages"]["inputs"] = "completed"
        staged = _stage_dataset(view, output / "campaign-dataset")
        record["stages"]["dataset"] = "completed"
        training_output = output / "rfdetr"
        with (
            _resource_guard(
                config.device,
                output,
                budget_seconds=RFDETR_CARD_CLUSTER_WALL_CLOCK_SECONDS,
            )
            if config.runner == "rfdetr"
            else _null_context()
        ):
            checkpoint = (
                _run_fixture(view, pretrained_sha256, training_output)
                if config.runner == "fixture"
                else _run_rfdetr(
                    staged["root"], pretrained, training_output, config.device, config.seed
                )
            )
        checkpoint_sha256 = _file_digest(checkpoint)
        if checkpoint_sha256 == pretrained_sha256:
            raise RfdetrCardClusterTrainingError(
                "trained checkpoint is identical to pretrained input"
            )
        record["stages"]["training"] = "completed"
        reload_result = (
            {"status": "fixture_verified", "model_class": RFDETR_CARD_CLUSTER_MODEL_CLASS}
            if config.runner == "fixture"
            else _reload_checkpoint(checkpoint, config.device)
        )
        record["stages"]["reload"] = "completed"
        report = evaluate_rfdetr_card_cluster_validation(
            RfdetrCardClusterEvaluationConfig(
                dataset_dir=config.dataset_dir,
                checkpoint=checkpoint,
                output_dir=output / "validation",
                device=config.device,
                runner=config.runner,
            )
        )
        record["stages"]["evaluation"] = "completed"
        bundle_manifest = _write_bundle(
            output / "bundle",
            checkpoint=checkpoint,
            pretrained_sha256=pretrained_sha256,
            view=view,
            recipe=recipe,
            report_path=output / "validation" / "report.json",
            run_id=record["run_id"],
            device=config.device,
            runner=config.runner,
        )
        bundle = load_rfdetr_card_cluster_bundle(output / "bundle")
        record["stages"]["bundle"] = "completed"
        record.update(
            {
                "status": "completed",
                "duration_seconds": round(time.time() - started, 3),
                "budget_seconds": RFDETR_CARD_CLUSTER_WALL_CLOCK_SECONDS,
                "model": recipe["model"],
                "model_arguments": _model_arguments(pretrained),
                "training_arguments": _training_arguments(
                    staged["root"], training_output, config.device, config.seed
                ),
                "materialization_digest": view["materialization_digest"],
                "dataset": staged["subset"],
                "pretrained_checkpoint": {"path": str(pretrained), "sha256": pretrained_sha256},
                "checkpoint": {
                    "file": checkpoint.name,
                    "sha256": checkpoint_sha256,
                    "pretrained_sha256": pretrained_sha256,
                    "weights_differ": True,
                },
                "reload": reload_result,
                "validation": {
                    "path": str(output / "validation" / "report.json"),
                    "report_digest": report["report_digest"],
                    "selected_threshold": report["threshold_policy"]["selected"],
                    "containment_floor_met": report["metrics"]["selected"][
                        "reviewed_card_crop_containment_recall"
                    ]
                    >= RFDETR_CARD_CLUSTER_CONTAINMENT_FLOOR,
                },
                "bundle": {
                    "path": str(bundle.root),
                    "schema_version": bundle_manifest["schema_version"],
                    "bundle_digest": bundle_manifest["bundle_digest"],
                    "manifest_sha256": _file_digest(bundle.root / "manifest.json"),
                },
            }
        )
    except Exception as error:
        record["failure"] = {"type": type(error).__name__, "message": str(error)}
    record["finished_at"] = datetime.now(UTC).isoformat()
    _write_json(output / "run.json", record)
    if record["status"] != "completed":
        raise RfdetrCardClusterTrainingError(record["failure"]["message"])
    return record


@contextmanager
def _null_context() -> Any:
    yield


__all__ = [
    "RFDETR_CARD_CLUSTER_BUNDLE_SCHEMA",
    "RFDETR_CARD_CLUSTER_CONTAINMENT_FLOOR",
    "RFDETR_CARD_CLUSTER_EVALUATION_SCHEMA",
    "RFDETR_CARD_CLUSTER_INPUT_SIZE",
    "RFDETR_CARD_CLUSTER_MODEL_CLASS",
    "RFDETR_CARD_CLUSTER_PACKAGE_VERSION",
    "RfdetrCardClusterBundle",
    "RfdetrCardClusterEvaluationConfig",
    "RfdetrCardClusterTrainingConfig",
    "RfdetrCardClusterTrainingError",
    "default_rfdetr_card_cluster_recipe",
    "evaluate_rfdetr_card_cluster_validation",
    "load_rfdetr_card_cluster_bundle",
    "run_rfdetr_card_cluster_training",
]
