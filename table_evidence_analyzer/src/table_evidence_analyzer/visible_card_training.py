"""Train and bundle the bounded local visible-card detector PoC.

The real runner is a deliberately small adapter around the pinned RF-DETR API.  The fixture
runner writes deterministic stand-ins so contract tests never download model weights.  Both
runners produce the same run and bundle contracts.
"""

from __future__ import annotations

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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .visible_card_dataset import (
    DEFAULT_CHECKPOINT_NAME,
    DEFAULT_INPUT_SIZE,
    DEFAULT_MODEL_VARIANT,
    DEFAULT_RFDETR_VERSION,
    VISIBLE_CARD_DATASET_SCHEMA,
    VISIBLE_CARD_RECIPE_SCHEMA,
    VISIBLE_CARD_SPLIT_SCHEMA,
    load_visible_card_dataset_manifest,
    load_visible_card_recipe,
)

VISIBLE_CARD_TRAINING_RUN_SCHEMA = "visible-card-detector-training-run/v1"
VISIBLE_CARD_BUNDLE_SCHEMA = "visible-card-detector-bundle/v1"
DEFAULT_FINAL_CHECKPOINT = "checkpoint_best_total.pth"
_RUNNERS = frozenset({"fixture", "rfdetr"})
_SHA256_LENGTH = 64


class VisibleCardTrainingError(ValueError):
    """Raised when the visible-card training or bundle contract is invalid."""


@dataclass(frozen=True, slots=True)
class VisibleCardTrainingConfig:
    """Mounted inputs and output path for one bounded detector training run."""

    dataset_dir: Path
    evidence_root: Path
    pretrained_checkpoint: Path
    output_dir: Path
    runner: Literal["fixture", "rfdetr"] = "rfdetr"

    def __post_init__(self) -> None:
        if self.runner not in _RUNNERS:
            raise VisibleCardTrainingError("runner must be fixture or rfdetr")


@dataclass(frozen=True, slots=True)
class VisibleCardDetectorBundle:
    """A validated native detector bundle, ready for the M2 inference adapter."""

    root: Path
    manifest: dict[str, Any]
    checkpoint_path: Path


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


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
        raise VisibleCardTrainingError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise VisibleCardTrainingError(f"{context} must be a JSON object: {path}")
    return value


def _required_path(root: Path, name: str) -> Path:
    path = root / name
    if not path.is_file():
        raise VisibleCardTrainingError(f"training dataset is missing {name}")
    return path


def _safe_relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise VisibleCardTrainingError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise VisibleCardTrainingError(f"{field} must stay below its mounted root")
    return path.as_posix()


def _assert_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise VisibleCardTrainingError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise VisibleCardTrainingError(f"{field} must be a SHA-256 digest") from error
    return value


