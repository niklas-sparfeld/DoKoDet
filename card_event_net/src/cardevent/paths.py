"""Default paths for disposable CardEventNet workspaces."""

from pathlib import Path

DEFAULT_RUNTIME_ROOT = Path(".runtime/cardevent")
DEFAULT_ANNOTATIONS_DIR = DEFAULT_RUNTIME_ROOT / "annotations"
DEFAULT_CACHE_DIR = DEFAULT_RUNTIME_ROOT / "cache"
DEFAULT_OUTPUT_DIR = DEFAULT_RUNTIME_ROOT / "outputs"
DEFAULT_SPLIT_DIR = DEFAULT_RUNTIME_ROOT / "splits"

__all__ = [
    "DEFAULT_ANNOTATIONS_DIR",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_RUNTIME_ROOT",
    "DEFAULT_SPLIT_DIR",
]
