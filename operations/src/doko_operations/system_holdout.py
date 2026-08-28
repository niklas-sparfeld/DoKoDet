"""Read-only composed evaluation on the shared system holdout."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from game_engine.contract import RoundScenario, load_round_scenario
from game_engine.reconstruction import reconstruct_round

from .holdout import (
    SystemHoldoutError,
    load_system_holdout_registry,
    sealed_group_keys,
    validate_split_against_system_holdout,
)
from .model_improvement import (
    CandidateLock,
    DataContext,
    ModelCampaign,
    ModelRegistry,
    load_campaign,
    load_campaign_comparison,
    load_candidate_lock,
    load_model_registry,
    sha256_mapping,
)

SYSTEM_HOLDOUT_EVALUATION_SCHEMA_VERSION = "system-holdout-evaluation/v1"
SYSTEM_RECONSTRUCTION_CONFIG_SCHEMA_VERSION = "system-reconstruction-config/v1"
SYSTEM_HOLDOUT_EVALUATION_STATES = frozenset({"passed", "failed"})
SYSTEM_HOLDOUT_RECOMMENDATIONS = frozenset({"system_holdout_passed", "human_review_required"})
COMPONENT_LOCK_STATES = frozenset(
    {"candidate_locked", "tested", "promotion_recommended", "promoted"}
)
FAILURE_BOUNDARIES = ("event", "observation", "reconstruction")
FailureBoundary = Literal["event", "observation", "reconstruction"]


class SystemHoldoutEvaluationError(ValueError):
    """Raised when a locked system holdout evaluation cannot run."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_json(path: Path, context: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemHoldoutEvaluationError(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemHoldoutEvaluationError(f"{context} {path} must contain a JSON object.")
    return value


def _write_json(path: Path, value: Mapping[str, object]) -> None:
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
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise SystemHoldoutEvaluationError(
            f"Could not write system holdout report {path}: {error}"
        ) from error


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise SystemHoldoutEvaluationError(f"Could not hash {path}: {error}") from error


def _safe_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemHoldoutEvaluationError(f"{field} must be a non-empty string.")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SystemHoldoutEvaluationError(f"{field} must be a positive integer.")
    return value


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemHoldoutEvaluationError(f"{field} must be a non-negative integer.")
    return value


@dataclass(frozen=True, slots=True)
class SystemReconstructionConfig:
    """The locked reconstruction settings used by one system evaluation."""

    config_id: str
    config_version: int
    engine_version: str
    ruleset: Mapping[str, str]
    deck_variant: str
    max_missing_plays: int
    max_hypotheses: int
    max_search_nodes: int
    locked: bool

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SystemReconstructionConfig":
        expected = {
            "schema_version",
            "config_id",
            "config_version",
            "engine_version",
            "ruleset",
            "deck_variant",
            "max_missing_plays",
            "max_hypotheses",
            "max_search_nodes",
            "locked",
        }
        if set(raw) != expected:
            raise SystemHoldoutEvaluationError("system reconstruction config has invalid fields.")
        if raw["schema_version"] != SYSTEM_RECONSTRUCTION_CONFIG_SCHEMA_VERSION:
            raise SystemHoldoutEvaluationError("unsupported system reconstruction config schema.")
        ruleset = raw["ruleset"]
        if not isinstance(ruleset, Mapping) or set(ruleset) != {"name", "version"}:
            raise SystemHoldoutEvaluationError("system reconstruction config ruleset is invalid.")
        if ruleset != {"name": "doko-normal", "version": "v1"}:
            raise SystemHoldoutEvaluationError(
                "system reconstruction config uses an unsupported ruleset."
            )
        locked = raw["locked"]
        if not isinstance(locked, bool) or not locked:
            raise SystemHoldoutEvaluationError("system reconstruction config must be locked.")
        return cls(
            _safe_string(raw["config_id"], "config_id"),
            _positive_int(raw["config_version"], "config_version"),
            _safe_string(raw["engine_version"], "engine_version"),
            {"name": "doko-normal", "version": "v1"},
            _safe_string(raw["deck_variant"], "deck_variant"),
            _non_negative_int(raw["max_missing_plays"], "max_missing_plays"),
            _positive_int(raw["max_hypotheses"], "max_hypotheses"),
            _positive_int(raw["max_search_nodes"], "max_search_nodes"),
            True,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": SYSTEM_RECONSTRUCTION_CONFIG_SCHEMA_VERSION,
            "config_id": self.config_id,
            "config_version": self.config_version,
            "engine_version": self.engine_version,
            "ruleset": dict(self.ruleset),
            "deck_variant": self.deck_variant,
            "max_missing_plays": self.max_missing_plays,
            "max_hypotheses": self.max_hypotheses,
            "max_search_nodes": self.max_search_nodes,
            "locked": self.locked,
        }

    @property
    def digest(self) -> str:
        return sha256_mapping(self.to_mapping())


