"""Check the inference rewrite and converter output against PyTorch."""

from types import SimpleNamespace

import numpy as np
import torch
from coreml_rfdetr_fixes import rfdetr_export_fixes
from coremltools.converters.mil import Builder as mb
from coremltools.converters.mil.frontend.torch import ops
from rfdetr.models.heads.segmentation import DepthwiseConvBlock


class Context(dict):
    def add(self, value, torch_name=None, override=False):
        self[torch_name or value.name] = value


def test_linspace_singleton_endpoints():
    with rfdetr_export_fixes():

        @mb.program(input_specs=[])
        def program():
            context = Context(
                start=mb.const(val=np.array([0], dtype=np.int32)),
                end=mb.const(val=np.array([35], dtype=np.int32)),
                steps=mb.const(val=36),
            )
            node = SimpleNamespace(
                inputs=["start", "end", "steps"], name="range", kind="linspace"
            )
            ops._TORCH_OPS_REGISTRY.get_func("linspace")(context, node)
            value = context["range"]
            assert value.shape == (36,)
            np.testing.assert_allclose(
                value.val, torch.linspace(0, 35, 36).numpy(), atol=1e-6
            )
            return value


def test_depthwise_matches_original_and_restores():
    torch.manual_seed(7)
    block = DepthwiseConvBlock(4).eval()
    x = torch.randn(1, 4, 8, 8)
    original = DepthwiseConvBlock._depthwise_conv
    with torch.inference_mode():
        expected = block(x)
        with rfdetr_export_fixes():
            actual = block(x)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    assert DepthwiseConvBlock._depthwise_conv is original
