from pathlib import Path

from table_evidence_analyzer.cli import build_parser


def test_root_help_lists_the_training_command_shape_without_analyze() -> None:
    help_text = build_parser().format_help()

    assert "data" in help_text
    assert "train" in help_text
    assert "evaluate" in help_text
    assert "export" in help_text
    assert "classify-crop" in help_text
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
