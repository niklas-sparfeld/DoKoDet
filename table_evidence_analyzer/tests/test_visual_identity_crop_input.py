from __future__ import annotations

from copy import deepcopy

import pytest

from table_evidence_analyzer.visual_identity_crop_input import (
    ReviewedVirtualCardLineage,
    VisualIdentityCropInput,
    VisualIdentityCropInputError,
    VisualIdentityCropInputItem,
    canonical_visual_identity_crop_input_bytes,
    parse_visual_identity_crop_input_bytes,
    validate_crop_policy_compatibility,
)

VIDEO_DIGEST = "a" * 64


def _frame(index: int, *, video_digest: str = VIDEO_DIGEST) -> dict[str, object]:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": video_digest,
        "requested_time_us": 500_000 + index,
        "frame_index": index,
        "presentation_timestamp_us": 500_000 + index,
        "width": 640,
        "height": 360,
        "decoder_version": "ffmpeg/test",
        "transform_version": "ffmpeg-mjpeg/test",
        "output_encoding": "jpeg",
        "content_type": "image/jpeg",
        "image_sha256": ("b" if index == 0 else "c") * 64,
        "policy": "exact-event/v1",
    }


def _geometry(kind: str) -> dict[str, object]:
    value: dict[str, object] = {
        "kind": kind,
        "visible_region": {
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 900, "y": 100},
                    {"x": 900, "y": 900},
                    {"x": 100, "y": 900},
                ]
            ]
        },
    }
    if kind == "reviewed-visible-region/v1":
        value = {
            "kind": kind,
            "visible_region": {
                "polygons": [
                    [
                        {"x": 100, "y": 100},
                        {"x": 900, "y": 100},
                        {"x": 900, "y": 900},
                        {"x": 100, "y": 900},
                    ]
                ]
            },
        }
    return value


def _item(
    card_id: str,
    frame_index: int,
    *,
    geometry_kind: str = "visible-region/v1",
    side: str = "face_up",
    identity_usable: bool = True,
    failure_tags: list[str] | None = None,
    video_digest: str = VIDEO_DIGEST,
) -> dict[str, object]:
    return {
        "card_id": card_id,
        "frame_identity": _frame(frame_index, video_digest=video_digest),
        "geometry": _geometry(geometry_kind),
        "side": side,
        "identity_usable": identity_usable,
        "failure_tags": [] if failure_tags is None else failure_tags,
    }


def _virtual_lineage() -> dict[str, str]:
    return {
        "card_scene_revision_id": "scene-revision-01",
        "card_scene_digest": "d" * 64,
        "calibration_revision_id": "calibration-revision-01",
        "calibration_digest": "e" * 64,
        "scene_derivation_receipt_digest": "f" * 64,
        "derived_visible_region_digest": "1" * 64,
    }


def _mapping(kind: str = "gemini_polygon") -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "visual-identity-crop-input/v1",
        "input_kind": kind,
        "recording_id": "recording-01",
        "accepted_video_sha256": VIDEO_DIGEST,
        "accepted_video_byte_length": 1234,
        "source_revision_id": f"{kind}-revision-01",
        "source_revision_digest": "2" * 64,
        "source_view_digest": "3" * 64,
        "items": [_item("card-01", 0)],
        "virtual_card_lineage": None,
        "manifest_digest": "0" * 64,
    }
    if kind == "rfdetr_segment":
        value["items"] = [
            _item("card-01", 0),
            _item(
                "card-02", 1, side="face_down", identity_usable=False, failure_tags=["face_down"]
            ),
        ]
    if kind == "reviewed_virtual_card":
        value["items"] = [
            _item(
                "card-01",
                0,
                geometry_kind="reviewed-visible-region/v1",
            )
        ]
        value["virtual_card_lineage"] = _virtual_lineage()
    # The contract computes the digest from the manifest.  Build once without a
    # supplied digest, then freeze the resulting canonical mapping.
    value["manifest_digest"] = None
    built = VisualIdentityCropInput(
        input_kind=kind,
        recording_id="recording-01",
        accepted_video_sha256=VIDEO_DIGEST,
        accepted_video_byte_length=1234,
        source_revision_id=f"{kind}-revision-01",
        source_revision_digest="2" * 64,
        source_view_digest="3" * 64,
        items=tuple(
            VisualIdentityCropInputItem.from_mapping(item, f"items[{index}]")
            for index, item in enumerate(value["items"])
        ),
        virtual_card_lineage=(
            None
            if value["virtual_card_lineage"] is None
            else ReviewedVirtualCardLineage.from_mapping(value["virtual_card_lineage"])
        ),
    )
    return built.to_mapping()


