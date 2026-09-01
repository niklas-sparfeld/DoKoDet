from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from table_evidence_analyzer.visible_card_prompt_pilot import PromptPilotFrame, run_prompt_pilot
from table_evidence_analyzer.visible_card_review import (
    DerivedBox,
    IdentityUsability,
    ReviewedVisibleCard,
    VisibleRegion,
)
from table_evidence_analyzer.visible_card_review_freeze import (
    VISIBLE_CARD_CROP_POLICY_SCHEMA,
    VISIBLE_CARD_PARTITION_SCHEMA,
    VisibleCardReviewFreezeError,
    apply_visible_card_crop_policy,
    freeze_visible_card_review_data,
    frozen_visible_card_crop_policy,
    load_frozen_visible_card_review_data,
    load_visible_card_partition_manifest,
)
from table_evidence_analyzer.visible_card_review_workflow import (
    build_visible_card_review_queue,
    finalize_visible_card_review,
    record_card_action,
    record_frame_review,
)
from table_evidence_analyzer.visible_cards import (
    FakeVisibleCardProvider,
    VisibleCardRequest,
    load_run_artifact,
    write_run_artifact,
)


def _image(path: Path, colour: tuple[int, int, int] = (20, 40, 60)) -> None:
    image = Image.new("RGB", (20, 20), colour)
    output = BytesIO()
    image.save(output, format="JPEG")
    path.write_bytes(output.getvalue())


def _prediction() -> dict:
    return {
        "cards": [
            {
                "box_2d": {"y_min": 100, "x_min": 100, "y_max": 800, "x_max": 800},
                "polygon": [
                    {"x": 100, "y": 100},
                    {"x": 800, "y": 100},
                    {"x": 800, "y": 500},
                    {"x": 500, "y": 500},
                    {"x": 500, "y": 800},
                    {"x": 100, "y": 800},
                ],
                "side": "face_up",
                "label": "visible card",
            }
        ]
    }


def _reviewed_card() -> ReviewedVisibleCard:
    prediction = _prediction()["cards"][0]
    region = VisibleRegion.from_mapping({"polygons": [prediction["polygon"]]})
    return ReviewedVisibleCard(
        card_id="card-001",
        visible_region=region,
        derived_box=DerivedBox.from_visible_region(region),
        identity_usability=IdentityUsability(True, "sufficient_identity_evidence"),
        side="face_up",
    )


def _queue(tmp_path: Path) -> Path:
    artifacts = []
    lineage = {}
    for index in range(6):
        package_id = f"package-{index:03d}"
        image = tmp_path / f"{package_id}.jpg"
        _image(image, (20 + index, 40, 60))
        request = VisibleCardRequest(
            package_id=package_id,
            frame_part_name="frame_00",
            target_offset_ms=0,
            image_bytes=image.read_bytes(),
            width=20,
            height=20,
            provider="fake",
        )
        result = FakeVisibleCardProvider({request.image_sha256: _prediction()}).propose(request)
        result_path = tmp_path / f"{package_id}.json"
        write_run_artifact(request, result, result_path, image=str(image))
        artifact = load_run_artifact(result_path)
        artifact["artifact_path"] = str(result_path)
        item_id = f"{package_id}:frame_00"
        lineage[item_id] = {
            "package_id": package_id,
            "frame_part_name": "frame_00",
            "target_offset_ms": 0,
            "image": str(image),
            "frame_sha256": request.image_sha256,
            "source_asset_id": f"asset-{index:03d}",
            "source_lineage_group": f"group-{index // 2}",
            "source_asset_sha256": None,
            "width": 20,
            "height": 20,
        }
        artifacts.append(artifact)
    queue_path = tmp_path / "queue.json"
    build_visible_card_review_queue(
        artifacts,
        queue_path,
        run_id="review-run",
        lineage_by_item=lineage,
    )
    for index in range(6):
        item_id = f"package-{index:03d}:frame_00"
        if index >= 4:
            record_frame_review(
                queue_path,
                item_id,
                "BAD",
                reviewer="operator",
                empty_frame=index == 4,
                failure_tags=("occlusion",) if index == 5 else (),
            )
            continue
        record_frame_review(
            queue_path,
            item_id,
            "GOOD",
            reviewer="operator",
            empty_frame=False,
        )
        record_card_action(
            queue_path,
            item_id,
            {
                "card_id": "card-001",
                "action": "accepted",
                "proposal_index": 0,
                "reviewed_card": _reviewed_card().to_mapping(),
            },
            reviewer="operator",
        )
        finalize_visible_card_review(queue_path, item_id, reviewer="operator")
    return queue_path


