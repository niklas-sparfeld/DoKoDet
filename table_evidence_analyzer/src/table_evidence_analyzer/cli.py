"""Command-line entry point for TableEvidenceAnalyzer tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from .visible_cards import (
    DEFAULT_MODEL,
    CachedVisibleCardProvider,
    FakeVisibleCardProvider,
    GeminiVisibleCardProvider,
    VisibleCardError,
    build_request_from_image,
    load_run_artifact,
    write_overlay_svg,
    write_run_artifact,
)


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

    materialize_parser = data_commands.add_parser(
        "materialize-visible-card-dataset",
        aliases=("materialize-visible-card",),
        help="Materialize the bounded visible-card COCO pseudo-label dataset.",
        description=(
            "Join exact-event frames and cached visible-card results into an external-image "
            "COCO dataset, provenance manifest, split, and frozen RF-DETR recipe."
        ),
    )
    materialize_parser.add_argument("--evidence-root", type=Path, required=True)
    materialize_parser.add_argument(
        "--results-root",
        "--results",
        dest="results_root",
        type=Path,
        required=True,
    )
    materialize_parser.add_argument(
        "--output-dir", "--output", dest="output_dir", type=Path, required=True
    )
    materialize_parser.add_argument(
        "--system-holdout",
        type=Path,
        help="JSON manifest of source-lineage groups excluded from development data.",
    )
    materialize_parser.add_argument("--target-frame-count", type=int, default=20)
    materialize_parser.add_argument("--max-frames", type=int, default=40)
    materialize_parser.add_argument("--seed", type=int, default=37)
    materialize_parser.add_argument("--epochs", type=int, default=20)
    materialize_parser.add_argument("--confidence-threshold", type=float, default=0.5)

    prompt_pilot_parser = commands.add_parser(
        "visible-card-prompt-pilot",
        help="Run paired visible-card request versions on development frames.",
        description=(
            "Run the existing and improved visible-card requests on the same development-only "
            "frames and write an immutable paired pilot report."
        ),
    )
    prompt_pilot_parser.add_argument("--manifest", type=Path, required=True)
    prompt_pilot_parser.add_argument("--output", type=Path, required=True)
    prompt_pilot_parser.add_argument("--provider", choices=("fake", "gemini"), default="fake")
    prompt_pilot_parser.add_argument("--model", default=DEFAULT_MODEL)
    prompt_pilot_parser.add_argument(
        "--cache-dir", type=Path, default=Path("data/cache/visible-card-prompt-pilot")
    )
    prompt_pilot_parser.add_argument(
        "--selected-version",
        choices=("none", "v1", "v2"),
        default="none",
        help="Select one request version only after reviewing the development pilot.",
    )
    prompt_pilot_parser.add_argument("--selection-reason", required=True)
    prompt_pilot_parser.add_argument("--run-id", default="visible-card-prompt-pilot-v1")
    prompt_pilot_parser.add_argument(
        "--frame-count",
        type=int,
        default=20,
        help="Require this many development frames (default: 20).",
    )

    train_parser = commands.add_parser(
        "train",
        help="Train a model from a resolved configuration.",
        description="Train a model from a resolved configuration.",
    )
    train_parser.add_argument("--config", type=Path, required=True)
    train_parser.add_argument("--resume", type=Path, help="Resume from a checkpoint.")

    visible_card_train_parser = commands.add_parser(
        "train-visible-card-detector",
        aliases=("train-visible-card",),
        help="Fine-tune and bundle the frozen local visible-card detector.",
        description=(
            "Run one frozen RF-DETR Large training operation from a materialized visible-card "
            "dataset and write a run record plus a digest-checked native bundle."
        ),
    )
    visible_card_train_parser.add_argument("--dataset-dir", type=Path, required=True)
    visible_card_train_parser.add_argument("--evidence-root", type=Path, required=True)
    visible_card_train_parser.add_argument("--pretrained-checkpoint", type=Path, required=True)
    visible_card_train_parser.add_argument("--output-dir", type=Path, required=True)
    visible_card_train_parser.add_argument(
        "--runner",
        choices=("rfdetr", "fixture"),
        default="rfdetr",
        help="Use rfdetr for the CUDA run or fixture for local contract tests.",
    )

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

    identity_parser = commands.add_parser(
        "identity-evaluate",
        help="Evaluate identity baselines on oracle crops.",
        description=(
            "Evaluate deterministic identity baselines on a frozen dataset partition. "
            "This measures identity feasibility, not visible-card localization."
        ),
    )
    identity_parser.add_argument("--dataset", type=Path, required=True)
    identity_parser.add_argument("--split", type=Path, required=True)
    identity_parser.add_argument("--artifacts", type=Path, required=True)
    identity_parser.add_argument("--output", type=Path, required=True)
    identity_parser.add_argument(
        "--partition",
        choices=("train", "validation", "test", "unassigned"),
        default="validation",
    )
    identity_parser.add_argument(
        "--method",
        choices=("all", "rgb-centroid", "rgb-prototype"),
        default="all",
    )
    identity_parser.add_argument("--top-k", type=int, nargs="+", default=[1, 3, 5])
    identity_parser.add_argument("--cache-dir", type=Path)

    visible_card_evaluation_parser = commands.add_parser(
        "visible-card-evaluate",
        help="Evaluate visible-card proposals against reviewed polygons.",
        description=(
            "Evaluate strict visible-card provider results against reviewed polygon references. "
            "This measures localization, not event truth."
        ),
    )
    visible_card_evaluation_parser.add_argument("--result", type=Path, nargs="+", required=True)
    visible_card_evaluation_parser.add_argument("--reference", type=Path, required=True)
    visible_card_evaluation_parser.add_argument("--output", type=Path, required=True)
    visible_card_evaluation_parser.add_argument("--iou-threshold", type=float, default=0.5)

    visible_card_batch_parser = commands.add_parser(
        "visible-card-batch",
        help="Run visible-card proposals over an evidence extraction.",
        description=(
            "Run one exact-event visible-card request per evidence package. "
            "The batch is resumable and defaults to the local fake provider."
        ),
    )
    visible_card_batch_parser.add_argument("--evidence-root", type=Path, required=True)
    visible_card_batch_parser.add_argument("--output-dir", type=Path, required=True)
    visible_card_batch_parser.add_argument(
        "--cache-dir", type=Path, default=Path("data/cache/visible-cards")
    )
    visible_card_batch_parser.add_argument("--provider", choices=("fake", "gemini"), default="fake")
    visible_card_batch_parser.add_argument("--model", default=DEFAULT_MODEL)
    visible_card_batch_parser.add_argument("--timeout", type=float, default=120.0)
    visible_card_batch_parser.add_argument("--max-retries", type=int, default=2)
    visible_card_batch_parser.add_argument("--target-offset-ms", type=int, default=0)
    visible_card_batch_parser.add_argument("--fake-prediction", type=Path)
    visible_card_batch_parser.add_argument("--overlay-dir", type=Path)
    visible_card_batch_parser.add_argument(
        "--identity-bundle",
        type=Path,
        help="Classify each detected polygon with an exported identity bundle.",
    )
    visible_card_batch_parser.add_argument(
        "--identity-classifier",
        choices=("bundle", "gemini"),
        help="Use the exported bundle or Gemini for each transformed card crop.",
    )
    visible_card_batch_parser.add_argument(
        "--identity-cache-dir", type=Path, default=Path("data/cache/card-classification")
    )
    visible_card_batch_parser.add_argument(
        "--observation-dir",
        type=Path,
        help="Directory for table-observation/v1 artifacts.",
    )
    visible_card_batch_parser.add_argument("--resume", action="store_true")

    visible_card_observe_parser = commands.add_parser(
        "visible-card-observe",
        help="Detect visible cards, classify their crops, and write a table observation.",
        description=(
            "Run one visible-card provider request, classify each transformed polygon crop with "
            "an exported identity bundle or Gemini, and write a validated table-observation/v1 "
            "artifact."
        ),
    )
    visible_card_observe_parser.add_argument("--image", type=Path, required=True)
    visible_card_observe_parser.add_argument("--package-id", required=True)
    visible_card_observe_parser.add_argument(
        "--bundle",
        type=Path,
        help="Exported local identity bundle, required when --identity-classifier=bundle.",
    )
    visible_card_observe_parser.add_argument(
        "--identity-classifier", choices=("bundle", "gemini"), default="bundle"
    )
    visible_card_observe_parser.add_argument("--output", type=Path, required=True)
    visible_card_observe_parser.add_argument("--event-time-ms", type=int, default=0)
    visible_card_observe_parser.add_argument("--actual-offset-ms", type=int, default=0)
    visible_card_observe_parser.add_argument("--session-id")
    visible_card_observe_parser.add_argument("--event-sequence", type=int, default=1)
    visible_card_observe_parser.add_argument("--width", type=int)
    visible_card_observe_parser.add_argument("--height", type=int)
    visible_card_observe_parser.add_argument("--frame-part-name", default="frame_00")
    visible_card_observe_parser.add_argument(
        "--cache-dir", type=Path, default=Path("data/cache/visible-cards")
    )
    visible_card_observe_parser.add_argument(
        "--provider", choices=("fake", "gemini"), default="fake"
    )
    visible_card_observe_parser.add_argument("--fake-prediction", type=Path)
    visible_card_observe_parser.add_argument("--model", default=DEFAULT_MODEL)
    visible_card_observe_parser.add_argument("--timeout", type=float, default=120.0)
    visible_card_observe_parser.add_argument("--max-retries", type=int, default=2)
    visible_card_observe_parser.add_argument(
        "--identity-cache-dir", type=Path, default=Path("data/cache/card-classification")
    )

    visible_cards_parser = commands.add_parser(
        "visible-cards",
        help="Propose visible cards for one exact-event frame.",
        description=(
            "Run the visible-card provider for one exact-event source frame. "
            "The result is a proposal, not a reviewed event."
        ),
    )
    visible_cards_parser.add_argument("--image", type=Path, required=True)
    visible_cards_parser.add_argument("--package-id", required=True)
    visible_cards_parser.add_argument("--frame-part-name", default="frame_00")
    visible_cards_parser.add_argument("--target-offset-ms", type=int, default=0)
    visible_cards_parser.add_argument("--output", type=Path, required=True)
    visible_cards_parser.add_argument("--overlay", type=Path)
    visible_cards_parser.add_argument(
        "--cache-dir", type=Path, default=Path("data/cache/visible-cards")
    )
    visible_cards_parser.add_argument("--provider", choices=("fake", "gemini"), default="fake")
    visible_cards_parser.add_argument("--fake-prediction", type=Path)
    visible_cards_parser.add_argument("--model", default=None)
    visible_cards_parser.add_argument("--width", type=int)
    visible_cards_parser.add_argument("--height", type=int)
    visible_cards_parser.add_argument("--timeout", type=float, default=120.0)
    visible_cards_parser.add_argument("--max-retries", type=int, default=2)

    queue_parser = commands.add_parser(
        "visible-card-queue",
        help="Create a resumable visible-card geometry review queue.",
    )
    queue_parser.add_argument("--result", type=Path, nargs="+", required=True)
    queue_parser.add_argument("--run-id", required=True)
    queue_parser.add_argument(
        "--lineage-manifest",
        type=Path,
        required=True,
        help="Source-lineage manifest for the result frames.",
    )
    queue_parser.add_argument("--output", type=Path, required=True)

    review_parser = commands.add_parser(
        "review-visible-card",
        help="Record a frame decision and optional visible-card actions.",
    )
    review_parser.add_argument("--queue", type=Path, required=True)
    review_parser.add_argument("--item-id", required=True)
    review_parser.add_argument("--decision", choices=("GOOD", "BAD"), required=True)
    review_parser.add_argument("--reviewer", required=True)
    empty_group = review_parser.add_mutually_exclusive_group(required=False)
    empty_group.add_argument("--empty-frame", dest="empty_frame", action="store_true")
    empty_group.add_argument("--not-empty-frame", dest="empty_frame", action="store_false")
    review_parser.set_defaults(empty_frame=None)
    review_parser.add_argument(
        "--cards",
        type=Path,
        help="JSON list of accept, reshape, add, or remove actions.",
    )
    review_parser.add_argument("--failure-tag", action="append", default=[])

    action_parser = commands.add_parser(
        "review-visible-card-action",
        help="Save one visible-card accept, reshape, add, or remove action.",
    )
    action_parser.add_argument("--queue", type=Path, required=True)
    action_parser.add_argument("--item-id", required=True)
    action_parser.add_argument(
        "--action", choices=("accepted", "reshaped", "added", "removed"), required=True
    )
    action_parser.add_argument("--card-id", required=True)
    action_parser.add_argument("--proposal-index", type=int)
    action_parser.add_argument(
        "--reviewed-card",
        type=Path,
        help="JSON ReviewedVisibleCard object; omit only for remove.",
    )
    action_parser.add_argument("--reviewer", required=True)

    complete_parser = commands.add_parser(
        "complete-visible-card-review",
        help="Finalize a GOOD visible-card review after all actions are saved.",
    )
    complete_parser.add_argument("--queue", type=Path, required=True)
    complete_parser.add_argument("--item-id", required=True)
    complete_parser.add_argument("--reviewer", required=True)

    freeze_parser = commands.add_parser(
        "freeze-visible-card-review",
        help="Freeze reviewed visible-card manifests and crop policies.",
        description=(
            "Freeze completed visible-card reviews into source-group-safe train, validation, "
            "challenge, teacher, coverage, and crop-policy artifacts."
        ),
    )
    freeze_parser.add_argument("--queue", type=Path, required=True)
    freeze_parser.add_argument("--pilot-report", type=Path, required=True)
    freeze_parser.add_argument("--partitions", type=Path, required=True)
    freeze_parser.add_argument("--output-dir", type=Path, required=True)
    freeze_parser.add_argument("--freeze-id", default="visible-card-review-freeze-v1")

    comparison_parser = commands.add_parser(
        "compare-visible-card-detectors",
        help="Compare pseudo-label and reviewed-box detector candidates.",
        description=(
            "Create a provenance-checked paired detector and crop comparison from a frozen "
            "visible-card review. This command does not train or promote a model."
        ),
    )
    comparison_parser.add_argument("--freeze", type=Path, required=True)
    comparison_parser.add_argument("--gemini-candidate", type=Path, required=True)
    comparison_parser.add_argument("--reviewed-candidate", type=Path, required=True)
    comparison_parser.add_argument("--crop-evaluation", type=Path, required=True)
    comparison_parser.add_argument("--output", type=Path, required=True)
    comparison_parser.add_argument("--score-threshold", type=float, default=0.5)
    comparison_parser.add_argument("--match-iou-threshold", type=float, default=0.5)

    targeted_round_parser = commands.add_parser(
        "evaluate-visible-card-targeted-round",
        help="Evaluate one bounded targeted visible-card data round.",
        description=(
            "Compare an augmented reviewed-box detector run with the M3 reviewed-box baseline "
            "on the unchanged frozen validation and challenge frames."
        ),
    )
    targeted_round_parser.add_argument("--freeze", type=Path, required=True)
    targeted_round_parser.add_argument("--m3-report", type=Path, required=True)
    targeted_round_parser.add_argument("--batch", type=Path, required=True)
    targeted_round_parser.add_argument("--targeted-candidate", type=Path, required=True)
    targeted_round_parser.add_argument("--output", type=Path, required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one offline analyzer command."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "data" and args.data_command is None:
        parser.parse_args(["data", "--help"])
    if args.command == "data" and args.data_command == "validate":
        from .data import (
            load_artifact_index,
            load_dataset_manifest,
            load_split_manifest,
            validate_dataset,
        )

        report = validate_dataset(
            load_dataset_manifest(args.dataset),
            split=load_split_manifest(args.split),
            artifacts=load_artifact_index(args.artifacts),
        )
        print(report.to_mapping())
        return 0 if report.valid else 1
    if args.command == "data" and args.data_command in {
        "materialize-visible-card-dataset",
        "materialize-visible-card",
    }:
        from .visible_card_dataset import (
            VisibleCardDatasetConfig,
            VisibleCardDatasetError,
            materialize_visible_card_dataset,
        )

        try:
            report = materialize_visible_card_dataset(
                VisibleCardDatasetConfig(
                    evidence_root=args.evidence_root,
                    results_root=args.results_root,
                    output_dir=args.output_dir,
                    system_holdout=args.system_holdout,
                    target_frame_count=args.target_frame_count,
                    max_frames=args.max_frames,
                    seed=args.seed,
                    epochs=args.epochs,
                    confidence_threshold=args.confidence_threshold,
                )
            )
        except (OSError, ValueError, VisibleCardDatasetError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.command == "visible-card-prompt-pilot":
        from .visible_card_prompt_pilot import load_prompt_pilot_frames, run_prompt_pilot

        try:
            frames = load_prompt_pilot_frames(args.manifest)
            if args.provider == "fake":
                provider = FakeVisibleCardProvider()
            else:
                provider = GeminiVisibleCardProvider.from_environment()
            selected_version = {
                "none": None,
                "v1": "visible-card-request/v1",
                "v2": "visible-card-request/v2",
            }[args.selected_version]
            report = run_prompt_pilot(
                frames,
                provider,
                output=args.output,
                selected_request_version=selected_version,
                selection_reason=args.selection_reason,
                run_id=args.run_id,
                model=args.model,
                cache_dir=args.cache_dir,
                expected_frame_count=args.frame_count,
            )
        except (VisibleCardError, OSError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(
            f"Wrote paired visible-card prompt pilot for {report['frame_count']} frames: "
            f"{args.output}"
        )
        return 0
    if args.command in {"train-visible-card-detector", "train-visible-card"}:
        from .visible_card_training import VisibleCardTrainingConfig, run_visible_card_training

        try:
            report = run_visible_card_training(
                VisibleCardTrainingConfig(
                    dataset_dir=args.dataset_dir,
                    evidence_root=args.evidence_root,
                    pretrained_checkpoint=args.pretrained_checkpoint,
                    output_dir=args.output_dir,
                    runner=args.runner,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(json.dumps(report, sort_keys=True))
        return 0
    from .training import evaluate, load_config, train

    if args.command == "train":
        config = load_config(args.config)
        if args.resume:
            config = replace(config, resume=args.resume)
        print(train(config))
        return 0
    if args.command == "evaluate":
        print(evaluate(args.run, args.split))
        return 0
    if args.command == "export":
        from .export import export_bundle

        print(export_bundle(args.run, args.output))
        return 0
    if args.command == "classify-crop":
        from .export import load_bundle

        print(
            [
                candidate.model_dump(mode="json")
                for candidate in load_bundle(args.bundle).classify(args.image)
            ]
        )
        return 0
    if args.command == "identity-evaluate":
        from .identity import IdentityEvaluationConfig, evaluate_identity_crops

        methods = ("rgb-centroid", "rgb-prototype") if args.method == "all" else (args.method,)
        try:
            report = evaluate_identity_crops(
                IdentityEvaluationConfig(
                    dataset=args.dataset,
                    split=args.split,
                    artifacts=args.artifacts,
                    output=args.output,
                    partition=args.partition,
                    methods=methods,
                    top_k=tuple(args.top_k),
                    cache_dir=args.cache_dir,
                )
            )
        except (OSError, VisibleCardError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote identity evaluation for {report['partition']} partition: {args.output}")
        return 0
    if args.command == "visible-card-evaluate":
        from .visible_card_evaluation import (
            VisibleCardEvaluationConfig,
            evaluate_visible_card_runs,
        )

        try:
            report = evaluate_visible_card_runs(
                VisibleCardEvaluationConfig(
                    results=tuple(args.result),
                    references=args.reference,
                    output=args.output,
                    iou_threshold=args.iou_threshold,
                )
            )
        except (OSError, VisibleCardError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote visible-card evaluation for {report['result_count']} frame(s): {args.output}")
        return 0
    if args.command == "visible-card-batch":
        from .visible_card_batch import VisibleCardBatchConfig, run_visible_card_batch

        try:
            report = run_visible_card_batch(
                VisibleCardBatchConfig(
                    evidence_root=args.evidence_root,
                    output_dir=args.output_dir,
                    cache_dir=args.cache_dir,
                    provider=args.provider,
                    model=args.model,
                    timeout_s=args.timeout,
                    max_retries=args.max_retries,
                    target_offset_ms=args.target_offset_ms,
                    fake_prediction=args.fake_prediction,
                    overlay_dir=args.overlay_dir,
                    identity_bundle=args.identity_bundle,
                    identity_classifier=args.identity_classifier,
                    identity_cache_dir=args.identity_cache_dir,
                    observation_dir=args.observation_dir,
                    resume=args.resume,
                )
            )
        except (OSError, VisibleCardError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(
            f"Processed {report['result_count']}/{report['package_count']} package(s); "
            f"{report['failure_count']} failure(s): {args.output_dir}"
        )
        return 0
    if args.command == "visible-card-observe":
        from uuid import UUID

        from PIL import Image

        from .analyzer import AnalyzerEvidence, AnalyzerFrame
        from .card_classification import CachedCardClassifier, GeminiCardClassifier
        from .export import load_bundle
        from .visible_card_observation import VisibleCardTableAnalyzer, write_observation

        try:
            with Image.open(args.image) as image:
                width, height = image.size
            width = args.width or width
            height = args.height or height
            image_bytes = args.image.read_bytes()
            provider: object
            if args.provider == "fake":
                predictions = {}
                if args.fake_prediction:
                    prediction = json.loads(args.fake_prediction.read_text(encoding="utf-8"))
                    if not isinstance(prediction, dict):
                        raise VisibleCardError("fake prediction must be an object")
                    predictions[hashlib.sha256(image_bytes).hexdigest()] = prediction
                provider = FakeVisibleCardProvider(predictions)
            else:
                provider = GeminiVisibleCardProvider.from_environment(
                    timeout_s=args.timeout,
                    max_retries=args.max_retries,
                )
            if args.identity_classifier == "bundle":
                if args.bundle is None:
                    raise VisibleCardError("--bundle is required for --identity-classifier=bundle")
                classifier = load_bundle(args.bundle)
            else:
                classifier = CachedCardClassifier(
                    GeminiCardClassifier.from_environment(
                        model=args.model,
                        timeout_s=args.timeout,
                        max_retries=args.max_retries,
                    ),
                    args.identity_cache_dir,
                )
            analyzer = VisibleCardTableAnalyzer(
                CachedVisibleCardProvider(provider, args.cache_dir),
                classifier,
                model=args.model,
                session_id=args.session_id,
                event_sequence=args.event_sequence,
            )
            observation = analyzer.analyze(
                AnalyzerEvidence(
                    package_id=UUID(args.package_id),
                    event_time_ms=args.event_time_ms,
                    frames=[
                        AnalyzerFrame(
                            part_name=args.frame_part_name,
                            actual_offset_ms=args.actual_offset_ms,
                            width=width,
                            height=height,
                            local_reference=str(args.image),
                        )
                    ],
                )
            )
            write_observation(observation, args.output)
        except (OSError, ValueError, VisibleCardError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote table observation: {args.output}")
        return 0
    if args.command == "visible-cards":
        try:
            request = build_request_from_image(
                args.image,
                package_id=args.package_id,
                frame_part_name=args.frame_part_name,
                target_offset_ms=args.target_offset_ms,
                width=args.width,
                height=args.height,
                model=args.model or DEFAULT_MODEL,
                provider=args.provider,
            )
            if args.provider == "fake":
                predictions = {}
                if args.fake_prediction:
                    predictions[request.image_sha256] = json.loads(
                        args.fake_prediction.read_text(encoding="utf-8")
                    )
                provider = FakeVisibleCardProvider(predictions)
            else:
                provider = GeminiVisibleCardProvider.from_environment(
                    timeout_s=args.timeout,
                    max_retries=args.max_retries,
                )
            result = CachedVisibleCardProvider(provider, args.cache_dir).propose(request)
            overlay = None
            if args.overlay:
                write_overlay_svg(request, result.prediction, args.overlay)
                overlay = str(args.overlay)
            write_run_artifact(
                request,
                result,
                args.output,
                image=str(args.image),
                overlay=overlay,
            )
        except (VisibleCardError, OSError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote visible-card result: {args.output}")
        return 0
    if args.command == "visible-card-queue":
        from .visible_card_review_workflow import (
            VisibleCardReviewWorkflowError,
            build_visible_card_review_queue,
            load_source_lineage_manifest,
        )

        try:
            lineage = load_source_lineage_manifest(args.lineage_manifest)
            artifacts = []
            for result_path in args.result:
                value = dict(load_run_artifact(result_path))
                value["artifact_path"] = str(result_path)
                artifacts.append(value)
            queue = build_visible_card_review_queue(
                artifacts,
                args.output,
                run_id=args.run_id,
                lineage_by_item=lineage,
            )
        except (
            VisibleCardError,
            VisibleCardReviewWorkflowError,
            OSError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote {len(queue.items)} visible-card review items: {args.output}")
        return 0
    if args.command == "review-visible-card":
        from .visible_card_review_workflow import (
            VisibleCardReviewWorkflowError,
            record_frame_review,
        )

        try:
            actions = []
            if args.cards is not None:
                actions = json.loads(args.cards.read_text(encoding="utf-8"))
                if not isinstance(actions, list):
                    raise VisibleCardReviewWorkflowError("--cards must contain a JSON list")
            queue = record_frame_review(
                args.queue,
                args.item_id,
                args.decision,
                reviewer=args.reviewer,
                empty_frame=args.empty_frame,
                failure_tags=tuple(args.failure_tag),
                actions=actions,
            )
        except (VisibleCardError, VisibleCardReviewWorkflowError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        item = next(item for item in queue.items if item.item_id == args.item_id)
        print(
            f"Recorded frame review ({item.review.status}); "
            f"{len(queue.pending_items)} item(s) remain"
        )
        return 0
    if args.command == "review-visible-card-action":
        from .visible_card_review_workflow import (
            VisibleCardReviewWorkflowError,
            record_card_action,
        )

        try:
            reviewed_card = None
            if args.reviewed_card is not None:
                reviewed_card = json.loads(args.reviewed_card.read_text(encoding="utf-8"))
                if not isinstance(reviewed_card, dict):
                    raise VisibleCardReviewWorkflowError(
                        "--reviewed-card must contain a JSON object"
                    )
            action = {
                "card_id": args.card_id,
                "action": args.action,
                "proposal_index": args.proposal_index,
                "reviewed_card": reviewed_card,
            }
            queue = record_card_action(
                args.queue,
                args.item_id,
                action,
                reviewer=args.reviewer,
            )
        except (VisibleCardError, VisibleCardReviewWorkflowError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Recorded card action; {len(queue.pending_items)} item(s) remain")
        return 0
    if args.command == "complete-visible-card-review":
        from .visible_card_review_workflow import (
            VisibleCardReviewWorkflowError,
            finalize_visible_card_review,
        )

        try:
            queue = finalize_visible_card_review(
                args.queue,
                args.item_id,
                reviewer=args.reviewer,
            )
        except (VisibleCardError, VisibleCardReviewWorkflowError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Completed visible-card review; {len(queue.pending_items)} item(s) remain")
        return 0
    if args.command == "freeze-visible-card-review":
        from .visible_card_review_freeze import (
            VisibleCardReviewFreezeError,
            freeze_visible_card_review_data,
        )

        try:
            report = freeze_visible_card_review_data(
                args.queue,
                args.pilot_report,
                args.partitions,
                args.output_dir,
                freeze_id=args.freeze_id,
            )
        except (VisibleCardError, VisibleCardReviewFreezeError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(
            f"Wrote visible-card freeze with {report['seed_frame_count']} seed frame(s) and "
            f"{report['challenge_frame_count']} challenge frame(s): {args.output_dir}"
        )
        return 0
    if args.command == "compare-visible-card-detectors":
        from .visible_card_comparison import (
            VisibleCardComparisonConfig,
            VisibleCardComparisonError,
            compare_visible_card_detectors,
        )

        try:
            report = compare_visible_card_detectors(
                VisibleCardComparisonConfig(
                    freeze=args.freeze,
                    gemini_candidate=args.gemini_candidate,
                    reviewed_candidate=args.reviewed_candidate,
                    crop_evaluation=args.crop_evaluation,
                    output=args.output,
                    score_threshold=args.score_threshold,
                    match_iou_threshold=args.match_iou_threshold,
                )
            )
        except (VisibleCardComparisonError, OSError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(
            f"Wrote visible-card comparison ({report['conclusion']['localization']['direction']}): "
            f"{args.output}"
        )
        return 0
    if args.command == "evaluate-visible-card-targeted-round":
        from .visible_card_targeted_round import (
            VisibleCardTargetedRoundConfig,
            VisibleCardTargetedRoundError,
            evaluate_visible_card_targeted_round,
        )

        try:
            report = evaluate_visible_card_targeted_round(
                VisibleCardTargetedRoundConfig(
                    freeze=args.freeze,
                    m3_report=args.m3_report,
                    batch=args.batch,
                    targeted_candidate=args.targeted_candidate,
                    output=args.output,
                )
            )
        except (
            VisibleCardTargetedRoundError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(
            "Wrote visible-card targeted round "
            f"({report['conclusion']['localization']['validation_direction']}): {args.output}"
        )
        return 0
    parser.exit(2, f"error: command '{_command_name(args)}' is not implemented yet.\n")


def _command_name(args: argparse.Namespace) -> str:
    if args.command == "data" and args.data_command:
        return f"data {args.data_command}"
    return args.command


if __name__ == "__main__":
    raise SystemExit(main())
