"""Freeze the epic 0070 synthetic visible-region experiment input.

M0 is a read-only audit of the completed 0068 training partition.  It freezes the
generator question, one bounded recipe, the paired comparison gate, and the
annotation-effort pilot before any scene is rendered or any model is trained.
The audit records missing reviewed inputs as a blocked immutable manifest.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from table_evidence_analyzer.visible_cards import (
    DEFAULT_MODEL,
    GEMINI_API_VERSION,
    GEMINI_PROVIDER_NAME,
    GEMINI_VISIBLE_CARD_THINKING_LEVEL,
    PROMPT,
    REQUEST_SCHEMA_VERSION,
    RESPONSE_SCHEMA,
)

from .reviewed_rfdetr_detector_campaign import (
    RFDETR_DETECTOR_CAMPAIGN_ID,
    ReviewedRfdetrDetectorCampaignError,
    canonical_json_bytes,
    validate_reviewed_rfdetr_detector_manifest,
)

SYNTHETIC_VISIBLE_REGION_MANIFEST_SCHEMA_VERSION = "synthetic-visible-region-manifest/v1"
SYNTHETIC_VISIBLE_REGION_CAMPAIGN_ID = "0070-m0-synthetic-visible-region-training-data"
SOURCE_MANIFEST_DEFAULT = "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
MATERIALIZATION_DEFAULT = ".runtime/rfdetr-segmentation-0068"
DETECTOR_BUNDLE_DEFAULT = ".runtime/rfdetr-visible-card-detector-0068-m2-training/bundle"
VALIDATION_REPORT_DEFAULT = ".runtime/rfdetr-visible-card-detector-0068-m3-validation/report.json"
SYNTHETIC_SEED = 7001
MAX_GENERATED_SCENES = 2_000
CARD_SIDES = frozenset({"face_up", "face_down", "unknown"})
_SHA256_LENGTH = 64


class SyntheticVisibleRegionCampaignError(ValueError):
    """Raised when the epic 0070 M0 contract or audit is invalid."""


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionCampaignError(
            f"could not read {field} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionCampaignError(f"{field} must be a JSON object")
    return dict(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SyntheticVisibleRegionCampaignError(f"could not hash {path}: {error}") from error
    return digest.hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise SyntheticVisibleRegionCampaignError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise SyntheticVisibleRegionCampaignError(f"{field} must be a SHA-256 digest") from error
    return value


def _resolve(repository: Path, value: str | Path | None, default: str) -> Path:
    path = Path(default if value is None else value).expanduser()
    return path if path.is_absolute() else repository / path


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _round(value: float) -> float:
    return round(float(value), 9)


def _polygon(target: Mapping[str, Any]) -> list[tuple[float, float]] | None:
    geometry = target.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    visible_region = geometry.get("visible_region")
    if not isinstance(visible_region, Mapping):
        return None
    polygons = visible_region.get("polygons")
    if not isinstance(polygons, list) or len(polygons) != 1:
        return None
    points = polygons[0]
    if not isinstance(points, list) or len(points) != 4:
        return None
    result: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, Mapping):
            return None
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, bool) or not isinstance(x, int) or not 0 < x < 1000:
            return None
        if isinstance(y, bool) or not isinstance(y, int) or not 0 < y < 1000:
            return None
        result.append((x / 1000, y / 1000))
    return result


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def _quadrilateral_metrics(points: Sequence[tuple[float, float]]) -> dict[str, float] | None:
    if len(points) != 4:
        return None
    crosses = [
        _cross(points[index], points[(index + 1) % 4], points[(index + 2) % 4])
        for index in range(4)
    ]
    if not all(value > 0 for value in crosses) and not all(value < 0 for value in crosses):
        return None
    area = (
        abs(
            sum(
                points[index][0] * points[(index + 1) % 4][1]
                - points[(index + 1) % 4][0] * points[index][1]
                for index in range(4)
            )
        )
        / 2
    )
    if area <= 0:
        return None
    edge_lengths = [
        math.hypot(
            points[(index + 1) % 4][0] - points[index][0],
            points[(index + 1) % 4][1] - points[index][1],
        )
        for index in range(4)
    ]
    rotation = math.degrees(math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0]))
    return {
        "area": _round(area),
        "centroid_x": _round(sum(point[0] for point in points) / 4),
        "centroid_y": _round(sum(point[1] for point in points) / 4),
        "edge_length_min": _round(min(edge_lengths)),
        "edge_length_max": _round(max(edge_lengths)),
        "edge_length_ratio": _round(max(edge_lengths) / min(edge_lengths)),
        "rotation_degrees": _round(rotation),
    }


def _geometry_envelope(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["table_setup"])].append(record)
    fields = (
        "area",
        "centroid_x",
        "centroid_y",
        "edge_length_min",
        "edge_length_max",
        "edge_length_ratio",
        "rotation_degrees",
    )
    result: dict[str, Any] = {}
    for setup in sorted(grouped):
        values = grouped[setup]
        result[setup] = {
            "sample_count": len(values),
            **{
                field: {
                    "min": _round(min(float(item["geometry"][field]) for item in values)),
                    "max": _round(max(float(item["geometry"][field]) for item in values)),
                }
                for field in fields
            },
        }
    return result


def _proposal_baseline() -> dict[str, Any]:
    contract = {
        "provider": GEMINI_PROVIDER_NAME,
        "api_version": GEMINI_API_VERSION,
        "model": DEFAULT_MODEL,
        "request_version": REQUEST_SCHEMA_VERSION,
        "thinking_level": GEMINI_VISIBLE_CARD_THINKING_LEVEL,
        "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
        "response_schema_sha256": hashlib.sha256(canonical_json_bytes(RESPONSE_SCHEMA)).hexdigest(),
    }
    return {
        **contract,
        "contract_sha256": hashlib.sha256(canonical_json_bytes(contract)).hexdigest(),
    }


def _recipe(source_recipe: Mapping[str, Any], real_training_frame_count: int) -> dict[str, Any]:
    control_recipe = json.loads(canonical_json_bytes(source_recipe).decode("utf-8"))
    training = control_recipe.setdefault("training", {})
    training["seed"] = SYNTHETIC_SEED
    training["output_dir_name"] = "rfdetr-synthetic-visible-region-0070-control"
    control_recipe["budget"] = {
        "candidate_count": 2,
        "sweep": False,
        "wall_clock_seconds_per_candidate": 7_200,
        "total_wall_clock_seconds": 14_400,
    }
    control_recipe.setdefault("data_contract", {})["synthetic_data"] = "training_only"
    return {
        "schema_version": "synthetic-visible-region-recipe/v1",
        "seed": SYNTHETIC_SEED,
        "max_scene_count": min(2 * real_training_frame_count, MAX_GENERATED_SCENES),
        "real_to_synthetic_sampling_ratio": 1.0,
        "source_partition": "train",
        "source_group_policy": "0068-training-source-groups-only/v1",
        "target_class": "visible_card",
        "geometry": {
            "placement": "measured-table-setup-quadrilateral/v1",
            "position_jitter_normalized": 0.015,
            "scale_range": [0.9, 1.1],
            "rotation_jitter_degrees": 4.0,
            "corner_jitter_normalized": 0.005,
            "out_of_envelope": "reject",
        },
        "occlusion": {
            "strategy": "card_card_exact_z_order/v1",
            "human_occluders": "disabled_until_reviewed_alpha_masks",
            "visible_depth_buckets": {
                "shallow": [0.10, 0.30],
                "medium": [0.30, 0.55],
                "heavy": [0.55, 0.80],
            },
        },
        "scene_buckets": [
            "fully_visible_card",
            "separated_cards",
            "overlapping_cards_shallow",
            "overlapping_cards_medium",
            "overlapping_cards_heavy",
            "frame_boundary_clipping",
            "face_down_cards",
            "mixed_card_sides",
            "blur_glare_dark_compressed",
            "reviewed_empty_background",
        ],
        "photometric": {
            "measurement": "training-only-real-frame-envelope/v1",
            "brightness_delta": [-0.12, 0.12],
            "contrast": [0.85, 1.15],
            "saturation": [0.85, 1.15],
            "blur_sigma": [0.0, 1.2],
            "glare_opacity": [0.0, 0.12],
            "jpeg_quality": [70, 95],
            "shadow_opacity": [0.08, 0.22],
        },
        "mask_policy": {
            "full_card_alpha_before_composite": True,
            "subtract_higher_z_order_opaque_masks": True,
            "subtract_reviewed_occluder_masks": True,
            "clip_to_frame": True,
            "preserve_disconnected_components": True,
            "derive_box": "tight-visible-mask-bounds/v1",
            "below_threshold": "omit_with_receipt",
        },
        "trainer": {
            "control": control_recipe,
            "synthetic_addition": {
                "same_as_control": True,
                "additional_input": "frozen-synthetic-scenes",
                "real_sample_order_unchanged": True,
                "synthetic_batches": "declared-scene-count-only",
            },
        },
    }


def _audit_materialization(
    repository: Path, source_manifest_path: Path, materialization_path: Path, source_digest: str
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    root = materialization_path if materialization_path.is_dir() else materialization_path.parent
    path = root / "materialization.json"
    gaps: list[str] = []
    if not path.is_file():
        return (
            {
                "path": _relative(path, repository),
                "file_sha256": None,
                "materialization_digest": None,
            },
            {},
            [f"0068 materialization manifest is missing: {_relative(path, repository)}"],
        )
    materialization = _read_json(path, "0068 materialization manifest")
    manifest_link = materialization.get("campaign_manifest")
    if not isinstance(manifest_link, Mapping):
        gaps.append("0068 materialization has no campaign manifest link")
    else:
        if manifest_link.get("manifest_digest") != source_digest:
            gaps.append("0068 materialization uses a different source manifest digest")
        if source_manifest_path.is_file() and manifest_link.get("file_sha256") != _sha256_file(
            source_manifest_path
        ):
            gaps.append("0068 materialization uses a different source manifest file digest")
    if materialization.get("schema_version") != "rfdetr-segmentation-materialization/v1":
        gaps.append("0068 materialization schema is unsupported")
    generated_files = materialization.get("generated_files")
    if not isinstance(generated_files, list):
        gaps.append("0068 materialization generated_files is not a list")
    train_files = [
        item
        for item in generated_files or []
        if isinstance(item, Mapping)
        and item.get("kind") == "extracted_frame"
        and str(item.get("path", "")).startswith("train/")
    ]
    train_event_digests = {
        str(item.get("event_id")): item.get("sha256")
        for item in train_files
        if isinstance(item.get("event_id"), str)
    }
    summary = {
        "path": _relative(path, repository),
        "file_sha256": _sha256_file(path),
        "materialization_digest": materialization.get("materialization_digest"),
        "split_digest": materialization.get("split", {}).get("digest")
        if isinstance(materialization.get("split"), Mapping)
        else None,
        "train_image_count": materialization.get("counts", {}).get("train_images")
        if isinstance(materialization.get("counts"), Mapping)
        else None,
        "train_annotation_count": materialization.get("counts", {}).get("train_annotations")
        if isinstance(materialization.get("counts"), Mapping)
        else None,
    }
    return (
        summary,
        {"train_event_digests": train_event_digests, "materialization": materialization},
        gaps,
    )


def _audit_bundle(
    repository: Path, bundle_path: Path, source_digest: str, materialization_digest: str | None
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    manifest_path = bundle_path / "manifest.json"
    gaps: list[str] = []
    if not manifest_path.is_file():
        return (
            {
                "path": _relative(bundle_path, repository),
                "manifest_sha256": None,
                "bundle_digest": None,
                "checkpoint_sha256": None,
            },
            {},
            [f"0068 detector bundle is missing: {_relative(bundle_path, repository)}"],
        )
    manifest = _read_json(manifest_path, "0068 detector bundle manifest")
    campaign_manifest = manifest.get("campaign_manifest")
    if not isinstance(campaign_manifest, Mapping):
        gaps.append("0068 detector bundle has no campaign manifest link")
    else:
        if campaign_manifest.get("manifest_digest") != source_digest:
            gaps.append("0068 detector bundle uses a different source manifest digest")
    if (
        materialization_digest is not None
        and manifest.get("materialization_digest") != materialization_digest
    ):
        gaps.append("0068 detector bundle uses a different materialization digest")
    files = manifest.get("files")
    checkpoint_file = manifest.get("checkpoint_file")
    if not isinstance(files, Mapping) or not isinstance(checkpoint_file, str):
        gaps.append("0068 detector bundle does not declare its checkpoint")
    else:
        checkpoint_path = bundle_path / checkpoint_file
        if not checkpoint_path.is_file():
            gaps.append(
                f"0068 detector checkpoint is missing: {_relative(checkpoint_path, repository)}"
            )
        elif files.get(checkpoint_file) != _sha256_file(checkpoint_path):
            gaps.append("0068 detector checkpoint digest differs from its bundle manifest")
    summary = {
        "path": _relative(bundle_path, repository),
        "manifest_sha256": _sha256_file(manifest_path),
        "bundle_digest": manifest.get("bundle_digest"),
        "checkpoint_sha256": manifest.get("checkpoint_sha256"),
        "checkpoint_file": checkpoint_file,
        "provider": "local-rfdetr-segmentation",
    }
    return summary, {"manifest": manifest}, gaps


def _audit_validation_report(
    repository: Path,
    report_path: Path,
    source_digest: str,
    materialization_digest: str | None,
    bundle_digest: str | None,
) -> tuple[dict[str, Any], list[str]]:
    gaps: list[str] = []
    if not report_path.is_file():
        return {
            "path": _relative(report_path, repository),
            "file_sha256": None,
            "schema_version": None,
            "status": None,
        }, [f"0068 validation report is missing: {_relative(report_path, repository)}"]
    report = _read_json(report_path, "0068 validation report")
    campaign_manifest = report.get("campaign_manifest")
    if (
        not isinstance(campaign_manifest, Mapping)
        or campaign_manifest.get("manifest_digest") != source_digest
    ):
        gaps.append("0068 validation report uses a different source manifest digest")
    if report.get("materialization_digest") != materialization_digest:
        gaps.append("0068 validation report uses a different materialization digest")
    candidate = report.get("candidate_bundle")
    if not isinstance(candidate, Mapping) or candidate.get("bundle_digest") != bundle_digest:
        gaps.append("0068 validation report uses a different detector bundle digest")
    if report.get("status") != "completed":
        gaps.append("0068 validation report is not completed")
    return {
        "path": _relative(report_path, repository),
        "file_sha256": _sha256_file(report_path),
        "schema_version": report.get("schema_version"),
        "status": report.get("status"),
        "bundle_digest": bundle_digest,
    }, gaps


def _eligible_card_cutouts(
    manifest: Mapping[str, Any],
    train_event_digests: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    recordings = {
        str(item["recording_id"]): item
        for item in manifest.get("recordings", [])
        if isinstance(item, Mapping) and isinstance(item.get("recording_id"), str)
    }
    candidates: list[dict[str, Any]] = []
    for sample in manifest.get("samples", []):
        if not isinstance(sample, Mapping) or sample.get("split") != "train":
            continue
        targets = sample.get("targets")
        if not isinstance(targets, list) or len(targets) != 1:
            continue
        target = targets[0]
        if not isinstance(target, Mapping):
            continue
        points = _polygon(target)
        metrics = _quadrilateral_metrics(points) if points is not None else None
        if points is None or metrics is None:
            continue
        recording = recordings.get(str(sample.get("recording_id")), {})
        candidates.append(
            {
                "event_id": sample.get("event_id"),
                "item_id": sample.get("item_id"),
                "card_id": target.get("card_id"),
                "recording_id": sample.get("recording_id"),
                "reference_revision_id": sample.get("reference_revision_id"),
                "source_group_key": sample.get("source_group_key"),
                "source_sha256": sample.get("source_sha256"),
                "source_permission": recording.get("source_permission"),
                "source_split": sample.get("split"),
                "table_setup": sample.get("table_setup"),
                "side": target.get("side", "unknown"),
                "frame_identity": {
                    "image_sha256": sample.get("frame_identity", {}).get("image_sha256"),
                    "width": sample.get("frame_identity", {}).get("width"),
                    "height": sample.get("frame_identity", {}).get("height"),
                },
                "materialized_frame_sha256": train_event_digests.get(sample.get("event_id")),
                "quadrilateral": [{"x": _round(x), "y": _round(y)} for x, y in (points or [])],
                "geometry": metrics,
            }
        )
    candidates.sort(key=lambda item: (str(item["recording_id"]), str(item["event_id"])))
    side_counts = Counter(str(item["side"]) for item in candidates)
    setup_counts = Counter(str(item["table_setup"]) for item in candidates)
    return candidates, {
        "eligible_card_cutout_count": len(candidates),
        "side_counts": {side: side_counts.get(side, 0) for side in sorted(CARD_SIDES)},
        "table_setup_counts": dict(sorted(setup_counts.items())),
    }


def build_synthetic_visible_region_manifest(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path | None = None,
    materialization_path: str | Path | None = None,
    detector_bundle_path: str | Path | None = None,
    validation_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the deterministic, read-only epic 0070 M0 manifest."""

    repository = Path(repository_root).expanduser().resolve()
    source_path = _resolve(repository, source_manifest_path, SOURCE_MANIFEST_DEFAULT)
    materialization_input = _resolve(repository, materialization_path, MATERIALIZATION_DEFAULT)
    bundle_path = _resolve(repository, detector_bundle_path, DETECTOR_BUNDLE_DEFAULT)
    report_path = _resolve(repository, validation_report_path, VALIDATION_REPORT_DEFAULT)
    gaps: list[str] = []

    source_manifest: dict[str, Any] = {}
    if not source_path.is_file():
        gaps.append(f"0068 source manifest is missing: {_relative(source_path, repository)}")
    else:
        source_manifest = _read_json(source_path, "0068 source manifest")
        try:
            validate_reviewed_rfdetr_detector_manifest(source_manifest)
        except (ReviewedRfdetrDetectorCampaignError, TypeError, ValueError) as error:
            gaps.append(f"0068 source manifest is invalid: {error}")
        if source_manifest.get("freeze_state") != "frozen":
            gaps.append("0068 source manifest is not frozen")
        if source_manifest.get("campaign_id") != RFDETR_DETECTOR_CAMPAIGN_ID:
            gaps.append("0068 source manifest is not the reviewed local detector campaign")

    source_digest = source_manifest.get("manifest_digest")
    if not isinstance(source_digest, str):
        source_digest = None
        gaps.append("0068 source manifest has no manifest digest")
    source_file_digest = _sha256_file(source_path) if source_path.is_file() else None
    materialization, materialization_details, materialization_gaps = _audit_materialization(
        repository,
        source_path,
        materialization_input,
        source_digest,
    )
    gaps.extend(materialization_gaps)
    bundle, bundle_details, bundle_gaps = _audit_bundle(
        repository,
        bundle_path,
        source_digest,
        materialization.get("materialization_digest"),
    )
    gaps.extend(bundle_gaps)
    validation_report, validation_gaps = _audit_validation_report(
        repository,
        report_path,
        source_digest,
        materialization.get("materialization_digest"),
        bundle.get("bundle_digest"),
    )
    gaps.extend(validation_gaps)

    train_event_digests = materialization_details.get("train_event_digests", {})
    card_cutouts, cutout_inventory = _eligible_card_cutouts(source_manifest, train_event_digests)
    for item in card_cutouts:
        if item["materialized_frame_sha256"] != item["frame_identity"]["image_sha256"]:
            gaps.append(f"materialized frame digest differs for {item['event_id']}")
    if not card_cutouts:
        gaps.append("no eligible training-only reviewed card cutouts were found")
    if not cutout_inventory["side_counts"].get("face_down"):
        gaps.append("no eligible training-only face_down card cutout was found")

    backgrounds: list[dict[str, Any]] = []
    occluders: list[dict[str, Any]] = []
    if not backgrounds:
        gaps.append("no explicitly reviewed empty table background is available")

    training_samples = [
        item
        for item in source_manifest.get("samples", [])
        if isinstance(item, Mapping) and item.get("split") == "train"
    ]
    training_recording_ids = sorted({str(item.get("recording_id")) for item in training_samples})
    training_frame_count = len(training_samples)
    geometry_envelope = _geometry_envelope(card_cutouts)
    recipe = _recipe(source_manifest.get("recipe", {}), training_frame_count)
    proposal_baseline = _proposal_baseline()
    baseline = {
        "proposal_baseline": proposal_baseline,
        "local_rfdetr_0068": {
            "provider": "local-rfdetr-segmentation",
            "bundle_digest": bundle.get("bundle_digest"),
            "checkpoint_sha256": bundle.get("checkpoint_sha256"),
            "source_manifest_digest": source_digest,
            "materialization_digest": materialization.get("materialization_digest"),
        },
    }
    comparison = {
        "candidate_count": 2,
        "control": "0068-real-training-partition-only",
        "synthetic_addition": "same-real-samples-plus-frozen-synthetic-scenes",
        "equal_fields": [
            "pretrained_checkpoint",
            "rf_detr_package",
            "model_class",
            "class_map",
            "resolution",
            "augmentation",
            "optimizer",
            "seed",
            "confidence_threshold",
            "checkpoint_selection",
            "real_sample_order",
            "validation_partition",
            "sealed_test_partition",
        ],
        "validation_gate": {
            "mask_ap_50_95_delta_min": -0.01,
            "recall_delta_min": -0.01,
            "synthetic_candidate_must_pass_validation": True,
            "sealed_test_runs": "only_after_validation_gate",
        },
        "synthetic_metrics_are_diagnostic_only": True,
    }
    annotation_pilot = {
        "frame_count": 20,
        "source_group_policy": "new-development-groups-not-used-by-training-or-evaluation/v1",
        "proposal_order": "randomized_and_processor_blinded_when_practical",
        "timing": "active_correction_only_excluding_model_execution_and_operator_idle",
        "recorded_measures": [
            "active_correction_time",
            "accepted_proposals",
            "reshapes",
            "additions",
            "removals",
            "missed_cards",
            "extra_cards",
            "visible_card_ignore_region_sends",
        ],
        "success_threshold": {
            "median_active_correction_time_reduction": 0.15,
            "maximum_missed_card_delta": 0,
            "same_exact_frames": True,
        },
    }
    stop_rules = {
        "required_inputs": [
            "frozen_0068_training_manifest",
            "digest_verified_0068_training_materialization",
            "digest_verified_0068_local_detector_bundle",
            "digest_verified_0068_validation_report",
            "at_least_one_reviewed_empty_background",
            "at_least_one_face_down_card_cutout",
        ],
        "stop_before_render_or_training_when": [
            "any_validation_or_sealed_test_contributor_is_selected",
            "any_source_digest_or_permission_is_missing_or_changed",
            "any_required_input_is_missing",
            "scene_count_exceeds_frozen_limit",
            "geometry_is_outside_table_setup_envelope",
            "a_source_digest_changes_after_freeze",
        ],
        "no_sweeps": True,
        "no_runtime_default_change": True,
        "no_provider_promotion": True,
    }
    inventory = {
        "source_training_group_count": len(training_recording_ids),
        "source_training_recording_ids": training_recording_ids,
        "real_training_frame_count": training_frame_count,
        "real_training_target_count": sum(
            len(item.get("targets", [])) for item in training_samples if isinstance(item, Mapping)
        ),
        **cutout_inventory,
        "eligible_background_count": len(backgrounds),
        "eligible_occluder_count": len(occluders),
        "geometry_example_count": len(card_cutouts),
        "max_generated_scene_count": recipe["max_scene_count"],
        "validation_source_groups_excluded": sorted(
            str(group.get("recording_id"))
            for group in source_manifest.get("source_groups", [])
            if isinstance(group, Mapping) and group.get("partition") == "validation"
        ),
        "sealed_test_source_groups_excluded": sorted(
            str(group.get("recording_id"))
            for group in source_manifest.get("source_groups", [])
            if isinstance(group, Mapping) and group.get("partition") == "sealed_test"
        ),
    }
    core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_MANIFEST_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_CAMPAIGN_ID,
        "milestone": "M0",
        "read_only": True,
        "freeze_state": "frozen" if not gaps else "blocked",
        "question": (
            "Does one fixed mixture of real reviewed training frames and perspective-grounded "
            "synthetic frames reduce correction effort on new real frames without reducing "
            "held-out quality?"
        ),
        "boundaries": {
            "source_campaign_id": RFDETR_DETECTOR_CAMPAIGN_ID,
            "source_partition": "train",
            "synthetic_partition": "training_only",
            "validation_and_sealed_test_unchanged": True,
            "identity_claims": False,
            "runtime_preprocessing": False,
            "diffusion_or_generative_image_models": False,
        },
        "inputs": {
            "source_manifest": {
                "path": _relative(source_path, repository),
                "file_sha256": source_file_digest,
                "manifest_digest": source_digest,
                "recipe_sha256": source_manifest.get("recipe_sha256"),
            },
            "materialization": materialization,
            "detector_bundle": bundle,
            "validation_report": validation_report,
        },
        "baseline": baseline,
        "eligibility": {
            "training_recording_ids": training_recording_ids,
            "card_cutouts": card_cutouts,
            "backgrounds": backgrounds,
            "occluders": occluders,
            "geometry_envelope_by_table_setup": geometry_envelope,
            "human_occluder_policy": "card_card_only_until_reviewed_alpha_masks_exist",
        },
        "recipe": recipe,
        "comparison": comparison,
        "annotation_pilot": annotation_pilot,
        "stop_rules": stop_rules,
        "inventory": inventory,
        "coverage_gaps": sorted(set(gaps)),
    }
    return json.loads(
        canonical_json_bytes(
            {**core, "manifest_digest": hashlib.sha256(canonical_json_bytes(core)).hexdigest()}
        ).decode("utf-8")
    )