def _pilot(tmp_path: Path) -> Path:
    frames = []
    for index in range(20):
        image = tmp_path / f"pilot-{index:03d}.jpg"
        _image(image, (10 + index, 20, 30))
        frames.append(
            PromptPilotFrame(
                package_id=f"pilot-{index:03d}",
                frame_part_name="frame_00",
                image=image,
                source_lineage_group=f"pilot-group-{index}",
            )
        )
    output = tmp_path / "pilot.json"
    run_prompt_pilot(
        frames,
        FakeVisibleCardProvider(),
        output=output,
        selected_request_version="visible-card-request/v2",
        selection_reason="The visible-region and tight-box wording is explicit.",
        expected_frame_count=20,
    )
    return output


def _partitions(tmp_path: Path, *, overlap: bool = False) -> Path:
    value = {
        "schema_version": VISIBLE_CARD_PARTITION_SCHEMA,
        "partitions": {
            "train": ["package-000:frame_00", "package-001:frame_00"],
            "validation": ["package-002:frame_00", "package-003:frame_00"],
            "challenge": ["package-004:frame_00", "package-005:frame_00"],
        },
        "system_holdout_groups": [],
        "reason": "Freeze the source-group split before detector comparison.",
    }
    if overlap:
        value["partitions"]["train"] = ["package-001:frame_00"]
        value["partitions"]["validation"] = [
            "package-000:frame_00",
            "package-002:frame_00",
            "package-003:frame_00",
        ]
    path = tmp_path / "partitions.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_freeze_publishes_provenance_safe_manifests_and_coverage_gap(tmp_path: Path) -> None:
    output = tmp_path / "freeze"
    report = freeze_visible_card_review_data(
        _queue(tmp_path),
        _pilot(tmp_path),
        _partitions(tmp_path),
        output,
    )

    assert report["seed_frame_count"] == 4
    assert report["seed_target_met"] is False
    assert (
        "usable seed frames: 4/100"
        in json.loads((output / "coverage-report.json").read_text(encoding="utf-8"))["seed"][
            "coverage_gap"
        ]
    )
    frozen = load_frozen_visible_card_review_data(output)
    assert frozen["selected_teacher_request_version"] == "visible-card-request/v2"
    assert len(frozen["teacher_manifest"]["frames"]) == 4
    assert frozen["partition_manifests"]["train"]["frames"][0]["labels"][0]["review_id"]


def test_freeze_rejects_source_group_overlap(tmp_path: Path) -> None:
    with pytest.raises(VisibleCardReviewFreezeError, match="crosses partitions"):
        freeze_visible_card_review_data(
            _queue(tmp_path),
            _pilot(tmp_path),
            _partitions(tmp_path, overlap=True),
            tmp_path / "freeze",
        )


def test_freeze_rejects_system_holdout_group(tmp_path: Path) -> None:
    partitions = json.loads(_partitions(tmp_path).read_text(encoding="utf-8"))
    partitions["system_holdout_groups"] = ["group-2"]
    partition_path = tmp_path / "holdout-partitions.json"
    partition_path.write_text(json.dumps(partitions), encoding="utf-8")

    with pytest.raises(VisibleCardReviewFreezeError, match="system holdout"):
        freeze_visible_card_review_data(
            _queue(tmp_path),
            _pilot(tmp_path),
            partition_path,
            tmp_path / "freeze",
        )


def test_partition_loader_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "partitions.json"
    path.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")
    with pytest.raises(VisibleCardReviewFreezeError, match="unexpected fields"):
        load_visible_card_partition_manifest(path)


def test_crop_policy_is_frozen_and_transforms_are_distinct(tmp_path: Path) -> None:
    policy = frozen_visible_card_crop_policy()
    assert policy["schema_version"] == VISIBLE_CARD_CROP_POLICY_SCHEMA
    image = tmp_path / "frame.jpg"
    _image(image, (220, 20, 20))
    card = _reviewed_card()
    raw = apply_visible_card_crop_policy(
        image.read_bytes(), card, "raw_rectangular", width=20, height=20
    )
    oracle = apply_visible_card_crop_policy(
        image.read_bytes(), card, "oracle_visible_region", width=20, height=20
    )
    assert raw is not None and oracle is not None and raw != oracle
    with Image.open(BytesIO(oracle)) as rendered:
        assert rendered.getpixel((12, 10)) == (128, 128, 128)
    tagged = ReviewedVisibleCard(
        card_id=card.card_id,
        visible_region=card.visible_region,
        derived_box=card.derived_box,
        identity_usability=card.identity_usability,
        side=card.side,
        failure_tags=("occlusion",),
    )
    assert (
        apply_visible_card_crop_policy(
            image.read_bytes(), tagged, "conservative_box_only", width=20, height=20
        )
        is None
    )
