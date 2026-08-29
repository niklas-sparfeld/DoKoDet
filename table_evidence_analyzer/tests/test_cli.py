import json
from pathlib import Path

from table_evidence_analyzer.cli import build_parser, main


def test_root_help_lists_the_training_command_shape_without_analyze() -> None:
    help_text = build_parser().format_help()

    assert "data" in help_text
    assert "train" in help_text
    assert "evaluate" in help_text
    assert "export" in help_text
    assert "classify-crop" in help_text
    assert "identity-evaluate" in help_text
    assert "visible-cards" in help_text
    assert "visible-card-queue" in help_text
    assert "review-visible-card" in help_text
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


def test_visible_card_fake_command_writes_run_overlay_queue_and_review(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fixture image bytes")
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps({"cards": []}), encoding="utf-8")
    result = tmp_path / "result.json"
    overlay = tmp_path / "overlay.svg"
    cache = tmp_path / "cache"

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

    queue = tmp_path / "queue.json"
    assert (
        main(
            [
                "visible-card-queue",
                "--result",
                str(result),
                "--run-id",
                "run-001",
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
                "GOOD",
                "--reviewer",
                "operator",
            ]
        )
        == 0
    )
    assert json.loads(queue.read_text(encoding="utf-8"))["items"][0]["decision"] == "GOOD"


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