@pytest.mark.parametrize("kind", ["gemini_polygon", "rfdetr_segment", "reviewed_virtual_card"])
def test_supported_inputs_round_trip_with_stable_manifest_digest(kind: str) -> None:
    raw = _mapping(kind)
    first = canonical_visual_identity_crop_input_bytes(raw)
    second = canonical_visual_identity_crop_input_bytes(
        parse_visual_identity_crop_input_bytes(first)
    )

    assert first == second
    parsed = parse_visual_identity_crop_input_bytes(first)
    assert parsed.to_mapping()["manifest_digest"] == parsed.computed_manifest_digest
    if kind == "reviewed_virtual_card":
        assert parsed.virtual_card_lineage is not None
        assert parsed.items[0].geometry.to_mapping()["kind"] == "reviewed-visible-region/v1"


def test_contract_keeps_crop_policy_separate_and_checks_geometry_compatibility() -> None:
    value = VisualIdentityCropInput.from_mapping(_mapping("reviewed_virtual_card"))

    validate_crop_policy_compatibility(value, "oracle_visible_region")

    with pytest.raises(VisualIdentityCropInputError, match="incompatible"):
        validate_crop_policy_compatibility(value, "predicted_visible_region")


def test_unsupported_input_kind_is_rejected_before_queueing() -> None:
    value = _mapping("reviewed_virtual_card")
    value["input_kind"] = "unsupported"
    with pytest.raises(VisualIdentityCropInputError, match="unsupported"):
        VisualIdentityCropInput.from_mapping(value)


def test_duplicate_frame_card_ids_are_rejected_before_queueing() -> None:
    value = _mapping("reviewed_virtual_card")
    value["items"].append(deepcopy(value["items"][0]))
    with pytest.raises(VisualIdentityCropInputError, match="duplicate"):
        VisualIdentityCropInput.from_mapping(value)


def test_changed_source_bytes_are_rejected_before_queueing() -> None:
    value = _mapping("reviewed_virtual_card")
    value["items"][0]["frame_identity"]["source_video_sha256"] = "4" * 64
    with pytest.raises(VisualIdentityCropInputError, match="accepted recording video"):
        VisualIdentityCropInput.from_mapping(value)


def test_missing_virtual_card_lineage_is_rejected_before_queueing() -> None:
    value = _mapping("reviewed_virtual_card")
    value["virtual_card_lineage"] = None
    with pytest.raises(VisualIdentityCropInputError, match="lineage"):
        VisualIdentityCropInput.from_mapping(value)


def test_changed_manifest_digest_is_rejected_before_queueing() -> None:
    value = _mapping("reviewed_virtual_card")
    value["manifest_digest"] = "4" * 64
    with pytest.raises(VisualIdentityCropInputError, match="manifest_digest"):
        VisualIdentityCropInput.from_mapping(value)


def test_face_down_and_unusable_items_remain_explicit() -> None:
    raw = _mapping("rfdetr_segment")
    parsed = VisualIdentityCropInput.from_mapping(raw)

    assert parsed.items[1].side == "face_down"
    assert parsed.items[1].identity_usable is False
    assert parsed.items[1].failure_tags == ("face_down",)
