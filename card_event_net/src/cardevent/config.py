from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isclose
from pathlib import Path
from typing import Any, Mapping

from .cache import FULL_FRAME_LETTERBOX_V1, LEGACY_ROI_LETTERBOX_V1


class ConfigError(ValueError):
    pass


def _require_mapping(data: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ConfigError(f"{context} must be a mapping.")
    return data


def _require_section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    try:
        value = data[key]
    except KeyError as exc:
        raise ConfigError(f"Missing required config section: {key}") from exc
    return _require_mapping(value, key)


def _require_int(data: Mapping[str, Any], key: str, *, min_value: int | None = None) -> int:
    try:
        value = data[key]
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {key}") from exc
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer.")
    if min_value is not None and value < min_value:
        raise ConfigError(f"{key} must be >= {min_value}.")
    return value


def _optional_int(
    data: Mapping[str, Any],
    key: str,
    *,
    default: int,
    min_value: int | None = None,
) -> int:
    if key not in data:
        return default
    return _require_int(data, key, min_value=min_value)


def _require_float(data: Mapping[str, Any], key: str, *, min_value: float | None = None) -> float:
    try:
        value = data[key]
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {key}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number.")
    result = float(value)
    if min_value is not None and result < min_value:
        raise ConfigError(f"{key} must be >= {min_value}.")
    return result


def _optional_float(
    data: Mapping[str, Any],
    key: str,
    *,
    default: float,
    min_value: float | None = None,
) -> float:
    if key not in data:
        return default
    return _require_float(data, key, min_value=min_value)


def _require_bool(data: Mapping[str, Any], key: str) -> bool:
    try:
        value = data[key]
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {key}") from exc
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean.")
    return value


def _require_string(data: Mapping[str, Any], key: str) -> str:
    try:
        value = data[key]
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {key}") from exc
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string.")
    return value


def _require_float_sequence(
    data: Mapping[str, Any], key: str, *, expected_len: int | None = None
) -> tuple[float, ...]:
    try:
        value = data[key]
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {key}") from exc
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"{key} must be a list of numbers.")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ConfigError(f"{key} must contain only numbers.")
    result = tuple(float(item) for item in value)
    if expected_len is not None and len(result) != expected_len:
        raise ConfigError(f"{key} must contain exactly {expected_len} values.")
    return result


@dataclass(frozen=True, slots=True)
class InputConfig:
    size: int
    cache_fps: float
    clip_offsets_s: tuple[float, ...]
    inference_stride_s: float
    preprocessing: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "InputConfig":
        mapping = _require_section(data, "input")
        size = _require_int(mapping, "size", min_value=1)
        if size != 224:
            raise ConfigError("input.size must be 224 for the fixed v1 model.")
        cache_fps = _require_float(mapping, "cache_fps", min_value=0.0)
        clip_offsets_s = _require_float_sequence(mapping, "clip_offsets_s", expected_len=8)
        inference_stride_s = _require_float(mapping, "inference_stride_s", min_value=0.0)
        preprocessing = mapping.get("preprocessing", LEGACY_ROI_LETTERBOX_V1)
        if not isinstance(preprocessing, str) or preprocessing not in {
            FULL_FRAME_LETTERBOX_V1,
            LEGACY_ROI_LETTERBOX_V1,
        }:
            raise ConfigError(
                "input.preprocessing must be full_frame_letterbox_v1 or roi_letterbox_v1."
            )
        if any(b < a for a, b in zip(clip_offsets_s, clip_offsets_s[1:], strict=False)):
            raise ConfigError("clip_offsets_s must be sorted from low to high.")
        if any(offset > 0.0 for offset in clip_offsets_s):
            raise ConfigError("clip_offsets_s must not include future frames.")
        if not isclose(clip_offsets_s[-1], 0.0, abs_tol=1e-9):
            raise ConfigError("clip_offsets_s must end at 0.0.")
        return cls(
            size=size,
            cache_fps=cache_fps,
            clip_offsets_s=clip_offsets_s,
            inference_stride_s=inference_stride_s,
            preprocessing=preprocessing,
        )