def _load_training_inputs(config: VisibleCardTrainingConfig) -> dict[str, Any]:
    dataset_root = config.dataset_dir.expanduser().resolve()
    evidence_root = config.evidence_root.expanduser().resolve()
    pretrained = config.pretrained_checkpoint.expanduser().resolve()
    if not dataset_root.is_dir():
        raise VisibleCardTrainingError(f"dataset directory does not exist: {dataset_root}")
    if not evidence_root.is_dir():
        raise VisibleCardTrainingError(f"evidence root does not exist: {evidence_root}")
    if not pretrained.is_file():
        raise VisibleCardTrainingError(f"pretrained checkpoint does not exist: {pretrained}")

    manifest_path = _required_path(dataset_root, "dataset-manifest.json")
    annotations_path = _required_path(dataset_root, "annotations.json")
    split_path = _required_path(dataset_root, "split.json")
    recipe_path = _required_path(dataset_root, "recipe.json")
    manifest = load_visible_card_dataset_manifest(manifest_path)
    recipe = load_visible_card_recipe(recipe_path)
    annotations = _read_json(annotations_path, "COCO annotations")
    split = _read_json(split_path, "visible-card split")

    if manifest.get("schema_version") != VISIBLE_CARD_DATASET_SCHEMA:
        raise VisibleCardTrainingError("dataset manifest has an unsupported schema")
    if split.get("schema_version") != VISIBLE_CARD_SPLIT_SCHEMA:
        raise VisibleCardTrainingError("split has an unsupported schema")
    if split != manifest.get("split"):
        raise VisibleCardTrainingError("split.json does not match the dataset manifest")
    if recipe.get("schema_version") != VISIBLE_CARD_RECIPE_SCHEMA:
        raise VisibleCardTrainingError("recipe has an unsupported schema")
    if recipe.get("dataset_digest") != manifest.get("dataset_digest"):
        raise VisibleCardTrainingError("recipe dataset digest does not match the dataset")
    if recipe.get("split_digest") != manifest.get("split_digest"):
        raise VisibleCardTrainingError("recipe split digest does not match the dataset")
    if recipe.get("model_variant") != DEFAULT_MODEL_VARIANT:
        raise VisibleCardTrainingError("training requires the frozen RFDETR Large recipe")
    if recipe.get("package") != {"name": "rfdetr", "version": DEFAULT_RFDETR_VERSION}:
        raise VisibleCardTrainingError("training requires rfdetr 1.9.4")
    if recipe.get("class_map") != {"1": "visible_card"}:
        raise VisibleCardTrainingError("training requires the one-class visible_card map")
    if recipe.get("input_size") != [DEFAULT_INPUT_SIZE, DEFAULT_INPUT_SIZE]:
        raise VisibleCardTrainingError("training requires the frozen 704 x 704 input")
    if recipe.get("final_checkpoint", DEFAULT_FINAL_CHECKPOINT) != DEFAULT_FINAL_CHECKPOINT:
        raise VisibleCardTrainingError(
            f"training requires the declared {DEFAULT_FINAL_CHECKPOINT} checkpoint"
        )

    expected_annotations_digest = manifest.get("coco_digest")
    if expected_annotations_digest != _digest(annotations):
        raise VisibleCardTrainingError("annotations digest does not match the dataset manifest")
    images = annotations.get("images")
    categories = annotations.get("categories")
    if not isinstance(images, list) or not images:
        raise VisibleCardTrainingError("COCO annotations must contain images")
    if categories != [{"id": 1, "name": "visible_card", "supercategory": "card"}]:
        raise VisibleCardTrainingError("COCO annotations must contain the visible_card category")
    frame_by_id = {
        frame["frame_id"]: frame
        for frame in manifest["frames"]
        if isinstance(frame, dict) and isinstance(frame.get("frame_id"), str)
    }
    image_ids = {image.get("source_frame_id") for image in images if isinstance(image, dict)}
    if image_ids != set(frame_by_id):
        raise VisibleCardTrainingError("COCO images do not cover the dataset manifest frames")

    source_digests: list[dict[str, str]] = []
    for frame in manifest["frames"]:
        if not isinstance(frame, dict):
            raise VisibleCardTrainingError("dataset manifest contains an invalid frame")
        frame_id = frame["frame_id"]
        relative_file = _safe_relative_path(frame.get("file_name"), f"{frame_id}.file_name")
        source_path = (evidence_root / relative_file).resolve()
        try:
            source_path.relative_to(evidence_root)
        except ValueError as error:
            raise VisibleCardTrainingError(f"frame escapes evidence root: {frame_id}") from error
        if not source_path.is_file():
            raise VisibleCardTrainingError(f"source frame does not exist: {source_path}")
        actual_digest = _file_digest(source_path)
        if actual_digest != frame.get("frame_sha256"):
            raise VisibleCardTrainingError(f"source frame digest does not match: {frame_id}")
        source_digests.append({"frame_id": frame_id, "sha256": actual_digest})

    declared_checkpoint = recipe.get("pretrained_checkpoint")
    if (
        not isinstance(declared_checkpoint, dict)
        or declared_checkpoint.get("name") != DEFAULT_CHECKPOINT_NAME
    ):
        raise VisibleCardTrainingError("recipe does not declare rf-detr-large.pth")
    pretrained_digest = _file_digest(pretrained)
    declared_digest = declared_checkpoint.get("sha256")
    if declared_digest is not None and declared_digest != pretrained_digest:
        raise VisibleCardTrainingError("pretrained checkpoint digest does not match the recipe")

    return {
        "dataset_root": dataset_root,
        "evidence_root": evidence_root,
        "pretrained": pretrained,
        "manifest_path": manifest_path,
        "annotations_path": annotations_path,
        "split_path": split_path,
        "recipe_path": recipe_path,
        "manifest": manifest,
        "annotations": annotations,
        "split": split,
        "recipe": recipe,
        "pretrained_digest": pretrained_digest,
        "source_digests": source_digests,
    }


