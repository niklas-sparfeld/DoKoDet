"""Freeze the epic 0067 RF-DETR visible-region training input.

M0 is a read-only audit.  It reads accepted recording bundles and maintained
visible-card references, validates their lineage and geometry, and writes one
deterministic manifest for the later COCO materialization and training steps.
It never changes source data and it never starts a model run.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .holdout import load_system_holdout_registry, sealed_group_keys

RFDETR_SEGMENTATION_MANIFEST_SCHEMA_VERSION = "rfdetr-segmentation-campaign-manifest/v1"
RFDETR_PACKAGE_VERSION = "1.9.4"
RFDETR_MODEL_CLASS = "RFDETRSegMedium"
RFDETR_MODEL_VARIANT = "rfdetr-seg-medium"
RFDETR_RESOLUTION = [432, 432]
CAMPAIGN_ID = "0067-m0-rfdetr-segmentation"

TRAIN_RECORDING_IDS = (
    "cardeventnet-IMG_0096",
    "cardeventnet-IMG_0097",
    "cardeventnet-IMG_0637",
    "cardeventnet-IMG_0643",
    "cardeventnet-IMG_0655",
    "cardeventnet-IMG_0669",
)
VALIDATION_RECORDING_IDS = (
    "cardeventnet-IMG_0090",
    "cardeventnet-IMG_0091",
    "cardeventnet-IMG_0661",
)
RECORDING_SPLITS = {
    **{recording_id: "train" for recording_id in TRAIN_RECORDING_IDS},
    **{recording_id: "validation" for recording_id in VALIDATION_RECORDING_IDS},
}
EXPECTED_COUNTS = {
    "train": {"reviewed_frames": 304, "retained_frames": 219, "targets": 703},
    "validation": {"reviewed_frames": 121, "retained_frames": 85, "targets": 213},
}
EXPECTED_TOTALS = {"reviewed_frames": 425, "retained_frames": 304, "targets": 916}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SOURCE_PERMISSIONS = {
    "training_only",
    "training_and_evaluation",
    "project_use",
    "unrestricted",
}
_ALLOWED_USES = {"train", "validation", "test", "evaluation"}
_REQUIRED_TRAIN_ARGUMENTS = (
    "resolution",
    "epochs",
    "batch_size",
    "grad_accum_steps",
    "device",
    "output_dir",
)


class RfdetrSegmentationCampaignError(ValueError):
    """Raised when the RF-DETR M0 audit or manifest is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable JSON bytes for all campaign and lineage digests."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RfdetrSegmentationCampaignError("campaign values must be finite JSON") from error


