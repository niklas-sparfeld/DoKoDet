from __future__ import annotations

from typing import Any

try:
    import torch
    from torch import nn
except ModuleNotFoundError:  # pragma: no cover - the package dependency is required at runtime.
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]


class ModelError(RuntimeError):
    """Raised when the CardEventNet model cannot be built or used."""


def _build_backbone(*, pretrained: bool) -> Any:
    try:
        from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
    except ModuleNotFoundError as exc:
        raise ModelError(
            "torchvision is not available. Run `uv sync` to install the project dependencies."
        ) from exc

    weights = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    try:
        return mobilenet_v3_small(weights=weights)
    except Exception as exc:
        if pretrained:
            raise ModelError(
                "Could not load the ImageNet MobileNetV3-Small weights. "
                "Check network access or set model.pretrained to false for a local smoke test."
            ) from exc
        raise ModelError(f"Could not build the MobileNetV3-Small backbone: {exc}") from exc


class CardEventNet(nn.Module if nn is not None else object):  # type: ignore[misc,valid-type]
    """MobileNetV3-Small plus a causal temporal convolution head."""

    def __init__(
        self,
        *,
        backbone: str = "mobilenet_v3_small",
        pretrained: bool = True,
        feature_dim: int = 128,
        temporal_hidden_1: int = 64,
        temporal_hidden_2: int = 32,
        dropout: float = 0.1,
        temporal_head: str = "padded_tail_v1",
    ) -> None:
        if torch is None or nn is None:
            raise ModelError(
                "PyTorch is not available. Run `uv sync` to install the project dependencies."
            )
        if backbone != "mobilenet_v3_small":
            raise ModelError("Only the mobilenet_v3_small backbone is supported in v1.")
        if feature_dim <= 0 or temporal_hidden_1 <= 0 or temporal_hidden_2 <= 0:
            raise ModelError("Model dimensions must be positive.")
        if not 0.0 <= dropout <= 1.0:
            raise ModelError("dropout must be between 0 and 1.")
        if temporal_head not in {"padded_tail_v1", "full_clip_v2"}:
            raise ModelError("temporal_head must be padded_tail_v1 or full_clip_v2.")

        backbone_model = _build_backbone(pretrained=pretrained)
        backbone_dim = int(backbone_model.classifier[0].in_features)
        super().__init__()
        self.backbone = backbone_model.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.projection = nn.Sequential(
            nn.Linear(backbone_dim, feature_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        if temporal_head == "padded_tail_v1":
            # Preserve the original module names and parameter shapes so old
            # checkpoints continue to reconstruct exactly.
            self.temporal_head = nn.Sequential(
                nn.Conv1d(feature_dim, temporal_hidden_1, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Conv1d(temporal_hidden_1, temporal_hidden_2, kernel_size=3, padding=1),
                nn.ReLU(),
            )
        else:
            self.temporal_head = nn.Sequential(
                nn.Conv1d(feature_dim, temporal_hidden_1, kernel_size=5),
                nn.ReLU(),
                nn.Conv1d(temporal_hidden_1, temporal_hidden_2, kernel_size=4),
                nn.ReLU(),
            )
        self.classifier = nn.Linear(temporal_hidden_2, 1)
        self._backbone_dim = backbone_dim
        self.temporal_head_name = temporal_head

    def classify_projected_features(self, projected: Any) -> Any:
        """Classify one batch of eight projected causal frame features."""
        if not torch.jit.is_tracing() and (projected.ndim != 3 or projected.shape[1] != 8):
            raise ModelError("Projected features must have shape [B, 8, feature_dim].")
        temporal = self.temporal_head(projected.transpose(1, 2))
        if self.temporal_head_name == "full_clip_v2":
            if not torch.jit.is_tracing() and temporal.shape[-1] != 1:
                raise ModelError("full_clip_v2 must reduce the eight-frame clip to one position.")
            temporal_output = temporal[:, :, 0]
        else:
            temporal_output = temporal[:, :, -1]
        return self.classifier(temporal_output).squeeze(-1)

    def forward(self, clips: Any) -> Any:
        if clips.ndim != 5:
            raise ModelError("CardEventNet expects input shape [B, 8, 3, 224, 224].")
        if tuple(clips.shape[1:]) != (8, 3, 224, 224):
            raise ModelError(
                f"CardEventNet expects input shape [B, 8, 3, 224, 224], got {tuple(clips.shape)}."
            )

        batch_size, frame_count, channels, height, width = clips.shape
        frame_features = self.backbone(
            clips.reshape(batch_size * frame_count, channels, height, width)
        )
        frame_features = self.pool(frame_features).flatten(1)
        frame_features = frame_features.reshape(batch_size, frame_count, self._backbone_dim)
        projected = self.projection(frame_features)
        return self.classify_projected_features(projected)


def build_model(model_config: Any) -> Any:
    return CardEventNet(
        backbone=model_config.backbone,
        pretrained=model_config.pretrained,
        feature_dim=model_config.feature_dim,
        temporal_hidden_1=model_config.temporal_hidden_1,
        temporal_hidden_2=model_config.temporal_hidden_2,
        dropout=model_config.dropout,
        temporal_head=model_config.temporal_head,
    )


def freeze_backbone(model: Any) -> None:
    """Freeze the spatial backbone for temporal-head warmup."""
    for parameter in model.backbone.parameters():
        parameter.requires_grad = False


def unfreeze_backbone(model: Any) -> None:
    """Allow the spatial backbone to be fine-tuned."""
    for parameter in model.backbone.parameters():
        parameter.requires_grad = True


def backbone_is_frozen(model: Any) -> bool:
    return all(not parameter.requires_grad for parameter in model.backbone.parameters())
