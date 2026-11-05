import json
from dataclasses import replace
from pathlib import Path

import pytest
from doko_operations.pipeline_data import (
    DataRevision,
    HumanProducer,
    PipelineSelection,
    RecordingVideoSource,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    sha256_bytes,
)
from doko_operations.pipeline_reference import PipelineReferenceDraft, PipelineReferenceState
from table_evidence_analyzer.pipeline_data import canonical_visible_card_data_bytes

from dokodetector_backend.lineage_migration_inventory import inventory

NOW = "2026-11-05T10:00:00Z"


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())


def fixture(root: Path):
    video = b"fixture video"
    path = root / "data/intake/recordings/rec/video.mov"
    path.parent.mkdir(parents=True)
    path.write_bytes(video)
    source = RecordingVideoSource(
        "rec", path.relative_to(root).as_posix(), sha256_bytes(video), len(video), 10000
    )
    content = canonical_event_data_bytes({"schema_version": "event-data/v1", "events": []})
    manifest = DataRevision(
        revision_id="base",
        content_type="events",
        content_schema="event-data/v1",
        recording_id="rec",
        source=source,
        content_sha256=sha256_bytes(content),
        input_revision_ids=(),
        origin="manual",
        producer=HumanProducer(review_id="review", operator_id="person"),
        coverage={"kind": "fixture"},
        created_at=NOW,
    )
    revision = root / "pipeline/revisions/base"
    revision.mkdir(parents=True)
    (revision / "manifest.json").write_bytes(canonical_data_revision_bytes(manifest))
    (revision / "content.json").write_bytes(content)
    visible = canonical_visible_card_data_bytes(
        {"schema_version": "visible-card-data/v1", "outcomes": []}
    )
    visible_manifest = replace(
        manifest,
        revision_id="visible-base",
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        content_sha256=sha256_bytes(visible),
    )
    revision = root / "pipeline/revisions/visible-base"
    revision.mkdir(parents=True)
    (revision / "manifest.json").write_bytes(canonical_data_revision_bytes(visible_manifest))
    (revision / "content.json").write_bytes(visible)
    state = PipelineReferenceState("rec", "events", 0, "draft", "base", None, NOW)
    draft = PipelineReferenceDraft("rec", "events", 0, "base", (), None, (), NOW)
    for folder in [
        root / "pipeline-references/rec/events",
        root / "pipeline-reviews/rec/visible_cards/review-a",
        root / "pipeline-reviews/rec/visible_cards/review-b",
    ]:
        is_review = folder.parent.name == "visible_cards"
        selected_state = (
            replace(state, content_type="visible_cards", source_revision_id="visible-base")
            if is_review
            else state
        )
        selected_draft = (
            replace(draft, content_type="visible_cards", source_revision_id="visible-base")
            if is_review
            else draft
        )
        write(folder / "state.json", selected_state.to_mapping())
        write(folder / "draft.json", selected_draft.to_mapping())
        write(folder / "commands.json", {})
        if folder.parent.name == "visible_cards":
            write(
                folder / "review.json",
                {
                    "schema_version": "visible-card-review/v1",
                    "recording_id": "rec",
                    "review_id": folder.name,
                    "lineage": {},
                    "status": "draft",
                    "source": "visible_regions",
                    "created_at": NOW,
                    "updated_at": NOW,
                    "idempotency_key": None,
                    "request_digest": None,
                },
            )
    selection = PipelineSelection(0, "rec", "events", "missing", None, NOW)
    write(root / "pipeline/selections/rec/events.json", selection.to_mapping())


def test_deterministic_groups_distinct_reviews_and_dangling_selection(tmp_path: Path):
    fixture(tmp_path)
    before = sorted(
        (p.relative_to(tmp_path).as_posix(), p.read_bytes())
        for p in tmp_path.rglob("*")
        if p.is_file()
    )
    first = inventory({"snapshot": tmp_path}, snapshot_is_immutable=True)
    assert first == inventory({"snapshot": tmp_path}, snapshot_is_immutable=True)
    reviews = [r for r in first["resources"] if r["kind"] == "independent_review"]
    assert len(reviews) == 2 and reviews[0]["new_id"] != reviews[1]["new_id"]
    assert all(r["unknown_history"] == "not_recorded" for r in reviews)
    assert all(r["references"][0]["old_revision_id"] == "visible-base" for r in reviews)
    assert any(
        c["kind"] == "dangling_revision" and c["revision_id"] == "missing"
        for c in first["conflicts"]
    )
    assert not first["activation_ready"]
    assert before == sorted(
        (p.relative_to(tmp_path).as_posix(), p.read_bytes())
        for p in tmp_path.rglob("*")
        if p.is_file()
    )


