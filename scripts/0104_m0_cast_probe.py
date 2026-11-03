"""Reproduce the Core ML singleton-constant integer conversion failure."""

from types import SimpleNamespace

import numpy as np
from coremltools.converters.mil import Builder as mb
from coremltools.converters.mil.frontend.torch import ops


class Context(dict):
    def add(self, value, name):
        self[name] = value


@mb.program(input_specs=[])
def probe():
    value = mb.const(val=np.array([7], dtype=np.int32))
    context = Context(value=value)
    node = SimpleNamespace(inputs=["value"], name="result", kind="int")
    try:
        ops._cast(context, node, int, "int32")
    except TypeError as error:
        assert "only 0-dimensional arrays" in str(error)
        print(f"Original converter: {type(error).__name__}: {error}")
    else:
        raise AssertionError("Expected the pinned converter failure")
    result = mb.const(val=int(np.asarray(value.val).item()), name="scalar")
    assert result.shape == () and result.val == 7
    print(f"Extracted singleton: shape={result.shape}, value={result.val}")
    return result
