import hashlib
import json
from pathlib import Path

from dokodetector_backend.upload_fixture import prepare_fixture

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v1"


def test_prepare_shared_manifest_fixture_creates_valid_deterministic_frames() -> None:
    manifest_bytes, manifest, frame_sources = prepare_fixture(FIXTURE_ROOT / "example-complete")

    assert manifest_bytes != (FIXTURE_ROOT / "example-complete" / "manifest.json").read_bytes()
    assert set(frame_sources) == {frame.part_name for frame in manifest.frames}
    for frame in manifest.frames:
        frame_bytes = frame_sources[frame.part_name]
        assert frame.byte_length == len(frame_bytes)
        assert frame.sha256 == hashlib.sha256(frame_bytes).hexdigest()


def test_prepare_fixture_uses_exact_frame_files(tmp_path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    source_manifest = (FIXTURE_ROOT / "example-incomplete" / "manifest.json").read_text()
    fixture.joinpath("manifest.json").write_text(source_manifest)
    frame_directory = fixture / "frames"
    frame_directory.mkdir()

    # The shared manifest has placeholder digests, so use a manifest with matching test bytes.
    frame_bytes = b"fixture frame"
    payload = json.loads(source_manifest)
    payload["frames"][0]["byte_length"] = len(frame_bytes)
    payload["frames"][0]["sha256"] = hashlib.sha256(frame_bytes).hexdigest()
    fixture.joinpath("manifest.json").write_text(json.dumps(payload, separators=(",", ":")))
    frame_directory.joinpath("frame_00.jpg").write_bytes(frame_bytes)

    _, manifest, frame_sources = prepare_fixture(fixture)

    assert manifest.frames[0].byte_length == len(frame_bytes)
    assert frame_sources == {
        "frame_00": frame_bytes,
        "frame_03": b"DokoDetector local fixture frame: frame_03",
    }