def load_system_reconstruction_config(path: str | Path) -> SystemReconstructionConfig:
    """Load one strict, locked reconstruction configuration."""

    return SystemReconstructionConfig.from_mapping(
        _read_json(Path(path), "system reconstruction config")
    )


@dataclass(frozen=True, slots=True)
class LockedComponentArtifact:
    """The candidate lock and validation artifact consumed by the composed pipeline."""

    component: str
    capability: str
    campaign_id: str
    campaign_state: str
    lock_id: str
    candidate_id: str
    run_id: str
    checkpoint_id: str
    recipe_digest: str
    bundle_id: str
    bundle_digest: str
    data: DataContext

    def to_mapping(self) -> dict[str, object]:
        return {
            "component": self.component,
            "capability": self.capability,
            "campaign_id": self.campaign_id,
            "campaign_state": self.campaign_state,
            "lock_id": self.lock_id,
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "checkpoint_id": self.checkpoint_id,
            "recipe_digest": self.recipe_digest,
            "bundle": {"id": self.bundle_id, "digest": self.bundle_digest},
            "data": self.data.to_mapping(),
        }


def _locked_component(
    campaign: ModelCampaign,
    lock: CandidateLock,
    comparison: object,
    *,
    component: str,
) -> LockedComponentArtifact:
    if campaign.component != component:
        raise SystemHoldoutEvaluationError(
            f"expected {component} campaign, got {campaign.component}"
        )
    if campaign.state not in COMPONENT_LOCK_STATES:
        raise SystemHoldoutEvaluationError(
            f"{component} campaign {campaign.campaign_id} is not locked: {campaign.state}"
        )
    if campaign.lock_id != lock.lock_id:
        raise SystemHoldoutEvaluationError(f"{component} campaign lock ID does not match lock.json")
    if (
        lock.campaign_id != campaign.campaign_id
        or lock.component != campaign.component
        or lock.capability != campaign.capability
        or lock.recipe_digest != campaign.recipe_digest
        or lock.data != campaign.data
    ):
        raise SystemHoldoutEvaluationError(f"{component} candidate lock is stale")
    if getattr(comparison, "recommendation", None) != "promote_candidate":
        raise SystemHoldoutEvaluationError(
            f"{component} campaign has no locked promotion recommendation"
        )
    if getattr(comparison, "recommended_candidate_id", None) != lock.candidate_id:
        raise SystemHoldoutEvaluationError(f"{component} candidate lock differs from comparison")
    if getattr(comparison, "campaign_id", None) != campaign.campaign_id:
        raise SystemHoldoutEvaluationError(f"{component} comparison belongs to another campaign")
    evaluation = next(
        (
            item
            for item in getattr(comparison, "candidates", ())
            if item.candidate_id == lock.candidate_id
        ),
        None,
    )
    if evaluation is None or evaluation.state != "success":
        raise SystemHoldoutEvaluationError(
            f"{component} locked candidate has no successful evaluation"
        )
    if (
        evaluation.evaluation_id != lock.validation_evaluation_id
        or evaluation.run_id != lock.run_id
        or evaluation.data != campaign.data
    ):
        raise SystemHoldoutEvaluationError(f"{component} locked evaluation is stale")
    run = next(
        (item for item in campaign.candidate_runs if item.candidate_id == lock.candidate_id), None
    )
    if run is None or run.state != "success" or run.checkpoint_id != lock.checkpoint_id:
        raise SystemHoldoutEvaluationError(f"{component} locked candidate run is incomplete")
    return LockedComponentArtifact(
        component=campaign.component,
        capability=campaign.capability,
        campaign_id=campaign.campaign_id,
        campaign_state=campaign.state,
        lock_id=lock.lock_id,
        candidate_id=lock.candidate_id,
        run_id=lock.run_id,
        checkpoint_id=lock.checkpoint_id,
        recipe_digest=lock.recipe_digest,
        bundle_id=evaluation.bundle.id,
        bundle_digest=evaluation.bundle.digest,
        data=lock.data,
    )


