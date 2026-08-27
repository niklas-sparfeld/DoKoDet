"""Command-line entry point for TableEvidenceAnalyzer tooling."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Build the command parser without loading models or data."""

    parser = argparse.ArgumentParser(
        prog="table-analyzer",
        description="TableEvidenceAnalyzer training and capability tooling.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    data_parser = commands.add_parser(
        "data",
        help="Dataset validation and materialization commands.",
        description="Dataset validation and materialization commands.",
    )
    data_commands = data_parser.add_subparsers(dest="data_command", metavar="COMMAND")
    validate_parser = data_commands.add_parser(
        "validate",
        help="Validate a frozen dataset and split.",
        description="Validate a frozen dataset and split.",
    )
    validate_parser.add_argument("--dataset", type=Path, required=True)
    validate_parser.add_argument("--split", type=Path, required=True)
    validate_parser.add_argument("--artifacts", type=Path, required=True)

    train_parser = commands.add_parser(
        "train",
        help="Train a model from a resolved configuration.",
        description="Train a model from a resolved configuration.",
    )
    train_parser.add_argument("--config", type=Path, required=True)

    evaluate_parser = commands.add_parser(
        "evaluate",
        help="Evaluate a frozen run or exported bundle.",
        description="Evaluate a frozen run or exported bundle.",
    )
    evaluate_parser.add_argument("--run", type=Path, required=True)
    evaluate_parser.add_argument("--split", required=True)

    export_parser = commands.add_parser(
        "export",
        help="Export a trained run as an analyzer capability bundle.",
        description="Export a trained run as an analyzer capability bundle.",
    )
    export_parser.add_argument("--run", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)

    classify_parser = commands.add_parser(
        "classify-crop",
        help="Classify one oracle crop with an exported bundle.",
        description="Classify one oracle crop with an exported bundle.",
    )
    classify_parser.add_argument("--bundle", type=Path, required=True)
    classify_parser.add_argument("--image", type=Path, required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse one command and report that implementation is pending."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "data" and args.data_command is None:
        parser.parse_args(["data", "--help"])
    parser.exit(2, f"error: command '{_command_name(args)}' is not implemented yet.\n")


def _command_name(args: argparse.Namespace) -> str:
    if args.command == "data" and args.data_command:
        return f"data {args.data_command}"
    return args.command


if __name__ == "__main__":
    raise SystemExit(main())
