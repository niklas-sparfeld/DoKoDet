from __future__ import annotations

from cardevent.cli import build_parser, main


def test_root_help_lists_the_expected_commands() -> None:
    help_text = build_parser().format_help()

    assert "annotate" in help_text
    assert "prepare" in help_text
    assert "train" in help_text


def test_main_without_arguments_prints_help(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage:" in captured.out

