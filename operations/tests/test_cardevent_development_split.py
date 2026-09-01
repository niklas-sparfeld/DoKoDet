from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from doko_operations import (
    CardEventDevelopmentRecording,
    CardEventDevelopmentSplitConflict,
    CardEventDevelopmentSplitStore,
    seal_system_holdout_group,
)
from doko_operations.cli import main
from doko_operations.intake import inspect_repository


def recording(
    recording_id: str,
    *,
    session_id: str = "session-1",
    review_state: str = "completed",
    allowed_uses: tuple[str, ...] = ("train", "validation"),
    group_keys: tuple[tuple[str, str], ...] | None = None,
) -> CardEventDevelopmentRecording:
    return CardEventDevelopmentRecording(
        recording_id=recording_id,
        source_asset_id=f"source-{recording_id}",
        source_sha256=(recording_id.encode().hex() * 64)[:64],
        source_permission="training_and_evaluation",
        allowed_uses=allowed_uses,
        retention_state="active",
        task_selected=True,
        review_state=review_state,
        group_keys=group_keys
        or (
            ("source_lineage", f"source-{recording_id}"),
            ("session_id", session_id),
            ("game_id", "game-1"),
            ("table_setup", "table-1"),
        ),
    )


def test_preview_and_apply_move_the_complete_connected_group(tmp_path: Path) -> None:
    store = CardEventDevelopmentSplitStore(tmp_path)
    facts = (
        recording("recording-a"),
        recording("recording-b"),
        recording(
            "recording-c",
            session_id="session-2",
            group_keys=(
                ("source_lineage", "source-recording-c"),
                ("session_id", "session-2"),
                ("game_id", "game-2"),
                ("table_setup", "table-2"),
            ),
        ),
    )

    initial = store.read(facts)
    preview = store.preview(
        facts,
        recording_id="recording-a",
        destination="train",
        expected_active_split_digest=initial["split_version_digest"],
    )

    assert preview["validation"] == {"valid": True, "blockers": []}
    assert [item["recording_id"] for item in preview["affected_recordings"]] == [
        "recording-a",
        "recording-b",
    ]
    assert preview["current_counts"] == {
        "train": 0,
        "validation": 0,
        "unassigned": 3,
        "test": 0,
    }
    assert preview["proposed_counts"] == {
        "train": 2,
        "validation": 0,
        "unassigned": 1,
        "test": 0,
    }

    applied = store.apply(
        facts,
        recording_id="recording-a",
        destination="train",
        expected_active_split_digest=initial["split_version_digest"],
        preview_digest=preview["preview_digest"],
        operator="operator",
    )

    assert applied["counts"] == {
        "train": 2,
        "validation": 0,
        "unassigned": 1,
        "test": 0,
    }
    assert set(applied["partitions"]["train"]) == {"recording-a", "recording-b"}
    assert applied["partitions"]["unassigned"] == ["recording-c"]
    assert (tmp_path / "cardevent-development-split" / "active.json").is_file()
    assert len(list((tmp_path / "cardevent-development-split" / "versions").glob("*.json"))) == 1
    assert len(list((tmp_path / "cardevent-development-split" / "receipts").glob("*.json"))) == 1

    next_preview = store.preview(
        facts,
        recording_id="recording-a",
        destination="unassigned",
        expected_active_split_digest=applied["split_version_digest"],
    )
    assert next_preview["validation"]["valid"] is True
    restored = store.apply(
        facts,
        recording_id="recording-a",
        destination="unassigned",
        expected_active_split_digest=applied["split_version_digest"],
        preview_digest=next_preview["preview_digest"],
        operator="operator",
    )
    assert restored["partitions"]["train"] == []
    assert restored["partitions"]["unassigned"] == [
        "recording-a",
        "recording-b",
        "recording-c",
    ]


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("review_state", "Full-recording CardEvent review is incomplete"),
        ("allowed_uses", "does not allow validation use"),
        ("group_keys", "Missing leakage-group data"),
    ],
)
def test_preview_reports_assignment_blockers(tmp_path: Path, field: str, expected: str) -> None:
    store = CardEventDevelopmentSplitStore(tmp_path)
    values = {"recording-a": recording("recording-a")}
    if field == "review_state":
        values["recording-a"] = recording("recording-a", review_state="draft")
    elif field == "allowed_uses":
        values["recording-a"] = recording("recording-a", allowed_uses=("train",))
    else:
        values["recording-a"] = recording(
            "recording-a",
            group_keys=(("source_lineage", "source-recording-a"),),
        )
    facts = tuple(values.values())
    active = store.read(facts)

    preview = store.preview(
        facts,
        recording_id="recording-a",
        destination="validation",
        expected_active_split_digest=active["split_version_digest"],
    )

    assert preview["validation"]["valid"] is False
    assert any(expected in blocker for blocker in preview["validation"]["blockers"])


