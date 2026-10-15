"""Self-contained export and validation for the local DINOv3 identity bundle.

Bundle validation is training-free.  The optional training module is imported only by the export
operation, while runtime callers can validate a bundle without importing training code or
constructing a model.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .dinov3_calibration import CALIBRATION_SCHEMA, SCORE_SCHEMA
from .local_identity import (
    DINOV3_BUNDLE_SCHEMA,
    DinoV3IdentityConfig,
    LocalIdentityContractError,
    load_dinov3_identity_config,
)

DINOV3_HEAD_SCHEMA = "dinov3-identity-linear-head/v2"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DinoV3BundleError(ValueError):
    """Raised when a local DINOv3 identity bundle is unsafe or incomplete."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise DinoV3BundleError(f"could not read bundle file: {path.name}") from error
    return digest.hexdigest()


def _safe_file(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DinoV3BundleError(f"{field} must be a non-empty file name")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or len(path.parts) != 1:
        raise DinoV3BundleError(f"{field} must be a file directly below the bundle root")
    return path.as_posix()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DinoV3BundleError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DinoV3BundleError(f"{field} must be a non-empty string")
    return value.strip()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DinoV3BundleError(f"{field} is not valid JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise DinoV3BundleError(f"{field} must be a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _review_threshold(calibration: Mapping[str, Any]) -> float | None:
    report = calibration.get("confidence_report")
    selection = report.get("review_threshold_selection") if isinstance(report, Mapping) else None
    selected = selection.get("selected_threshold") if isinstance(selection, Mapping) else None
    threshold = selected.get("threshold") if isinstance(selected, Mapping) else None
    if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
        return float(threshold)
    return None


@dataclass(frozen=True, slots=True)
class DinoV3IdentityBundle:
    """A validated, model-free local DINOv3 identity bundle."""

    root: Path
    manifest: dict[str, Any]
    identity: DinoV3IdentityConfig

    @property
    def head_path(self) -> Path:
        return self.root / self.manifest["head"]["file"]

    @property
    def encoder_state_path(self) -> Path:
        return self.root / self.manifest["encoder"]["file"]

    @property
    def encoder_path(self) -> Path:
        return self.root

    @property
    def bundle_digest(self) -> str:
        return self.manifest["bundle_digest"]


def _resolve_export_identity(
    run: Mapping[str, Any],
    identity_config: DinoV3IdentityConfig | str | Path | None,
    weights_root: str | Path | None,
) -> DinoV3IdentityConfig:
    if isinstance(identity_config, DinoV3IdentityConfig):
        identity = identity_config
    else:
        config_path: Path | None
        if identity_config is not None:
            config_path = Path(identity_config).expanduser().resolve()
        else:
            declared = run.get("config", {}).get("identity_config")
            if not isinstance(declared, str) or declared.startswith("<"):
                raise DinoV3BundleError(
                    "export needs identity_config and weights_root when the run used "
                    "a resolved object"
                )
            config_path = Path(declared).expanduser().resolve()
        root = Path(weights_root).expanduser().resolve() if weights_root else config_path.parent
        try:
            identity = load_dinov3_identity_config(config_path, weights_root=root)
        except (LocalIdentityContractError, OSError, ValueError) as error:
            raise DinoV3BundleError(f"could not load DINOv3 identity config: {error}") from error
    recorded = run.get("identity_config")
    if recorded != identity.to_mapping():
        raise DinoV3BundleError("run identity config does not match the export identity config")
    return identity


def _head_from_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    checkpoint_digest: str,
    identity: DinoV3IdentityConfig,
    adapter: str,
) -> tuple[Any, int]:
    try:
        state = checkpoint["model_state"]
        weight = state["head.weight"]
        bias = state["head.bias"]
    except (KeyError, TypeError) as error:
        raise DinoV3BundleError("DINOv3 checkpoint has no complete identity head") from error
    shape = getattr(weight, "shape", None)
    bias_shape = getattr(bias, "shape", None)
    if shape is None or bias_shape is None or len(shape) != 2 or len(bias_shape) != 1:
        raise DinoV3BundleError("DINOv3 checkpoint identity head has invalid tensor shapes")
    class_count, hidden_size = (int(shape[0]), int(shape[1]))
    if class_count != 25 or tuple(bias_shape) != (class_count,) or hidden_size <= 0:
        raise DinoV3BundleError(
            "DINOv3 checkpoint uses the obsolete 24-class head; the FACE_DOWN "
            "target contract has 25 classes"
        )
    expected_size = _config_hidden_size(identity.weights.root / identity.weights.config_file)
    if identity.recipe["feature_layout"] == "cls_mean_patch":
        expected_size *= 2
    if hidden_size != expected_size:
        raise DinoV3BundleError("DINOv3 checkpoint head does not match its feature layout")
    return (
        {
            "schema_version": DINOV3_HEAD_SCHEMA,
            "adapter": adapter,
            "class_count": class_count,
            "hidden_size": hidden_size,
            "feature_layout": identity.recipe["feature_layout"],
            "input_size": identity.input_size,
            "transform_digest": identity.transform_digest,
            "source_checkpoint_sha256": checkpoint_digest,
            "state_dict": {
                "weight": weight.detach().cpu(),
                "bias": bias.detach().cpu(),
            },
        },
        hidden_size,
    )


def export_dinov3_identity_bundle(
    run_dir: str | Path,
    output: str | Path,
    *,
    identity_config: DinoV3IdentityConfig | str | Path | None = None,
    weights_root: str | Path | None = None,
    calibration: str | Path | None = None,
) -> Path:
    """Copy verified encoder files and a trained linear head into one native bundle."""

    run_root = Path(run_dir).expanduser().resolve()
    try:
        run = _read_json(run_root / "run.json", "DINOv3 training run")
    except DinoV3BundleError:
        raise
    if run.get("status") != "completed":
        raise DinoV3BundleError("only a completed DINOv3 run can be exported")
    from .dinov3_training import DINOV3_ADAPTED_TASK_ADAPTER, DINOV3_TASK_ADAPTER

    adapter = run.get("task")
    if adapter not in {DINOV3_TASK_ADAPTER, DINOV3_ADAPTED_TASK_ADAPTER}:
        raise DinoV3BundleError("run is not a supported DINOv3 identity task")
    if run.get("quality_state") != "unusable_smoke_artifact":
        raise DinoV3BundleError("run has an invalid DINOv3 quality state")
    identity = _resolve_export_identity(run, identity_config, weights_root)

    checkpoints = run.get("checkpoints")
    if not isinstance(checkpoints, Mapping):
        raise DinoV3BundleError("completed DINOv3 run has no checkpoint record")
    checkpoint_name = _safe_file(checkpoints.get("best"), "best checkpoint")
    checkpoint_path = run_root / checkpoint_name
    if not checkpoint_path.is_file():
        raise DinoV3BundleError(f"best DINOv3 checkpoint is missing: {checkpoint_name}")
    checkpoint_digest = _file_digest(checkpoint_path)
    calibration_payload: dict[str, Any]
    if calibration is None:
        calibration_payload = {
            "schema_version": CALIBRATION_SCHEMA,
            "score_schema_version": SCORE_SCHEMA,
            "method": "scalar_temperature_scaling",
            "temperature": 1.0,
            "temperature_bounds": [0.05, 20.0],
            "run_id": run.get("run_id"),
            "source_checkpoint_sha256": checkpoint_digest,
            "view_id": None,
            "view_sha256": None,
            "sample_ids_sha256": None,
            "source_lineage_groups_sha256": None,
            "sample_count": 0,
            "nll_before": None,
            "nll_after": None,
            "confidence_report": None,
        }
    else:
        calibration_path = Path(calibration).expanduser().resolve()
        calibration_payload = _read_json(calibration_path, "DINOv3 confidence calibration")
        if (
            calibration_payload.get("schema_version") != CALIBRATION_SCHEMA
            or calibration_payload.get("score_schema_version") != SCORE_SCHEMA
            or calibration_payload.get("method") != "scalar_temperature_scaling"
            or calibration_payload.get("run_id") != run.get("run_id")
            or calibration_payload.get("source_checkpoint_sha256") != checkpoint_digest
            or isinstance(calibration_payload.get("temperature"), bool)
            or not isinstance(calibration_payload.get("temperature"), (int, float))
            or not 0.05 <= float(calibration_payload["temperature"]) <= 20.0
            or not isinstance(calibration_payload.get("view_sha256"), str)
        ):
            raise DinoV3BundleError("DINOv3 calibration does not match the source checkpoint")
    try:
        from .dinov3_training import load_dinov3_checkpoint

        checkpoint = load_dinov3_checkpoint(checkpoint_path)
    except (ImportError, OSError, ValueError) as error:
        raise DinoV3BundleError(f"could not load DINOv3 checkpoint: {error}") from error
    if checkpoint.get("config", {}).get("identity_digest") != identity.identity_digest:
        raise DinoV3BundleError("checkpoint identity digest does not match the export identity")

    head_payload, hidden_size = _head_from_checkpoint(
        checkpoint, checkpoint_digest=checkpoint_digest, identity=identity, adapter=adapter
    )
    model_state = checkpoint.get("model_state")
    if not isinstance(model_state, Mapping):
        raise DinoV3BundleError("DINOv3 checkpoint has no model state")
    encoder_state = {
        key.removeprefix("encoder."): value.detach().cpu()
        for key, value in model_state.items()
        if isinstance(key, str) and key.startswith("encoder.")
    }
    if not encoder_state:
        raise DinoV3BundleError("DINOv3 checkpoint has no encoder weights")
    training = run.get("training")
    if not isinstance(training, Mapping) or training.get("encoder_training") not in {
        "frozen",
        "last_two_blocks",
    }:
        raise DinoV3BundleError("DINOv3 run has no supported encoder training recipe")
    expected_mode = "last_two_blocks" if adapter == DINOV3_ADAPTED_TASK_ADAPTER else "frozen"
    if training["encoder_training"] != expected_mode:
        raise DinoV3BundleError("DINOv3 task adapter does not match its encoder training recipe")
    semantic_config = training.get("semantic_config")
    if (
        not isinstance(semantic_config, Mapping)
        or semantic_config.get("task_adapter") != adapter
        or semantic_config.get("identity_digest") != identity.identity_digest
        or semantic_config.get("feature_layout") != identity.recipe["feature_layout"]
        or semantic_config.get("encoder_training") != expected_mode
        or checkpoint.get("config") != dict(semantic_config)
    ):
        raise DinoV3BundleError("DINOv3 checkpoint and run recipes do not match")
    trainable_names = training.get("trainable_encoder_parameters")
    if not isinstance(trainable_names, list) or not all(
        isinstance(name, str) and name for name in trainable_names
    ):
        raise DinoV3BundleError("DINOv3 run has invalid trainable encoder parameter names")
    if expected_mode == "last_two_blocks" and not trainable_names:
        raise DinoV3BundleError("adapted DINOv3 run has no trainable encoder parameters")
    if expected_mode == "frozen" and trainable_names:
        raise DinoV3BundleError("frozen DINOv3 run declares trainable encoder parameters")
    source_files = (
        identity.weights.weight_file,
        identity.weights.config_file,
        identity.weights.processor_file,
    )
    target_map_file = "target-map.json"
    head_file = "head.pt"
    encoder_file = "encoder-state.pt"
    calibration_file = "calibration.json"
    declared_names = (
        *source_files,
        target_map_file,
        head_file,
        encoder_file,
        calibration_file,
        "manifest.json",
    )
    if len(set(declared_names)) != 8:
        raise DinoV3BundleError("DINOv3 bundle file names must be unique")

    destination = Path(output).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise DinoV3BundleError(f"DINOv3 bundle directory is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for filename in source_files:
        source = identity.weights.root / filename
        if not source.is_file():
            raise DinoV3BundleError(f"DINOv3 source file is missing: {filename}")
        shutil.copy2(source, destination / filename)

    import torch

    torch.save(head_payload, destination / head_file)
    torch.save(encoder_state, destination / encoder_file)
    _write_json(destination / target_map_file, identity.to_mapping()["target"])
    _write_json(destination / calibration_file, calibration_payload)
    files = {
        path.name: _file_digest(path)
        for path in sorted(destination.iterdir(), key=lambda item: item.name)
        if path.is_file()
    }
    manifest: dict[str, Any] = {
        "schema_version": DINOV3_BUNDLE_SCHEMA,
        "component": "table-evidence-analyzer",
        "capability": "visual-card-identity",
        "capabilities": ["identity_candidates"],
        "quality_state": "unusable_smoke_artifact",
        "calibration": {
            "schema_version": calibration_payload["schema_version"],
            "score_schema_version": calibration_payload["score_schema_version"],
            "method": calibration_payload["method"],
            "temperature": float(calibration_payload["temperature"]),
            "file": calibration_file,
            "sha256": files[calibration_file],
            "view_id": calibration_payload.get("view_id"),
            "review_threshold": _review_threshold(calibration_payload),
        },
        "identity": identity.to_mapping(),
        "pretrained_provenance": {
            "model_id": identity.weights.model_id,
            "model_revision": identity.weights.model_revision,
            "weight_file": identity.weights.weight_file,
            "weight_sha256": identity.weights.weight_sha256,
        },
        "recipe_digest": identity.recipe_digest,
        "transform_digest": identity.transform_digest,
        "target_map_file": target_map_file,
        "target_map_sha256": files[target_map_file],
        "head": {
            "schema_version": DINOV3_HEAD_SCHEMA,
            "adapter": adapter,
            "file": head_file,
            "sha256": files[head_file],
            "hidden_size": hidden_size,
            "feature_layout": identity.recipe["feature_layout"],
            "input_size": identity.input_size,
            "transform_digest": identity.transform_digest,
            "class_count": 25,
        },
        "encoder": {
            "file": encoder_file,
            "sha256": files[encoder_file],
            "initialization": "adapted_checkpoint"
            if expected_mode == "last_two_blocks"
            else "pretrained",
            "training_mode": expected_mode,
            "trainable_parameter_names": trainable_names,
        },
        "inference_recipe": {
            "feature_layout": identity.recipe["feature_layout"],
            "input_size": identity.input_size,
            "transform_digest": identity.transform_digest,
            "class_count": 25,
        },
        "training_recipe": dict(semantic_config),
        "run_id": _text(run.get("run_id"), "run_id"),
        "source_checkpoint_sha256": checkpoint_digest,
        "files": files,
    }
    manifest["bundle_digest"] = _digest(manifest)
    _write_json(destination / "manifest.json", manifest)
    return destination


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    head = manifest.get("head")
    if (
        manifest.get("schema_version") == "dinov3-identity-bundle/v2"
        and isinstance(head, Mapping)
        and head.get("schema_version") == "dinov3-identity-linear-head/v1"
    ):
        raise DinoV3BundleError(
            "the configured DINOv3 bundle uses an obsolete uncalibrated smoke format; "
            "export a current calibrated 25-class bundle"
        )
    required = {
        "schema_version",
        "component",
        "capability",
        "capabilities",
        "quality_state",
        "calibration",
        "identity",
        "pretrained_provenance",
        "recipe_digest",
        "transform_digest",
        "target_map_file",
        "target_map_sha256",
        "head",
        "encoder",
        "inference_recipe",
        "training_recipe",
        "run_id",
        "source_checkpoint_sha256",
        "files",
        "bundle_digest",
    }
    if set(manifest) != required:
        raise DinoV3BundleError("DINOv3 bundle manifest has unexpected fields")
    if manifest["schema_version"] == "dinov3-identity-bundle/v1":
        raise DinoV3BundleError(
            "24-class DINOv3 identity bundle is obsolete; use a FACE_DOWN-capable 25-class bundle"
        )
    if manifest["schema_version"] != DINOV3_BUNDLE_SCHEMA:
        raise DinoV3BundleError("unsupported DINOv3 identity bundle schema")
    if manifest["component"] != "table-evidence-analyzer":
        raise DinoV3BundleError("DINOv3 bundle has the wrong component")
    if manifest["capability"] != "visual-card-identity":
        raise DinoV3BundleError("DINOv3 bundle has the wrong capability")
    if manifest["capabilities"] != ["identity_candidates"]:
        raise DinoV3BundleError("DINOv3 bundle must declare only identity_candidates")
    if manifest["quality_state"] != "unusable_smoke_artifact":
        raise DinoV3BundleError("DINOv3 bundle has an invalid quality state")
    calibration = manifest["calibration"]
    if not isinstance(calibration, Mapping) or set(calibration) != {
        "schema_version",
        "score_schema_version",
        "method",
        "temperature",
        "file",
        "sha256",
        "view_id",
        "review_threshold",
    }:
        raise DinoV3BundleError("DINOv3 confidence calibration metadata is incomplete")
    calibration_file = _safe_file(calibration["file"], "calibration file")
    calibration_digest = _sha256(calibration["sha256"], "calibration digest")
    declared_files = manifest["files"]
    if (
        not isinstance(declared_files, Mapping)
        or declared_files.get(calibration_file) != calibration_digest
    ):
        raise DinoV3BundleError("DINOv3 confidence calibration digest is inconsistent")
    if (
        calibration["schema_version"] != CALIBRATION_SCHEMA
        or calibration["score_schema_version"] != SCORE_SCHEMA
        or calibration["method"] != "scalar_temperature_scaling"
        or isinstance(calibration["temperature"], bool)
        or not isinstance(calibration["temperature"], (int, float))
        or not math.isfinite(float(calibration["temperature"]))
        or not 0.05 <= float(calibration["temperature"]) <= 20.0
    ):
        raise DinoV3BundleError("DINOv3 confidence calibration metadata is invalid")
    if not (calibration["view_id"] is None or isinstance(calibration["view_id"], str)):
        raise DinoV3BundleError("DINOv3 calibration view ID is invalid")
    threshold = calibration["review_threshold"]
    if threshold is not None and (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
        or not 0 <= float(threshold) <= 1
    ):
        raise DinoV3BundleError("DINOv3 review threshold is invalid")
    provenance = manifest["pretrained_provenance"]
    if not isinstance(provenance, Mapping) or set(provenance) != {
        "model_id",
        "model_revision",
        "weight_file",
        "weight_sha256",
    }:
        raise DinoV3BundleError("DINOv3 pretrained provenance is incomplete")
    _text(provenance["model_id"], "pretrained model ID")
    _text(provenance["model_revision"], "pretrained model revision")
    _safe_file(provenance["weight_file"], "pretrained weight file")
    _sha256(provenance["weight_sha256"], "pretrained weight digest")
    _text(manifest["run_id"], "run_id")
    _sha256(manifest["source_checkpoint_sha256"], "source checkpoint digest")
    if manifest["bundle_digest"] != _digest(
        {key: value for key, value in manifest.items() if key != "bundle_digest"}
    ):
        raise DinoV3BundleError("DINOv3 bundle manifest hash does not match its contents")


def load_dinov3_identity_bundle(path: str | Path) -> DinoV3IdentityBundle:
    """Verify every bundle file and return a model-free bundle description."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise DinoV3BundleError(f"DINOv3 bundle directory does not exist: {root}")
    manifest = _read_json(root / "manifest.json", "DINOv3 bundle manifest")
    _validate_manifest(manifest)
    files = manifest["files"]
    if not isinstance(files, Mapping) or not files:
        raise DinoV3BundleError("DINOv3 bundle does not declare file digests")
    for raw_name, raw_digest in files.items():
        name = _safe_file(raw_name, "bundle file")
        expected = _sha256(raw_digest, f"bundle file digest {name}")
        file_path = root / name
        if not file_path.is_file():
            raise DinoV3BundleError(f"DINOv3 bundle file is missing: {name}")
        if _file_digest(file_path) != expected:
            raise DinoV3BundleError(f"DINOv3 bundle file hash does not match: {name}")

    calibration = manifest["calibration"]
    if files.get(calibration["file"]) != calibration["sha256"]:
        raise DinoV3BundleError("DINOv3 confidence calibration digest is inconsistent")
    calibration_artifact = _read_json(root / calibration["file"], "DINOv3 calibration")
    if (
        calibration_artifact.get("schema_version") != calibration["schema_version"]
        or calibration_artifact.get("score_schema_version") != calibration["score_schema_version"]
        or calibration_artifact.get("method") != calibration["method"]
        or calibration_artifact.get("temperature") != calibration["temperature"]
        or calibration_artifact.get("view_id") != calibration["view_id"]
        or _review_threshold(calibration_artifact) != calibration["review_threshold"]
    ):
        raise DinoV3BundleError("DINOv3 calibration file does not match its manifest")

    identity_payload = manifest["identity"]
    if not isinstance(identity_payload, Mapping):
        raise DinoV3BundleError("DINOv3 bundle identity config is invalid")
    try:
        identity = DinoV3IdentityConfig.from_mapping(identity_payload, root=root)
    except (LocalIdentityContractError, OSError, ValueError) as error:
        raise DinoV3BundleError(f"DINOv3 bundle identity config is invalid: {error}") from error
    if identity.to_mapping() != dict(identity_payload):
        raise DinoV3BundleError("DINOv3 bundle identity config is not canonical")
    provenance = manifest["pretrained_provenance"]
    expected_provenance = {
        "model_id": identity.weights.model_id,
        "model_revision": identity.weights.model_revision,
        "weight_file": identity.weights.weight_file,
        "weight_sha256": identity.weights.weight_sha256,
    }
    if dict(provenance) != expected_provenance:
        raise DinoV3BundleError("DINOv3 pretrained provenance does not match its identity")
    if (
        manifest["recipe_digest"] != identity.recipe_digest
        or manifest["transform_digest"] != identity.transform_digest
    ):
        raise DinoV3BundleError("DINOv3 bundle recipe or transform digest does not match identity")

    target_file = _safe_file(manifest["target_map_file"], "target map file")
    target_digest = _sha256(manifest["target_map_sha256"], "target map digest")
    if files.get(target_file) != target_digest:
        raise DinoV3BundleError("DINOv3 target map digest is inconsistent")
    target = _read_json(root / target_file, "DINOv3 target map")
    if target != identity.to_mapping()["target"]:
        raise DinoV3BundleError("DINOv3 target map does not match the frozen identity map")

    head = manifest["head"]
    if not isinstance(head, Mapping) or set(head) != {
        "schema_version",
        "adapter",
        "file",
        "sha256",
        "hidden_size",
        "feature_layout",
        "input_size",
        "transform_digest",
        "class_count",
    }:
        raise DinoV3BundleError("DINOv3 identity head manifest is incomplete")
    head_file = _safe_file(head["file"], "head file")
    if (
        head["schema_version"] != DINOV3_HEAD_SCHEMA
        or head["adapter"] not in {"dinov3-frozen-linear-v1", "dinov3-last-two-blocks-v1"}
        or head["class_count"] != 25
        or head["feature_layout"] != identity.recipe["feature_layout"]
        or head["input_size"] != identity.input_size
        or head["transform_digest"] != identity.transform_digest
        or isinstance(head["hidden_size"], bool)
        or not isinstance(head["hidden_size"], int)
        or head["hidden_size"] <= 0
    ):
        raise DinoV3BundleError(
            "DINOv3 identity head manifest is invalid or uses the obsolete 24-class target"
        )
    head_digest = _sha256(head["sha256"], "head digest")
    if files.get(head_file) != head_digest:
        raise DinoV3BundleError("DINOv3 identity head digest is inconsistent")

    encoder = manifest["encoder"]
    if not isinstance(encoder, Mapping) or set(encoder) != {
        "file",
        "sha256",
        "initialization",
        "training_mode",
        "trainable_parameter_names",
    }:
        raise DinoV3BundleError("DINOv3 encoder state manifest is incomplete")
    encoder_file = _safe_file(encoder["file"], "encoder state file")
    encoder_digest = _sha256(encoder["sha256"], "encoder state digest")
    if files.get(encoder_file) != encoder_digest:
        raise DinoV3BundleError("DINOv3 encoder state digest is inconsistent")
    mode = encoder["training_mode"]
    names = encoder["trainable_parameter_names"]
    if (
        mode not in {"frozen", "last_two_blocks"}
        or encoder["initialization"]
        != ("adapted_checkpoint" if mode == "last_two_blocks" else "pretrained")
        or not isinstance(names, list)
        or not all(isinstance(name, str) and name for name in names)
        or (mode == "last_two_blocks" and not names)
        or (mode == "frozen" and names)
        or head["adapter"]
        != ("dinov3-last-two-blocks-v1" if mode == "last_two_blocks" else "dinov3-frozen-linear-v1")
    ):
        raise DinoV3BundleError("DINOv3 encoder state recipe is invalid")
    recipe = manifest["inference_recipe"]
    if not isinstance(recipe, Mapping) or dict(recipe) != {
        "feature_layout": identity.recipe["feature_layout"],
        "input_size": identity.input_size,
        "transform_digest": identity.transform_digest,
        "class_count": 25,
    }:
        raise DinoV3BundleError("DINOv3 inference recipe does not match the identity config")
    training_recipe = manifest["training_recipe"]
    if (
        not isinstance(training_recipe, Mapping)
        or training_recipe.get("encoder_training") != mode
        or training_recipe.get("task_adapter") != head["adapter"]
        or training_recipe.get("feature_layout") != identity.recipe["feature_layout"]
        or training_recipe.get("identity_digest") != identity.identity_digest
    ):
        raise DinoV3BundleError("DINOv3 training recipe is missing")

    model = identity.to_mapping()["model"]
    expected_files = {
        model["weights"]["file"],
        model["config_file"],
        model["processor_file"],
        head_file,
        encoder_file,
        target_file,
        manifest["calibration"]["file"],
    }
    if set(files) != expected_files:
        raise DinoV3BundleError("DINOv3 bundle file list does not match its manifest")
    feature_factor = 2 if identity.recipe["feature_layout"] == "cls_mean_patch" else 1
    if head["hidden_size"] != feature_factor * _config_hidden_size(root / model["config_file"]):
        raise DinoV3BundleError(
            "DINOv3 identity head input size does not match the encoder feature layout"
        )
    return DinoV3IdentityBundle(root=root, manifest=dict(manifest), identity=identity)


def _config_hidden_size(path: Path) -> int:
    config = _read_json(path, "DINOv3 encoder config")
    value = config.get("hidden_size")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DinoV3BundleError("DINOv3 encoder config has no valid hidden_size")
    return value


__all__ = [
    "DINOV3_HEAD_SCHEMA",
    "DinoV3BundleError",
    "DinoV3IdentityBundle",
    "export_dinov3_identity_bundle",
    "load_dinov3_identity_bundle",
]
