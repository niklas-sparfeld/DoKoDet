"""Contracts and deterministic comparison for model-improvement campaigns.

M0 only reads campaign artifacts.  Training, export, test evaluation, and promotion are owned by
later milestones.  The contracts in this module are deliberately strict so that a campaign cannot
silently compare different data or replace a component champion with a different component.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

MODEL_REGISTRY_SCHEMA_VERSION = "model-registry/v1"
MODEL_RECIPE_SCHEMA_VERSION = "model-improvement-recipe/v1"
MODEL_GATE_PROFILE_SCHEMA_VERSION = "model-promotion-gate-profile/v1"
MODEL_CAMPAIGN_SCHEMA_VERSION = "model-campaign/v1"
MODEL_COMPARISON_SCHEMA_VERSION = "model-comparison/v1"
MODEL_CANDIDATE_LOCK_SCHEMA_VERSION = "model-candidate-lock/v1"
MODEL_PROMOTION_RECEIPT_SCHEMA_VERSION = "model-promotion-receipt/v1"
MODEL_STATUS_SCHEMA_VERSION = "model-status/v1"

MODEL_COMPONENTS = frozenset({"card-event-net", "table-evidence-analyzer"})
MODEL_COMPONENT_TASKS = {
    "card-event-net": "cardevent_event_detection",
    "table-evidence-analyzer": "table_evidence_analysis",
}
MODEL_CAMPAIGN_STATES = frozenset(
    {
        "created",
        "validated",
        "running",
        "compared",
        "candidate_locked",
        "tested",
        "promotion_recommended",
        "keep_champion_recommended",
        "human_review_required",
        "promoted",
        "failed",
        "cancelled",
    }
)
MODEL_RECOMMENDATIONS = frozenset(
    {"promote_candidate", "keep_champion", "human_review_required", "no_valid_candidate"}
)
MODEL_EVALUATION_STATES = frozenset({"success", "failed", "interrupted", "skipped"})
MODEL_GATE_STATES = frozenset({"passed", "failed", "not_applicable"})
MODEL_GATE_OPERATORS = frozenset({"min", "max", "equals"})
MODEL_PROMOTION_STATES = frozenset({"promoted", "failed"})
MODEL_PROMOTION_REGISTRY_UPDATES = frozenset({"updated", "unchanged"})
MODEL_SELECTION_DIRECTIONS = frozenset({"maximize", "minimize"})
MODEL_TASKS = frozenset({"cardevent_event_detection", "table_evidence_analysis"})

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ModelImprovementError(ValueError):
    """Raised when a model-improvement artifact is invalid or incompatible."""


def _strict(data: Mapping[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise ModelImprovementError(f"{context} has invalid fields ({'; '.join(details)}).")


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelImprovementError(f"{context} must be an object.")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelImprovementError(f"{field} must be a non-empty string.")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _string(value, field)
    if _IDENTIFIER.fullmatch(result) is None:
        raise ModelImprovementError(f"{field} must be a safe identifier.")
    return result


def _digest(value: Any, field: str) -> str:
    result = _string(value, field)
    if _DIGEST.fullmatch(result) is None:
        raise ModelImprovementError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ModelImprovementError(f"{field} must be a positive integer.")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelImprovementError(f"{field} must be a non-negative integer.")
    return value


def _finite_number(value: Any, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ModelImprovementError(f"{field} must be a finite number.")
    return value


def _finite_json(value: Any, field: str) -> Any:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ModelImprovementError(f"{field} must contain finite JSON values.") from error
    return value


def _timestamp(value: Any, field: str) -> str:
    result = _string(value, field)
    if not result.endswith("Z"):
        raise ModelImprovementError(f"{field} must use UTC with a Z suffix.")
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as error:
        raise ModelImprovementError(f"{field} must be an ISO-8601 timestamp.") from error
    if parsed.utcoffset() != timedelta(0):
        raise ModelImprovementError(f"{field} must use UTC.")
    return result


def _safe_relative_path(value: Any, field: str) -> str:
    result = _string(value, field)
    path = PurePosixPath(result)
    if path.is_absolute() or ".." in path.parts or "\\" in result or path.name in {"", "."}:
        raise ModelImprovementError(f"{field} must be a safe relative path.")
    return result


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ModelImprovementError(f"{field} must be a list.")
    return value


def _optional_pair(
    identifier: Any, digest: Any, identifier_field: str, digest_field: str
) -> tuple[str | None, str | None]:
    if (identifier is None) != (digest is None):
        raise ModelImprovementError(
            f"{identifier_field} and {digest_field} must be both set or null."
        )
    if identifier is None:
        return None, None
    return _identifier(identifier, identifier_field), _digest(digest, digest_field)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as error:
        raise ModelImprovementError("Values must be finite JSON values.") from error


def sha256_mapping(value: Mapping[str, Any]) -> str:
    """Return the deterministic digest used for resolved recipe and artifact references."""

    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """An immutable artifact identifier and its content digest."""

    id: str
    digest: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "artifact") -> "ArtifactReference":
        data = _object(raw, context)
        _strict(data, {"id", "digest"}, context)
        return cls(
            _identifier(data["id"], f"{context}.id"), _digest(data["digest"], f"{context}.digest")
        )

    def to_mapping(self) -> dict[str, str]:
        return {"id": self.id, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class DataContext:
    """The frozen data contract shared by champion and candidate evaluations."""

    dataset: ArtifactReference
    split: ArtifactReference
    source_annotation: ArtifactReference | None
    review: ArtifactReference | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DataContext":
        data = _object(raw, "data_context")
        _strict(data, {"dataset", "split", "source_annotation", "review"}, "data_context")
        annotation = (
            None
            if data["source_annotation"] is None
            else ArtifactReference.from_mapping(
                data["source_annotation"], "data_context.source_annotation"
            )
        )
        review = (
            None
            if data["review"] is None
            else ArtifactReference.from_mapping(data["review"], "data_context.review")
        )
        return cls(
            dataset=ArtifactReference.from_mapping(data["dataset"], "data_context.dataset"),
            split=ArtifactReference.from_mapping(data["split"], "data_context.split"),
            source_annotation=annotation,
            review=review,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset.to_mapping(),
            "split": self.split.to_mapping(),
            "source_annotation": (
                None if self.source_annotation is None else self.source_annotation.to_mapping()
            ),
            "review": None if self.review is None else self.review.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class ExportContract:
    """Export environment and runtime compatibility recorded for a champion."""

    environment: Mapping[str, Any]
    compatibility: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "export") -> "ExportContract":
        data = _object(raw, context)
        _strict(data, {"environment", "compatibility"}, context)
        environment = _object(data["environment"], f"{context}.environment")
        _finite_json(environment, f"{context}.environment")
        return cls(
            environment=dict(environment),
            compatibility=_string(data["compatibility"], f"{context}.compatibility"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {"environment": dict(self.environment), "compatibility": self.compatibility}


@dataclass(frozen=True, slots=True)
class ChampionModel:
    """One component-specific champion entry."""

    component: str
    capability: str
    champion_bundle: ArtifactReference
    bundle_path: str
    runtime_contract_version: str
    input_contract_version: str
    data: DataContext
    validation_report_id: str
    sealed_test_report_id: str | None
    export: ExportContract
    promotion_receipt_id: str
    decision_note: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ChampionModel":
        data = _object(raw, "champion entry")
        fields = {
            "component",
            "capability",
            "champion_bundle_id",
            "champion_bundle_digest",
            "bundle_path",
            "runtime_contract_version",
            "input_contract_version",
            "dataset_version_id",
            "dataset_version_digest",
            "split_version_id",
            "split_version_digest",
            "annotation_version_id",
            "annotation_version_digest",
            "review_version_id",
            "review_version_digest",
            "validation_report_id",
            "sealed_test_report_id",
            "export",
            "promotion_receipt_id",
            "decision_note",
        }
        _strict(data, fields, "champion entry")
        component = _component(data["component"], "champion entry.component")
        annotation_id, annotation_digest = _optional_pair(
            data["annotation_version_id"],
            data["annotation_version_digest"],
            "annotation_version_id",
            "annotation_version_digest",
        )
        review_id, review_digest = _optional_pair(
            data["review_version_id"],
            data["review_version_digest"],
            "review_version_id",
            "review_version_digest",
        )
        return cls(
            component=component,
            capability=_identifier(data["capability"], "champion entry.capability"),
            champion_bundle=ArtifactReference(
                _identifier(data["champion_bundle_id"], "champion_bundle_id"),
                _digest(data["champion_bundle_digest"], "champion_bundle_digest"),
            ),
            bundle_path=_safe_relative_path(data["bundle_path"], "bundle_path"),
            runtime_contract_version=_string(
                data["runtime_contract_version"], "runtime_contract_version"
            ),
            input_contract_version=_string(
                data["input_contract_version"], "input_contract_version"
            ),
            data=DataContext(
                dataset=ArtifactReference(
                    _identifier(data["dataset_version_id"], "dataset_version_id"),
                    _digest(data["dataset_version_digest"], "dataset_version_digest"),
                ),
                split=ArtifactReference(
                    _identifier(data["split_version_id"], "split_version_id"),
                    _digest(data["split_version_digest"], "split_version_digest"),
                ),
                source_annotation=(
                    None
                    if annotation_id is None
                    else ArtifactReference(annotation_id, annotation_digest or "")
                ),
                review=(
                    None if review_id is None else ArtifactReference(review_id, review_digest or "")
                ),
            ),
            validation_report_id=_identifier(data["validation_report_id"], "validation_report_id"),
            sealed_test_report_id=(
                None
                if data["sealed_test_report_id"] is None
                else _identifier(data["sealed_test_report_id"], "sealed_test_report_id")
            ),
            export=ExportContract.from_mapping(data["export"]),
            promotion_receipt_id=_identifier(data["promotion_receipt_id"], "promotion_receipt_id"),
            decision_note=_string(data["decision_note"], "decision_note"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "capability": self.capability,
            "champion_bundle_id": self.champion_bundle.id,
            "champion_bundle_digest": self.champion_bundle.digest,
            "bundle_path": self.bundle_path,
            "runtime_contract_version": self.runtime_contract_version,
            "input_contract_version": self.input_contract_version,
            "dataset_version_id": self.data.dataset.id,
            "dataset_version_digest": self.data.dataset.digest,
            "split_version_id": self.data.split.id,
            "split_version_digest": self.data.split.digest,
            "annotation_version_id": (
                None if self.data.source_annotation is None else self.data.source_annotation.id
            ),
            "annotation_version_digest": (
                None if self.data.source_annotation is None else self.data.source_annotation.digest
            ),
            "review_version_id": None if self.data.review is None else self.data.review.id,
            "review_version_digest": None if self.data.review is None else self.data.review.digest,
            "validation_report_id": self.validation_report_id,
            "sealed_test_report_id": self.sealed_test_report_id,
            "export": self.export.to_mapping(),
            "promotion_receipt_id": self.promotion_receipt_id,
            "decision_note": self.decision_note,
        }


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """Independent champion entries for each component capability."""

    registry_version: int
    champions: tuple[ChampionModel, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ModelRegistry":
        data = _object(raw, "model registry")
        _strict(data, {"schema_version", "registry_version", "champions"}, "model registry")
        if data["schema_version"] != MODEL_REGISTRY_SCHEMA_VERSION:
            raise ModelImprovementError("model registry has an unsupported schema_version.")
        champions = tuple(
            ChampionModel.from_mapping(item) for item in _list(data["champions"], "champions")
        )
        keys = [(item.component, item.capability) for item in champions]
        if len(keys) != len(set(keys)):
            raise ModelImprovementError(
                "model registry cannot contain duplicate component champions."
            )
        return cls(_positive_int(data["registry_version"], "registry_version"), champions)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_REGISTRY_SCHEMA_VERSION,
            "registry_version": self.registry_version,
            "champions": [
                item.to_mapping()
                for item in sorted(
                    self.champions, key=lambda value: (value.component, value.capability)
                )
            ],
        }

    def champion_for(self, component: str, capability: str) -> ChampionModel | None:
        return next(
            (
                item
                for item in self.champions
                if item.component == component and item.capability == capability
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    candidate_id: str
    experiment_family: str
    configuration: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "candidate") -> "CandidateSpec":
        data = _object(raw, context)
        _strict(data, {"candidate_id", "experiment_family", "configuration"}, context)
        configuration = _object(data["configuration"], f"{context}.configuration")
        _finite_json(configuration, f"{context}.configuration")
        return cls(
            _identifier(data["candidate_id"], f"{context}.candidate_id"),
            _identifier(data["experiment_family"], f"{context}.experiment_family"),
            dict(configuration),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "experiment_family": self.experiment_family,
            "configuration": dict(self.configuration),
        }


@dataclass(frozen=True, slots=True)
class ExperimentBudget:
    max_candidates: int
    max_compute_minutes: int
    max_failures: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ExperimentBudget":
        data = _object(raw, "budget")
        _strict(data, {"max_candidates", "max_compute_minutes", "max_failures"}, "budget")
        return cls(
            _positive_int(data["max_candidates"], "budget.max_candidates"),
            _positive_int(data["max_compute_minutes"], "budget.max_compute_minutes"),
            _non_negative_int(data["max_failures"], "budget.max_failures"),
        )

    def to_mapping(self) -> dict[str, int]:
        return {
            "max_candidates": self.max_candidates,
            "max_compute_minutes": self.max_compute_minutes,
            "max_failures": self.max_failures,
        }


@dataclass(frozen=True, slots=True)
class ExecutionContract:
    device: str
    precision: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ExecutionContract":
        data = _object(raw, "execution")
        _strict(data, {"device", "precision"}, "execution")
        return cls(
            _string(data["device"], "execution.device"),
            _string(data["precision"], "execution.precision"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {"device": self.device, "precision": self.precision}


@dataclass(frozen=True, slots=True)
class SelectionMetric:
    metric: str
    direction: str

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "selection metric"
    ) -> "SelectionMetric":
        data = _object(raw, context)
        _strict(data, {"metric", "direction"}, context)
        direction = _string(data["direction"], f"{context}.direction")
        if direction not in MODEL_SELECTION_DIRECTIONS:
            raise ModelImprovementError(f"{context}.direction is not supported.")
        return cls(_string(data["metric"], f"{context}.metric"), direction)

    def to_mapping(self) -> dict[str, str]:
        return {"metric": self.metric, "direction": self.direction}


@dataclass(frozen=True, slots=True)
class ModelRecipe:
    recipe_id: str
    recipe_version: int
    component: str
    capability: str
    task: str
    baseline_bundle: ArtifactReference
    data: DataContext
    experiment_axes: tuple[str, ...]
    candidates: tuple[CandidateSpec, ...]
    seeds: tuple[int, ...]
    repeat_policy: str
    budget: ExperimentBudget
    execution: ExecutionContract
    selection_metrics: tuple[SelectionMetric, ...]
    gate_profile_id: str
    export_compatibility: str
    sealed_test_authorized: bool

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ModelRecipe":
        data = _object(raw, "model recipe")
        _strict(
            data,
            {
                "schema_version",
                "recipe_id",
                "recipe_version",
                "component",
                "capability",
                "task",
                "baseline_bundle",
                "data",
                "experiment_axes",
                "candidates",
                "seeds",
                "repeat_policy",
                "budget",
                "execution",
                "selection_metrics",
                "gate_profile_id",
                "export_compatibility",
                "sealed_test_authorized",
            },
            "model recipe",
        )
        if data["schema_version"] != MODEL_RECIPE_SCHEMA_VERSION:
            raise ModelImprovementError("model recipe has an unsupported schema_version.")
        candidates = tuple(
            CandidateSpec.from_mapping(item, f"candidates[{index}]")
            for index, item in enumerate(_list(data["candidates"], "candidates"))
        )
        if not candidates:
            raise ModelImprovementError("model recipe must declare at least one candidate.")
        candidate_ids = [item.candidate_id for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ModelImprovementError("model recipe candidate IDs must be unique.")
        experiment_axes = tuple(
            _identifier(value, f"experiment_axes[{index}]")
            for index, value in enumerate(_list(data["experiment_axes"], "experiment_axes"))
        )
        if not experiment_axes:
            raise ModelImprovementError("model recipe must declare experiment axes.")
        if any(item.experiment_family not in experiment_axes for item in candidates):
            raise ModelImprovementError("every candidate must use a declared experiment axis.")
        seeds = tuple(
            _positive_int(value, f"seeds[{index}]")
            for index, value in enumerate(_list(data["seeds"], "seeds"))
        )
        if not seeds:
            raise ModelImprovementError("model recipe must declare at least one seed.")
        budget = ExperimentBudget.from_mapping(data["budget"])
        if len(candidates) > budget.max_candidates:
            raise ModelImprovementError("model recipe declares more candidates than its budget.")
        selection_metrics = tuple(
            SelectionMetric.from_mapping(item, f"selection_metrics[{index}]")
            for index, item in enumerate(_list(data["selection_metrics"], "selection_metrics"))
        )
        if not selection_metrics:
            raise ModelImprovementError("model recipe must declare selection metrics.")
        task = _string(data["task"], "model recipe.task")
        if task not in MODEL_TASKS:
            raise ModelImprovementError("model recipe.task is not supported.")
        component = _component(data["component"], "model recipe.component")
        _component_task(component, task, "model recipe")
        return cls(
            recipe_id=_identifier(data["recipe_id"], "recipe_id"),
            recipe_version=_positive_int(data["recipe_version"], "recipe_version"),
            component=component,
            capability=_identifier(data["capability"], "model recipe.capability"),
            task=task,
            baseline_bundle=ArtifactReference.from_mapping(
                data["baseline_bundle"], "baseline_bundle"
            ),
            data=DataContext.from_mapping(data["data"]),
            experiment_axes=experiment_axes,
            candidates=candidates,
            seeds=seeds,
            repeat_policy=_string(data["repeat_policy"], "repeat_policy"),
            budget=budget,
            execution=ExecutionContract.from_mapping(data["execution"]),
            selection_metrics=selection_metrics,
            gate_profile_id=_identifier(data["gate_profile_id"], "gate_profile_id"),
            export_compatibility=_string(data["export_compatibility"], "export_compatibility"),
            sealed_test_authorized=data["sealed_test_authorized"]
            if isinstance(data["sealed_test_authorized"], bool)
            else (_raise_bool("sealed_test_authorized")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_RECIPE_SCHEMA_VERSION,
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "component": self.component,
            "capability": self.capability,
            "task": self.task,
            "baseline_bundle": self.baseline_bundle.to_mapping(),
            "data": self.data.to_mapping(),
            "experiment_axes": list(self.experiment_axes),
            "candidates": [item.to_mapping() for item in self.candidates],
            "seeds": list(self.seeds),
            "repeat_policy": self.repeat_policy,
            "budget": self.budget.to_mapping(),
            "execution": self.execution.to_mapping(),
            "selection_metrics": [item.to_mapping() for item in self.selection_metrics],
            "gate_profile_id": self.gate_profile_id,
            "export_compatibility": self.export_compatibility,
            "sealed_test_authorized": self.sealed_test_authorized,
        }

    @property
    def digest(self) -> str:
        return sha256_mapping(self.to_mapping())


@dataclass(frozen=True, slots=True)
class GateDefinition:
    gate_id: str
    metric: str
    operator: str
    threshold: int | float | bool
    hard: bool
    min_support: int | None
    support_metric: str | None
    description: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "gate") -> "GateDefinition":
        data = _object(raw, context)
        _strict(
            data,
            {
                "gate_id",
                "metric",
                "operator",
                "threshold",
                "hard",
                "min_support",
                "support_metric",
                "description",
            },
            context,
        )
        operator = _string(data["operator"], f"{context}.operator")
        if operator not in MODEL_GATE_OPERATORS:
            raise ModelImprovementError(f"{context}.operator is not supported.")
        threshold = data["threshold"]
        if operator == "equals":
            if not isinstance(threshold, bool):
                raise ModelImprovementError(
                    f"{context}.threshold must be boolean for equals gates."
                )
        else:
            threshold = _finite_number(threshold, f"{context}.threshold")
        hard = data["hard"] if isinstance(data["hard"], bool) else _raise_bool(f"{context}.hard")
        min_support = data["min_support"]
        if min_support is not None:
            min_support = _positive_int(min_support, f"{context}.min_support")
        support_metric = (
            None
            if data["support_metric"] is None
            else _string(data["support_metric"], f"{context}.support_metric")
        )
        if min_support is not None and support_metric is None:
            raise ModelImprovementError(f"{context}.support_metric is required with min_support.")
        return cls(
            _identifier(data["gate_id"], f"{context}.gate_id"),
            _string(data["metric"], f"{context}.metric"),
            operator,
            threshold,
            hard,
            min_support,
            support_metric,
            _string(data["description"], f"{context}.description"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "hard": self.hard,
            "min_support": self.min_support,
            "support_metric": self.support_metric,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class NonInferiorityRule:
    metric: str
    max_regression: float
    hard: bool

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "non-inferiority"
    ) -> "NonInferiorityRule":
        data = _object(raw, context)
        _strict(data, {"metric", "max_regression", "hard"}, context)
        hard = data["hard"] if isinstance(data["hard"], bool) else _raise_bool(f"{context}.hard")
        regression = _finite_number(data["max_regression"], f"{context}.max_regression")
        if regression < 0:
            raise ModelImprovementError(f"{context}.max_regression must not be negative.")
        return cls(_string(data["metric"], f"{context}.metric"), float(regression), hard)

    def to_mapping(self) -> dict[str, Any]:
        return {"metric": self.metric, "max_regression": self.max_regression, "hard": self.hard}


@dataclass(frozen=True, slots=True)
class GateProfile:
    gate_profile_id: str
    component: str
    capability: str
    gates: tuple[GateDefinition, ...]
    non_inferiority: tuple[NonInferiorityRule, ...]
    selection_metrics: tuple[SelectionMetric, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "GateProfile":
        data = _object(raw, "gate profile")
        _strict(
            data,
            {
                "schema_version",
                "gate_profile_id",
                "component",
                "capability",
                "gates",
                "non_inferiority",
                "selection_metrics",
            },
            "gate profile",
        )
        if data["schema_version"] != MODEL_GATE_PROFILE_SCHEMA_VERSION:
            raise ModelImprovementError("gate profile has an unsupported schema_version.")
        gates = tuple(
            GateDefinition.from_mapping(item, f"gates[{index}]")
            for index, item in enumerate(_list(data["gates"], "gates"))
        )
        gate_ids = [item.gate_id for item in gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise ModelImprovementError("gate profile gate IDs must be unique.")
        non_inferiority = tuple(
            NonInferiorityRule.from_mapping(item, f"non_inferiority[{index}]")
            for index, item in enumerate(_list(data["non_inferiority"], "non_inferiority"))
        )
        selection = tuple(
            SelectionMetric.from_mapping(item, f"selection_metrics[{index}]")
            for index, item in enumerate(_list(data["selection_metrics"], "selection_metrics"))
        )
        if not gates or not selection:
            raise ModelImprovementError("gate profile needs gates and selection metrics.")
        return cls(
            _identifier(data["gate_profile_id"], "gate_profile_id"),
            _component(data["component"], "gate profile.component"),
            _identifier(data["capability"], "gate profile.capability"),
            gates,
            non_inferiority,
            selection,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_GATE_PROFILE_SCHEMA_VERSION,
            "gate_profile_id": self.gate_profile_id,
            "component": self.component,
            "capability": self.capability,
            "gates": [item.to_mapping() for item in self.gates],
            "non_inferiority": [item.to_mapping() for item in self.non_inferiority],
            "selection_metrics": [item.to_mapping() for item in self.selection_metrics],
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    status: str
    hard: bool
    observed: int | float | bool | None
    threshold: int | float | bool
    reason: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "gate result") -> "GateResult":
        data = _object(raw, context)
        _strict(data, {"gate_id", "status", "hard", "observed", "threshold", "reason"}, context)
        status = _string(data["status"], f"{context}.status")
        if status not in MODEL_GATE_STATES:
            raise ModelImprovementError(f"{context}.status is not supported.")
        hard = data["hard"] if isinstance(data["hard"], bool) else _raise_bool(f"{context}.hard")
        observed = data["observed"]
        if observed is not None:
            observed = (
                observed
                if isinstance(observed, bool)
                else _finite_number(observed, f"{context}.observed")
            )
        threshold = data["threshold"]
        if not isinstance(threshold, bool):
            threshold = _finite_number(threshold, f"{context}.threshold")
        return cls(
            _identifier(data["gate_id"], f"{context}.gate_id"),
            status,
            hard,
            observed,
            threshold,
            _string(data["reason"], f"{context}.reason"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "status": self.status,
            "hard": self.hard,
            "observed": self.observed,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    evaluation_id: str
    role: str
    candidate_id: str | None
    run_id: str
    bundle: ArtifactReference
    state: str
    data: DataContext
    metrics: Mapping[str, Any]
    gates: tuple[GateResult, ...]
    failure_reason: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "evaluation") -> "ModelEvaluation":
        data = _object(raw, context)
        _strict(
            data,
            {
                "evaluation_id",
                "role",
                "candidate_id",
                "run_id",
                "bundle",
                "state",
                "data",
                "metrics",
                "gates",
                "failure_reason",
            },
            context,
        )
        role = _string(data["role"], f"{context}.role")
        if role not in {"champion", "candidate"}:
            raise ModelImprovementError(f"{context}.role is not supported.")
        candidate_id = (
            None
            if data["candidate_id"] is None
            else _identifier(data["candidate_id"], f"{context}.candidate_id")
        )
        if (role == "champion") != (candidate_id is None):
            raise ModelImprovementError(f"{context}.candidate_id does not match its role.")
        state = _string(data["state"], f"{context}.state")
        if state not in MODEL_EVALUATION_STATES:
            raise ModelImprovementError(f"{context}.state is not supported.")
        metrics = _object(data["metrics"], f"{context}.metrics")
        _finite_json(metrics, f"{context}.metrics")
        gates = tuple(
            GateResult.from_mapping(item, f"{context}.gates[{index}]")
            for index, item in enumerate(_list(data["gates"], f"{context}.gates"))
        )
        failure_reason = (
            None
            if data["failure_reason"] is None
            else _string(data["failure_reason"], f"{context}.failure_reason")
        )
        if state == "success" and failure_reason is not None:
            raise ModelImprovementError(f"{context}.success evaluation cannot have failure_reason.")
        if state != "success" and failure_reason is None:
            raise ModelImprovementError(f"{context} non-success evaluation needs failure_reason.")
        return cls(
            _identifier(data["evaluation_id"], f"{context}.evaluation_id"),
            role,
            candidate_id,
            _identifier(data["run_id"], f"{context}.run_id"),
            ArtifactReference.from_mapping(data["bundle"], f"{context}.bundle"),
            state,
            DataContext.from_mapping(data["data"]),
            dict(metrics),
            gates,
            failure_reason,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "role": self.role,
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "bundle": self.bundle.to_mapping(),
            "state": self.state,
            "data": self.data.to_mapping(),
            "metrics": dict(self.metrics),
            "gates": [item.to_mapping() for item in self.gates],
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True, slots=True)
class CandidateRunReference:
    candidate_id: str
    run_id: str
    state: str
    run_digest: str
    checkpoint_id: str | None
    result_digest: str | None
    failure_reason: str | None

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "candidate run"
    ) -> "CandidateRunReference":
        data = _object(raw, context)
        _strict(
            data,
            {
                "candidate_id",
                "run_id",
                "state",
                "run_digest",
                "checkpoint_id",
                "result_digest",
                "failure_reason",
            },
            context,
        )
        state = _string(data["state"], f"{context}.state")
        if state not in MODEL_EVALUATION_STATES:
            raise ModelImprovementError(f"{context}.state is not supported.")
        checkpoint_id = (
            None
            if data["checkpoint_id"] is None
            else _identifier(data["checkpoint_id"], f"{context}.checkpoint_id")
        )
        result_digest = (
            None
            if data["result_digest"] is None
            else _digest(data["result_digest"], f"{context}.result_digest")
        )
        failure_reason = (
            None
            if data["failure_reason"] is None
            else _string(data["failure_reason"], f"{context}.failure_reason")
        )
        if state == "success" and (
            checkpoint_id is None or result_digest is None or failure_reason is not None
        ):
            raise ModelImprovementError(
                f"{context}.success run needs a checkpoint and result digest."
            )
        if state != "success" and failure_reason is None:
            raise ModelImprovementError(f"{context} non-success run needs failure_reason.")
        return cls(
            _identifier(data["candidate_id"], f"{context}.candidate_id"),
            _identifier(data["run_id"], f"{context}.run_id"),
            state,
            _digest(data["run_digest"], f"{context}.run_digest"),
            checkpoint_id,
            result_digest,
            failure_reason,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "state": self.state,
            "run_digest": self.run_digest,
            "checkpoint_id": self.checkpoint_id,
            "result_digest": self.result_digest,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True, slots=True)
class ModelCampaign:
    campaign_id: str
    component: str
    capability: str
    task: str
    recipe_id: str
    recipe_digest: str
    baseline_bundle: ArtifactReference
    data: DataContext
    state: str
    created_at_utc: str
    updated_at_utc: str
    candidate_runs: tuple[CandidateRunReference, ...]
    comparison_id: str | None
    lock_id: str | None
    test_evaluation_id: str | None
    promotion_receipt_id: str | None
    recommendation: str | None
    failure_reason: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ModelCampaign":
        data = _object(raw, "model campaign")
        _strict(
            data,
            {
                "schema_version",
                "campaign_id",
                "component",
                "capability",
                "task",
                "recipe_id",
                "recipe_digest",
                "baseline_bundle",
                "data",
                "state",
                "created_at_utc",
                "updated_at_utc",
                "candidate_runs",
                "comparison_id",
                "lock_id",
                "test_evaluation_id",
                "promotion_receipt_id",
                "recommendation",
                "failure_reason",
            },
            "model campaign",
        )
        if data["schema_version"] != MODEL_CAMPAIGN_SCHEMA_VERSION:
            raise ModelImprovementError("model campaign has an unsupported schema_version.")
        state = _string(data["state"], "campaign.state")
        if state not in MODEL_CAMPAIGN_STATES:
            raise ModelImprovementError("campaign.state is not supported.")
        recommendation = (
            None
            if data["recommendation"] is None
            else _string(data["recommendation"], "campaign.recommendation")
        )
        if recommendation is not None and recommendation not in MODEL_RECOMMENDATIONS:
            raise ModelImprovementError("campaign.recommendation is not supported.")
        ids = [
            ("comparison_id", data["comparison_id"]),
            ("lock_id", data["lock_id"]),
            ("test_evaluation_id", data["test_evaluation_id"]),
            ("promotion_receipt_id", data["promotion_receipt_id"]),
        ]
        optional_ids = {
            name: (None if value is None else _identifier(value, f"campaign.{name}"))
            for name, value in ids
        }
        failure_reason = (
            None
            if data["failure_reason"] is None
            else _string(data["failure_reason"], "campaign.failure_reason")
        )
        if state in {"failed", "cancelled"} and failure_reason is None:
            raise ModelImprovementError(f"campaign.{state} needs failure_reason.")
        if state == "promoted" and optional_ids["promotion_receipt_id"] is None:
            raise ModelImprovementError("promoted campaign needs promotion_receipt_id.")
        if (
            state
            in {
                "compared",
                "candidate_locked",
                "tested",
                "promotion_recommended",
                "human_review_required",
                "keep_champion_recommended",
                "promoted",
            }
            and optional_ids["comparison_id"] is None
        ):
            raise ModelImprovementError(f"campaign.{state} needs comparison_id.")
        if (
            state in {"candidate_locked", "tested", "promotion_recommended", "promoted"}
            and optional_ids["lock_id"] is None
        ):
            raise ModelImprovementError(f"campaign.{state} needs lock_id.")
        if (
            state in {"tested", "promotion_recommended", "promoted"}
            and optional_ids["test_evaluation_id"] is None
        ):
            raise ModelImprovementError(f"campaign.{state} needs test_evaluation_id.")
        candidate_runs = tuple(
            CandidateRunReference.from_mapping(item, f"candidate_runs[{index}]")
            for index, item in enumerate(_list(data["candidate_runs"], "candidate_runs"))
        )
        candidate_ids = [item.candidate_id for item in candidate_runs]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ModelImprovementError("campaign candidate IDs must be unique.")
        task = _string(data["task"], "campaign.task")
        if task not in MODEL_TASKS:
            raise ModelImprovementError("campaign.task is not supported.")
        component = _component(data["component"], "campaign.component")
        _component_task(component, task, "campaign")
        return cls(
            _identifier(data["campaign_id"], "campaign_id"),
            component,
            _identifier(data["capability"], "campaign.capability"),
            task,
            _identifier(data["recipe_id"], "recipe_id"),
            _digest(data["recipe_digest"], "recipe_digest"),
            ArtifactReference.from_mapping(data["baseline_bundle"], "campaign.baseline_bundle"),
            DataContext.from_mapping(data["data"]),
            state,
            _timestamp(data["created_at_utc"], "campaign.created_at_utc"),
            _timestamp(data["updated_at_utc"], "campaign.updated_at_utc"),
            candidate_runs,
            optional_ids["comparison_id"],
            optional_ids["lock_id"],
            optional_ids["test_evaluation_id"],
            optional_ids["promotion_receipt_id"],
            recommendation,
            failure_reason,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_CAMPAIGN_SCHEMA_VERSION,
            "campaign_id": self.campaign_id,
            "component": self.component,
            "capability": self.capability,
            "task": self.task,
            "recipe_id": self.recipe_id,
            "recipe_digest": self.recipe_digest,
            "baseline_bundle": self.baseline_bundle.to_mapping(),
            "data": self.data.to_mapping(),
            "state": self.state,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "candidate_runs": [item.to_mapping() for item in self.candidate_runs],
            "comparison_id": self.comparison_id,
            "lock_id": self.lock_id,
            "test_evaluation_id": self.test_evaluation_id,
            "promotion_receipt_id": self.promotion_receipt_id,
            "recommendation": self.recommendation,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True, slots=True)
class ModelComparison:
    comparison_id: str
    campaign_id: str
    component: str
    capability: str
    task: str
    recipe_digest: str
    gate_profile_id: str
    data: DataContext
    champion: ModelEvaluation
    candidates: tuple[ModelEvaluation, ...]
    recommendation: str
    recommended_candidate_id: str | None
    selection_order: tuple[str, ...]
    generated_at_utc: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ModelComparison":
        data = _object(raw, "model comparison")
        _strict(
            data,
            {
                "schema_version",
                "comparison_id",
                "campaign_id",
                "component",
                "capability",
                "task",
                "recipe_digest",
                "gate_profile_id",
                "data",
                "champion",
                "candidates",
                "recommendation",
                "recommended_candidate_id",
                "selection_order",
                "generated_at_utc",
            },
            "model comparison",
        )
        if data["schema_version"] != MODEL_COMPARISON_SCHEMA_VERSION:
            raise ModelImprovementError("model comparison has an unsupported schema_version.")
        champion = ModelEvaluation.from_mapping(data["champion"], "comparison.champion")
        if champion.role != "champion":
            raise ModelImprovementError("comparison.champion must have champion role.")
        comparison_data = DataContext.from_mapping(data["data"])
        if champion.data != comparison_data:
            raise ModelImprovementError("comparison champion uses an incompatible data context.")
        candidates = tuple(
            ModelEvaluation.from_mapping(item, f"comparison.candidates[{index}]")
            for index, item in enumerate(_list(data["candidates"], "comparison.candidates"))
        )
        if any(item.role != "candidate" or item.candidate_id is None for item in candidates):
            raise ModelImprovementError("comparison candidates must have candidate role and ID.")
        if any(item.data != comparison_data for item in candidates):
            raise ModelImprovementError("comparison candidate uses an incompatible data context.")
        candidate_ids = [item.candidate_id or "" for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ModelImprovementError("comparison candidate IDs must be unique.")
        recommendation = _string(data["recommendation"], "comparison.recommendation")
        if recommendation not in MODEL_RECOMMENDATIONS:
            raise ModelImprovementError("comparison.recommendation is not supported.")
        recommended = (
            None
            if data["recommended_candidate_id"] is None
            else _identifier(data["recommended_candidate_id"], "recommended_candidate_id")
        )
        if recommendation == "promote_candidate":
            if recommended is None or recommended not in candidate_ids:
                raise ModelImprovementError(
                    "promote_candidate needs a known recommended candidate."
                )
        elif recommended is not None:
            raise ModelImprovementError("only promote_candidate can name a recommended candidate.")
        order = tuple(
            _identifier(value, f"selection_order[{index}]")
            for index, value in enumerate(_list(data["selection_order"], "selection_order"))
        )
        if set(order) != set(candidate_ids) or len(order) != len(candidate_ids):
            raise ModelImprovementError(
                "selection_order must contain every candidate exactly once."
            )
        component = _component(data["component"], "comparison.component")
        task = _task(data["task"], "comparison.task")
        _component_task(component, task, "comparison")
        return cls(
            _identifier(data["comparison_id"], "comparison_id"),
            _identifier(data["campaign_id"], "campaign_id"),
            component,
            _identifier(data["capability"], "comparison.capability"),
            task,
            _digest(data["recipe_digest"], "comparison.recipe_digest"),
            _identifier(data["gate_profile_id"], "comparison.gate_profile_id"),
            comparison_data,
            champion,
            candidates,
            recommendation,
            recommended,
            order,
            _timestamp(data["generated_at_utc"], "comparison.generated_at_utc"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_COMPARISON_SCHEMA_VERSION,
            "comparison_id": self.comparison_id,
            "campaign_id": self.campaign_id,
            "component": self.component,
            "capability": self.capability,
            "task": self.task,
            "recipe_digest": self.recipe_digest,
            "gate_profile_id": self.gate_profile_id,
            "data": self.data.to_mapping(),
            "champion": self.champion.to_mapping(),
            "candidates": [item.to_mapping() for item in self.candidates],
            "recommendation": self.recommendation,
            "recommended_candidate_id": self.recommended_candidate_id,
            "selection_order": list(self.selection_order),
            "generated_at_utc": self.generated_at_utc,
        }


@dataclass(frozen=True, slots=True)
class CandidateLock:
    lock_id: str
    campaign_id: str
    component: str
    capability: str
    candidate_id: str
    run_id: str
    checkpoint_id: str
    recipe_digest: str
    data: DataContext
    validation_evaluation_id: str
    threshold_settings: Mapping[str, Any]
    decoder_settings: Mapping[str, Any]
    code_revision: str
    code_dirty: bool
    locked_at_utc: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CandidateLock":
        data = _object(raw, "candidate lock")
        _strict(
            data,
            {
                "schema_version",
                "lock_id",
                "campaign_id",
                "component",
                "capability",
                "candidate_id",
                "run_id",
                "checkpoint_id",
                "recipe_digest",
                "data",
                "validation_evaluation_id",
                "threshold_settings",
                "decoder_settings",
                "code_revision",
                "code_dirty",
                "locked_at_utc",
            },
            "candidate lock",
        )
        if data["schema_version"] != MODEL_CANDIDATE_LOCK_SCHEMA_VERSION:
            raise ModelImprovementError("candidate lock has an unsupported schema_version.")
        thresholds = _object(data["threshold_settings"], "candidate lock.threshold_settings")
        decoder = _object(data["decoder_settings"], "candidate lock.decoder_settings")
        _finite_json(thresholds, "candidate lock.threshold_settings")
        _finite_json(decoder, "candidate lock.decoder_settings")
        dirty = (
            data["code_dirty"]
            if isinstance(data["code_dirty"], bool)
            else _raise_bool("candidate lock.code_dirty")
        )
        return cls(
            _identifier(data["lock_id"], "lock_id"),
            _identifier(data["campaign_id"], "campaign_id"),
            _component(data["component"], "candidate lock.component"),
            _identifier(data["capability"], "candidate lock.capability"),
            _identifier(data["candidate_id"], "candidate_id"),
            _identifier(data["run_id"], "run_id"),
            _identifier(data["checkpoint_id"], "checkpoint_id"),
            _digest(data["recipe_digest"], "recipe_digest"),
            DataContext.from_mapping(data["data"]),
            _identifier(data["validation_evaluation_id"], "validation_evaluation_id"),
            dict(thresholds),
            dict(decoder),
            _string(data["code_revision"], "code_revision"),
            dirty,
            _timestamp(data["locked_at_utc"], "locked_at_utc"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_CANDIDATE_LOCK_SCHEMA_VERSION,
            "lock_id": self.lock_id,
            "campaign_id": self.campaign_id,
            "component": self.component,
            "capability": self.capability,
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "checkpoint_id": self.checkpoint_id,
            "recipe_digest": self.recipe_digest,
            "data": self.data.to_mapping(),
            "validation_evaluation_id": self.validation_evaluation_id,
            "threshold_settings": dict(self.threshold_settings),
            "decoder_settings": dict(self.decoder_settings),
            "code_revision": self.code_revision,
            "code_dirty": self.code_dirty,
            "locked_at_utc": self.locked_at_utc,
        }


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    receipt_id: str
    campaign_id: str
    component: str
    capability: str
    candidate_id: str
    promoted_bundle: ArtifactReference
    previous_champion: ArtifactReference
    recipe_digest: str
    data: DataContext
    sealed_test_evaluation_id: str
    export_artifact: ArtifactReference
    runtime_contract_version: str
    input_contract_version: str
    promotion_state: str
    registry_update: str
    registry_before_digest: str
    registry_after_digest: str | None
    occurred_at_utc: str
    failure_reason: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PromotionReceipt":
        data = _object(raw, "promotion receipt")
        _strict(
            data,
            {
                "schema_version",
                "receipt_id",
                "campaign_id",
                "component",
                "capability",
                "candidate_id",
                "promoted_bundle",
                "previous_champion",
                "recipe_digest",
                "data",
                "sealed_test_evaluation_id",
                "export_artifact",
                "runtime_contract_version",
                "input_contract_version",
                "promotion_state",
                "registry_update",
                "registry_before_digest",
                "registry_after_digest",
                "occurred_at_utc",
                "failure_reason",
            },
            "promotion receipt",
        )
        if data["schema_version"] != MODEL_PROMOTION_RECEIPT_SCHEMA_VERSION:
            raise ModelImprovementError("promotion receipt has an unsupported schema_version.")
        state = _string(data["promotion_state"], "promotion_state")
        update = _string(data["registry_update"], "registry_update")
        if state not in MODEL_PROMOTION_STATES or update not in MODEL_PROMOTION_REGISTRY_UPDATES:
            raise ModelImprovementError("promotion receipt has an unsupported state.")
        after = (
            None
            if data["registry_after_digest"] is None
            else _digest(data["registry_after_digest"], "registry_after_digest")
        )
        failure = (
            None
            if data["failure_reason"] is None
            else _string(data["failure_reason"], "failure_reason")
        )
        if state == "promoted" and (update != "updated" or after is None or failure is not None):
            raise ModelImprovementError("promoted receipt must record one updated registry.")
        if state == "failed" and (update != "unchanged" or after is not None or failure is None):
            raise ModelImprovementError("failed receipt must prove that the registry is unchanged.")
        return cls(
            _identifier(data["receipt_id"], "receipt_id"),
            _identifier(data["campaign_id"], "campaign_id"),
            _component(data["component"], "promotion receipt.component"),
            _identifier(data["capability"], "promotion receipt.capability"),
            _identifier(data["candidate_id"], "candidate_id"),
            ArtifactReference.from_mapping(data["promoted_bundle"], "promoted_bundle"),
            ArtifactReference.from_mapping(data["previous_champion"], "previous_champion"),
            _digest(data["recipe_digest"], "recipe_digest"),
            DataContext.from_mapping(data["data"]),
            _identifier(data["sealed_test_evaluation_id"], "sealed_test_evaluation_id"),
            ArtifactReference.from_mapping(data["export_artifact"], "export_artifact"),
            _string(data["runtime_contract_version"], "runtime_contract_version"),
            _string(data["input_contract_version"], "input_contract_version"),
            state,
            update,
            _digest(data["registry_before_digest"], "registry_before_digest"),
            after,
            _timestamp(data["occurred_at_utc"], "occurred_at_utc"),
            failure,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_PROMOTION_RECEIPT_SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "campaign_id": self.campaign_id,
            "component": self.component,
            "capability": self.capability,
            "candidate_id": self.candidate_id,
            "promoted_bundle": self.promoted_bundle.to_mapping(),
            "previous_champion": self.previous_champion.to_mapping(),
            "recipe_digest": self.recipe_digest,
            "data": self.data.to_mapping(),
            "sealed_test_evaluation_id": self.sealed_test_evaluation_id,
            "export_artifact": self.export_artifact.to_mapping(),
            "runtime_contract_version": self.runtime_contract_version,
            "input_contract_version": self.input_contract_version,
            "promotion_state": self.promotion_state,
            "registry_update": self.registry_update,
            "registry_before_digest": self.registry_before_digest,
            "registry_after_digest": self.registry_after_digest,
            "occurred_at_utc": self.occurred_at_utc,
            "failure_reason": self.failure_reason,
        }


def _raise_bool(field: str) -> bool:
    raise ModelImprovementError(f"{field} must be a boolean.")


def _component(value: Any, field: str) -> str:
    result = _identifier(value, field)
    if result not in MODEL_COMPONENTS:
        raise ModelImprovementError(f"{field} is not a supported model component.")
    return result


def _task(value: Any, field: str) -> str:
    result = _string(value, field)
    if result not in MODEL_TASKS:
        raise ModelImprovementError(f"{field} is not a supported model task.")
    return result


def _component_task(component: str, task: str, context: str) -> None:
    if MODEL_COMPONENT_TASKS[component] != task:
        raise ModelImprovementError(f"{context} pairs an incompatible component and task.")


def _path_value(metrics: Mapping[str, Any], path: str) -> Any:
    current: Any = metrics
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def evaluate_gates(profile: GateProfile, metrics: Mapping[str, Any]) -> tuple[GateResult, ...]:
    """Evaluate a profile without changing the supplied metric mapping."""

    results: list[GateResult] = []
    for gate in profile.gates:
        observed = _path_value(metrics, gate.metric)
        if gate.min_support is not None:
            support = _path_value(metrics, gate.support_metric or "")
            if (
                not isinstance(support, (int, float))
                or isinstance(support, bool)
                or support < gate.min_support
            ):
                results.append(
                    GateResult(
                        gate.gate_id,
                        "not_applicable",
                        gate.hard,
                        None if observed is None else _finite_number(observed, gate.metric),
                        gate.threshold,
                        f"support below declared minimum {gate.min_support}",
                    )
                )
                continue
        if observed is None:
            results.append(
                GateResult(
                    gate.gate_id, "failed", gate.hard, None, gate.threshold, "metric is missing"
                )
            )
            continue
        if gate.operator == "equals":
            valid = isinstance(observed, bool) and observed is gate.threshold
        else:
            observed = _finite_number(observed, gate.metric)
            valid = (
                observed >= gate.threshold if gate.operator == "min" else observed <= gate.threshold
            )
        results.append(
            GateResult(
                gate.gate_id,
                "passed" if valid else "failed",
                gate.hard,
                observed,
                gate.threshold,
                "meets threshold" if valid else f"does not meet {gate.operator} threshold",
            )
        )
    return tuple(results)


def _hard_gate_failed(gates: Sequence[GateResult]) -> bool:
    return any(item.hard and item.status == "failed" for item in gates)


def _metric_value(metrics: Mapping[str, Any], name: str) -> float | None:
    value = _path_value(metrics, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _rank_key(
    evaluation: ModelEvaluation, metrics: Sequence[SelectionMetric]
) -> tuple[float, ...] | None:
    values: list[float] = []
    for metric in metrics:
        value = _metric_value(evaluation.metrics, metric.metric)
        if value is None:
            return None
        values.append(value if metric.direction == "maximize" else -value)
    return tuple(values)


def _non_inferiority_ok(
    champion: ModelEvaluation,
    candidate: ModelEvaluation,
    rules: Sequence[NonInferiorityRule],
    selection_metrics: Sequence[SelectionMetric],
) -> bool:
    directions = {item.metric: item.direction for item in selection_metrics}
    for rule in rules:
        baseline = _metric_value(champion.metrics, rule.metric)
        value = _metric_value(candidate.metrics, rule.metric)
        if baseline is None or value is None:
            if rule.hard:
                return False
            continue
        direction = directions.get(rule.metric, "maximize")
        regression = value < baseline - rule.max_regression
        if direction == "minimize":
            regression = value > baseline + rule.max_regression
        if regression and rule.hard:
            return False
    return True


def compare_evaluations(
    *,
    campaign_id: str,
    component: str,
    capability: str,
    task: str,
    recipe_digest: str,
    data: DataContext,
    champion: ModelEvaluation,
    candidates: Sequence[ModelEvaluation],
    profile: GateProfile,
    generated_at_utc: str,
) -> ModelComparison:
    """Build the machine-readable comparison and recommendation deterministically."""

    component = _component(component, "component")
    task = _task(task, "task")
    _component_task(component, task, "comparison")
    if champion.role != "champion" or champion.candidate_id is not None:
        raise ModelImprovementError("champion evaluation has an incompatible role.")
    if champion.data != data:
        raise ModelImprovementError("champion evaluation uses an incompatible data context.")
    if profile.component != component or profile.capability != capability:
        raise ModelImprovementError("gate profile is incompatible with the comparison component.")
    candidate_inputs = sorted(candidates, key=lambda item: item.candidate_id or "")
    candidate_ids = [item.candidate_id for item in candidate_inputs]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ModelImprovementError("comparison candidate IDs must be unique.")
    evaluated_candidates: list[ModelEvaluation] = []
    for candidate in candidate_inputs:
        if candidate.role != "candidate" or candidate.candidate_id is None:
            raise ModelImprovementError("candidate evaluation has an incompatible role.")
        if candidate.data != data:
            raise ModelImprovementError(
                f"candidate {candidate.candidate_id} uses an incompatible dataset or split digest."
            )
        gates = evaluate_gates(profile, candidate.metrics) if candidate.state == "success" else ()
        evaluated_candidates.append(
            ModelEvaluation(
                candidate.evaluation_id,
                candidate.role,
                candidate.candidate_id,
                candidate.run_id,
                candidate.bundle,
                candidate.state,
                candidate.data,
                candidate.metrics,
                gates,
                candidate.failure_reason,
            )
        )
    champion_gates = (
        evaluate_gates(profile, champion.metrics) if champion.state == "success" else ()
    )
    champion = ModelEvaluation(
        champion.evaluation_id,
        champion.role,
        champion.candidate_id,
        champion.run_id,
        champion.bundle,
        champion.state,
        champion.data,
        champion.metrics,
        champion_gates,
        champion.failure_reason,
    )
    valid = [
        item
        for item in evaluated_candidates
        if item.state == "success"
        and not _hard_gate_failed(item.gates)
        and _rank_key(item, profile.selection_metrics) is not None
    ]
    ordered = sorted(
        evaluated_candidates,
        key=lambda item: (
            _rank_key(item, profile.selection_metrics) is None,
            tuple(-value for value in (_rank_key(item, profile.selection_metrics) or ())),
            item.candidate_id or "",
        ),
    )
    recommendation = "no_valid_candidate"
    recommended: str | None = None
    if valid:
        best = max(
            valid,
            key=lambda item: (
                _rank_key(item, profile.selection_metrics) or (),
                item.candidate_id or "",
            ),
        )
        ties = [
            item
            for item in valid
            if _rank_key(item, profile.selection_metrics)
            == _rank_key(best, profile.selection_metrics)
        ]
        champion_key = _rank_key(champion, profile.selection_metrics)
        if len(ties) > 1 or champion_key is None:
            recommendation = "human_review_required"
        elif (_rank_key(best, profile.selection_metrics) or ()) <= champion_key:
            recommendation = "keep_champion"
        elif not _non_inferiority_ok(
            champion, best, profile.non_inferiority, profile.selection_metrics
        ):
            recommendation = "human_review_required"
        else:
            recommendation = "promote_candidate"
            recommended = best.candidate_id
    comparison_identity = {
        "campaign_id": campaign_id,
        "recipe_digest": recipe_digest,
        "candidate_ids": candidate_ids,
    }
    return ModelComparison(
        comparison_id=f"comparison-{sha256_mapping(comparison_identity)[:20]}",
        campaign_id=_identifier(campaign_id, "campaign_id"),
        component=_component(component, "component"),
        capability=_identifier(capability, "capability"),
        task=_task(task, "task"),
        recipe_digest=_digest(recipe_digest, "recipe_digest"),
        gate_profile_id=profile.gate_profile_id,
        data=data,
        champion=champion,
        candidates=tuple(evaluated_candidates),
        recommendation=recommendation,
        recommended_candidate_id=recommended,
        selection_order=tuple(item.candidate_id or "" for item in ordered),
        generated_at_utc=_timestamp(generated_at_utc, "generated_at_utc"),
    )


def validate_comparison_against_campaign(
    campaign: ModelCampaign, comparison: ModelComparison
) -> None:
    """Reject stale or cross-campaign comparison artifacts."""

    pairs = (
        (campaign.campaign_id, comparison.campaign_id, "campaign ID"),
        (campaign.component, comparison.component, "component"),
        (campaign.capability, comparison.capability, "capability"),
        (campaign.task, comparison.task, "task"),
        (campaign.recipe_digest, comparison.recipe_digest, "recipe digest"),
        (campaign.data, comparison.data, "dataset or split context"),
        (campaign.baseline_bundle, comparison.champion.bundle, "champion bundle"),
    )
    for expected, actual, label in pairs:
        if expected != actual:
            raise ModelImprovementError(f"comparison is stale or incompatible: {label} differs.")
    if campaign.comparison_id is not None and campaign.comparison_id != comparison.comparison_id:
        raise ModelImprovementError("comparison is stale: campaign comparison_id differs.")


def validate_campaign_against_registry(campaign: ModelCampaign, registry: ModelRegistry) -> None:
    """Reject a non-promoted campaign whose baseline is no longer the champion."""

    champion = registry.champion_for(campaign.component, campaign.capability)
    if (
        champion is not None
        and campaign.state != "promoted"
        and campaign.baseline_bundle != champion.champion_bundle
    ):
        raise ModelImprovementError(
            "campaign is stale: baseline champion differs from the current registry champion."
        )


def load_json_object(path: str | Path, context: str) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelImprovementError(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ModelImprovementError(f"{context} {path} must contain a JSON object.")
    return value


def load_model_registry(path: str | Path) -> ModelRegistry:
    return ModelRegistry.from_mapping(load_json_object(path, "model registry"))


def validate_model_registry(payload: Mapping[str, Any]) -> None:
    ModelRegistry.from_mapping(payload)


def load_model_recipe(path: str | Path) -> ModelRecipe:
    recipe_path = Path(path)
    if recipe_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as error:
            raise ModelImprovementError(
                "YAML model recipes require the operations package YAML dependency."
            ) from error
        try:
            value = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as error:
            raise ModelImprovementError(
                f"Could not read model recipe {recipe_path}: {error}"
            ) from error
        if not isinstance(value, Mapping):
            raise ModelImprovementError(f"model recipe {recipe_path} must contain an object.")
        return ModelRecipe.from_mapping(value)
    return ModelRecipe.from_mapping(load_json_object(recipe_path, "model recipe"))


def validate_model_recipe(payload: Mapping[str, Any]) -> None:
    ModelRecipe.from_mapping(payload)


def load_gate_profile(path: str | Path) -> GateProfile:
    return GateProfile.from_mapping(load_json_object(path, "gate profile"))


def validate_gate_profile(payload: Mapping[str, Any]) -> None:
    GateProfile.from_mapping(payload)


def validate_model_campaign(payload: Mapping[str, Any]) -> None:
    ModelCampaign.from_mapping(payload)


def validate_model_comparison(payload: Mapping[str, Any]) -> None:
    ModelComparison.from_mapping(payload)


def load_candidate_lock(path: str | Path) -> CandidateLock:
    return CandidateLock.from_mapping(load_json_object(path, "candidate lock"))


def validate_candidate_lock(payload: Mapping[str, Any]) -> None:
    CandidateLock.from_mapping(payload)


def load_promotion_receipt(path: str | Path) -> PromotionReceipt:
    return PromotionReceipt.from_mapping(load_json_object(path, "promotion receipt"))


def validate_promotion_receipt(payload: Mapping[str, Any]) -> None:
    PromotionReceipt.from_mapping(payload)


def load_campaign(campaign_root: str | Path, campaign_id: str) -> ModelCampaign:
    campaign_id = _identifier(campaign_id, "campaign_id")
    path = Path(campaign_root) / campaign_id / "campaign.json"
    return ModelCampaign.from_mapping(load_json_object(path, "model campaign"))


def load_campaign_comparison(campaign_root: str | Path, campaign: ModelCampaign) -> ModelComparison:
    path = Path(campaign_root) / campaign.campaign_id / "comparison.json"
    comparison = ModelComparison.from_mapping(load_json_object(path, "model comparison"))
    validate_comparison_against_campaign(campaign, comparison)
    return comparison


def render_comparison_json(comparison: ModelComparison) -> str:
    return json.dumps(comparison.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_comparison_human(comparison: ModelComparison) -> str:
    lines = [
        "DokoDetector model comparison",
        f"campaign: {comparison.campaign_id}",
        f"component: {comparison.component} ({comparison.capability})",
        f"data: {comparison.data.dataset.id} / {comparison.data.split.id}",
        f"champion: {comparison.champion.bundle.id}",
        f"candidates: {len(comparison.candidates)}",
        f"recommendation: {comparison.recommendation}",
    ]
    if comparison.recommended_candidate_id is not None:
        lines.append(f"recommended candidate: {comparison.recommended_candidate_id}")
    lines.append("candidate results:")
    by_id = {item.candidate_id: item for item in comparison.candidates}
    for candidate_id in comparison.selection_order:
        item = by_id[candidate_id]
        failed = sum(result.hard and result.status == "failed" for result in item.gates)
        lines.append(f"  - {candidate_id}: {item.state}, hard-gate failures: {failed}")
        for gate in item.gates:
            lines.append(f"    - {gate.gate_id}: {gate.status}")
    lines.append("champion gates:")
    for gate in comparison.champion.gates:
        lines.append(f"  - {gate.gate_id}: {gate.status}")
    return "\n".join(lines) + "\n"


def render_comparison_report(comparison: ModelComparison) -> str:
    """Render the concise review report from comparison data only."""

    lines = [
        "# Model comparison report",
        "",
        f"- Campaign: `{comparison.campaign_id}`",
        f"- Component: `{comparison.component}` (`{comparison.capability}`)",
        f"- Dataset: `{comparison.data.dataset.id}` (`{comparison.data.dataset.digest}`)",
        f"- Split: `{comparison.data.split.id}` (`{comparison.data.split.digest}`)",
        f"- Champion: `{comparison.champion.bundle.id}`",
        f"- Recommendation: `{comparison.recommendation}`",
        "",
        "## Candidates",
        "",
        "| Candidate | State | Hard-gate failures |",
        "| --- | --- | ---: |",
    ]
    by_id = {item.candidate_id: item for item in comparison.candidates}
    for candidate_id in comparison.selection_order:
        item = by_id[candidate_id]
        failures = sum(result.hard and result.status == "failed" for result in item.gates)
        lines.append(f"| `{candidate_id}` | `{item.state}` | {failures} |")
    lines.extend(["", "## Gate results", ""])
    for evaluation in (comparison.champion, *comparison.candidates):
        label = (
            "champion" if evaluation.role == "champion" else evaluation.candidate_id or "candidate"
        )
        lines.append(f"### {label}")
        for gate in evaluation.gates:
            lines.append(f"- `{gate.gate_id}`: `{gate.status}` — {gate.reason}")
    lines.extend(["", "The recommendation is derived from `comparison.json`.\n"])
    return "\n".join(lines)


def default_gate_profile(component: str) -> GateProfile:
    """Load the checked-in fixture gate profile for one component."""

    profile_name = {
        "card-event-net": "card-event-net-v1.json",
        "table-evidence-analyzer": "table-evidence-analyzer-identity-v1.json",
    }.get(component)
    if profile_name is None:
        raise ModelImprovementError(f"No default gate profile exists for {component}.")
    path = Path(__file__).resolve().parents[2] / "config" / "model-gates" / profile_name
    return GateProfile.from_mapping(load_json_object(path, "gate profile"))


def model_status(
    repository_root: str | Path,
    *,
    registry_path: str | Path | None = None,
    campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return a read-only status mapping for champions and campaigns."""

    root = Path(repository_root).resolve()
    registry_file = (
        Path(registry_path) if registry_path is not None else root / "data" / "model-registry.json"
    )
    if not registry_file.is_absolute():
        registry_file = root / registry_file
    campaigns_dir = (
        Path(campaign_root) if campaign_root is not None else root / "data" / "model-campaigns"
    )
    if not campaigns_dir.is_absolute():
        campaigns_dir = root / campaigns_dir
    issues: list[dict[str, str]] = []
    registry: ModelRegistry | None = None
    if registry_file.exists():
        try:
            registry = load_model_registry(registry_file)
        except ModelImprovementError as error:
            issues.append(
                {"kind": "corrupt_registry", "path": str(registry_file), "message": str(error)}
            )
    campaigns: list[dict[str, Any]] = []
    if campaigns_dir.is_dir():
        for directory in sorted(path for path in campaigns_dir.iterdir() if path.is_dir()):
            try:
                campaign = load_campaign(campaigns_dir, directory.name)
                comparison_path = directory / "comparison.json"
                if comparison_path.exists():
                    try:
                        comparison = load_campaign_comparison(campaigns_dir, campaign)
                        if campaign.comparison_id is None:
                            issues.append(
                                {
                                    "kind": "stale_campaign",
                                    "path": str(comparison_path),
                                    "message": (
                                        "comparison exists but campaign has no comparison_id"
                                    ),
                                }
                            )
                        elif comparison.recommendation != campaign.recommendation:
                            issues.append(
                                {
                                    "kind": "stale_campaign",
                                    "path": str(comparison_path),
                                    "message": (
                                        "comparison recommendation differs from campaign state"
                                    ),
                                }
                            )
                    except ModelImprovementError as error:
                        issues.append(
                            {
                                "kind": "corrupt_comparison",
                                "path": str(comparison_path),
                                "message": str(error),
                            }
                        )
                elif campaign.state in {
                    "compared",
                    "candidate_locked",
                    "tested",
                    "promotion_recommended",
                    "human_review_required",
                    "keep_champion_recommended",
                    "promoted",
                }:
                    issues.append(
                        {
                            "kind": "incomplete_campaign",
                            "path": str(comparison_path),
                            "message": f"campaign state {campaign.state} requires comparison.json",
                        }
                    )
                receipt_path = directory / "promotion-receipt.json"
                if receipt_path.exists():
                    try:
                        load_promotion_receipt(receipt_path)
                    except ModelImprovementError as error:
                        issues.append(
                            {
                                "kind": "corrupt_promotion_receipt",
                                "path": str(receipt_path),
                                "message": str(error),
                            }
                        )
                if registry is not None:
                    try:
                        validate_campaign_against_registry(campaign, registry)
                    except ModelImprovementError:
                        issues.append(
                            {
                                "kind": "stale_campaign",
                                "path": str(directory / "campaign.json"),
                                "message": (
                                    "campaign baseline champion differs from the current "
                                    "registry champion"
                                ),
                            }
                        )
                campaigns.append(
                    {
                        "campaign_id": campaign.campaign_id,
                        "component": campaign.component,
                        "capability": campaign.capability,
                        "state": campaign.state,
                        "recommendation": campaign.recommendation,
                    }
                )
            except ModelImprovementError as error:
                issues.append(
                    {
                        "kind": "corrupt_campaign",
                        "path": str(directory / "campaign.json"),
                        "message": str(error),
                    }
                )
    return {
        "schema_version": MODEL_STATUS_SCHEMA_VERSION,
        "registry": None if registry is None else registry.to_mapping(),
        "campaigns": campaigns,
        "issues": sorted(issues, key=lambda item: (item["kind"], item["path"], item["message"])),
        "valid": not issues,
    }


