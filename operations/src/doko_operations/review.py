"""Strict review-run state and resumable task orchestration.

The operations package owns review-run coordination, not component annotation or dataset
contracts.  Adapters provide task-specific discovery and publication.  This module keeps the
shared run state task-specific and writes it atomically after every decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .intake import TASKS, BundleInspection, InspectionResult, inspect_repository

REVIEW_RUN_SCHEMA_VERSION = "doko-review-run/v1"
REVIEW_REPORT_SCHEMA_VERSION = "doko-review-report/v1"
REVIEW_TASK_ALL = "all"
REVIEW_RUN_STATES = frozenset({"new", "in_progress", "interrupted", "failed", "complete"})
REVIEW_TASK_STATES = frozenset({"pending", "in_progress", "failed", "complete"})
REVIEW_ITEM_STATES = frozenset({"pending", "complete"})
REVIEW_ACTIONS = frozenset({"human_decision", "approve_split", "resolve_failure", "validate_task"})
REVIEW_TASK_SELECTIONS = frozenset((*TASKS, REVIEW_TASK_ALL))


class ReviewRunError(ValueError):
    """Raised when review-run state or orchestration input is invalid."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ReviewRunError("Review-run values must be finite JSON values.") from exc


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _strict_fields(data: Mapping[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise ReviewRunError(f"{context} has invalid fields ({'; '.join(details)}).")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewRunError(f"{field} must be a non-empty string.")
    return value


def _safe_identifier(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if any(character in result for character in ("/", "\\", "\x00")) or result in {".", ".."}:
        raise ReviewRunError(f"{field} must be a safe identifier.")
    return result


def _digest(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ReviewRunError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _timestamp(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    result = _required_string(value, field)
    if not result.endswith("Z"):
        raise ReviewRunError(f"{field} must use UTC with a Z suffix.")
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as exc:
        raise ReviewRunError(f"{field} must be an ISO-8601 timestamp.") from exc
    if parsed.utcoffset() != datetime.now(UTC).utcoffset():
        raise ReviewRunError(f"{field} must use UTC.")
    return result


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return path.resolve().as_posix()


def _resolve_bundle_path(repository_root: Path, bundle_path: str) -> Path:
    path = Path(bundle_path)
    return path if path.is_absolute() else repository_root / path


@dataclass(frozen=True, slots=True)
class ReviewInput:
    """One selected source and task enrollment presented to an adapter."""

    task: str
    source_asset_id: str
    recording_id: str
    source_sha256: str
    bundle_path: str
    task_enrollment_id: str

    def to_mapping(self) -> dict[str, str]:
        return {
            "task": self.task,
            "source_asset_id": self.source_asset_id,
            "recording_id": self.recording_id,
            "source_sha256": self.source_sha256,
            "bundle_path": self.bundle_path,
            "task_enrollment_id": self.task_enrollment_id,
        }


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One human decision owned by a task adapter."""

    item_id: str
    source_asset_id: str
    kind: str
    prompt: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source_asset_id": self.source_asset_id,
            "kind": self.kind,
            "prompt": self.prompt,
            "state": "pending",
            "decision": None,
            "decided_at_utc": None,
        }


@dataclass(frozen=True, slots=True)
class TaskArtifacts:
    """Validated staged output information returned by an adapter."""

    staged_files: tuple[Path, ...] = ()
    split_approval_required: bool = False


class ReviewAdapter(Protocol):
    """Typed interface for a task-specific review implementation."""

    def discover(self, task: str, inputs: Sequence[ReviewInput]) -> Sequence[ReviewItem]:
        """Return deterministic human-decision items for selected inputs."""

    def apply_decision(
        self,
        task: str,
        item: ReviewItem,
        decision: Mapping[str, Any],
        staging_dir: Path,
    ) -> None:
        """Apply one decision to task-local staged state."""

    def finalize(
        self,
        task: str,
        inputs: Sequence[ReviewInput],
        items: Sequence[Mapping[str, Any]],
        staging_dir: Path,
    ) -> TaskArtifacts:
        """Create task-local staged outputs without publishing them."""

    def validate(self, task: str, staging_dir: Path) -> Sequence[str]:
        """Return validation failures for staged task outputs."""


DecisionProvider = Callable[[ReviewItem], Mapping[str, Any] | None]
SplitApprovalProvider = Callable[[str, Mapping[str, Any]], bool]


class GenericReviewAdapter:
    """Small deterministic adapter used until a component adapter is registered.

    It creates one explicit source-review decision per selected enrollment.  The adapter is useful
    for the orchestration contract and never treats a decision as dataset ground truth.
    """

    def discover(self, task: str, inputs: Sequence[ReviewInput]) -> Sequence[ReviewItem]:
        result: list[ReviewItem] = []
        for item in sorted(inputs, key=lambda value: (value.source_asset_id, value.recording_id)):
            item_id = (
                "item-"
                + _sha256_value(
                    {
                        "task": task,
                        "source_asset_id": item.source_asset_id,
                        "source_sha256": item.source_sha256,
                    }
                )[:20]
            )
            result.append(
                ReviewItem(
                    item_id=item_id,
                    source_asset_id=item.source_asset_id,
                    kind="source_review",
                    prompt=f"Review source asset {item.source_asset_id} for {task}.",
                )
            )
        return result

    def apply_decision(
        self,
        task: str,
        item: ReviewItem,
        decision: Mapping[str, Any],
        staging_dir: Path,
    ) -> None:
        del task, item, staging_dir
        if not isinstance(decision.get("outcome"), str) or not decision["outcome"].strip():
            raise ReviewRunError("A review decision needs a non-empty outcome.")

    def finalize(
        self,
        task: str,
        inputs: Sequence[ReviewInput],
        items: Sequence[Mapping[str, Any]],
        staging_dir: Path,
    ) -> TaskArtifacts:
        staging_dir.mkdir(parents=True, exist_ok=True)
        output = staging_dir / "review-decisions.json"
        payload = {
            "schema_version": "doko-task-review-output/v1",
            "task": task,
            "inputs": [item.to_mapping() for item in inputs],
            "items": [dict(item) for item in items],
        }
        _atomic_write_json(output, payload)
        return TaskArtifacts((output,))

    def validate(self, task: str, staging_dir: Path) -> Sequence[str]:
        output = staging_dir / "review-decisions.json"
        if not output.is_file():
            return (f"{task} staged review output is missing",)
        return ()


def default_adapters() -> dict[str, ReviewAdapter]:
    """Return the deterministic default adapters for both data tasks."""

    from .cardevent import CardEventNetReviewAdapter
    from .table_evidence import TableObservationReviewAdapter

    return {
        "cardevent_event_detection": CardEventNetReviewAdapter(),
        "table_evidence_analysis": TableObservationReviewAdapter(),
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(
                payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
            )
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ReviewRunError(f"Could not write review-run file {path}: {exc}") from exc


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(value)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ReviewRunError(f"Could not write review-run report {path}: {exc}") from exc


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewRunError(f"Could not read review-run file {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ReviewRunError(f"Review-run file must contain an object: {path}")
    return payload


def _validate_decision(value: Any, context: str) -> None:
    if not isinstance(value, Mapping) or not value:
        raise ReviewRunError(f"{context} must be a non-empty object.")
    _canonical_json(value)


def _validate_review_input(value: Any, context: str) -> None:
    if not isinstance(value, Mapping):
        raise ReviewRunError(f"{context} must be an object.")
    fields = {
        "task",
        "source_asset_id",
        "recording_id",
        "source_sha256",
        "bundle_path",
        "task_enrollment_id",
    }
    _strict_fields(value, fields, context)
    if value.get("task") not in TASKS:
        raise ReviewRunError(f"{context}.task is invalid.")
    for field in ("source_asset_id", "recording_id", "task_enrollment_id"):
        _safe_identifier(value.get(field), f"{context}.{field}")
    _digest(value.get("source_sha256"), f"{context}.source_sha256")
    _required_string(value.get("bundle_path"), f"{context}.bundle_path")


def _validate_item(value: Any, context: str) -> None:
    if not isinstance(value, Mapping):
        raise ReviewRunError(f"{context} must be an object.")
    fields = {"item_id", "source_asset_id", "kind", "prompt", "state", "decision", "decided_at_utc"}
    _strict_fields(value, fields, context)
    for field in ("item_id", "source_asset_id", "kind", "prompt"):
        _required_string(value.get(field), f"{context}.{field}")
    state = value.get("state")
    if state not in REVIEW_ITEM_STATES:
        raise ReviewRunError(f"{context}.state is invalid.")
    decision = value.get("decision")
    decided_at = value.get("decided_at_utc")
    if state == "pending":
        if decision is not None or decided_at is not None:
            raise ReviewRunError(f"{context} pending items must not have decisions.")
    else:
        _validate_decision(decision, f"{context}.decision")
        _timestamp(decided_at, f"{context}.decided_at_utc")


def _validate_next_action(value: Any, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ReviewRunError(f"{context} must be an object or null.")
    fields = {"kind", "task", "item_id", "message"}
    _strict_fields(value, fields, context)
    if value.get("kind") not in REVIEW_ACTIONS:
        raise ReviewRunError(f"{context}.kind is invalid.")
    _required_string(value.get("task"), f"{context}.task")
    item_id = value.get("item_id")
    if item_id is not None:
        _safe_identifier(item_id, f"{context}.item_id")
    _required_string(value.get("message"), f"{context}.message")


def _validate_failure(value: Any, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ReviewRunError(f"{context} must be an object or null.")
    _strict_fields(value, {"kind", "message"}, context)
    _required_string(value.get("kind"), f"{context}.kind")
    _required_string(value.get("message"), f"{context}.message")


def _validate_task_state(value: Any, context: str) -> None:
    if not isinstance(value, Mapping):
        raise ReviewRunError(f"{context} must be an object.")
    fields = {
        "task",
        "state",
        "inputs",
        "items",
        "staged_outputs",
        "published_outputs",
        "split_approval_required",
        "split_approved",
        "failure",
    }
    _strict_fields(value, fields, context)
    task = value.get("task")
    if task not in TASKS:
        raise ReviewRunError(f"{context}.task is invalid.")
    if value.get("state") not in REVIEW_TASK_STATES:
        raise ReviewRunError(f"{context}.state is invalid.")
    inputs = value.get("inputs")
    if not isinstance(inputs, list):
        raise ReviewRunError(f"{context}.inputs must be a list.")
    for index, item in enumerate(inputs):
        _validate_review_input(item, f"{context}.inputs[{index}]")
        if item.get("task") != task:
            raise ReviewRunError(f"{context}.inputs[{index}].task does not match task.")
    items = value.get("items")
    if not isinstance(items, list):
        raise ReviewRunError(f"{context}.items must be a list.")
    item_ids: set[str] = set()
    for index, item in enumerate(items):
        _validate_item(item, f"{context}.items[{index}]")
        if item["item_id"] in item_ids:
            raise ReviewRunError(f"{context}.items contains a duplicate item_id.")
        item_ids.add(item["item_id"])
        if item["source_asset_id"] not in {candidate["source_asset_id"] for candidate in inputs}:
            raise ReviewRunError(f"{context}.items[{index}] names an unknown source asset.")
    for field in ("staged_outputs", "published_outputs"):
        values = value.get(field)
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item for item in values
        ):
            raise ReviewRunError(f"{context}.{field} must be a list of paths.")
        if len(values) != len(set(values)):
            raise ReviewRunError(f"{context}.{field} must not contain duplicate paths.")
    if not isinstance(value.get("split_approval_required"), bool) or not isinstance(
        value.get("split_approved"), bool
    ):
        raise ReviewRunError(f"{context} split approval flags must be boolean.")
    if value["split_approved"] and not value["split_approval_required"]:
        raise ReviewRunError(f"{context}.split_approved requires split_approval_required.")
    _validate_failure(value.get("failure"), f"{context}.failure")


def validate_review_run(payload: Mapping[str, Any]) -> None:
    """Validate the strict ``doko-review-run/v1`` state contract."""

    fields = {
        "schema_version",
        "run_id",
        "reviewer",
        "requested_tasks",
        "input_digest",
        "created_at_utc",
        "updated_at_utc",
        "state",
        "tasks",
        "next_action",
        "failure",
        "log_path",
        "report_path",
        "commit_ready_files",
    }
    _strict_fields(payload, fields, "review run")
    if payload.get("schema_version") != REVIEW_RUN_SCHEMA_VERSION:
        raise ReviewRunError("Unsupported review-run schema_version.")
    _safe_identifier(payload.get("run_id"), "review run.run_id")
    _required_string(payload.get("reviewer"), "review run.reviewer")
    requested = payload.get("requested_tasks")
    if (
        not isinstance(requested, list)
        or not requested
        or any(item not in TASKS for item in requested)
    ):
        raise ReviewRunError("review run.requested_tasks is invalid.")
    if len(requested) != len(set(requested)):
        raise ReviewRunError("review run.requested_tasks must not contain duplicates.")
    _digest(payload.get("input_digest"), "review run.input_digest")
    _timestamp(payload.get("created_at_utc"), "review run.created_at_utc")
    _timestamp(payload.get("updated_at_utc"), "review run.updated_at_utc")
    if payload.get("state") not in REVIEW_RUN_STATES:
        raise ReviewRunError("review run.state is invalid.")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or [
        item.get("task") for item in tasks if isinstance(item, Mapping)
    ] != sorted(requested):
        raise ReviewRunError("review run.tasks must list requested tasks in deterministic order.")
    if len(tasks) != len(requested):
        raise ReviewRunError("review run.tasks must contain every requested task exactly once.")
    for index, item in enumerate(tasks):
        _validate_task_state(item, f"review run.tasks[{index}]")
    _validate_next_action(payload.get("next_action"), "review run.next_action")
    _validate_failure(payload.get("failure"), "review run.failure")
    for field in ("log_path", "report_path"):
        _required_string(payload.get(field), f"review run.{field}")
    files = payload.get("commit_ready_files")
    if not isinstance(files, list) or any(not isinstance(item, str) or not item for item in files):
        raise ReviewRunError("review run.commit_ready_files must be a list of paths.")
    if len(files) != len(set(files)):
        raise ReviewRunError("review run.commit_ready_files must not contain duplicates.")


def validate_review_report(payload: Mapping[str, Any]) -> None:
    """Validate the strict concise JSON report contract."""

    fields = {
        "schema_version",
        "run_id",
        "reviewer",
        "requested_tasks",
        "state",
        "tasks",
        "next_action",
        "commit_ready_files",
        "log_path",
        "generated_at_utc",
    }
    _strict_fields(payload, fields, "review report")
    if payload.get("schema_version") != REVIEW_REPORT_SCHEMA_VERSION:
        raise ReviewRunError("Unsupported review-report schema_version.")
    _safe_identifier(payload.get("run_id"), "review report.run_id")
    _required_string(payload.get("reviewer"), "review report.reviewer")
    requested = payload.get("requested_tasks")
    if (
        not isinstance(requested, list)
        or not requested
        or any(item not in TASKS for item in requested)
    ):
        raise ReviewRunError("review report.requested_tasks is invalid.")
    if payload.get("state") not in REVIEW_RUN_STATES:
        raise ReviewRunError("review report.state is invalid.")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != len(requested):
        raise ReviewRunError("review report.tasks is invalid.")
    expected = {
        "task",
        "state",
        "selected_sources",
        "completed_decisions",
        "total_decisions",
        "published_outputs",
        "failure",
    }
    for index, item in enumerate(tasks):
        if not isinstance(item, Mapping):
            raise ReviewRunError(f"review report.tasks[{index}] must be an object.")
        _strict_fields(item, expected, f"review report.tasks[{index}]")
        if item.get("task") not in requested or item.get("state") not in REVIEW_TASK_STATES:
            raise ReviewRunError(f"review report.tasks[{index}] has invalid task or state.")
        if not isinstance(item.get("selected_sources"), list) or any(
            not isinstance(source, str) or not source for source in item["selected_sources"]
        ):
            raise ReviewRunError(f"review report.tasks[{index}].selected_sources is invalid.")
        for field in ("completed_decisions", "total_decisions"):
            if (
                isinstance(item.get(field), bool)
                or not isinstance(item.get(field), int)
                or item[field] < 0
            ):
                raise ReviewRunError(f"review report.tasks[{index}].{field} is invalid.")
        if item["completed_decisions"] > item["total_decisions"]:
            raise ReviewRunError(f"review report.tasks[{index}] decision counts are invalid.")
        if not isinstance(item.get("published_outputs"), list) or any(
            not isinstance(path, str) or not path for path in item["published_outputs"]
        ):
            raise ReviewRunError(f"review report.tasks[{index}].published_outputs is invalid.")
        _validate_failure(item.get("failure"), f"review report.tasks[{index}].failure")
    next_action = payload.get("next_action")
    if next_action is not None:
        _required_string(next_action, "review report.next_action")
    files = payload.get("commit_ready_files")
    if not isinstance(files, list) or any(not isinstance(item, str) or not item for item in files):
        raise ReviewRunError("review report.commit_ready_files is invalid.")
    _required_string(payload.get("log_path"), "review report.log_path")
    _timestamp(payload.get("generated_at_utc"), "review report.generated_at_utc")


def load_review_run(path: str | Path) -> dict[str, Any]:
    payload = dict(_read_json(Path(path)))
    validate_review_run(payload)
    return payload


def load_review_report(path: str | Path) -> dict[str, Any]:
    payload = dict(_read_json(Path(path)))
    validate_review_report(payload)
    return payload


def _inspection_bundle_path(repository_root: Path, inspection: BundleInspection) -> Path:
    return _resolve_bundle_path(repository_root, inspection.path)


def _selected_inputs(
    repository_root: Path,
    inspection_result: InspectionResult,
    requested_tasks: Sequence[str],
) -> tuple[dict[str, tuple[ReviewInput, ...]], dict[str, tuple[str, ...]]]:
    inputs: dict[str, list[ReviewInput]] = {task: [] for task in requested_tasks}
    failures: dict[str, list[str]] = {task: [] for task in requested_tasks}
    inspections_by_path = {item.path: item for item in inspection_result.bundles}
    for failure in inspection_result.failures:
        inspection = inspections_by_path.get(failure.path)
        if inspection is None:
            for task in requested_tasks:
                failures[task].append(f"{failure.path}: {failure.message}")
        else:
            for task_state in inspection.tasks:
                if task_state.task in failures and task_state.disposition == "selected":
                    failures[task_state.task].append(f"{failure.path}: {failure.message}")
    for inspection in inspection_result.bundles:
        for task_state in inspection.tasks:
            if task_state.task not in inputs or task_state.disposition != "selected":
                continue
            if task_state.lifecycle_state not in {"intake", "annotating", "review_required"}:
                continue
            if (
                inspection.state != "complete"
                or not inspection.source_asset_id
                or not inspection.source_sha256
            ):
                continue
            inputs[task_state.task].append(
                ReviewInput(
                    task=task_state.task,
                    source_asset_id=inspection.source_asset_id,
                    recording_id=inspection.recording_id or inspection.source_asset_id,
                    source_sha256=inspection.source_sha256,
                    bundle_path=str(_inspection_bundle_path(repository_root, inspection)),
                    task_enrollment_id=task_state.enrollment_id,
                )
            )
    result_inputs = {
        task: tuple(sorted(values, key=lambda item: (item.source_asset_id, item.recording_id)))
        for task, values in inputs.items()
    }
    result_failures = {task: tuple(sorted(set(values))) for task, values in failures.items()}
    return result_inputs, result_failures


def _input_digest(
    inputs: Mapping[str, Sequence[ReviewInput]], requested_tasks: Sequence[str]
) -> str:
    return _sha256_value(
        {
            "requested_tasks": list(requested_tasks),
            "inputs": {
                task: [item.to_mapping() for item in inputs[task]] for task in requested_tasks
            },
        }
    )


def _run_id(reviewer: str, requested_tasks: Sequence[str], input_digest: str) -> str:
    return (
        "run-"
        + _sha256_value(
            {
                "reviewer": reviewer,
                "requested_tasks": list(requested_tasks),
                "input_digest": input_digest,
            }
        )[:24]
    )


def _task_mapping(payload: Mapping[str, Any], task: str) -> dict[str, Any]:
    return next(item for item in payload["tasks"] if item["task"] == task)


def _input_mapping(inputs: Sequence[ReviewInput]) -> list[dict[str, str]]:
    return [item.to_mapping() for item in inputs]


def _new_task_state(
    task: str, inputs: Sequence[ReviewInput], items: Sequence[ReviewItem]
) -> dict[str, Any]:
    return {
        "task": task,
        "state": "pending",
        "inputs": _input_mapping(inputs),
        "items": [item.to_mapping() for item in items],
        "staged_outputs": [],
        "published_outputs": [],
        "split_approval_required": False,
        "split_approved": False,
        "failure": None,
    }


def _new_run_payload(
    run_id: str,
    reviewer: str,
    requested_tasks: Sequence[str],
    input_digest: str,
    inputs: Mapping[str, Sequence[ReviewInput]],
    discovered_items: Mapping[str, Sequence[ReviewItem]],
    *,
    log_path: str,
    report_path: str,
) -> dict[str, Any]:
    created = _now()
    return {
        "schema_version": REVIEW_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "reviewer": reviewer,
        "requested_tasks": list(requested_tasks),
        "input_digest": input_digest,
        "created_at_utc": created,
        "updated_at_utc": created,
        "state": "new",
        "tasks": [
            _new_task_state(task, inputs[task], discovered_items[task]) for task in requested_tasks
        ],
        "next_action": None,
        "failure": None,
        "log_path": log_path,
        "report_path": report_path,
        "commit_ready_files": [],
    }


def _review_item_from_mapping(value: Mapping[str, Any]) -> ReviewItem:
    return ReviewItem(
        item_id=str(value["item_id"]),
        source_asset_id=str(value["source_asset_id"]),
        kind=str(value["kind"]),
        prompt=str(value["prompt"]),
    )


def _next_action(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    for task_state in payload["tasks"]:
        if task_state["state"] == "failed":
            failure = task_state["failure"] or payload.get("failure")
            message = (failure or {}).get(
                "message", f"Resolve the failed {task_state['task']} task."
            )
            return {
                "kind": "resolve_failure",
                "task": task_state["task"],
                "item_id": None,
                "message": message,
            }
        if task_state["state"] == "complete":
            continue
        for item in task_state["items"]:
            if item["state"] == "pending":
                return {
                    "kind": "human_decision",
                    "task": task_state["task"],
                    "item_id": item["item_id"],
                    "message": (
                        f"Review {item['item_id']} for source asset {item['source_asset_id']}."
                    ),
                }
        if task_state["split_approval_required"] and not task_state["split_approved"]:
            return {
                "kind": "approve_split",
                "task": task_state["task"],
                "item_id": None,
                "message": (
                    f"Approve the proposed split for {task_state['task']} before publication."
                ),
            }
        return {
            "kind": "validate_task",
            "task": task_state["task"],
            "item_id": None,
            "message": f"Validate staged outputs for {task_state['task']}.",
        }
    return None


def _task_complete(task_state: Mapping[str, Any]) -> bool:
    return task_state["state"] == "complete"


def _all_complete(payload: Mapping[str, Any]) -> bool:
    return all(_task_complete(item) for item in payload["tasks"])


def _commit_ready_files(
    run_dir: Path, repository_root: Path, payload: Mapping[str, Any]
) -> list[str]:
    if payload["state"] != "complete":
        return []
    files = [
        _relative_path(run_dir / "state.json", repository_root),
        _relative_path(run_dir / "report.json", repository_root),
        _relative_path(run_dir / "report.md", repository_root),
        _relative_path(run_dir / "run.log", repository_root),
    ]
    for task_state in payload["tasks"]:
        files.extend(task_state["published_outputs"])
    return sorted(dict.fromkeys(files))


def _report_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": REVIEW_REPORT_SCHEMA_VERSION,
        "run_id": payload["run_id"],
        "reviewer": payload["reviewer"],
        "requested_tasks": list(payload["requested_tasks"]),
        "state": payload["state"],
        "tasks": [
            {
                "task": task["task"],
                "state": task["state"],
                "selected_sources": [item["source_asset_id"] for item in task["inputs"]],
                "completed_decisions": sum(item["state"] == "complete" for item in task["items"]),
                "total_decisions": len(task["items"]),
                "published_outputs": list(task["published_outputs"]),
                "failure": task["failure"],
            }
            for task in payload["tasks"]
        ],
        "next_action": (payload["next_action"] or {}).get("message"),
        "commit_ready_files": list(payload["commit_ready_files"]),
        "log_path": payload["log_path"],
        "generated_at_utc": payload["updated_at_utc"],
    }


def _report_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# DokoDetector review run",
        "",
        f"- Run: `{payload['run_id']}`",
        f"- Reviewer: `{payload['reviewer']}`",
        f"- State: `{payload['state']}`",
        "",
        "## Task summary",
        "",
    ]
    for task in payload["tasks"]:
        completed = sum(item["state"] == "complete" for item in task["items"])
        lines.append(
            f"- `{task['task']}`: `{task['state']}`, {completed}/{len(task['items'])} decisions, "
            f"{len(task['published_outputs'])} published outputs"
        )
        if task["failure"]:
            lines.append(f"  - Failure: {task['failure']['message']}")
    lines.extend(["", "## Next action", ""])
    if payload["next_action"]:
        lines.append(f"{payload['next_action']['message']}")
    else:
        lines.append("No further human action is required.")
    lines.extend(["", "## Commit-ready files", ""])
    if payload["commit_ready_files"]:
        lines.extend(f"- `{path}`" for path in payload["commit_ready_files"])
    else:
        lines.append("None. The run is not ready for publication.")
    lines.append("")
    return "\n".join(lines)


def _persist(run_dir: Path, repository_root: Path, payload: dict[str, Any]) -> None:
    payload["updated_at_utc"] = _now()
    payload["commit_ready_files"] = _commit_ready_files(run_dir, repository_root, payload)
    payload["next_action"] = _next_action(payload)
    validate_review_run(payload)
    _atomic_write_json(run_dir / "state.json", payload)
    report = _report_mapping(payload)
    validate_review_report(report)
    _atomic_write_json(run_dir / "report.json", report)
    markdown_path = run_dir / "report.md"
    _atomic_write_text(markdown_path, _report_markdown(payload))


def _log(run_dir: Path, message: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "run.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _set_task_failure(task_state: dict[str, Any], kind: str, message: str) -> None:
    task_state["state"] = "failed"
    task_state["failure"] = {"kind": kind, "message": message}


def _verify_staged_files(staging_dir: Path, files: Sequence[Path]) -> tuple[str, ...]:
    errors: list[str] = []
    for path in files:
        resolved = path.resolve()
        try:
            resolved.relative_to(staging_dir.resolve())
        except ValueError:
            errors.append(f"staged output is outside task staging directory: {path}")
            continue
        if not resolved.is_file():
            errors.append(f"staged output is not a file: {path}")
    return tuple(errors)


def _publish_task(
    task_state: dict[str, Any],
    *,
    task_staging: Path,
    published_root: Path,
    repository_root: Path,
) -> None:
    destination = published_root / task_state["task"]
    if destination.exists():
        raise ReviewRunError(f"Published output already exists for run task: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(task_staging, destination)
    files = sorted(path for path in destination.rglob("*") if path.is_file())
    task_state["published_outputs"] = [_relative_path(path, repository_root) for path in files]
    task_state["staged_outputs"] = []
    task_state["state"] = "complete"
    task_state["failure"] = None


def _prepare_new_run(
    run_dir: Path,
    repository_root: Path,
    reviewer: str,
    requested_tasks: Sequence[str],
    input_digest: str,
    inputs: Mapping[str, Sequence[ReviewInput]],
    adapters: Mapping[str, ReviewAdapter],
    failures: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    discovered_items: dict[str, list[ReviewItem]] = {task: [] for task in requested_tasks}
    discovery_failures: dict[str, list[str]] = {
        task: list(failures[task]) for task in requested_tasks
    }
    for task in requested_tasks:
        if discovery_failures[task]:
            continue
        try:
            discovered_items[task] = list(adapters[task].discover(task, inputs[task]))
        except Exception as exc:  # adapter failures become durable task state
            discovery_failures[task].append(f"Could not discover {task} review work: {exc}")
    run_id = _run_id(reviewer, requested_tasks, input_digest)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = _new_run_payload(
        run_id,
        reviewer,
        requested_tasks,
        input_digest,
        inputs,
        discovered_items,
        log_path=_relative_path(run_dir / "run.log", repository_root),
        report_path=_relative_path(run_dir / "report.md", repository_root),
    )
    for task in requested_tasks:
        if discovery_failures[task]:
            _set_task_failure(
                _task_mapping(payload, task),
                "discovery",
                "; ".join(discovery_failures[task]),
            )
    return payload


def _check_existing_identity(
    payload: Mapping[str, Any], reviewer: str, requested_tasks: Sequence[str], input_digest: str
) -> None:
    if payload["reviewer"] != reviewer:
        raise ReviewRunError("The existing review run belongs to a different reviewer.")
    if payload["requested_tasks"] != list(requested_tasks):
        raise ReviewRunError("The existing review run has a different task selection.")
    if payload["input_digest"] != input_digest:
        raise ReviewRunError("The selected review inputs changed; start a new review run.")


def _reset_failed_task(task_state: dict[str, Any]) -> None:
    if task_state["state"] == "failed":
        task_state["state"] = "in_progress"
        task_state["failure"] = None


def _task_inputs_from_state(task_state: Mapping[str, Any]) -> tuple[ReviewInput, ...]:
    return tuple(
        ReviewInput(
            task=item["task"],
            source_asset_id=item["source_asset_id"],
            recording_id=item["recording_id"],
            source_sha256=item["source_sha256"],
            bundle_path=item["bundle_path"],
            task_enrollment_id=item["task_enrollment_id"],
        )
        for item in task_state["inputs"]
    )


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Stable result returned by a review invocation."""

    run_id: str
    state: str
    run_path: Path
    report_path: Path
    next_action: str | None
    commit_ready_files: tuple[str, ...]
    tasks: tuple[Mapping[str, Any], ...]

    def to_mapping(self, *, repository_root: Path) -> dict[str, Any]:
        del repository_root
        return load_review_report(self.run_path.parent / "report.json")


def _result(payload: Mapping[str, Any], run_dir: Path, repository_root: Path) -> ReviewResult:
    return ReviewResult(
        run_id=payload["run_id"],
        state=payload["state"],
        run_path=run_dir / "state.json",
        report_path=run_dir / "report.md",
        next_action=(payload["next_action"] or {}).get("message"),
        commit_ready_files=tuple(payload["commit_ready_files"]),
        tasks=tuple(payload["tasks"]),
    )


def run_review(
    repository_root: str | Path,
    *,
    task: str,
    reviewer: str,
    bundle_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
    run_id: str | None = None,
    decision_provider: DecisionProvider | None = None,
    split_approval_provider: SplitApprovalProvider | None = None,
    adapters: Mapping[str, ReviewAdapter] | None = None,
) -> ReviewResult:
    """Create or resume a review run and process safe deterministic decisions.

    A missing decision provider is intentional: the command creates durable work and prints the
    exact next human action.  Component adapters can supply an interactive provider later.
    """

    if task not in REVIEW_TASK_SELECTIONS:
        raise ReviewRunError(f"task must be one of: {', '.join(sorted(REVIEW_TASK_SELECTIONS))}")
    reviewer = _required_string(reviewer, "reviewer")
    repository = Path(repository_root).expanduser().resolve()
    if not repository.is_dir():
        raise ReviewRunError(f"Repository root is not a directory: {repository}")
    requested_tasks = tuple(TASKS if task == REVIEW_TASK_ALL else (task,))
    intake_result = inspect_repository(
        repository,
        bundle_root=bundle_root,
        artifacts_root=artifacts_root,
    )
    inputs, discovery_failures = _selected_inputs(repository, intake_result, requested_tasks)
    input_digest = _input_digest(inputs, requested_tasks)
    adapter_map = dict(default_adapters())
    if adapters is not None:
        adapter_map.update(adapters)
    for adapter in adapter_map.values():
        set_reviewer = getattr(adapter, "set_reviewer", None)
        if callable(set_reviewer):
            set_reviewer(reviewer)
    missing_adapters = [task_name for task_name in requested_tasks if task_name not in adapter_map]
    if missing_adapters:
        raise ReviewRunError("No adapter is registered for: " + ", ".join(missing_adapters))
    artifact_path = (
        Path(artifacts_root).expanduser()
        if artifacts_root is not None
        else repository / "data" / "operations"
    )
    if not artifact_path.is_absolute():
        artifact_path = repository / artifact_path
    artifact_path = artifact_path.resolve()
    review_root = artifact_path / "review-runs"
    requested_run_id = run_id or _run_id(reviewer, requested_tasks, input_digest)
    _safe_identifier(requested_run_id, "run_id")
    run_dir = review_root / requested_run_id
    state_path = run_dir / "state.json"
    if state_path.exists():
        payload = load_review_run(state_path)
        _check_existing_identity(payload, reviewer, requested_tasks, input_digest)
        if payload["state"] == "complete":
            return _result(payload, run_dir, repository)
        for task_state in payload["tasks"]:
            if (
                task_state["state"] == "failed"
                and task_state["failure"]
                and task_state["failure"]["kind"] == "discovery"
            ):
                task_name = task_state["task"]
                try:
                    discovered = adapter_map[task_name].discover(
                        task_name, _task_inputs_from_state(task_state)
                    )
                    task_state["items"] = [item.to_mapping() for item in discovered]
                except Exception as exc:  # keep the failure durable until the next retry
                    _set_task_failure(task_state, "discovery", str(exc))
                    continue
            _reset_failed_task(task_state)
    else:
        payload = _prepare_new_run(
            run_dir,
            repository,
            reviewer,
            requested_tasks,
            input_digest,
            inputs,
            adapter_map,
            discovery_failures,
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    _log(run_dir, f"started task selection: {', '.join(requested_tasks)}")
    payload["state"] = "in_progress"
    payload["failure"] = None
    _persist(run_dir, repository, payload)

    for task_name in requested_tasks:
        task_state = _task_mapping(payload, task_name)
        if task_state["state"] == "complete":
            continue
        if task_state["state"] == "failed":
            if len(requested_tasks) == 1:
                payload["state"] = "failed"
                payload["failure"] = task_state["failure"]
                _persist(run_dir, repository, payload)
                continue
            continue
        task_state["state"] = "in_progress"
        if not task_state["inputs"] and not task_state["items"]:
            task_state["state"] = "complete"
            _persist(run_dir, repository, payload)
            continue
        task_inputs = _task_inputs_from_state(task_state)
        adapter = adapter_map[task_name]
        task_staging = run_dir / "staging" / task_name
        try:
            for item_mapping in task_state["items"]:
                if item_mapping["state"] == "complete":
                    continue
                if decision_provider is None:
                    break
                item = _review_item_from_mapping(item_mapping)
                decision = decision_provider(item)
                if decision is None:
                    break
                _validate_decision(decision, f"decision for {item.item_id}")
                # Persist the human decision before adapter work.  A failed adapter cannot cause
                # the operator to repeat a decision that was already accepted by the run.
                item_mapping["decision"] = dict(decision)
                item_mapping["state"] = "complete"
                item_mapping["decided_at_utc"] = _now()
                _persist(run_dir, repository, payload)
                adapter.apply_decision(task_name, item, decision, task_staging)
                _log(run_dir, f"saved decision {item.item_id} for {task_name}")
            if any(item["state"] == "pending" for item in task_state["items"]):
                continue
            if not task_state["staged_outputs"] and not task_state["published_outputs"]:
                staged = adapter.finalize(task_name, task_inputs, task_state["items"], task_staging)
                errors = _verify_staged_files(task_staging, staged.staged_files)
                if errors:
                    raise ReviewRunError("; ".join(errors))
                task_state["staged_outputs"] = [
                    _relative_path(path, repository) for path in staged.staged_files
                ]
                task_state["split_approval_required"] = staged.split_approval_required
                _persist(run_dir, repository, payload)
            if task_state["split_approval_required"] and not task_state["split_approved"]:
                if split_approval_provider is None:
                    continue
                if not split_approval_provider(task_name, task_state):
                    continue
                task_state["split_approved"] = True
                _persist(run_dir, repository, payload)
            validation_errors = tuple(adapter.validate(task_name, task_staging))
            if validation_errors:
                raise ReviewRunError("; ".join(validation_errors))
            _publish_task(
                task_state,
                task_staging=task_staging,
                published_root=artifact_path / "published",
                repository_root=repository,
            )
            _log(run_dir, f"published validated outputs for {task_name}")
            _persist(run_dir, repository, payload)
        except KeyboardInterrupt:
            payload["state"] = "interrupted"
            payload["failure"] = None
            _log(run_dir, f"interrupted while processing {task_name}")
            _persist(run_dir, repository, payload)
            return _result(payload, run_dir, repository)
        except Exception as exc:
            _set_task_failure(task_state, "execution", str(exc))
            _log(run_dir, f"failed {task_name}: {exc}")
            if len(requested_tasks) == 1:
                payload["state"] = "failed"
                payload["failure"] = task_state["failure"]
            _persist(run_dir, repository, payload)

    if any(task_state["state"] == "failed" for task_state in payload["tasks"]):
        payload["state"] = "failed"
        first_failure = next(
            task_state["failure"] for task_state in payload["tasks"] if task_state["failure"]
        )
        payload["failure"] = first_failure
    elif _all_complete(payload):
        payload["state"] = "complete"
        payload["failure"] = None
    else:
        payload["state"] = "in_progress"
        payload["failure"] = None
    _persist(run_dir, repository, payload)
    return _result(payload, run_dir, repository)


def render_review_human(result: ReviewResult, *, repository_root: Path) -> str:
    lines = [
        "DokoDetector review run",
        f"run: {result.run_id}",
        f"state: {result.state}",
        f"state file: {_relative_path(result.run_path, repository_root)}",
        f"report: {_relative_path(result.report_path, repository_root)}",
    ]
    if result.next_action:
        lines.extend(["next action:", f"  {result.next_action}"])
    else:
        lines.extend(["next action:", "  none"])
    lines.append("commit-ready files:")
    if result.commit_ready_files:
        lines.extend(f"  - {path}" for path in result.commit_ready_files)
    else:
        lines.append("  none")
    return "\n".join(lines) + "\n"


def render_review_json(result: ReviewResult, *, repository_root: Path) -> str:
    return (
        json.dumps(result.to_mapping(repository_root=repository_root), indent=2, sort_keys=True)
        + "\n"
    )


__all__ = [
    "DecisionProvider",
    "GenericReviewAdapter",
    "REVIEW_REPORT_SCHEMA_VERSION",
    "REVIEW_RUN_SCHEMA_VERSION",
    "REVIEW_TASK_ALL",
    "ReviewAdapter",
    "ReviewInput",
    "ReviewItem",
    "ReviewResult",
    "ReviewRunError",
    "SplitApprovalProvider",
    "TaskArtifacts",
    "default_adapters",
    "load_review_report",
    "load_review_run",
    "render_review_human",
    "render_review_json",
    "run_review",
    "validate_review_report",
    "validate_review_run",
]