def _source_path(frame: Mapping[str, Any], evidence_root: Path) -> Path:
    relative_file = _safe_relative_path(frame.get("file_name"), "frame.file_name")
    path = (evidence_root / relative_file).resolve()
    try:
        path.relative_to(evidence_root)
    except ValueError as error:
        raise VisibleCardTrainingError("frame path escapes evidence root") from error
    return path


def _staged_annotations(
    annotations: Mapping[str, Any], frame_ids: set[str], image_names: Mapping[int, str]
) -> dict[str, Any]:
    images = [
        {
            **image,
            "file_name": f"images/{image_names[int(image['id'])]}",
        }
        for image in annotations.get("images", [])
        if isinstance(image, dict) and image.get("source_frame_id") in frame_ids
    ]
    image_id_set = {image["id"] for image in images}
    staged_annotations = [
        annotation
        for annotation in annotations.get("annotations", [])
        if isinstance(annotation, dict) and annotation.get("image_id") in image_id_set
    ]
    return {
        "info": annotations.get("info", {}),
        "licenses": annotations.get("licenses", []),
        "images": images,
        "annotations": staged_annotations,
        "categories": annotations["categories"],
    }


def _stage_dataset(inputs: Mapping[str, Any], destination: Path) -> Path:
    """Create RF-DETR's train/valid COCO view with symlinks to mounted source frames."""

    if destination.exists():
        raise VisibleCardTrainingError(f"staged dataset already exists: {destination}")
    manifest = inputs["manifest"]
    annotations = inputs["annotations"]
    evidence_root = inputs["evidence_root"]
    frames_by_id = {frame["frame_id"]: frame for frame in manifest["frames"]}
    images = annotations["images"]
    image_names = {int(image["id"]): f"frame-{int(image['id']):04d}.jpg" for image in images}
    destination.mkdir(parents=True)
    for partition, rfdetector_partition in (("train", "train"), ("validation", "valid")):
        partition_root = destination / rfdetector_partition
        image_root = partition_root / "images"
        image_root.mkdir(parents=True)
        frame_ids = set(inputs["split"][partition])
        for image in images:
            if not isinstance(image, dict) or image.get("source_frame_id") not in frame_ids:
                continue
            source = _source_path(frames_by_id[image["source_frame_id"]], evidence_root)
            link = image_root / image_names[int(image["id"])]
            link.symlink_to(source)
        _write_json(
            partition_root / "_annotations.coco.json",
            _staged_annotations(annotations, frame_ids, image_names),
        )
    return destination


def _environment(package_name: str | None = None) -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in (package_name, "torch", "torchvision", "pytorch-lightning"):
        if not name:
            continue
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": packages,
    }


def _code_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _model_arguments(checkpoint: Path, recipe: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "num_classes": 1,
        "pretrain_weights": str(checkpoint),
        "resolution": recipe["input_size"][0],
    }


def _training_arguments(
    staged_dataset: Path, training_output: Path, recipe: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "dataset_dir": str(staged_dataset),
        "dataset_file": "coco",
        "output_dir": str(training_output),
        "epochs": recipe["epochs"],
        "resolution": recipe["input_size"][0],
        "device": recipe["device"],
        "class_names": ["visible_card"],
        "run_test": False,
    }


def _run_fixture(
    inputs: Mapping[str, Any], staged_dataset: Path, training_output: Path
) -> dict[str, Any]:
    training_output.mkdir(parents=True)
    seed_material = _canonical(
        {
            "dataset_digest": inputs["manifest"]["dataset_digest"],
            "split_digest": inputs["manifest"]["split_digest"],
            "pretrained_sha256": inputs["pretrained_digest"],
            "recipe_digest": inputs["recipe"]["recipe_digest"],
        }
    )
    checkpoint = b"fixture-rfdetr-large-checkpoint/v1\n" + hashlib.sha256(seed_material).digest()
    (training_output / DEFAULT_FINAL_CHECKPOINT).write_bytes(checkpoint)
    _write_json(
        training_output / "losses.json",
        {"loss": [1.0, 0.5, 0.25], "runner": "fixture", "dataset_dir": str(staged_dataset)},
    )
    _write_json(
        training_output / "training_config.json",
        {
            "model": DEFAULT_MODEL_VARIANT,
            "arguments": _training_arguments(staged_dataset, training_output, inputs["recipe"]),
        },
    )
    return {"package": "fixture", "checkpoint": training_output / DEFAULT_FINAL_CHECKPOINT}


