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
        "scripts/test_0112_boundaries.py",
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


def _python_imports_test_support(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
            modules.extend(alias.name for alias in node.names)
    return any(
        segment.lower() in {"test", "tests", "test_support"}
        for module in modules
        for segment in module.split(".")
    )


_TS_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
_TS_NUMBER = re.compile(r"(?:0[xX][\da-fA-F]+|\d+(?:\.\d*)?)(?:[eE][+-]?\d+)?")
_TS_REGEX_PREFIXES = {
    "(",
    "[",
    "{",
    ",",
    ";",
    ":",
    "=",
    "!",
    "?",
    "&",
    "|",
    "+",
    "-",
    "*",
    "%",
    "^",
    "~",
    "<",
    ">",
    "=>",
    "return",
    "case",
    "throw",
    "else",
    "do",
    "yield",
    "await",
    "typeof",
    "void",
    "delete",
    "in",
    "of",
}


def _typescript_tokens(source: str) -> list[tuple[str, str]]:
    """Tokenize executable code, skipping comments, regexes, and template text."""
    tokens: list[tuple[str, str]] = []

    def scan_code(position: int, stop_at_brace: bool = False) -> int:
        brace_depth = 0
        while position < len(source):
            char = source[position]
            if char.isspace():
                position += 1
                continue
            if source.startswith("//", position):
                newline = source.find("\n", position + 2)
                position = len(source) if newline == -1 else newline + 1
                continue
            if source.startswith("/*", position):
                end = source.find("*/", position + 2)
                position = len(source) if end == -1 else end + 2
                continue
            if stop_at_brace and char == "}":
                if brace_depth == 0:
                    return position + 1
                brace_depth -= 1
            elif char == "{":
                brace_depth += 1

            if char in "'\"":
                quote = char
                end = position + 1
                value: list[str] = []
                while end < len(source):
                    current = source[end]
                    if current == "\\" and end + 1 < len(source):
                        value.extend((current, source[end + 1]))
                        end += 2
                        continue
                    if current == quote:
                        end += 1
                        break
                    value.append(current)
                    end += 1
                tokens.append(("string", "".join(value)))
                position = end
                continue

            if char == "`":
                end = position + 1
                value: list[str] = []
                has_interpolation = False
                while end < len(source):
                    current = source[end]
                    if current == "\\" and end + 1 < len(source):
                        value.extend((current, source[end + 1]))
                        end += 2
                        continue
                    if current == "`":
                        end += 1
                        break
                    if source.startswith("${", end):
                        has_interpolation = True
                        end = scan_code(end + 2, stop_at_brace=True)
                        continue
                    value.append(current)
                    end += 1
                # Keep a static template as a module literal. Its executable
                # interpolations were already tokenized by scan_code.
                if not has_interpolation:
                    tokens.append(("template", "".join(value)))
                else:
                    tokens.append(("expression", "template"))
                position = end
                continue

            if char == "/" and _can_start_typescript_regex(tokens):
                end = position + 1
                in_character_class = False
                while end < len(source) and source[end] not in "\r\n":
                    current = source[end]
                    if current == "\\":
                        end += 2
                        continue
                    if current == "[":
                        in_character_class = True
                    elif current == "]":
                        in_character_class = False
                    elif current == "/" and not in_character_class:
                        end += 1
                        while end < len(source) and source[end].isalpha():
                            end += 1
                        break
                    end += 1
                tokens.append(("expression", "regex"))
                position = end
                continue

            identifier = _TS_IDENTIFIER.match(source, position)
            if identifier:
                tokens.append(("identifier", identifier.group()))
                position = identifier.end()
                continue
            number = _TS_NUMBER.match(source, position)
            if number:
                tokens.append(("expression", "number"))
                position = number.end()
                continue

            operator = next(
                (
                    item
                    for item in ("=>", "?.", "==", "!=", "<=", ">=", "&&", "||", "??")
                    if source.startswith(item, position)
                ),
                char,
            )
            tokens.append(("punct", operator))
            position += len(operator)
        return position

    scan_code(0)
    return tokens


def _can_start_typescript_regex(tokens: list[tuple[str, str]]) -> bool:
    if not tokens:
        return True
    kind, token = tokens[-1]
    return (
        kind == "punct"
        and token in _TS_REGEX_PREFIXES
        or (kind == "identifier" and token in _TS_REGEX_PREFIXES)
    )


def _typescript_import_modules(source: str) -> list[str]:
    """Return statically named TypeScript imports without scanning comments or strings."""
    tokens = _typescript_tokens(source)
    modules: list[str] = []

    def module_at(index: int) -> str | None:
        if index >= len(tokens):
            return None
        kind, token = tokens[index]
        if kind == "string":
            return token
        if kind == "template":
            return token
        return None

    for index, (kind, token) in enumerate(tokens):
        if kind != "identifier":
            continue
        if token == "require" and index + 2 < len(tokens):
            if tokens[index + 1] == ("punct", "("):
                module = module_at(index + 2)
                if module is not None:
                    modules.append(module)
            continue
        if token not in {"import", "export"}:
            continue
        if index + 1 < len(tokens) and tokens[index + 1][0] in {
            "string",
            "template",
        }:
            module = module_at(index + 1)
            if module is not None:
                modules.append(module)
            continue
        if token == "import" and index + 2 < len(tokens):
            if tokens[index + 1] == ("punct", "("):
                module = module_at(index + 2)
                if module is not None:
                    modules.append(module)
                continue
            if tokens[index + 1] == ("punct", "."):
                continue
        for cursor in range(index + 1, len(tokens)):
            next_kind, next_token = tokens[cursor]
            if next_kind == "punct" and next_token == ";":
                break
            if next_kind == "identifier" and next_token in {"import", "export"}:
                break
            if next_kind == "identifier" and next_token == "from":
                module = module_at(cursor + 1)
                if module is not None:
                    modules.append(module)
                break
    return modules


def _typescript_imports_test_support(path: Path) -> bool:
    for module in _typescript_import_modules(path.read_text()):
        parts = [part.lower() for part in module.split("/") if part not in {".", ".."}]
        if any(
            part in {"test", "tests", "__tests__", "test_support"} for part in parts
        ):
            return True
        if parts and re.search(r"test.?fixtures?(?:\.tsx?)?$", parts[-1]):
            return True
    return False


def production_test_support_imports(root: Path) -> list[str]:
    """Return production source paths that import test-only support."""
    violations: list[str] = []
    backend_source = root / "backend/src"
    for path in backend_source.rglob("*.py"):
        if _python_imports_test_support(path):
            violations.append(path.relative_to(root).as_posix())

    web_source = root / "web/src"
    for base in (web_source,):
        for path in (*base.rglob("*.ts"), *base.rglob("*.tsx")):
            relative_parts = path.relative_to(base).parts
            if any(
                part.lower() in {"test", "tests", "__tests__"}
                for part in relative_parts[:-1]
            ):
                continue
            if path.name.lower().endswith(
                (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
            ):
                continue
            if "testfixtures" in path.name.lower():
                continue
            if _typescript_imports_test_support(path):
                violations.append(path.relative_to(root).as_posix())
    return sorted(violations)


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

    failures.extend(
        f"production imports test support: {path}"
        for path in production_test_support_imports(ROOT)
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
