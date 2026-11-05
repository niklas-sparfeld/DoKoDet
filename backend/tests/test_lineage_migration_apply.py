import hashlib
import json
from pathlib import Path

import pytest

from dokodetector_backend.lineage_migration_apply import apply_plan


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plan(root: Path) -> dict:
    payload = b'{"events":[],"schema_version":"event-data/v1"}'
    path = root / "pipeline/revisions/rev-1/content.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    digest = _sha(payload)
    return {
        "schema_version": "lineage-migration-inventory/v1",
        "snapshot_sha256": "a" * 64,
        "activation_ready": True,
        "conflicts": [],
        "uncertainties": [],
        "sealed_artifacts": [],
        "files": [
            {
                "root_id": "snapshot",
                "path": "pipeline/revisions/rev-1/content.json",
                "byte_length": len(payload),
                "sha256": digest,
            }
        ],
        "resources": [
            {
                "kind": "pipeline_revision",
                "root_id": "snapshot",
                "old_id": "rev-1",
                "relative_identity": "pipeline/revisions/rev-1",
                "new_id": "node-1",
                "new_revision_id": "revision-1",
                "content_type": "events",
                "recording_id": "rec-1",
                "content_sha256": digest,
                "unknown_history": "not_recorded",
                "references": [],
                "files": [
                    {
                        "path": "pipeline/revisions/rev-1/content.json",
                        "byte_length": len(payload),
                        "sha256": digest,
                    }
                ],
            },
            {
                "kind": "selection",
                "root_id": "snapshot",
                "old_id": "rec-1/events",
                "relative_identity": "pipeline/selections/rec-1/events.json",
                "new_id": "selection-1",
                "references": [
                    {
                        "role": "generated",
                        "target_id": "node-1",
                        "target_revision_id": "revision-1",
                    }
                ],
                "files": [],
            },
        ],
    }


def test_apply_plan_copies_and_verifies_then_reapplies_idempotently(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    plan = _plan(source)
    target = tmp_path / "staged"

    first = apply_plan(plan, target, {"snapshot": source})
    second = apply_plan(plan, target, {"snapshot": source})

    assert first == second
    assert first["file_count"] == 1
    assert first["resource_count"] == 2
    assert (target / "evidence/snapshot/pipeline/revisions/rev-1/content.json").read_bytes() == (
        source / "pipeline/revisions/rev-1/content.json"
    ).read_bytes()
    converted = json.loads((target / "resources/node-1.json").read_text())
    assert converted["new_revision_id"] == "revision-1"
    selection = json.loads((target / "resources/selection-1.json").read_text())
    assert selection["references"][0]["target_revision_id"] == "revision-1"
    assert not list(tmp_path.glob(".staged-*"))


def test_reference_only_root_is_verified_without_copying_its_bytes(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    plan = _plan(source)
    media = tmp_path / "media"
    media.mkdir()
    video = b"large external video"
    (media / "recording.mov").write_bytes(video)
    plan["files"].append(
        {
            "root_id": "media",
            "path": "recording.mov",
            "byte_length": len(video),
            "sha256": _sha(video),
        }
    )
    plan["reference_only_root_ids"] = ["media"]
    target = tmp_path / "staged"

    manifest = apply_plan(plan, target, {"snapshot": source, "media": media})

    external = next(item for item in manifest["files"] if item["root_id"] == "media")
    assert external == {
        "root_id": "media",
        "path": "recording.mov",
        "external_reference": True,
        "byte_length": len(video),
        "sha256": _sha(video),
    }
    assert not (target / "evidence/media/recording.mov").exists()
    (media / "recording.mov").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source snapshot changed"):
        apply_plan(plan, tmp_path / "retry", {"snapshot": source, "media": media})


def test_lost_revision_policy_is_staged_and_checked(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    plan = _plan(source)
    lost_id = "visible-cards-lost-run-attempt-1"
    plan["lost_revision_ids"] = [lost_id]
    plan["resources"][1]["references"].append(
        {
            "role": "input",
            "old_revision_id": lost_id,
            "target_id": None,
            "target_revision_id": None,
            "availability": "lost",
        }
    )

    manifest = apply_plan(plan, tmp_path / "staged", {"snapshot": source})

    assert manifest["lost_revision_ids"] == [lost_id]
    selection = json.loads((tmp_path / "staged/resources/selection-1.json").read_text())
    assert selection["references"][1]["availability"] == "lost"
    assert len(manifest["plan_sha256"]) == 64


def test_apply_plan_refuses_changed_source_and_preserves_no_destination(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    plan = _plan(source)
    (source / "pipeline/revisions/rev-1/content.json").write_bytes(b"changed")
    target = tmp_path / "staged"

    with pytest.raises(ValueError, match="snapshot changed"):
        apply_plan(plan, target, {"snapshot": source})

    assert not target.exists()


def test_apply_plan_refuses_to_overwrite_different_destination(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    plan = _plan(source)
    target = tmp_path / "staged"
    target.mkdir()
    (target / "unrelated").write_text("keep")

    with pytest.raises(ValueError, match="already exists"):
        apply_plan(plan, target, {"snapshot": source})

    assert (target / "unrelated").read_text() == "keep"


def test_apply_plan_requires_destination_outside_snapshot(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    plan = _plan(source)

    with pytest.raises(ValueError, match="outside all source roots"):
        apply_plan(plan, source / "migration", {"snapshot": source})

    assert sorted(path.relative_to(source).as_posix() for path in source.rglob("*")) == [
        "pipeline",
        "pipeline/revisions",
        "pipeline/revisions/rev-1",
        "pipeline/revisions/rev-1/content.json",
    ]


@pytest.mark.parametrize("failure_point", ["copy", "verify", "publish"])
def test_interrupted_apply_keeps_source_and_leaves_no_partial_package(
    tmp_path: Path, monkeypatch, failure_point: str
):
    import dokodetector_backend.lineage_migration_apply as module

    def fail(error):
        raise error

    source = tmp_path / "source"
    source.mkdir()
    plan = _plan(source)
    target = tmp_path / "staged"
    source_bytes = (source / "pipeline/revisions/rev-1/content.json").read_bytes()
    active_pointer = tmp_path / "active-root.txt"
    active_pointer.write_text("existing-store")
    if failure_point == "copy":
        monkeypatch.setattr(module.shutil, "copyfile", lambda *_: fail(OSError()))
    elif failure_point == "verify":
        monkeypatch.setattr(module, "_verify_package", lambda *_: fail(ValueError()))
    else:
        monkeypatch.setattr(module.os, "rename", lambda *_: fail(OSError()))

    with pytest.raises((OSError, ValueError)):
        apply_plan(plan, target, {"snapshot": source})

    assert not target.exists()
    assert (source / "pipeline/revisions/rev-1/content.json").read_bytes() == source_bytes
    assert active_pointer.read_text() == "existing-store"
    assert not list(tmp_path.glob(".staged-*"))
