"""Local DINOv3 frozen-encoder training for the visual card identity proof.

The module imports PyTorch and Transformers only when a training operation starts.  This keeps the
contract and runtime package usable without the optional training dependency group.  A caller can
inject a local encoder factory for offline contract tests; the default factory loads only the
already-materialized files recorded by :mod:`table_evidence_analyzer.local_identity`.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import random
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data import (
    CropCache,
    DatasetManifest,
    LoadedCrop,
    MaterializedCropDataset,
    SplitManifest,
    assert_valid_dataset,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
    materialize_crops,
)
from .local_identity import (
    DINOV3_AUGMENTATION_CONFIG,
    DINOV3_DEPENDENCY_VERSIONS,
    DINOV3_RUN_SCHEMA,
    DinoV3IdentityConfig,
    LocalIdentityContractError,
    identity_from_target_index,
    identity_target_index,
    load_dinov3_identity_config,
    transform_identity_crop,
    verify_materialized_dinov3_weights,
)

DINOV3_TASK_ADAPTER = "dinov3-frozen-linear-v1"
DINOV3_CHECKPOINT_SCHEMA = "dinov3-identity-checkpoint/v1"
DINOV3_PREDICTION_SCHEMA = "dinov3-identity-predictions/v1"
DINOV3_PREPARATION_SCHEMA = "dinov3-identity-preparation/v1"


class DinoV3TrainingError(ValueError):
    """Raised when the local DINOv3 training contract cannot run."""


class DinoV3TrainingInterrupted(RuntimeError):
    """Raised when a run stops after writing a resumable checkpoint."""


def _torch_modules() -> tuple[Any, Any]:
    try:
        import torch
        from torch import nn
    except ImportError as error:
        raise DinoV3TrainingError(
            "DINOv3 training requires the optional training dependency group"
        ) from error
    return torch, nn


def load_dinov3_encoder(identity: DinoV3IdentityConfig) -> Any:
    """Load the frozen encoder from materialized local files without network access."""

    verify_materialized_dinov3_weights(identity.weights)
    try:
        from transformers import AutoModel
    except ImportError as error:
        raise DinoV3TrainingError(
            "DINOv3 training requires the optional Transformers dependency"
        ) from error
    try:
        encoder = AutoModel.from_pretrained(
            str(identity.weights.root),
            local_files_only=True,
            revision=identity.weights.model_revision,
            use_safetensors=True,
            trust_remote_code=False,
        )
    except Exception as error:
        raise DinoV3TrainingError(
            "could not load the materialized DINOv3 encoder locally"
        ) from error
    return encoder


def _pooler_output(outputs: Any) -> Any:
    features = getattr(outputs, "pooler_output", None)
    if features is None and isinstance(outputs, Mapping):
        features = outputs.get("pooler_output")
    if features is None:
        raise DinoV3TrainingError("DINOv3 encoder output has no pooler_output")
    if getattr(features, "ndim", None) != 2:
        raise DinoV3TrainingError("DINOv3 pooler_output must have shape [batch, hidden_size]")
    return features


class DinoV3FrozenLinearTask:
    """A frozen DINOv3 encoder with one trainable linear 25-class visual head."""

    def __init__(self, encoder: Any, *, class_count: int = 25) -> None:
        torch, nn = _torch_modules()
        if class_count != 25:
            raise DinoV3TrainingError("the DINOv3 visual head must have 25 classes")
        hidden_size = getattr(getattr(encoder, "config", None), "hidden_size", None)
        if isinstance(hidden_size, bool) or not isinstance(hidden_size, int) or hidden_size <= 0:
            raise DinoV3TrainingError("DINOv3 encoder config must declare hidden_size")
        if not isinstance(encoder, nn.Module):
            raise DinoV3TrainingError("DINOv3 encoder must be a PyTorch module")
        self.encoder = encoder
        self.encoder.eval()
        for parameter in self.encoder.parameters():
            parameter.requires_grad_(False)
        self.head = nn.Linear(hidden_size, class_count)
        self.class_count = class_count
        self.hidden_size = hidden_size
        self._torch = torch

    def train(self, mode: bool = True) -> "DinoV3FrozenLinearTask":
        self.encoder.eval()
        self.head.train(mode)
        return self

    def eval(self) -> "DinoV3FrozenLinearTask":
        return self.train(False)

    def to(self, device: Any) -> "DinoV3FrozenLinearTask":
        self.encoder.to(device)
        self.head.to(device)
        return self

    def forward(self, pixel_values: Any) -> Any:
        self.encoder.eval()
        with self._torch.no_grad():
            outputs = self.encoder(pixel_values=pixel_values)
            features = _pooler_output(outputs)
        if features.shape[1] != self.hidden_size:
            raise DinoV3TrainingError(
                "DINOv3 pooler_output hidden size does not match the identity head"
            )
        return self.head(features)

    def compute_loss(self, pixel_values: Any, targets: Any) -> Any:
        """Compute the fixed cross-entropy objective for the trainable head."""

        return self._torch.nn.functional.cross_entropy(self.forward(pixel_values), targets)

    def trainable_parameters(self) -> Any:
        return self.head.parameters()

    def state_dict(self) -> dict[str, Any]:
        return {
            **{
                f"encoder.{key}": value.detach().cpu()
                for key, value in self.encoder.state_dict().items()
            },
            **{
                f"head.{key}": value.detach().cpu() for key, value in self.head.state_dict().items()
            },
        }

    def load_state_dict(self, state: Mapping[str, Any]) -> None:
        encoder_state = {
            key[8:]: value for key, value in state.items() if key.startswith("encoder.")
        }
        head_state = {key[5:]: value for key, value in state.items() if key.startswith("head.")}
        if set(head_state) != {"weight", "bias"}:
            raise DinoV3TrainingError("checkpoint identity head state is incomplete")
        try:
            self.encoder.load_state_dict(encoder_state, strict=True)
            self.head.load_state_dict(head_state, strict=True)
        except (RuntimeError, TypeError) as error:
            raise DinoV3TrainingError(
                "checkpoint model state does not match the DINOv3 task"
            ) from error


EncoderFactory = Callable[[DinoV3IdentityConfig], Any]


@dataclass(frozen=True, slots=True)
class DinoV3TrainConfig:
    """Resolved inputs for one local DINOv3 identity training run."""

    dataset: Path
    split: Path
    artifacts: Path
    identity_config: DinoV3IdentityConfig | Path
    output: Path
    campaign_manifest: Path | None = None
    seed: int = 17
    epochs: int = 8
    batch_size: int = 1
    learning_rate: float = 0.001
    weight_decay: float = 0.0
    device: str = "cpu"
    precision: str = "fp32"
    resume: Path | None = None
    max_steps: int | None = None
    weights_root: Path | None = None

    def __post_init__(self) -> None:
        if self.epochs <= 0:
            raise DinoV3TrainingError("epochs must be positive")
        if self.batch_size <= 0:
            raise DinoV3TrainingError("batch_size must be positive")
        if self.learning_rate <= 0:
            raise DinoV3TrainingError("learning_rate must be positive")
        if self.weight_decay < 0:
            raise DinoV3TrainingError("weight_decay must not be negative")
        if self.device not in {"cpu", "mps", "cuda"}:
            raise DinoV3TrainingError(f"unsupported device request: {self.device}")
        if self.precision != "fp32":
            raise DinoV3TrainingError("the DINOv3 smoke task supports fp32 only")
        if self.max_steps is not None and self.max_steps <= 0:
            raise DinoV3TrainingError("max_steps must be positive when set")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, base: Path) -> "DinoV3TrainConfig":
        required = {"dataset", "split", "artifacts", "identity_config", "output"}
        missing = required - set(value)
        if missing:
            raise DinoV3TrainingError(
                "DINOv3 training config is missing: " + ", ".join(sorted(missing))
            )
        identity_path = base / str(value["identity_config"])
        weights_root = base / str(value["weights_root"]) if value.get("weights_root") else None
        return cls(
            dataset=base / str(value["dataset"]),
            split=base / str(value["split"]),
            artifacts=base / str(value["artifacts"]),
            identity_config=identity_path,
            output=base / str(value["output"]),
            campaign_manifest=(
                base / str(value["campaign_manifest"]) if value.get("campaign_manifest") else None
            ),
            seed=int(value.get("seed", 17)),
            epochs=int(value.get("epochs", 8)),
            batch_size=int(value.get("batch_size", 1)),
            learning_rate=float(value.get("learning_rate", 0.001)),
            weight_decay=float(value.get("weight_decay", 0.0)),
            device=str(value.get("device", "cpu")),
            precision=str(value.get("precision", "fp32")),
            resume=(base / str(value["resume"]) if value.get("resume") else None),
            max_steps=(int(value["max_steps"]) if value.get("max_steps") is not None else None),
            weights_root=weights_root,
        )


def load_dinov3_training_config(path: str | Path) -> DinoV3TrainConfig:
    """Load a JSON training configuration relative to its file."""

    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DinoV3TrainingError(
            f"could not read DINOv3 training config: {config_path}"
        ) from error
    if not isinstance(value, Mapping):
        raise DinoV3TrainingError("DINOv3 training config must be a JSON object")
    return DinoV3TrainConfig.from_mapping(value, base=config_path.parent)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_torch_save(torch: Any, value: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            torch.save(value, temporary)
            temporary.flush()
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def load_dinov3_checkpoint(path: str | Path) -> Mapping[str, Any]:
    """Load and minimally validate one native DINOv3 checkpoint."""

    torch, _ = _torch_modules()
    checkpoint_path = Path(path)
    try:
        value = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    except Exception as error:
        raise ValueError(f"could not load DINOv3 checkpoint: {checkpoint_path}") from error
    if not isinstance(value, Mapping) or value.get("schema_version") != DINOV3_CHECKPOINT_SCHEMA:
        raise ValueError("DINOv3 checkpoint has an unsupported checkpoint schema")
    required = {"config", "model_state", "optimizer_state", "progress", "best"}
    if not required <= set(value):
        raise ValueError("DINOv3 checkpoint is incomplete")
    if not isinstance(value["model_state"], Mapping) or not isinstance(
        value["optimizer_state"], Mapping
    ):
        raise ValueError("DINOv3 checkpoint state is invalid")
    return value


def _resolve_identity(config: DinoV3TrainConfig) -> DinoV3IdentityConfig:
    if isinstance(config.identity_config, DinoV3IdentityConfig):
        return config.identity_config
    root = config.weights_root or config.identity_config.parent
    try:
        return load_dinov3_identity_config(config.identity_config, weights_root=root)
    except LocalIdentityContractError as error:
        raise DinoV3TrainingError(str(error)) from error


def _environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for package in ("torch", "torchvision", "transformers", "safetensors"):
        try:
            packages[package] = importlib.metadata.version(package)
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


def _dirty_state() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(result.stdout.strip())


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_record(config: DinoV3TrainConfig) -> dict[str, Any]:
    identity_path = (
        str(config.identity_config.expanduser().resolve())
        if isinstance(config.identity_config, Path)
        else "<resolved-identity-config>"
    )
    return {
        "dataset": str(config.dataset.expanduser().resolve()),
        "split": str(config.split.expanduser().resolve()),
        "artifacts": str(config.artifacts.expanduser().resolve()),
        "identity_config": identity_path,
        "output": str(config.output.expanduser().resolve()),
        "campaign_manifest": (
            str(config.campaign_manifest.expanduser().resolve())
            if config.campaign_manifest is not None
            else None
        ),
        "seed": config.seed,
        "epochs": config.epochs,
        "batch_size": config.batch_size,
        "learning_rate": config.learning_rate,
        "weight_decay": config.weight_decay,
        "device": config.device,
        "precision": config.precision,
        "max_steps": config.max_steps,
    }


def _base_run_record(config: DinoV3TrainConfig, started: float) -> dict[str, Any]:
    return {
        "schema_version": DINOV3_RUN_SCHEMA,
        "run_id": f"dinov3-m1-{int(started)}",
        "status": "failed",
        "quality_state": "unusable_smoke_artifact",
        "task": DINOV3_TASK_ADAPTER,
        "started_at": _utc(started),
        "config": _config_record(config),
        "environment": _environment(),
        "code_revision": _code_revision(),
        "dirty_state": _dirty_state(),
        "progress": {"epoch": 0, "batch_index": 0, "step": 0, "next_epoch": 0, "next_batch": 0},
    }


def _input_record(
    identity: DinoV3IdentityConfig,
    dataset: DatasetManifest,
    split: SplitManifest,
    cache_digest: str,
    campaign: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    model = identity.to_mapping()["model"]
    target = identity.to_mapping()["target"]
    result = {
        "identity_digest": identity.identity_digest,
        "model_id": model["id"],
        "model_revision": model["revision"],
        "weight_sha256": model["weights"]["sha256"],
        "config_sha256": model["config_sha256"],
        "processor_sha256": model["processor_sha256"],
        "transform_version": identity.to_mapping()["transform_version"],
        "card_set_id": target["card_set_id"],
        "class_count": target["class_count"],
        "dependency_versions": dict(DINOV3_DEPENDENCY_VERSIONS),
        "dataset_version_digest": dataset.digest,
        "split_version_digest": split.digest,
        "crop_cache_digest": cache_digest,
    }
    if campaign is not None:
        result.update(
            {
                "campaign_id": campaign["campaign_id"],
                "campaign_manifest_digest": campaign["manifest_digest"],
                "revision_content_digests": campaign["revision_content_digests"],
                "recipe_digest": campaign["recipe_digest"],
            }
        )
    return result


def _semantic_config(
    config: DinoV3TrainConfig, identity: DinoV3IdentityConfig, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "task_adapter": DINOV3_TASK_ADAPTER,
        "identity_digest": identity.identity_digest,
        "dataset_version_digest": inputs["dataset_version_digest"],
        "split_version_digest": inputs["split_version_digest"],
        "crop_cache_digest": inputs["crop_cache_digest"],
        "transform_version": inputs["transform_version"],
        "augmentation": DINOV3_AUGMENTATION_CONFIG,
        "class_count": 25,
        "seed": config.seed,
        "epochs": config.epochs,
        "batch_size": config.batch_size,
        "learning_rate": config.learning_rate,
        "weight_decay": config.weight_decay,
        "precision": config.precision,
        "campaign_id": inputs.get("campaign_id"),
        "campaign_manifest_digest": inputs.get("campaign_manifest_digest"),
    }


def _validate_resume(checkpoint: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    if checkpoint.get("config") != dict(expected):
        raise DinoV3TrainingError("DINOv3 resume checkpoint is incompatible with frozen inputs")
    progress = checkpoint.get("progress")
    if not isinstance(progress, Mapping):
        raise DinoV3TrainingError("DINOv3 resume checkpoint has no progress record")
    for name in ("step", "next_epoch", "next_batch"):
        if isinstance(progress.get(name), bool) or not isinstance(progress.get(name), int):
            raise DinoV3TrainingError("DINOv3 resume checkpoint progress is invalid")
    if progress["step"] < 0 or progress["next_epoch"] < 0 or progress["next_batch"] < 0:
        raise DinoV3TrainingError("DINOv3 resume checkpoint progress is invalid")


def _apply_augmentation(tensor: Any, *, seed: int, epoch: int, sample_id: str) -> Any:
    """Apply only the declared deterministic identity-preserving train transforms."""

    torch, _ = _torch_modules()
    selector = int(hashlib.sha256(f"{seed}:{epoch}:{sample_id}".encode()).hexdigest()[:8], 16)
    if selector & 1:
        tensor = torch.flip(tensor, dims=(-1, -2))

    means = tensor.new_tensor([0.485, 0.456, 0.406]).reshape(3, 1, 1)
    standard_deviations = tensor.new_tensor([0.229, 0.224, 0.225]).reshape(3, 1, 1)
    pixels = tensor * standard_deviations + means
    brightness = 1.0 + (((selector >> 1) % 3) - 1) * 0.15
    contrast = 1.0 + (((selector >> 3) % 3) - 1) * 0.15
    saturation = 1.0 + (((selector >> 5) % 3) - 1) * 0.10
    pixels = (pixels - 0.5) * contrast + 0.5
    gray = pixels.mean(dim=0, keepdim=True)
    pixels = gray + (pixels - gray) * saturation
    pixels = (pixels * brightness).clamp(0.0, 1.0)
    return (pixels - means) / standard_deviations


def _batches(samples: Sequence[LoadedCrop], batch_size: int) -> list[tuple[LoadedCrop, ...]]:
    return [
        tuple(samples[start : start + batch_size]) for start in range(0, len(samples), batch_size)
    ]


def _batch_tensors(
    samples: Sequence[LoadedCrop], *, train: bool, epoch: int, seed: int
) -> tuple[Any, Any]:
    torch, _ = _torch_modules()
    tensors = []
    targets = []

    for sample in samples:
        tensor = transform_identity_crop(sample.crop_bytes).to_torch()
        if train:
            tensor = _apply_augmentation(
                tensor, seed=seed, epoch=epoch, sample_id=sample.dataset_item_id
            )
        tensors.append(tensor)
        targets.append(identity_target_index(sample.target))
    return torch.stack(tensors), torch.tensor(targets, dtype=torch.long)


def _predict(
    task: DinoV3FrozenLinearTask,
    samples: Sequence[LoadedCrop],
    *,
    device: Any,
    seed: int,
) -> tuple[list[dict[str, Any]], float, float]:
    torch, _ = _torch_modules()
    task.eval()
    rows: list[dict[str, Any]] = []
    total_loss = 0.0
    correct = 0
    batches = _batches(samples, max(1, len(samples))) if samples else []
    with torch.no_grad():
        for batch in batches:
            tensors, targets = _batch_tensors(batch, train=False, epoch=0, seed=seed)
            logits = task.forward(tensors.to(device))
            if not torch.isfinite(logits).all():
                raise DinoV3TrainingError("DINOv3 prediction produced non-finite logits")
            loss = torch.nn.functional.cross_entropy(logits, targets.to(device))
            probabilities = torch.softmax(logits, dim=1).detach().cpu()
            if not torch.isfinite(probabilities).all():
                raise DinoV3TrainingError("DINOv3 prediction produced non-finite probabilities")
            ranked = torch.argsort(probabilities, dim=1, descending=True)
            total_loss += float(loss.item()) * len(batch)
            correct += int((ranked[:, 0] == targets).sum().item())
            for row_index, sample in enumerate(batch):
                indices = ranked[row_index].tolist()
                rows.append(
                    {
                        "sample_id": sample.dataset_item_id,
                        "target": sample.target,
                        "target_index": int(targets[row_index]),
                        "prediction": identity_from_target_index(indices[0]),
                        "top_k": [identity_from_target_index(index) for index in indices],
                        "probabilities": [
                            float(probabilities[row_index, index]) for index in indices
                        ],
                    }
                )
    count = len(samples)
    return rows, total_loss / count if count else 0.0, correct / count if count else 0.0


def _checkpoint_payload(
    torch: Any,
    task: DinoV3FrozenLinearTask,
    optimizer: Any,
    semantic_config: Mapping[str, Any],
    progress: Mapping[str, int],
    best: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": DINOV3_CHECKPOINT_SCHEMA,
        "config": dict(semantic_config),
        "model_state": task.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "progress": dict(progress),
        "best": dict(best),
        "rng_state": {"torch_cpu": torch.get_rng_state()},
    }


def _load_checkpoint_state(
    torch: Any, task: DinoV3FrozenLinearTask, optimizer: Any, checkpoint: Mapping[str, Any]
) -> tuple[dict[str, int], dict[str, Any]]:
    task.load_state_dict(checkpoint["model_state"])
    try:
        optimizer.load_state_dict(checkpoint["optimizer_state"])
        rng_state = checkpoint.get("rng_state", {}).get("torch_cpu")
        if rng_state is not None:
            torch.set_rng_state(rng_state)
    except (RuntimeError, TypeError, AttributeError) as error:
        raise DinoV3TrainingError("DINOv3 resume checkpoint optimizer state is invalid") from error
    return dict(checkpoint["progress"]), dict(checkpoint["best"])


def _read_training_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DinoV3TrainingError(f"could not read {context}: {path}") from error
    if not isinstance(value, Mapping):
        raise DinoV3TrainingError(f"{context} must be a JSON object: {path}")
    return dict(value)


def _campaign_path(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise DinoV3TrainingError(f"campaign {field} is missing")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise DinoV3TrainingError(
            f"campaign {field} must stay below the campaign directory"
        ) from error
    return path


def _load_campaign_inputs(
    config: DinoV3TrainConfig,
    dataset: DatasetManifest,
    split: SplitManifest,
    artifacts: Any,
) -> tuple[dict[str, Any], CropCache]:
    manifest_path = config.campaign_manifest
    if manifest_path is None:
        raise DinoV3TrainingError("DINOv3 campaign manifest is required for campaign training")
    manifest_path = manifest_path.expanduser().resolve()
    manifest = _read_training_json(manifest_path, "DINOv3 campaign manifest")
    if manifest.get("schema_version") != DINOV3_PREPARATION_SCHEMA:
        raise DinoV3TrainingError("DINOv3 campaign manifest schema is unsupported")
    declared_digest = manifest.get("manifest_digest")
    if declared_digest != _digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"}
    ):
        raise DinoV3TrainingError("DINOv3 campaign manifest digest does not match contents")
    if manifest.get("milestone") != "M1" or manifest.get("state") != "frozen":
        raise DinoV3TrainingError("DINOv3 campaign manifest is not a frozen M1 campaign")
    campaign_root = manifest_path.parent
    campaign_id = manifest.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise DinoV3TrainingError("DINOv3 campaign manifest has no campaign ID")

    references = {
        "dataset": (manifest.get("dataset"), dataset.digest),
        "split": (manifest.get("split"), split.digest),
        "artifact_index": (manifest.get("artifact_index"), artifacts.digest),
        "crop_inventory": (manifest.get("crop_inventory"), None),
        "recipe": (manifest.get("recipe"), None),
        "training_preflight": (manifest.get("training_preflight"), None),
    }
    loaded: dict[str, dict[str, Any]] = {}
    for name, (reference, expected_digest) in references.items():
        if not isinstance(reference, Mapping):
            raise DinoV3TrainingError(f"DINOv3 campaign {name} reference is invalid")
        path = _campaign_path(campaign_root, reference.get("path"), f"{name}.path")
        value = _read_training_json(path, f"DINOv3 campaign {name}")
        loaded[name] = value
        if name in {"recipe", "training_preflight"}:
            if reference.get("digest") != _digest(value):
                raise DinoV3TrainingError(f"DINOv3 campaign {name} digest does not match contents")
        elif name == "crop_inventory":
            if reference.get("digest") != value.get("cache_digest"):
                raise DinoV3TrainingError("DINOv3 campaign crop cache digest does not match")
        elif reference.get("digest") != expected_digest:
            raise DinoV3TrainingError(f"DINOv3 campaign {name} digest does not match inputs")
        expected_path = {
            "dataset": config.dataset,
            "split": config.split,
            "artifact_index": config.artifacts,
        }.get(name)
        if expected_path is not None and expected_path.expanduser().resolve() != path:
            raise DinoV3TrainingError(f"DINOv3 training {name} is not the frozen campaign input")

    preflight = loaded["training_preflight"]
    if preflight.get("schema_version") != "dinov3-identity-training-preflight/v1":
        raise DinoV3TrainingError("DINOv3 campaign training preflight schema is unsupported")
    if preflight.get("campaign_id") != campaign_id or preflight.get("state") != "ready":
        raise DinoV3TrainingError("DINOv3 campaign training preflight is not ready")
    recipe = loaded["recipe"]
    if recipe.get("campaign_id") != campaign_id:
        raise DinoV3TrainingError("DINOv3 campaign recipe belongs to a different campaign")
    optimizer = recipe.get("optimizer")
    if not isinstance(optimizer, Mapping):
        raise DinoV3TrainingError("DINOv3 campaign recipe has no optimizer contract")
    expected_config = {
        "seed": recipe.get("seed"),
        "epochs": recipe.get("max_epochs"),
        "batch_size": recipe.get("batch_size"),
        "learning_rate": optimizer.get("learning_rate"),
        "weight_decay": optimizer.get("weight_decay"),
        "device": recipe.get("device"),
        "precision": recipe.get("precision"),
    }
    actual_config = {
        "seed": config.seed,
        "epochs": config.epochs,
        "batch_size": config.batch_size,
        "learning_rate": config.learning_rate,
        "weight_decay": config.weight_decay,
        "device": config.device,
        "precision": config.precision,
    }
    if actual_config != expected_config:
        raise DinoV3TrainingError(
            "DINOv3 training arguments differ from the frozen campaign recipe"
        )
    identity_reference = preflight.get("checks", {}).get("identity_config")
    if isinstance(identity_reference, Mapping) and isinstance(config.identity_config, Path):
        declared_path = Path(str(identity_reference.get("path", "")))
        if not declared_path.is_absolute():
            repository_root = next(
                (
                    parent.parent
                    for parent in (campaign_root, *campaign_root.parents)
                    if parent.name == "data"
                ),
                campaign_root,
            )
            declared_path = repository_root / declared_path
        if config.identity_config.expanduser().resolve() != declared_path.resolve():
            raise DinoV3TrainingError("DINOv3 identity config is not the frozen campaign input")
        expected_digest = identity_reference.get("digest")
        if not isinstance(expected_digest, str) or not declared_path.is_file():
            raise DinoV3TrainingError("frozen DINOv3 identity config is missing")
        if _file_sha256(declared_path) != expected_digest:
            raise DinoV3TrainingError("frozen DINOv3 identity config digest does not match")
    cache_path = _campaign_path(
        campaign_root,
        manifest["crop_inventory"]["path"],
        "crop_inventory.path",
    )
    cache = CropCache.from_mapping(loaded["crop_inventory"], root=cache_path.parent)
    for crop in cache.crops:
        cache.read(crop)
    return (
        {
            "campaign_id": campaign_id,
            "manifest_digest": declared_digest,
            "manifest_path": str(manifest_path),
            "revision_content_digests": list(manifest.get("revision_content_digests", [])),
            "recipe_digest": manifest["recipe"]["digest"],
            "recipe": recipe,
            "training_preflight": preflight,
        },
        cache,
    )


def train_dinov3_identity(
    config: DinoV3TrainConfig, *, encoder_factory: EncoderFactory | None = None
) -> Path:
    """Train the frozen DINOv3 identity head and write a resumable local run."""

    started = time.time()
    output = config.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()) and config.resume is None:
        raise DinoV3TrainingError(f"DINOv3 output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    run_path = output / "run.json"
    record = _base_run_record(config, started)
    _write_json(run_path, record)
    torch = None
    try:
        identity = _resolve_identity(config)
        dataset = load_dataset_manifest(config.dataset)
        split = load_split_manifest(config.split)
        artifacts = load_artifact_index(config.artifacts)
        assert_valid_dataset(dataset, split=split, artifacts=artifacts)
        campaign: dict[str, Any] | None = None
        if config.campaign_manifest is not None:
            campaign, cache = _load_campaign_inputs(config, dataset, split, artifacts)
        else:
            cache = materialize_crops(dataset, split, artifacts, output / "crop-cache")
        train_samples = tuple(MaterializedCropDataset(cache, partition="train"))
        validation_samples = tuple(MaterializedCropDataset(cache, partition="validation"))
        if not train_samples:
            raise DinoV3TrainingError("DINOv3 training split is empty")
        inputs = _input_record(identity, dataset, split, cache.digest, campaign)
        semantic_config = _semantic_config(config, identity, inputs)
        record.update(
            {
                "identity_config": identity.to_mapping(),
                "license": identity.license_record.to_mapping(),
                "inputs": inputs,
                "model": {
                    "adapter": DINOV3_TASK_ADAPTER,
                    "encoder": identity.to_mapping()["model"],
                    "head": {"type": "linear", "class_count": 25},
                },
                "device": config.device,
                "precision": config.precision,
                "status": "running",
            }
        )
        if campaign is not None:
            record["campaign"] = campaign
        _write_json(run_path, record)

        torch, _ = _torch_modules()
        torch.manual_seed(config.seed)
        random.seed(config.seed)
        if config.device != "cpu":
            available = (
                torch.backends.mps.is_available()
                if config.device == "mps"
                else torch.cuda.is_available()
            )
            if not available:
                raise DinoV3TrainingError(f"requested device is unavailable: {config.device}")
        device = torch.device(config.device)
        encoder = (
            encoder_factory(identity)
            if encoder_factory is not None
            else load_dinov3_encoder(identity)
        )
        task = DinoV3FrozenLinearTask(encoder).to(device)
        optimizer = torch.optim.AdamW(
            task.trainable_parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
        )
        record["training"] = {
            "semantic_config": semantic_config,
            "hidden_size": task.hidden_size,
            "encoder_loader": (
                "injected_factory" if encoder_factory is not None else "transformers_local_files"
            ),
        }
        if config.resume is not None:
            record["resumed_from"] = str(config.resume.expanduser().resolve())
        _write_json(run_path, record)
        progress = {"epoch": 0, "batch_index": 0, "step": 0, "next_epoch": 0, "next_batch": 0}
        best: dict[str, Any] = {"metric": "validation_top_1_accuracy", "value": -1.0, "epoch": 0}
        if config.resume is not None:
            checkpoint = load_dinov3_checkpoint(config.resume)
            _validate_resume(checkpoint, semantic_config)
            progress, best = _load_checkpoint_state(torch, task, optimizer, checkpoint)
        if progress["next_epoch"] > config.epochs:
            raise DinoV3TrainingError(
                "DINOv3 resume checkpoint is past the configured epoch budget"
            )

        batches = _batches(train_samples, config.batch_size)
        epoch = progress["next_epoch"]
        batch_start = progress["next_batch"]
        last_train_loss = 0.0
        while epoch < config.epochs:
            if batch_start > len(batches):
                raise DinoV3TrainingError("DINOv3 resume checkpoint batch progress is invalid")
            task.train()
            for batch_index in range(batch_start, len(batches)):
                batch = batches[batch_index]
                pixel_values, targets = _batch_tensors(
                    batch, train=True, epoch=epoch, seed=config.seed
                )
                optimizer.zero_grad(set_to_none=True)
                loss = task.compute_loss(pixel_values.to(device), targets.to(device))
                if not torch.isfinite(loss):
                    raise DinoV3TrainingError("DINOv3 training produced a non-finite loss")
                loss.backward()
                optimizer.step()
                progress = {
                    "epoch": epoch + 1 if batch_index + 1 == len(batches) else epoch,
                    "batch_index": batch_index + 1,
                    "step": progress["step"] + 1,
                    "next_epoch": epoch + 1 if batch_index + 1 == len(batches) else epoch,
                    "next_batch": 0 if batch_index + 1 == len(batches) else batch_index + 1,
                }
                last_train_loss = float(loss.item())
                _atomic_torch_save(
                    torch,
                    _checkpoint_payload(torch, task, optimizer, semantic_config, progress, best),
                    output / "checkpoint-last.pt",
                )
                record["progress"] = progress
                record["metrics"] = {
                    "steps": progress["step"],
                    "epochs_completed": progress["next_epoch"],
                    "last_train_loss": last_train_loss,
                }
                _write_json(run_path, record)
                if config.max_steps is not None and progress["step"] >= config.max_steps:
                    raise DinoV3TrainingInterrupted(
                        f"DINOv3 training stopped after {config.max_steps} step(s)"
                    )
            train_rows, epoch_train_loss, train_accuracy = _predict(
                task, train_samples, device=device, seed=config.seed
            )
            validation_rows, validation_loss, validation_accuracy = _predict(
                task, validation_samples, device=device, seed=config.seed
            )
            last_train_loss = epoch_train_loss
            if validation_accuracy > float(best["value"]):
                best = {
                    "metric": "validation_top_1_accuracy",
                    "value": validation_accuracy,
                    "epoch": epoch + 1,
                }
                _atomic_torch_save(
                    torch,
                    _checkpoint_payload(torch, task, optimizer, semantic_config, progress, best),
                    output / "checkpoint-best.pt",
                )
            _atomic_torch_save(
                torch,
                _checkpoint_payload(torch, task, optimizer, semantic_config, progress, best),
                output / "checkpoint-last.pt",
            )
            epoch += 1
            batch_start = 0

        if not (output / "checkpoint-best.pt").exists():
            _atomic_torch_save(
                torch,
                _checkpoint_payload(torch, task, optimizer, semantic_config, progress, best),
                output / "checkpoint-best.pt",
            )
        final_progress = dict(progress)
        best_checkpoint = load_dinov3_checkpoint(output / "checkpoint-best.pt")
        _validate_resume(best_checkpoint, semantic_config)
        _load_checkpoint_state(torch, task, optimizer, best_checkpoint)
        train_rows, train_loss, train_accuracy = _predict(
            task, train_samples, device=device, seed=config.seed
        )
        validation_rows, validation_loss, validation_accuracy = _predict(
            task, validation_samples, device=device, seed=config.seed
        )
        reloaded_validation_rows, _, _ = _predict(
            task, validation_samples, device=device, seed=config.seed
        )
        validation_digest = _digest(validation_rows)
        if reloaded_validation_rows != validation_rows:
            raise DinoV3TrainingError(
                "DINOv3 best checkpoint validation predictions are not reproducible"
            )
        _write_json(
            output / "predictions-train.json",
            {"schema_version": DINOV3_PREDICTION_SCHEMA, "predictions": train_rows},
        )
        _write_json(
            output / "predictions-validation.json",
            {"schema_version": DINOV3_PREDICTION_SCHEMA, "predictions": validation_rows},
        )
        record.update(
            {
                "status": "completed",
                "completed_at": _utc(time.time()),
                "progress": final_progress,
                "metrics": {
                    "train_samples": len(train_samples),
                    "validation_samples": len(validation_samples),
                    "steps": final_progress["step"],
                    "epochs_completed": final_progress["next_epoch"],
                    "train_loss": train_loss,
                    "train_top_1_accuracy": train_accuracy,
                    "validation_loss": validation_loss,
                    "validation_top_1_accuracy": validation_accuracy,
                    "best_validation_top_1_accuracy": best["value"],
                    "best_checkpoint_validation_digest": validation_digest,
                    "duration_seconds": round(time.time() - started, 6),
                },
                "checkpoints": {"last": "checkpoint-last.pt", "best": "checkpoint-best.pt"},
            }
        )
        _write_json(run_path, record)
        return output
    except (DinoV3TrainingInterrupted, KeyboardInterrupt) as error:
        record.update(
            {
                "status": "interrupted",
                "error": {"type": type(error).__name__, "message": str(error)},
                "interrupted_at": _utc(time.time()),
            }
        )
        _write_json(run_path, record)
        if isinstance(error, KeyboardInterrupt):
            raise
        raise
    except Exception as error:
        record.update(
            {
                "status": "failed",
                "error": {"type": type(error).__name__, "message": str(error)},
                "failed_at": _utc(time.time()),
            }
        )
        _write_json(run_path, record)
        raise


__all__ = [
    "DINOV3_CHECKPOINT_SCHEMA",
    "DINOV3_PREDICTION_SCHEMA",
    "DINOV3_PREPARATION_SCHEMA",
    "DINOV3_TASK_ADAPTER",
    "DinoV3FrozenLinearTask",
    "DinoV3TrainConfig",
    "DinoV3TrainingError",
    "DinoV3TrainingInterrupted",
    "load_dinov3_checkpoint",
    "load_dinov3_encoder",
    "load_dinov3_training_config",
    "train_dinov3_identity",
]
