from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cardevent.repository_intake import (
    RepositoryIntakeError,
    discover_repository_recordings,
    load_repository_recording,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1"


def test_cardevent_opens_canonical_video_and_proposals_without_copying() -> None:
    root = FIXTURE_ROOT / "both"
    recording = load_repository_recording(root)

    assert recording.video_path == root / "videos" / "video-both.mov"
    assert recording.proposal_paths == (root / "predictions" / "proposal-both.json",)
    assert recording.source_record.source_asset_id == "source-both"
    assert recording.proposal_runs[0].purpose == "proposal_only"


def test_repository_discovery_is_sorted_and_rejects_tampered_proposal(tmp_path: Path) -> None:
    for name in ("both", "cardevent-only"):
        shutil.copytree(FIXTURE_ROOT / name, tmp_path / name)
    discovered = discover_repository_recordings(tmp_path)
    assert [item.bundle.recording_id for item in discovered] == [
        "recording-both",
        "recording-cardevent-only",
    ]
    proposal = next((tmp_path / "both" / "predictions").glob("*.json"))
    proposal.write_bytes(proposal.read_bytes() + b" ")
    with pytest.raises(RepositoryIntakeError, match="invalid"):
        load_repository_recording(tmp_path / "both")