def _load_locked_component(
    campaign_root: Path, campaign_id: str, *, component: str
) -> LockedComponentArtifact:
    campaign = load_campaign(campaign_root, campaign_id)
    campaign_dir = campaign_root / campaign.campaign_id
    lock = load_candidate_lock(campaign_dir / "lock.json")
    comparison = load_campaign_comparison(campaign_root, campaign)
    return _locked_component(campaign, lock, comparison, component=component)


def _manifest_groups(
    dataset: Mapping[str, object], split: Mapping[str, object]
) -> set[tuple[str, str]]:
    entries = dataset.get("entries")
    if not isinstance(entries, list):
        raise SystemHoldoutEvaluationError("component dataset must contain entries")
    by_id: dict[str, set[tuple[str, str]]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("dataset_item_id"), str):
            raise SystemHoldoutEvaluationError("component dataset entries are invalid")
        raw_groups = entry.get("group_keys")
        if not isinstance(raw_groups, list):
            raise SystemHoldoutEvaluationError("component dataset entry group_keys are invalid")
        groups: set[tuple[str, str]] = set()
        for raw_group in raw_groups:
            if not isinstance(raw_group, list) or len(raw_group) != 2:
                raise SystemHoldoutEvaluationError("component dataset group key is invalid")
            name, value = raw_group
            if not isinstance(name, str) or not isinstance(value, str):
                raise SystemHoldoutEvaluationError("component dataset group key values are invalid")
            groups.add((name, value))
        by_id[entry["dataset_item_id"]] = groups
    selected: set[tuple[str, str]] = set()
    for partition in ("train", "validation"):
        values = split.get(partition)
        if not isinstance(values, list):
            raise SystemHoldoutEvaluationError(f"component split {partition} is invalid")
        for item_id in values:
            if not isinstance(item_id, str) or item_id not in by_id:
                raise SystemHoldoutEvaluationError("component split references an unknown item")
            selected.update(by_id[item_id])
    return selected


def _validate_component_data(
    artifact: LockedComponentArtifact,
    *,
    dataset_path: Path,
    split_path: Path,
    registry: Mapping[str, object],
) -> dict[str, object]:
    dataset = _read_json(dataset_path, f"{artifact.component} dataset")
    split = _read_json(split_path, f"{artifact.component} split")
    expected_dataset = artifact.data.dataset
    expected_split = artifact.data.split
    if (
        dataset.get("dataset_version_id") != expected_dataset.id
        or dataset.get("dataset_version_digest") != expected_dataset.digest
        or split.get("split_version_id") != expected_split.id
        or split.get("split_version_digest") != expected_split.digest
    ):
        raise SystemHoldoutEvaluationError(
            f"{artifact.component} manifests do not match the locked data context"
        )
    try:
        validate_split_against_system_holdout(dataset, split, registry, artifact.component)
    except SystemHoldoutError as error:
        raise SystemHoldoutEvaluationError(
            f"{artifact.component} system holdout leakage: {error}"
        ) from error
    used_groups = _manifest_groups(dataset, split)
    held_out = set(sealed_group_keys(registry))
    overlap = sorted(used_groups & held_out)
    if overlap:
        raise SystemHoldoutEvaluationError(
            f"{artifact.component} uses system holdout groups in training or selection: {overlap}"
        )
    return {
        "dataset": expected_dataset.to_mapping(),
        "split": expected_split.to_mapping(),
        "training_and_selection_group_count": len(used_groups),
        "training_and_selection_groups": [list(item) for item in sorted(used_groups)],
        "system_holdout_overlap": [],
        "unseen_by_training_or_selection": True,
    }


