from uuid import UUID

import pytest

from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage

ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000032")


def test_round_analysis_artifacts_are_published_as_one_directory(tmp_path) -> None:
    storage = RoundAnalysisArtifactStorage(tmp_path)
    input_bytes = b'{"input":true}\n'
    result_bytes = b'{"result":true}\n'

    stored = storage.publish(ANALYSIS_ID, input_bytes, result_bytes)

    assert stored.input.relative_path == f"round-analyses/{ANALYSIS_ID}/input.json"
    assert stored.result.relative_path == f"round-analyses/{ANALYSIS_ID}/result.json"
    assert stored.input.sha256 != stored.result.sha256
    assert (storage.analysis_path(ANALYSIS_ID) / "input.json").read_bytes() == input_bytes
    assert (storage.analysis_path(ANALYSIS_ID) / "result.json").read_bytes() == result_bytes
    assert list(storage.root.glob(f".{ANALYSIS_ID}-*")) == []


def test_round_analysis_artifacts_reject_replay_and_clean_failed_publish(
    tmp_path, monkeypatch
) -> None:
    storage = RoundAnalysisArtifactStorage(tmp_path)
    storage.publish(ANALYSIS_ID, b"input", b"result")

    with pytest.raises(FileExistsError):
        storage.publish(ANALYSIS_ID, b"other-input", b"other-result")

    other_id = UUID("00000000-0000-0000-0000-000000000036")
    original_rename = storage._rename

    def fail_rename(source, destination):
        raise OSError("simulated artifact publish failure")

    monkeypatch.setattr(storage, "_rename", fail_rename)
    with pytest.raises(OSError, match="simulated artifact publish failure"):
        storage.publish(other_id, b"input", b"result")

    assert not storage.analysis_path(other_id).exists()
    assert list(storage.root.glob(f".{other_id}-*")) == []
    assert original_rename is not None
