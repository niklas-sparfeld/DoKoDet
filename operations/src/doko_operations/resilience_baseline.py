"""Freeze the epic 0051 resilience measurement contract and inspect coverage.

M0 is deliberately read-only.  It scans accepted recording bundles, immutable pipeline
revisions, and completed maintained references.  It does not create a review, classify a crop,
or change a source artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .holdout import load_system_holdout_registry, sealed_group_keys

RESILIENCE_BASELINE_SCHEMA_VERSION = "visible-region-identity-resilience-manifest/v1"
MEASUREMENT_CONTRACT_SCHEMA_VERSION = "visible-region-identity-measurement/v1"
MINIMUM_VALIDATION_SAMPLES = 24

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
    classifier_provider: str = "gemini",
    classifier_model: str = "gemini-3.6-flash",
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
            "implementation": "configured-visual-identity-classifier/v1",
            "score_calibration": "uncalibrated_single_candidate_is_not_probability",
        },
        "budget": {
            "max_classifier_requests": 5000,
            "max_estimated_cost_usd": 25.0,
            "max_wall_clock_seconds": 7200,
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
    intake_root: Path, repository_root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    recordings: list[dict[str, Any]] = []
    gaps: list[str] = []
    if not intake_root.is_dir():
        return recordings, [
            f"recording intake root is missing: {_relative(intake_root, repository_root)}"
        ]
    for directory in sorted(intake_root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.is_symlink() or directory.name.startswith("."):
            continue
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = _read_json(manifest_path, "recording bundle manifest")
        except ResilienceBaselineError as error:
            gaps.append(str(error))
            continue
        if (
            manifest.get("schema_version") != "repository-bundle/v1"
            or manifest.get("state") != "complete"
        ):
            continue
        recording_id = manifest.get("recording_id")
        session_id = manifest.get("session_id")
        source_asset_id = manifest.get("source_asset_id")
        source_sha256 = manifest.get("source_sha256")
        if not all(
            isinstance(value, str) and value
            for value in (recording_id, session_id, source_asset_id, source_sha256)
        ):
            gaps.append(
                "recording bundle has incomplete lineage: "
                f"{_relative(manifest_path, repository_root)}"
            )
            continue
        if recording_id != directory.name:
            gaps.append(f"recording bundle directory does not match recording_id: {directory}")
            continue
        recordings.append(
            {
                "recording_id": recording_id,
                "session_id": session_id,
                "source_lineage_group": session_id,
                "source_asset_id": source_asset_id,
                "source_video_sha256": source_sha256,
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
    source_revision_id = visible_revision["manifest"].get("producer", {}).get("base_revision_id")
    if visible_reference["draft"].get("source_revision_id") != source_revision_id:
        gaps.append(
            f"visible maintained reference does not preserve generated source lineage: "
            f"{visible_reference['selected_revision_id']}"
        )
    generated_revision = (
        revisions.get(source_revision_id) if isinstance(source_revision_id, str) else None
    )
    generated_content = generated_revision["content"] if generated_revision is not None else None
    generated_outcomes = {
        item.get("event_id"): item
        for item in (generated_content or {}).get("outcomes", [])
        if isinstance(item, Mapping) and isinstance(item.get("event_id"), str)
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
        generated_item = (
            generated_outcomes.get(generated_item_id)
            if isinstance(generated_item_id, str)
            else None
        )
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
                    "generated_item_present": generated_item is not None,
                    "frame_identity_digest": sha256_json(item["frame_identity"]),
                    "reviewed_visible_geometry_digest": sha256_json(candidate["geometry"]),
                    "reviewed_identity_geometry_digest": sha256_json(identity_item.get("geometry")),
                    "reviewed_target_identity": identity_item["candidates"][0].get("identity"),
                }
            )
    if not isinstance(source_revision_id, str) or generated_revision is None:
        gaps.append(
            "visible reference "
            f"{visible_reference['selected_revision_id']} has no recorded generated "
            "proposal lineage"
        )
    elif generated_revision["manifest"].get("origin") not in {"processor", "import"}:
        gaps.append(
            f"generated visible revision is not processor/import output: {source_revision_id}"
        )
    elif generated_revision["manifest"].get("content_type") != "visible_cards":
        gaps.append(f"generated proposal revision is not visible-card data: {source_revision_id}")
    for sample in samples:
        if not sample["generated_item_present"]:
            gaps.append(
                f"generated proposal item is missing: {sample['generated_visible_card_item_id']}"
            )
    return samples, gaps


def build_resilience_baseline_manifest(
    repository_root: str | Path,
    *,
    runtime_root: str | Path | None = None,
    operations_root: str | Path | None = None,
    intake_root: str | Path | None = None,
    holdout_registry_path: str | Path | None = None,
    classifier_provider: str = "gemini",
    classifier_model: str = "gemini-3.6-flash",
) -> dict[str, Any]:
    """Build the deterministic M0 manifest and coverage report."""

    repository = Path(repository_root).expanduser().resolve()
    runtime = _resolve(repository, runtime_root, repository / ".runtime")
    operations = _resolve(repository, operations_root, repository / "data" / "operations")
    intake = _resolve(repository, intake_root, repository / "data" / "intake" / "recordings")
    holdout_path = _resolve(
        repository, holdout_registry_path, operations / "system-holdout-registry.json"
    )
    contract = default_measurement_contract(
        classifier_provider=classifier_provider,
        classifier_model=classifier_model,
    )
    recordings, recording_gaps = _recording_inventory(intake, repository)
    revisions, revision_gaps = _revision_inventory(runtime)
    references, reference_gaps = _reference_inventory(operations)
    try:
        holdout_registry = load_system_holdout_registry(holdout_path)
        held_out = sealed_group_keys(holdout_registry)
    except (OSError, ValueError) as error:
        raise ResilienceBaselineError(f"could not load system holdout registry: {error}") from error
    by_recording = {recording["recording_id"]: recording for recording in recordings}
    references_by_key = {
        (reference["recording_id"], reference["content_type"]): reference
        for reference in references
    }
    samples: list[dict[str, Any]] = []
    gaps = [*recording_gaps, *revision_gaps, *reference_gaps]
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
    referenced_recording_ids = {reference["recording_id"] for reference in references}
    for recording_id in sorted(referenced_recording_ids - set(by_recording)):
        gaps.append(f"maintained references point to an unknown recording bundle: {recording_id}")
    groups = sorted({sample["source_lineage_group"] for sample in samples})
    validation_group = groups[-1] if len(groups) >= 2 else None
    development_groups = groups[:-1] if validation_group is not None else []
    validation_samples = [
        sample for sample in samples if sample["source_lineage_group"] == validation_group
    ]
    blocking_gaps: list[str] = []
    if len(groups) < 2:
        blocking_gaps.append(
            "need paired completed maintained visible-card and visual identity references "
            "from at least two "
            f"source-lineage groups; found {len(groups)}"
        )
    if len(validation_samples) < MINIMUM_VALIDATION_SAMPLES:
        blocking_gaps.append(
            f"validation coverage needs {MINIMUM_VALIDATION_SAMPLES} paired samples; "
            f"found {len(validation_samples)}"
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
                    sample["source_lineage_group"] == group for sample in samples
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
            "development_source_lineage_groups": development_groups,
            "validation_source_lineage_groups": []
            if validation_group is None
            else [validation_group],
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
        "paired_samples": samples,
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
    if data["measurement_contract_sha256"] != sha256_json(contract):
        raise ResilienceBaselineError("measurement_contract_sha256 does not match its content")
    for field in ("source_groups", "paired_samples", "coverage_gaps", "required_review_actions"):
        if not isinstance(data[field], list):
            raise ResilienceBaselineError(f"{field} must be a list")
    partitions = _mapping(data["partitions"], "partitions")
    for field in (
        "development_source_lineage_groups",
        "validation_source_lineage_groups",
        "system_holdout_excluded_groups",
    ):
        if not isinstance(partitions.get(field), list):
            raise ResilienceBaselineError(f"partitions.{field} must be a list")
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
        "validation classification: "
        f"{'allowed' if manifest['validation_classification_allowed'] else 'not allowed'}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"


__all__ = [
    "CONDITION_IDS",
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
