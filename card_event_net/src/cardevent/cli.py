from __future__ import annotations

import argparse
from collections.abc import Sequence

_PLACEHOLDER_COMMANDS = {
    "annotate": "Annotate a source video.",
    "prepare": "Build the low-resolution frame cache.",
    "make-split": "Create a video-level split file.",
    "train": "Train the CardEventNet model.",
    "infer": "Run offline inference on one video.",
    "evaluate": "Evaluate one checkpoint on a split.",
    "baseline": "Run the classical motion baseline.",
    "mine-hard-negatives": "Mine hard negatives from training videos.",
    "export-coreml": "Export a checkpoint to Core ML.",
    "extract-evidence": "Extract source-resolution evidence frames.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cardevent",
        description="CardEventNet command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    for name, help_text in _PLACEHOLDER_COMMANDS.items():
        command_parser = subparsers.add_parser(name, help=help_text, description=help_text)
        command_parser.set_defaults(command_name=name)

    return parser


def _dispatch_placeholder(parser: argparse.ArgumentParser, command_name: str) -> None:
    parser.exit(2, f"error: command '{command_name}' is not implemented yet.\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command_name = getattr(args, "command_name", None)
    if command_name is None:
        parser.print_help()
        return 0

    _dispatch_placeholder(parser, command_name)
    return 0

