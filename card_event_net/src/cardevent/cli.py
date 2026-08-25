from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from .annotation import AnnotationError, annotate_video, load_annotation_proposals
from .baseline import evaluate_baseline_from_files
from .cache import CacheError, PrepareProgressCallback, prepare_videos
from .evaluate import (
    EvaluationError,
    diagnose_checkpoint_from_files,
    evaluate_checkpoint_from_files,
    format_report,
)
from .export_coreml import CoreMLExportError, export_checkpoint_to_coreml
from .hard_negatives import HardNegativeError, mine_hard_negatives_from_files
from .infer import InferenceError, infer_from_files
from .ingestion import IngestionError, ingest_dataset, inspect_dataset
from .manifest import ManifestError, load_dataset_manifest, make_group_split
from .review import (
    ReviewQueueError,
    ReviewSession,
    ReviewSessionError,
    apply_review_queue,
    review_queue_from_files,
)
from .review_ui import review_queue_interactively
from .splits import SplitError, make_video_split, save_split
from .train import TrainingError, train_from_files
from .transition_diagnostics import TransitionDiagnosticError, diagnose_saved_validation_stream
from .video import VideoError

_PLACEHOLDER_COMMANDS = {
    "annotate": "Annotate a source video.",
    "prepare": "Build the low-resolution frame cache.",
    "make-split": "Create a video-level split file.",
    "train": "Train the CardEventNet model.",
    "infer": "Run offline inference on one video.",
    "evaluate": "Evaluate one checkpoint on a split.",
    "diagnose": "Compare train and validation event behavior.",
    "baseline": "Run the classical motion baseline.",
    "mine-hard-negatives": "Mine hard negatives from training videos.",
    "export-coreml": "Export a checkpoint to Core ML.",
    "ingest": "Register source videos and write a dataset index.",
    "inspect-dataset": "Filter and inspect a dataset index.",
    "extract-evidence": "Extract source-resolution evidence frames.",
    "review-queue": "Build a human review queue from model candidates.",
    "review": "Review queue items with the source videos.",
    "apply-review": "Apply reviewed outcomes to a new annotation version.",
}


