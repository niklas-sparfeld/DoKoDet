from __future__ import annotations

from importlib import metadata

from .config import Config, load_config, save_config
from .device import resolve_device


def _resolve_version() -> str:
    try:
        return metadata.version("cardevent")
    except metadata.PackageNotFoundError:
        return "0.1.0"


__version__ = _resolve_version()

__all__ = [
    "Config",
    "load_config",
    "resolve_device",
    "save_config",
    "__version__",
]