@dataclass(frozen=True, slots=True)
class LabelConfig:
    positive_window_s: float
    negative_past_exclusion_s: float
    negative_future_exclusion_s: float
    negative_to_positive_ratio: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LabelConfig":
        mapping = _require_section(data, "labels")
        positive_window_s = _require_float(mapping, "positive_window_s", min_value=0.0)
        negative_past_exclusion_s = _require_float(
            mapping, "negative_past_exclusion_s", min_value=0.0
        )
        if positive_window_s > negative_past_exclusion_s:
            raise ConfigError(
                "labels.positive_window_s must not exceed labels.negative_past_exclusion_s."
            )
        return cls(
            positive_window_s=positive_window_s,
            negative_past_exclusion_s=negative_past_exclusion_s,
            negative_future_exclusion_s=_require_float(
                mapping, "negative_future_exclusion_s", min_value=0.0
            ),
            negative_to_positive_ratio=_require_int(
                mapping, "negative_to_positive_ratio", min_value=1
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelConfig:
    backbone: str
    pretrained: bool
    feature_dim: int
    temporal_hidden_1: int
    temporal_hidden_2: int
    dropout: float
    temporal_head: str = "padded_tail_v1"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ModelConfig":
        mapping = _require_section(data, "model")
        dropout = _require_float(mapping, "dropout", min_value=0.0)
        if not 0.0 <= dropout <= 1.0:
            raise ConfigError("dropout must be between 0 and 1.")
        backbone = _require_string(mapping, "backbone")
        if backbone != "mobilenet_v3_small":
            raise ConfigError("model.backbone must be mobilenet_v3_small in v1.")
        temporal_head = mapping.get("temporal_head", "padded_tail_v1")
        if temporal_head not in ("padded_tail_v1", "full_clip_v2"):
            raise ConfigError("model.temporal_head must be padded_tail_v1 or full_clip_v2.")
        return cls(
            backbone=backbone,
            pretrained=_require_bool(mapping, "pretrained"),
            feature_dim=_require_int(mapping, "feature_dim", min_value=1),
            temporal_hidden_1=_require_int(mapping, "temporal_hidden_1", min_value=1),
            temporal_hidden_2=_require_int(mapping, "temporal_hidden_2", min_value=1),
            dropout=dropout,
            temporal_head=temporal_head,
        )


@dataclass(frozen=True, slots=True)
class EarlyStoppingConfig:
    metric: str = "validation_event_f1"
    patience: int = 3
    min_delta: float = 0.005

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EarlyStoppingConfig":
        if not data:
            return cls()
        metric = _require_string(data, "metric")
        if metric not in {"validation_event_f1", "validation_event_recall"}:
            raise ConfigError("training.early_stopping.metric is not supported.")
        return cls(
            metric=metric,
            patience=_require_int(data, "patience", min_value=1),
            min_delta=_require_float(data, "min_delta", min_value=0.0),
        )


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    batch_size: int
    warmup_epochs: int
    finetune_epochs: int
    warmup_lr: float
    finetune_lr: float
    weight_decay: float
    hard_negative_repeat: int
    device: str
    early_stopping: EarlyStoppingConfig

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TrainingConfig":
        mapping = _require_section(data, "training")
        device = _require_string(mapping, "device").lower()
        if device not in {"auto", "cpu", "cuda", "mps"}:
            raise ConfigError("training.device must be one of: auto, cpu, cuda, mps")
        return cls(
            batch_size=_require_int(mapping, "batch_size", min_value=1),
            warmup_epochs=_require_int(mapping, "warmup_epochs", min_value=1),
            finetune_epochs=_require_int(mapping, "finetune_epochs", min_value=1),
            warmup_lr=_require_float(mapping, "warmup_lr", min_value=0.0),
            finetune_lr=_require_float(mapping, "finetune_lr", min_value=0.0),
            weight_decay=_require_float(mapping, "weight_decay", min_value=0.0),
            # Keep old Phase 4/5 checkpoints loadable.
            hard_negative_repeat=_optional_int(
                mapping, "hard_negative_repeat", default=3, min_value=2
            ),
            device=device,
            early_stopping=EarlyStoppingConfig.from_mapping(
                _require_mapping(mapping["early_stopping"], "training.early_stopping")
                if "early_stopping" in mapping
                else {}
            ),
        )


@dataclass(frozen=True, slots=True)
class InferenceConfig:
    peak_confirmation_s: float
    min_event_gap_s: float

    @property
    def merge_window_s(self) -> float:
        """Compatibility name for checkpoints created before peak decoding."""
        return self.min_event_gap_s

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "InferenceConfig":
        mapping = _require_section(data, "inference")
        has_new_keys = "peak_confirmation_s" in mapping or "min_event_gap_s" in mapping
        if has_new_keys:
            return cls(
                peak_confirmation_s=_optional_float(
                    mapping, "peak_confirmation_s", default=0.125, min_value=0.0
                ),
                min_event_gap_s=_require_float(mapping, "min_event_gap_s", min_value=0.0),
            )
        # Old checkpoints only store the connected-component merge window.
        return cls(
            peak_confirmation_s=0.125,
            min_event_gap_s=_require_float(mapping, "merge_window_s", min_value=0.0),
        )


@dataclass(frozen=True, slots=True)
class MetricsConfig:
    event_match_tolerance_s: float
    target_recall: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MetricsConfig":
        mapping = _require_section(data, "metrics")
        target_recall = _require_float(mapping, "target_recall", min_value=0.0)
        if not 0.0 <= target_recall <= 1.0:
            raise ConfigError("target_recall must be between 0 and 1.")
        return cls(
            event_match_tolerance_s=_require_float(
                mapping, "event_match_tolerance_s", min_value=0.0
            ),
            target_recall=target_recall,
        )


@dataclass(frozen=True, slots=True)
class Config:
    seed: int
    input: InputConfig
    labels: LabelConfig
    model: ModelConfig
    training: TrainingConfig
    inference: InferenceConfig
    metrics: MetricsConfig

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Config":
        mapping = _require_mapping(data, "config")
        return cls(
            seed=_require_int(mapping, "seed", min_value=0),
            input=InputConfig.from_mapping(mapping),
            labels=LabelConfig.from_mapping(mapping),
            model=ModelConfig.from_mapping(mapping),
            training=TrainingConfig.from_mapping(mapping),
            inference=InferenceConfig.from_mapping(mapping),
            metrics=MetricsConfig.from_mapping(mapping),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["input"]["clip_offsets_s"] = list(self.input.clip_offsets_s)
        return data


def _load_yaml_text(text: str) -> Mapping[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is not available. Run `uv sync` to install the project dependencies."
        ) from exc

    data = yaml.safe_load(text)
    return _require_mapping(data, "config")


def load_config(path: str | Path) -> Config:
    config_path = Path(path)
    data = _load_yaml_text(config_path.read_text(encoding="utf-8"))
    return Config.from_mapping(data)


def save_config(config: Config, path: str | Path) -> None:
    config_path = Path(path)
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is not available. Run `uv sync` to install the project dependencies."
        ) from exc

    config_path.write_text(yaml.safe_dump(config.to_dict(), sort_keys=False), encoding="utf-8")
