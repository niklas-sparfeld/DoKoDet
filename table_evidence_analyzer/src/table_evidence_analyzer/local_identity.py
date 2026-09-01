"""Frozen contracts for the local DINOv3 visual card identity proof.

This module owns metadata, input preparation, and pretrained-file validation only.  It does not
import PyTorch or Transformers at module import time, and none of its operations download model
weights.  The later training and runtime milestones consume these records.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from .cards import CARD_IDENTITIES, CARD_SET_ID
from .data import _ppm_tokens

DINOV3_MODEL_ID = "facebook/dinov3-vits16-pretrain-lvd1689m"
DINOV3_ARCHITECTURE = "DINOv3 ViT-S/16"
DINOV3_FEATURE = "pooler_output"
DINOV3_PATCH_SIZE = 16
DINOV3_IMAGE_SIZE = 224
DINOV3_LICENSE_ID = "dinov3-license"
DINOV3_LICENSE_NAME = "DINOv3 License"
DINOV3_LICENSE_VERSION = "2025-08-19"
DINOV3_LICENSE_URL = "https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md"
DINOV3_WEIGHTS_FILENAME = "model.safetensors"
DINOV3_CONFIG_FILENAME = "config.json"
DINOV3_PROCESSOR_FILENAME = "preprocessor_config.json"

DINOV3_CONFIG_SCHEMA = "dinov3-identity-config/v1"
DINOV3_PROCESSOR_SCHEMA = "dinov3-identity-processor/v1"
DINOV3_TARGET_MAP_SCHEMA = "dinov3-identity-target-map/v1"
DINOV3_WEIGHTS_SCHEMA = "dinov3-pretrained-materialization/v1"
DINOV3_TRANSFORM_VERSION = "dinov3-identity-letterbox-224-v1"
DINOV3_AUGMENTATION_SCHEMA = "dinov3-identity-augmentation/v1"
DINOV3_RUN_SCHEMA = "dinov3-identity-training-run/v1"
DINOV3_BUNDLE_SCHEMA = "dinov3-identity-bundle/v1"

# These versions are pinned in the optional package groups and are repeated in every resolved
# identity configuration.  This keeps a run tied to the code that interprets its weights.
DINOV3_DEPENDENCY_VERSIONS = {
    "torch": "2.13.0",
    "torchvision": "0.28.0",
    "transformers": "5.16.1",
    "safetensors": "0.8.0",
}

DINOV3_PROCESSOR_CONFIG: dict[str, Any] = {
    "schema_version": DINOV3_PROCESSOR_SCHEMA,
    "input_size": {"height": DINOV3_IMAGE_SIZE, "width": DINOV3_IMAGE_SIZE},
    "resize": {"method": "aspect_ratio_preserving", "resampling": "lanczos"},
    "padding": {"mode": "constant", "fill_rgb": [128, 128, 128], "anchor": "center"},
    "channels": "RGB",
    "layout": "CHW",
    "dtype": "float32",
    "rescale": {"enabled": True, "factor": 1 / 255},
    "normalize": {
        "enabled": True,
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
    },
}

DINOV3_AUGMENTATION_CONFIG: dict[str, Any] = {
    "schema_version": DINOV3_AUGMENTATION_SCHEMA,
    "train_only": True,
    "color_and_exposure": {"brightness": 0.15, "contrast": 0.15, "saturation": 0.10},
    "orientation": {"allowed": ["identity", "rotate_180"], "arbitrary_rotation": False},
    "mirror": False,
    "identity_mark_mirroring": False,
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LocalIdentityContractError(ValueError):
    """Raised when a local identity proof input does not match its frozen contract."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise LocalIdentityContractError(f"could not read pretrained file: {path.name}") from error
    return digest.hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalIdentityContractError(f"{field} must be a non-empty string")
    return value.strip()


def _digest_value(value: Any, field: str) -> str:
    result = _text(value, field)
    if _SHA256.fullmatch(result) is None:
        raise LocalIdentityContractError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _safe_relative_file(value: Any, field: str) -> str:
    result = _text(value, field)
    path = PurePosixPath(result)
    if path.is_absolute() or ".." in path.parts or "\\" in result or len(path.parts) != 1:
        raise LocalIdentityContractError(f"{field} must be a file directly below the weight root")
    return path.as_posix()