class _PrepareProgress:
    _BAR_WIDTH = 24

    def __init__(
        self,
        videos: Sequence[Path] = (),
        *,
        stream: TextIO | None = None,
    ) -> None:
        self._stream = sys.stderr if stream is None else stream
        self._interactive = self._stream.isatty()
        self._video_positions = {
            video.resolve(): index for index, video in enumerate(videos, start=1)
        }
        self._video_count = len(videos)
        self._video_path: Path | None = None
        self._last_percent = -1
        self._line_active = False

    def __call__(self, video_path: Path, current: int, total: int) -> None:
        if total <= 0:
            return
        if video_path != self._video_path:
            self.finish()
            self._video_path = video_path
            self._last_percent = -1

        percent = min(100, current * 100 // total)
        if percent == self._last_percent:
            return
        if (
            not self._interactive
            and current < total
            and self._last_percent >= 0
            and percent < self._last_percent + 10
        ):
            return

        completed = self._BAR_WIDTH * percent // 100
        bar = "#" * completed + "-" * (self._BAR_WIDTH - completed)
        displayed_current = min(current, total)
        video_number = self._video_positions.get(video_path.resolve(), 1)
        video_prefix = f"Video {video_number} / {self._video_count} — " if self._video_count else ""
        text = (
            f"{video_prefix}Preparing {video_path.name}: [{bar}] {percent:3d}% "
            f"({displayed_current}/{total} frames)"
        )
        if self._interactive:
            self._stream.write(f"\r{text}")
        else:
            self._stream.write(f"{text}\n")
        self._stream.flush()
        self._last_percent = percent
        self._line_active = self._interactive

    def finish(self) -> None:
        if self._line_active:
            self._stream.write("\n")
            self._stream.flush()
        self._line_active = False


def _prepare_progress_callback(videos: Sequence[Path] = ()) -> PrepareProgressCallback:
    return _PrepareProgress(videos)


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
    annotate_parser.add_argument(
        "--proposals",
        type=Path,
        default=None,
        help="Inference or review JSON with model candidates to review.",
    )
    annotate_parser.set_defaults(command_name="annotate")

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Build the low-resolution frame cache.",
        description="Decode annotated videos and build their 10 fps frame caches.",
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
    prepare_parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild caches even when a matching complete cache exists.",
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

    group_split_parser = subparsers.add_parser(
        "split", help="Create a session-aware split from a dataset manifest."
    )
    group_split_parser.add_argument("--manifest", type=Path, required=True)
    group_split_parser.add_argument("--group-by", choices=("session_id",), default="session_id")
    group_split_parser.add_argument("--out", type=Path, required=True)
    group_split_parser.add_argument("--seed", type=int, default=42)
    group_split_parser.set_defaults(command_name="split")

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
    train_parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override the training batch size.",
    )
    train_parser.add_argument(
        "--num-workers",
        type=int,
        default=None,
        help="DataLoader worker count (default: 0).",
    )
    train_parser.add_argument(
        "--precision",
        choices=("fp32", "bf16"),
        default=None,
        help="Training precision (default: fp32; bf16 requires CUDA).",
    )
    train_parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Resume a run directory or checkpoint.",
    )
    train_parser.add_argument(
        "--hard-negative-manifest",
        type=Path,
        default=None,
        help="Use mined false-trigger timestamps during training.",
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
    evaluate_parser.add_argument(
        "--reviewed-hard-negative-manifest",
        type=Path,
        default=None,
        help="Optional reviewed validation hard-negative manifest for score diagnostics.",
    )
    evaluate_parser.set_defaults(command_name="evaluate")

    transition_parser = subparsers.add_parser(
        "transition-diagnostics",
        help="Diagnose a saved validation probability stream.",
        description=(
            "Read a saved validation stream and measure post-event score tails "
            "without model inference."
        ),
    )
    transition_parser.add_argument(
        "--validation-stream", type=Path, required=True, help="Saved validation stream (.json.gz)."
    )
    transition_parser.add_argument(
        "--threshold", type=float, required=True, help="Validation-selected probability threshold."
    )
    transition_parser.add_argument("--out", type=Path, required=True, help="Diagnostics JSON path.")
    transition_parser.add_argument(
        "--reviewed-hard-negative-manifest",
        type=Path,
        default=None,
        help="Reviewed validation hard-negative manifest.",
    )
    transition_parser.set_defaults(command_name="transition-diagnostics")

    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help=_PLACEHOLDER_COMMANDS["diagnose"],
        description=(
            "Select a threshold from validation and compare train and validation event metrics."
        ),
    )
    diagnose_parser.add_argument("--checkpoint", type=Path, required=True, help="Model checkpoint.")
    diagnose_parser.add_argument("--split", type=Path, required=True, help="Video split YAML.")
    diagnose_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Prepared cache root (default: data/cache).",
    )
    diagnose_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=Path("data/annotations"),
        help="Annotation directory (default: data/annotations).",
    )
    diagnose_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Diagnostics JSON path (default: next to the checkpoint).",
    )
    diagnose_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default=None,
        help="Override the device stored in the checkpoint.",
    )
    diagnose_parser.set_defaults(command_name="diagnose")

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

    mine_parser = subparsers.add_parser(
        "mine-hard-negatives",
        help="Mine hard negatives from training videos.",
        description="Find false model triggers in the training partition.",
    )
    mine_parser.add_argument("--checkpoint", type=Path, required=True, help="Model checkpoint.")
    mine_parser.add_argument("--split", type=Path, required=True, help="Video split YAML.")
    mine_parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/outputs/hard-negatives.json"),
        help="Manifest path (default: data/outputs/hard-negatives.json).",
    )
    mine_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Prepared cache root (default: data/cache).",
    )
    mine_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=Path("data/annotations"),
        help="Annotation directory (default: data/annotations).",
    )
    mine_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default=None,
        help="Override the device stored in the checkpoint.",
    )
    mine_parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Inference batch size (default: training batch size).",
    )
    mine_parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Use this event threshold instead of the validation threshold.",
    )
    mine_parser.add_argument(
        "--merge-window",
        type=float,
        default=None,
        help="Override the event merge window in seconds.",
    )
    mine_parser.add_argument(
        "--event-match-tolerance",
        type=float,
        default=None,
        help="Override the event matching tolerance in seconds.",
    )
    mine_parser.set_defaults(command_name="mine-hard-negatives")

    review_queue_parser = subparsers.add_parser(
        "review-queue",
        help=_PLACEHOLDER_COMMANDS["review-queue"],
        description=("Build a deterministic review queue. Generated outcomes remain unreviewed."),
    )
    review_queue_parser.add_argument("--checkpoint", type=Path, required=True)
    review_queue_parser.add_argument("--split", type=Path, required=True)
    review_queue_parser.add_argument("--partition", choices=("train", "val", "test"), required=True)
    review_queue_parser.add_argument("--out", type=Path, required=True)
    review_queue_parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    review_queue_parser.add_argument(
        "--annotations-dir", type=Path, default=Path("data/annotations")
    )
    review_queue_parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda", "mps"), default=None
    )
    review_queue_parser.add_argument("--threshold", type=float, default=None)
    review_queue_parser.add_argument("--low-confidence-margin", type=float, default=0.05)
    review_queue_parser.add_argument("--empty-count", type=int, default=2)
    review_queue_parser.add_argument("--seed", type=int, default=42)
    review_queue_parser.add_argument("--preview-half-window", type=float, default=1.0)
    review_queue_parser.add_argument(
        "--compare-checkpoint",
        type=Path,
        default=None,
        help="Optional second checkpoint for model-version disagreement items.",
    )
    review_queue_parser.set_defaults(command_name="review-queue")

    review_parser = subparsers.add_parser(
        "review",
        help=_PLACEHOLDER_COMMANDS["review"],
        description=(
            "Review queue items in source videos. Decisions are autosaved to a separate queue."
        ),
    )
    review_parser.add_argument("--queue", type=Path, required=True, help="Unreviewed review queue.")
    review_parser.add_argument("--out", type=Path, required=True, help="Reviewed queue output.")
    review_parser.add_argument(
        "--videos-dir", type=Path, required=True, help="Source video directory."
    )
    review_parser.add_argument(
        "--annotations-dir", type=Path, required=True, help="Read-only source annotation directory."
    )
    review_parser.add_argument("--reviewer", required=True, help="Stable reviewer name.")
    review_parser.add_argument("--video", default=None, help="Review one video ID or name.")
    review_parser.add_argument("--category", default=None, help="Review one queue category.")
    review_parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help="Include completed items when navigating.",
    )
    review_parser.add_argument("--start-item", default=None, help="Start at this item ID.")
    review_parser.set_defaults(command_name="review")

    apply_review_parser = subparsers.add_parser(
        "apply-review",
        help=_PLACEHOLDER_COMMANDS["apply-review"],
        description=(
            "Apply explicit human outcomes to a new annotation directory. "
            "The source directory is never modified."
        ),
    )
    apply_review_parser.add_argument("--queue", type=Path, required=True)
    apply_review_parser.add_argument(
        "--annotations-dir", type=Path, default=Path("data/annotations")
    )
    apply_review_parser.add_argument("--out-dir", type=Path, required=True)
    apply_review_parser.add_argument(
        "--reviewer", default=None, help="Reviewer name (default: the name in the reviewed queue)."
    )
    apply_review_parser.add_argument("--videos-dir", type=Path, default=Path("data/raw"))
    apply_review_parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Apply reviewed items while leaving unreviewed items unchanged.",
    )
    apply_review_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the application summary without writing annotations.",
    )
    apply_review_parser.set_defaults(command_name="apply-review")

    export_parser = subparsers.add_parser(
        "export-coreml",
        help="Export a checkpoint to Core ML.",
        description="Export CardEventNet as a fixed-shape Core ML model.",
    )
    export_parser.add_argument("--checkpoint", type=Path, required=True, help="Model checkpoint.")
    export_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output .mlpackage path.",
    )
    export_parser.add_argument(
        "--skip-parity",
        action="store_true",
        help="Skip the Core ML versus PyTorch output check.",
    )
    export_parser.set_defaults(command_name="export-coreml")

    ingest_parser = subparsers.add_parser(
        "ingest",
        help=_PLACEHOLDER_COMMANDS["ingest"],
        description="Register source videos without changing the originals or annotations.",
    )
    ingest_parser.add_argument(
        "source_dir",
        nargs="?",
        type=Path,
        help="Directory with source videos (or use --source-dir).",
    )
    ingest_parser.add_argument("--source-dir", dest="source_dir_option", type=Path)
    ingest_parser.add_argument(
        "--operator-metadata",
        "--metadata",
        dest="operator_metadata",
        type=Path,
        required=True,
        help="YAML operator metadata with defaults and per-video records.",
    )
    ingest_parser.add_argument(
        "--manifest",
        "--manifest-out",
        dest="manifest_out",
        type=Path,
        required=True,
        help="V1 dataset manifest output path.",
    )
    ingest_parser.add_argument(
        "--index",
        "--index-out",
        dest="index_out",
        type=Path,
        required=True,
        help="Versioned ingestion index output path.",
    )
    ingest_parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Optional directory for thumbnails and contact sheets.",
    )
    ingest_parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=None,
        help="Read-only annotation directory used for output safety checks.",
    )
    ingest_parser.add_argument(
        "--near-duplicate-distance",
        type=float,
        default=0.08,
        help="Maximum visual fingerprint distance for near duplicates (default: 0.08).",
    )
    ingest_parser.set_defaults(command_name="ingest")

    inspect_parser = subparsers.add_parser(
        "inspect-dataset",
        help=_PLACEHOLDER_COMMANDS["inspect-dataset"],
        description="Print matching ingestion-index rows as stable JSON.",
    )
    inspect_parser.add_argument("index_path", nargs="?", type=Path)
    inspect_parser.add_argument("--index", "--index-path", dest="index_option", type=Path)
    inspect_parser.add_argument("--video-id", action="append", default=[])
    inspect_parser.add_argument("--session-id", action="append", default=[])
    inspect_parser.add_argument("--game-id", action="append", default=[])
    inspect_parser.add_argument("--content-type", action="append", default=[])
    inspect_parser.add_argument("--source-permission", action="append", default=[])
    inspect_parser.add_argument("--duplicate-status", action="append", default=[])
    inspect_parser.set_defaults(command_name="inspect-dataset")

    for name, help_text in _PLACEHOLDER_COMMANDS.items():
        if name in {
            "annotate",
            "prepare",
            "make-split",
            "train",
            "infer",
            "evaluate",
            "diagnose",
            "baseline",
            "mine-hard-negatives",
            "export-coreml",
            "ingest",
            "inspect-dataset",
            "review-queue",
            "review",
            "apply-review",
        }:
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

    if command_name == "ingest":
        source_dir = args.source_dir_option or args.source_dir
        if source_dir is None:
            parser.error("ingest requires a source directory (SOURCE_DIR or --source-dir)")
        try:
            result = ingest_dataset(
                source_dir,
                args.operator_metadata,
                args.manifest_out,
                args.index_out,
                artifact_dir=args.artifact_dir,
                annotation_dir=args.annotations_dir,
                near_duplicate_distance=args.near_duplicate_distance,
            )
        except (IngestionError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote manifest: {result.manifest_path}")
        print(f"Wrote ingestion index: {result.index_path}")
        print(f"Dataset version: {result.dataset_version_digest}")
        return 0

    if command_name == "inspect-dataset":
        index_path = args.index_option or args.index_path
        if index_path is None:
            parser.error("inspect-dataset requires an index path (INDEX_PATH or --index)")
        try:
            rows = inspect_dataset(
                index_path,
                video_id=args.video_id or None,
                session_id=args.session_id or None,
                game_id=args.game_id or None,
                content_type=args.content_type or None,
                source_permission=args.source_permission or None,
                duplicate_status=args.duplicate_status or None,
            )
        except (IngestionError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(json.dumps(list(rows), indent=2, sort_keys=True))
        return 0

    if command_name == "annotate":
        try:
            proposals = load_annotation_proposals(args.proposals) if args.proposals else ()
            annotate_video(args.video, annotations_dir=args.annotations_dir, proposals=proposals)
        except (AnnotationError, VideoError, RuntimeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        return 0

    if command_name == "prepare":
        progress = _prepare_progress_callback(args.videos)
        skipped: list[Path] = []
        try:
            cache_paths = prepare_videos(
                args.videos,
                annotations_dir=args.annotations_dir,
                cache_root=args.cache_dir,
                cache_fps=args.cache_fps,
                size=args.size,
                progress_callback=progress,
                skip_callback=lambda _video, cache_path: skipped.append(cache_path),
                force=args.force,
            )
        except (AnnotationError, CacheError, VideoError, RuntimeError) as exc:
            progress.finish()
            parser.exit(1, f"error: {exc}\n")
        progress.finish()
        for cache_path in cache_paths:
            label = "Skipped cached video" if cache_path in skipped else "Prepared cache"
            print(f"{label}: {cache_path}")
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

    if command_name == "split":
        try:
            split = make_group_split(load_dataset_manifest(args.manifest), seed=args.seed)
            save_split(split, args.out)
        except (ManifestError, SplitError, RuntimeError, OSError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote session-aware split: {args.out}")
        return 0

    if command_name == "train":
        if args.resume is not None and args.run_name is not None:
            parser.exit(2, "error: --resume cannot be combined with --run-name.\n")
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
                hard_negative_manifest=args.hard_negative_manifest,
                batch_size=args.batch_size,
                num_workers=args.num_workers,
                precision=args.precision,
                resume_path=args.resume,
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
                reviewed_hard_negative_manifest=args.reviewed_hard_negative_manifest,
            )
        except (EvaluationError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(format_report(payload))
        if not payload.get("target_recall_met", True):
            maximum_recall = payload.get("maximum_attainable_recall", 0.0)
            print(
                "WARNING: target recall was not met; "
                f"maximum attainable recall was {maximum_recall:.2%}.",
                file=sys.stderr,
            )
        output_path = args.out or args.checkpoint.parent / f"evaluation-{args.partition}.json"
        print(f"Metrics JSON: {output_path}")
        return 0

    if command_name == "transition-diagnostics":
        try:
            payload = diagnose_saved_validation_stream(
                args.validation_stream,
                threshold=args.threshold,
                output_path=args.out,
                reviewed_hard_negative_manifest=args.reviewed_hard_negative_manifest,
            )
        except (TransitionDiagnosticError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        tail = payload["aggregate"]["post_event_tail"]
        print(
            "Post-event tail samples at or above threshold: "
            f"{tail['threshold_exceedance_count']} / {tail['eligible_sample_count']}"
        )
        print(f"Transition diagnostics JSON: {args.out}")
        return 0

    if command_name == "diagnose":
        try:
            payload = diagnose_checkpoint_from_files(
                args.checkpoint,
                args.split,
                cache_dir=args.cache_dir,
                annotations_dir=args.annotations_dir,
                output_path=args.out,
                device_override=args.device,
            )
        except (EvaluationError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        train = payload["train"]
        validation = payload["validation"]
        print("                         train       val")
        print(
            f"Recall                   {train['event_recall']:.1%}      "
            f"{validation['event_recall']:.1%}"
        )
        print(
            f"Precision                {train['event_precision']:.1%}      "
            f"{validation['event_precision']:.1%}"
        )
        print(
            f"False events/hour       {train['false_events_per_hour']:.2f}     "
            f"{validation['false_events_per_hour']:.2f}"
        )
        print(f"Selected threshold:     {payload['threshold']:.2f}")
        print(f"Recall generalization gap: {payload['generalization_gap']['recall']:.1%}")
        print(f"Precision generalization gap: {payload['generalization_gap']['precision']:.1%}")
        output_path = args.out or args.checkpoint.parent / "diagnostics.json"
        print(f"Diagnostics JSON: {output_path}")
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

    if command_name == "mine-hard-negatives":
        try:
            payload = mine_hard_negatives_from_files(
                args.checkpoint,
                args.split,
                out_path=args.out,
                cache_dir=args.cache_dir,
                annotations_dir=args.annotations_dir,
                device_override=args.device,
                batch_size=args.batch_size,
                threshold=args.threshold,
                merge_window_s=args.merge_window,
                event_match_tolerance_s=args.event_match_tolerance,
            )
        except (HardNegativeError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Mined {payload['hard_negative_count']} hard negatives: {args.out}")
        return 0

    if command_name == "review-queue":
        try:
            payload = review_queue_from_files(
                args.checkpoint,
                args.split,
                partition=args.partition,
                out_path=args.out,
                cache_dir=args.cache_dir,
                annotations_dir=args.annotations_dir,
                device_override=args.device,
                threshold=args.threshold,
                low_confidence_margin=args.low_confidence_margin,
                empty_count=args.empty_count,
                seed=args.seed,
                preview_half_window_s=args.preview_half_window,
                compare_checkpoint_path=args.compare_checkpoint,
            )
        except (ReviewQueueError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote {len(payload['items'])} review items: {args.out}")
        return 0

    if command_name == "review":
        try:
            session = ReviewSession.open(
                args.queue,
                args.out,
                videos_dir=args.videos_dir,
                annotations_dir=args.annotations_dir,
                reviewer=args.reviewer,
                video=args.video,
                category=args.category,
                include_reviewed=args.include_reviewed,
                start_item=args.start_item,
            )
            review_queue_interactively(session)
        except (ReviewSessionError, ReviewQueueError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        return 0

    if command_name == "apply-review":
        try:
            summary = apply_review_queue(
                args.queue,
                annotations_dir=args.annotations_dir,
                out_dir=args.out_dir,
                reviewer=args.reviewer,
                videos_dir=args.videos_dir,
                allow_partial=args.allow_partial,
                dry_run=True,
            )
            print(
                f"Review summary: {summary['reviewed_count']} reviewed, "
                f"{summary['remaining_count']} remaining, "
                f"{summary['positives_to_add']} positives to add, "
                f"{summary['timestamps_to_correct']} timestamps to correct, "
                f"{summary['hard_negative_count']} hard negatives, "
                f"{summary['ignored_count']} ignored; "
                f"videos: {', '.join(summary['affected_videos']) or 'none'}."
            )
            if not args.dry_run:
                summary = apply_review_queue(
                    args.queue,
                    annotations_dir=args.annotations_dir,
                    out_dir=args.out_dir,
                    reviewer=args.reviewer,
                    videos_dir=args.videos_dir,
                    allow_partial=args.allow_partial,
                )
        except (ReviewQueueError, AnnotationError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        if args.dry_run:
            print("Dry run: no files written.")
        else:
            print(
                f"Wrote annotation version {args.out_dir} "
                f"({summary['annotations_added']} events added, "
                f"{summary['timestamps_corrected']} timestamps corrected)"
            )
        return 0

    if command_name == "export-coreml":
        try:
            result = export_checkpoint_to_coreml(
                args.checkpoint,
                args.out,
                verify_parity=not args.skip_parity,
            )
        except (CoreMLExportError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote Core ML model: {result.output_path}")
        if result.parity_verified:
            print(f"Parity check passed (max absolute error: {result.max_abs_error:.6g})")
        else:
            print("Parity check skipped")
        return 0

    _dispatch_placeholder(parser, command_name)
    return 0