def test_sealed_content_is_not_read_and_symlinks_are_rejected(tmp_path: Path):
    (tmp_path / "sealed").mkdir()
    (tmp_path / "sealed" / "sample").write_bytes(b"do not read")
    declared = [
        {
            "root_id": "r",
            "relative_path": "sealed",
            "artifact_id": "sealed-campaign",
            "sha256": "a" * 64,
        }
    ]
    result = inventory({"r": tmp_path}, sealed=declared, snapshot_is_immutable=True)
    assert not result["files"]
    assert result["sealed_artifacts"] == declared
    (tmp_path / "link").symlink_to(tmp_path / "sealed", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        inventory({"r": tmp_path}, sealed=declared, snapshot_is_immutable=True)


def test_snapshot_change_during_scan_is_rejected(tmp_path: Path, monkeypatch):
    import dokodetector_backend.lineage_migration_inventory as module

    (tmp_path / "file").write_text("original")
    original = module._files
    calls = 0

    def changed(*args):
        nonlocal calls
        calls += 1
        result = original(*args)
        if calls == 1:
            (tmp_path / "file").write_text("changed")
        return result

    monkeypatch.setattr(module, "_files", changed)
    with pytest.raises(ValueError, match="snapshot changed"):
        inventory({"r": tmp_path}, snapshot_is_immutable=True)


def test_repaired_selection_keeps_unknown_history_without_blocking(tmp_path: Path):
    fixture(tmp_path)
    selection = PipelineSelection(0, "rec", "events", "base", None, NOW)
    write(tmp_path / "pipeline/selections/rec/events.json", selection.to_mapping())
    result = inventory({"snapshot": tmp_path}, snapshot_is_immutable=True, scope_complete=True)
    assert result["conflicts"] == []
    assert result["activation_ready"]
    assert any(item["kind"] == "item_history_not_recorded" for item in result["uncertainties"])
    selected = next(r for r in result["resources"] if r["kind"] == "selection")
    assert selected["references"][0]["target_revision_id"]


def test_table_observation_identity_is_checked_against_its_own_path(tmp_path: Path):
    observation_id = "observation-one"
    write(
        tmp_path / "table-observations" / observation_id / "observation.json",
        {
            "schema_version": "table-observation/v1",
            "observation_id": observation_id,
            "source": {"package_id": "package-one"},
            "session": {"session_id": "session-one", "event_sequence": 1},
            "observed_at_ms": 10,
            "status": "observed",
            "capabilities": ["identity_candidates"],
            "cards": [],
            "calibration": "uncalibrated",
            "analyzer": {"name": "fixture", "version": "v1"},
            "diagnostics": {},
        },
    )

    result = inventory({"snapshot": tmp_path}, snapshot_is_immutable=True)

    assert not any(
        conflict.get("message") == "observation identity differs from path"
        for conflict in result["conflicts"]
    )
    observation = next(
        resource
        for resource in result["resources"]
        if resource["kind"] == "table_observation_artifact"
    )
    assert observation["old_id"] == observation_id
    assert observation["recording_id"] is None


def test_unrecognized_sealed_path_is_not_read(tmp_path: Path, monkeypatch):
    import dokodetector_backend.lineage_migration_inventory as module

    sealed = tmp_path / "sealed"
    sealed.mkdir()
    (sealed / "sample").write_text("never inspect")
    original = module._stable_file

    def protect(path, **kwargs):
        assert sealed not in path.parents
        return original(path, **kwargs)

    monkeypatch.setattr(module, "_stable_file", protect)
    with pytest.raises(ValueError, match="must be explicitly declared"):
        inventory({"r": tmp_path}, snapshot_is_immutable=True)


def test_immutable_snapshot_is_required(tmp_path: Path):
    with pytest.raises(ValueError, match="immutable source snapshot"):
        inventory({"r": tmp_path})


def test_unclassified_paths_and_missing_sources_block_readiness(tmp_path: Path):
    fixture(tmp_path)
    (tmp_path / "extra.bin").write_bytes(b"unknown")
    (tmp_path / "data/intake/recordings/rec/video.mov").unlink()
    result = inventory({"r": tmp_path}, snapshot_is_immutable=True)
    assert any(c["kind"] == "missing_or_ambiguous_source" for c in result["conflicts"])
    assert any(
        u["kind"] == "unclassified_artifact" and u["path"] == "extra.bin"
        for u in result["uncertainties"]
    )
    assert not result["activation_ready"]


def test_consumer_reference_inventory_and_incomplete_scope(tmp_path: Path):
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "reader.py").write_text('REFERENCE_ROOT = "pipeline-references"\n')
    result = inventory({"repo": root}, snapshot_is_immutable=True, consumer_root_ids=["repo"])
    assert result["consumer_references"] == [
        {"root_id": "repo", "path": "reader.py", "line": 1, "references": ["pipeline-references"]}
    ]
    assert any(u["kind"] == "source_scope_not_confirmed" for u in result["uncertainties"])
    assert not result["activation_ready"]


