from uuid import UUID

import pytest

from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage

ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000032")
COUNTERFACTUAL_ID = UUID("00000000-0000-0000-0000-000000000037")


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


def test_counterfactual_artifacts_record_digests_and_survive_readback(tmp_path) -> None:
    storage = RoundAnalysisArtifactStorage(tmp_path)
    request_bytes = b'{"request":true}'
    input_bytes = b'{"input":true}'
    result_bytes = b'{"result":true}'

    stored = storage.publish_counterfactual(
        ANALYSIS_ID,
        COUNTERFACTUAL_ID,
        request_bytes,
        input_bytes,
        result_bytes,
    )
    contents = storage.read_counterfactual(ANALYSIS_ID, COUNTERFACTUAL_ID)

    assert stored.request.relative_path == (
        f"round-analyses/{ANALYSIS_ID}/counterfactuals/{COUNTERFACTUAL_ID}/request.json"
    )
    assert contents.request_bytes == request_bytes
    assert contents.input_bytes == input_bytes
    assert contents.result_bytes == result_bytes
    assert contents.artifacts.result.sha256 == stored.result.sha256
    assert (storage.counterfactual_path(ANALYSIS_ID, COUNTERFACTUAL_ID) / "manifest.json").is_file()

    (storage.counterfactual_path(ANALYSIS_ID, COUNTERFACTUAL_ID) / "result.json").write_bytes(
        b"tampered"
    )
    with pytest.raises(OSError, match="failed verification"):
        storage.read_counterfactual(ANALYSIS_ID, COUNTERFACTUAL_ID)


def test_counterfactual_publish_rejects_replay_and_cleans_failed_staging(
    tmp_path, monkeypatch
) -> None:
    storage = RoundAnalysisArtifactStorage(tmp_path)
    storage.publish_counterfactual(
        ANALYSIS_ID,
        COUNTERFACTUAL_ID,
        b"request",
        b"input",
        b"result",
    )

    with pytest.raises(FileExistsError):
        storage.publish_counterfactual(
            ANALYSIS_ID,
            COUNTERFACTUAL_ID,
            b"other-request",
            b"input",
            b"result",
        )

    failed_id = UUID("00000000-0000-0000-0000-000000000038")

    def fail_rename(source, destination):
        raise OSError("simulated counterfactual publish failure")

    monkeypatch.setattr(storage, "_rename", fail_rename)
    with pytest.raises(OSError, match="simulated counterfactual publish failure"):
        storage.publish_counterfactual(
            ANALYSIS_ID,
            failed_id,
            b"request",
            b"input",
            b"result",
        )

    assert not storage.counterfactual_path(ANALYSIS_ID, failed_id).exists()
    assert (
        list(storage.counterfactual_path(ANALYSIS_ID, failed_id).parent.glob(f".{failed_id}-*"))
        == []
    )
