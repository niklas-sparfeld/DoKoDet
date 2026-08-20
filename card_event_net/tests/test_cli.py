from __future__ import annotations

from pathlib import Path

from cardevent.cli import build_parser, main


def test_root_help_lists_the_expected_commands() -> None:
    help_text = build_parser().format_help()

    assert "annotate" in help_text
    assert "prepare" in help_text
    assert "train" in help_text


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


def test_main_without_arguments_prints_help(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage:" in captured.out