def _scenario_groups(scenario: RoundScenario) -> set[tuple[str, str]]:
    groups = {("game_id", scenario.input.game_id)}
    for observation in scenario.input.observations:
        groups.add(("session_id", observation.session.session_id))
        groups.add(("source_lineage", observation.source.package_id))
    return groups


def _stage(
    name: str, status: str, details: Mapping[str, object], boundary: str | None = None
) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "failure_boundary": boundary,
        "details": dict(details),
    }


class SystemHoldoutRunner(Protocol):
    """Run the local composed system fixture without changing model artifacts."""

    def run(
        self,
        scenario: RoundScenario,
        *,
        config: SystemReconstructionConfig,
        cardevent: LockedComponentArtifact,
        table_analyzer: LockedComponentArtifact,
    ) -> Mapping[str, object]: ...


class SystemHoldoutFixtureRunner:
    """Run source evidence through event, observation, and reconstruction fixtures."""

    def __init__(self, *, fail_boundary: FailureBoundary | None = None) -> None:
        if fail_boundary is not None and fail_boundary not in FAILURE_BOUNDARIES:
            raise ValueError(f"unsupported system holdout failure boundary: {fail_boundary}")
        self.fail_boundary = fail_boundary
        self.calls = 0

    def run(
        self,
        scenario: RoundScenario,
        *,
        config: SystemReconstructionConfig,
        cardevent: LockedComponentArtifact,
        table_analyzer: LockedComponentArtifact,
    ) -> Mapping[str, object]:
        self.calls += 1
        stages: list[dict[str, object]] = [
            _stage(
                "source_evidence",
                "passed",
                {
                    "scenario_id": scenario.scenario_id,
                    "observation_count": len(scenario.input.observations),
                },
            )
        ]
        attribution = {
            boundary: {"status": "not_observed", "failures": []} for boundary in FAILURE_BOUNDARIES
        }

        if self.fail_boundary == "event":
            message = "fixture event proposal stage failed"
            stages.append(_stage("event_proposals", "failed", {"error": message}, "event"))
            attribution["event"] = {"status": "failed", "failures": [message]}
            stages.extend(
                [
                    _stage("evidence_selection", "skipped", {"reason": "event proposals failed"}),
                    _stage("table_observations", "skipped", {"reason": "event proposals failed"}),
                    _stage("reconstruction", "skipped", {"reason": "event proposals failed"}),
                ]
            )
        else:
            stages.append(
                _stage(
                    "event_proposals",
                    "passed",
                    {"count": len(scenario.input.observations), "component": cardevent.component},
                )
            )
            attribution["event"] = {"status": "passed", "failures": []}
            stages.append(
                _stage(
                    "evidence_selection",
                    "passed",
                    {"selected_observation_count": len(scenario.input.observations)},
                )
            )
            if self.fail_boundary == "observation":
                message = "fixture table observation stage failed"
                stages.append(
                    _stage("table_observations", "failed", {"error": message}, "observation")
                )
                attribution["observation"] = {"status": "failed", "failures": [message]}
                stages.append(
                    _stage("reconstruction", "skipped", {"reason": "table observations failed"})
                )
            else:
                stages.append(
                    _stage(
                        "table_observations",
                        "passed",
                        {
                            "count": len(scenario.input.observations),
                            "component": table_analyzer.component,
                            "output_schema": "table-observation/v1",
                        },
                    )
                )
                attribution["observation"] = {"status": "passed", "failures": []}
                if self.fail_boundary == "reconstruction":
                    message = "fixture reconstruction stage failed"
                    stages.append(
                        _stage("reconstruction", "failed", {"error": message}, "reconstruction")
                    )
                    attribution["reconstruction"] = {"status": "failed", "failures": [message]}
                else:
                    try:
                        result = reconstruct_round(
                            scenario.input,
                            max_missing_plays=config.max_missing_plays,
                            max_hypotheses=config.max_hypotheses,
                            max_search_nodes=config.max_search_nodes,
                        )
                        expected = scenario.expected.status
                        actual = result.status
                        if actual != expected:
                            message = f"expected reconstruction status {expected}, got {actual}"
                            stages.append(
                                _stage(
                                    "reconstruction",
                                    "failed",
                                    {"error": message, "status": actual},
                                    "reconstruction",
                                )
                            )
                            attribution["reconstruction"] = {
                                "status": "failed",
                                "failures": [message],
                            }
                        else:
                            stages.append(
                                _stage(
                                    "reconstruction",
                                    "passed",
                                    {
                                        "status": actual,
                                        "hypothesis_count": len(result.hypotheses),
                                        "trick_count": len(result.best_hypothesis.tricks)
                                        if result.best_hypothesis is not None
                                        else 0,
                                    },
                                )
                            )
                            attribution["reconstruction"] = {"status": "passed", "failures": []}
                    except (ValueError, RuntimeError) as error:
                        message = str(error)
                        stages.append(
                            _stage("reconstruction", "failed", {"error": message}, "reconstruction")
                        )
                        attribution["reconstruction"] = {
                            "status": "failed",
                            "failures": [message],
                        }

        status = "failed" if any(item["status"] == "failed" for item in stages) else "passed"
        if status == "passed":
            for boundary in FAILURE_BOUNDARIES:
                attribution[boundary] = {"status": "passed", "failures": []}
        return {
            "status": status,
            "stages": stages,
            "failure_attribution": attribution,
            "metrics": {
                "event_proposals": len(scenario.input.observations)
                if self.fail_boundary != "event"
                else 0,
                "table_observations": len(scenario.input.observations)
                if self.fail_boundary not in {"event", "observation"}
                else 0,
            },
        }


