"""Training-free runtime adapter for a bundled local DINOv3 identity classifier."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .card_classification import CardClassificationResult
from .dinov3_bundle import DinoV3IdentityBundle, load_dinov3_identity_bundle
from .local_identity import (
    LocalIdentityContractError,
    identity_from_target_index,
    transform_identity_crop,
)

DINOV3_RUNTIME_VERSION = "dinov3-local-identity-v1"
DINOV3_RUNTIME_DEVICES = frozenset({"cpu", "mps", "cuda"})


class DinoV3InferenceError(ValueError):
    """Raised when a local DINOv3 runtime request cannot be constructed."""


def _import_torch() -> Any:
    try:
        import torch
    except ImportError as error:
        raise DinoV3InferenceError(
            "DINOv3 local inference requires PyTorch; install the inference dependency group"
        ) from error
    return torch


def _device_available(torch: Any, device: str) -> bool:
    if device == "cpu":
        return True
    if device == "mps":
        return bool(torch.backends.mps.is_available())
    if device == "cuda":
        return bool(torch.cuda.is_available())
    return False


def _load_encoder(bundle: DinoV3IdentityBundle) -> Any:
    try:
        from transformers import AutoModel
    except ImportError as error:
        raise DinoV3InferenceError(
            "DINOv3 local inference requires Transformers; install the inference dependency group"
        ) from error
    try:
        return AutoModel.from_pretrained(
            str(bundle.encoder_path),
            revision=bundle.identity.weights.model_revision,
            local_files_only=True,
            use_safetensors=True,
            trust_remote_code=False,
        )
    except Exception as error:
        raise DinoV3InferenceError(f"could not load the bundled DINOv3 encoder: {error}") from error


def _load_head(torch: Any, bundle: DinoV3IdentityBundle) -> Any:
    try:
        payload = torch.load(bundle.head_path, map_location="cpu", weights_only=True)
    except Exception as error:
        raise DinoV3InferenceError(
            f"could not load the bundled DINOv3 identity head: {error}"
        ) from error
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "adapter",
        "class_count",
        "hidden_size",
        "source_checkpoint_sha256",
        "state_dict",
    }:
        raise DinoV3InferenceError("bundled DINOv3 identity head has unexpected fields")
    head_metadata = bundle.manifest["head"]
    if (
        payload["schema_version"] != head_metadata["schema_version"]
        or payload["adapter"] != head_metadata["adapter"]
        or payload["class_count"] != head_metadata["class_count"]
        or payload["hidden_size"] != head_metadata["hidden_size"]
        or payload["source_checkpoint_sha256"] != bundle.manifest["source_checkpoint_sha256"]
    ):
        raise DinoV3InferenceError(
            "bundled DINOv3 identity head metadata does not match the manifest"
        )
    state = payload["state_dict"]
    if not isinstance(state, Mapping) or set(state) != {"weight", "bias"}:
        raise DinoV3InferenceError("bundled DINOv3 identity head state is incomplete")
    head = torch.nn.Linear(int(payload["hidden_size"]), int(payload["class_count"]))
    try:
        head.load_state_dict(dict(state), strict=True)
    except (RuntimeError, TypeError) as error:
        raise DinoV3InferenceError("bundled DINOv3 identity head state is invalid") from error
    return head


def _pooler_output(outputs: Any) -> Any:
    features = getattr(outputs, "pooler_output", None)
    if features is None and isinstance(outputs, Mapping):
        features = outputs.get("pooler_output")
    if features is None or getattr(features, "ndim", None) != 2:
        raise DinoV3InferenceError(
            "DINOv3 encoder output has no [batch, hidden_size] pooler_output"
        )
    return features


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.monotonic() - started) * 1000.0, 3)


class DinoV3IdentityClassifier:
    """Classify transformed PPM crops with one explicitly selected local device."""

    name = "local-dinov3"
    version = DINOV3_RUNTIME_VERSION
    calibration = "uncalibrated"

    def __init__(
        self,
        bundle: str | Path | DinoV3IdentityBundle,
        *,
        device: str = "cpu",
        encoder_loader: Callable[[DinoV3IdentityBundle], Any] | None = None,
        torch_module: Any | None = None,
    ) -> None:
        if device not in DINOV3_RUNTIME_DEVICES:
            raise DinoV3InferenceError(f"unsupported DINOv3 inference device: {device}")
        # This validation happens before torch or model construction.  It is the only path to a
        # runtime model, so corrupt files cannot be hidden by a loader or a device fallback.
        self.bundle = (
            bundle
            if isinstance(bundle, DinoV3IdentityBundle)
            else load_dinov3_identity_bundle(bundle)
        )
        torch = torch_module or _import_torch()
        if not _device_available(torch, device):
            raise DinoV3InferenceError(
                f"requested DINOv3 inference device is unavailable: {device}"
            )
        self.device = device
        self._torch = torch
        started = time.monotonic()
        try:
            encoder = (encoder_loader or _load_encoder)(self.bundle)
            if not isinstance(encoder, torch.nn.Module):
                raise DinoV3InferenceError("DINOv3 encoder loader did not return a PyTorch module")
            hidden_size = getattr(getattr(encoder, "config", None), "hidden_size", None)
            if hidden_size != self.bundle.manifest["head"]["hidden_size"]:
                raise DinoV3InferenceError(
                    "DINOv3 encoder hidden size does not match the bundle head"
                )
            self._encoder = encoder.to(device).eval()
            self._head = _load_head(torch, self.bundle).to(device).eval()
            self.load_latency_ms = _elapsed_ms(started)
        except DinoV3InferenceError:
            raise
        except Exception as error:
            raise DinoV3InferenceError(
                f"could not construct DINOv3 inference model: {error}"
            ) from error

    @property
    def bundle_identity(self) -> dict[str, Any]:
        return {
            "schema_version": self.bundle.manifest["schema_version"],
            "bundle_digest": self.bundle.manifest["bundle_digest"],
            "head_sha256": self.bundle.manifest["head"]["sha256"],
            "model_id": self.bundle.identity.weights.model_id,
            "model_revision": self.bundle.identity.weights.model_revision,
        }

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        """Return all 24 normalized candidates in deterministic probability order."""

        started = time.monotonic()
        try:
            transformed = transform_identity_crop(crop_bytes)
        except LocalIdentityContractError as error:
            raise DinoV3InferenceError(str(error)) from error
        try:
            tensor = transformed.to_torch().unsqueeze(0).to(self.device)
            with self._torch.no_grad():
                logits = self._head(_pooler_output(self._encoder(pixel_values=tensor)))
            if getattr(logits, "shape", None) != (1, 24):
                raise DinoV3InferenceError("DINOv3 identity head output must have shape [1, 24]")
            if not bool(self._torch.isfinite(logits).all().item()):
                raise DinoV3InferenceError("DINOv3 inference produced non-finite logits")
            probabilities = self._torch.softmax(logits, dim=1)[0].detach().cpu().tolist()
            if len(probabilities) != 24 or not all(
                isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                for value in probabilities
            ):
                raise DinoV3InferenceError("DINOv3 inference produced invalid probabilities")
            total = sum(float(value) for value in probabilities)
            if not math.isfinite(total) or total <= 0:
                raise DinoV3InferenceError("DINOv3 inference probabilities are not normalizable")
            probabilities = [float(value) / total for value in probabilities]
            ranked = sorted(range(24), key=lambda index: (-probabilities[index], index))
            candidates = tuple(
                {
                    "card": identity_from_target_index(index),
                    "probability": probabilities[index],
                }
                for index in ranked
            )
            from .table_observation import IdentityCandidate

            return CardClassificationResult(
                status="ok",
                candidates=tuple(IdentityCandidate(**candidate) for candidate in candidates),
                latency_ms=_elapsed_ms(started),
                raw_response={
                    "provider": self.name,
                    "version": self.version,
                    "device": self.device,
                    "bundle_identity": self.bundle_identity,
                    "bundle_digest": self.bundle.manifest["bundle_digest"],
                    "input_tensor_digest": transformed.tensor_digest,
                },
            )
        except DinoV3InferenceError as error:
            return CardClassificationResult(
                status="unavailable",
                latency_ms=_elapsed_ms(started),
                error=str(error),
                raw_response={
                    "provider": self.name,
                    "version": self.version,
                    "device": self.device,
                    "bundle_identity": self.bundle_identity,
                },
            )
        except Exception as error:
            return CardClassificationResult(
                status="unavailable",
                latency_ms=_elapsed_ms(started),
                error=f"DINOv3 inference failed: {error}",
                raw_response={
                    "provider": self.name,
                    "version": self.version,
                    "device": self.device,
                    "bundle_identity": self.bundle_identity,
                },
            )


__all__ = [
    "DINOV3_RUNTIME_DEVICES",
    "DINOV3_RUNTIME_VERSION",
    "DinoV3IdentityClassifier",
    "DinoV3InferenceError",
]
