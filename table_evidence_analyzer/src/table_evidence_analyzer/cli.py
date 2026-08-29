"""Command-line entry point for TableEvidenceAnalyzer tooling."""

from __future__ import annotations

import argparse
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
    build_review_queue,
    load_run_artifact,
    record_review,
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

    train_parser = commands.add_parser(
        "train",
        help="Train a model from a resolved configuration.",
        description="Train a model from a resolved configuration.",
    )
    train_parser.add_argument("--config", type=Path, required=True)
    train_parser.add_argument("--resume", type=Path, help="Resume from a checkpoint.")

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
        help="Create a resumable visible-card review queue.",
    )
    queue_parser.add_argument("--result", type=Path, nargs="+", required=True)
    queue_parser.add_argument("--run-id", required=True)
    queue_parser.add_argument("--output", type=Path, required=True)

    review_parser = commands.add_parser(
        "review-visible-card",
        help="Record one GOOD or BAD visible-card review decision.",
    )
    review_parser.add_argument("--queue", type=Path, required=True)
    review_parser.add_argument("--item-id", required=True)
    review_parser.add_argument("--decision", choices=("GOOD", "BAD"), required=True)
    review_parser.add_argument("--reviewer", required=True)

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
        try:
            results = []
            for result_path in args.result:
                value = load_run_artifact(result_path)
                request = value["request"]
                results.append(
                    {
                        "package_id": request["package_id"],
                        "frame_part_name": request["frame_part_name"],
                        "target_offset_ms": request["target_offset_ms"],
                        "image": value.get("image"),
                        "overlay": value.get("overlay"),
                        "prediction": value["prediction"],
                    }
                )
            queue = build_review_queue(results, args.output, run_id=args.run_id)
        except (VisibleCardError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Wrote {len(queue.items)} visible-card review items: {args.output}")
        return 0
    if args.command == "review-visible-card":
        try:
            queue = record_review(
                args.queue,
                args.item_id,
                args.decision,
                reviewer=args.reviewer,
            )
        except (VisibleCardError, OSError, ValueError) as exc:
            parser.exit(1, f"error: {exc}\n")
        print(f"Recorded review; {len(queue.pending_items)} item(s) remain")
        return 0
    parser.exit(2, f"error: command '{_command_name(args)}' is not implemented yet.\n")


def _command_name(args: argparse.Namespace) -> str:
    if args.command == "data" and args.data_command:
        return f"data {args.data_command}"
    return args.command


if __name__ == "__main__":
    raise SystemExit(main())
