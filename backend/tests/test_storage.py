import hashlib
from io import BytesIO
from uuid import UUID

import pytest

from dokodetector_backend.storage import EvidenceStorage

PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


def test_storage_writes_exact_bytes_and_renames_the_package(tmp_path) -> None:
    storage = EvidenceStorage(tmp_path)
    manifest_bytes = b'{"keep": "the original bytes"}\n'
    frame_bytes = b"not-a-real-jpeg-but-exact-test-bytes"

    with storage.start_package(PACKAGE_ID) as upload:
        upload.write_manifest(BytesIO(manifest_bytes))
        frame = upload.write_frame("frame_00", BytesIO(frame_bytes))
        stored = upload.commit()

    assert stored.manifest.relative_path == (f"evidence/{PACKAGE_ID}/manifest.json")
    assert stored.manifest.byte_length == len(manifest_bytes)
    assert stored.manifest.sha256 == hashlib.sha256(manifest_bytes).hexdigest()
    assert frame.relative_path == f"evidence/{PACKAGE_ID}/frames/frame_00.jpg"
    assert frame.byte_length == len(frame_bytes)
    assert frame.sha256 == hashlib.sha256(frame_bytes).hexdigest()
    assert storage.package_path(PACKAGE_ID).is_dir()
    assert (storage.package_path(PACKAGE_ID) / "manifest.json").read_bytes() == manifest_bytes
    assert (
        storage.package_path(PACKAGE_ID) / "frames" / "frame_00.jpg"
    ).read_bytes() == frame_bytes
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_failed_upload_cleans_up_temporary_directory_and_final_path(tmp_path) -> None:
    storage = EvidenceStorage(tmp_path)

    with (
        pytest.raises(RuntimeError, match="simulated write failure"),
        storage.start_package(PACKAGE_ID) as upload,
    ):
        upload.write_manifest(BytesIO(b"manifest"))
        raise RuntimeError("simulated write failure")

    assert not storage.package_path(PACKAGE_ID).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_storage_rejects_unsafe_frame_part_names(tmp_path) -> None:
    storage = EvidenceStorage(tmp_path)

    with (
        storage.start_package(PACKAGE_ID) as upload,
        pytest.raises(ValueError, match="safe part name"),
    ):
        upload.write_frame("../outside", BytesIO(b"frame"))
