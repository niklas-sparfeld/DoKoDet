from __future__ import annotations

import importlib
import importlib.util

import pytest

from table_evidence_analyzer.rfdetr_import import block_pyav_import


def test_block_pyav_import_restores_import_state() -> None:
    if importlib.util.find_spec("av") is None:
        pytest.skip("PyAV is not installed")

    with block_pyav_import(), pytest.raises(ModuleNotFoundError, match="blocked during its import"):
        importlib.import_module("av")

    assert importlib.util.find_spec("av") is not None
