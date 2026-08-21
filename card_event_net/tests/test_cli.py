from __future__ import annotations

from pathlib import Path

from cardevent.cli import build_parser, main


def test_root_help_lists_the_expected_commands() -> None:
    help_text = build_parser().format_help()

    assert "annotate" in help_text
    assert "prepare" in help_text
    assert "train" in help_text
    assert "export-coreml" in help_text


def test_annotate_command_parses_a_video_path() -> None:
    args = build_parser().parse_args(["annotate", "data/raw/IMG_0090.mov"])

    assert args.command_name == "annotate"
    assert args.video == Path("data/raw/IMG_0090.mov")


def test_train_command_parses_config_and_split() -> None:
    args = build_parser().parse_args(
        ["train", "--config", "configs/base.yaml", "--split", "data/splits/default.yaml"]
    )

    assert args.command_name == "train"
    assert args.config == Path("configs/base.yaml")
    assert args.split == Path("data/splits/default.yaml")
    assert args.max_samples is None
    assert args.hard_negative_manifest is None
    assert args.batch_size is None
    assert args.num_workers is None
    assert args.precision is None
    assert args.resume is None


def test_train_command_parses_runtime_overrides_and_resume() -> None:
    args = build_parser().parse_args(
        [
            "train",
            "--config",
            "configs/base.yaml",
            "--split",
            "data/splits/default.yaml",
            "--batch-size",
            "32",
            "--num-workers",
            "4",
            "--precision",
            "bf16",
            "--resume",
            "data/outputs/run-1",
        ]
    )

    assert args.batch_size == 32
    assert args.num_workers == 4
    assert args.precision == "bf16"
    assert args.resume == Path("data/outputs/run-1")


def test_infer_command_parses_checkpoint_video_and_output() -> None:
    args = build_parser().parse_args(
        [
            "infer",
            "--checkpoint",
            "run/best.pt",
            "--video",
            "data/raw/game.mov",
            "--out",
            "predictions.json",
        ]
    )

    assert args.command_name == "infer"
    assert args.checkpoint == Path("run/best.pt")
    assert args.video == Path("data/raw/game.mov")
    assert args.out == Path("predictions.json")


def test_evaluate_and_baseline_commands_parse_partitions() -> None:
    evaluate_args = build_parser().parse_args(
        [
            "evaluate",
            "--checkpoint",
            "run/best.pt",
            "--split",
            "data/splits/default.yaml",
            "--partition",
            "test",
        ]
    )
    baseline_args = build_parser().parse_args(
        ["baseline", "--split", "data/splits/default.yaml", "--partition", "val"]
    )

    assert evaluate_args.partition == "test"
    assert baseline_args.partition == "val"


def test_diagnose_command_parses_checkpoint_and_split() -> None:
    args = build_parser().parse_args(
        [
            "diagnose",
            "--checkpoint",
            "run/best.pt",
            "--split",
            "data/splits/default.yaml",
        ]
    )

    assert args.command_name == "diagnose"
    assert args.checkpoint == Path("run/best.pt")
    assert args.split == Path("data/splits/default.yaml")


def test_mine_hard_negatives_command_parses_checkpoint_and_split() -> None:
    args = build_parser().parse_args(
        [
            "mine-hard-negatives",
            "--checkpoint",
            "run/best.pt",
            "--split",
            "data/splits/default.yaml",
        ]
    )

    assert args.command_name == "mine-hard-negatives"
    assert args.checkpoint == Path("run/best.pt")
    assert args.split == Path("data/splits/default.yaml")
    assert args.out == Path("data/outputs/hard-negatives.json")


def test_export_coreml_command_parses_checkpoint_and_output() -> None:
    args = build_parser().parse_args(
        [
            "export-coreml",
            "--checkpoint",
            "run/best.pt",
            "--out",
            "CardEventNet.mlpackage",
        ]
    )

    assert args.command_name == "export-coreml"
    assert args.checkpoint == Path("run/best.pt")
    assert args.out == Path("CardEventNet.mlpackage")
    assert args.skip_parity is False


def test_main_without_arguments_prints_help(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage:" in captured.out


def test_prepare_command_reports_progress(monkeypatch, capsys) -> None:
    def fake_prepare_videos(videos, **kwargs):
        progress_callback = kwargs["progress_callback"]
        progress_callback(Path(videos[0]), 0, 4)
        progress_callback(Path(videos[0]), 4, 4)
        return [Path("data/cache/sample")]

    monkeypatch.setattr("cardevent.cli.prepare_videos", fake_prepare_videos)

    assert main(["prepare", "--videos", "sample.mov"]) == 0

    captured = capsys.readouterr()
    assert "Preparing sample.mov" in captured.err
    assert "  0%" in captured.err
    assert "100%" in captured.err
    assert "Prepared cache: data/cache/sample" in captured.out