def _read_json_object(path: Path, field: str) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LocalIdentityContractError(f"{field} is not valid JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise LocalIdentityContractError(f"{field} must be a JSON object")


def canonical_identity_target_map() -> dict[str, str]:
    """Return the strict zero-based map for all 24 canonical visual card identities."""

    return {str(index): identity for index, identity in enumerate(CARD_IDENTITIES)}


def validate_identity_target_map(value: Mapping[str, Any]) -> dict[str, str]:
    """Validate and copy the frozen 24-class output map."""

    if not isinstance(value, Mapping):
        raise LocalIdentityContractError("identity target map must be a mapping")
    expected = canonical_identity_target_map()
    if dict(value) != expected:
        raise LocalIdentityContractError(
            "identity target map must contain the ordered 24 canonical card identities"
        )
    return expected


def identity_target_index(identity: str) -> int:
    """Return the frozen model index for one canonical visual card identity."""

    try:
        return CARD_IDENTITIES.index(identity)
    except ValueError as error:
        raise LocalIdentityContractError(f"unknown visual card identity: {identity}") from error


def identity_from_target_index(index: int) -> str:
    """Return the canonical identity for one frozen model index."""

    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < len(CARD_IDENTITIES)
    ):
        raise LocalIdentityContractError("identity target index must be between 0 and 23")
    return CARD_IDENTITIES[index]