def test_stale_active_digest_is_rejected(tmp_path: Path) -> None:
    store = CardEventDevelopmentSplitStore(tmp_path)
    facts = (recording("recording-a"),)
    with pytest.raises(CardEventDevelopmentSplitConflict, match="active development split changed"):
        store.preview(
            facts,
            recording_id="recording-a",
            destination="train",
            expected_active_split_digest="0" * 64,
        )


def test_test_and_system_holdout_groups_are_read_only(tmp_path: Path) -> None:
    store = CardEventDevelopmentSplitStore(tmp_path)
    facts = (recording("recording-a"),)
    initial = store.read(facts)
    core = {
        **initial,
        "test": ["recording-a"],
        "unassigned": [],
    }
    core.pop("split_version_id")
    core.pop("split_version_digest")
    digest = hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    version_id = "cardevent-development-split-test"
    version = {**core, "split_version_id": version_id, "split_version_digest": digest}
    version_path = tmp_path / "cardevent-development-split" / "versions" / f"{version_id}.json"
    version_path.parent.mkdir(parents=True)
    version_path.write_text(json.dumps(version), encoding="utf-8")
    active_path = tmp_path / "cardevent-development-split" / "active.json"
    active_path.write_text(
        json.dumps(
            {
                "schema_version": "cardevent-development-split-active/v1",
                "split_version_id": version_id,
                "split_version_digest": digest,
            }
        ),
        encoding="utf-8",
    )

    test_preview = store.preview(
        facts,
        recording_id="recording-a",
        destination="train",
        expected_active_split_digest=digest,
    )
    assert "read-only test partition" in " ".join(test_preview["validation"]["blockers"])

    seal_system_holdout_group(
        tmp_path / "system-holdout-registry.json",
        group_name="session_id",
        group_value="session-1",
        reviewer="operator",
        reason="fixture holdout",
    )
    holdout_preview = store.preview(
        facts,
        recording_id="recording-a",
        destination="unassigned",
        expected_active_split_digest=digest,
    )
    assert "read-only system holdout" in " ".join(holdout_preview["validation"]["blockers"])


def test_published_version_and_receipt_keep_parent_and_digest_provenance(tmp_path: Path) -> None:
    store = CardEventDevelopmentSplitStore(tmp_path)
    facts = (recording("recording-a"),)
    initial = store.read(facts)
    preview = store.preview(
        facts,
        recording_id="recording-a",
        destination="train",
        expected_active_split_digest=initial["split_version_digest"],
    )
    applied = store.apply(
        facts,
        recording_id="recording-a",
        destination="train",
        expected_active_split_digest=initial["split_version_digest"],
        preview_digest=preview["preview_digest"],
        operator="operator",
    )

    version = json.loads(
        next((tmp_path / "cardevent-development-split" / "versions").glob("*.json")).read_text()
    )
    receipt = json.loads(
        next((tmp_path / "cardevent-development-split" / "receipts").glob("*.json")).read_text()
    )
    assert version["parent_split_version_digest"] == initial["split_version_digest"]
    assert version["split_version_digest"] == applied["split_version_digest"]
    assert receipt["inputs"][0] == {
        "kind": "split_version",
        "id": initial["split_version_id"],
        "digest": initial["split_version_digest"],
    }
    assert receipt["outputs"][0] == {
        "kind": "split_version",
        "id": applied["split_version_id"],
        "digest": applied["split_version_digest"],
    }


def test_doko_data_validate_accepts_published_split_artifacts(tmp_path: Path) -> None:
    fixture_root = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"
    store = CardEventDevelopmentSplitStore(tmp_path / "operations")
    facts = (recording("recording-both"),)
    initial = store.read(facts)
    preview = store.preview(
        facts,
        recording_id="recording-both",
        destination="train",
        expected_active_split_digest=initial["split_version_digest"],
    )
    store.apply(
        facts,
        recording_id="recording-both",
        destination="train",
        expected_active_split_digest=initial["split_version_digest"],
        preview_digest=preview["preview_digest"],
        operator="operator",
    )

    result = inspect_repository(
        tmp_path,
        bundle_root=fixture_root,
        evidence_package_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
        artifacts_root=tmp_path / "operations",
    )
    assert result.valid
    assert main(
        [
            "data",
            "validate",
            "--repository-root",
            str(tmp_path),
            "--intake-root",
            str(fixture_root),
            "--evidence-package-root",
            str(tmp_path / "evidence-packages"),
            "--pending-video-root",
            str(tmp_path / "pending-videos"),
            "--artifacts-root",
            str(tmp_path / "operations"),
            "--format",
            "json",
        ]
    ) == 0