def _run_rfdetr(
    inputs: Mapping[str, Any], staged_dataset: Path, training_output: Path
) -> dict[str, Any]:
    try:
        from rfdetr import RFDETRLarge
    except ModuleNotFoundError as error:
        if error.name != "rfdetr":
            raise VisibleCardTrainingError(
                "RF-DETR training dependencies are missing; run `uv sync --group training`"
            ) from error
        raise VisibleCardTrainingError(
            "RF-DETR is not installed; run the training dependency group with "
            "`uv sync --group training`"
        ) from error
    try:
        package_version = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError as error:
        raise VisibleCardTrainingError("RF-DETR package metadata is not installed") from error
    if package_version != DEFAULT_RFDETR_VERSION:
        raise VisibleCardTrainingError(
            f"RF-DETR package version {package_version} does not match the frozen "
            f"{DEFAULT_RFDETR_VERSION} recipe"
        )
    training_output.mkdir(parents=True)
    checkpoint = inputs["pretrained"]
    model = RFDETRLarge(
        **_model_arguments(checkpoint, inputs["recipe"]),
    )
    arguments = _training_arguments(staged_dataset, training_output, inputs["recipe"])
    model.train(**arguments)
    return {
        "package": DEFAULT_RFDETR_VERSION,
        "checkpoint": training_output / DEFAULT_FINAL_CHECKPOINT,
    }


def _numeric_loss_values(value: Any) -> list[float]:
    values: list[float] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                "loss" in str(key).lower()
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
            ):
                values.append(float(item))
            else:
                values.extend(_numeric_loss_values(item))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                values.append(float(item))
            else:
                values.extend(_numeric_loss_values(item))
    return values


def _confirm_finite_losses(training_output: Path) -> dict[str, Any]:
    evidence: list[str] = []
    values: list[float] = []
    for path in sorted(training_output.rglob("*")):
        if not path.is_file() or path.name == DEFAULT_FINAL_CHECKPOINT:
            continue
        if path.suffix == ".json":
            try:
                values_from_file = _numeric_loss_values(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        elif path.suffix == ".csv":
            try:
                with path.open(newline="", encoding="utf-8") as stream:
                    rows = csv.DictReader(stream)
                    values_from_file = []
                    for row in rows:
                        for key, raw in row.items():
                            if "loss" not in key.lower() or raw in (None, ""):
                                continue
                            try:
                                values_from_file.append(float(raw))
                            except ValueError:
                                continue
            except OSError:
                continue
        else:
            continue
        if values_from_file:
            evidence.append(path.name)
            values.extend(values_from_file)
    if not values:
        raise VisibleCardTrainingError("training emitted no numeric loss metric")
    if not all(math.isfinite(value) for value in values):
        raise VisibleCardTrainingError("training emitted a non-finite loss")
    return {"confirmed": True, "finite": True, "sample_count": len(values), "evidence": evidence}


def _stable_bundle_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "bundle_digest"}


def _write_bundle(
    destination: Path,
    *,
    inputs: Mapping[str, Any],
    checkpoint: Path,
    checkpoint_digest: str,
    run_id: str,
    runner: str,
    training_device: str,
) -> dict[str, Any]:
    if destination.exists():
        raise VisibleCardTrainingError(f"bundle directory already exists: {destination}")
    destination.mkdir(parents=True)
    bundled_checkpoint = destination / DEFAULT_FINAL_CHECKPOINT
    shutil.copy2(checkpoint, bundled_checkpoint)
    if _file_digest(bundled_checkpoint) != checkpoint_digest:
        raise VisibleCardTrainingError("bundled checkpoint digest changed during copy")
    manifest: dict[str, Any] = {
        "schema_version": VISIBLE_CARD_BUNDLE_SCHEMA,
        "component": "visible-card-detector",
        "quality_state": "unreviewed",
        "model_variant": DEFAULT_MODEL_VARIANT,
        "package": inputs["recipe"]["package"],
        "class_map": inputs["recipe"]["class_map"],
        "input_size": inputs["recipe"]["input_size"],
        "preprocessing": inputs["recipe"]["preprocessing"],
        "confidence_threshold": inputs["recipe"]["confidence_threshold"],
        "non_maximum_suppression": inputs["recipe"]["non_maximum_suppression"],
        "dataset_digest": inputs["manifest"]["dataset_digest"],
        "split_digest": inputs["manifest"]["split_digest"],
        "recipe_digest": inputs["recipe"]["recipe_digest"],
        "seed": inputs["recipe"]["seed"],
        "training_device": training_device,
        "runner": runner,
        "run_id": run_id,
        "pretrained_checkpoint": {
            "name": inputs["recipe"]["pretrained_checkpoint"]["name"],
            "sha256": inputs["pretrained_digest"],
        },
        "recipe": inputs["recipe"],
        "dependency_versions": _environment("rfdetr")["packages"],
        "checkpoint_file": bundled_checkpoint.name,
        "checkpoint_sha256": checkpoint_digest,
        "files": {bundled_checkpoint.name: checkpoint_digest},
        "code_revision": _code_revision(),
    }
    manifest["bundle_digest"] = _digest(_stable_bundle_manifest(manifest))
    _write_json(destination / "manifest.json", manifest)
    return manifest


