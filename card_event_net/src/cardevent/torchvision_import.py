"""Load torchvision without importing its optional PyAV video backend."""

from __future__ import annotations

import importlib.abc
import sys
from collections.abc import Iterator
from contextlib import contextmanager


class _BlockPyAV(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object | None = None, target: object = None) -> None:
        if fullname == "av" or fullname.startswith("av."):
            raise ModuleNotFoundError(
                "PyAV is not needed by CardEventNet and is blocked during its import."
            )
        return None


@contextmanager
def block_pyav_import() -> Iterator[None]:
    """Prevent optional PyAV from loading while CardEventNet imports torchvision."""

    if "av" in sys.modules or any(name.startswith("av.") for name in sys.modules):
        yield
        return
    finder = _BlockPyAV()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)


__all__ = ["block_pyav_import"]
