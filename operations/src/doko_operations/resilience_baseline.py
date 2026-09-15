"""Freeze the epic 0051 resilience measurement contract and inspect coverage.

M0 is deliberately read-only.  It scans accepted recording bundles, immutable pipeline
revisions, and completed maintained references.  It does not create a review, classify a crop,
or change a source artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from table_evidence_analyzer.card_classification import (
    CARD_CLASSIFICATION_SCHEMA,
    PROMPT,
    RESPONSE_SCHEMA,
)
from table_evidence_analyzer.cards import CARD_IDENTITIES
from table_evidence_analyzer.visible_cards import (
    DEFAULT_MODEL,
    GEMINI_API_VERSION,
    GEMINI_THINKING_LEVEL,
)

from .holdout import load_system_holdout_registry, sealed_group_keys
from .intake import inspect_repository

RESILIENCE_BASELINE_SCHEMA_VERSION = "visible-region-identity-resilience-manifest/v1"
MEASUREMENT_CONTRACT_SCHEMA_VERSION = "visible-region-identity-measurement/v1"
MINIMUM_VALIDATION_SAMPLES = 24
DEFAULT_CLASSIFIER_PROVIDER = "gemini"
DEFAULT_CLASSIFIER_MODEL = DEFAULT_MODEL

# These are operator-selected partitions.  They are deliberately explicit because the two
# visually similar 0090/0091 recordings must remain development material, while 0661 is the
# different validation capture.  Do not infer these partitions from identifier ordering.
DEFAULT_PARTITION_RECORDING_IDS = {
    "development": (
        "cardeventnet-IMG_0090",
        "cardeventnet-IMG_0091",
    ),
    "validation": ("cardeventnet-IMG_0661",),
}

CLASSIFIER_IMPLEMENTATION = "visual-identity-classifier-adapter/v1"
RUNTIME_CROP_DEFAULTS = {
    "detector_box": {"policy_id": "raw_rectangular", "output_encoding": "ppm"},
    "predicted_visible_region": {
        "policy_id": "predicted_visible_region",
        "output_encoding": "ppm",
    },
    "reviewed_visible_region": {
        "policy_id": "oracle_visible_region",
        "output_encoding": "ppm",
    },
}
GEMINI_INPUT_TOKENS_PER_REQUEST = 1_200
GEMINI_OUTPUT_TOKENS_PER_REQUEST = 16
GEMINI_INPUT_USD_PER_MILLION_TOKENS = 0.75
GEMINI_OUTPUT_USD_PER_MILLION_TOKENS = 3.75

CONDITION_IDS = (
    "raw_rectangular",
    "predicted_visible_region",
    "generated_other_region_exclusion",
    "predicted_region_with_other_exclusion",
    "reviewed_other_region_exclusion",
    "oracle_visible_region",
)

METRICS = (
    "classified_top1_accuracy",
    "classified_coverage",
    "unusable_rate",
    "end_to_end_correct_identity_recall",
    "high_confidence_error_rate_when_calibrated",
    "operational_failure_rate",
    "retry_count",
    "latency_ms",
    "token_count",
    "estimated_cost_usd",
    "recovered_identities",
    "harmed_identities",
    "results_by_condition_corruption_group_card_count_area_fraction_overlap",
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class ResilienceBaselineError(ValueError):
    """A resilience baseline input or artifact is invalid."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ResilienceBaselineError(f"{field} must be an object")
    return value


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResilienceBaselineError(f"could not read {field} {path}: {error}") from error
    value = _mapping(raw, field)
    return dict(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical JSON bytes used for manifest and lineage digests."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ResilienceBaselineError("baseline values must be finite JSON") from error


def sha256_json(value: Any) -> str:
    """Return the digest of one canonical JSON value."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ResilienceBaselineError(f"{field} must be a safe identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ResilienceBaselineError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _file_json_digest(path: Path, field: str) -> str:
    return sha256_json(_read_json(path, field))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ResilienceBaselineError(f"{path} is outside repository root {root}") from error


def _resolve(root: Path, value: str | Path | None, default: Path) -> Path:
    path = default if value is None else Path(value).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def default_measurement_contract(
    *,
    classifier_provider: str = DEFAULT_CLASSIFIER_PROVIDER,
    classifier_model: str = DEFAULT_CLASSIFIER_MODEL,
) -> dict[str, Any]:
    """Return the immutable M0 contract used by every later baseline run."""

    provider = _identifier(classifier_provider, "classifier_provider")
    model = _identifier(classifier_model, "classifier_model")
    return {
        "schema_version": MEASUREMENT_CONTRACT_SCHEMA_VERSION,
        "input_families": [
            "reviewed_visible_region_oracle",
            "matched_generated_visible_region_prediction",
            "derived_box_raw_condition",
            "deterministic_reviewed_region_corruptions",
        ],
        "conditions": [
            {
                "condition_id": "raw_rectangular",
                "geometry_source": "generated_derived_box",
                "region_source": "none",
                "deployable": True,
            },
            {
                "condition_id": "predicted_visible_region",
                "geometry_source": "generated_visible_region",
                "region_source": "generated_visible_region",
                "deployable": True,
            },
            {
                "condition_id": "generated_other_region_exclusion",
                "geometry_source": "generated_derived_box",
                "region_source": "generated_other_visible_regions",
                "deployable": True,
            },
            {
                "condition_id": "predicted_region_with_other_exclusion",
                "geometry_source": "generated_visible_region",
                "region_source": "generated_other_visible_regions",
                "deployable": True,
            },
            {
                "condition_id": "reviewed_other_region_exclusion",
                "geometry_source": "generated_derived_box",
                "region_source": "reviewed_other_visible_regions",
                "deployable": False,
            },
            {
                "condition_id": "oracle_visible_region",
                "geometry_source": "reviewed_visible_region",
                "region_source": "reviewed_visible_region",
                "deployable": False,
            },
        ],
        "corruptions": [
            {
                "family": "erosion_missing_boundary_pixels",
                "severity_unit": "derived_box_fraction",
                "severities": [0.05, 0.10, 0.20],
                "seed": 5101,
            },
            {
                "family": "dilation_into_background_or_neighbor",
                "severity_unit": "derived_box_fraction",
                "severities": [0.05, 0.10, 0.20],
                "seed": 5102,
            },
            {
                "family": "position_shift",
                "severity_unit": "derived_box_fraction",
                "severities": [0.05, 0.10, 0.20],
                "seed": 5103,
            },
            {
                "family": "holes_missing_connected_components",
                "severity_unit": "visible_area_fraction",
                "severities": [0.05, 0.10, 0.20],
                "seed": 5104,
            },
            {
                "family": "false_disconnected_components",
                "severity_unit": "component_count",
                "severities": [1, 2, 3],
                "seed": 5105,
            },
            {
                "family": "pixels_from_another_visible_card",
                "severity_unit": "target_box_fraction",
                "severities": [0.05, 0.10, 0.20],
                "seed": 5106,
            },
            {
                "family": "complete_derived_box_fallback",
                "severity_unit": "fallback",
                "severities": [1],
                "seed": 5107,
            },
        ],
        "exclusion": {
            "eligibility": "generated_provider_confidence_and_geometry_diagnostics_only",
            "erosion_fraction_of_derived_box": 0.10,
            "material_overlap_fraction": 0.25,
            "fill_value_rgb": [128, 128, 128],
            "disputed_overlap": "leave_unresolved",
            "deduplicate_geometry": True,
            "recursive_exclusion": False,
        },
        "classifier": {
            "provider": provider,
            "model": model,
            "implementation": CLASSIFIER_IMPLEMENTATION,
            "classifier_version": (
                CARD_CLASSIFICATION_SCHEMA
                if provider == DEFAULT_CLASSIFIER_PROVIDER
                else "configured"
            ),
            "score_calibration": "uncalibrated_single_candidate_is_not_probability",
            "request": {
                "schema_version": CARD_CLASSIFICATION_SCHEMA,
                "api_version": GEMINI_API_VERSION,
                "thinking_level": GEMINI_THINKING_LEVEL,
                "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
                "response_schema_sha256": sha256_json(RESPONSE_SCHEMA),
            },
        },
        "runtime_crop_defaults": {
            key: dict(value) for key, value in RUNTIME_CROP_DEFAULTS.items()
        },
        "budget": {
            "max_classifier_requests": 5000,
            "max_estimated_cost_usd": 25.0,
            "max_wall_clock_seconds": 7200,
            "cost_estimate": {
                "input_tokens_per_request": GEMINI_INPUT_TOKENS_PER_REQUEST,
                "output_tokens_per_request": GEMINI_OUTPUT_TOKENS_PER_REQUEST,
                "input_usd_per_million_tokens": GEMINI_INPUT_USD_PER_MILLION_TOKENS,
                "output_usd_per_million_tokens": GEMINI_OUTPUT_USD_PER_MILLION_TOKENS,
            },
        },
        "metrics": list(METRICS),
        "decision_gates": {
            "minimum_classified_top1_accuracy": 0.90,
            "minimum_end_to_end_correct_identity_recall": 0.80,
            "maximum_exclusion_harm_rate": 0.02,
            "minimum_validation_samples": MINIMUM_VALIDATION_SAMPLES,
            "minimum_validation_source_lineage_groups": 1,
        },
        "holdout_policy": {
            "excluded_group_key": "session_id",
            "sealed_system_holdout_is_never_classified": True,
        },
    }


def _recording_inventory(
    intake_root: Path,
    repository_root: Path,
    *,
    operations_root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read complete bundles through the shared repository intake validator."""

    recordings: list[dict[str, Any]] = []
    gaps: list[str] = []
    if not intake_root.is_dir():
        return recordings, [
            f"recording intake root is missing: {_relative(intake_root, repository_root)}"
        ]
    try:
        inspection = inspect_repository(
            repository_root,
            bundle_root=intake_root,
            artifacts_root=operations_root,
        )
    except (OSError, ValueError) as error:
        return recordings, [f"shared recording-bundle validation failed: {error}"]

    for bundle in inspection.bundles:
        if bundle.state != "complete":
            details = "; ".join(bundle.errors) or "bundle is not complete"
            gaps.append(f"shared recording bundle rejected: {bundle.path}: {details}")
            continue
        if not all(
            isinstance(value, str) and value
            for value in (
                bundle.recording_id,
                bundle.session_id,
                bundle.source_asset_id,
                bundle.source_sha256,
            )
        ):
            gaps.append(f"shared recording bundle has incomplete lineage: {bundle.path}")
            continue
        manifest_path = repository_root / bundle.path / "manifest.json"
        try:
            manifest = _read_json(manifest_path, "recording bundle manifest")
            _digest(bundle.source_sha256, f"{bundle.path}.source_sha256")
        except ResilienceBaselineError as error:
            gaps.append(str(error))
            continue
        if manifest.get("recording_id") != bundle.recording_id:
            gaps.append(f"recording bundle directory does not match recording_id: {bundle.path}")
            continue
        recordings.append(
            {
                "recording_id": bundle.recording_id,
                "session_id": bundle.session_id,
                "source_lineage_group": bundle.session_id,
                "source_asset_id": bundle.source_asset_id,
                "source_video_sha256": bundle.source_sha256,
                "manifest_path": _relative(manifest_path, repository_root),
                "manifest_sha256": _file_json_digest(manifest_path, "recording bundle manifest"),
            }
        )
    return recordings, gaps


def _revision_inventory(runtime_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    revisions: dict[str, dict[str, Any]] = {}
    gaps: list[str] = []
    root = runtime_root / "pipeline" / "revisions"
    if not root.is_dir():
        return revisions, []
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.is_symlink() or directory.name.startswith("."):
            continue
        manifest_path = directory / "manifest.json"
        content_path = directory / "content.json"
        if not manifest_path.is_file() or not content_path.is_file():
            gaps.append(f"incomplete pipeline revision directory: {directory}")
            continue
        try:
            manifest = _read_json(manifest_path, "pipeline revision manifest")
            content = _read_json(content_path, "pipeline revision content")
        except ResilienceBaselineError as error:
            gaps.append(str(error))
            continue
        revision_id = manifest.get("revision_id")
        if not isinstance(revision_id, str) or revision_id != directory.name:
            gaps.append(f"pipeline revision directory does not match revision_id: {directory}")
            continue
        declared_digest = manifest.get("content_sha256")
        actual_digest = sha256_json(content)
        if declared_digest != actual_digest:
            gaps.append(f"pipeline revision content digest mismatch: {revision_id}")
            continue
        revisions[revision_id] = {
            "manifest": manifest,
            "content": content,
            "manifest_path": manifest_path,
            "content_path": content_path,
        }
    return revisions, gaps


def _reference_inventory(operations_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    references: list[dict[str, Any]] = []
    gaps: list[str] = []
    root = operations_root / "pipeline-references"
    if not root.is_dir():
        return references, []
    for recording_directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not recording_directory.is_dir() or recording_directory.is_symlink():
            continue
        for content_directory in sorted(recording_directory.iterdir(), key=lambda item: item.name):
            if not content_directory.is_dir() or content_directory.is_symlink():
                continue
            state_path = content_directory / "state.json"
            draft_path = content_directory / "draft.json"
            if not state_path.is_file() or not draft_path.is_file():
                gaps.append(f"incomplete maintained reference: {content_directory}")
                continue
            try:
                state = _read_json(state_path, "pipeline reference state")
                draft = _read_json(draft_path, "pipeline reference draft")
            except ResilienceBaselineError as error:
                gaps.append(str(error))
                continue
            if state.get("draft_state") != "completed":
                continue
            selected_revision_id = state.get("selected_completed_revision_id")
            if not isinstance(selected_revision_id, str) or not selected_revision_id:
                gaps.append(
                    f"completed maintained reference has no selected revision: {content_directory}"
                )
                continue
            if (
                state.get("recording_id") != recording_directory.name
                or state.get("content_type") != content_directory.name
            ):
                gaps.append(f"maintained reference path and state disagree: {content_directory}")
                continue
            if draft.get("recording_id") != state.get("recording_id") or draft.get(
                "content_type"
            ) != state.get("content_type"):
                gaps.append(f"maintained reference state and draft disagree: {content_directory}")
                continue
            references.append(
                {
                    "recording_id": recording_directory.name,
                    "content_type": content_directory.name,
                    "selected_revision_id": selected_revision_id,
                    "state": state,
                    "draft": draft,
                    "state_path": state_path,
                    "draft_path": draft_path,
                }
            )
    return references, gaps


def _frame_key(frame: Any) -> tuple[Any, ...] | None:
    if not isinstance(frame, Mapping):
        return None
    return tuple(
        frame.get(key)
        for key in (
            "source_video_sha256",
            "requested_time_us",
            "frame_index",
            "presentation_timestamp_us",
        )
    )


def _reference_items(
    reference: Mapping[str, Any], revision: Mapping[str, Any]
) -> list[dict[str, Any]]:
    content = _mapping(revision.get("content"), "reference revision content")
    content_type = reference["content_type"]
    key = "outcomes" if content_type in {"visible_cards", "visual_identities"} else content_type
    raw_items = content.get(key)
    if not isinstance(raw_items, list):
        raise ResilienceBaselineError(
            f"{reference['selected_revision_id']} has no {key} list for {content_type}"
        )
    raw_draft_items = reference["draft"].get("items")
    if not isinstance(raw_draft_items, list):
        raise ResilienceBaselineError(
            f"maintained reference draft has no items: {reference['recording_id']}/{content_type}"
        )
    draft_by_id = {
        item.get("item_id"): item
        for item in raw_draft_items
        if isinstance(item, Mapping) and isinstance(item.get("item_id"), str)
    }
    result: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise ResilienceBaselineError(
                f"reference revision has a non-object item: {reference['selected_revision_id']}"
            )
        item_id = item.get("event_id") if content_type == "visible_cards" else item.get("card_id")
        if not isinstance(item_id, str):
            raise ResilienceBaselineError(
                f"reference item has no stable item ID: {reference['selected_revision_id']}"
            )
        draft_item = draft_by_id.get(item_id)
        if draft_item is None:
            raise ResilienceBaselineError(f"reference item is absent from its draft: {item_id}")
        result.append({"item": dict(item), "draft": dict(draft_item)})
    return result


def _generated_visible_revision_id(
    visible_revision_id: str,
    revisions: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, list[str]]:
    """Follow maintained-reference producers to the immutable generated proposal revision."""

    gaps: list[str] = []
    current_id: str | None = visible_revision_id
    visited: set[str] = set()
    while isinstance(current_id, str):
        if current_id in visited:
            gaps.append(f"visible reference lineage contains a cycle: {visible_revision_id}")
            return None, gaps
        visited.add(current_id)
        revision = revisions.get(current_id)
        if revision is None:
            gaps.append(f"completed reference revision is missing: {current_id}")
            return None, gaps
        manifest = revision["manifest"]
        origin = manifest.get("origin")
        producer = manifest.get("producer")
        if (
            origin in {"processor", "import"}
            and isinstance(producer, Mapping)
            and producer.get("kind") in {"processor", "import"}
        ):
            if manifest.get("content_type") != "visible_cards":
                gaps.append(f"generated proposal revision is not visible-card data: {current_id}")
                return None, gaps
            return current_id, gaps
        if origin not in {"manual", "corrected"} or not isinstance(producer, Mapping):
            gaps.append(f"visible reference has no generated proposal lineage: {current_id}")
            return None, gaps
        base_revision_id = producer.get("base_revision_id")
        if not isinstance(base_revision_id, str) or not base_revision_id:
            gaps.append(f"visible reference has no generated proposal base revision: {current_id}")
            return None, gaps
        current_id = base_revision_id
    return None, gaps


def _paired_samples(
    recording: Mapping[str, Any],
    visible_reference: Mapping[str, Any],
    identity_reference: Mapping[str, Any],
    revisions: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    gaps: list[str] = []
    visible_revision = revisions.get(visible_reference["selected_revision_id"])
    identity_revision = revisions.get(identity_reference["selected_revision_id"])
    if visible_revision is None or identity_revision is None:
        missing = [
            revision_id
            for revision_id, revision in (
                (visible_reference["selected_revision_id"], visible_revision),
                (identity_reference["selected_revision_id"], identity_revision),
            )
            if revision is None
        ]
        return [], [f"completed reference revision is missing: {', '.join(missing)}"]
    for reference, expected_type in (
        (visible_reference, "visible_cards"),
        (identity_reference, "visual_identities"),
    ):
        manifest = (
            visible_revision["manifest"]
            if expected_type == "visible_cards"
            else identity_revision["manifest"]
        )
        if manifest.get("recording_id") != recording["recording_id"]:
            gaps.append(
                "reference revision belongs to another recording: "
                f"{reference['selected_revision_id']}"
            )
        if manifest.get("content_type") != expected_type:
            gaps.append(
                f"reference revision has wrong content type: {reference['selected_revision_id']}"
            )
        if manifest.get("origin") not in {"manual", "corrected"}:
            gaps.append(
                f"reference revision is not human-maintained: {reference['selected_revision_id']}"
            )
        producer = manifest.get("producer")
        if not isinstance(producer, Mapping) or producer.get("kind") != "human":
            gaps.append(
                f"reference revision has no human lineage: {reference['selected_revision_id']}"
            )
    visible_items = _reference_items(visible_reference, visible_revision)
    identity_items = _reference_items(identity_reference, identity_revision)
    identity_by_card = {
        item["item"].get("card_id"): item
        for item in identity_items
        if isinstance(item["item"].get("card_id"), str)
    }
    source_revision_id, lineage_gaps = _generated_visible_revision_id(
        visible_reference["selected_revision_id"], revisions
    )
    gaps.extend(lineage_gaps)
    generated_revision = revisions.get(source_revision_id) if source_revision_id else None
    if source_revision_id is None or generated_revision is None:
        return [], gaps
    generated_content = generated_revision["content"] if generated_revision is not None else None
    generated_outcomes = {
        item.get("event_id"): item
        for item in (generated_content or {}).get("outcomes", [])
        if isinstance(item, Mapping) and isinstance(item.get("event_id"), str)
    }
    generated_cards = {
        candidate.get("card_id"): outcome.get("event_id")
        for outcome in (generated_content or {}).get("outcomes", [])
        if isinstance(outcome, Mapping)
        for candidate in outcome.get("candidates", [])
        if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str)
    }
    samples: list[dict[str, Any]] = []
    for visible in visible_items:
        item = visible["item"]
        draft = visible["draft"]
        if item.get("status") != "detected":
            continue
        candidates = item.get("candidates")
        if not isinstance(candidates, list):
            gaps.append(f"visible reference item has invalid candidates: {item.get('event_id')}")
            continue
        generated_item_id = draft.get("base_item_id")
        if not isinstance(generated_item_id, str):
            generated_item_id = None
            for candidate in candidates:
                if isinstance(candidate, Mapping):
                    generated_item_id = generated_cards.get(candidate.get("card_id"))
                    if generated_item_id is not None:
                        break
        generated_item = (
            generated_outcomes.get(generated_item_id)
            if isinstance(generated_item_id, str)
            else None
        )
        if generated_item is None:
            gaps.append(f"generated proposal item is missing: {generated_item_id}")
            continue
        for candidate in candidates:
            if not isinstance(candidate, Mapping) or not isinstance(candidate.get("card_id"), str):
                gaps.append(
                    f"visible reference candidate has no card lineage: {item.get('event_id')}"
                )
                continue
            identity = identity_by_card.get(candidate["card_id"])
            if identity is None:
                gaps.append(f"visible card {candidate['card_id']} has no paired identity reference")
                continue
            identity_item = identity["item"]
            identity_draft = identity["draft"]
            frame_key = _frame_key(item.get("frame_identity"))
            identity_frame_key = _frame_key(identity_item.get("frame_identity"))
            if frame_key is None or frame_key != identity_frame_key:
                gaps.append(
                    f"paired references do not use the same source frame: {candidate['card_id']}"
                )
                continue
            if (
                item["frame_identity"].get("source_video_sha256")
                != recording["source_video_sha256"]
            ):
                gaps.append(
                    f"visible region points to a different source video: {candidate['card_id']}"
                )
                continue
            if (
                identity_item["frame_identity"].get("source_video_sha256")
                != recording["source_video_sha256"]
            ):
                gaps.append(
                    f"visual identity points to a different source video: {candidate['card_id']}"
                )
                continue
            if draft.get("review_state") not in {"accepted", "corrected"}:
                gaps.append(f"visible card is not completed as reviewed: {item.get('event_id')}")
                continue
            if (
                identity_draft.get("review_state") not in {"accepted", "corrected"}
                or identity_item.get("status") != "classified"
            ):
                gaps.append(
                    f"visual identity is not completed as classified: {candidate['card_id']}"
                )
                continue
            if (
                not isinstance(identity_item.get("candidates"), list)
                or not identity_item["candidates"]
            ):
                gaps.append(
                    f"visual identity has no reviewed target candidate: {candidate['card_id']}"
                )
                continue
            target_identity = identity_item["candidates"][0].get("identity")
            if not isinstance(target_identity, str) or target_identity not in CARD_IDENTITIES:
                gaps.append(
                    f"visual identity target has no canonical identity: {candidate['card_id']}"
                )
                continue
            sample_id = (
                "sample-"
                + sha256_json(
                    {
                        "recording_id": recording["recording_id"],
                        "event_id": item["event_id"],
                        "card_id": candidate["card_id"],
                        "frame": item["frame_identity"],
                    }
                )[:24]
            )
            samples.append(
                {
                    "sample_id": sample_id,
                    "recording_id": recording["recording_id"],
                    "source_lineage_group": recording["source_lineage_group"],
                    "source_asset_id": recording["source_asset_id"],
                    "source_video_sha256": recording["source_video_sha256"],
                    "visible_card_reference_revision_id": visible_reference["selected_revision_id"],
                    "visual_identity_reference_revision_id": identity_reference[
                        "selected_revision_id"
                    ],
                    "visible_card_item_id": item["event_id"],
                    "visual_identity_item_id": identity_item["card_id"],
                    "generated_visible_card_revision_id": source_revision_id,
                    "generated_visible_card_item_id": generated_item_id,
                    "generated_geometry_is_prediction": True,
                    "generated_item_present": True,
                    "frame_identity_digest": sha256_json(item["frame_identity"]),
                    "reviewed_visible_geometry_digest": sha256_json(candidate["geometry"]),
                    "reviewed_identity_geometry_digest": sha256_json(identity_item.get("geometry")),
                    "reviewed_target_identity": target_identity,
                }
            )
    return samples, gaps


def _partition_recording_ids(
    recordings: Sequence[Mapping[str, Any]],
    requested: Mapping[str, Sequence[str]] | None,
) -> tuple[dict[str, list[str]], list[str]]:
    """Resolve the operator-selected recording partition without sorting into validation."""

    source = DEFAULT_PARTITION_RECORDING_IDS if requested is None else requested
    gaps: list[str] = []
    if set(source) != {"development", "validation"}:
        raise ResilienceBaselineError(
            "partition_recording_ids must contain development and validation only"
        )
    available = {recording["recording_id"] for recording in recordings}
    result: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    for partition in ("development", "validation"):
        recording_ids = source[partition]
        if isinstance(recording_ids, (str, bytes)):
            raise ResilienceBaselineError(f"partition_recording_ids.{partition} must be a list")
        result[partition] = []
        for recording_id in recording_ids:
            _identifier(recording_id, f"partition_recording_ids.{partition}[]")
            previous = seen.get(recording_id)
            if previous is not None:
                gaps.append(
                    f"recording {recording_id} is assigned to both {previous} and {partition}"
                )
                continue
            seen[recording_id] = partition
            result[partition].append(recording_id)
            if recording_id not in available:
                gaps.append(
                    f"partition recording is not an accepted shared bundle: {recording_id}"
                )
    if not result["development"]:
        gaps.append("the explicit development partition has no recording")
    if not result["validation"]:
        gaps.append("the explicit validation partition has no recording")
    return result, gaps


def _work_matrix(
    samples: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Expand selected samples into the immutable condition/corruption request matrix."""

    corruptions: list[dict[str, Any] | None] = [None]
    for corruption in contract["corruptions"]:
        for severity in corruption["severities"]:
            corruptions.append(
                {
                    "family": corruption["family"],
                    "severity": severity,
                    "seed": corruption["seed"],
                }
            )
    matrix: list[dict[str, Any]] = []
    for sample in sorted(samples, key=lambda item: str(item["sample_id"])):
        partition = str(sample["partition"])
        for condition in contract["conditions"]:
            condition_id = condition["condition_id"]
            for corruption in corruptions:
                matrix.append(
                    {
                        "sample_id": sample["sample_id"],
                        "partition": partition,
                        "condition_id": condition_id,
                        "corruption": corruption,
                    }
                )
    return matrix


def _estimated_cost_usd(request_count: int, contract: Mapping[str, Any]) -> float:
    estimate = _mapping(contract["budget"], "measurement_contract.budget")["cost_estimate"]
    return round(
        request_count
        * (
            estimate["input_tokens_per_request"]
            * estimate["input_usd_per_million_tokens"]
            / 1_000_000
            + estimate["output_tokens_per_request"]
            * estimate["output_usd_per_million_tokens"]
            / 1_000_000
        ),
        10,
    )


def build_resilience_baseline_manifest(
    repository_root: str | Path,
    *,
    runtime_root: str | Path | None = None,
    operations_root: str | Path | None = None,
    intake_root: str | Path | None = None,
    holdout_registry_path: str | Path | None = None,
    classifier_provider: str = DEFAULT_CLASSIFIER_PROVIDER,
    classifier_model: str = DEFAULT_CLASSIFIER_MODEL,
    partition_recording_ids: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Build the deterministic M0 manifest and coverage report."""

    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root, repository / "data" / "operations")
    revisions_root = _resolve(repository, runtime_root, operations)
    intake = _resolve(repository, intake_root, repository / "data" / "intake" / "recordings")
    holdout_path = _resolve(
        repository, holdout_registry_path, operations / "system-holdout-registry.json"
    )
    contract = default_measurement_contract(
        classifier_provider=classifier_provider,
        classifier_model=classifier_model,
    )
    recordings, recording_gaps = _recording_inventory(
        intake, repository, operations_root=operations
    )
    revisions, revision_gaps = _revision_inventory(revisions_root)
    references, reference_gaps = _reference_inventory(operations)
    try:
        holdout_registry = load_system_holdout_registry(holdout_path)
        held_out = sealed_group_keys(holdout_registry)
    except (OSError, ValueError) as error:
        raise ResilienceBaselineError(f"could not load system holdout registry: {error}") from error
    by_recording = {recording["recording_id"]: recording for recording in recordings}
    partition_ids, partition_gaps = _partition_recording_ids(recordings, partition_recording_ids)
    references_by_key = {
        (reference["recording_id"], reference["content_type"]): reference
        for reference in references
    }
    partition_recording_set = {
        recording_id
        for recording_ids in partition_ids.values()
        for recording_id in recording_ids
    }
    samples: list[dict[str, Any]] = []
    gaps = [*recording_gaps, *revision_gaps, *reference_gaps]
    selected_partition_pair_gaps: list[str] = []
    for recording in recordings:
        recording_id = recording["recording_id"]
        visible_reference = references_by_key.get((recording_id, "visible_cards"))
        identity_reference = references_by_key.get((recording_id, "visual_identities"))
        if visible_reference is None or identity_reference is None:
            missing = [
                content_type
                for content_type, reference in (
                    ("visible_cards", visible_reference),
                    ("visual_identities", identity_reference),
                )
                if reference is None
            ]
            gaps.append(
                f"recording {recording_id} "
                f"(source-lineage group {recording['source_lineage_group']}) "
                f"needs completed maintained reference(s): {', '.join(missing)}"
            )
            continue
        if ("session_id", recording["source_lineage_group"]) in held_out:
            gaps.append(
                f"recording {recording_id} is in the sealed system holdout and is "
                "excluded from M0 samples"
            )
            continue
        try:
            paired, pair_gaps = _paired_samples(
                recording, visible_reference, identity_reference, revisions
            )
        except ResilienceBaselineError as error:
            paired, pair_gaps = [], [str(error)]
        samples.extend(paired)
        gaps.extend(pair_gaps)
        if recording_id in partition_recording_set:
            selected_partition_pair_gaps.extend(pair_gaps)
    referenced_recording_ids = {reference["recording_id"] for reference in references}
    for recording_id in sorted(referenced_recording_ids - set(by_recording)):
        gaps.append(f"maintained references point to an unknown recording bundle: {recording_id}")
    gaps.extend(partition_gaps)
    partition_for_recording = {
        recording_id: partition
        for partition, recording_ids in partition_ids.items()
        for recording_id in recording_ids
        if recording_id in by_recording
    }
    partitioned_samples: list[dict[str, Any]] = []
    for sample in samples:
        partition = partition_for_recording.get(sample["recording_id"])
        if partition is None:
            continue
        partitioned_samples.append({**sample, "partition": partition})
    development_samples = [
        sample for sample in partitioned_samples if sample["partition"] == "development"
    ]
    validation_samples = [
        sample for sample in partitioned_samples if sample["partition"] == "validation"
    ]
    development_groups = sorted(
        {
            by_recording[recording_id]["source_lineage_group"]
            for recording_id in partition_ids["development"]
            if recording_id in by_recording
        }
    )
    validation_groups = sorted(
        {
            by_recording[recording_id]["source_lineage_group"]
            for recording_id in partition_ids["validation"]
            if recording_id in by_recording
        }
    )
    blocking_gaps: list[str] = []
    blocking_gaps.extend(selected_partition_pair_gaps)
    held_out_partition_recordings = [
        recording_id
        for partition_recording_ids in partition_ids.values()
        for recording_id in partition_recording_ids
        if recording_id in by_recording
        and ("session_id", by_recording[recording_id]["source_lineage_group"]) in held_out
    ]
    if held_out_partition_recordings:
        blocking_gaps.append(
            "partition recordings must not be in the sealed system holdout: "
            + ", ".join(sorted(held_out_partition_recordings))
        )
    overlapping_groups = sorted(
        set(development_groups).intersection(validation_groups)
    )
    if overlapping_groups:
        blocking_gaps.append(
            "development and validation partitions share source-lineage groups: "
            + ", ".join(overlapping_groups)
        )
    if not development_groups or not validation_groups:
        blocking_gaps.append(
            "need paired completed maintained visible-card and visual identity references "
            "in explicit development and validation source-lineage groups"
        )
    if len(validation_samples) < MINIMUM_VALIDATION_SAMPLES:
        blocking_gaps.append(
            f"validation coverage needs {MINIMUM_VALIDATION_SAMPLES} paired samples; "
            f"found {len(validation_samples)}"
        )
    gaps.extend(blocking_gaps)

    budget = _mapping(contract["budget"], "measurement_contract.budget")
    requests_per_sample = len(CONDITION_IDS) * (
        1 + sum(len(item["severities"]) for item in contract["corruptions"])
    )
    max_requests = budget["max_classifier_requests"]
    max_samples = max_requests // requests_per_sample
    selected_validation = sorted(validation_samples, key=lambda item: item["sample_id"])[
        : min(len(validation_samples), max_samples)
    ]
    remaining_capacity = max(0, max_samples - len(selected_validation))
    selected_development = sorted(development_samples, key=lambda item: item["sample_id"])[
        :remaining_capacity
    ]
    selected_samples = [*selected_development, *selected_validation]
    matrix = _work_matrix(selected_samples, contract)
    planned_cost = _estimated_cost_usd(len(matrix), contract)
    if max_samples < MINIMUM_VALIDATION_SAMPLES:
        blocking_gaps.append(
            "classifier request budget cannot fit the minimum validation sample count: "
            f"{max_samples} samples at {requests_per_sample} requests per sample"
        )
    if planned_cost > budget["max_estimated_cost_usd"]:
        blocking_gaps.append(
            "classifier cost estimate exceeds the frozen budget: "
            f"${planned_cost:.4f} > ${budget['max_estimated_cost_usd']:.4f}"
        )
    gaps.extend(blocking_gaps)
    source_groups = []
    for group in sorted({recording["source_lineage_group"] for recording in recordings}):
        source_groups.append(
            {
                "source_lineage_group": group,
                "group_key": "session_id",
                "recording_ids": sorted(
                    recording["recording_id"]
                    for recording in recordings
                    if recording["source_lineage_group"] == group
                ),
                "paired_sample_count": sum(
                    sample["source_lineage_group"] == group for sample in partitioned_samples
                ),
                "system_holdout": ("session_id", group) in held_out,
            }
        )
    manifest = {
        "schema_version": RESILIENCE_BASELINE_SCHEMA_VERSION,
        "baseline_id": "0051-m0-resilience-baseline",
        "classification_state": "not_started",
        "validation_classification_allowed": not blocking_gaps,
        "measurement_contract": contract,
        "measurement_contract_sha256": sha256_json(contract),
        "source_groups": source_groups,
        "partitions": {
            "recording_ids": partition_ids,
            "development_source_lineage_groups": development_groups,
            "validation_source_lineage_groups": validation_groups,
            "system_holdout_excluded_groups": sorted(
                group for name, group in held_out if name == "session_id"
            ),
        },
        "inventory": {
            "recording_count": len(recordings),
            "completed_reference_count": len(references),
            "pipeline_revision_count": len(revisions),
            "paired_sample_count": len(samples),
            "validation_sample_count": len(validation_samples),
        },
        "experiment_plan": {
            "schema_version": "visible-region-identity-resilience-matrix/v1",
            "available_paired_sample_count": len(partitioned_samples),
            "selected_paired_sample_count": len(selected_samples),
            "requests_per_sample": requests_per_sample,
            "planned_classifier_request_count": len(matrix),
            "estimated_cost_usd": planned_cost,
            "estimated_wall_clock_seconds": budget["max_wall_clock_seconds"],
            "matrix_sha256": sha256_json(matrix),
            "matrix": matrix,
        },
        "coverage_report": {
            "available_sample_ids": sorted(sample["sample_id"] for sample in partitioned_samples),
            "selected_sample_ids": sorted(sample["sample_id"] for sample in selected_samples),
            "available_by_partition": {
                "development": len(development_samples),
                "validation": len(validation_samples),
            },
            "selected_by_partition": {
                "development": len(selected_development),
                "validation": len(selected_validation),
            },
            "required_validation_samples": MINIMUM_VALIDATION_SAMPLES,
            "validation_classification_allowed": not blocking_gaps,
            "gaps": sorted(set(gaps)),
        },
        "paired_samples": selected_samples,
        "coverage_gaps": sorted(set(gaps)),
        "required_review_actions": sorted(
            gap for gap in set(gaps) if "needs completed maintained reference" in gap
        ),
        "holdout_registry": {
            "path": _relative(holdout_path, repository) if holdout_path.exists() else None,
            "registry_version": holdout_registry["registry_version"],
            "registry_digest": holdout_registry["registry_digest"],
        },
    }
    return json.loads(canonical_json_bytes(manifest).decode("utf-8"))


def validate_resilience_baseline_manifest(raw: Mapping[str, Any]) -> None:
    """Validate the strict, immutable M0 manifest contract."""

    data = _mapping(raw, "resilience baseline manifest")
    expected = {
        "schema_version",
        "baseline_id",
        "classification_state",
        "validation_classification_allowed",
        "measurement_contract",
        "measurement_contract_sha256",
        "source_groups",
        "partitions",
        "inventory",
        "experiment_plan",
        "coverage_report",
        "paired_samples",
        "coverage_gaps",
        "required_review_actions",
        "holdout_registry",
    }
    if set(data) != expected:
        raise ResilienceBaselineError("resilience baseline manifest has invalid fields")
    if data["schema_version"] != RESILIENCE_BASELINE_SCHEMA_VERSION:
        raise ResilienceBaselineError("resilience baseline manifest has an unsupported schema")
    if data["baseline_id"] != "0051-m0-resilience-baseline":
        raise ResilienceBaselineError("resilience baseline manifest has an invalid baseline_id")
    if data["classification_state"] != "not_started":
        raise ResilienceBaselineError(
            "M0 manifests cannot record classifier results or start validation classification"
        )
    if not isinstance(data["validation_classification_allowed"], bool):
        raise ResilienceBaselineError("validation_classification_allowed must be boolean")
    contract = _mapping(data["measurement_contract"], "measurement_contract")
    if contract.get("schema_version") != MEASUREMENT_CONTRACT_SCHEMA_VERSION:
        raise ResilienceBaselineError("measurement contract has an unsupported schema")
    condition_ids = [
        item.get("condition_id")
        for item in contract.get("conditions", [])
        if isinstance(item, Mapping)
    ]
    if condition_ids != list(CONDITION_IDS):
        raise ResilienceBaselineError("measurement contract conditions are not frozen")
    corruption_families = {
        item.get("family") for item in contract.get("corruptions", []) if isinstance(item, Mapping)
    }
    expected_corruption_families = {
        "erosion_missing_boundary_pixels",
        "dilation_into_background_or_neighbor",
        "position_shift",
        "holes_missing_connected_components",
        "false_disconnected_components",
        "pixels_from_another_visible_card",
        "complete_derived_box_fallback",
    }
    if corruption_families != expected_corruption_families:
        raise ResilienceBaselineError("measurement contract corruption families are incomplete")
    if contract.get("exclusion", {}).get("recursive_exclusion") is not False:
        raise ResilienceBaselineError("measurement contract permits recursive exclusion")
    classifier = _mapping(contract.get("classifier"), "measurement_contract.classifier")
    if classifier.get("provider") == DEFAULT_CLASSIFIER_PROVIDER:
        if classifier.get("model") != DEFAULT_CLASSIFIER_MODEL:
            raise ResilienceBaselineError("measurement contract classifier model is not frozen")
        if classifier.get("implementation") != CLASSIFIER_IMPLEMENTATION:
            raise ResilienceBaselineError(
                "measurement contract classifier implementation is not frozen"
            )
        request = _mapping(classifier.get("request"), "measurement_contract.classifier.request")
        expected_request = {
            "schema_version": CARD_CLASSIFICATION_SCHEMA,
            "api_version": GEMINI_API_VERSION,
            "thinking_level": GEMINI_THINKING_LEVEL,
            "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
            "response_schema_sha256": sha256_json(RESPONSE_SCHEMA),
        }
        if dict(request) != expected_request:
            raise ResilienceBaselineError("measurement contract classifier request is not frozen")
    if contract.get("runtime_crop_defaults") != RUNTIME_CROP_DEFAULTS:
        raise ResilienceBaselineError("measurement contract runtime crop defaults are not frozen")
    if data["measurement_contract_sha256"] != sha256_json(contract):
        raise ResilienceBaselineError("measurement_contract_sha256 does not match its content")
    for field in (
        "source_groups",
        "paired_samples",
        "coverage_gaps",
        "required_review_actions",
    ):
        if not isinstance(data[field], list):
            raise ResilienceBaselineError(f"{field} must be a list")
    partitions = _mapping(data["partitions"], "partitions")
    if set(partitions) != {
        "recording_ids",
        "development_source_lineage_groups",
        "validation_source_lineage_groups",
        "system_holdout_excluded_groups",
    }:
        raise ResilienceBaselineError("partitions has invalid fields")
    recording_ids = _mapping(partitions["recording_ids"], "partitions.recording_ids")
    if set(recording_ids) != {"development", "validation"}:
        raise ResilienceBaselineError("partitions.recording_ids has invalid fields")
    for partition in ("development", "validation"):
        if not isinstance(recording_ids[partition], list):
            raise ResilienceBaselineError(f"partitions.recording_ids.{partition} must be a list")
    for field in (
        "development_source_lineage_groups",
        "validation_source_lineage_groups",
        "system_holdout_excluded_groups",
    ):
        if not isinstance(partitions.get(field), list):
            raise ResilienceBaselineError(f"partitions.{field} must be a list")
    if set(recording_ids["development"]).intersection(recording_ids["validation"]):
        raise ResilienceBaselineError("partitions assign one recording to both partitions")
    if set(partitions["development_source_lineage_groups"]).intersection(
        partitions["validation_source_lineage_groups"]
    ):
        raise ResilienceBaselineError("partitions share a source-lineage group")
    experiment = _mapping(data["experiment_plan"], "experiment_plan")
    if set(experiment) != {
        "schema_version",
        "available_paired_sample_count",
        "selected_paired_sample_count",
        "requests_per_sample",
        "planned_classifier_request_count",
        "estimated_cost_usd",
        "estimated_wall_clock_seconds",
        "matrix_sha256",
        "matrix",
    }:
        raise ResilienceBaselineError("experiment_plan has invalid fields")
    if experiment["schema_version"] != "visible-region-identity-resilience-matrix/v1":
        raise ResilienceBaselineError("experiment_plan has an unsupported schema")
    for field in (
        "available_paired_sample_count",
        "selected_paired_sample_count",
        "requests_per_sample",
        "planned_classifier_request_count",
    ):
        if isinstance(experiment[field], bool) or not isinstance(experiment[field], int):
            raise ResilienceBaselineError(f"experiment_plan.{field} must be an integer")
        if experiment[field] < 0:
            raise ResilienceBaselineError(f"experiment_plan.{field} must not be negative")
    matrix = experiment["matrix"]
    if not isinstance(matrix, list):
        raise ResilienceBaselineError("experiment_plan.matrix must be a list")
    if experiment["planned_classifier_request_count"] != len(matrix):
        raise ResilienceBaselineError("experiment_plan request count does not match its matrix")
    if experiment["matrix_sha256"] != sha256_json(matrix):
        raise ResilienceBaselineError("experiment_plan.matrix_sha256 does not match its matrix")
    if experiment["selected_paired_sample_count"] != len(data["paired_samples"]):
        raise ResilienceBaselineError(
            "experiment_plan selected sample count does not match paired_samples"
        )
    expected_requests_per_sample = len(CONDITION_IDS) * (
        1 + sum(len(item["severities"]) for item in contract["corruptions"])
    )
    if experiment["requests_per_sample"] != expected_requests_per_sample:
        raise ResilienceBaselineError("experiment_plan requests per sample are not frozen")
    if experiment["planned_classifier_request_count"] != (
        experiment["selected_paired_sample_count"] * expected_requests_per_sample
    ):
        raise ResilienceBaselineError("experiment_plan matrix is incomplete")
    if matrix != _work_matrix(data["paired_samples"], contract):
        raise ResilienceBaselineError("experiment_plan matrix does not match frozen inputs")
    if experiment["estimated_cost_usd"] != _estimated_cost_usd(len(matrix), contract):
        raise ResilienceBaselineError("experiment_plan cost estimate does not match its matrix")
    budget = _mapping(contract["budget"], "measurement_contract.budget")
    if experiment["planned_classifier_request_count"] > budget["max_classifier_requests"]:
        raise ResilienceBaselineError("experiment_plan exceeds the classifier request budget")
    if experiment["estimated_cost_usd"] > budget["max_estimated_cost_usd"]:
        raise ResilienceBaselineError("experiment_plan exceeds the estimated cost budget")
    coverage = _mapping(data["coverage_report"], "coverage_report")
    if set(coverage) != {
        "available_sample_ids",
        "selected_sample_ids",
        "available_by_partition",
        "selected_by_partition",
        "required_validation_samples",
        "validation_classification_allowed",
        "gaps",
    }:
        raise ResilienceBaselineError("coverage_report has invalid fields")
    for field in ("available_sample_ids", "selected_sample_ids", "gaps"):
        if not isinstance(coverage[field], list):
            raise ResilienceBaselineError(f"coverage_report.{field} must be a list")
    if not isinstance(coverage["validation_classification_allowed"], bool):
        raise ResilienceBaselineError(
            "coverage_report.validation_classification_allowed must be boolean"
        )
    if coverage["validation_classification_allowed"] != data["validation_classification_allowed"]:
        raise ResilienceBaselineError(
            "coverage_report validation status does not match the manifest"
        )
    sample_ids: list[str] = []
    for index, sample in enumerate(data["paired_samples"]):
        sample_data = _mapping(sample, f"paired_samples[{index}]")
        sample_id = sample_data.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise ResilienceBaselineError(f"paired_samples[{index}] has no sample_id")
        sample_ids.append(sample_id)
    if coverage["selected_sample_ids"] != sorted(sample_ids):
        raise ResilienceBaselineError("coverage_report selected samples do not match the manifest")
    if coverage["required_validation_samples"] != MINIMUM_VALIDATION_SAMPLES:
        raise ResilienceBaselineError("coverage_report validation minimum is not frozen")
    for field in ("available_by_partition", "selected_by_partition"):
        counts = _mapping(coverage[field], f"coverage_report.{field}")
        if set(counts) != {"development", "validation"} or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        ):
            raise ResilienceBaselineError(f"coverage_report.{field} is invalid")
    selected_counts = {
        partition: sum(
            sample.get("partition") == partition for sample in data["paired_samples"]
        )
        for partition in ("development", "validation")
    }
    if dict(coverage["selected_by_partition"]) != selected_counts:
        raise ResilienceBaselineError("coverage_report selected partition counts are stale")
    if any(
        coverage["selected_by_partition"][partition]
        > coverage["available_by_partition"][partition]
        for partition in ("development", "validation")
    ):
        raise ResilienceBaselineError("coverage_report selects more samples than available")
    for index, sample in enumerate(data["paired_samples"]):
        sample_data = _mapping(sample, f"paired_samples[{index}]")
        if sample_data.get("generated_geometry_is_prediction") is not True:
            raise ResilienceBaselineError(
                f"paired_samples[{index}] must mark generated geometry as prediction"
            )
        if not isinstance(sample_data.get("generated_visible_card_revision_id"), str):
            raise ResilienceBaselineError(
                f"paired_samples[{index}] has no generated visible-card lineage"
            )
        if sample_data.get("generated_item_present") is not True:
            raise ResilienceBaselineError(
                f"paired_samples[{index}] has no generated visible-card item"
            )
        if sample_data.get("partition") not in {"development", "validation"}:
            raise ResilienceBaselineError(
                f"paired_samples[{index}] has no frozen partition"
            )
        if sample_data.get("reviewed_target_identity") not in CARD_IDENTITIES:
            raise ResilienceBaselineError(
                f"paired_samples[{index}] has no canonical reviewed identity"
            )


def write_resilience_baseline_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    """Write one canonical M0 manifest."""

    validate_resilience_baseline_manifest(manifest)
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return destination


def render_resilience_baseline_human(manifest: Mapping[str, Any]) -> str:
    """Render a concise operator report for the M0 command."""

    inventory = manifest["inventory"]
    partitions = manifest["partitions"]
    experiment = manifest["experiment_plan"]
    status = (
        "ready for validation classification"
        if manifest["validation_classification_allowed"]
        else "blocked by coverage"
    )
    lines = [
        "Visible-region identity resilience baseline M0",
        f"status: {status}",
        f"recordings: {inventory['recording_count']}",
        f"completed references: {inventory['completed_reference_count']}",
        f"paired samples: {inventory['paired_sample_count']}",
        "development groups: "
        f"{', '.join(partitions['development_source_lineage_groups']) or 'none'}",
        f"validation groups: {', '.join(partitions['validation_source_lineage_groups']) or 'none'}",
        f"validation samples: {inventory['validation_sample_count']}",
        "planned classifier requests: "
        f"{experiment['planned_classifier_request_count']} "
        f"(estimated ${experiment['estimated_cost_usd']:.4f})",
        "validation classification: "
        f"{'allowed' if manifest['validation_classification_allowed'] else 'not allowed'}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"


__all__ = [
    "CONDITION_IDS",
    "DEFAULT_CLASSIFIER_MODEL",
    "DEFAULT_CLASSIFIER_PROVIDER",
    "DEFAULT_PARTITION_RECORDING_IDS",
    "MEASUREMENT_CONTRACT_SCHEMA_VERSION",
    "METRICS",
    "MINIMUM_VALIDATION_SAMPLES",
    "RESILIENCE_BASELINE_SCHEMA_VERSION",
    "ResilienceBaselineError",
    "build_resilience_baseline_manifest",
    "canonical_json_bytes",
    "default_measurement_contract",
    "render_resilience_baseline_human",
    "sha256_json",
    "validate_resilience_baseline_manifest",
    "write_resilience_baseline_manifest",
]