def render_model_status_json(status: Mapping[str, Any]) -> str:
    return json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_model_status_human(status: Mapping[str, Any]) -> str:
    lines = ["DokoDetector model status"]
    registry = status.get("registry")
    champions = [] if not isinstance(registry, Mapping) else registry.get("champions", [])
    if champions:
        lines.append("champions:")
        for item in champions:
            lines.append(
                f"  - {item['component']} ({item['capability']}): {item['champion_bundle_id']}"
            )
    else:
        lines.append("champions: none")
    campaigns = status.get("campaigns", [])
    lines.append(f"campaigns: {len(campaigns)}")
    for item in campaigns:
        lines.append(
            f"  - {item['campaign_id']}: {item['component']} / {item['capability']} — "
            f"{item['state']}"
        )
    issues = status.get("issues", [])
    lines.append(f"issues: {len(issues)}")
    for issue in issues:
        lines.append(f"  - {issue['kind']}: {issue['path']} ({issue['message']})")
    return "\n".join(lines) + "\n"


__all__ = [
    "ArtifactReference",
    "CandidateLock",
    "CandidateRunReference",
    "CandidateSpec",
    "ChampionModel",
    "DataContext",
    "ExportContract",
    "ExperimentBudget",
    "ExecutionContract",
    "GateDefinition",
    "GateProfile",
    "GateResult",
    "MODEL_CAMPAIGN_SCHEMA_VERSION",
    "MODEL_CANDIDATE_LOCK_SCHEMA_VERSION",
    "MODEL_COMPARISON_SCHEMA_VERSION",
    "MODEL_COMPONENTS",
    "MODEL_GATE_PROFILE_SCHEMA_VERSION",
    "MODEL_PROMOTION_RECEIPT_SCHEMA_VERSION",
    "MODEL_RECIPE_SCHEMA_VERSION",
    "MODEL_REGISTRY_SCHEMA_VERSION",
    "MODEL_STATUS_SCHEMA_VERSION",
    "ModelCampaign",
    "ModelComparison",
    "ModelEvaluation",
    "ModelImprovementError",
    "ModelRecipe",
    "ModelRegistry",
    "NonInferiorityRule",
    "PromotionReceipt",
    "SelectionMetric",
    "compare_evaluations",
    "default_gate_profile",
    "evaluate_gates",
    "load_campaign",
    "load_campaign_comparison",
    "load_candidate_lock",
    "load_gate_profile",
    "load_json_object",
    "load_model_recipe",
    "load_model_registry",
    "load_promotion_receipt",
    "model_status",
    "render_comparison_human",
    "render_comparison_json",
    "render_comparison_report",
    "render_model_status_human",
    "render_model_status_json",
    "sha256_mapping",
    "validate_candidate_lock",
    "validate_campaign_against_registry",
    "validate_comparison_against_campaign",
    "validate_gate_profile",
    "validate_model_campaign",
    "validate_model_comparison",
    "validate_model_recipe",
    "validate_model_registry",
    "validate_promotion_receipt",
]
