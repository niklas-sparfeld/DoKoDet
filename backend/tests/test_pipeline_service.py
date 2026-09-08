from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dokodetector_backend.event_pipeline_service import CardEventFileProvider


def test_card_event_file_provider_uses_installed_cardevent_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import cardevent

    calls: dict[str, object] = {}

    def fake_infer_from_files(checkpoint_path, video_path, **kwargs):
        calls.update(checkpoint_path=checkpoint_path, video_path=video_path, kwargs=kwargs)
        return {"events": []}

    monkeypatch.setattr(cardevent, "infer_from_files", fake_infer_from_files)
    provider = CardEventFileProvider(tmp_path)
    request = SimpleNamespace(
        configuration={
            "checkpoint": "checkpoints/best.pt",
            "cache_dir": "cache",
            "batch_size": 4,
            "threshold": 0.5,
            "merge_window_s": 1.25,
        }
    )
    video_path = tmp_path / "recording.mov"

    result = provider.infer(video_path, request=request)

    assert result == {"events": []}
    assert calls["checkpoint_path"] == tmp_path / "checkpoints" / "best.pt"
    assert calls["video_path"] == video_path
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    assert Path(kwargs["out_path"]).suffix == ".json"
    assert kwargs["cache_dir"] == tmp_path / "cache"
    assert kwargs["batch_size"] == 4
    assert kwargs["threshold"] == 0.5
    assert kwargs["merge_window_s"] == 1.25


def test_card_event_file_provider_uses_explicit_checkpoint_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import cardevent

    calls: dict[str, object] = {}

    def fake_infer_from_files(checkpoint_path, video_path, **kwargs):
        calls.update(checkpoint_path=checkpoint_path, video_path=video_path, kwargs=kwargs)
        return {"events": []}

    monkeypatch.setattr(cardevent, "infer_from_files", fake_infer_from_files)
    provider = CardEventFileProvider(tmp_path)

    provider.infer(
        tmp_path / "recording.mov",
        request=SimpleNamespace(configuration={"checkpoint_path": "checkpoints/best.pt"}),
    )

    assert calls["checkpoint_path"] == tmp_path / "checkpoints" / "best.pt"
