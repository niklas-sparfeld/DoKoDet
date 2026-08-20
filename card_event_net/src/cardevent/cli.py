from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .annotation import AnnotationError, annotate_video
from .video import VideoError

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

    annotate_parser = subparsers.add_parser(
        "annotate",
        help=_PLACEHOLDER_COMMANDS["annotate"],
        description="Annotate one source video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Event definition:\n"
            "  Event time is the first frame at which the card has substantially\n"
            "  reached its final position in the trick area.\n\n"
            "Controls:\n"
            "  SPACE   mark a card_played event\n"
            "  P       pause or play\n"
            "  A / D   seek backward or forward about 250 ms\n"
            "  J / L   seek backward or forward about 2 s\n"
            "  BACKSPACE or X  remove the latest event\n"
            "  R       redefine the ROI\n"
            "  Q       save and exit"
        ),
    )
    annotate_parser.add_argument("video", type=Path, help="Source video to annotate.")
    annotate_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=None,
        help="Override the annotations directory.",
    )
    annotate_parser.set_defaults(command_name="annotate")

    for name, help_text in _PLACEHOLDER_COMMANDS.items():
        if name == "annotate":
            continue
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

    if command_name == "annotate":
        try:
            annotate_video(args.video, annotations_dir=args.annotations_dir)
        except (AnnotationError, VideoError, RuntimeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        return 0

    _dispatch_placeholder(parser, command_name)
    return 0