def sha256_json(value: Any) -> str:
    """Return the SHA-256 digest of one canonical JSON value."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RfdetrSegmentationCampaignError(f"{field} must be an object")
    return value


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RfdetrSegmentationCampaignError(f"could not read {field} {path}: {error}") from error
    return dict(_mapping(value, field))


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or _IDENTIFIER.fullmatch(value) is None:
        raise RfdetrSegmentationCampaignError(f"{field} must be a safe identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RfdetrSegmentationCampaignError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _resolve(root: Path, value: str | Path | None, default: Path) -> Path:
    path = default if value is None else Path(value).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise RfdetrSegmentationCampaignError(
            f"{path} is outside repository root {root}"
        ) from error


def _safe_relative_path(path_value: Any, root: Path, field: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise RfdetrSegmentationCampaignError(f"{field} must be a relative path")
    path = (root / path_value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise RfdetrSegmentationCampaignError(f"{field} escapes its recording bundle") from error
    return path


def default_rfdetr_segmentation_recipe(
    *,
    repository_root: str | Path | None = None,
    pretrained_checkpoint: str | Path | None = None,
    device: str = "mps",
) -> dict[str, Any]:
    """Return the fixed RF-DETR segmentation recipe for M0 and later milestones."""

    if device not in {"mps", "cuda", "cpu"}:
        raise RfdetrSegmentationCampaignError("device must be mps, cuda, or cpu")
    repository = Path(repository_root).expanduser().resolve() if repository_root else None
    checkpoint_path: Path | None = None
    checkpoint_digest: str | None = None
    if pretrained_checkpoint is not None:
        checkpoint_path = Path(pretrained_checkpoint).expanduser().resolve()
        if checkpoint_path.is_file():
            checkpoint_digest = _sha256_file(checkpoint_path)
    if repository is not None and checkpoint_path is not None:
        try:
            checkpoint_display = checkpoint_path.relative_to(repository).as_posix()
        except ValueError:
            checkpoint_display = str(checkpoint_path)
    else:
        checkpoint_display = str(checkpoint_path) if checkpoint_path is not None else None
    return {
        "schema_version": "rfdetr-segmentation-recipe/v1",
        "model": {
            "class": RFDETR_MODEL_CLASS,
            "variant": RFDETR_MODEL_VARIANT,
            "class_names": ["visible_card"],
            "num_classes": 1,
            "resolution": RFDETR_RESOLUTION,
        },
        "package": {"name": "rfdetr", "version": RFDETR_PACKAGE_VERSION},
        "pretrained_checkpoint": {
            "name": "rf-detr-seg-medium.pt",
            "path": checkpoint_display,
            "sha256": checkpoint_digest,
        },
        "augmentation": {
            "policy_id": "rfdetr-default-v1",
            "multi_scale": True,
            "expanded_scales": True,
            "do_random_resize_via_padding": False,
            "use_ema": True,
        },
        "training": {
            "batch_size": 1,
            "grad_accum_steps": 4,
            "effective_batch_size": 4,
            "epochs": 40,
            "seed": 6701,
            "num_workers": 0,
            "device": device,
            "mixed_precision": False,
            "output_dir_name": "rfdetr-segmentation-0067",
        },
        "early_stopping": {
            "enabled": True,
            "monitor": "val/mask_ap_50_95",
            "patience": 8,
            "min_delta": 0.001,
        },
        "budget": {"wall_clock_seconds": 7200, "candidate_count": 1, "sweep": False},
        "validation": {
            "confidence_threshold": 0.5,
            "metrics": [
                "mask_ap_50_95",
                "mask_ap50",
                "box_ap50_95",
                "recall",
                "false_predictions",
                "duplicate_predictions",
                "empty_prediction_rate",
            ],
            "group_by": "recording_id",
        },
        "data_contract": {
            "label": "visible_card",
            "mask_source": "reviewed_visible_region",
            "box_source": "derived_from_same_visible_region",
            "ignore_policy": "exclude_frame_on_any_reviewed_ignore_region",
            "ignore_loss": "no_custom_masked_loss",
            "test_partition": None,
        },
    }


def probe_rfdetr_segmentation_api() -> dict[str, Any]:
    """Inspect the installed RF-DETR segmentation API without constructing a model."""

    result: dict[str, Any] = {
        "package": "rfdetr",
        "required_version": RFDETR_PACKAGE_VERSION,
        "installed_version": None,
        "model_class": RFDETR_MODEL_CLASS,
        "constructor_signature": None,
        "train_signature": None,
        "train_accepts_keyword_arguments": False,
        "status": "unavailable",
        "gaps": [],
    }
    try:
        result["installed_version"] = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError:
        result["gaps"].append("rfdetr is not installed")
        return result
    except Exception as error:  # pragma: no cover - metadata backends are environment-specific
        result["gaps"].append(f"could not inspect installed rfdetr: {type(error).__name__}")
        return result
    if result["installed_version"] != RFDETR_PACKAGE_VERSION:
        result["gaps"].append(
            f"rfdetr version is {result['installed_version']!r}; "
            f"M0 requires {RFDETR_PACKAGE_VERSION!r}"
        )
    try:
        from rfdetr import RFDETRSegMedium

        result["constructor_signature"] = str(inspect.signature(RFDETRSegMedium))
        train = getattr(RFDETRSegMedium, "train", None)
        if train is None:
            raise TypeError("RFDETRSegMedium has no train method")
        train_signature = inspect.signature(train)
        result["train_signature"] = str(train_signature)
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in train_signature.parameters.values()
        )
        result["train_accepts_keyword_arguments"] = accepts_kwargs
        missing = (
            []
            if accepts_kwargs
            else [
                name for name in _REQUIRED_TRAIN_ARGUMENTS if name not in train_signature.parameters
            ]
        )
        if missing:
            result["gaps"].append(
                "RFDETRSegMedium.train is missing required arguments: " + ", ".join(missing)
            )
    except Exception as error:
        result["gaps"].append(f"could not inspect RF-DETR segmentation API: {type(error).__name__}")
    if not result["gaps"]:
        result["status"] = "available"
    return result


def _bundle_audit(
    recording_id: str,
    split: str,
    *,
    intake_root: Path,
    repository_root: Path,
    verify_source_bytes: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Read one accepted bundle and return stable lineage metadata."""

    gaps: list[str] = []
    directory = intake_root / recording_id
    manifest_path = directory / "manifest.json"
    source_record_path = directory / "source-record.json"
    if not directory.is_dir():
        return None, [f"{split} recording bundle is missing: {recording_id}"]
    try:
        manifest = _read_json(manifest_path, f"recording bundle manifest for {recording_id}")
        source_record = _read_json(source_record_path, f"source record for {recording_id}")
    except RfdetrSegmentationCampaignError as error:
        return None, [str(error)]
    if manifest.get("schema_version") != "repository-bundle/v1":
        gaps.append(f"{recording_id}: recording bundle schema is not repository-bundle/v1")
    if manifest.get("state") != "complete":
        gaps.append(f"{recording_id}: recording bundle is not complete")
    for field in ("recording_id", "session_id", "source_asset_id", "video_id", "source_sha256"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            gaps.append(f"{recording_id}: manifest is missing {field}")
    if manifest.get("recording_id") != recording_id:
        gaps.append(f"{recording_id}: manifest recording_id does not match selected ID")
    source_digest = source_record.get("sha256", source_record.get("source_sha256"))
    for field in ("recording_id", "session_id", "source_asset_id", "video_id", "table_setup"):
        if not isinstance(source_record.get(field), str) or not source_record[field]:
            gaps.append(f"{recording_id}: source record is missing {field}")
    if isinstance(source_digest, str) and _SHA256.fullmatch(source_digest):
        if source_digest != manifest.get("source_sha256"):
            gaps.append(f"{recording_id}: source record and bundle source digests differ")
    else:
        gaps.append(f"{recording_id}: source record has no valid source digest")
    if source_record.get("recording_id") != manifest.get("recording_id"):
        gaps.append(f"{recording_id}: source record and bundle recording IDs differ")
    for field in ("session_id", "source_asset_id", "video_id"):
        if source_record.get(field) != manifest.get(field):
            gaps.append(f"{recording_id}: source record and bundle {field} differ")
    allowed_uses = source_record.get("allowed_uses")
    if (
        not isinstance(allowed_uses, list)
        or not allowed_uses
        or any(not isinstance(value, str) for value in allowed_uses)
        or len(allowed_uses) != len(set(allowed_uses))
        or not set(allowed_uses) <= _ALLOWED_USES
        or split not in allowed_uses
    ):
        gaps.append(f"{recording_id}: source permission does not allow {split}")
    if source_record.get("source_permission") not in _SOURCE_PERMISSIONS:
        gaps.append(f"{recording_id}: source record has a disallowed source permission")
    if source_record.get("retention_state") != "active":
        gaps.append(f"{recording_id}: source retention state is not active")
    video_info = manifest.get("files", {}).get("video")
    if not isinstance(video_info, Mapping):
        gaps.append(f"{recording_id}: bundle has no video file descriptor")
        video_info = {}
    video_path: Path | None = None
    if isinstance(video_info.get("relative_path"), str):
        try:
            video_path = _safe_relative_path(video_info["relative_path"], directory, "video path")
        except RfdetrSegmentationCampaignError as error:
            gaps.append(f"{recording_id}: {error}")
    else:
        gaps.append(f"{recording_id}: video descriptor has no relative_path")
    if video_path is not None:
        if not video_path.is_file():
            gaps.append(f"{recording_id}: source video is missing")
        else:
            actual_size = video_path.stat().st_size
            declared_size = video_info.get("byte_length", source_record.get("byte_length"))
            if actual_size != declared_size:
                gaps.append(f"{recording_id}: source video byte length differs from declaration")
            if verify_source_bytes:
                actual_digest = _sha256_file(video_path)
                if actual_digest != manifest.get("source_sha256"):
                    gaps.append(f"{recording_id}: source video digest differs from declaration")
    result = {
        "recording_id": recording_id,
        "split": split,
        "session_id": manifest.get("session_id"),
        "source_asset_id": manifest.get("source_asset_id"),
        "video_id": manifest.get("video_id"),
        "table_setup": source_record.get("table_setup"),
        "source_permission": source_record.get("source_permission"),
        "allowed_uses": sorted(allowed_uses) if isinstance(allowed_uses, list) else [],
        "retention_state": source_record.get("retention_state"),
        "source_sha256": manifest.get("source_sha256"),
        "source_byte_length": video_info.get("byte_length", source_record.get("byte_length")),
        "source_video_path": (
            _relative(video_path, repository_root) if video_path is not None else None
        ),
        "manifest_path": _relative(manifest_path, repository_root),
        "manifest_sha256": sha256_json(manifest),
        "source_record_path": _relative(source_record_path, repository_root),
        "source_record_sha256": sha256_json(source_record),
        "source_bytes_verified": verify_source_bytes,
    }
    return result, gaps


def _valid_frame_identity(
    frame: Any, source_sha256: str, context: str
) -> tuple[dict[str, Any] | None, list[str]]:
    gaps: list[str] = []
    if not isinstance(frame, Mapping):
        return None, [f"{context}: frame_identity must be an object"]
    required = ("frame_index", "image_sha256", "source_video_sha256", "width", "height")
    for field in required:
        if field not in frame:
            gaps.append(f"{context}: frame_identity is missing {field}")
    if not isinstance(frame.get("frame_index"), int) or isinstance(frame.get("frame_index"), bool):
        gaps.append(f"{context}: frame_index must be an integer")
    elif frame["frame_index"] < 0:
        gaps.append(f"{context}: frame_index must be non-negative")
    for field in ("width", "height"):
        if not isinstance(frame.get(field), int) or isinstance(frame.get(field), bool):
            gaps.append(f"{context}: {field} must be an integer")
        elif frame[field] <= 0:
            gaps.append(f"{context}: {field} must be positive")
    for field in ("image_sha256", "source_video_sha256"):
        if not isinstance(frame.get(field), str) or _SHA256.fullmatch(frame[field]) is None:
            gaps.append(f"{context}: {field} must be a lower-case SHA-256 digest")
    if frame.get("source_video_sha256") != source_sha256:
        gaps.append(f"{context}: frame points to a different source video")
    return dict(frame), gaps


def _polygon_points(
    value: Any, context: str
) -> tuple[list[list[dict[str, int]]] | None, list[str]]:
    if not isinstance(value, list) or not value:
        return None, [f"{context} must contain at least one polygon"]
    gaps: list[str] = []
    polygons: list[list[dict[str, int]]] = []
    for polygon_index, polygon in enumerate(value):
        if not isinstance(polygon, list) or len(polygon) < 3:
            gaps.append(f"{context}[{polygon_index}] must contain at least three points")
            continue
        normalized: list[dict[str, int]] = []
        for point_index, point in enumerate(polygon):
            if not isinstance(point, Mapping):
                gaps.append(f"{context}[{polygon_index}][{point_index}] must be an object")
                continue
            x, y = point.get("x"), point.get("y")
            if (
                isinstance(x, bool)
                or not isinstance(x, int)
                or isinstance(y, bool)
                or not isinstance(y, int)
            ):
                gaps.append(f"{context}[{polygon_index}][{point_index}] x and y must be integers")
                continue
            if not 0 <= x <= 1000 or not 0 <= y <= 1000:
                gaps.append(f"{context}[{polygon_index}][{point_index}] must be in 0..1000")
                continue
            normalized.append({"x": x, "y": y})
        if len(normalized) == len(polygon):
            polygons.append(normalized)
    return (polygons if not gaps else None), gaps


def _validate_candidate(
    candidate: Any, frame: Mapping[str, Any], context: str
) -> tuple[dict[str, Any] | None, list[str]]:
    gaps: list[str] = []
    if not isinstance(candidate, Mapping):
        return None, [f"{context} must be an object"]
    card_id = candidate.get("card_id")
    if not isinstance(card_id, str) or not card_id:
        gaps.append(f"{context}.card_id must be a non-empty string")
    geometry = candidate.get("geometry")
    geometry_kind = geometry.get("kind") if isinstance(geometry, Mapping) else None
    if geometry_kind not in {"visible-region/v1", "reviewed-visible-region/v1"}:
        gaps.append(f"{context}.geometry must be a reviewed visible-region geometry")
        polygons = None
    else:
        visible_region = geometry.get("visible_region")
        polygons, polygon_gaps = _polygon_points(
            visible_region.get("polygons") if isinstance(visible_region, Mapping) else None,
            f"{context}.geometry.visible_region.polygons",
        )
        gaps.extend(polygon_gaps)
    normalization = candidate.get("normalization")
    if not isinstance(normalization, Mapping):
        gaps.append(f"{context}.normalization must be an object")
    else:
        if normalization.get("policy_id") != "full-frame-0-1000/v1":
            gaps.append(f"{context}.normalization has an unsupported policy")
        if normalization.get("width") != frame.get("width") or normalization.get(
            "height"
        ) != frame.get("height"):
            gaps.append(f"{context}.normalization does not match frame dimensions")
    if gaps:
        return None, gaps
    return {
        "card_id": card_id,
        "geometry": {
            "kind": geometry_kind,
            "visible_region": {"polygons": polygons},
        },
        "normalization": dict(normalization),
        "side": candidate.get("side", "unknown"),
    }, []


def _validate_ignore_region(
    region: Any, frame: Mapping[str, Any], context: str
) -> tuple[dict[str, Any] | None, list[str]]:
    gaps: list[str] = []
    if not isinstance(region, Mapping):
        return None, [f"{context} must be an object"]
    if not isinstance(region.get("region_id"), str) or not region["region_id"]:
        gaps.append(f"{context}.region_id must be a non-empty string")
    geometry = region.get("geometry")
    if not isinstance(geometry, Mapping) or geometry.get("kind") != "reviewed-ignore-region/v1":
        gaps.append(f"{context}.geometry must be reviewed-ignore-region/v1")
        polygons = None
    else:
        polygons, polygon_gaps = _polygon_points(
            geometry.get("polygons"), f"{context}.geometry.polygons"
        )
        gaps.extend(polygon_gaps)
    normalization = region.get("normalization")
    if not isinstance(normalization, Mapping):
        gaps.append(f"{context}.normalization must be an object")
    else:
        if normalization.get("policy_id") != "full-frame-0-1000/v1":
            gaps.append(f"{context}.normalization has an unsupported policy")
        if normalization.get("width") != frame.get("width") or normalization.get(
            "height"
        ) != frame.get("height"):
            gaps.append(f"{context}.normalization does not match frame dimensions")
    if not isinstance(region.get("reason"), str) or not region["reason"]:
        gaps.append(f"{context}.reason must be a non-empty string")
    if gaps:
        return None, gaps
    return dict(region), []


def _normalize_outcome(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.setdefault("ignored_regions", [])
    return result


def _reference_audit(
    recording: Mapping[str, Any],
    *,
    operations_root: Path,
    repository_root: Path,
) -> tuple[dict[str, Any], list[str]]:
    recording_id = recording["recording_id"]
    reference_root = operations_root / "pipeline-references" / recording_id / "visible_cards"
    state_path = reference_root / "state.json"
    draft_path = reference_root / "draft.json"
    gaps: list[str] = []
    result: dict[str, Any] = {
        "recording_id": recording_id,
        "reference_path": _relative(reference_root, repository_root),
        "reference_revision_id": None,
        "reference_state_sha256": None,
        "reference_draft_sha256": None,
        "reference_revision_manifest_path": None,
        "reference_revision_manifest_sha256": None,
        "reference_content_sha256": None,
        "reviewed_frame_count": 0,
        "retained_frame_count": 0,
        "excluded_frame_count": 0,
        "ignored_region_count": 0,
        "target_count": 0,
        "samples": [],
        "excluded_frames": [],
        "ineligible_outcomes": [],
    }
    if not state_path.is_file() or not draft_path.is_file():
        return result, [f"{recording_id}: maintained visible_cards reference is incomplete"]
    try:
        state = _read_json(state_path, f"visible_cards state for {recording_id}")
        draft = _read_json(draft_path, f"visible_cards draft for {recording_id}")
    except RfdetrSegmentationCampaignError as error:
        return result, [str(error)]
    result["reference_state_sha256"] = sha256_json(state)
    result["reference_draft_sha256"] = sha256_json(draft)
    revision_id = state.get("selected_completed_revision_id")
    result["reference_revision_id"] = revision_id
    if state.get("schema_version") != "pipeline-reference-state/v1":
        gaps.append(f"{recording_id}: maintained reference state has an unsupported schema")
    if state.get("draft_state") != "completed":
        gaps.append(f"{recording_id}: maintained visible_cards reference is not completed")
    if state.get("recording_id") != recording_id or state.get("content_type") != "visible_cards":
        gaps.append(f"{recording_id}: maintained reference state has wrong identity")
    if draft.get("schema_version") != "pipeline-reference-draft/v1":
        gaps.append(f"{recording_id}: maintained visible_cards draft has an unsupported schema")
    if draft.get("recording_id") != recording_id or draft.get("content_type") != "visible_cards":
        gaps.append(f"{recording_id}: maintained visible_cards draft has wrong identity")
    if not isinstance(revision_id, str) or not revision_id:
        return result, [*gaps, f"{recording_id}: completed reference has no selected revision"]
    revision_root = operations_root / "pipeline" / "revisions" / revision_id
    revision_manifest_path = revision_root / "manifest.json"
    content_path = revision_root / "content.json"
    result["reference_revision_manifest_path"] = _relative(revision_manifest_path, repository_root)
    if not revision_manifest_path.is_file() or not content_path.is_file():
        return result, [*gaps, f"{recording_id}: selected reference revision is incomplete"]
    try:
        revision_manifest = _read_json(
            revision_manifest_path, f"visible_cards revision manifest for {recording_id}"
        )
        content = _read_json(content_path, f"visible_cards revision content for {recording_id}")
    except RfdetrSegmentationCampaignError as error:
        return result, [*gaps, str(error)]
    result["reference_revision_manifest_sha256"] = sha256_json(revision_manifest)
    result["reference_content_sha256"] = sha256_json(content)
    if revision_manifest.get("revision_id") != revision_id:
        gaps.append(f"{recording_id}: selected revision ID does not match its path")
    if revision_manifest.get("recording_id") != recording_id:
        gaps.append(f"{recording_id}: selected revision points to another recording")
    if revision_manifest.get("content_type") != "visible_cards":
        gaps.append(f"{recording_id}: selected revision is not visible-card data")
    if revision_manifest.get("content_schema") != "visible-card-data/v1":
        gaps.append(f"{recording_id}: selected revision has an unsupported content schema")
    if revision_manifest.get("origin") not in {"manual", "corrected"}:
        gaps.append(f"{recording_id}: selected revision is not human-maintained")
    producer = revision_manifest.get("producer")
    if not isinstance(producer, Mapping) or producer.get("kind") != "human":
        gaps.append(f"{recording_id}: selected revision has no human lineage")
    if revision_manifest.get("content_sha256") != result["reference_content_sha256"]:
        gaps.append(f"{recording_id}: selected revision content digest does not match")
    revision_source = revision_manifest.get("source")
    if not isinstance(revision_source, Mapping):
        gaps.append(f"{recording_id}: selected revision has no source lineage")
    else:
        if revision_source.get("video_sha256") != recording["source_sha256"]:
            gaps.append(f"{recording_id}: selected revision source digest differs from bundle")
        if revision_source.get("recording_id") != recording_id:
            gaps.append(f"{recording_id}: selected revision source recording differs from bundle")
    outcomes = content.get("outcomes")
    draft_items = draft.get("items")
    coverage = draft.get("coverage")
    coverage_frames = coverage.get("frames") if isinstance(coverage, Mapping) else None
    if not isinstance(outcomes, list) or not isinstance(draft_items, list):
        return result, [*gaps, f"{recording_id}: maintained reference has no complete outcome list"]
    if not isinstance(coverage_frames, list):
        gaps.append(f"{recording_id}: maintained reference has no complete frame coverage")
        coverage_frames = []
    result["reviewed_frame_count"] = len(outcomes)
    if len(draft_items) != len(outcomes):
        gaps.append(f"{recording_id}: draft and selected revision outcome counts differ")
    if len(coverage_frames) != len(outcomes):
        gaps.append(f"{recording_id}: frame coverage and outcome counts differ")
    coverage_by_item = {
        frame.get("item_id"): frame
        for frame in coverage_frames
        if isinstance(frame, Mapping) and isinstance(frame.get("item_id"), str)
    }
    if len(coverage_by_item) != len(coverage_frames):
        gaps.append(f"{recording_id}: frame coverage item IDs are not unique")
    for index, outcome_value in enumerate(outcomes):
        context = f"{recording_id}: outcome[{index}]"
        if not isinstance(outcome_value, Mapping):
            gaps.append(f"{context} must be an object")
            continue
        outcome = _normalize_outcome(outcome_value)
        item_id = outcome.get("event_id")
        draft_item = draft_items[index] if index < len(draft_items) else None
        if not isinstance(draft_item, Mapping):
            gaps.append(f"{context} has no corresponding draft item")
        else:
            if draft_item.get("item_id") != item_id:
                gaps.append(f"{context}: draft item ID does not match event_id")
            draft_outcome = draft_item.get("item")
            if isinstance(draft_outcome, Mapping) and _normalize_outcome(draft_outcome) != outcome:
                gaps.append(f"{context}: selected revision differs from maintained draft")
        coverage_frame = coverage_by_item.get(item_id)
        frame, frame_gaps = _valid_frame_identity(
            outcome.get("frame_identity"), recording["source_sha256"], context
        )
        gaps.extend(frame_gaps)
        if coverage_frame is None:
            gaps.append(f"{context}: outcome is missing from frame coverage")
        elif frame is not None and coverage_frame.get("frame_identity") != frame:
            gaps.append(f"{context}: coverage frame identity differs from outcome")
        ignored = outcome.get("ignored_regions", [])
        if not isinstance(ignored, list):
            gaps.append(f"{context}.ignored_regions must be a list")
            ignored = []
        normalized_ignored: list[dict[str, Any]] = []
        for region_index, region in enumerate(ignored):
            normalized_region, region_gaps = _validate_ignore_region(
                region, frame or {}, f"{context}.ignored_regions[{region_index}]"
            )
            gaps.extend(region_gaps)
            if normalized_region is not None:
                normalized_ignored.append(normalized_region)
        result["ignored_region_count"] += len(normalized_ignored)
        candidates = outcome.get("candidates", [])
        if not isinstance(candidates, list):
            gaps.append(f"{context}.candidates must be a list")
            candidates = []
        expected_decision = (
            "cards_and_ignored"
            if ignored
            else "cards"
            if outcome.get("status") == "detected" and candidates
            else "empty"
            if outcome.get("status") == "empty"
            else "unusable"
        )
        if coverage_frame is not None and coverage_frame.get("decision") != expected_decision:
            gaps.append(f"{context}: frame coverage decision is inconsistent with outcome")
        if normalized_ignored:
            result["excluded_frame_count"] += 1
            result["excluded_frames"].append(
                {
                    "item_id": item_id,
                    "event_id": item_id,
                    "frame_identity": frame,
                    "decision": "cards_and_ignored",
                    "candidate_count": len(candidates),
                    "target_count": len(candidates),
                    "ignored_region_ids": [region["region_id"] for region in normalized_ignored],
                }
            )
            continue
        if outcome.get("status") != "detected":
            result["ineligible_outcomes"].append(
                {
                    "item_id": item_id,
                    "event_id": item_id,
                    "status": outcome.get("status"),
                    "frame_identity": frame,
                    "candidate_count": len(candidates),
                    "target_count": len(candidates),
                    "reason": outcome.get("error") or "reviewed outcome is not detected",
                }
            )
            continue
        if not isinstance(draft_item, Mapping) or draft_item.get("review_state") not in {
            "accepted",
            "corrected",
        }:
            gaps.append(f"{context}: draft item is not accepted or corrected")
            result["ineligible_outcomes"].append(
                {
                    "item_id": item_id,
                    "event_id": item_id,
                    "status": "invalid",
                    "frame_identity": frame,
                    "candidate_count": len(candidates),
                    "target_count": len(candidates),
                    "reason": "visible-region outcome is not human-reviewed",
                }
            )
            continue
        if not candidates:
            result["ineligible_outcomes"].append(
                {
                    "item_id": item_id,
                    "event_id": item_id,
                    "status": "empty",
                    "frame_identity": frame,
                    "candidate_count": 0,
                    "target_count": 0,
                    "reason": "reviewed empty frame; not a background negative",
                }
            )
            continue
        normalized_candidates: list[dict[str, Any]] = []
        candidate_ids: set[str] = set()
        item_gaps: list[str] = []
        for candidate_index, candidate in enumerate(candidates):
            normalized_candidate, candidate_gaps = _validate_candidate(
                candidate, frame or {}, f"{context}.candidates[{candidate_index}]"
            )
            item_gaps.extend(candidate_gaps)
            if normalized_candidate is not None:
                if normalized_candidate["card_id"] in candidate_ids:
                    item_gaps.append(f"{context}: candidate card IDs are not unique")
                candidate_ids.add(normalized_candidate["card_id"])
                normalized_candidates.append(normalized_candidate)
        if item_gaps:
            gaps.extend(item_gaps)
            result["ineligible_outcomes"].append(
                {
                    "item_id": item_id,
                    "event_id": item_id,
                    "status": "invalid",
                    "frame_identity": frame,
                    "candidate_count": len(candidates),
                    "target_count": len(candidates),
                    "reason": "visible-region geometry validation failed",
                }
            )
            continue
        result["retained_frame_count"] += 1
        result["target_count"] += len(normalized_candidates)
        result["samples"].append(
            {
                "recording_id": recording_id,
                "split": recording["split"],
                "session_id": recording["session_id"],
                "table_setup": recording["table_setup"],
                "source_asset_id": recording["source_asset_id"],
                "source_sha256": recording["source_sha256"],
                "reference_revision_id": revision_id,
                "event_id": item_id,
                "item_id": draft_item.get("item_id")
                if isinstance(draft_item, Mapping)
                else item_id,
                "frame_identity": frame,
                "targets": normalized_candidates,
            }
        )
    return result, gaps


def _holdout_groups(
    repository_root: Path, operations_root: Path, holdout_registry_path: str | Path | None
) -> tuple[dict[str, Any], set[tuple[str, str]], list[str]]:
    path = _resolve(
        repository_root,
        holdout_registry_path,
        operations_root / "system-holdout-registry.json",
    )
    try:
        registry = load_system_holdout_registry(path)
        return (
            {
                "path": _relative(path, repository_root) if path.exists() else None,
                "registry_version": registry["registry_version"],
                "registry_digest": registry["registry_digest"],
            },
            set(sealed_group_keys(registry)),
            [],
        )
    except (OSError, ValueError) as error:
        return (
            {
                "path": _relative(path, repository_root),
                "registry_version": None,
                "registry_digest": None,
            },
            set(),
            [f"could not load system holdout registry: {error}"],
        )


def build_rfdetr_segmentation_manifest(
    repository_root: str | Path,
    *,
    intake_root: str | Path | None = None,
    operations_root: str | Path | None = None,
    holdout_registry_path: str | Path | None = None,
    pretrained_checkpoint: str | Path | None = None,
    device: str = "mps",
    verify_source_bytes: bool = False,
    api_probe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the deterministic, read-only RF-DETR M0 campaign manifest."""

    repository = Path(repository_root).expanduser().resolve()
    intake = _resolve(repository, intake_root, repository / "data" / "intake" / "recordings")
    operations = _resolve(repository, operations_root, repository / "data" / "operations")
    recipe = default_rfdetr_segmentation_recipe(
        repository_root=repository,
        pretrained_checkpoint=pretrained_checkpoint,
        device=device,
    )
    probe = dict(api_probe) if api_probe is not None else probe_rfdetr_segmentation_api()
    gaps: list[str] = []
    if recipe["pretrained_checkpoint"]["sha256"] is None:
        gaps.append("pretrained RF-DETR segmentation checkpoint is missing or unreadable")
    holdout, held_out, holdout_gaps = _holdout_groups(repository, operations, holdout_registry_path)
    gaps.extend(holdout_gaps)
    recordings: list[dict[str, Any]] = []
    reference_reports: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    excluded_frames: list[dict[str, Any]] = []
    ineligible_outcomes: list[dict[str, Any]] = []
    for recording_id in (*TRAIN_RECORDING_IDS, *VALIDATION_RECORDING_IDS):
        split = RECORDING_SPLITS[recording_id]
        recording, recording_gaps = _bundle_audit(
            recording_id,
            split,
            intake_root=intake,
            repository_root=repository,
            verify_source_bytes=verify_source_bytes,
        )
        gaps.extend(recording_gaps)
        if recording is None:
            continue
        protected_groups = {
            ("session_id", recording.get("session_id")),
            ("table_setup", recording.get("table_setup")),
            ("source_lineage", recording.get("source_asset_id")),
        }
        sealed_groups = sorted(protected_groups & held_out)
        if sealed_groups:
            groups = ", ".join(f"{name}:{value}" for name, value in sealed_groups)
            gaps.append(f"{recording_id}: recording is in the sealed system holdout ({groups})")
            continue
        reference_report, reference_gaps = _reference_audit(
            recording, operations_root=operations, repository_root=repository
        )
        gaps.extend(reference_gaps)
        recordings.append(recording)
        reference_reports.append(reference_report)
        samples.extend(reference_report["samples"])
        excluded_frames.extend(
            {
                **frame,
                "recording_id": recording["recording_id"],
                "session_id": recording["session_id"],
                "source_sha256": recording["source_sha256"],
                "reference_revision_id": reference_report["reference_revision_id"],
                "split": split,
            }
            for frame in reference_report["excluded_frames"]
        )
        ineligible_outcomes.extend(
            {
                **outcome,
                "recording_id": recording["recording_id"],
                "session_id": recording["session_id"],
                "source_sha256": recording["source_sha256"],
                "reference_revision_id": reference_report["reference_revision_id"],
                "split": split,
            }
            for outcome in reference_report["ineligible_outcomes"]
        )
    if set(recording["recording_id"] for recording in recordings) != set(RECORDING_SPLITS):
        missing = sorted(
            set(RECORDING_SPLITS) - {recording["recording_id"] for recording in recordings}
        )
        gaps.append("selected recording set is incomplete: " + ", ".join(missing))
    overlap_fields = {
        "recording_id": [recording["recording_id"] for recording in recordings],
        "session_id": [recording["session_id"] for recording in recordings],
        "table_setup": [recording["table_setup"] for recording in recordings],
        "source_asset_id": [recording["source_asset_id"] for recording in recordings],
        "source_sha256": [recording["source_sha256"] for recording in recordings],
        "reference_revision_id": [report["reference_revision_id"] for report in reference_reports],
    }
    overlaps = {
        field: sorted({value for value in values if values.count(value) > 1})
        for field, values in overlap_fields.items()
    }
    if any(overlaps.values()):
        gaps.append("train and validation source groups overlap in selected lineage fields")
    for field, values in overlap_fields.items():
        if len(values) != len(set(values)):
            gaps.append(f"selected recording {field} values are not unique")
    gaps.extend(str(gap) for gap in probe.get("gaps", []) if isinstance(gap, str))
    split_summary = {
        "train": {
            "recording_ids": list(TRAIN_RECORDING_IDS),
            "reviewed_frames": sum(
                report["reviewed_frame_count"]
                for report in reference_reports
                if report["recording_id"] in TRAIN_RECORDING_IDS
            ),
            "retained_frames": sum(
                report["retained_frame_count"]
                for report in reference_reports
                if report["recording_id"] in TRAIN_RECORDING_IDS
            ),
            "targets": sum(
                report["target_count"]
                for report in reference_reports
                if report["recording_id"] in TRAIN_RECORDING_IDS
            ),
        },
        "validation": {
            "recording_ids": list(VALIDATION_RECORDING_IDS),
            "reviewed_frames": sum(
                report["reviewed_frame_count"]
                for report in reference_reports
                if report["recording_id"] in VALIDATION_RECORDING_IDS
            ),
            "retained_frames": sum(
                report["retained_frame_count"]
                for report in reference_reports
                if report["recording_id"] in VALIDATION_RECORDING_IDS
            ),
            "targets": sum(
                report["target_count"]
                for report in reference_reports
                if report["recording_id"] in VALIDATION_RECORDING_IDS
            ),
        },
    }
    inventory = {
        "recording_count": len(recordings),
        "selected_recording_count": len(RECORDING_SPLITS),
        "reviewed_frame_count": sum(report["reviewed_frame_count"] for report in reference_reports),
        "retained_frame_count": sum(report["retained_frame_count"] for report in reference_reports),
        "excluded_frame_count": len(excluded_frames),
        "ineligible_outcome_count": len(ineligible_outcomes),
        "ignored_region_count": sum(report["ignored_region_count"] for report in reference_reports),
        "target_count": len([target for sample in samples for target in sample["targets"]]),
    }
    expected_total_gaps = []
    for split, expected in EXPECTED_COUNTS.items():
        for field, value in expected.items():
            if split_summary[split][field] != value:
                expected_total_gaps.append(
                    f"{split} {field} drift: expected {value}, found {split_summary[split][field]}"
                )
    inventory_fields = {
        "reviewed_frames": "reviewed_frame_count",
        "retained_frames": "retained_frame_count",
        "targets": "target_count",
    }
    for field, value in EXPECTED_TOTALS.items():
        inventory_field = inventory_fields[field]
        actual = inventory[inventory_field]
        if actual != value:
            expected_total_gaps.append(f"total {field} drift: expected {value}, found {actual}")
    gaps.extend(expected_total_gaps)
    if inventory["excluded_frame_count"] and inventory["target_count"] == 0:
        gaps.append("selected references contain no retained visible-card targets")
    freeze_state = "frozen" if not gaps else "blocked"
    core = {
        "schema_version": RFDETR_SEGMENTATION_MANIFEST_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "milestone": "M0",
        "read_only": True,
        "freeze_state": freeze_state,
        "split": split_summary,
        "recipe": recipe,
        "recipe_sha256": sha256_json(recipe),
        "api_probe": probe,
        "recordings": recordings,
        "references": reference_reports,
        "samples": samples,
        "excluded_frames": excluded_frames,
        "ineligible_outcomes": ineligible_outcomes,
        "inventory": inventory,
        "overlaps": overlaps,
        "holdout_registry": holdout,
        "coverage_gaps": sorted(set(gaps)),
    }
    return json.loads(
        canonical_json_bytes({**core, "manifest_digest": sha256_json(core)}).decode("utf-8")
    )


def validate_rfdetr_segmentation_manifest(raw: Mapping[str, Any]) -> None:
    """Validate the immutable campaign manifest and its internal digests."""

    data = _mapping(raw, "RF-DETR segmentation campaign manifest")
    expected = {
        "schema_version",
        "campaign_id",
        "milestone",
        "read_only",
        "freeze_state",
        "split",
        "recipe",
        "recipe_sha256",
        "api_probe",
        "recordings",
        "references",
        "samples",
        "excluded_frames",
        "ineligible_outcomes",
        "inventory",
        "overlaps",
        "holdout_registry",
        "coverage_gaps",
        "manifest_digest",
    }
    if set(data) != expected:
        raise RfdetrSegmentationCampaignError("RF-DETR segmentation manifest has invalid fields")
    if data["schema_version"] != RFDETR_SEGMENTATION_MANIFEST_SCHEMA_VERSION:
        raise RfdetrSegmentationCampaignError("RF-DETR segmentation manifest schema is unsupported")
    if data["campaign_id"] != CAMPAIGN_ID or data["milestone"] != "M0":
        raise RfdetrSegmentationCampaignError("RF-DETR segmentation manifest identity is invalid")
    if data["read_only"] is not True or data["freeze_state"] not in {"frozen", "blocked"}:
        raise RfdetrSegmentationCampaignError("RF-DETR segmentation manifest state is invalid")
    recipe = _mapping(data["recipe"], "recipe")
    if data["recipe_sha256"] != sha256_json(recipe):
        raise RfdetrSegmentationCampaignError("recipe_sha256 does not match recipe")
    if recipe.get("package") != {"name": "rfdetr", "version": RFDETR_PACKAGE_VERSION}:
        raise RfdetrSegmentationCampaignError("RF-DETR package pin changed")
    model = _mapping(recipe.get("model"), "recipe.model")
    if model.get("class") != RFDETR_MODEL_CLASS or model.get("resolution") != RFDETR_RESOLUTION:
        raise RfdetrSegmentationCampaignError("RF-DETR model or resolution pin changed")
    if recipe.get("data_contract", {}).get("test_partition", "missing") is not None:
        raise RfdetrSegmentationCampaignError("M0 must not define a test partition")
    probe = _mapping(data["api_probe"], "api_probe")
    if not isinstance(probe.get("gaps"), list):
        raise RfdetrSegmentationCampaignError("api_probe.gaps must be a list")
    if data["freeze_state"] == "frozen":
        checkpoint = _mapping(recipe["pretrained_checkpoint"], "recipe.pretrained_checkpoint")
        if (
            not isinstance(checkpoint.get("sha256"), str)
            or _SHA256.fullmatch(checkpoint["sha256"]) is None
        ):
            raise RfdetrSegmentationCampaignError(
                "frozen M0 manifest must pin a pretrained checkpoint digest"
            )
        if probe.get("status") != "available" or probe.get("gaps"):
            raise RfdetrSegmentationCampaignError(
                "frozen M0 manifest must pass the RF-DETR segmentation API probe"
            )
    for field in (
        "recordings",
        "references",
        "samples",
        "excluded_frames",
        "ineligible_outcomes",
        "coverage_gaps",
    ):
        if not isinstance(data[field], list):
            raise RfdetrSegmentationCampaignError(f"{field} must be a list")
    inventory = _mapping(data["inventory"], "inventory")
    for field in inventory:
        if (
            isinstance(inventory[field], bool)
            or not isinstance(inventory[field], int)
            or inventory[field] < 0
        ):
            raise RfdetrSegmentationCampaignError(
                f"inventory.{field} must be a non-negative integer"
            )
    if data["freeze_state"] == "frozen" and data["coverage_gaps"]:
        raise RfdetrSegmentationCampaignError("frozen M0 manifest cannot contain coverage gaps")
    core = {key: data[key] for key in expected if key != "manifest_digest"}
    if data["manifest_digest"] != sha256_json(core):
        raise RfdetrSegmentationCampaignError("manifest_digest does not match manifest contents")


def write_rfdetr_segmentation_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    """Write one manifest and refuse to replace an existing different manifest."""

    validate_rfdetr_segmentation_manifest(manifest)
    destination = Path(path).expanduser().resolve()
    payload = canonical_json_bytes(manifest) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise RfdetrSegmentationCampaignError(
                f"immutable RF-DETR M0 manifest already exists and differs: {destination}"
            )
        return destination
    destination.write_bytes(payload)
    return destination


def render_rfdetr_segmentation_human(manifest: Mapping[str, Any]) -> str:
    """Render a concise operator report for the M0 audit."""

    inventory = manifest["inventory"]
    lines = [
        "RF-DETR visible-region segmentation campaign M0",
        f"status: {manifest['freeze_state']}",
        f"recordings: {inventory['recording_count']}/{inventory['selected_recording_count']}",
        f"reviewed frames: {inventory['reviewed_frame_count']}",
        f"retained frames: {inventory['retained_frame_count']}",
        f"targets: {inventory['target_count']}",
        f"excluded frames: {inventory['excluded_frame_count']}",
        f"ineligible outcomes: {inventory['ineligible_outcome_count']}",
        f"manifest digest: {manifest['manifest_digest']}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"
