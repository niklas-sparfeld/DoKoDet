import hashlib
import json
import shutil
from pathlib import Path

import pytest

from dokodetector_backend.operator_corpus_import import (
    OperatorCorpusImportError,
    import_recordings,
)
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage

FIXTURE = Path(__file__).parents[2] / "fixtures/repository-bundle/v1/both"


def _manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_operator_bundle_is_copied_with_exact_identity_without_source_changes(
    tmp_path: Path,
) -> None:
    corpus_root = tmp_path / "operator-corpus"
    source = corpus_root / "recording-both"
    source.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE, source)
    source_before = _manifest(source)
    target_root = tmp_path / "worktree-state" / "recordings"

    receipt = import_recordings(corpus_root, target_root, ("recording-both",))

    copied = target_root / "recording-both"
    assert receipt[0].created is True
    assert receipt[0].file_count == len(source_before) == 5
    assert receipt[0].bundle_fingerprint
    root = json.loads((copied / "recording.json").read_text())
    assert root["schema_version"] == "recording/v1"
    assert root["version"] == 1
    assert root["source"]["source_permission"] == "training_and_evaluation"
    assert root["source"]["allowed_uses"] == ["train", "validation", "evaluation"]
    assert root["task_enrollment"]["schema_version"] == "task-enrollment/v1"
    assert root["proposal_generator_runs"][0]["proposal_generator_run_id"] == "proposal-both"
    assert (copied / "source/video-both.mov").read_bytes() == (
        source / "videos/video-both.mov"
    ).read_bytes()
    assert _manifest(source) == source_before
    assert not (copied / "manifest.json").exists()
    assert RecordingBundleStore(RepositoryBundleStorage(corpus_root)).get("recording-both")
    assert (copied / "source/video-both.mov").stat().st_nlink == 1

    replay = import_recordings(corpus_root, target_root, ("recording-both",))
    assert replay[0].created is False
    assert replay[0].bundle_fingerprint == receipt[0].bundle_fingerprint


def test_operator_import_rejects_a_missing_source_and_writes_nothing(tmp_path: Path) -> None:
    corpus_root = tmp_path / "operator-corpus"
    corpus_root.mkdir()
    target_root = tmp_path / "worktree-state" / "recordings"

    with pytest.raises(OperatorCorpusImportError, match="missing or unsafe"):
        import_recordings(corpus_root, target_root, ("missing-recording",))

    assert not target_root.exists()
