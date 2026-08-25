from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from torch import nn

from cardevent import export_coreml
from cardevent.export_coreml import (
    COREML_INPUT_NAME,
    COREML_INPUT_SHAPE,
    COREML_OUTPUT_NAME,
    COREML_PREPROCESSING_METADATA_KEY,
    CoreMLExportError,
    CoreMLExportModel,
    deterministic_sample,
    verify_coreml_parity,
)
from cardevent.model import CardEventNet


def test_deterministic_sample_has_the_fixed_export_shape() -> None:
    first = deterministic_sample(seed=7)
    second = deterministic_sample(seed=7)

    assert tuple(first.shape) == COREML_INPUT_SHAPE
    assert first.dtype == torch.float32
    assert torch.equal(first, second)


def test_coreml_export_model_uses_only_fixed_reshape_dimensions() -> None:
    model = CardEventNet(pretrained=False).eval()
    export_model = CoreMLExportModel(model).eval()
    sample = deterministic_sample(seed=11)

    traced = torch.jit.trace(export_model, sample)

    with torch.inference_mode():
        assert torch.allclose(export_model(sample), model(sample))
    assert "aten::Int" not in str(traced.inlined_graph)


def test_coreml_export_model_matches_full_clip_v2() -> None:
    model = CardEventNet(pretrained=False, temporal_head="full_clip_v2").eval()
    export_model = CoreMLExportModel(model).eval()
    sample = deterministic_sample(seed=12)

    traced = torch.jit.trace(export_model, sample)

    with torch.inference_mode():
        assert torch.allclose(export_model(sample), model(sample))
    assert "aten::Int" not in str(traced.inlined_graph)


class _FakeCoreMLModel:
    def __init__(self, output: float) -> None:
        self.output = output
        self.inputs: list[np.ndarray] = []

    def predict(self, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        self.inputs.append(inputs[COREML_INPUT_NAME])
        return {COREML_OUTPUT_NAME: np.asarray([self.output], dtype=np.float32)}


def test_verify_coreml_parity_accepts_close_logit() -> None:
    sample = deterministic_sample(seed=3)
    expected = torch.tensor([0.25])
    coreml_model = _FakeCoreMLModel(output=0.25001)

    max_error = verify_coreml_parity(coreml_model, sample, expected)

    assert max_error == pytest.approx(0.00001, abs=1e-6)
    assert tuple(coreml_model.inputs[0].shape) == COREML_INPUT_SHAPE


def test_verify_coreml_parity_rejects_wrong_output() -> None:
    sample = deterministic_sample(seed=3)
    coreml_model = _FakeCoreMLModel(output=0.5)

    with pytest.raises(CoreMLExportError, match="parity check failed"):
        verify_coreml_parity(coreml_model, sample, torch.tensor([0.25]))


class _TinyModel(nn.Module):
    def forward(self, clips: torch.Tensor) -> torch.Tensor:
        return clips.mean(dim=(1, 2, 3, 4))


class _FakeTensorType:
    def __init__(self, *, name: str, shape: list[int] | None = None) -> None:
        self.name = name
        self.shape = shape


class _FakeConvertedModel:
    def __init__(self, traced_model: torch.jit.ScriptModule) -> None:
        self.traced_model = traced_model
        self.saved_path: str | None = None
        self.user_defined_metadata: dict[str, str] = {}

    def save(self, path: str) -> None:
        self.saved_path = path

    def predict(self, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        tensor = torch.from_numpy(inputs[COREML_INPUT_NAME])
        with torch.inference_mode():
            output = self.traced_model(tensor).numpy()
        return {COREML_OUTPUT_NAME: output}


class _FakeCoreMLTools:
    class target:
        iOS15 = object()

    class precision:
        FLOAT32 = object()

    TensorType = _FakeTensorType

    def __init__(self) -> None:
        self.converted: _FakeConvertedModel | None = None
        self.input_shape: list[int] | None = None
        self.compute_precision: object | None = None

    def convert(
        self, traced_model: torch.jit.ScriptModule, **kwargs: object
    ) -> _FakeConvertedModel:
        input_type = kwargs["inputs"][0]  # type: ignore[index]
        self.input_shape = input_type.shape
        self.compute_precision = kwargs["compute_precision"]
        self.converted = _FakeConvertedModel(traced_model)
        return self.converted


def test_export_checkpoint_uses_fixed_shape_and_checks_parity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_coremltools = _FakeCoreMLTools()
    loaded = type(
        "Loaded",
        (),
        {
            "model": _TinyModel(),
            "config": SimpleNamespace(
                input=SimpleNamespace(preprocessing="full_frame_letterbox_v1")
            ),
        },
    )()
    monkeypatch.setattr(export_coreml, "_load_coremltools", lambda: fake_coremltools)
    monkeypatch.setattr(export_coreml, "load_checkpoint", lambda *_args, **_kwargs: loaded)
    monkeypatch.setattr(export_coreml, "CoreMLExportModel", lambda model: model)

    destination = tmp_path / "CardEventNet.mlpackage"
    result = export_coreml.export_checkpoint_to_coreml("checkpoint.pt", destination)

    assert result.parity_verified is True
    assert result.max_abs_error == pytest.approx(0.0)
    assert fake_coremltools.input_shape == list(COREML_INPUT_SHAPE)
    assert fake_coremltools.compute_precision is fake_coremltools.precision.FLOAT32
    assert fake_coremltools.converted is not None
    assert fake_coremltools.converted.saved_path == str(destination)
    assert fake_coremltools.converted.user_defined_metadata == {
        COREML_PREPROCESSING_METADATA_KEY: "full_frame_letterbox_v1"
    }


def test_export_rejects_legacy_roi_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = type(
        "Loaded",
        (),
        {
            "model": _TinyModel(),
            "config": SimpleNamespace(input=SimpleNamespace(preprocessing="roi_letterbox_v1")),
        },
    )()
    monkeypatch.setattr(export_coreml, "_load_coremltools", _FakeCoreMLTools)
    monkeypatch.setattr(export_coreml, "load_checkpoint", lambda *_args, **_kwargs: loaded)

    with pytest.raises(CoreMLExportError, match="full_frame_letterbox_v1"):
        export_coreml.export_checkpoint_to_coreml("checkpoint.pt", "CardEventNet.mlpackage")
