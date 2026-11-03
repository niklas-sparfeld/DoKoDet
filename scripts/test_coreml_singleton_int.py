"""Focused behavior checks for the bounded converter fix."""

from types import SimpleNamespace

import numpy as np
import pytest
from coreml_singleton_int import singleton_int_fix
from coremltools.converters.mil import Builder as mb
from coremltools.converters.mil.frontend.torch import ops
from coremltools.converters.mil.mil import types


class Context(dict):
    def add(self, value, name):
        self[name] = value


def convert(value):
    context = Context(value=value)
    node = SimpleNamespace(inputs=["value"], name="result", kind="int")
    ops._cast(context, node, int, "int32")
    return context["result"]


def test_constants_and_invalid_shape():
    original = ops._cast
    with singleton_int_fix():

        @mb.program(input_specs=[])
        def program():
            scalar = convert(mb.const(val=np.array(-3, dtype=np.int32)))
            singleton = convert(mb.const(val=np.array([[7]], dtype=np.int32)))
            assert scalar.shape == () and scalar.val == -3
            assert singleton.shape == () and singleton.val == 7
            with pytest.raises(ValueError, match="scalar or a length 1 tensor"):
                convert(mb.const(val=np.array([1, 2], dtype=np.int32)))
            return singleton

    assert ops._cast is original


def test_dynamic_singleton():
    with singleton_int_fix():

        @mb.program(input_specs=[mb.TensorSpec(shape=(1,), dtype=types.fp32)])
        def program(value):
            result = convert(value)
            assert result.shape == () and result.dtype == types.int32
            return result
