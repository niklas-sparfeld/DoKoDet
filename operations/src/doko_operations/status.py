"""Stable human and JSON renderers for read-only repository inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intake import InspectionResult


def status_mapping(
    result: InspectionResult, *, repository_root: Path, bundle_root: Path
) -> dict[str, Any]:
    """Return the canonical JSON-compatible status mapping."""

    return result.to_mapping(repository_root=repository_root, bundle_root=bundle_root)


def render_json(result: InspectionResult, *, repository_root: Path, bundle_root: Path) -> str:
    """Render stable, newline-terminated JSON."""

    return (
        json.dumps(
            status_mapping(result, repository_root=repository_root, bundle_root=bundle_root),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_human(result: InspectionResult, *, repository_root: Path, bundle_root: Path) -> str:
    """Render concise stable status for an operator or a log file."""

    complete = sum(item.state == "complete" for item in result.bundles)
    incomplete = sum(item.state == "incomplete" for item in result.bundles)
    invalid = sum(item.state == "invalid" for item in result.bundles)
    lines = [
        "DokoDetector data status",
        f"repository root: {repository_root}",
        f"bundle root: {_relative(bundle_root, repository_root)}",
        f"bundles: {len(result.bundles)} "
        f"({complete} complete, {incomplete} incomplete, {invalid} invalid)",
        f"pending review: {len(result.pending_review)}",
        f"failures: {len(result.failures)}",
        f"unassigned eligible groups: {len(result.unassigned_eligible_groups)}",
        f"stale derived artifacts: {len(result.stale_derived_artifacts)}",
    ]
    if result.bundles:
        lines.append("bundle details:")
        for bundle in result.bundles:
            identity = bundle.source_asset_id or "unknown-source"
            lines.append(f"  - {bundle.path}: {bundle.state} ({identity})")
            for task in bundle.tasks:
                lines.append(f"    {task.task}: {task.disposition}/{task.lifecycle_state}")
    if result.pending_review:
        lines.append("pending work:")
        for item in result.pending_review:
            resume = "resumable" if item.resumable else "not resumable"
            suffix = f" [{item.run_path}]" if item.run_path else ""
            lines.append(f"  - {item.source_asset_id} {item.task}: {item.state}, {resume}{suffix}")
    if result.failures:
        lines.append("failures:")
        for failure in result.failures:
            lines.append(f"  - {failure.path} ({failure.kind}): {failure.message}")
    if result.unassigned_eligible_groups:
        lines.append("unassigned eligible groups:")
        lines.extend(f"  - {item}" for item in result.unassigned_eligible_groups)
    if result.stale_derived_artifacts:
        lines.append("stale derived artifacts:")
        lines.extend(f"  - {item}" for item in result.stale_derived_artifacts)
    return "\n".join(lines) + "\n"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return path.resolve().as_posix()


__all__ = ["render_human", "render_json", "status_mapping"]