def _base_run_record(config: VisibleCardTrainingConfig, started: float) -> dict[str, Any]:
    return {
        "schema_version": VISIBLE_CARD_TRAINING_RUN_SCHEMA,
        "run_id": f"visible-card-m1-{int(started)}",
        "status": "failed",
        "runner": config.runner,
        "config": {
            "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
            "evidence_root": str(config.evidence_root.expanduser().resolve()),
            "pretrained_checkpoint": str(config.pretrained_checkpoint.expanduser().resolve()),
            "output_dir": str(config.output_dir.expanduser().resolve()),
        },
        "started_at": datetime.fromtimestamp(started, tz=UTC).isoformat(),
        "environment": _environment("rfdetr" if config.runner == "rfdetr" else None),
        "code_revision": _code_revision(),
    }


def run_visible_card_training(config: VisibleCardTrainingConfig) -> dict[str, Any]:
    """Run one frozen detector training operation and write its run record and bundle."""

    started = time.time()
    output_dir = config.output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise VisibleCardTrainingError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    record = _base_run_record(config, started)
    run_path = output_dir / "run.json"
    try:
        inputs = _load_training_inputs(config)
        staged_dataset = output_dir / "rfdet-dataset"
        training_output = output_dir / "rfdetr"
        _stage_dataset(inputs, staged_dataset)
        runner_result = (
            _run_fixture(inputs, staged_dataset, training_output)
            if config.runner == "fixture"
            else _run_rfdetr(inputs, staged_dataset, training_output)
        )
        checkpoint = Path(runner_result["checkpoint"])
        if not checkpoint.is_file():
            raise VisibleCardTrainingError(
                f"the declared final checkpoint is missing: {checkpoint.name}"
            )
        loss_confirmation = _confirm_finite_losses(training_output)
        checkpoint_digest = _file_digest(checkpoint)
        if checkpoint_digest == inputs["pretrained_digest"]:
            raise VisibleCardTrainingError("trained checkpoint is identical to pretrained input")
        run_id = record["run_id"]
        _write_bundle(
            output_dir / "bundle",
            inputs=inputs,
            checkpoint=checkpoint,
            checkpoint_digest=checkpoint_digest,
            run_id=run_id,
            runner=config.runner,
            training_device=inputs["recipe"]["device"],
        )
        validated_bundle = load_visible_card_detector_bundle(output_dir / "bundle")
        record.update(
            {
                "status": "completed",
                "device": inputs["recipe"]["device"],
                "dataset": {
                    "manifest_sha256": _file_digest(inputs["manifest_path"]),
                    "annotations_sha256": _file_digest(inputs["annotations_path"]),
                    "split_sha256": _file_digest(inputs["split_path"]),
                    "recipe_sha256": _file_digest(inputs["recipe_path"]),
                    "dataset_digest": inputs["manifest"]["dataset_digest"],
                    "split_digest": inputs["manifest"]["split_digest"],
                    "source_frame_count": len(inputs["source_digests"]),
                    "source_frame_digests": inputs["source_digests"],
                },
                "pretrained_checkpoint": {
                    "path": str(inputs["pretrained"]),
                    "name": inputs["recipe"]["pretrained_checkpoint"]["name"],
                    "sha256": inputs["pretrained_digest"],
                },
                "recipe": inputs["recipe"],
                "model_arguments": _model_arguments(inputs["pretrained"], inputs["recipe"]),
                "training_arguments": _training_arguments(
                    staged_dataset, training_output, inputs["recipe"]
                ),
                "loss_confirmation": loss_confirmation,
                "checkpoint": {
                    "file": checkpoint.name,
                    "sha256": checkpoint_digest,
                    "pretrained_sha256": inputs["pretrained_digest"],
                    "weights_differ": True,
                },
                "bundle": {
                    "path": str(output_dir / "bundle"),
                    "bundle_digest": validated_bundle.manifest["bundle_digest"],
                    "manifest_sha256": _file_digest(output_dir / "bundle" / "manifest.json"),
                },
            }
        )
    except Exception as error:
        record["failure"] = {"type": type(error).__name__, "message": str(error)}
    record["finished_at"] = datetime.now(UTC).isoformat()
    _write_json(run_path, record)
    if record["status"] != "completed":
        raise VisibleCardTrainingError(record["failure"]["message"])
    return record


