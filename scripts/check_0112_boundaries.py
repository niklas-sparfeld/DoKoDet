#!/usr/bin/env python3
"""Enforce the source and focused-test budgets for epic 0112."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep this list explicit: each path is part of the 0112 owner map. Generated API
# code and unrelated modules are intentionally absent.
BUDGETS = {
    500: [
        "backend/src/dokodetector_backend/visual_identity_pipeline_service.py",
        "backend/src/dokodetector_backend/job_store.py",
        "web/src/api/client.ts",
        "web/src/pipeline/RecordingPipelineWorkspace.tsx",
        "web/src/pipeline/RunControls.tsx",
    ],
    700: [
        "backend/src/dokodetector_backend/visual_identity_approval.py",
        "backend/src/dokodetector_backend/visual_identity_classification.py",
        "backend/src/dokodetector_backend/visual_identity_crop_inputs.py",
        "backend/src/dokodetector_backend/visual_identity_crop_provenance.py",
        "backend/src/dokodetector_backend/visual_identity_crop_queries.py",
        "backend/src/dokodetector_backend/visual_identity_crop_resolution.py",
        "backend/src/dokodetector_backend/visual_identity_crop_sources.py",
        "backend/src/dokodetector_backend/visual_identity_job.py",
        "backend/src/dokodetector_backend/visual_identity_jobs.py",
        "backend/src/dokodetector_backend/visual_identity_pipeline_errors.py",
        "backend/src/dokodetector_backend/visual_identity_recording_access.py",
        "backend/src/dokodetector_backend/visual_identity_request.py",
        "backend/src/dokodetector_backend/pipeline_revision_store.py",
        "backend/src/dokodetector_backend/processor_run_store.py",
        "backend/src/dokodetector_backend/processor_run_catalog.py",
        "backend/src/dokodetector_backend/processor_run_codec.py",
        "backend/src/dokodetector_backend/processor_run_models.py",
        "backend/src/dokodetector_backend/processor_run_reader.py",
        "backend/src/dokodetector_backend/pipeline_storage.py",
        "backend/src/dokodetector_backend/legacy_processor_run_store.py",
        "backend/src/dokodetector_backend/legacy_processor_run_codec.py",
        "backend/src/dokodetector_backend/job_models.py",
        "backend/src/dokodetector_backend/job_persistence.py",
        "backend/src/dokodetector_backend/job_recovery.py",
        "web/src/api/transport.ts",
        "web/src/api/clientTypes.ts",
        "web/src/api/analysisClient.ts",
        "web/src/api/analysisContracts.ts",
        "web/src/api/calibrationClient.ts",
        "web/src/api/calibrationContracts.ts",
        "web/src/api/frameReviewClient.ts",
        "web/src/api/jobsClient.ts",
        "web/src/api/jobsContracts.ts",
        "web/src/api/pipelineContracts.ts",
        "web/src/api/pipelineProcessingClient.ts",
        "web/src/api/recordingContracts.ts",
        "web/src/api/recordingsClient.ts",
        "web/src/pipeline/EventLaunchFields.tsx",
        "web/src/pipeline/VisibleCardLaunchFields.tsx",
        "web/src/pipeline/VisualIdentityLaunchFields.tsx",
        "web/src/pipeline/RunHistoryPresentation.tsx",
        "web/src/pipeline/RunStatusPresentation.tsx",
        "web/src/pipeline/pipelineLaunchRequest.ts",
        "web/src/pipeline/usePipelineLaunchClient.ts",
        "web/src/pipeline/useRecordingPipelineData.ts",
        "web/src/pipeline/useRecordingPipelineSelection.ts",
        "web/src/pipeline/recordingWorkspacePresentation.ts",
        "web/src/pipeline/recordingPipelineSelection.ts",
        "web/src/pipeline/recordingPipelineUrl.ts",
    ],
    800: [
        "backend/tests/test_visual_identity_pipeline_api.py",
        "backend/tests/test_visual_identity_approval.py",
        "backend/tests/test_visual_identity_classification.py",
        "backend/tests/test_visual_identity_crop_queries.py",
        "backend/tests/test_visual_identity_crop_resolution.py",
        "backend/tests/test_visual_identity_crop_sources.py",
        "backend/tests/test_visual_identity_job.py",
        "backend/tests/test_visual_identity_request.py",
        "backend/tests/test_pipeline_store.py",
        "backend/tests/test_pipeline_node_selection_store.py",
        "backend/tests/test_pipeline_lineage.py",
        "backend/tests/test_pipeline_node_store.py",
        "backend/tests/test_pipeline_node_transactions.py",
        "backend/tests/test_pipeline_node_uses.py",
        "backend/tests/test_pipeline_node_reviews.py",
        "backend/tests/test_lineage_migration_inventory.py",
        "backend/tests/test_pipeline_run_api.py",
        "backend/tests/test_pipeline_comparison_api.py",
        "backend/tests/test_pipeline_vision_comparison_api.py",
        "backend/tests/test_proposed_card_scene_pipeline.py",
        "backend/tests/test_event_recovery_catalog.py",
        "backend/tests/test_repair_0100_m5.py",
        "backend/tests/test_calculation_jobs.py",
        "backend/tests/test_automated_pipeline_jobs.py",
        "backend/tests/test_round_analysis_logging.py",
        "backend/tests/test_job_store.py",
        "backend/tests/test_jobs_api.py",
        "backend/tests/test_job_scheduler.py",
        "backend/tests/test_job_recovery.py",
        "backend/tests/test_job_publication.py",
        "web/src/api/client.test.ts",
        "web/src/api/transport.test.ts",
        "web/src/api/analysisClient.test.ts",
        "web/src/api/calibrationClient.test.ts",
        "web/src/api/pipelineProcessingClient.test.ts",
        "web/src/api/recordingsClient.test.ts",
        "web/src/pipeline/RecordingPipelineWorkspace.test.tsx",
        "web/src/pipeline/RecordingPipelineWorkspaceSelection.test.tsx",
        "web/src/pipeline/RecordingPipelineWorkspacePresentation.test.tsx",
        "web/src/pipeline/useRecordingPipelineData.test.tsx",
        "web/src/pipeline/useRecordingPipelineSelection.test.tsx",
        "web/src/pipeline/RecordingPipelineSelectionIntegration.test.tsx",
        "web/src/pipeline/RunControlsEventAndVisibleCard.test.tsx",
        "web/src/pipeline/RunControlsVisualIdentity.test.tsx",
        "web/src/pipeline/runControlsTestFixtures.tsx",
    ],
}

FEATURE_CLIENTS = [
    "analysisClient.ts",
    "calibrationClient.ts",
    "frameReviewClient.ts",
    "jobsClient.ts",
    "pipelineProcessingClient.ts",
    "recordingsClient.ts",
]
IDENTITY_MODULES = [
    "visual_identity_approval.py",
    "visual_identity_classification.py",
    "visual_identity_crop_inputs.py",
    "visual_identity_crop_provenance.py",
    "visual_identity_crop_queries.py",
    "visual_identity_crop_resolution.py",
    "visual_identity_crop_sources.py",
    "visual_identity_job.py",
    "visual_identity_jobs.py",
    "visual_identity_pipeline_service.py",
    "visual_identity_recording_access.py",
    "visual_identity_request.py",
]


def line_count(path: Path) -> int:
    return len(path.read_text().splitlines())


def import_cycles() -> list[list[str]]:
    package = ROOT / "backend/src/dokodetector_backend"
    owned = {Path(name).stem for name in IDENTITY_MODULES}
    graph: dict[str, set[str]] = {name: set() for name in owned}
    for filename in IDENTITY_MODULES:
        source = (package / filename).read_text()
        tree = ast.parse(source, filename=filename)
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                for item in node.names:
                    prefix = "dokodetector_backend."
                    if item.name.startswith(prefix):
                        target = item.name[len(prefix) :].split(".", 1)[0]
                        if target in owned:
                            graph[Path(filename).stem].add(target)
            if module:
                prefix = "dokodetector_backend."
                if module.startswith(prefix):
                    target = module[len(prefix) :].split(".", 1)[0]
                    if target in owned:
                        graph[Path(filename).stem].add(target)
    cycles: set[tuple[str, ...]] = set()
    for start in graph:
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack:
            current, path = stack.pop()
            for target in graph[current]:
                if target == start and len(path) > 1:
                    cycle = tuple(sorted(path))
                    cycles.add(cycle)
                elif target not in path:
                    stack.append((target, [*path, target]))
    return [list(cycle) for cycle in sorted(cycles)]


def main() -> int:
    failures: list[str] = []
    for budget, names in BUDGETS.items():
        for name in names:
            path = ROOT / name
            if not path.is_file():
                failures.append(f"missing explicit budget path: {name}")
                continue
            lines = line_count(path)
            print(f"{lines:4} / {budget:3}  {name}")
            if lines > budget:
                failures.append(f"{name}: {lines} lines exceeds {budget}")

    client_root = ROOT / "web/src/api"
    aggregate_import = re.compile(r"""from\s+["'](?:\./)?client(?:\.ts)?["']""")
    for filename in FEATURE_CLIENTS:
        path = client_root / filename
        if aggregate_import.search(path.read_text()):
            failures.append(
                f"feature client imports aggregate root: {path.relative_to(ROOT)}"
            )

    production_roots = [
        ROOT / "backend/src",
        ROOT / "web/src/api",
        ROOT / "web/src/pipeline",
    ]
    test_import = re.compile(
        r"(?:dokodetector_backend\.)?test_support|(?:\.\./)+tests?/"
    )
    for base in production_roots:
        for path in base.rglob("*.py") if base.suffix == ".py" else base.rglob("*.ts"):
            if (
                path.name.endswith((".test.ts", ".test.tsx"))
                or "TestFixtures" in path.name
            ):
                continue
            if test_import.search(path.read_text()):
                failures.append(
                    f"production imports test support: {path.relative_to(ROOT)}"
                )
        if base.name in {"api", "pipeline"}:
            for path in base.rglob("*.tsx"):
                if (
                    not path.name.endswith(".test.tsx")
                    and "TestFixtures" not in path.name
                    and test_import.search(path.read_text())
                ):
                    failures.append(
                        f"production imports test support: {path.relative_to(ROOT)}"
                    )

    for cycle in import_cycles():
        failures.append("visual-identity import cycle: " + " -> ".join(cycle))
    if failures:
        print("\nFAIL")
        print("\n".join(f"- {item}" for item in failures))
        return 1
    print("\nPASS: explicit file budgets and import directions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