def test_command_writes_only_outside_snapshot(tmp_path: Path, monkeypatch):
    import sys

    from dokodetector_backend.lineage_migration_inventory import main

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    config = tmp_path / "config.json"
    write(
        config,
        {"roots": {"r": str(snapshot)}, "snapshot_is_immutable": True, "scope_complete": True},
    )
    output = tmp_path / "plan.json"
    monkeypatch.setattr(sys, "argv", ["inventory", str(config), str(output)])
    main()
    assert json.loads(output.read_text())["activation_ready"]
    monkeypatch.setattr(sys, "argv", ["inventory", str(config), str(snapshot / "plan.json")])
    with pytest.raises(SystemExit):
        main()
    assert not (snapshot / "plan.json").exists()


def test_calibration_draft_groups_snapshots_without_inventing_edits(tmp_path: Path):
    from table_evidence_analyzer.card_scene_contract import CalibrationDraft

    fixture(tmp_path)
    draft = CalibrationDraft.create(
        draft_id="draft-1",
        recording_id="rec",
        detector_revision_id="visible-base",
        detector_revision_digest="a" * 64,
        base_calibration_revision_id="calibration-1",
        base_calibration_digest="c" * 64,
        source_frame_digests={},
        anchors=[],
        commands=[],
    )
    folder = tmp_path / "rec/table-plane-calibration-drafts/draft-1"
    write(folder / "initial.json", draft.to_mapping())
    write(folder / "draft.json", draft.to_mapping())
    plan = inventory({"r": tmp_path}, snapshot_is_immutable=True)
    resource = next(r for r in plan["resources"] if r["kind"] == "calibration_draft")
    assert resource["initial_revision_id"] == resource["new_revision_id"]
    assert any(c["kind"] == "dangling_calibration" for c in plan["conflicts"])
    assert any(
        u["kind"] == "intermediate_draft_history_not_recorded" for u in plan["uncertainties"]
    )


def test_duplicate_revision_identity_across_roots_is_ambiguous(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    fixture(left)
    fixture(right)
    plan = inventory(
        {"left": left, "right": right}, snapshot_is_immutable=True, scope_complete=True
    )
    assert any(
        c["kind"] == "ambiguous_revision" and c["revision_id"] == "base" for c in plan["conflicts"]
    )
    assert any(c["kind"] == "ambiguous_reference" for c in plan["conflicts"])
    assert not plan["activation_ready"]


def test_corrupt_revision_and_wrong_selection_type_block(tmp_path: Path):
    fixture(tmp_path)
    (tmp_path / "pipeline/revisions/base/content.json").write_bytes(b"{}")
    selection = PipelineSelection(0, "rec", "events", "visible-base", None, NOW)
    write(tmp_path / "pipeline/selections/rec/events.json", selection.to_mapping())
    plan = inventory({"r": tmp_path}, snapshot_is_immutable=True, scope_complete=True)
    assert any(c["kind"] == "invalid_resource" for c in plan["conflicts"])
    assert any(c["kind"] == "revision_type_mismatch" for c in plan["conflicts"])
    assert not plan["activation_ready"]
