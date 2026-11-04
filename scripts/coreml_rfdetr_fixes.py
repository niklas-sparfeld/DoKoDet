"""Process-local inference and converter fixes for the frozen RF-DETR export."""

import hashlib
import inspect
from contextlib import contextmanager


def digest(function):
    return hashlib.sha256(inspect.getsource(function).encode()).hexdigest()


@contextmanager
def rfdetr_export_fixes():
    from coremltools.converters.mil.frontend.torch import ops
    from rfdetr.models.heads.segmentation import DepthwiseConvBlock

    registry = ops._TORCH_OPS_REGISTRY
    linspace = registry.get_func("linspace")
    depthwise = DepthwiseConvBlock._depthwise_conv
    if (
        digest(linspace)
        != "9d4455a4fab2d4c8cfd768c8a3ea8e6ebb013de37e54fa8685064f21c53f0680"
    ):
        raise RuntimeError("Unexpected Core ML linspace converter")
    if (
        digest(depthwise)
        != "a0c1d77df9461950066484487bbb97e98d88ea73facb64a61796e77d7f8f94a5"
    ):
        raise RuntimeError("Unexpected RF-DETR depthwise implementation")

    def fixed_linspace(context, node):
        inputs = ops._get_inputs(context, node, min_expected=3)
        linspace(context, node)
        value = context[node.name]
        if value.rank > 1 and all(d == 1 for d in value.shape[1:]):
            if not all(
                x.can_be_folded_to_const() and x.val.size == 1 for x in inputs[:3]
            ):
                raise ValueError("Unexpected nonconstant linspace inputs")
            vector = ops.mb.squeeze(
                x=value, axes=list(range(1, value.rank)), name=node.name + "_vector"
            )
            context.add(vector, node.name, override=True)

    def inference_depthwise(self, x):
        return self.dwconv(x)

    registry.set_func_by_name(fixed_linspace, "linspace")
    DepthwiseConvBlock._depthwise_conv = inference_depthwise
    try:
        yield
    finally:
        registry.set_func_by_name(linspace, "linspace")
        DepthwiseConvBlock._depthwise_conv = depthwise