@dataclass(frozen=True, slots=True)
class DinoV3LicenseRecord:
    """An explicit operator acceptance record for the gated DINOv3 materials."""

    license_id: str = DINOV3_LICENSE_ID
    name: str = DINOV3_LICENSE_NAME
    version: str = DINOV3_LICENSE_VERSION
    url: str = DINOV3_LICENSE_URL
    accepted: bool = False
    accepted_at_utc: str | None = None

    def __post_init__(self) -> None:
        if self.license_id != DINOV3_LICENSE_ID:
            raise LocalIdentityContractError("license record is not the DINOv3 license")
        if self.name != DINOV3_LICENSE_NAME or self.version != DINOV3_LICENSE_VERSION:
            raise LocalIdentityContractError(
                "license record does not match the pinned DINOv3 license"
            )
        if self.url != DINOV3_LICENSE_URL:
            raise LocalIdentityContractError(
                "license record URL does not match the pinned DINOv3 license"
            )
        if not isinstance(self.accepted, bool):
            raise LocalIdentityContractError("license acceptance must be a boolean")
        if self.accepted_at_utc is not None and (
            not isinstance(self.accepted_at_utc, str) or not self.accepted_at_utc.strip()
        ):
            raise LocalIdentityContractError(
                "license acceptance timestamp must be a non-empty string"
            )
        if self.accepted and not self.accepted_at_utc:
            raise LocalIdentityContractError(
                "accepted DINOv3 license needs an acceptance timestamp"
            )
        if not self.accepted and self.accepted_at_utc is not None:
            raise LocalIdentityContractError(
                "unaccepted DINOv3 license cannot have an acceptance timestamp"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DinoV3LicenseRecord":
        if not isinstance(value, Mapping):
            raise LocalIdentityContractError("license record must be a mapping")
        fields = {"license_id", "name", "version", "url", "accepted", "accepted_at_utc"}
        if set(value) != fields:
            raise LocalIdentityContractError("license record has unexpected fields")
        return cls(
            license_id=_text(value["license_id"], "license_id"),
            name=_text(value["name"], "license name"),
            version=_text(value["version"], "license version"),
            url=_text(value["url"], "license URL"),
            accepted=value["accepted"],
            accepted_at_utc=value["accepted_at_utc"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "name": self.name,
            "version": self.version,
            "url": self.url,
            "accepted": self.accepted,
            "accepted_at_utc": self.accepted_at_utc,
        }


def _license_record(value: DinoV3LicenseRecord | Mapping[str, Any]) -> DinoV3LicenseRecord:
    if isinstance(value, DinoV3LicenseRecord):
        return value
    return DinoV3LicenseRecord.from_mapping(value)


@dataclass(frozen=True, slots=True)
class MaterializedDinoV3Weights:
    """Digest-checked DINOv3 files already present in a local directory."""

    root: Path
    model_id: str
    model_revision: str
    weight_file: str
    weight_sha256: str
    config_file: str
    config_sha256: str
    processor_file: str
    processor_sha256: str

    def __post_init__(self) -> None:
        if self.model_id != DINOV3_MODEL_ID:
            raise LocalIdentityContractError("pretrained materialization has the wrong model ID")
        _text(self.model_revision, "model revision")
        for field, value in (
            ("weight_file", self.weight_file),
            ("config_file", self.config_file),
            ("processor_file", self.processor_file),
        ):
            _safe_relative_file(value, field)
        for field, value in (
            ("weight_sha256", self.weight_sha256),
            ("config_sha256", self.config_sha256),
            ("processor_sha256", self.processor_sha256),
        ):
            _digest_value(value, field)

    @property
    def materialization_digest(self) -> str:
        return _digest(self.to_mapping())

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": DINOV3_WEIGHTS_SCHEMA,
            "model_id": self.model_id,
            "revision": self.model_revision,
            "files": {
                "weights": {"path": self.weight_file, "sha256": self.weight_sha256},
                "config": {"path": self.config_file, "sha256": self.config_sha256},
                "processor": {"path": self.processor_file, "sha256": self.processor_sha256},
            },
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, root: Path) -> "MaterializedDinoV3Weights":
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "model_id",
            "revision",
            "files",
        }:
            raise LocalIdentityContractError("pretrained materialization has unexpected fields")
        if value["schema_version"] != DINOV3_WEIGHTS_SCHEMA:
            raise LocalIdentityContractError("unsupported pretrained materialization schema")
        files = value["files"]
        if not isinstance(files, Mapping) or set(files) != {"weights", "config", "processor"}:
            raise LocalIdentityContractError(
                "pretrained materialization file records are incomplete"
            )

        def file_record(name: str) -> tuple[str, str]:
            item = files[name]
            if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
                raise LocalIdentityContractError(f"pretrained {name} file record is invalid")
            return (
                _safe_relative_file(item["path"], f"{name}.path"),
                _digest_value(item["sha256"], f"{name}.sha256"),
            )

        weight_file, weight_sha256 = file_record("weights")
        config_file, config_sha256 = file_record("config")
        processor_file, processor_sha256 = file_record("processor")
        return cls(
            root=Path(root).expanduser().resolve(),
            model_id=_text(value["model_id"], "model ID"),
            model_revision=_text(value["revision"], "model revision"),
            weight_file=weight_file,
            weight_sha256=weight_sha256,
            config_file=config_file,
            config_sha256=config_sha256,
            processor_file=processor_file,
            processor_sha256=processor_sha256,
        )


def materialize_dinov3_weights(
    root: str | Path,
    *,
    model_revision: str,
    license_record: DinoV3LicenseRecord | Mapping[str, Any],
    expected_weight_sha256: str | None = None,
    expected_config_sha256: str | None = None,
    expected_processor_sha256: str | None = None,
    weight_file: str = DINOV3_WEIGHTS_FILENAME,
    config_file: str = DINOV3_CONFIG_FILENAME,
    processor_file: str = DINOV3_PROCESSOR_FILENAME,
) -> MaterializedDinoV3Weights:
    """Check already-materialized gated files without contacting the model host."""

    license_value = _license_record(license_record)
    if not license_value.accepted:
        raise LocalIdentityContractError("explicit DINOv3 license acceptance is required")
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise LocalIdentityContractError(f"pretrained weight root does not exist: {root_path}")
    _text(model_revision, "model revision")
    paths = {
        "weights": root_path / _safe_relative_file(weight_file, "weight_file"),
        "config": root_path / _safe_relative_file(config_file, "config_file"),
        "processor": root_path / _safe_relative_file(processor_file, "processor_file"),
    }
    for name, path in paths.items():
        if not path.is_file():
            raise LocalIdentityContractError(f"pretrained {name} file is missing: {path.name}")
    _read_json_object(paths["config"], "DINOv3 config")
    _read_json_object(paths["processor"], "DINOv3 processor config")
    digests = {name: _file_digest(path) for name, path in paths.items()}
    expected = {
        "weights": expected_weight_sha256,
        "config": expected_config_sha256,
        "processor": expected_processor_sha256,
    }
    for name, declared in expected.items():
        if declared is not None and digests[name] != _digest_value(
            declared, f"expected {name} digest"
        ):
            raise LocalIdentityContractError(
                f"pretrained {name} bytes do not match the declared digest"
            )
    return MaterializedDinoV3Weights(
        root=root_path,
        model_id=DINOV3_MODEL_ID,
        model_revision=model_revision,
        weight_file=_safe_relative_file(weight_file, "weight_file"),
        weight_sha256=digests["weights"],
        config_file=_safe_relative_file(config_file, "config_file"),
        config_sha256=digests["config"],
        processor_file=_safe_relative_file(processor_file, "processor_file"),
        processor_sha256=digests["processor"],
    )


