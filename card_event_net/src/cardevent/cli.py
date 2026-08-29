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
from .evidence_extraction import EvidenceExtractionError, extract_annotation_evidence
from .export_coreml import CoreMLExportError, export_checkpoint_to_coreml
from .hard_negatives import HardNegativeError, mine_hard_negatives_from_files
from .infer import InferenceError, infer_from_files
from .ingestion import IngestionError, ingest_dataset, inspect_dataset
from .lifecycle import (
    LifecycleReceiptError,
    build_dataset_creation_receipt,
    build_evidence_import_receipt,
    build_source_import_receipt,
    build_split_creation_receipt,
    build_training_run_receipt,
    load_lifecycle_receipts,
    retire_source_records,
    save_lifecycle_receipt,
    save_source_records,
)
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
from .table_dataset import (
    TableDatasetError,
    assemble_table_evidence_dataset,
    assert_valid_dataset_version,
    build_table_dataset_coverage,
    load_dataset_split,
    load_dataset_version,
    load_lineage_graph,
    load_source_metadata,
    load_source_records,
    load_table_observation_annotations,
    load_table_observation_reviews,
    make_dataset_split,
    save_assembly_result,
    save_coverage_reports,
    save_dataset_split,
    save_dataset_version,
    save_validation_report,
)
from .train import TrainingError, train_from_files
from .transition_diagnostics import TransitionDiagnosticError, diagnose_saved_validation_stream
from .video import VideoError
from .vision_annotation import (
    VisionAnnotationError,
    import_evidence_packages,
    save_vision_annotation,
)
from .vision_review import (
    VisionReviewError,
    apply_vision_review,
)
from .vision_viewer import VisionViewerError, review_vision_annotation

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
    "vision-import": "Import evidence manifests as visual event proposals.",
    "vision-review": "Review one visual event and its evidence frames.",
    "vision-apply-review": "Apply one visual review to a new annotation version.",
    "dataset-build": "Build a TableEvidenceAnalyzer dataset from reviewed observations.",
    "dataset-split": "Create a group-safe split for a frozen table-observation dataset.",
    "dataset-validate": "Validate a frozen table-observation dataset and its lineage.",
    "dataset-coverage": "Write machine-readable and human-readable dataset coverage reports.",
    "training-receipt": (
        "Record the complete source, annotation, and review provenance of a model run."
    ),
    "retire-source": "Retire source assets and report affected derived artifacts and runs.",
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

    extract_evidence_parser = subparsers.add_parser(
        "extract-evidence",
        help=_PLACEHOLDER_COMMANDS["extract-evidence"],
        description=(
            "Create source-resolution evidence packages from reviewed card-play annotations."
        ),
    )
    extract_evidence_parser.add_argument("--videos-dir", type=Path, required=True)
    extract_evidence_parser.add_argument("--annotations-dir", type=Path, required=True)
    extract_evidence_parser.add_argument("--manifest", type=Path, required=True)
    extract_evidence_parser.add_argument("--out", type=Path, required=True)
    extract_evidence_parser.add_argument(
        "--split",
        type=Path,
        default=None,
        help="Optional split used to exclude sealed partitions.",
    )
    extract_evidence_parser.add_argument(
        "--partition",
        nargs="+",
        choices=("train", "val", "test", "unassigned"),
        default=("train", "val"),
        help="Partitions to extract when --split is present (default: train val).",
    )
    extract_evidence_parser.add_argument(
        "--video-id",
        nargs="+",
        default=(),
        help="Extract only these manifest video IDs (default: all records).",
    )
    extract_evidence_parser.add_argument(
        "--jpeg-quality",
        type=float,
        default=0.85,
        help="JPEG quality from 0 to 1 (default: 0.85).",
    )
    extract_evidence_parser.set_defaults(command_name="extract-evidence")

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
        "--seed",
        type=int,
        default=None,
        help="Override the seed from the training config.",
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
    evaluate_parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Evaluate validation at this explicit operating threshold.",
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

    vision_import_parser = subparsers.add_parser(
        "vision-import",
        aliases=("import-vision", "import-vision-annotations"),
        help=_PLACEHOLDER_COMMANDS["vision-import"],
        description=(
            "Import accepted evidence-package manifests as draft visual event annotations. "
            "Source manifests are never modified."
        ),
    )
    vision_import_parser.add_argument(
        "manifests", nargs="+", type=Path, help="Evidence manifest or package directory."
    )
    vision_import_parser.add_argument(
        "--out-dir", type=Path, required=True, help="New directory for table-observation files."
    )
    vision_import_parser.add_argument("--operator", default="operator")
    vision_import_parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Lifecycle receipt path (default: inside the output directory).",
    )
    vision_import_parser.set_defaults(command_name="vision-import")

    vision_review_parser = subparsers.add_parser(
        "vision-review",
        help=_PLACEHOLDER_COMMANDS["vision-review"],
        description="Review one visual event and all supplied evidence frames.",
    )
    vision_review_parser.add_argument("--annotation", type=Path, required=True)
    vision_review_parser.add_argument("--frames-dir", type=Path, required=True)
    vision_review_parser.add_argument("--out", type=Path, required=True)
    vision_review_parser.add_argument("--reviewer", required=True)
    vision_review_parser.add_argument("--review-id", default=None)
    vision_review_parser.add_argument("--snippet", type=Path, default=None)
    vision_review_parser.set_defaults(command_name="vision-review")

    vision_apply_parser = subparsers.add_parser(
        "vision-apply-review",
        help=_PLACEHOLDER_COMMANDS["vision-apply-review"],
        description=(
            "Apply one immutable visual review to a new annotation directory. "
            "The source annotation is never modified."
        ),
    )
    vision_apply_parser.add_argument("--annotation", type=Path, required=True)
    vision_apply_parser.add_argument("--review", type=Path, required=True)
    vision_apply_parser.add_argument("--out-dir", type=Path, required=True)
    vision_apply_parser.add_argument("--dry-run", action="store_true")
    vision_apply_parser.set_defaults(command_name="vision-apply-review")

    dataset_build_parser = subparsers.add_parser(
        "dataset-build",
        aliases=("assemble-dataset",),
        help=_PLACEHOLDER_COMMANDS["dataset-build"],
        description=(
            "Build a frozen TableEvidenceAnalyzer identity-crop dataset from reviewed "
            "table observations."
        ),
    )
    dataset_build_parser.add_argument("--annotations", type=Path, required=True)
    dataset_build_parser.add_argument("--reviews", type=Path, required=True)
    dataset_build_parser.add_argument("--sources", type=Path, required=True)
    dataset_build_parser.add_argument("--lineage", type=Path, required=True)
    dataset_build_parser.add_argument("--metadata", type=Path, default=None)
    dataset_build_parser.add_argument("--out", type=Path, required=True)
    dataset_build_parser.add_argument("--report-dir", type=Path, default=None)
    dataset_build_parser.add_argument("--dataset-version-id", required=True)
    dataset_build_parser.add_argument(
        "--intended-use", choices=("train", "validation", "test", "evaluation"), default=None
    )
    dataset_build_parser.add_argument("--allowed-use", action="append", default=None)
    dataset_build_parser.add_argument("--creation-code-revision", default="working-tree")
    dataset_build_parser.add_argument("--operator", default="operator")
    dataset_build_parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Lifecycle receipt path (default: inside the report directory).",
    )
    dataset_build_parser.add_argument(
        "--clean", action="store_true", help="Mark the code revision clean."
    )
    dataset_build_parser.add_argument("--force", action="store_true")
    dataset_build_parser.set_defaults(command_name="dataset-build")

    dataset_split_parser = subparsers.add_parser(
        "dataset-split",
        aliases=("make-dataset-split",),
        help=_PLACEHOLDER_COMMANDS["dataset-split"],
        description="Create a deterministic group-safe train/validation/test split.",
    )
    dataset_split_parser.add_argument("--dataset", type=Path, required=True)
    dataset_split_parser.add_argument("--out", type=Path, required=True)
    dataset_split_parser.add_argument("--split-version-id", required=True)
    dataset_split_parser.add_argument("--seed", type=int, default=42)
    dataset_split_parser.add_argument("--operator", default="operator")
    dataset_split_parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Lifecycle receipt path (default: beside the split).",
    )
    dataset_split_parser.add_argument("--force", action="store_true")
    dataset_split_parser.set_defaults(command_name="dataset-split")

    dataset_validate_parser = subparsers.add_parser(
        "dataset-validate",
        aliases=("validate-dataset",),
        help=_PLACEHOLDER_COMMANDS["dataset-validate"],
        description="Validate a frozen dataset version, source records, targets, and split.",
    )
    dataset_validate_parser.add_argument("--dataset", type=Path, required=True)
    dataset_validate_parser.add_argument("--sources", type=Path, required=True)
    dataset_validate_parser.add_argument("--lineage", type=Path, required=True)
    dataset_validate_parser.add_argument("--annotations", type=Path, default=None)
    dataset_validate_parser.add_argument("--reviews", type=Path, default=None)
    dataset_validate_parser.add_argument("--split", type=Path, default=None)
    dataset_validate_parser.add_argument("--out", type=Path, default=None)
    dataset_validate_parser.set_defaults(command_name="dataset-validate")

    dataset_coverage_parser = subparsers.add_parser(
        "dataset-coverage",
        aliases=("dataset-report",),
        help=_PLACEHOLDER_COMMANDS["dataset-coverage"],
        description="Write coverage.json and coverage.md for a frozen dataset version.",
    )
    dataset_coverage_parser.add_argument("--dataset", type=Path, required=True)
    dataset_coverage_parser.add_argument("--annotations", type=Path, required=True)
    dataset_coverage_parser.add_argument("--sources", type=Path, required=True)
    dataset_coverage_parser.add_argument("--metadata", type=Path, default=None)
    dataset_coverage_parser.add_argument("--out-dir", type=Path, required=True)
    dataset_coverage_parser.add_argument("--force", action="store_true")
    dataset_coverage_parser.set_defaults(command_name="dataset-coverage")

    training_receipt_parser = subparsers.add_parser(
        "training-receipt",
        aliases=("record-training-run",),
        help=_PLACEHOLDER_COMMANDS["training-receipt"],
        description=(
            "Write model-run provenance with the dataset, split, source, annotation, and review "
            "versions used."
        ),
    )
    training_receipt_parser.add_argument("--dataset", type=Path, required=True)
    training_receipt_parser.add_argument("--split", type=Path, default=None)
    training_receipt_parser.add_argument("--training-run-id", required=True)
    training_receipt_parser.add_argument("--model-bundle-id", default=None)
    training_receipt_parser.add_argument("--derived-artifact-id", action="append", default=[])
    training_receipt_parser.add_argument("--operator", default="operator")
    training_receipt_parser.add_argument("--out", type=Path, required=True)
    training_receipt_parser.add_argument("--force", action="store_true")
    training_receipt_parser.set_defaults(command_name="training-receipt")

    retire_parser = subparsers.add_parser(
        "retire-source",
        aliases=("retire-data",),
        help=_PLACEHOLDER_COMMANDS["retire-source"],
        description=(
            "Write a new source-record state and a receipt for permission withdrawal or "
            "retirement. Source bytes are never changed."
        ),
    )
    retire_parser.add_argument("--sources", type=Path, required=True)
    retire_parser.add_argument("--source-asset-id", action="append", required=True)
    retire_parser.add_argument("--receipts-dir", type=Path, default=None)
    retire_parser.add_argument("--reason", required=True)
    retire_parser.add_argument(
        "--retention-state",
        choices=("deletion_requested", "retired"),
        default="retired",
    )
    retire_parser.add_argument("--operator", default="operator")
    retire_parser.add_argument("--out", type=Path, required=True)
    retire_parser.add_argument("--receipt", type=Path, default=None)
    retire_parser.add_argument("--force", action="store_true")
    retire_parser.set_defaults(command_name="retire-source")

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
    ingest_parser.add_argument("--operator", default="operator")
    ingest_parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Lifecycle receipt path (default: beside the ingestion index).",
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
            "extract-evidence",
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
            "vision-import",
            "vision-review",
            "vision-apply-review",
            "dataset-build",
            "dataset-split",
            "dataset-validate",
            "dataset-coverage",
            "training-receipt",
            "retire-source",
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
        try:
            receipt = build_source_import_receipt(result, operator=args.operator)
            receipt_path = args.receipt or args.index_out.with_name(
                f"{args.index_out.stem}-import-receipt.json"
            )
            save_lifecycle_receipt(receipt, receipt_path)
        except (LifecycleReceiptError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote manifest: {result.manifest_path}")
        print(f"Wrote ingestion index: {result.index_path}")
        print(f"Dataset version: {result.dataset_version_digest}")
        print(f"Wrote lifecycle receipt: {receipt_path}")
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

    if command_name == "extract-evidence":
        try:
            result = extract_annotation_evidence(
                videos_dir=args.videos_dir,
                annotations_dir=args.annotations_dir,
                dataset_manifest=args.manifest,
                output_dir=args.out,
                video_ids=args.video_id,
                split_path=args.split,
                partitions=args.partition,
                jpeg_quality=args.jpeg_quality,
            )
        except (
            AnnotationError,
            EvidenceExtractionError,
            ManifestError,
            VideoError,
            RuntimeError,
            OSError,
            ValueError,
        ) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote {result.package_count} annotation evidence packages: {result.output_dir}")
        print(
            f"Excluded events: {result.excluded_event_count}; "
            f"incomplete packages: {result.incomplete_package_count}"
        )
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
                seed_override=args.seed,
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
                threshold_override=args.threshold,
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

    if command_name == "vision-import":
        try:
            annotation_set = import_evidence_packages(
                args.manifests,
            )
            if args.out_dir.exists() and (not args.out_dir.is_dir() or any(args.out_dir.iterdir())):
                raise VisionAnnotationError(f"Output directory is not empty: {args.out_dir}")
            args.out_dir.mkdir(parents=True, exist_ok=True)
            for annotation in annotation_set:
                save_vision_annotation(
                    annotation,
                    args.out_dir / f"{annotation.annotation_set_id}.json",
                )
        except (VisionAnnotationError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        try:
            receipt = build_evidence_import_receipt(
                annotation_set,
                manifests=args.manifests,
                operator=args.operator,
            )
            receipt_path = args.receipt or args.out_dir / "table-observation-import-receipt.json"
            save_lifecycle_receipt(receipt, receipt_path)
        except (LifecycleReceiptError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Imported {len(annotation_set)} table observations: {args.out_dir}")
        print(f"Wrote lifecycle receipt: {receipt_path}")
        return 0

    if command_name == "vision-review":
        try:
            review = review_vision_annotation(
                args.annotation,
                frames_dir=args.frames_dir,
                review_path=args.out,
                reviewer=args.reviewer,
                review_id=args.review_id,
                snippet_path=args.snippet,
            )
        except (
            VisionAnnotationError,
            VisionReviewError,
            VisionViewerError,
            RuntimeError,
            OSError,
            ValueError,
        ) as exc:
            parser.exit(1, f"error: {exc}\n")
        if review is None:
            print("Review cancelled; no artifact was written.")
        else:
            print(f"Wrote visual review {args.out}: {review.decision}")
        return 0

    if command_name == "vision-apply-review":
        try:
            receipt = apply_vision_review(
                args.annotation,
                args.review,
                out_dir=args.out_dir,
                dry_run=args.dry_run,
            )
        except (VisionReviewError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        if args.dry_run:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            print(f"Wrote reviewed visual annotation: {args.out_dir}")
        return 0

    if command_name == "dataset-build":
        try:
            sources = load_source_records(args.sources)
            annotations = load_table_observation_annotations(args.annotations)
            reviews = load_table_observation_reviews(args.reviews)
            lineage = load_lineage_graph(args.lineage)
            source_metadata = (
                load_source_metadata(args.metadata) if args.metadata is not None else None
            )
            result = assemble_table_evidence_dataset(
                annotations,
                sources,
                reviews=reviews,
                lineage=lineage,
                dataset_version_id=args.dataset_version_id,
                allowed_use_filter=tuple(args.allowed_use or ("train", "validation", "test")),
                intended_use=args.intended_use,
                creation_code_revision=args.creation_code_revision,
                dirty_state=not args.clean,
                source_metadata=source_metadata,
            )
            save_dataset_version(result.dataset_version, args.out, overwrite=args.force)
            report_dir = args.report_dir or args.out.parent / f"{args.out.stem}-reports"
            save_coverage_reports(result.coverage, report_dir, overwrite=args.force)
            save_assembly_result(
                result,
                report_dir / "assembly.json",
                overwrite=args.force,
            )
            receipt_path = args.receipt or report_dir / "dataset-creation-receipt.json"
            save_lifecycle_receipt(
                build_dataset_creation_receipt(
                    result,
                    sources=sources,
                    reviewed_annotations=tuple(
                        review.reviewed_annotation for review in reviews.values()
                    ),
                    reviews=reviews,
                    operator=args.operator,
                ),
                receipt_path,
                overwrite=args.force,
            )
        except (TableDatasetError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote dataset version: {args.out}")
        print(f"Wrote coverage reports: {report_dir}")
        print(f"Wrote lifecycle receipt: {receipt_path}")
        print(f"Unassigned: {len(result.unassigned)}; excluded: {len(result.excluded)}")
        return 0

    if command_name == "dataset-split":
        try:
            dataset = load_dataset_version(args.dataset)
            split = make_dataset_split(
                dataset,
                split_version_id=args.split_version_id,
                seed=args.seed,
            )
            save_dataset_split(split, args.out, overwrite=args.force)
            receipt_path = args.receipt or args.out.with_name(
                f"{args.out.stem}-creation-receipt.json"
            )
            save_lifecycle_receipt(
                build_split_creation_receipt(
                    dataset,
                    split,
                    operator=args.operator,
                ),
                receipt_path,
                overwrite=args.force,
            )
        except (TableDatasetError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote dataset split: {args.out}")
        print(f"Wrote lifecycle receipt: {receipt_path}")
        print(
            f"  train: {len(split.train)}; validation: {len(split.validation)}; "
            f"test: {len(split.test)}; unassigned: {len(split.unassigned)}"
        )
        return 0

    if command_name == "dataset-validate":
        try:
            dataset = load_dataset_version(args.dataset)
            sources = load_source_records(args.sources)
            lineage = load_lineage_graph(args.lineage)
            annotations = (
                load_table_observation_annotations(args.annotations)
                if args.annotations is not None
                else ()
            )
            reviews = (
                load_table_observation_reviews(args.reviews) if args.reviews is not None else None
            )
            split = load_dataset_split(args.split) if args.split is not None else None
            report = assert_valid_dataset_version(
                dataset,
                sources=sources,
                annotations=annotations,
                reviews=reviews,
                lineage=lineage,
                split=split,
            )
            if args.out is not None:
                save_validation_report(report, args.out, overwrite=True)
        except (TableDatasetError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(json.dumps(report.to_mapping(), indent=2, sort_keys=True))
        return 0

    if command_name == "dataset-coverage":
        try:
            dataset = load_dataset_version(args.dataset)
            annotations = load_table_observation_annotations(args.annotations)
            sources = load_source_records(args.sources)
            source_metadata = (
                load_source_metadata(args.metadata) if args.metadata is not None else None
            )
            report = build_table_dataset_coverage(
                dataset,
                reviewed_annotations=annotations,
                sources=sources,
                source_metadata=source_metadata,
            )
            save_coverage_reports(report, args.out_dir, overwrite=args.force)
        except (TableDatasetError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote coverage reports: {args.out_dir}")
        return 0

    if command_name == "training-receipt":
        try:
            dataset = load_dataset_version(args.dataset)
            split = load_dataset_split(args.split) if args.split is not None else None
            receipt = build_training_run_receipt(
                dataset,
                split,
                training_run_id=args.training_run_id,
                model_bundle_id=args.model_bundle_id,
                derived_artifact_ids=args.derived_artifact_id,
                operator=args.operator,
            )
            save_lifecycle_receipt(receipt, args.out, overwrite=args.force)
        except (LifecycleReceiptError, TableDatasetError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote training lifecycle receipt: {args.out}")
        print(
            f"Sources: {receipt.metadata['source_count']}; "
            f"annotation sets: {receipt.metadata['annotation_set_count']}"
        )
        return 0

    if command_name == "retire-source":
        try:
            sources = load_source_records(args.sources)
            receipts = (
                load_lifecycle_receipts(args.receipts_dir) if args.receipts_dir is not None else ()
            )
            result = retire_source_records(
                sources,
                source_asset_ids=args.source_asset_id,
                operator=args.operator,
                reason=args.reason,
                retention_state=args.retention_state,
                receipts=receipts,
            )
            save_source_records(result.source_records, args.out, overwrite=args.force)
            receipt_path = args.receipt or args.out.with_name("source-retirement-receipt.json")
            save_lifecycle_receipt(result.receipt, receipt_path, overwrite=args.force)
        except (LifecycleReceiptError, TableDatasetError, RuntimeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote source catalog: {args.out}")
        print(f"Wrote lifecycle receipt: {receipt_path}")
        print(json.dumps(result.impact, indent=2, sort_keys=True))
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
