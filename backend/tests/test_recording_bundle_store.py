from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path

from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1"


def _copy_fixture(source: str, root: Path, recording_id: str = "recording-both") -> Path:
    destination = root / recording_id
    shutil.copytree(FIXTURE_ROOT / source, destination)
    return destination


def test_store_reads_canonical_bundle_without_rebuild(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    bundle_path = _copy_fixture("both", intake_root)
    store = RecordingBundleStore(RepositoryBundleStorage(intake_root))

    stored = store.get("recording-both")

    assert stored is not None
    assert stored.recording_id == "recording-both"
    assert stored.source_sha256 == json.loads((bundle_path / "manifest.json").read_text())[
        "source_sha256"
    ]
    assert stored.received_at.isoformat() == "2026-08-28T08:00:00+00:00"


def test_invalid_canonical_member_is_excluded_and_reported(tmp_path: Path, caplog) -> None:
    intake_root = tmp_path / "intake"
    _copy_fixture("both", intake_root)
    invalid_path = _copy_fixture("both", intake_root, "recording-invalid")
    source_path = invalid_path / "source-record.json"
    source = json.loads(source_path.read_text())
    source["notes"] = "changed"
    source_path.write_text(json.dumps(source))
    store = RecordingBundleStore(RepositoryBundleStorage(intake_root))

    with caplog.at_level(logging.WARNING):
        bundles = store.list()

    assert [item.recording_id for item in bundles] == ["recording-both"]
    warning = next(
        record
        for record in caplog.records
        if record.msg == "recording_bundle_catalog_skipped"
        and record.event_fields["recording_id"] == "recording-invalid"
    )
    assert warning.levelno == logging.WARNING


def test_catalog_accepts_harmless_extra_files(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    bundle_path = _copy_fixture("both", intake_root)
    (bundle_path / "operator-note.txt").write_text("local note", encoding="utf-8")
    (bundle_path / ".DS_Store").write_bytes(b"finder metadata")
    store = RecordingBundleStore(RepositoryBundleStorage(intake_root))

    bundles = store.list()

    assert [item.recording_id for item in bundles] == ["recording-both"]


def test_catalog_order_is_stable_and_newest_received_first(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    first = _copy_fixture("both", intake_root, "recording-z")
    second = _copy_fixture("both", intake_root, "recording-a")
    for path in (first, second):
        enrollment_path = path / "initial-task-enrollment.json"
        enrollment = json.loads(enrollment_path.read_text())
        enrollment["enrollments"][0]["created_at_utc"] = "2026-08-28T08:00:00Z"
        enrollment["enrollments"][1]["created_at_utc"] = "2026-08-28T08:00:00Z"
        enrollment_path.write_text(json.dumps(enrollment))

    # Changed canonical bytes need matching descriptors and identities in each manifest.
    for path in (first, second):
        enrollment_path = path / "initial-task-enrollment.json"
        source_path = path / "source-record.json"
        proposal_path = next((path / "predictions").glob("*.json"))
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        enrollment = enrollment_path.read_bytes()
        source = json.loads(source_path.read_text())
        proposal = json.loads(proposal_path.read_text())
        source["recording_id"] = path.name
        proposal["recording_id"] = path.name
        source_bytes = json.dumps(source, separators=(",", ":")).encode()
        proposal_bytes = json.dumps(proposal, separators=(",", ":")).encode()
        source_path.write_bytes(source_bytes)
        proposal_path.write_bytes(proposal_bytes)
        descriptor = manifest["files"]["task_enrollment"]
        descriptor["byte_length"] = len(enrollment)
        descriptor["sha256"] = hashlib.sha256(enrollment).hexdigest()
        manifest["files"]["source_record"].update(
            byte_length=len(source_bytes), sha256=hashlib.sha256(source_bytes).hexdigest()
        )
        manifest["files"]["proposal_generator_runs"][0].update(
            byte_length=len(proposal_bytes), sha256=hashlib.sha256(proposal_bytes).hexdigest()
        )
        manifest["recording_id"] = path.name
        manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))

    store = RecordingBundleStore(RepositoryBundleStorage(intake_root))

    assert [item.recording_id for item in store.list()] == ["recording-a", "recording-z"]