def verify_materialized_dinov3_weights(value: MaterializedDinoV3Weights) -> None:
    """Recheck every file digest before a later model construction step."""

    root = value.root.expanduser().resolve()
    if not root.is_dir():
        raise LocalIdentityContractError(f"pretrained weight root does not exist: {root}")
    for name, filename, expected in (
        ("weights", value.weight_file, value.weight_sha256),
        ("config", value.config_file, value.config_sha256),
        ("processor", value.processor_file, value.processor_sha256),
    ):
        path = root / _safe_relative_file(filename, f"{name}_file")
        if not path.is_file():
            raise LocalIdentityContractError(f"pretrained {name} file is missing: {path.name}")
        if _file_digest(path) != expected:
            raise LocalIdentityContractError(f"pretrained {name} bytes changed")
    _read_json_object(root / value.config_file, "DINOv3 config")
    _read_json_object(root / value.processor_file, "DINOv3 processor config")


@dataclass(frozen=True, slots=True)
class DinoV3IdentityConfig:
    """Complete frozen input identity for one local visual card classifier run."""

    weights: MaterializedDinoV3Weights
    license_record: DinoV3LicenseRecord
    processor_config: Mapping[str, Any]
    augmentation_config: Mapping[str, Any]
    dependency_versions: Mapping[str, str]
    target_map: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.license_record.accepted:
            raise LocalIdentityContractError("explicit DINOv3 license acceptance is required")
        if self.processor_config != DINOV3_PROCESSOR_CONFIG:
            raise LocalIdentityContractError("DINOv3 processor configuration is not frozen")
        if self.augmentation_config != DINOV3_AUGMENTATION_CONFIG:
            raise LocalIdentityContractError("DINOv3 augmentation configuration is not frozen")
        if self.dependency_versions != DINOV3_DEPENDENCY_VERSIONS:
            raise LocalIdentityContractError("DINOv3 dependency versions are not pinned")
        validate_identity_target_map(self.target_map)
        verify_materialized_dinov3_weights(self.weights)

    @property
    def identity_digest(self) -> str:
        return _digest(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, root: str | Path) -> "DinoV3IdentityConfig":
        """Load and validate a resolved configuration against the frozen M0 values."""

        fields = {
            "schema_version",
            "component",
            "capability",
            "quality_state",
            "model",
            "processor",
            "augmentation",
            "target",
            "license",
            "dependency_versions",
            "transform_version",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise LocalIdentityContractError("DINOv3 identity config has unexpected fields")
        if value["schema_version"] != DINOV3_CONFIG_SCHEMA:
            raise LocalIdentityContractError("unsupported DINOv3 identity config schema")
        if value["component"] != "table-evidence-analyzer":
            raise LocalIdentityContractError("DINOv3 identity config has the wrong component")
        if value["capability"] != "visual-card-identity":
            raise LocalIdentityContractError("DINOv3 identity config has the wrong capability")
        if value["quality_state"] != "unusable_smoke_artifact":
            raise LocalIdentityContractError("DINOv3 identity config has an invalid quality state")
        if value["processor"] != DINOV3_PROCESSOR_CONFIG:
            raise LocalIdentityContractError("DINOv3 processor configuration is not frozen")
        if value["augmentation"] != DINOV3_AUGMENTATION_CONFIG:
            raise LocalIdentityContractError("DINOv3 augmentation configuration is not frozen")
        if value["dependency_versions"] != DINOV3_DEPENDENCY_VERSIONS:
            raise LocalIdentityContractError("DINOv3 dependency versions are not pinned")
        if value["transform_version"] != DINOV3_TRANSFORM_VERSION:
            raise LocalIdentityContractError("DINOv3 transform version is not frozen")

        target = value["target"]
        if not isinstance(target, Mapping) or set(target) != {
            "schema_version",
            "card_set_id",
            "class_count",
            "class_map",
        }:
            raise LocalIdentityContractError("DINOv3 target declaration is incomplete")
        if (
            target["schema_version"] != DINOV3_TARGET_MAP_SCHEMA
            or target["card_set_id"] != CARD_SET_ID
            or target["class_count"] != len(CARD_IDENTITIES)
        ):
            raise LocalIdentityContractError("DINOv3 target declaration is not the shared card set")
        target_map = validate_identity_target_map(target["class_map"])

        model = value["model"]
        if not isinstance(model, Mapping) or set(model) != {
            "id",
            "architecture",
            "revision",
            "patch_size",
            "feature",
            "weights",
            "config_file",
            "config_sha256",
            "processor_file",
            "processor_sha256",
        }:
            raise LocalIdentityContractError("DINOv3 model declaration is incomplete")
        if (
            model["id"] != DINOV3_MODEL_ID
            or model["architecture"] != DINOV3_ARCHITECTURE
            or model["patch_size"] != DINOV3_PATCH_SIZE
            or model["feature"] != DINOV3_FEATURE
        ):
            raise LocalIdentityContractError("DINOv3 model declaration is not frozen")
        model_weights = model["weights"]
        if not isinstance(model_weights, Mapping) or set(model_weights) != {"file", "sha256"}:
            raise LocalIdentityContractError("DINOv3 weight declaration is incomplete")
        weights = MaterializedDinoV3Weights(
            root=Path(root).expanduser().resolve(),
            model_id=_text(model["id"], "model ID"),
            model_revision=_text(model["revision"], "model revision"),
            weight_file=_safe_relative_file(model_weights["file"], "weights.file"),
            weight_sha256=_digest_value(model_weights["sha256"], "weights.sha256"),
            config_file=_safe_relative_file(model["config_file"], "config_file"),
            config_sha256=_digest_value(model["config_sha256"], "config_sha256"),
            processor_file=_safe_relative_file(model["processor_file"], "processor_file"),
            processor_sha256=_digest_value(model["processor_sha256"], "processor_sha256"),
        )
        license_value = _license_record(value["license"])
        if not license_value.accepted:
            raise LocalIdentityContractError("explicit DINOv3 license acceptance is required")
        config = cls(
            weights=weights,
            license_record=license_value,
            processor_config=DINOV3_PROCESSOR_CONFIG,
            augmentation_config=DINOV3_AUGMENTATION_CONFIG,
            dependency_versions=DINOV3_DEPENDENCY_VERSIONS,
            target_map=target_map,
        )
        if config.to_mapping() != dict(value):
            raise LocalIdentityContractError("DINOv3 identity config is not canonical")
        verify_materialized_dinov3_weights(weights)
        return config

    def to_mapping(self) -> dict[str, Any]:
        model = {
            "id": DINOV3_MODEL_ID,
            "architecture": DINOV3_ARCHITECTURE,
            "revision": self.weights.model_revision,
            "patch_size": DINOV3_PATCH_SIZE,
            "feature": DINOV3_FEATURE,
            "weights": {"file": self.weights.weight_file, "sha256": self.weights.weight_sha256},
            "config_file": self.weights.config_file,
            "config_sha256": self.weights.config_sha256,
            "processor_file": self.weights.processor_file,
            "processor_sha256": self.weights.processor_sha256,
        }
        return {
            "schema_version": DINOV3_CONFIG_SCHEMA,
            "component": "table-evidence-analyzer",
            "capability": "visual-card-identity",
            "quality_state": "unusable_smoke_artifact",
            "model": model,
            "processor": json.loads(json.dumps(self.processor_config, sort_keys=True)),
            "augmentation": json.loads(json.dumps(self.augmentation_config, sort_keys=True)),
            "target": {
                "schema_version": DINOV3_TARGET_MAP_SCHEMA,
                "card_set_id": CARD_SET_ID,
                "class_count": len(CARD_IDENTITIES),
                "class_map": dict(self.target_map),
            },
            "license": self.license_record.to_mapping(),
            "dependency_versions": dict(self.dependency_versions),
            "transform_version": DINOV3_TRANSFORM_VERSION,
        }


def build_dinov3_identity_config(
    weights: MaterializedDinoV3Weights,
    *,
    license_record: DinoV3LicenseRecord | Mapping[str, Any],
) -> DinoV3IdentityConfig:
    """Build the complete M0 configuration after local weights pass validation."""

    license_value = _license_record(license_record)
    if not license_value.accepted:
        raise LocalIdentityContractError("explicit DINOv3 license acceptance is required")
    verify_materialized_dinov3_weights(weights)
    if weights.model_id != DINOV3_MODEL_ID:
        raise LocalIdentityContractError("pretrained materialization has the wrong model ID")
    return DinoV3IdentityConfig(
        weights=weights,
        license_record=license_value,
        processor_config=DINOV3_PROCESSOR_CONFIG,
        augmentation_config=DINOV3_AUGMENTATION_CONFIG,
        dependency_versions=DINOV3_DEPENDENCY_VERSIONS,
        target_map=canonical_identity_target_map(),
    )


def load_dinov3_identity_config(
    path: str | Path, *, weights_root: str | Path
) -> DinoV3IdentityConfig:
    """Load a resolved DINOv3 configuration and verify its referenced local files."""

    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LocalIdentityContractError(
            f"could not read DINOv3 identity config: {config_path}"
        ) from error
    if not isinstance(value, Mapping):
        raise LocalIdentityContractError("DINOv3 identity config must be a JSON object")
    return DinoV3IdentityConfig.from_mapping(value, root=weights_root)


@dataclass(frozen=True, slots=True)
class TransformedIdentityCrop:
    """The deterministic image and normalized CHW float32 bytes used by the classifier."""

    transformed_ppm: bytes
    tensor_bytes: bytes
    shape: tuple[int, int, int]
    source_width: int
    source_height: int
    crop_sha256: str
    tensor_digest: str
    processor_digest: str

    def pixel_rgb(self, x: int, y: int) -> tuple[int, int, int]:
        if not 0 <= x < DINOV3_IMAGE_SIZE or not 0 <= y < DINOV3_IMAGE_SIZE:
            raise LocalIdentityContractError(
                "transformed pixel coordinate is outside the 224x224 image"
            )
        offset = len(f"P6\n{DINOV3_IMAGE_SIZE} {DINOV3_IMAGE_SIZE}\n255\n".encode())
        pixel = offset + (y * DINOV3_IMAGE_SIZE + x) * 3
        return tuple(self.transformed_ppm[pixel : pixel + 3])  # type: ignore[return-value]

    def to_torch(self) -> Any:
        """Return a cloned PyTorch tensor, importing the optional dependency only on demand."""

        try:
            import torch
        except ImportError as error:
            raise LocalIdentityContractError(
                "PyTorch is required for tensor conversion; install the identity dependency group"
            ) from error
        return torch.frombuffer(self.tensor_bytes, dtype=torch.float32).reshape(self.shape).clone()


def transform_identity_crop(crop_bytes: bytes) -> TransformedIdentityCrop:
    """Decode a binary PPM crop, letterbox it to 224x224, and normalize CHW float32 values."""

    if not isinstance(crop_bytes, bytes) or not crop_bytes:
        raise LocalIdentityContractError("identity crop bytes must be non-empty bytes")
    try:
        source_width, source_height, _maximum, _offset = _ppm_tokens(crop_bytes)
    except ValueError as error:
        raise LocalIdentityContractError("identity crop is not a valid binary PPM image") from error
    if source_width < 4 or source_height < 4:
        raise LocalIdentityContractError("identity crop must be at least 4x4 pixels")
    try:
        with Image.open(BytesIO(crop_bytes)) as image:
            if image.size != (source_width, source_height):
                raise LocalIdentityContractError("PPM dimensions do not match decoded image")
            source = image.convert("RGB")
            scale = min(DINOV3_IMAGE_SIZE / source_width, DINOV3_IMAGE_SIZE / source_height)
            resized_width = max(1, round(source_width * scale))
            resized_height = max(1, round(source_height * scale))
            resized = source.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (DINOV3_IMAGE_SIZE, DINOV3_IMAGE_SIZE), (128, 128, 128))
            canvas.paste(
                resized,
                (
                    (DINOV3_IMAGE_SIZE - resized_width) // 2,
                    (DINOV3_IMAGE_SIZE - resized_height) // 2,
                ),
            )
            pixels = canvas.tobytes()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise LocalIdentityContractError("identity crop is not a valid binary PPM image") from error

    tensor = bytearray(3 * DINOV3_IMAGE_SIZE * DINOV3_IMAGE_SIZE * 4)
    means = DINOV3_PROCESSOR_CONFIG["normalize"]["mean"]
    standard_deviations = DINOV3_PROCESSOR_CONFIG["normalize"]["std"]
    pixel_count = DINOV3_IMAGE_SIZE * DINOV3_IMAGE_SIZE
    for channel in range(3):
        for index in range(pixel_count):
            value = pixels[index * 3 + channel] / 255.0
            normalized = (value - means[channel]) / standard_deviations[channel]
            struct.pack_into("<f", tensor, (channel * pixel_count + index) * 4, normalized)
    transformed_ppm = f"P6\n{DINOV3_IMAGE_SIZE} {DINOV3_IMAGE_SIZE}\n255\n".encode() + pixels
    return TransformedIdentityCrop(
        transformed_ppm=transformed_ppm,
        tensor_bytes=bytes(tensor),
        shape=(3, DINOV3_IMAGE_SIZE, DINOV3_IMAGE_SIZE),
        source_width=source_width,
        source_height=source_height,
        crop_sha256=hashlib.sha256(crop_bytes).hexdigest(),
        tensor_digest=hashlib.sha256(tensor).hexdigest(),
        processor_digest=_digest(DINOV3_PROCESSOR_CONFIG),
    )