def validate_synthetic_visible_region_manifest(raw: Mapping[str, Any]) -> None:
    """Validate the strict immutable epic 0070 M0 manifest contract."""

    expected = {
        "schema_version",
        "campaign_id",
        "milestone",
        "read_only",
        "freeze_state",
        "question",
        "boundaries",
        "inputs",
        "baseline",
        "eligibility",
        "recipe",
        "comparison",
        "annotation_pilot",
        "stop_rules",
        "inventory",
        "coverage_gaps",
        "manifest_digest",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise SyntheticVisibleRegionCampaignError(
            "synthetic visible-region manifest has invalid fields"
        )
    if raw["schema_version"] != SYNTHETIC_VISIBLE_REGION_MANIFEST_SCHEMA_VERSION:
        raise SyntheticVisibleRegionCampaignError(
            "synthetic visible-region manifest schema is unsupported"
        )
    if raw["campaign_id"] != SYNTHETIC_VISIBLE_REGION_CAMPAIGN_ID or raw["milestone"] != "M0":
        raise SyntheticVisibleRegionCampaignError(
            "synthetic visible-region manifest identity is invalid"
        )
    if raw["read_only"] is not True or raw["freeze_state"] not in {"frozen", "blocked"}:
        raise SyntheticVisibleRegionCampaignError(
            "synthetic visible-region manifest state is invalid"
        )
    if not isinstance(raw["coverage_gaps"], list) or any(
        not isinstance(item, str) for item in raw["coverage_gaps"]
    ):
        raise SyntheticVisibleRegionCampaignError("coverage_gaps must be a list of strings")
    recipe = raw["recipe"]
    if not isinstance(recipe, Mapping):
        raise SyntheticVisibleRegionCampaignError("recipe must be an object")
    inventory = raw["inventory"]
    if not isinstance(inventory, Mapping):
        raise SyntheticVisibleRegionCampaignError("inventory must be an object")
    real_count = inventory.get("real_training_frame_count")
    max_count = recipe.get("max_scene_count")
    if isinstance(real_count, bool) or not isinstance(real_count, int) or real_count < 0:
        raise SyntheticVisibleRegionCampaignError("inventory real_training_frame_count is invalid")
    if max_count != min(2 * real_count, MAX_GENERATED_SCENES):
        raise SyntheticVisibleRegionCampaignError(
            "recipe max_scene_count is not frozen from the real count"
        )
    if inventory.get("eligible_card_cutout_count") != len(
        raw["eligibility"].get("card_cutouts", [])
    ):
        raise SyntheticVisibleRegionCampaignError("card cutout inventory is stale")
    if inventory.get("eligible_background_count") != len(raw["eligibility"].get("backgrounds", [])):
        raise SyntheticVisibleRegionCampaignError("background inventory is stale")
    if inventory.get("eligible_occluder_count") != len(raw["eligibility"].get("occluders", [])):
        raise SyntheticVisibleRegionCampaignError("occluder inventory is stale")
    for item in raw["eligibility"].get("card_cutouts", []):
        if not isinstance(item, Mapping) or item.get("source_split") != "train":
            raise SyntheticVisibleRegionCampaignError("card cutout is not training-only")
        if item.get("side") not in CARD_SIDES:
            raise SyntheticVisibleRegionCampaignError("card cutout has an invalid side")
        if raw["freeze_state"] == "frozen" or item.get("materialized_frame_sha256") is not None:
            _digest(item.get("materialized_frame_sha256"), "card cutout materialized frame digest")
    baseline = raw["baseline"]
    if not isinstance(baseline, Mapping):
        raise SyntheticVisibleRegionCampaignError("baseline must be an object")
    proposal = baseline.get("proposal_baseline")
    local = baseline.get("local_rfdetr_0068")
    if not isinstance(proposal, Mapping) or not isinstance(local, Mapping):
        raise SyntheticVisibleRegionCampaignError(
            "baseline must identify proposal and local detector"
        )
    _digest(proposal.get("contract_sha256"), "proposal baseline contract digest")
    for field, label in (
        ("bundle_digest", "0068 detector bundle digest"),
        ("source_manifest_digest", "0068 source manifest digest"),
        ("materialization_digest", "0068 materialization digest"),
    ):
        if raw["freeze_state"] == "frozen" or local.get(field) is not None:
            _digest(local.get(field), label)
    core = {key: raw[key] for key in expected if key != "manifest_digest"}
    if raw["manifest_digest"] != hashlib.sha256(canonical_json_bytes(core)).hexdigest():
        raise SyntheticVisibleRegionCampaignError(
            "manifest_digest does not match manifest contents"
        )


def write_synthetic_visible_region_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    """Write one immutable M0 manifest and refuse a different replacement."""

    validate_synthetic_visible_region_manifest(manifest)
    destination = Path(path).expanduser().resolve()
    payload = canonical_json_bytes(manifest) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != payload:
        raise SyntheticVisibleRegionCampaignError(
            "immutable synthetic visible-region M0 manifest already exists and differs: "
            f"{destination}"
        )
    if not destination.exists():
        destination.write_bytes(payload)
    return destination


def render_synthetic_visible_region_human(manifest: Mapping[str, Any]) -> str:
    """Render a concise operator report for the M0 audit."""

    inventory = manifest["inventory"]
    lines = [
        "Synthetic visible-region training data M0",
        f"status: {manifest['freeze_state']}",
        f"training source groups: {inventory['source_training_group_count']}",
        f"real training frames: {inventory['real_training_frame_count']}",
        f"eligible card cutouts: {inventory['eligible_card_cutout_count']}",
        f"eligible backgrounds: {inventory['eligible_background_count']}",
        f"eligible human occluders: {inventory['eligible_occluder_count']}",
        f"eligible geometry examples: {inventory['geometry_example_count']}",
        f"maximum synthetic scenes: {inventory['max_generated_scene_count']}",
        f"manifest digest: {manifest['manifest_digest']}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"


__all__ = [
    "DETECTOR_BUNDLE_DEFAULT",
    "MATERIALIZATION_DEFAULT",
    "SOURCE_MANIFEST_DEFAULT",
    "SYNTHETIC_VISIBLE_REGION_CAMPAIGN_ID",
    "SYNTHETIC_VISIBLE_REGION_MANIFEST_SCHEMA_VERSION",
    "SyntheticVisibleRegionCampaignError",
    "VALIDATION_REPORT_DEFAULT",
    "build_synthetic_visible_region_manifest",
    "render_synthetic_visible_region_human",
    "validate_synthetic_visible_region_manifest",
    "write_synthetic_visible_region_manifest",
]
