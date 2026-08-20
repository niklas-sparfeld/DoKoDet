from __future__ import annotations

import sys
import types

import pytest

from cardevent.device import resolve_device


def make_fake_torch(
    *, cuda_available: bool = False, mps_available: bool = False
) -> types.SimpleNamespace:
    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return cuda_available

    class FakeMps:
        @staticmethod
        def is_available() -> bool:
            return mps_available

    return types.SimpleNamespace(
        cuda=FakeCuda(),
        backends=types.SimpleNamespace(mps=FakeMps()),
        device=lambda name: name,
    )


def test_auto_prefers_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", make_fake_torch(cuda_available=True))

    assert resolve_device("auto") == "cuda"


def test_auto_falls_back_to_mps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", make_fake_torch(mps_available=True))

    assert resolve_device("auto") == "mps"


def test_auto_falls_back_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", make_fake_torch())

    assert resolve_device("auto") == "cpu"


def test_invalid_device_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", make_fake_torch())

    with pytest.raises(ValueError, match="auto, cuda, mps, cpu"):
        resolve_device("invalid")
