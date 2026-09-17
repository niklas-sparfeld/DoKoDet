from __future__ import annotations

from pathlib import Path

from doko_operations.dinov3_identity_campaign import (
    DINOV3_REQUIRED_CROP_POLICY,
    _analyze_recording,
    build_dinov3_identity_preflight,
    render_dinov3_identity_preflight_human,
)

DIGEST = "a" * 64


def _frame() -> dict[str, object]:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": DIGEST,
        "requested_time_us": 2,
        "frame_index": 0,
        "presentation_timestamp_us": 2,
        "width": 100,
        "height": 100,
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "image_sha256": DIGEST,
        "policy": "exact-event/v1",
    }


def _geometry() -> dict[str, object]:
    return {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
    }


def _visible_content() -> dict[str, object]:
    return {
        "schema_version": "visible-card-data/v1",
        "outcomes": [
            {
                "event_id": "event-01",
                "frame_identity": _frame(),
                "status": "detected",
                "candidates": [
                    {
                        "card_id": "card-01",
                        "geometry": _geometry(),
                        "normalization": {
                            "width": 64,
                            "height": 64,
                            "policy_id": "normalize.v1",
                        },
                        "side": "unknown",
                    }
                ],
                "ignored_regions": [],
                "error": None,
            }
        ],
    }


def _identity_content(*, status: str) -> dict[str, object]:
    crop = {
        "schema_version": "visible-region-crop/v1",
        "status": "usable",
        "frame_identity": _frame(),
        "geometry": _geometry(),
        "pixel_bounds": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
        "crop_policy": DINOV3_REQUIRED_CROP_POLICY,
        "output_encoding": "png",
        "content_type": "image/png",
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "image_sha256": DIGEST,
        "unusable_reason": None,
    }
    return {
        "schema_version": "visual-identity-data/v1",
        "outcomes": [
            {
                "card_id": "card-01",
                "frame_identity": _frame(),
                "geometry": _geometry(),
                "crop_identity": crop,
                "classifier": {
                    "provider": "human-reference",
                    "implementation": {"name": "maintained-reference", "version": "v1"},
                    "model": {"name": "human-decision", "version": "v1"},
                },
                "status": status,
                "candidates": [] if status == "face_down" else [{"identity": "HEARTS_QUEEN"}],
                "unusable_reason": None,
                "error": None,
            }
        ],
    }


def _revision(revision_id: str, content_type: str, content: dict[str, object]) -> dict[str, object]:
    return {
        "manifest": {
            "revision_id": revision_id,
            "recording_id": "recording-01",
            "content_type": content_type,
            "origin": "corrected",
            "producer": {"kind": "human"},
            "source": {"video_sha256": DIGEST},
        },
        "content": content,
    }


def test_preflight_is_read_only_and_reports_missing_current_store(tmp_path: Path) -> None:
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    report = build_dinov3_identity_preflight(tmp_path)
    repeated = build_dinov3_identity_preflight(tmp_path)

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert report["read_only"] is True
    assert report["preflight_state"] == "blocked"
    assert report["manifest_digest"] == repeated["manifest_digest"]
    assert any(
        "selected visual-identity split version is missing" in gap
        for gap in report["coverage_gaps"]
    )
    assert any("DINOv3 identity config is missing" in gap for gap in report["coverage_gaps"])
    assert "state: blocked" in render_dinov3_identity_preflight_human(report)


def test_relative_split_path_is_resolved_from_repository(tmp_path: Path) -> None:
    split = tmp_path / "data" / "operations" / "selected-split.json"
    split.parent.mkdir(parents=True)
    split.write_text(
        '{"split_version_id":"v1","split_version_digest":"%s",'
        '"partitions":{"train":["train-01"],"validation":["val-01"]}}' % ("b" * 64),
        encoding="utf-8",
    )

    report = build_dinov3_identity_preflight(
        tmp_path, split_path="data/operations/selected-split.json"
    )

    assert report["split"]["active_path"] == "data/operations/selected-split.json"
    assert not any("data/data/operations" in gap for gap in report["coverage_gaps"])


def test_face_down_outcome_is_excluded_with_exact_revision_lineage() -> None:
    visible_id = "visible-revision-01"
    identity_id = "identity-revision-01"
    recording = {
        "recording_id": "recording-01",
        "source_sha256": DIGEST,
        "source_groups": {"session_id": "session-01"},
    }
    visible_reference = {"selected_revision_id": visible_id}
    identity_reference = {"selected_revision_id": identity_id}
    revisions = {
        visible_id: _revision(visible_id, "visible_cards", _visible_content()),
        identity_id: _revision(
            identity_id,
            "visual_identities",
            _identity_content(status="face_down"),
        ),
    }

    report, rows, gaps = _analyze_recording(
        recording,
        "train",
        visible_reference,
        identity_reference,
        revisions,
        Path("."),
    )

    assert rows == []
    assert gaps == []
    assert report["included_count"] == 0
    assert report["outcome_counts"] == {"face_down": 1}
    assert report["excluded"][0]["identity_revision_id"] == identity_id
    assert report["excluded"][0]["status"] == "face_down"
