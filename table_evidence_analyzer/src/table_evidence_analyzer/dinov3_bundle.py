"""Self-contained export and validation for the local DINOv3 identity bundle.

Bundle validation is training-free.  The optional training module is imported only by the export
operation, while runtime callers can validate a bundle without importing training code or
constructing a model.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .local_identity import (
    DINOV3_BUNDLE_SCHEMA,
    DinoV3IdentityConfig,
    LocalIdentityContractError,
    load_dinov3_identity_config,
)

DINOV3_HEAD_SCHEMA = "dinov3-identity-linear-head/v1"
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
    checkpoint: Mapping[str, Any], *, checkpoint_digest: str
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
    if class_count != 24 or tuple(bias_shape) != (class_count,) or hidden_size <= 0:
        raise DinoV3BundleError("DINOv3 checkpoint identity head is not a 24-class linear head")
    return (
        {
            "schema_version": DINOV3_HEAD_SCHEMA,
            "adapter": "dinov3-frozen-linear-v1",
            "class_count": class_count,
            "hidden_size": hidden_size,
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
) -> Path:
    """Copy verified encoder files and a trained linear head into one native bundle."""

    run_root = Path(run_dir).expanduser().resolve()
    try:
        run = _read_json(run_root / "run.json", "DINOv3 training run")
    except DinoV3BundleError:
        raise
    if run.get("status") != "completed":
        raise DinoV3BundleError("only a completed DINOv3 run can be exported")
    if run.get("task") != "dinov3-frozen-linear-v1":
        raise DinoV3BundleError("run is not the frozen DINOv3 identity task")
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
    try:
        from .dinov3_training import load_dinov3_checkpoint

        checkpoint = load_dinov3_checkpoint(checkpoint_path)
    except (ImportError, OSError, ValueError) as error:
        raise DinoV3BundleError(f"could not load DINOv3 checkpoint: {error}") from error
    if checkpoint.get("config", {}).get("identity_digest") != identity.identity_digest:
        raise DinoV3BundleError("checkpoint identity digest does not match the export identity")

    head_payload, hidden_size = _head_from_checkpoint(
        checkpoint, checkpoint_digest=checkpoint_digest
    )
    source_files = (
        identity.weights.weight_file,
        identity.weights.config_file,
        identity.weights.processor_file,
    )
    target_map_file = "target-map.json"
    head_file = "head.pt"
    if len(set((*source_files, target_map_file, head_file, "manifest.json"))) != 6:
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
    _write_json(destination / target_map_file, identity.to_mapping()["target"])
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
        "calibration": "uncalibrated",
        "identity": identity.to_mapping(),
        "target_map_file": target_map_file,
        "target_map_sha256": files[target_map_file],
        "head": {
            "schema_version": DINOV3_HEAD_SCHEMA,
            "adapter": "dinov3-frozen-linear-v1",
            "file": head_file,
            "sha256": files[head_file],
            "hidden_size": hidden_size,
            "class_count": 24,
        },
        "run_id": _text(run.get("run_id"), "run_id"),
        "source_checkpoint_sha256": checkpoint_digest,
        "files": files,
    }
    manifest["bundle_digest"] = _digest(manifest)
    _write_json(destination / "manifest.json", manifest)
    return destination


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "component",
        "capability",
        "capabilities",
        "quality_state",
        "calibration",
        "identity",
        "target_map_file",
        "target_map_sha256",
        "head",
        "run_id",
        "source_checkpoint_sha256",
        "files",
        "bundle_digest",
    }
    if set(manifest) != required:
        raise DinoV3BundleError("DINOv3 bundle manifest has unexpected fields")
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
    if manifest["calibration"] != "uncalibrated":
        raise DinoV3BundleError("DINOv3 identity bundle must remain uncalibrated")
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

    identity_payload = manifest["identity"]
    if not isinstance(identity_payload, Mapping):
        raise DinoV3BundleError("DINOv3 bundle identity config is invalid")
    try:
        identity = DinoV3IdentityConfig.from_mapping(identity_payload, root=root)
    except (LocalIdentityContractError, OSError, ValueError) as error:
        raise DinoV3BundleError(f"DINOv3 bundle identity config is invalid: {error}") from error
    if identity.to_mapping() != dict(identity_payload):
        raise DinoV3BundleError("DINOv3 bundle identity config is not canonical")

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
        "class_count",
    }:
        raise DinoV3BundleError("DINOv3 identity head manifest is incomplete")
    head_file = _safe_file(head["file"], "head file")
    if (
        head["schema_version"] != DINOV3_HEAD_SCHEMA
        or head["adapter"] != "dinov3-frozen-linear-v1"
        or head["class_count"] != 24
        or isinstance(head["hidden_size"], bool)
        or not isinstance(head["hidden_size"], int)
        or head["hidden_size"] <= 0
    ):
        raise DinoV3BundleError("DINOv3 identity head manifest is invalid")
    head_digest = _sha256(head["sha256"], "head digest")
    if files.get(head_file) != head_digest:
        raise DinoV3BundleError("DINOv3 identity head digest is inconsistent")

    model = identity.to_mapping()["model"]
    expected_files = {
        model["weights"]["file"],
        model["config_file"],
        model["processor_file"],
        head_file,
        target_file,
    }
    if set(files) != expected_files:
        raise DinoV3BundleError("DINOv3 bundle file list does not match its manifest")
    if head["hidden_size"] != _config_hidden_size(root / model["config_file"]):
        raise DinoV3BundleError(
            "DINOv3 identity head hidden size does not match the encoder config"
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