# Descriptive aliases keep the contract discoverable to callers that use "check" terminology.
check_dinov3_weight_materialization = materialize_dinov3_weights
validate_materialized_dinov3_weights = verify_materialized_dinov3_weights


__all__ = [
    "DINOV3_ARCHITECTURE",
    "DINOV3_AUGMENTATION_CONFIG",
    "DINOV3_BUNDLE_SCHEMA",
    "DINOV3_CONFIG_FILENAME",
    "DINOV3_CONFIG_SCHEMA",
    "DINOV3_DEPENDENCY_VERSIONS",
    "DINOV3_FEATURE",
    "DINOV3_IMAGE_SIZE",
    "DINOV3_LICENSE_ID",
    "DINOV3_LICENSE_NAME",
    "DINOV3_LICENSE_URL",
    "DINOV3_LICENSE_VERSION",
    "DINOV3_MODEL_ID",
    "DINOV3_PATCH_SIZE",
    "DINOV3_PROCESSOR_CONFIG",
    "DINOV3_PROCESSOR_FILENAME",
    "DINOV3_PROCESSOR_SCHEMA",
    "DINOV3_RUN_SCHEMA",
    "DINOV3_TARGET_MAP_SCHEMA",
    "DINOV3_TRANSFORM_VERSION",
    "DINOV3_WEIGHTS_FILENAME",
    "DINOV3_WEIGHTS_SCHEMA",
    "DinoV3IdentityConfig",
    "DinoV3LicenseRecord",
    "LocalIdentityContractError",
    "MaterializedDinoV3Weights",
    "TransformedIdentityCrop",
    "build_dinov3_identity_config",
    "canonical_identity_target_map",
    "check_dinov3_weight_materialization",
    "identity_from_target_index",
    "identity_target_index",
    "load_dinov3_identity_config",
    "materialize_dinov3_weights",
    "transform_identity_crop",
    "validate_identity_target_map",
    "validate_materialized_dinov3_weights",
    "verify_materialized_dinov3_weights",
]
