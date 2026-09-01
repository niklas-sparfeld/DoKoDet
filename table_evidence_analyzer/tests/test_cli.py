import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from table_evidence_analyzer.cli import build_parser, main


def test_root_help_lists_the_training_command_shape_without_analyze() -> None:
    help_text = build_parser().format_help()

    assert "data" in help_text
    assert "train" in help_text
    assert "evaluate" in help_text
    assert "export" in help_text
    assert "classify-crop" in help_text
    assert "identity-evaluate" in help_text
    assert "visible-card-evaluate" in help_text
    assert "visible-card-prompt-pilot" in help_text
    assert "visible-card-batch" in help_text
    assert "visible-card-observe" in help_text
    assert "visible-cards" in help_text
    assert "visible-card-queue" in help_text
    assert "review-visible-card" in help_text
    assert "review-visible-card-action" in help_text
    assert "complete-visible-card-review" in help_text
    assert "freeze-visible-card-review" in help_text
    assert "compare-visible-card-detectors" in help_text
    assert "evaluate-visible-card-targeted-round" in help_text
    assert "\n    analyze " not in help_text


def test_data_validate_parser_keeps_explicit_artifact_inputs() -> None:
    args = build_parser().parse_args(
        [
            "data",
            "validate",
            "--dataset",
            "dataset.json",
            "--split",
            "split.json",
            "--artifacts",
            "artifacts.json",
        ]
    )

    assert args.command == "data"
    assert args.data_command == "validate"
    assert args.dataset == Path("dataset.json")
    assert args.split == Path("split.json")
    assert args.artifacts == Path("artifacts.json")


