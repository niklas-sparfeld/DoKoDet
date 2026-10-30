"""Execution and output for source lifecycle commands."""

import argparse
import json
import sys

from .config import ConfigurationError, RepositoryConfig
from .impact import (
    SourceImpactError,
    analyze_repository_impacts,
    analyze_source_impact,
    retire_source,
)


def run_impact(args: argparse.Namespace) -> int:
    try:
        config = RepositoryConfig.from_environment(
            args.repository_root,
            intake_root=args.intake_root,
            evidence_package_root=args.evidence_package_root,
            pending_video_root=args.pending_video_root,
            artifacts_root=args.artifacts_root,
        )
        if args.source_asset_id:
            result = analyze_source_impact(
                config.repository_root,
                args.source_asset_id,
                bundle_root=config.bundle_root,
                artifacts_root=config.derived_artifact_root,
                requested_retention_state=args.retention_state,
            )
        else:
            if args.retention_state is not None:
                raise SourceImpactError(
                    "--retention-state requires --source-asset-id for an impact preview."
                )
            result = {
                "schema_version": "source-impact-index/v1",
                "reports": list(
                    analyze_repository_impacts(
                        config.repository_root,
                        bundle_root=config.bundle_root,
                        artifacts_root=config.derived_artifact_root,
                    )
                ),
            }
    except (ConfigurationError, OSError, SourceImpactError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json or args.format == "json":
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_render_impact_human(result))
    return 0


def run_source_retirement(args: argparse.Namespace) -> int:
    try:
        config = RepositoryConfig.from_environment(
            args.repository_root,
            intake_root=args.intake_root,
            evidence_package_root=args.evidence_package_root,
            pending_video_root=args.pending_video_root,
            artifacts_root=args.artifacts_root,
        )
        result = retire_source(
            config.repository_root,
            args.source_asset_id,
            bundle_root=config.bundle_root,
            artifacts_root=config.derived_artifact_root,
            retention_state=args.retention_state,
            operator=args.operator,
            reason=args.reason,
        )
    except (ConfigurationError, OSError, SourceImpactError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json or args.format == "json":
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        state = result["source_state"]
        receipt = result["stale_receipt"]
        sys.stdout.write(
            "Source lifecycle state recorded\n"
            f"source: {state['source_asset_id']}\n"
            f"retention state: {state['retention_state']}\n"
            f"state version: {state['version']}\n"
            f"stale receipt: {receipt['receipt_id']}\n"
        )
    return 0


def _render_impact_human(result: dict) -> str:
    reports = result.get("reports") if "reports" in result else [result]
    lines = ["DokoDetector source impact"]
    for report in reports:
        lines.append(
            f"source: {report['source_asset_id']} ({report['retention_state']}), "
            f"{sum(report['artifact_counts'].values())} affected artifacts"
        )
        for task in report["task_impacts"]:
            lines.append(f"  - {task['task']}: {task['impact_state']}")
        for artifact in report["affected_artifacts"]:
            lines.append(f"    - {artifact['kind']}: {artifact['path']}")
    return "\n".join(lines) + "\n"