def load_visible_card_detector_bundle(path: str | Path) -> VisibleCardDetectorBundle:
    """Validate every bundle file digest before returning the native checkpoint path."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise VisibleCardTrainingError(f"bundle directory does not exist: {root}")
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path, "visible-card detector bundle manifest")
    if manifest.get("schema_version") != VISIBLE_CARD_BUNDLE_SCHEMA:
        raise VisibleCardTrainingError("unsupported visible-card detector bundle schema")
    if manifest.get("quality_state") != "unreviewed":
        raise VisibleCardTrainingError("visible-card detector bundle has an invalid quality state")
    if manifest.get("model_variant") != DEFAULT_MODEL_VARIANT:
        raise VisibleCardTrainingError("bundle model variant is not RFDETRLarge")
    if manifest.get("package") != {"name": "rfdetr", "version": DEFAULT_RFDETR_VERSION}:
        raise VisibleCardTrainingError("bundle package is not rfdetr 1.9.4")
    if manifest.get("class_map") != {"1": "visible_card"}:
        raise VisibleCardTrainingError("bundle class map is not the visible_card class")
    if manifest.get("input_size") != [DEFAULT_INPUT_SIZE, DEFAULT_INPUT_SIZE]:
        raise VisibleCardTrainingError("bundle input size is not the frozen 704 x 704 input")
    if manifest.get("confidence_threshold") != 0.5:
        raise VisibleCardTrainingError("bundle confidence threshold is not the frozen value")
    if manifest.get("non_maximum_suppression") is not False:
        raise VisibleCardTrainingError("bundle must not add non-maximum suppression")
    recipe = manifest.get("recipe")
    if (
        not isinstance(recipe, dict)
        or recipe.get("recipe_digest") != manifest.get("recipe_digest")
        or recipe.get("recipe_digest")
        != _digest({key: value for key, value in recipe.items() if key != "recipe_digest"})
    ):
        raise VisibleCardTrainingError("bundle recipe is missing or has a stale digest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise VisibleCardTrainingError("bundle does not declare file digests")
    if manifest.get("bundle_digest") != _digest(_stable_bundle_manifest(manifest)):
        raise VisibleCardTrainingError("bundle manifest digest does not match its contents")
    checkpoint_name = manifest.get("checkpoint_file")
    if not isinstance(checkpoint_name, str) or checkpoint_name not in files:
        raise VisibleCardTrainingError("bundle checkpoint is not declared in its file digests")
    checkpoint_path = root / checkpoint_name
    for relative_name, expected_digest in files.items():
        safe_name = _safe_relative_path(relative_name, "bundle file")
        file_path = root / safe_name
        if not file_path.is_file():
            raise VisibleCardTrainingError(f"bundle file is missing: {safe_name}")
        if _assert_digest(expected_digest, f"bundle file digest {safe_name}") != _file_digest(
            file_path
        ):
            raise VisibleCardTrainingError(f"bundle file hash does not match: {safe_name}")
    if manifest.get("checkpoint_sha256") != files[checkpoint_name]:
        raise VisibleCardTrainingError("bundle checkpoint digest is inconsistent")
    return VisibleCardDetectorBundle(root=root, manifest=manifest, checkpoint_path=checkpoint_path)


__all__ = [
    "DEFAULT_FINAL_CHECKPOINT",
    "VISIBLE_CARD_BUNDLE_SCHEMA",
    "VISIBLE_CARD_TRAINING_RUN_SCHEMA",
    "VisibleCardDetectorBundle",
    "VisibleCardTrainingConfig",
    "VisibleCardTrainingError",
    "load_visible_card_detector_bundle",
    "run_visible_card_training",
]