def test_visible_card_prompt_pilot_command_writes_paired_report(tmp_path: Path) -> None:
    frames = []
    for index in range(2):
        image = BytesIO()
        Image.new("RGB", (16, 12), (index, 20, 30)).save(image, format="JPEG")
        image_path = tmp_path / f"frame-{index}.jpg"
        image_path.write_bytes(image.getvalue())
        frames.append(
            {
                "package_id": f"package-{index}",
                "frame_part_name": "frame_00",
                "image": image_path.name,
                "source_lineage_group": f"session-{index}",
                "partition": "development",
                "target_offset_ms": 0,
            }
        )
    manifest = tmp_path / "frames.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "visible-card-prompt-pilot-input/v1",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "pilot.json"

    assert (
        main(
            [
                "visible-card-prompt-pilot",
                "--manifest",
                str(manifest),
                "--output",
                str(output),
                "--frame-count",
                "2",
                "--selected-version",
                "v2",
                "--selection-reason",
                "The v2 contract is explicit.",
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["frame_count"] == 2


def test_visible_card_dataset_materializer_parser_has_bounded_inputs() -> None:
    args = build_parser().parse_args(
        [
            "data",
            "materialize-visible-card-dataset",
            "--evidence-root",
            "evidence",
            "--results-root",
            "results",
            "--output-dir",
            "output",
        ]
    )

    assert args.data_command == "materialize-visible-card-dataset"
    assert args.evidence_root == Path("evidence")
    assert args.results_root == Path("results")
    assert args.output_dir == Path("output")
    assert args.target_frame_count == 20
    assert args.max_frames == 40


def test_visible_card_training_parser_has_explicit_mounted_inputs() -> None:
    args = build_parser().parse_args(
        [
            "train-visible-card-detector",
            "--dataset-dir",
            "dataset",
            "--evidence-root",
            "evidence",
            "--pretrained-checkpoint",
            "weights/rf-detr-large.pth",
            "--output-dir",
            "output",
            "--runner",
            "fixture",
        ]
    )

    assert args.command == "train-visible-card-detector"
    assert args.dataset_dir == Path("dataset")
    assert args.evidence_root == Path("evidence")
    assert args.pretrained_checkpoint == Path("weights/rf-detr-large.pth")
    assert args.output_dir == Path("output")
    assert args.runner == "fixture"


def test_visible_card_freeze_parser_has_explicit_immutable_inputs() -> None:
    args = build_parser().parse_args(
        [
            "freeze-visible-card-review",
            "--queue",
            "queue.json",
            "--pilot-report",
            "pilot.json",
            "--partitions",
            "partitions.json",
            "--output-dir",
            "freeze",
        ]
    )

    assert args.command == "freeze-visible-card-review"
    assert args.queue == Path("queue.json")
    assert args.pilot_report == Path("pilot.json")
    assert args.partitions == Path("partitions.json")
    assert args.output_dir == Path("freeze")


def test_visible_card_comparison_parser_has_paired_inputs() -> None:
    args = build_parser().parse_args(
        [
            "compare-visible-card-detectors",
            "--freeze",
            "freeze",
            "--gemini-candidate",
            "gemini.json",
            "--reviewed-candidate",
            "reviewed.json",
            "--crop-evaluation",
            "crops.json",
            "--output",
            "comparison.json",
        ]
    )

    assert args.command == "compare-visible-card-detectors"
    assert args.freeze == Path("freeze")
    assert args.gemini_candidate == Path("gemini.json")
    assert args.reviewed_candidate == Path("reviewed.json")
    assert args.crop_evaluation == Path("crops.json")
    assert args.output == Path("comparison.json")
    assert args.score_threshold == 0.5
    assert args.match_iou_threshold == 0.5


def test_visible_card_targeted_round_parser_has_bounded_inputs() -> None:
    args = build_parser().parse_args(
        [
            "evaluate-visible-card-targeted-round",
            "--freeze",
            "freeze",
            "--m3-report",
            "m3.json",
            "--batch",
            "batch.json",
            "--targeted-candidate",
            "targeted.json",
            "--output",
            "m4.json",
        ]
    )

    assert args.command == "evaluate-visible-card-targeted-round"
    assert args.freeze == Path("freeze")
    assert args.m3_report == Path("m3.json")
    assert args.batch == Path("batch.json")
    assert args.targeted_candidate == Path("targeted.json")
    assert args.output == Path("m4.json")


def test_visible_card_fake_command_writes_run_overlay_queue_and_review(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fixture image bytes")
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps({"cards": []}), encoding="utf-8")
    result = tmp_path / "result.json"
    overlay = tmp_path / "overlay.svg"
    cache = tmp_path / "cache"
    lineage = tmp_path / "lineage.json"

    assert (
        main(
            [
                "visible-cards",
                "--image",
                str(image),
                "--package-id",
                "package-001",
                "--output",
                str(result),
                "--overlay",
                str(overlay),
                "--cache-dir",
                str(cache),
                "--fake-prediction",
                str(prediction),
                "--width",
                "64",
                "--height",
                "48",
            ]
        )
        == 0
    )
    assert json.loads(result.read_text(encoding="utf-8"))["provider"] == {
        "name": "fake",
        "model": "gemini-3.6-flash",
    }
    assert overlay.is_file()
    lineage.write_text(
        json.dumps(
            {
                "schema_version": "visible-card-review-lineage/v1",
                "items": [
                    {
                        "item_id": "package-001:frame_00",
                        "package_id": "package-001",
                        "frame_part_name": "frame_00",
                        "target_offset_ms": 0,
                        "image": str(image),
                        "frame_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                        "source_asset_id": "asset-001",
                        "source_lineage_group": "session-001",
                        "source_asset_sha256": None,
                        "width": 64,
                        "height": 48,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    queue = tmp_path / "queue.json"
    assert (
        main(
            [
                "visible-card-queue",
                "--result",
                str(result),
                "--run-id",
                "run-001",
                "--lineage-manifest",
                str(lineage),
                "--output",
                str(queue),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "review-visible-card",
                "--queue",
                str(queue),
                "--item-id",
                "package-001:frame_00",
                "--decision",
                "BAD",
                "--empty-frame",
                "--reviewer",
                "operator",
            ]
        )
        == 0
    )
    review = json.loads(queue.read_text(encoding="utf-8"))["items"][0]["review"]
    assert review["decision"] == "BAD"
    assert review["empty_frame"] is True


def test_identity_evaluate_command_writes_feasibility_report(tmp_path: Path) -> None:
    from table_evidence_analyzer.data import build_smoke_fixture

    fixture = build_smoke_fixture(tmp_path / "fixture")
    output = tmp_path / "identity-evaluation.json"

    assert (
        main(
            [
                "identity-evaluate",
                "--dataset",
                str(fixture.dataset_path),
                "--split",
                str(fixture.split_path),
                "--artifacts",
                str(fixture.artifact_index_path),
                "--partition",
                "train",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["task"] == "oracle_crop_identity_feasibility"
    assert set(report["methods"]) == {"rgb-centroid", "rgb-prototype"}


def test_visible_card_evaluate_command_writes_localization_report(tmp_path: Path) -> None:
    from table_evidence_analyzer.visible_cards import build_request_from_image

    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fixture image bytes")
    prediction = tmp_path / "prediction.json"
    prediction.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "box_2d": {"y_min": 100, "x_min": 100, "y_max": 300, "x_max": 300},
                        "polygon": [
                            {"x": 100, "y": 100},
                            {"x": 300, "y": 100},
                            {"x": 300, "y": 300},
                            {"x": 100, "y": 300},
                        ],
                        "side": "face_up",
                        "label": "card",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = tmp_path / "result.json"
    assert (
        main(
            [
                "visible-cards",
                "--image",
                str(image),
                "--package-id",
                "package-001",
                "--output",
                str(result),
                "--fake-prediction",
                str(prediction),
                "--width",
                "1000",
                "--height",
                "1000",
            ]
        )
        == 0
    )
    request = build_request_from_image(
        image,
        package_id="package-001",
        frame_part_name="frame_00",
        target_offset_ms=0,
        width=1000,
        height=1000,
        provider="fake",
    )
    references = tmp_path / "references.json"
    references.write_text(
        json.dumps(
            {
                "schema_version": "visible-card-reference/v1",
                "references": [
                    {
                        "package_id": "package-001",
                        "frame_part_name": "frame_00",
                        "target_offset_ms": 0,
                        "image_sha256": request.image_sha256,
                        "cards": [
                            {
                                "card_id": "card-001",
                                "polygon": [
                                    {"x": 100, "y": 100},
                                    {"x": 300, "y": 100},
                                    {"x": 300, "y": 300},
                                    {"x": 100, "y": 300},
                                ],
                                "side": "face_up",
                                "usable_for_crop": True,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evaluation = tmp_path / "evaluation.json"
    assert (
        main(
            [
                "visible-card-evaluate",
                "--result",
                str(result),
                "--reference",
                str(references),
                "--output",
                str(evaluation),
            ]
        )
        == 0
    )
    report = json.loads(evaluation.read_text(encoding="utf-8"))
    assert report["metrics"]["instance_recall"] == 1.0
