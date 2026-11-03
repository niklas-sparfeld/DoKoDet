"""Guarded, process-local Core ML Torch integer constant conversion fix."""

import hashlib
import inspect
from contextlib import contextmanager

EXPECTED_CAST_SHA256 = (
    "f946f34f789baea09f9698c0c1ca4d6d55a75c65c9ffd33914053b2653306fb0"
)


@contextmanager
def singleton_int_fix():
    import numpy as np
    from coremltools.converters.mil.frontend.torch import ops

    original = ops._cast
    digest = hashlib.sha256(inspect.getsource(original).encode()).hexdigest()
    if digest != EXPECTED_CAST_SHA256:
        raise RuntimeError(f"Unexpected coremltools _cast implementation: {digest}")

    def cast(context, node, dtype, dtype_name):
        if dtype is int and dtype_name == "int32":
            x = ops._get_inputs(context, node, expected=1)[0]
            if (
                x.can_be_folded_to_const()
                and all(d == 1 for d in x.shape)
                and len(x.shape) > 0
            ):
                result = ops.mb.const(val=int(np.asarray(x.val).item()), name=node.name)
                context.add(result, node.name)
                return
        return original(context, node, dtype, dtype_name)

    ops._cast = cast
    try:
        yield
    finally:
        ops._cast = original
