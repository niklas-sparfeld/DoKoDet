from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts/build_0086_m5_campaign_handoff.py"
_SPEC = importlib.util.spec_from_file_location("build_0086_m5_campaign_handoff", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_0086_m5_campaign_handoff = _MODULE.build_0086_m5_campaign_handoff


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _write_json(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(encoded)
    return encoded


def _fixture(tmp_path: Path) -> Path:
    repository = tmp_path
    recording_id = "cardeventnet-IMG_0001"
    revision_id = "reference-visible_cards-current"
    content = {
        "schema_version": "visible-card-data/v2",
        "outcomes": [
            {
                "event_id": "event-1",
                "frame_identity": {"requested_time_us": 10, "source_video_sha256": "a" * 64},
                "status": "detected",
                "candidates": [{"card_id": "card-1", "geometry": {"box": [1, 2, 3, 4]}}],
                "pile_regions": [
                    {
                        "pile_id": "pile-1",
                        "normalization": {"policy_id": "full-frame-0-1000/v1"},
                        "grouped_candidates": ["candidate-1"],
                        "grouped_card_states": [],
                        "grouped_scene_decision": None,
                        "source_candidates": ["candidate-1"],
                    }
                ],
            }
        ],
    }
    _write_json(
        repository / "data/operations/pipeline/revisions" / revision_id / "content.json", content
    )
    manifest = {"revision_id": revision_id, "recording_id": recording_id}
    _write_json(
        repository / "data/operations/pipeline/revisions" / revision_id / "manifest.json", manifest
    )
    state = {"selected_completed_revision_id": revision_id}
    state_bytes = _write_json(
        repository
        / "data/operations/pipeline-references"
        / recording_id
        / "visible_cards/state.json",
        state,
    )
    draft = {
        "items": [{"item_id": "frame-1", "review_state": "accepted", "item": {"pile_regions": []}}],
        "coverage": {"frames": [{"decision": "cards_and_piles"}]},
    }
    _write_json(
        repository
        / "data/operations/pipeline-references"
        / recording_id
        / "visible_cards/draft.json",
        draft,
    )
    classes = [f"CLASS_{index}" for index in range(20)] + ["FACE_DOWN"]
    support = {name: 1 for name in classes}
    readiness = {
        "identity_review_complete": True,
        "target_classes": classes,
        "recordings_still_needing_human_decisions": [],
        "back_design_unspecified_recordings": [],
        "exclusions": [],
        "recordings": [
            {
                "recording_id": recording_id,
                "source_group": {"source_group_id": "group-1"},
                "visible_card_revision": {
                    "revision_id": revision_id,
                    "content_sha256": _digest(
                        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                    ),
                    "manifest_sha256": _digest(
                        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
                    ),
                    "state_sha256": _digest(state_bytes),
                },
                "visual_identity_revision": {"revision_id": "identity-1"},
                "positive_crop_count": 21,
                "class_support": support,
            }
        ],
    }
    readiness["report_sha256"] = _digest(_canonical(readiness))
    _write_json(repository / "docs/reports/0086-M5_Visual_Identity_Readiness.json", readiness)
    audit = {
        "report_sha256": "c" * 64,
        "detection_handoff_sha256": "d" * 64,
        "detection_handoff_summary": {"eligible_recording_count": 1},
        "policy": {"source_bytes_verified": False},
        "recordings": [
            {
                "recording_id": recording_id,
                "disposition": "active",
                "detection_handoff_eligible": True,
                "selected_completed_revision_id": revision_id,
                "accepted_items_without_explicit_pile_coverage": [],
                "unfinished_item_ids": [],
            }
        ],
    }
    _write_json(repository / "docs/reports/0086-M4_Geometry_Review_Audit.json", audit)
    _write_json(
        repository / "docs/reports/0086-M4_Recording_Dispositions.json",
        {"receipt_sha256": "e" * 64, "recordings": {}},
    )
    return repository


def test_campaign_handoff_binds_exact_refs_and_explicit_pile_review(tmp_path: Path) -> None:
    report = build_0086_m5_campaign_handoff(_fixture(tmp_path))
    repeated = build_0086_m5_campaign_handoff(tmp_path)

    assert report == repeated
    assert report["handoff_complete"] is True
    assert report["summary"]["supported_class_count"] == 21
    assert report["summary"]["pile_target_count"] == 1
    assert report["summary"]["pile_review_coverage_decision_counts"] == {"cards_and_piles": 1}
    assert report["pile_policy"]["grouping_provenance"][0]["grouped_candidates"] == ["candidate-1"]
    assert report["handoff_sha256"] == _digest(
        _canonical({key: value for key, value in report.items() if key != "handoff_sha256"})
    )


def test_campaign_handoff_rejects_accepted_geometry_without_pile_coverage(tmp_path: Path) -> None:
    repository = _fixture(tmp_path)
    draft_path = (
        repository
        / "data/operations/pipeline-references/cardeventnet-IMG_0001/visible_cards/draft.json"
    )
    draft = json.loads(draft_path.read_text())
    draft["items"][0]["item"].pop("pile_regions")
    draft_path.write_text(json.dumps(draft))

    with pytest.raises(ValueError, match="explicit pile coverage"):
        build_0086_m5_campaign_handoff(repository)
