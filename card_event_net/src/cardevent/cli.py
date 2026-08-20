from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .annotation import AnnotationError, annotate_video
from .baseline import evaluate_baseline_from_files
from .cache import CacheError, prepare_videos
from .evaluate import EvaluationError, evaluate_checkpoint_from_files, format_report
from .infer import InferenceError, infer_from_files
from .splits import SplitError, make_video_split, save_split
from .train import TrainingError, train_from_files
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

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Build the low-resolution frame cache.",
        description="Decode annotated videos and build their 10 fps ROI caches.",
    )
    prepare_parser.add_argument(
        "--videos",
        nargs="+",
        type=Path,
        required=True,
        help="Source videos to cache.",
    )
    prepare_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=None,
        help="Override the annotations directory.",
    )
    prepare_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Override the cache root directory.",
    )
    prepare_parser.add_argument(
        "--cache-fps",
        type=float,
        default=10.0,
        help="Cached frame rate (default: 10).",
    )
    prepare_parser.add_argument(
        "--size",
        type=int,
        default=224,
        help="Square cached frame size (default: 224).",
    )
    prepare_parser.set_defaults(command_name="prepare")

    split_parser = subparsers.add_parser(
        "make-split",
        help="Create a video-level split file.",
        description="Create a deterministic train/val/test split by source video.",
    )
    split_parser.add_argument("videos", nargs="+", type=Path, help="Source videos to split.")
    split_parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/splits/default.yaml"),
        help="Split file path (default: data/splits/default.yaml).",
    )
    split_parser.add_argument("--seed", type=int, default=42, help="Split random seed.")
    split_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing split file.",
    )
    split_parser.set_defaults(command_name="make-split")

    train_parser = subparsers.add_parser(
        "train",
        help="Train the CardEventNet model.",
        description="Train CardEventNet with the two-stage transfer-learning schedule.",
    )
    train_parser.add_argument("--config", type=Path, required=True, help="Training config YAML.")
    train_parser.add_argument("--split", type=Path, required=True, help="Video split YAML.")
    train_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs"),
        help="Directory for timestamped runs (default: data/outputs).",
    )
    train_parser.add_argument(
        "--run-name",
        default=None,
        help="Optional stable run directory name.",
    )
    train_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Prepared cache root (default: data/cache).",
    )
    train_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=Path("data/annotations"),
        help="Annotation directory (default: data/annotations).",
    )
    train_parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Limit train and validation samples for a fast development sanity check.",
    )
    train_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default=None,
        help="Override the device in the config.",
    )
    train_parser.set_defaults(command_name="train")

    infer_parser = subparsers.add_parser(
        "infer",
        help="Run offline inference on one video.",
        description="Run causal inference at eight decisions per second.",
    )
    infer_parser.add_argument("--checkpoint", type=Path, required=True, help="Model checkpoint.")
    infer_parser.add_argument("--video", type=Path, required=True, help="Source video.")
    infer_parser.add_argument("--out", type=Path, required=True, help="Prediction JSON path.")
    infer_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Prepared cache root (default: data/cache).",
    )
    infer_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default=None,
        help="Override the device stored in the checkpoint config.",
    )
    infer_parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Inference batch size (default: training batch size).",
    )
    infer_parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Also write clustered events at this threshold.",
    )
    infer_parser.add_argument(
        "--merge-window",
        type=float,
        default=None,
        help="Override the event merge window in seconds.",
    )
    infer_parser.set_defaults(command_name="infer")

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate one checkpoint on a split.",
        description="Tune a threshold on validation data and report event-level metrics.",
    )
    evaluate_parser.add_argument("--checkpoint", type=Path, required=True, help="Model checkpoint.")
    evaluate_parser.add_argument("--split", type=Path, required=True, help="Video split YAML.")
    evaluate_parser.add_argument(
        "--partition",
        choices=("train", "val", "test"),
        required=True,
        help="Split partition to evaluate.",
    )
    evaluate_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Prepared cache root (default: data/cache).",
    )
    evaluate_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=Path("data/annotations"),
        help="Annotation directory (default: data/annotations).",
    )
    evaluate_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Metrics JSON path (default: next to the checkpoint).",
    )
    evaluate_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default=None,
        help="Override the device stored in the checkpoint config.",
    )
    evaluate_parser.set_defaults(command_name="evaluate")

    baseline_parser = subparsers.add_parser(
        "baseline",
        help="Run the classical motion baseline.",
        description="Tune and evaluate a simple cached-frame motion baseline.",
    )
    baseline_parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    baseline_parser.add_argument("--split", type=Path, required=True, help="Video split YAML.")
    baseline_parser.add_argument(
        "--partition",
        choices=("train", "val", "test"),
        required=True,
        help="Split partition to evaluate.",
    )
    baseline_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Prepared cache root (default: data/cache).",
    )
    baseline_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=Path("data/annotations"),
        help="Annotation directory (default: data/annotations).",
    )
    baseline_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Metrics JSON path (default: data/outputs).",
    )
    baseline_parser.set_defaults(command_name="baseline")

    for name, help_text in _PLACEHOLDER_COMMANDS.items():
        if name in {"annotate", "prepare", "make-split", "train", "infer", "evaluate", "baseline"}:
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

    if command_name == "prepare":
        try:
            cache_paths = prepare_videos(
                args.videos,
                annotations_dir=args.annotations_dir,
                cache_root=args.cache_dir,
                cache_fps=args.cache_fps,
                size=args.size,
            )
        except (AnnotationError, CacheError, VideoError, RuntimeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        for cache_path in cache_paths:
            print(f"Prepared cache: {cache_path}")
        return 0

    if command_name == "make-split":
        if args.out.exists() and not args.force:
            parser.exit(
                2,
                f"error: split file already exists: {args.out} (use --force to replace it)\n",
            )
        try:
            split = make_video_split(args.videos, seed=args.seed)
            save_split(split, args.out)
        except (SplitError, RuntimeError, OSError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote split: {args.out}")
        print(f"  train: {len(split.train)} videos")
        print(f"  val:   {len(split.val)} videos")
        print(f"  test:  {len(split.test)} videos")
        return 0

    if command_name == "train":
        try:
            result = train_from_files(
                args.config,
                args.split,
                output_dir=args.output_dir,
                run_name=args.run_name,
                cache_dir=args.cache_dir,
                annotations_dir=args.annotations_dir,
                max_samples=args.max_samples,
                device_override=args.device,
            )
        except (TrainingError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Training run: {result.run_dir}")
        print(f"Best checkpoint: {result.run_dir / 'best.pt'}")
        return 0

    if command_name == "infer":
        try:
            payload = infer_from_files(
                args.checkpoint,
                args.video,
                out_path=args.out,
                cache_dir=args.cache_dir,
                device_override=args.device,
                batch_size=args.batch_size,
                threshold=args.threshold,
                merge_window_s=args.merge_window,
            )
        except (InferenceError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote {len(payload['probabilities'])} probability samples: {args.out}")
        if "events" in payload:
            print(f"Detected events: {len(payload['events'])}")
        return 0

    if command_name == "evaluate":
        try:
            payload = evaluate_checkpoint_from_files(
                args.checkpoint,
                args.split,
                partition=args.partition,
                cache_dir=args.cache_dir,
                annotations_dir=args.annotations_dir,
                output_path=args.out,
                device_override=args.device,
            )
        except (EvaluationError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(format_report(payload))
        output_path = args.out or args.checkpoint.parent / f"evaluation-{args.partition}.json"
        print(f"Metrics JSON: {output_path}")
        return 0

    if command_name == "baseline":
        try:
            payload = evaluate_baseline_from_files(
                args.config,
                args.split,
                partition=args.partition,
                cache_dir=args.cache_dir,
                annotations_dir=args.annotations_dir,
                output_path=args.out,
            )
        except (EvaluationError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(format_report(payload))
        print(f"Metrics JSON: {args.out or 'data/outputs/baseline-' + args.partition + '.json'}")
        return 0

    _dispatch_placeholder(parser, command_name)
    return 0