@dataclass(frozen=True, slots=True)
class SystemHoldoutReport:
    """Machine-readable result of one immutable system holdout evaluation."""

    evaluation_id: str
    status: str
    recommendation: str
    holdout_registry: Mapping[str, object]
    components: Mapping[str, object]
    reconstruction_config: Mapping[str, object]
    fixture: Mapping[str, object]
    stages: tuple[Mapping[str, object], ...]
    failure_attribution: Mapping[str, object]
    metrics: Mapping[str, object]
    champion_registry_before_digest: str | None
    champion_registry_after_digest: str | None
    generated_at_utc: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SystemHoldoutReport":
        expected = {
            "schema_version",
            "evaluation_id",
            "status",
            "recommendation",
            "holdout_registry",
            "components",
            "reconstruction_config",
            "fixture",
            "stages",
            "failure_attribution",
            "metrics",
            "champion_registry_before_digest",
            "champion_registry_after_digest",
            "generated_at_utc",
        }
        if (
            set(raw) != expected
            or raw.get("schema_version") != SYSTEM_HOLDOUT_EVALUATION_SCHEMA_VERSION
        ):
            raise SystemHoldoutEvaluationError("system holdout report has invalid fields.")
        status = _safe_string(raw.get("status"), "report.status")
        recommendation = _safe_string(raw.get("recommendation"), "report.recommendation")
        if status not in SYSTEM_HOLDOUT_EVALUATION_STATES:
            raise SystemHoldoutEvaluationError("report.status is invalid.")
        if recommendation not in SYSTEM_HOLDOUT_RECOMMENDATIONS:
            raise SystemHoldoutEvaluationError("report.recommendation is invalid.")
        if (status == "passed") != (recommendation == "system_holdout_passed"):
            raise SystemHoldoutEvaluationError("report status and recommendation do not match.")
        stages = raw.get("stages")
        if not isinstance(stages, list) or any(not isinstance(item, Mapping) for item in stages):
            raise SystemHoldoutEvaluationError("report.stages must be a list of objects.")
        attribution = raw.get("failure_attribution")
        if not isinstance(attribution, Mapping) or set(attribution) != set(FAILURE_BOUNDARIES):
            raise SystemHoldoutEvaluationError(
                "report.failure_attribution must cover all boundaries."
            )
        for boundary in FAILURE_BOUNDARIES:
            item = attribution[boundary]
            if not isinstance(item, Mapping) or set(item) != {"status", "failures"}:
                raise SystemHoldoutEvaluationError(
                    f"report failure attribution for {boundary} is invalid."
                )
            if item["status"] not in {"passed", "failed", "not_observed"} or not isinstance(
                item["failures"], list
            ):
                raise SystemHoldoutEvaluationError(
                    f"report failure attribution for {boundary} is invalid."
                )
        before = raw.get("champion_registry_before_digest")
        after = raw.get("champion_registry_after_digest")
        if before is not None and (not isinstance(before, str) or len(before) != 64):
            raise SystemHoldoutEvaluationError("report champion registry digest is invalid.")
        if after is not None and (not isinstance(after, str) or len(after) != 64):
            raise SystemHoldoutEvaluationError("report champion registry digest is invalid.")
        return cls(
            _safe_string(raw.get("evaluation_id"), "report.evaluation_id"),
            status,
            recommendation,
            _mapping(raw.get("holdout_registry"), "report.holdout_registry"),
            _mapping(raw.get("components"), "report.components"),
            _mapping(raw.get("reconstruction_config"), "report.reconstruction_config"),
            _mapping(raw.get("fixture"), "report.fixture"),
            tuple(dict(item) for item in stages),
            dict(attribution),
            _mapping(raw.get("metrics"), "report.metrics"),
            before,
            after,
            _timestamp(raw.get("generated_at_utc"), "report.generated_at_utc"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": SYSTEM_HOLDOUT_EVALUATION_SCHEMA_VERSION,
            "evaluation_id": self.evaluation_id,
            "status": self.status,
            "recommendation": self.recommendation,
            "holdout_registry": dict(self.holdout_registry),
            "components": dict(self.components),
            "reconstruction_config": dict(self.reconstruction_config),
            "fixture": dict(self.fixture),
            "stages": [dict(item) for item in self.stages],
            "failure_attribution": dict(self.failure_attribution),
            "metrics": dict(self.metrics),
            "champion_registry_before_digest": self.champion_registry_before_digest,
            "champion_registry_after_digest": self.champion_registry_after_digest,
            "generated_at_utc": self.generated_at_utc,
        }


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SystemHoldoutEvaluationError(f"{field} must be an object.")
    return dict(value)


def _timestamp(value: object, field: str) -> str:
    result = _safe_string(value, field)
    if not result.endswith("Z"):
        raise SystemHoldoutEvaluationError(f"{field} must use UTC with a Z suffix.")
    try:
        datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as error:
        raise SystemHoldoutEvaluationError(f"{field} must be ISO-8601.") from error
    return result


def _render_report(report: SystemHoldoutReport) -> str:
    lines = [
        "# System holdout evaluation",
        "",
        f"- Evaluation: `{report.evaluation_id}`",
        f"- Status: `{report.status}`",
        f"- Recommendation: `{report.recommendation}`",
        f"- Holdout registry: `{report.holdout_registry['registry_digest']}`",
        "",
        "## Pipeline stages",
        "",
        "| Stage | Status | Failure boundary |",
        "| --- | --- | --- |",
    ]
    for stage in report.stages:
        lines.append(
            f"| `{stage['name']}` | `{stage['status']}` | "
            f"`{stage.get('failure_boundary') or 'none'}` |"
        )
    lines.extend(["", "## Failure attribution", ""])
    for boundary in FAILURE_BOUNDARIES:
        item = report.failure_attribution[boundary]
        lines.append(f"- `{boundary}`: `{item['status']}`")
        for failure in item["failures"]:
            lines.append(f"  - {failure}")
    lines.extend(
        [
            "",
            "The evaluator reads locked component artifacts and does not update component "
            "campaigns or the champion registry.",
            "",
        ]
    )
    return "\n".join(lines)


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _registry_digest(registry: ModelRegistry | None) -> str | None:
    return None if registry is None else sha256_mapping(registry.to_mapping())


def evaluate_system_holdout(
    cardevent_campaign_id: str,
    table_campaign_id: str,
    *,
    repository_root: str | Path,
    cardevent_dataset_path: str | Path,
    cardevent_split_path: str | Path,
    table_dataset_path: str | Path,
    table_split_path: str | Path,
    reconstruction_config_path: str | Path | None = None,
    holdout_registry_path: str | Path | None = None,
    model_registry_path: str | Path | None = None,
    campaign_root: str | Path | None = None,
    fixture_path: str | Path | None = None,
    evaluation_root: str | Path | None = None,
    runner: SystemHoldoutRunner | None = None,
    now_utc: str | None = None,
) -> SystemHoldoutReport:
    """Evaluate two locked component campaigns on the shared holdout.

    This operation is read-only for component campaigns, model bundles, and the champion registry.
    It writes only the separate system evaluation report.  A report is idempotent: a second call
    with the same locked inputs reads the existing result and does not run the fixture again.
    """

    root = Path(repository_root).expanduser().resolve()
    campaigns = _resolve(root, campaign_root or root / "data" / "model-campaigns")
    holdout_path = _resolve(
        root, holdout_registry_path or root / "data" / "operations" / "system-holdout-registry.json"
    )
    registry = load_system_holdout_registry(holdout_path)
    if not registry["seals"]:
        raise SystemHoldoutEvaluationError("system holdout registry has no sealed groups")
    cardevent = _load_locked_component(campaigns, cardevent_campaign_id, component="card-event-net")
    table_analyzer = _load_locked_component(
        campaigns, table_campaign_id, component="table-evidence-analyzer"
    )
    cardevent_isolation = _validate_component_data(
        cardevent,
        dataset_path=_resolve(root, cardevent_dataset_path),
        split_path=_resolve(root, cardevent_split_path),
        registry=registry,
    )
    table_isolation = _validate_component_data(
        table_analyzer,
        dataset_path=_resolve(root, table_dataset_path),
        split_path=_resolve(root, table_split_path),
        registry=registry,
    )
    config_path = _resolve(
        root,
        reconstruction_config_path
        or root / "fixtures" / "model-improvement" / "v1" / "system-reconstruction-config.json",
    )
    config = load_system_reconstruction_config(config_path)
    fixture = _resolve(
        root,
        fixture_path or root / "fixtures" / "game-engine" / "v1" / "rounds" / "unambiguous.json",
    )
    try:
        scenario = load_round_scenario(fixture)
    except (OSError, ValueError) as error:
        raise SystemHoldoutEvaluationError(f"invalid system holdout fixture: {error}") from error
    if config.deck_variant != scenario.input.deck_variant:
        raise SystemHoldoutEvaluationError("reconstruction config deck does not match the fixture")
    fixture_groups = _scenario_groups(scenario)
    held_out = set(sealed_group_keys(registry))
    if not fixture_groups & held_out:
        raise SystemHoldoutEvaluationError(
            "system holdout fixture does not identify a sealed system holdout group"
        )

    model_registry: ModelRegistry | None = None
    registry_path: Path | None = None
    selected_registry_path = model_registry_path or root / "data" / "model-registry.json"
    candidate_registry_path = _resolve(root, selected_registry_path)
    if candidate_registry_path.is_file():
        registry_path = candidate_registry_path
        model_registry = load_model_registry(candidate_registry_path)
    before_digest = _registry_digest(model_registry)
    identity = {
        "schema_version": SYSTEM_HOLDOUT_EVALUATION_SCHEMA_VERSION,
        "holdout_registry_digest": registry["registry_digest"],
        "cardevent": cardevent.to_mapping(),
        "table_analyzer": table_analyzer.to_mapping(),
        "reconstruction_config_digest": config.digest,
        "fixture_digest": _file_digest(fixture),
        "fixture_groups": [list(item) for item in sorted(fixture_groups)],
    }
    evaluation_id = f"system-evaluation-{sha256_mapping(identity)[:24]}"
    output_root = (
        _resolve(root, evaluation_root or root / "data" / "model-system-evaluations")
        / evaluation_id
    )
    report_path = output_root / "report.json"
    if report_path.is_file():
        report = load_system_holdout_report(report_path)
        if report.evaluation_id != evaluation_id:
            raise SystemHoldoutEvaluationError(
                "existing system holdout report has a different identity"
            )
        return report

    command_runner = runner or SystemHoldoutFixtureRunner()
    result = command_runner.run(
        scenario,
        config=config,
        cardevent=cardevent,
        table_analyzer=table_analyzer,
    )
    status = result.get("status")
    if status not in SYSTEM_HOLDOUT_EVALUATION_STATES:
        raise SystemHoldoutEvaluationError("system holdout runner returned an invalid status")
    stages = result.get("stages")
    attribution = result.get("failure_attribution")
    metrics = result.get("metrics", {})
    if (
        not isinstance(stages, list)
        or any(not isinstance(item, Mapping) for item in stages)
        or not isinstance(attribution, Mapping)
        or not isinstance(metrics, Mapping)
    ):
        raise SystemHoldoutEvaluationError("system holdout runner returned an invalid report")
    after_registry = load_model_registry(registry_path) if registry_path is not None else None
    after_digest = _registry_digest(after_registry)
    if before_digest != after_digest:
        raise SystemHoldoutEvaluationError(
            "system holdout evaluation changed the champion registry"
        )
    report = SystemHoldoutReport.from_mapping(
        {
            "schema_version": SYSTEM_HOLDOUT_EVALUATION_SCHEMA_VERSION,
            "evaluation_id": evaluation_id,
            "status": status,
            "recommendation": (
                "system_holdout_passed" if status == "passed" else "human_review_required"
            ),
            "holdout_registry": {
                "registry_id": registry["registry_id"],
                "registry_version": registry["registry_version"],
                "registry_digest": registry["registry_digest"],
                "sealed_group_keys": [list(item) for item in sorted(held_out)],
            },
            "components": {
                "card-event-net": {
                    "artifact": cardevent.to_mapping(),
                    "isolation": cardevent_isolation,
                },
                "table-evidence-analyzer": {
                    "artifact": table_analyzer.to_mapping(),
                    "isolation": table_isolation,
                },
            },
            "reconstruction_config": {
                "config_id": config.config_id,
                "config_version": config.config_version,
                "digest": config.digest,
                "path": str(config_path),
            },
            "fixture": {
                "scenario_id": scenario.scenario_id,
                "path": str(fixture),
                "digest": identity["fixture_digest"],
                "source_group_keys": [list(item) for item in sorted(fixture_groups)],
                "covered_holdout_groups": [
                    list(item) for item in sorted(fixture_groups & held_out)
                ],
            },
            "stages": [dict(item) for item in stages],
            "failure_attribution": dict(attribution),
            "metrics": dict(metrics),
            "champion_registry_before_digest": before_digest,
            "champion_registry_after_digest": after_digest,
            "generated_at_utc": now_utc or _now(),
        }
    )
    _write_json(report_path, report.to_mapping())
    _write_json(output_root / "evaluation.json", report.to_mapping())
    (output_root / "report.md").write_text(_render_report(report), encoding="utf-8")
    return report


def load_system_holdout_report(path: str | Path) -> SystemHoldoutReport:
    """Load and validate one system holdout report."""

    return SystemHoldoutReport.from_mapping(_read_json(Path(path), "system holdout report"))


run_system_holdout_evaluation = evaluate_system_holdout


__all__ = [
    "COMPONENT_LOCK_STATES",
    "FAILURE_BOUNDARIES",
    "SYSTEM_HOLDOUT_EVALUATION_SCHEMA_VERSION",
    "SYSTEM_RECONSTRUCTION_CONFIG_SCHEMA_VERSION",
    "LockedComponentArtifact",
    "SystemHoldoutEvaluationError",
    "SystemHoldoutFixtureRunner",
    "SystemHoldoutRunner",
    "SystemHoldoutReport",
    "SystemReconstructionConfig",
    "evaluate_system_holdout",
    "load_system_holdout_report",
    "load_system_reconstruction_config",
    "run_system_holdout_evaluation",
]
