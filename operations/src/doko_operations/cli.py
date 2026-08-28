"""The read-only ``doko`` repository operations command."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import ConfigurationError, RepositoryConfig
from .intake import inspect_repository
from .review import (
    REVIEW_TASK_ALL,
    ReviewRunError,
    render_review_human,
    render_review_json,
    run_review,
)
from .status import render_human, render_json
from .table_evidence import TABLE_EVIDENCE_TASK, TableObservationReviewAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doko", description="DokoDetector data operations.")
    _add_path_options(parser)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    data = commands.add_parser("data", help="Inspect and process repository data.")
    data_commands = data.add_subparsers(dest="data_command", metavar="COMMAND")
    for name, help_text in (
        ("status", "Show read-only intake and derived-data status."),
        ("validate", "Validate read-only intake and derived-data state."),
    ):
        command = data_commands.add_parser(name, help=help_text, description=help_text)
        _add_path_options(command, suppress_defaults=True)
        command.add_argument(
            "--format",
            choices=("human", "json"),
            default="human",
            help="Output format (default: human).",
        )
        command.add_argument(
            "--json",
            action="store_true",
            help="Alias for --format json.",
        )
    review = data_commands.add_parser(
        "review",
        help="Create or resume one task review run.",
        description="Create or resume one task review run.",
    )
    _add_path_options(review, suppress_defaults=True)
    review.add_argument(
        "--task",
        choices=("cardevent_event_detection", "table_evidence_analysis", REVIEW_TASK_ALL),
        required=True,
    )
    review.add_argument("--reviewer", required=True, help="Stable reviewer name.")
    review.add_argument(
        "--run-id", default=None, help="Resume this run instead of the deterministic default."
    )
    review.add_argument(
        "--decision-file", type=Path, default=None, help="JSON map of item IDs to decision objects."
    )
    review.add_argument(
        "--approve-split", action="store_true", help="Approve any staged split proposal."
    )
    review.add_argument(
        "--evidence-root",
        action="append",
        type=Path,
        default=[],
        help="Read-only root containing accepted evidence packages (repeatable).",
    )
    review.add_argument(
        "--reviewed-events-root",
        action="append",
        type=Path,
        default=[],
        help="Read-only root containing reviewed event documents (repeatable).",
    )
    review.add_argument(
        "--operator-selection-file",
        type=Path,
        default=None,
        help="JSON file containing explicit operator-selected intervals.",
    )
    review.add_argument("--format", choices=("human", "json"), default="human")
    review.add_argument("--json", action="store_true", help="Alias for --format json.")
    return parser


def _add_path_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--repository-root",
        "--root",
        dest="repository_root",
        type=Path,
        default=default,
        help="Repository checkout to inspect (default: discover from mise.toml).",
    )
    parser.add_argument(
        "--intake-root",
        dest="intake_root",
        type=Path,
        default=default,
        help="Override the repository intake root; useful for a fixture or temporary root.",
    )
    parser.add_argument(
        "--artifacts-root",
        dest="artifacts_root",
        type=Path,
        default=default,
        help="Override the read-only derived-artifact root.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one read-only command and return its process status."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "data" and args.data_command is None:
        data_parser = next(
            action for action in parser._subparsers._group_actions if action.dest == "command"
        )
        data_parser.choices["data"].print_help()
        return 0
    if args.command == "data" and args.data_command == "review":
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                artifacts_root=args.artifacts_root,
            )
            provider = _decision_provider(args.decision_file)
            split_provider = (lambda task, state: True) if args.approve_split else None
            adapters = None
            if args.evidence_root or args.reviewed_events_root or args.operator_selection_file:
                adapters = {
                    TABLE_EVIDENCE_TASK: TableObservationReviewAdapter(
                        evidence_roots=args.evidence_root,
                        reviewed_event_roots=args.reviewed_events_root,
                        operator_selection_file=args.operator_selection_file,
                    )
                }
            result = run_review(
                config.repository_root,
                task=args.task,
                reviewer=args.reviewer,
                bundle_root=config.bundle_root,
                artifacts_root=config.derived_artifact_root,
                run_id=args.run_id,
                decision_provider=provider,
                split_approval_provider=split_provider,
                adapters=adapters,
            )
        except (ConfigurationError, OSError, ReviewRunError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(render_review_json(result, repository_root=config.repository_root))
        else:
            sys.stdout.write(render_review_human(result, repository_root=config.repository_root))
        return 1 if result.state == "failed" else 0
    try:
        config = RepositoryConfig.from_environment(
            args.repository_root,
            intake_root=args.intake_root,
            artifacts_root=args.artifacts_root,
        )
        result = inspect_repository(
            config.repository_root,
            bundle_root=config.bundle_root,
            artifacts_root=config.derived_artifact_root,
        )
    except (ConfigurationError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    output_json = args.json or args.format == "json"
    if output_json:
        sys.stdout.write(
            render_json(
                result,
                repository_root=config.repository_root,
                bundle_root=config.bundle_root,
            )
        )
    else:
        sys.stdout.write(
            render_human(
                result,
                repository_root=config.repository_root,
                bundle_root=config.bundle_root,
            )
        )
    return 1 if args.data_command == "validate" and not result.valid else 0


def _decision_provider(path: Path | None):
    if path is None:
        return None
    try:
        value = __import__("json").loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ReviewRunError(f"Could not read decision file {path}: {error}") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ReviewRunError("Decision file must be a JSON object keyed by review item ID.")
    decisions = dict(value)

    def provide(item):
        decision = decisions.get(item.item_id)
        if decision is None:
            return None
        if not isinstance(decision, dict):
            raise ReviewRunError(f"Decision for {item.item_id} must be a JSON object.")
        return decision

    return provide


__all__ = ["build_parser", "main"]
