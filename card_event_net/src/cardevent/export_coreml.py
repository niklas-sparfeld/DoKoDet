from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from torch import nn

from .cache import FULL_FRAME_LETTERBOX_V1
from .infer import InferenceError, load_checkpoint
from .model import CardEventNet

COREML_INPUT_NAME = "clips"
COREML_OUTPUT_NAME = "logit"
COREML_INPUT_SHAPE = (1, 8, 3, 224, 224)
COREML_PREPROCESSING_METADATA_KEY = "com.doko-detector.cardevent.preprocessing"


class CoreMLExportError(RuntimeError):
    """Raised when a PyTorch checkpoint cannot be exported to Core ML."""


class CoreMLExportModel(nn.Module):
    """Fixed-shape model graph without Python input-shape checks."""

    def __init__(self, model: CardEventNet) -> None:
        super().__init__()
        self.model = model

    def forward(self, clips: torch.Tensor) -> torch.Tensor:
        frame_features = self.model.backbone(clips.reshape(8, 3, 224, 224))
        frame_features = self.model.pool(frame_features).flatten(1)
        frame_features = frame_features.reshape(1, 8, self.model._backbone_dim)
        projected = self.model.projection(frame_features)
        temporal = self.model.temporal_head(projected.transpose(1, 2))
        return self.model.classifier(temporal[:, :, -1]).squeeze(-1)


@dataclass(frozen=True, slots=True)
class CoreMLExportResult:
    output_path: Path
    expected_logit: float
    actual_logit: float | None
    max_abs_error: float | None
    parity_verified: bool


def deterministic_sample(*, seed: int = 42) -> torch.Tensor:
    """Create the deterministic normalized input used for export verification."""
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    return torch.randn(COREML_INPUT_SHAPE, generator=generator, dtype=torch.float32)


def verify_coreml_parity(
    coreml_model: Any,
    sample: torch.Tensor,
    expected_output: torch.Tensor,
    *,
    atol: float = 1e-3,
    rtol: float = 1e-3,
) -> float:
    """Compare one Core ML prediction with the matching PyTorch output."""
    if tuple(sample.shape) != COREML_INPUT_SHAPE:
        raise CoreMLExportError(
            f"Parity sample must have shape {COREML_INPUT_SHAPE}, got {tuple(sample.shape)}."
        )
    if atol < 0.0 or rtol < 0.0:
        raise CoreMLExportError("Parity tolerances must not be negative.")

    try:
        prediction = coreml_model.predict({COREML_INPUT_NAME: sample.detach().cpu().numpy()})
    except Exception as exc:
        raise CoreMLExportError(
            "Core ML prediction failed during the parity check. "
            "Use --skip-parity only when the Core ML runtime is not available."
        ) from exc

    if not isinstance(prediction, Mapping) or COREML_OUTPUT_NAME not in prediction:
        raise CoreMLExportError(
            f"Core ML prediction does not contain the '{COREML_OUTPUT_NAME}' output."
        )

    actual = np.asarray(prediction[COREML_OUTPUT_NAME], dtype=np.float64).reshape(-1)
    expected = expected_output.detach().cpu().numpy().astype(np.float64).reshape(-1)
    if actual.shape != expected.shape:
        raise CoreMLExportError(
            f"Core ML output shape {actual.shape} does not match PyTorch shape {expected.shape}."
        )

    max_abs_error = float(np.max(np.abs(actual - expected))) if actual.size else 0.0
    if not np.allclose(actual, expected, atol=atol, rtol=rtol):
        raise CoreMLExportError(
            "Core ML parity check failed: "
            f"maximum absolute error is {max_abs_error:.6g} "
            f"(atol={atol}, rtol={rtol})."
        )
    return max_abs_error


def _load_coremltools() -> Any:
    try:
        import coremltools as ct
    except ModuleNotFoundError as exc:
        raise CoreMLExportError(
            "Core ML export requires the optional dependency. "
            "Run `uv sync --extra coreml` on a supported macOS environment."
        ) from exc
    except Exception as exc:
        raise CoreMLExportError(
            f"Could not import coremltools: {exc}. Use a supported macOS environment."
        ) from exc
    return ct


def export_checkpoint_to_coreml(
    checkpoint_path: str | Path,
    out_path: str | Path,
    *,
    verify_parity: bool = True,
    sample_seed: int = 42,
    parity_atol: float = 1e-3,
    parity_rtol: float = 1e-3,
) -> CoreMLExportResult:
    """Export a checkpoint as an ML Program with a fixed tensor input shape."""
    ct = _load_coremltools()
    try:
        loaded = load_checkpoint(checkpoint_path, device_override="cpu")
    except (InferenceError, RuntimeError, ValueError, OSError) as exc:
        raise CoreMLExportError(f"Could not load checkpoint for Core ML export: {exc}") from exc
    if loaded.config.input.preprocessing != FULL_FRAME_LETTERBOX_V1:
        raise CoreMLExportError(
            "Core ML export requires a full_frame_letterbox_v1 checkpoint. "
            "Retrain with the full-frame preprocessing contract first."
        )

    sample = deterministic_sample(seed=sample_seed)
    loaded.model.eval()
    export_model = CoreMLExportModel(loaded.model).eval()
    with torch.inference_mode():
        expected_output = loaded.model(sample).detach().cpu().reshape(-1)
        export_output = export_model(sample).detach().cpu().reshape(-1)
    if not torch.equal(expected_output, export_output):
        raise CoreMLExportError("The fixed-shape export model does not match the checkpoint model.")

    try:
        traced_model = torch.jit.trace(export_model, sample, strict=False)
        traced_model.eval()
        converted_model = ct.convert(
            traced_model,
            convert_to="mlprogram",
            inputs=[ct.TensorType(name=COREML_INPUT_NAME, shape=list(COREML_INPUT_SHAPE))],
            outputs=[ct.TensorType(name=COREML_OUTPUT_NAME)],
            compute_precision=ct.precision.FLOAT32,
            minimum_deployment_target=ct.target.iOS15,
        )
    except Exception as exc:
        raise CoreMLExportError(f"Could not convert checkpoint to Core ML: {exc}") from exc
    converted_model.user_defined_metadata[COREML_PREPROCESSING_METADATA_KEY] = (
        loaded.config.input.preprocessing
    )

    actual_logit: float | None = None
    max_abs_error: float | None = None
    if verify_parity:
        max_abs_error = verify_coreml_parity(converted_model, sample, expected_output)
        prediction = converted_model.predict({COREML_INPUT_NAME: sample.numpy()})
        actual_logit = float(np.asarray(prediction[COREML_OUTPUT_NAME]).reshape(-1)[0])

    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        converted_model.save(str(destination))
    except Exception as exc:
        raise CoreMLExportError(f"Could not save Core ML model to {destination}: {exc}") from exc

    expected_logit = float(expected_output[0])
    return CoreMLExportResult(
        output_path=destination,
        expected_logit=expected_logit,
        actual_logit=actual_logit,
        max_abs_error=max_abs_error,
        parity_verified=verify_parity,
    )
