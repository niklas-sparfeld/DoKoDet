from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from table_evidence_analyzer.cards import CARD_IDENTITIES

from doko_operations.derived_view import (
    DEFAULT_FRAME_TRANSFORM_VERSION,
    ResolvedFrame,
    resolve_visible_region_crop,
)
from doko_operations.visual_identity_materialization import (
    materialize_reviewed_visual_identity_crops,
)


def _frame() -> ResolvedFrame:
    return ResolvedFrame(
        requested_time_us=10,
        frame_index=0,
        presentation_timestamp_us=10,
        source_video_sha256=hashlib.sha256(b"video").hexdigest(),
        width=32,
        height=32,
        decoder_version="fixture-decoder/v1",
        transform_version=DEFAULT_FRAME_TRANSFORM_VERSION,
        output_encoding="png",
        image_bytes=b"P6\n32 32\n255\n" + bytes([10, 20, 30]) * (32 * 32),
    )


def _geometry(x_max: int = 900) -> dict[str, object]:
    return {
        "kind": "reviewed-visible-region/v1",
        "visible_region": {
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": x_max, "y": 100},
                    {"x": x_max, "y": 900},
                    {"x": 100, "y": 900},
                ]
            ]
        },
    }


def _recording(
    status: str = "face_down", target_identity: str = "HEARTS_QUEEN"
) -> tuple[dict[str, object], ResolvedFrame]:
    frame = _frame()
    geometry = _geometry()
    frame_identity = frame.identity_mapping()
    visible = {
        "schema_version": "visible-card-data/v1",
        "outcomes": [
            {
                "event_id": "event-01",
                "frame_identity": frame_identity,
                "status": "detected",
                "candidates": [
                    {
                        "card_id": "card-01",
                        "geometry": geometry,
                        "side": "face_down" if status == "face_down" else "face_up",
                    }
                ],
                "ignored_regions": [],
                "error": None,
            }
        ],
    }
    target = "FACE_DOWN" if status == "face_down" else target_identity
    crop = resolve_visible_region_crop(
        frame, geometry, crop_policy="oracle_visible_region", output_encoding="ppm"
    )
    identity = {
        "schema_version": "visual-identity-data/v2",
        "outcomes": [
            {
                "card_id": "card-01",
                "frame_identity": frame_identity,
                "geometry": geometry,
                "crop_identity": {
                    "schema_version": "visible-region-crop/v1",
                    "status": "usable",
                    "frame_identity": frame_identity,
                    "geometry": geometry,
                    "crop_policy": "oracle_visible_region",
                    "image_sha256": hashlib.sha256(crop.image_bytes or b"").hexdigest(),
                },
                "annotation_provenance": {
                    "visible_card_revision_id": "visible-01",
                    "visible_card_revision_digest": "a" * 64,
                    "card_id": "card-01",
                    "frame_identity": frame_identity,
                    "geometry_digest": hashlib.sha256(
                        json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                },
                "status": status,
                "candidates": [] if status == "face_down" else [{"identity": target}],
                "unusable_reason": None,
                "error": None,
            }
        ],
    }
    visible_digest = hashlib.sha256(
        json.dumps(visible, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    identity["outcomes"][0]["annotation_provenance"]["visible_card_revision_digest"] = (
        visible_digest
    )
    identity_digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        {
            "recording_id": "recording-01",
            "source_lineage_group": {"session_id": "session-01"},
            "visible_card_revision": {
                "revision_id": "visible-01",
                "content_digest": visible_digest,
                "content": visible,
            },
            "visual_identity_revision": {
                "revision_id": "identity-01",
                "content_digest": identity_digest,
                "content": identity,
            },
        },
        frame,
    )


def test_materializes_reviewed_back_and_identity_with_masks_and_stable_digests(
    tmp_path: Path,
) -> None:
    back, frame = _recording("face_down")
    face_up_recordings = []
    for index, identity in enumerate(CARD_IDENTITIES):
        recording, _ = _recording("classified", identity)
        recording["recording_id"] = f"recording-{index + 2:02}"
        recording["visible_card_revision"]["content"]["outcomes"][0]["candidates"][0]["card_id"] = (
            f"card-{index + 2:02}"
        )
        visible_content = recording["visible_card_revision"]["content"]
        visible_digest = hashlib.sha256(
            json.dumps(
                visible_content,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        recording["visible_card_revision"]["content_digest"] = visible_digest
        recording["visual_identity_revision"]["content"]["outcomes"][0]["card_id"] = (
            f"card-{index + 2:02}"
        )
        recording["visual_identity_revision"]["content"]["outcomes"][0]["annotation_provenance"][
            "card_id"
        ] = f"card-{index + 2:02}"
        recording["visual_identity_revision"]["content"]["outcomes"][0]["annotation_provenance"][
            "visible_card_revision_digest"
        ] = visible_digest
        identity_content = recording["visual_identity_revision"]["content"]
        recording["visual_identity_revision"]["content_digest"] = hashlib.sha256(
            json.dumps(
                identity_content,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        face_up_recordings.append(recording)
    out1, out2 = tmp_path / "first", tmp_path / "second"

    def resolver(_identity: Mapping[str, object]) -> ResolvedFrame:
        return frame

    recordings = [back, *face_up_recordings]
    first = materialize_reviewed_visual_identity_crops(recordings, out1, resolver)
    second = materialize_reviewed_visual_identity_crops(recordings, out2, resolver)

    assert {row["target"] for row in first["samples"]} == {*CARD_IDENTITIES, "FACE_DOWN"}
    assert len(first["target_classes"]) == 25
    assert first["back_design_support"] == {}
    assert first["back_design_unspecified_recordings"] == ["recording-01"]
    assert first["manifest_digest"] == second["manifest_digest"]
    for row in first["samples"]:
        assert (out1 / row["crop_path"]).read_bytes() == (out2 / row["crop_path"]).read_bytes()
        mask_bytes = (out1 / row["mask_path"]).read_bytes()
        assert mask_bytes.startswith(b"P5\n")
        assert mask_bytes == (out2 / row["mask_path"]).read_bytes()


def test_excludes_wrong_frame_stale_geometry_unreadable_and_piles(tmp_path: Path) -> None:
    recording, frame = _recording("face_down")
    outcomes = recording["visual_identity_revision"]["content"]["outcomes"]
    outcomes[0]["frame_identity"] = {"wrong": "frame"}
    recording["visual_identity_revision"]["content_digest"] = hashlib.sha256(
        json.dumps(
            recording["visual_identity_revision"]["content"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    second, _ = _recording("face_down")
    second["recording_id"] = "recording-02"
    second["visual_identity_revision"]["content"]["outcomes"][0]["geometry"] = _geometry(800)
    second["visual_identity_revision"]["content"]["outcomes"][0]["annotation_provenance"][
        "geometry_digest"
    ] = hashlib.sha256(
        json.dumps(_geometry(800), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    second["visual_identity_revision"]["content_digest"] = hashlib.sha256(
        json.dumps(
            second["visual_identity_revision"]["content"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    third, _ = _recording("unusable")
    third["recording_id"] = "recording-03"
    report = materialize_reviewed_visual_identity_crops(
        [recording, second, third], tmp_path / "out", lambda _identity: frame
    )
    assert report["samples"] == []
    assert {item["reason"] for item in report["exclusions"]} >= {
        "wrong_frame",
        "stale_geometry",
        "unreadable_evidence",
    }


def test_source_frame_resolver_must_return_exact_identity(tmp_path: Path) -> None:
    recording, _frame_value = _recording()
    other = _frame()
    altered = ResolvedFrame(
        requested_time_us=11,
        frame_index=0,
        presentation_timestamp_us=11,
        source_video_sha256=other.source_video_sha256,
        width=other.width,
        height=other.height,
        decoder_version=other.decoder_version,
        transform_version=other.transform_version,
        output_encoding="png",
        image_bytes=other.image_bytes,
    )
    report = materialize_reviewed_visual_identity_crops(
        [recording], tmp_path / "out", lambda _identity: altered
    )
    assert report["samples"] == []
    assert report["exclusions"][0]["reason"] == "crop_materialization_failed"
