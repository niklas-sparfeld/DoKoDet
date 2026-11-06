from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from doko_operations.pipeline_data import PipelineSelection, canonical_pipeline_selection_bytes

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/repair_0100_m5.py"
spec = importlib.util.spec_from_file_location("repair_0100_m5", SCRIPT)
assert spec is not None and spec.loader is not None
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def _write(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return hashlib.sha256(value).hexdigest()


def _fixture(root: Path):
    stage = root / "stage"
    geometry = {"destination": str(stage), "records": [], "repair_at": "2026-10-30T00:00:00Z"}
    identities = {"destination": str(stage), "records": []}
    drafts = {"destination": str(stage), "records": []}
    validation = {"destination": str(stage), "references": [], "selections": [], "crop_checks": []}
    items = []
    for number in range(53):
        old = (
            "visual-identities-visual_identities-run-debcf221-570-attempt-1"
            if number == 28
            else f"old-{number}"
        )
        new = f"repair-0100-m5-{number:032x}"
        old_dir = root / "data/operations/pipeline/revisions" / old
        new_dir = stage / "pipeline/revisions" / new
        content = json.dumps(
            {"outcomes": [{"card_id": f"card-{number}", "status": "classified"}]}
        ).encode()
        old_digest = _write(old_dir / "content.json", content)
        new_digest = _write(new_dir / "content.json", content)
        parents = [] if number >= 40 else [f"old-{40 + number % 13}"]
        if number == 0:
            parents.extend(f"old-{n}" for n in range(29, 40))
        producer = (
            {"kind": "human", "operator_id": "operator", "review_id": "review"}
            if number >= 41
            else {
                "kind": "processor",
                "processor_type": "identity",
                "implementation_id": "original",
            }
        )
        facts = {
            "recording_id": "recording-1",
            "source": {},
            "content_type": "visual_identities",
            "origin": "corrected" if number >= 41 else "processor",
            "input_revision_ids": parents,
            "producer": producer,
            "coverage": {},
        }
        copied_facts = {
            **facts,
            "input_revision_ids": [f"repair-0100-m5-{int(value[4:]):032x}" for value in parents],
            "producer": producer
            if number >= 41
            else {**producer, "implementation_id": "lineage-repair-copy.0100-m5-v1"},
        }
        _write(
            old_dir / "manifest.json",
            json.dumps({"revision_id": old, "content_sha256": old_digest, **facts}).encode(),
        )
        _write(
            new_dir / "manifest.json",
            json.dumps(
                {
                    "revision_id": new,
                    "content_sha256": new_digest,
                    "created_at": geometry["repair_at"],
                    **copied_facts,
                }
            ).encode(),
        )
        (geometry if number < 28 else identities)["records"].append(
            {
                "old": old,
                "new": new,
                "content_sha256": new_digest,
                **({"origin": "processor" if number < 41 else "corrected"} if number >= 28 else {}),
            }
        )
        if number < 29:
            selection_index = number % 18
            items.append(
                {
                    "revision_id": old,
                    "selection": (
                        f"selections/recording-{selection_index % 13}/"
                        f"selection-{selection_index}.json"
                    ),
                    "obsolete_or_missing_ancestors": (
                        [[f"old-{n}", "proposed-card-scene-data/v1"] for n in range(40, 53)]
                        if number == 0
                        else []
                    ),
                }
            )
    _write(
        root / "docs/reports/0100-M5_Lineage_Inventory.json", json.dumps({"items": items}).encode()
    )
    for number in range(18):
        path = f"selections/recording-{number % 13}/selection-{number}.json"
        checksum = _write(
            root / path,
            json.dumps(
                {
                    "revision": 1,
                    "selected_generated_revision_id": None,
                    "selected_completed_reference_revision_id": None,
                }
            ).encode(),
        )
        validation["selections"].append(
            {
                "path": path,
                "old_sha256": checksum,
                "old_revision": 1,
                "new_revision": 2,
                "selected_generated_revision_id": None,
                "selected_completed_reference_revision_id": None,
            }
        )
    for number in range(26):
        recording = f"recording-{number // 2}"
        stage_name = ("visible_cards", "visual_identities")[number % 2]
        path = root / "data/operations/pipeline-references" / recording / stage_name
        state = _write(path / "state.json", b"state")
        draft = _write(path / "draft.json", b"draft")
        drafts["records"].append(
            {
                "recording_id": recording,
                "stage": stage_name,
                "old_state_sha256": state,
                "old_draft_sha256": draft,
            }
        )
        validation["references"].append([recording, stage_name])
    validation["crop_checks"] = [{"old": f"old-{n}", "crop_count": 1} for n in range(29, 41)] + [
        {"old": "visual-identities-visual_identities-run-debcf221-570-attempt-1", "crop_count": 226}
    ]
    return geometry, identities, drafts, validation


def test_preflight_rejects_changed_source_or_draft(tmp_path: Path) -> None:
    reports = _fixture(tmp_path)
    repair.verify_sources(tmp_path, *reports)
    (tmp_path / "data/operations/pipeline/revisions/old-0/content.json").write_text("tampered")
    with pytest.raises(ValueError, match="source revision changed"):
        repair.verify_sources(tmp_path, *reports)
    _write(
        tmp_path / "data/operations/pipeline/revisions/old-0/content.json",
        json.dumps({"outcomes": [{"card_id": "card-0", "status": "classified"}]}).encode(),
    )
    (
        tmp_path / "data/operations/pipeline-references/recording-0/visible_cards/draft.json"
    ).write_text("edited")
    with pytest.raises(ValueError, match="reference changed"):
        repair.verify_sources(tmp_path, *reports)


def test_preflight_requires_complete_legacy_crop_check(tmp_path: Path) -> None:
    reports = _fixture(tmp_path)
    reports[3]["crop_checks"][-1]["crop_count"] = 225
    with pytest.raises(ValueError, match="legacy identity crop checks"):
        repair.verify_sources(tmp_path, *reports)


def test_preflight_rejects_obsolete_coverage_lineage(tmp_path: Path) -> None:
    reports = _fixture(tmp_path)
    old_manifest = tmp_path / "data/operations/pipeline/revisions/old-0/manifest.json"
    new_id = reports[0]["records"][0]["new"]
    new_manifest = tmp_path / "stage/pipeline/revisions" / new_id / "manifest.json"
    old_data = json.loads(old_manifest.read_bytes())
    new_data = json.loads(new_manifest.read_bytes())
    old_data["coverage"] = {"visible_card_revision_id": "old-40"}
    new_data["coverage"] = {"visible_card_revision_id": "old-40"}
    _write(old_manifest, json.dumps(old_data).encode())
    _write(new_manifest, json.dumps(new_data).encode())
    with pytest.raises(ValueError, match="replacement coverage changed"):
        repair.verify_sources(tmp_path, *reports)


def test_preflight_refuses_to_invalidate_saved_review_receipt(tmp_path: Path) -> None:
    reports = _fixture(tmp_path)
    path = tmp_path / "data/operations/frame-review-queues/0096-M4/receipts/one.json"
    _write(path, json.dumps({"recording_id": "recording-0"}).encode())
    with pytest.raises(ValueError, match="saved-review receipt needs explicit preservation"):
        repair.verify_sources(tmp_path, *reports)


def test_preflight_rejects_silently_selecting_another_result(tmp_path: Path) -> None:
    reports = _fixture(tmp_path)
    reports[3]["selections"][0]["selected_generated_revision_id"] = "unrelated-result"
    with pytest.raises(ValueError, match="changes the selected result"):
        repair.verify_sources(tmp_path, *reports)


def test_draft_copy_preserves_decisions_and_card_evidence() -> None:
    original = {
        "recording_id": "recording-1",
        "content_type": "visual_identities",
        "revision": 5,
        "coverage": None,
        "impact": [],
        "items": [
            {
                "item_id": "card-1",
                "base_item_id": None,
                "review_state": "accepted",
                "item": {
                    "candidates": [{"identity": "CLUBS_QUEEN", "score": 0.8}],
                    "crop_input_provenance": {
                        "source_revision_id": "old",
                        "input_kind": "reviewed_visible_card",
                    },
                },
            }
        ],
    }
    copied = json.loads(json.dumps(original))
    copied["revision"] = 6
    copied["items"][0]["item"]["crop_input_provenance"]["source_revision_id"] = "new"
    repair.verify_draft_decisions(original, copied)
    copied["items"][0]["review_state"] = "rejected"
    with pytest.raises(ValueError, match="review_state changed"):
        repair.verify_draft_decisions(original, copied)
    copied["items"][0]["review_state"] = "accepted"
    copied["items"][0]["item"]["candidates"][0]["score"] = 0.1
    with pytest.raises(ValueError, match="candidates changed"):
        repair.verify_draft_decisions(original, copied)


def test_draft_copy_requires_the_recorded_source_mapping() -> None:
    original = {
        "recording_id": "recording-1",
        "content_type": "visual_identities",
        "revision": 5,
        "source_revision_id": "old",
        "coverage": None,
        "impact": [],
        "items": [],
    }
    copied = {**original, "revision": 6, "source_revision_id": "new"}
    repair.verify_draft_lineage(original, copied, {"old": "new"}, {}, {}, {})
    copied["source_revision_id"] = "different"
    with pytest.raises(ValueError, match="incorrect source_revision_id"):
        repair.verify_draft_lineage(original, copied, {"old": "new"}, {}, {}, {})


def test_identity_copy_rejects_a_changed_classification() -> None:
    original = {
        "outcomes": [
            {
                "card_id": "card-1",
                "status": "classified",
                "candidates": [{"identity": "CLUBS_QUEEN", "score": 0.8}],
                "crop_input_provenance": {"source_revision_id": "old"},
            }
        ]
    }
    copied = json.loads(json.dumps(original))
    copied["outcomes"][0]["crop_input_provenance"]["source_revision_id"] = "new"
    repair.verify_revision_content("visual_identities", original, copied)
    copied["outcomes"][0]["candidates"][0]["score"] = 0.2
    with pytest.raises(ValueError, match="identity candidates changed"):
        repair.verify_revision_content("visual_identities", original, copied)


def _reference_fixture(repository: Path, stage: Path, recording_id: str) -> dict[str, object]:
    from doko_operations.pipeline_reference import PipelineReferenceDraft, PipelineReferenceState

    from dokodetector_backend.pipeline_reference_store import (
        PipelineReferenceStore,
        StoredPipelineReference,
    )

    def reference(revision: int) -> StoredPipelineReference:
        timestamp = "2026-10-30T12:00:00Z"
        state = PipelineReferenceState.from_mapping(
            {
                "schema_version": "pipeline-reference-state/v1",
                "recording_id": recording_id,
                "content_type": "events",
                "draft_revision": revision,
                "draft_state": "draft",
                "source_revision_id": None,
                "selected_completed_revision_id": None,
                "updated_at": timestamp,
            }
        )
        draft = PipelineReferenceDraft.from_mapping(
            {
                "schema_version": "pipeline-reference-draft/v2",
                "recording_id": recording_id,
                "content_type": "events",
                "revision": revision,
                "source_revision_id": None,
                "items": [],
                "coverage": None,
                "impact": [],
                "updated_at": timestamp,
            }
        )
        return StoredPipelineReference(state=state, draft=draft)

    original = PipelineReferenceStore(repository / "data/operations/pipeline-references")
    copied = PipelineReferenceStore(stage / "pipeline-references")
    for store, revision in ((original, 1), (copied, 2)):
        with store.locked(recording_id, "events"):
            store.write_locked(reference(revision))
    path = repository / "data/operations/pipeline-references" / recording_id / "events"
    return {
        "recording_id": recording_id,
        "stage": "events",
        "old_state_sha256": repair.digest(path / "state.json"),
        "old_draft_sha256": repair.digest(path / "draft.json"),
    }


def test_reference_repair_rolls_back_after_a_write_failure(tmp_path: Path, monkeypatch) -> None:
    from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore

    repository, stage = tmp_path / "repository", tmp_path / "stage"
    rows = [_reference_fixture(repository, stage, f"recording-{n}") for n in range(2)]
    original_write = PipelineReferenceStore.write_locked
    writes = 0

    def fail_second(store, reference):
        nonlocal writes
        if store.root == repository / "data/operations/pipeline-references":
            writes += 1
            if writes == 2:
                raise OSError("simulated failure")
        return original_write(store, reference)

    monkeypatch.setattr(PipelineReferenceStore, "write_locked", fail_second)
    with pytest.raises(OSError, match="simulated failure"):
        repair.apply_targets(
            repository,
            stage,
            {"records": rows},
            {"selections": []},
            tmp_path / "snapshot.tar.gz",
            lambda: None,
        )
    for row in rows:
        path = repository / "data/operations/pipeline-references" / row["recording_id"] / "events"
        assert repair.digest(path / "state.json") == row["old_state_sha256"]
        assert repair.digest(path / "draft.json") == row["old_draft_sha256"]
    assert (tmp_path / "snapshot.tar.gz").is_file()


def test_reference_repair_rejects_a_concurrent_edit(tmp_path: Path) -> None:
    repository, stage = tmp_path / "repository", tmp_path / "stage"
    row = _reference_fixture(repository, stage, "recording-0")
    path = repository / "data/operations/pipeline-references/recording-0/events/draft.json"
    changed = path.read_bytes() + b" "
    path.write_bytes(changed)
    with pytest.raises(ValueError):
        repair.apply_targets(
            repository,
            stage,
            {"records": [row]},
            {"selections": []},
            tmp_path / "snapshot.tar.gz",
            lambda: None,
        )
    assert path.read_bytes() == changed
    assert not (tmp_path / "snapshot.tar.gz").exists()


def test_selection_write_failure_restores_drafts_and_selection(tmp_path: Path, monkeypatch) -> None:
    repository, stage = tmp_path / "repository", tmp_path / "stage"
    row = _reference_fixture(repository, stage, "recording-0")
    old_path = repository / "data/operations/pipeline/selections/recording-0/events.json"
    staged_path = stage / "pipeline/selections/recording-0/events.json"
    for path, revision in ((old_path, 1), (staged_path, 2)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            canonical_pipeline_selection_bytes(
                PipelineSelection(
                    revision=revision,
                    recording_id="recording-0",
                    content_type="events",
                    selected_generated_revision_id=None,
                    selected_completed_reference_revision_id=None,
                    updated_at="2026-11-06T00:00:00Z",
                )
            )
        )
    old_bytes = old_path.read_bytes()
    selected = {
        "path": old_path.relative_to(repository).as_posix(),
        "old_sha256": hashlib.sha256(old_bytes).hexdigest(),
        "old_revision": 1,
        "new_revision": 2,
        "selected_generated_revision_id": None,
        "selected_completed_reference_revision_id": None,
    }
    original_write = repair._write_exact
    failed = False

    def fail_selection(path, content):
        nonlocal failed
        if path == old_path and not failed:
            failed = True
            raise OSError("simulated selection failure")
        return original_write(path, content)

    monkeypatch.setattr(repair, "_write_exact", fail_selection)
    with pytest.raises(OSError, match="simulated selection failure"):
        repair.apply_targets(
            repository,
            stage,
            {"records": [row]},
            {"selections": [selected]},
            tmp_path / "snapshot.tar.gz",
            lambda: None,
        )
    draft = repository / "data/operations/pipeline-references/recording-0/events/draft.json"
    assert repair.digest(draft) == row["old_draft_sha256"]
    assert old_path.read_bytes() == old_bytes


def test_reference_repair_saves_original_and_applies_copy(tmp_path: Path) -> None:
    import tarfile

    from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore

    repository, stage = tmp_path / "repository", tmp_path / "stage"
    row = _reference_fixture(repository, stage, "recording-0")
    draft = repository / "data/operations/pipeline-references/recording-0/events/draft.json"
    before = draft.read_bytes()
    snapshot = tmp_path / "snapshot.tar.gz"
    repair.apply_targets(
        repository, stage, {"records": [row]}, {"selections": []}, snapshot, lambda: None
    )
    reference = PipelineReferenceStore(repository / "data/operations/pipeline-references").require(
        "recording-0", "events"
    )
    assert reference.draft.revision == 2
    with tarfile.open(snapshot, "r:gz") as archive:
        member = archive.extractfile(draft.relative_to(repository).as_posix())
        assert member is not None and member.read() == before


def test_missing_legacy_frame_evidence_requires_matching_cache_bytes(tmp_path: Path) -> None:
    from doko_operations.derived_view import DerivedViewCache, ExactEventRequest, frame_cache_key
    from doko_operations.pipeline_data import RecordingVideoSource

    repository, stage = tmp_path / "repository", tmp_path / "stage"
    old = "visual-identities-visual_identities-run-debcf221-570-attempt-1"
    old_dir = repository / "data/operations/pipeline/revisions" / old
    source = {
        "schema_version": "recording-video/v1",
        "recording_id": "recording-1",
        "relative_path": "data/intake/recordings/recording-1/video.mov",
        "video_sha256": "a" * 64,
        "byte_length": 10,
        "duration_us": 10_000_000,
    }
    expected = {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "a" * 64,
        "requested_time_us": 1_000,
        "frame_index": 1,
        "presentation_timestamp_us": 1_000,
        "width": 100,
        "height": 100,
        "decoder_version": "fixture/v1",
        "transform_version": "fixture/v1",
        "output_encoding": "jpeg",
        "content_type": "image/jpeg",
        "image_sha256": "b" * 64,
        "policy": "exact-event/v1",
    }
    actual_bytes = b"different jpeg bytes"
    observed = {**expected, "image_sha256": hashlib.sha256(actual_bytes).hexdigest()}
    _write(old_dir / "manifest.json", json.dumps({"source": source}).encode())
    _write(
        old_dir / "content.json",
        json.dumps({"outcomes": [{"card_id": "card-1", "frame_identity": expected}]}).encode(),
    )
    request = ExactEventRequest(
        source=RecordingVideoSource.from_mapping(source),
        requested_time_us=1_000,
        output_encoding="jpeg",
    )
    key = frame_cache_key(request, decoder_version="fixture/v1", transform_version="fixture/v1")
    cache = DerivedViewCache(stage / "runtime/pipeline/derived-views")
    cache.write(
        key,
        {
            "schema_version": "derived-view-cache/v1",
            "cache_key": key,
            "view_kind": "exact-event/v1",
            "identity": observed,
        },
        actual_bytes,
    )
    row = {
        "missing_evidence": {
            "reason": "exact_frame_digest_mismatch",
            "card_id": "card-1",
            "expected_frame": expected,
            "observed_frame": observed,
            "cache_key": key,
        }
    }
    repair.verify_missing_legacy_evidence(repository, stage, row)
    (cache.path(key) / "content.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="resolved frame bytes"):
        repair.verify_missing_legacy_evidence(repository, stage, row)


def test_publish_copy_records_a_repair_run_without_inference(tmp_path: Path) -> None:
    from test_pipeline_store import processor_producer, request, revision

    from dokodetector_backend.pipeline_store import PipelineRevisionStore, ProcessorRunStore

    stage, target = tmp_path / "stage", tmp_path / "target"
    source_store = PipelineRevisionStore(stage)
    target_store = PipelineRevisionStore(target)
    input_revision = revision(revision_id="input-1", producer=processor_producer("import-1"))
    source_store.publish(input_revision)
    target_store.publish(input_revision)
    run_store = ProcessorRunStore(stage, revision_store=source_store)
    run_request = request("copy-run").to_mapping()
    run_request["input_revision_ids"] = ["input-1"]
    run_request["configuration"] = {"lineage_repair": {"inference_performed": False}}
    run_store.create(run_request)
    run_store.start("copy-run")
    output = revision(
        revision_id="copy-output",
        producer=processor_producer("copy-run"),
        input_revision_ids=["input-1"],
    )
    source_store.publish(output)
    run_store.complete("copy-run", ["copy-output"])

    repair.publish_revisions(target, stage, [{"new": "copy-output"}])
    repair.publish_revisions(target, stage, [{"new": "copy-output"}])
    copied = target_store.require("copy-output")
    copied_run = ProcessorRunStore(target, revision_store=target_store).require("copy-run")
    assert copied.manifest == output.manifest
    assert copied_run.state.output_revision_ids == ("copy-output",)
    assert copied_run.request.configuration["lineage_repair"]["inference_performed"] is False
