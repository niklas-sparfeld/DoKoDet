from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch


def _import_torch() -> Any:
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyTorch is not available. Run `uv sync` to install the project dependencies."
        ) from exc
    return torch


def _is_cuda_available(torch_module: Any) -> bool:
    cuda = getattr(torch_module, "cuda", None)
    is_available = getattr(cuda, "is_available", None)
    return bool(is_available()) if callable(is_available) else False


def _is_mps_available(torch_module: Any) -> bool:
    backends = getattr(torch_module, "backends", None)
    mps = getattr(backends, "mps", None)
    is_available = getattr(mps, "is_available", None)
    return bool(is_available()) if callable(is_available) else False


def resolve_device(requested: str = "auto") -> "torch.device":
    torch_module = _import_torch()
    normalized = requested.strip().lower()

    if normalized == "auto":
        if _is_cuda_available(torch_module):
            return torch_module.device("cuda")
        if _is_mps_available(torch_module):
            return torch_module.device("mps")
        return torch_module.device("cpu")

    if normalized == "cuda":
        if not _is_cuda_available(torch_module):
            raise RuntimeError("CUDA was requested, but it is not available.")
        return torch_module.device("cuda")

    if normalized == "mps":
        if not _is_mps_available(torch_module):
            raise RuntimeError("MPS was requested, but it is not available.")
        return torch_module.device("mps")

    if normalized == "cpu":
        return torch_module.device("cpu")

    raise ValueError("requested must be one of: auto, cuda, mps, cpu")

