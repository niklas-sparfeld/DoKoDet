"""Materialize the bounded visible-card detector pseudo-label dataset.

This module joins the exact-event frame packages produced by CardEventNet with cached visible-card
provider results.  The output is a COCO annotation view over the source frames.  It does not copy
source media and it does not turn Gemini proposals into reviewed references.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .visible_cards import (
    CACHE_SCHEMA_VERSION,
    PREDICTION_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    ProviderResult,
    VisibleCardError,
    VisibleCardPrediction,
    load_run_artifact,
)

VISIBLE_CARD_DATASET_SCHEMA = "visible-card-pseudo-label-dataset/v1"
VISIBLE_CARD_SPLIT_SCHEMA = "visible-card-pseudo-label-split/v1"
VISIBLE_CARD_RECIPE_SCHEMA = "visible-card-detector-recipe/v1"
COCO_VERSION = "coco-2017"

DEFAULT_TARGET_OFFSET_MS = 0
DEFAULT_TARGET_FRAME_COUNT = 20
DEFAULT_MAX_FRAMES = 40
DEFAULT_SEED = 37
DEFAULT_EPOCHS = 20
DEFAULT_CONFIDENCE_THRESHOLD = 0.5
DEFAULT_MODEL_VARIANT = "RFDETRLarge"
DEFAULT_RFDETR_VERSION = "1.9.4"
DEFAULT_INPUT_SIZE = 704
DEFAULT_CHECKPOINT_NAME = "rf-detr-large.pth"
DEFAULT_TARGET_CLASS = "visible_card"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class VisibleCardDatasetError(ValueError):
    """Raised when the bounded pseudo-label dataset cannot be materialized safely."""


@dataclass(frozen=True, slots=True)
class VisibleCardDatasetConfig:
    """Inputs and frozen M0 values for one dataset materialization."""

    evidence_root: Path
    results_root: Path
    output_dir: Path
    system_holdout: Path | None = None
    target_frame_count: int = DEFAULT_TARGET_FRAME_COUNT
    max_frames: int = DEFAULT_MAX_FRAMES
    seed: int = DEFAULT_SEED
    epochs: int = DEFAULT_EPOCHS
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD

    def __post_init__(self) -> None:
        if self.target_frame_count < 1:
            raise VisibleCardDatasetError("target_frame_count must be positive")
        if self.max_frames < self.target_frame_count:
            raise VisibleCardDatasetError("max_frames must be at least target_frame_count")
        if self.max_frames > DEFAULT_MAX_FRAMES:
            raise VisibleCardDatasetError(f"max_frames must be at most {DEFAULT_MAX_FRAMES}")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise VisibleCardDatasetError("seed must be an integer")
        if isinstance(self.epochs, bool) or not isinstance(self.epochs, int) or self.epochs < 1:
            raise VisibleCardDatasetError("epochs must be a positive integer")
        if not (
            math.isfinite(self.confidence_threshold) and 0.0 <= self.confidence_threshold <= 1.0
        ):
            raise VisibleCardDatasetError("confidence_threshold must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class _Target:
    normalized_box: dict[str, int]
    pixel_bbox: tuple[int, int, int, int]
    segmentation: tuple[float, ...]
    side: str
    provider_label: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    package_id: str
    frame_part_name: str
    frame_path: str
    frame_sha256: str
    width: int
    height: int
    source_asset_id: str
    source_asset_sha256: str | None
    source_lineage_group: str
    session_id: str
    table_setup: str
    deck_design: str
    event_id: str
    source_video_id: str | None
    annotation_event_index: int | None
    event_time_ms: int
    event_type: str
    request_digest: str
    result_digest: str
    result_path: str
    provider: str
    targets: tuple[_Target, ...]

    @property
    def frame_id(self) -> str:
        return f"{self.package_id}:{self.frame_part_name}"


@dataclass(frozen=True, slots=True)
class _ResultArtifact:
    package_id: str
    frame_part_name: str
    request_digest: str
    image_sha256: str
    target_offset_ms: int
    provider: str
    status: str
    prediction: VisibleCardPrediction
    path: Path
    relative_path: str
    digest: str


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    temporary.replace(path)


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardDatasetError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise VisibleCardDatasetError(f"{context} must be a JSON object: {path}")
    return value


def _text(value: Any, field: str, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise VisibleCardDatasetError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if _IDENTIFIER.fullmatch(result) is None:
        raise VisibleCardDatasetError(f"{field} contains unsupported characters")
    return result


def _digest_value(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VisibleCardDatasetError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VisibleCardDatasetError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisibleCardDatasetError(f"{field} must be a non-negative integer")
    return value


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise VisibleCardDatasetError(f"path is outside its input root: {path}") from error


def _result_hint(path: Path) -> tuple[str, str] | None:
    match = re.match(r"^(.+)-(frame_[^/]+)\.json$", path.name)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _validate_request(request: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(request, dict):
        raise VisibleCardDatasetError("visible-card result request must be an object")
    required = {
        "schema_version",
        "package_id",
        "frame_part_name",
        "target_offset_ms",
        "image_sha256",
        "image_mime_type",
        "width",
        "height",
        "provider",
        "api_version",
        "model",
        "prompt",
        "response_schema",
        "thinking_level",
        "prompt_sha256",
        "response_schema_sha256",
    }
    if set(request) != required:
        raise VisibleCardDatasetError("visible-card result request has unexpected fields")
    if request["schema_version"] != "visible-card-request/v1":
        raise VisibleCardDatasetError("unsupported visible-card result request schema")
    _identifier(request["package_id"], "request.package_id")
    _identifier(request["frame_part_name"], "request.frame_part_name")
    target_offset_ms = request["target_offset_ms"]
    if isinstance(target_offset_ms, bool) or not isinstance(target_offset_ms, int):
        raise VisibleCardDatasetError("request.target_offset_ms must be an integer")
    image_sha256 = _digest_value(request["image_sha256"], "request.image_sha256")
    if image_sha256 is None:
        raise VisibleCardDatasetError("request.image_sha256 is required")
    _positive_int(request["width"], "request.width")
    _positive_int(request["height"], "request.height")
    if not isinstance(request["prompt"], str) or not request["prompt"]:
        raise VisibleCardDatasetError("request.prompt must be non-empty")
    if not isinstance(request["response_schema"], dict):
        raise VisibleCardDatasetError("request.response_schema must be an object")
    if request["prompt_sha256"] != hashlib.sha256(request["prompt"].encode("utf-8")).hexdigest():
        raise VisibleCardDatasetError("request.prompt_sha256 does not match prompt")
    if request["response_schema_sha256"] != _digest(request["response_schema"]):
        raise VisibleCardDatasetError("request.response_schema_sha256 does not match schema")
    for field in ("provider", "api_version", "model", "thinking_level"):
        _text(request[field], f"request.{field}")
    request_digest = _digest(request)
    return request, request_digest


def _result_from_payload(
    payload: Mapping[str, Any], path: Path
) -> tuple[dict[str, Any], ProviderResult]:
    schema = payload.get("schema_version")
    if schema == RUN_SCHEMA_VERSION:
        validated = load_run_artifact(path)
        request, request_digest = _validate_request(validated["request"])
        result = ProviderResult.from_mapping(
            {
                field: validated[field]
                for field in (
                    "status",
                    "prediction",
                    "usage",
                    "latency_ms",
                    "retry_count",
                    "estimated_cost_usd",
                    "error",
                    "raw_response",
                )
            }
        )
        if validated["request_key"] != request_digest:
            raise VisibleCardDatasetError("visible-card run request key does not match request")
        return request, result
    if schema != CACHE_SCHEMA_VERSION:
        raise VisibleCardDatasetError("unsupported visible-card result schema")
    expected = {
        "schema_version",
        "request_key",
        "request",
        "prediction_schema_version",
        "status",
        "prediction",
        "usage",
        "latency_ms",
        "retry_count",
        "estimated_cost_usd",
        "error",
        "raw_response",
        "provider",
    }
    if set(payload) != expected:
        raise VisibleCardDatasetError("visible-card cache has unexpected fields")
    if payload["prediction_schema_version"] != PREDICTION_SCHEMA_VERSION:
        raise VisibleCardDatasetError("unsupported visible-card prediction schema")
    request, request_digest = _validate_request(payload["request"])
    if payload["request_key"] != request_digest:
        raise VisibleCardDatasetError("visible-card cache request key does not match request")
    result = ProviderResult.from_mapping(
        {
            field: payload[field]
            for field in (
                "status",
                "prediction",
                "usage",
                "latency_ms",
                "retry_count",
                "estimated_cost_usd",
                "error",
                "raw_response",
            )
        }
    )
    return request, result


def _load_result_index(
    results_root: Path,
) -> tuple[
    dict[tuple[str, str], list[_ResultArtifact]], dict[tuple[str, str], list[dict[str, str]]]
]:
    if results_root.is_file():
        paths = [results_root]
        root = results_root.parent
    else:
        if not results_root.is_dir():
            raise VisibleCardDatasetError(f"results root does not exist: {results_root}")
        paths = sorted(results_root.rglob("*.json"))
        root = results_root
    valid: dict[tuple[str, str], list[_ResultArtifact]] = defaultdict(list)
    invalid: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for path in paths:
        try:
            payload = _read_json(path, "visible-card result")
            request, result = _result_from_payload(payload, path)
            package_id = _identifier(request["package_id"], "request.package_id")
            frame_part_name = _identifier(request["frame_part_name"], "request.frame_part_name")
            artifact = _ResultArtifact(
                package_id=package_id,
                frame_part_name=frame_part_name,
                request_digest=_digest(request),
                image_sha256=request["image_sha256"],
                target_offset_ms=request["target_offset_ms"],
                provider=request["provider"],
                status=result.status,
                prediction=result.prediction,
                path=path,
                relative_path=_relative_path(path, root),
                digest=_file_digest(path),
            )
            valid[(package_id, frame_part_name)].append(artifact)
        except (OSError, TypeError, ValueError, VisibleCardError, VisibleCardDatasetError) as error:
            hint = _result_hint(path)
            if hint is not None:
                invalid[hint].append(
                    {
                        "relative_path": _relative_path(path, root),
                        "reason": str(error),
                        "digest": _file_digest(path),
                    }
                )
    return dict(valid), dict(invalid)


def _first_text(*values: Any, default: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return default


def _holdout_values(value: Any) -> set[str]:
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    if isinstance(value, dict):
        values: set[str] = set()
        for key in ("groups", "source_lineage_groups", "source_asset_ids", "sessions"):
            values.update(_holdout_values(value.get(key)))
        return values
    return set()


def _is_system_holdout(
    row: Mapping[str, Any], package: Mapping[str, Any], groups: set[str]
) -> bool:
    for value in (row, package):
        for key in ("system_holdout", "is_system_holdout", "holdout"):
            if value.get(key) is True:
                return True
        for key in ("allowed_use", "allowed_uses", "partition", "split", "intended_use"):
            candidate = value.get(key)
            if candidate == "system_holdout" or (
                isinstance(candidate, list) and "system_holdout" in candidate
            ):
                return True
    for value in (
        row.get("source_lineage_group"),
        row.get("source_asset_id"),
        row.get("session_id"),
    ):
        if isinstance(value, str) and value in groups:
            return True
    return False


def _pixel_point(value: int, size: int) -> float:
    return round(value * size / 1000.0, 6)


def _pixel_box(box: Mapping[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    x_min = max(0, min(width - 1, round(box["x_min"] * width / 1000.0)))
    y_min = max(0, min(height - 1, round(box["y_min"] * height / 1000.0)))
    x_max = max(x_min + 1, min(width, round(box["x_max"] * width / 1000.0)))
    y_max = max(y_min + 1, min(height, round(box["y_max"] * height / 1000.0)))
    if x_max <= x_min or y_max <= y_min:
        raise VisibleCardDatasetError("provider box becomes an empty pixel rectangle")
    return x_min, y_min, x_max, y_max


def _targets(prediction: VisibleCardPrediction, width: int, height: int) -> tuple[_Target, ...]:
    targets: list[_Target] = []
    for proposal in prediction.cards:
        box = proposal.box_2d.to_mapping()
        pixel_bbox = _pixel_box(box, width, height)
        segmentation = tuple(
            coordinate
            for point in proposal.polygon
            for coordinate in (_pixel_point(point.x, width), _pixel_point(point.y, height))
        )
        targets.append(
            _Target(
                normalized_box=box,
                pixel_bbox=pixel_bbox,
                segmentation=segmentation,
                side=proposal.side,
                provider_label=proposal.label,
            )
        )
    return tuple(targets)


def _package_candidate(
    row: Mapping[str, Any],
    *,
    evidence_root: Path,
    result_index: Mapping[tuple[str, str], list[_ResultArtifact]],
    invalid_results: Mapping[tuple[str, str], list[dict[str, str]]],
    holdout_groups: set[str],
) -> tuple[_Candidate | None, dict[str, Any] | None]:
    package_id_value = row.get("package_id")
    package_id = str(package_id_value) if package_id_value is not None else "<missing-package-id>"
    relative_path = row.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        return None, {"package_id": package_id, "reason": "missing_package_path"}
    package_path = (evidence_root / relative_path).resolve()
    if evidence_root.resolve() not in package_path.parents:
        return None, {"package_id": package_id, "reason": "package_path_escapes_evidence_root"}
    try:
        package = _read_json(package_path / "manifest.json", "evidence package manifest")
        if package.get("schema_version") != "cardevent-evidence/v2":
            raise VisibleCardDatasetError("unsupported evidence package schema")
        package_id = _identifier(row.get("package_id"), "package_id")
        event_type = _first_text(row.get("event_type"), default="card_played")
        if event_type != "card_played":
            raise VisibleCardDatasetError("event is not card_played")
        if _is_system_holdout(row, package, holdout_groups):
            raise VisibleCardDatasetError("system_holdout")
        package_event = package.get("event")
        if not isinstance(package_event, dict):
            raise VisibleCardDatasetError("evidence package event must be an object")
        if row.get("evidence_complete") is False or package_event.get("evidence_complete") is False:
            raise VisibleCardDatasetError("incomplete_evidence_package")
        frames = package.get("frames")
        if not isinstance(frames, list):
            raise VisibleCardDatasetError("evidence package frames must be a list")
        exact_frames = [
            frame
            for frame in frames
            if isinstance(frame, dict) and frame.get("target_offset_ms") == DEFAULT_TARGET_OFFSET_MS
        ]
        if len(exact_frames) != 1:
            raise VisibleCardDatasetError("missing_or_duplicate_exact_event_frame")
        frame = exact_frames[0]
        frame_part_name = _identifier(frame.get("part_name"), "frame.part_name")
        image_path = package_path / "frames" / f"{frame_part_name}.jpg"
        if not image_path.is_file():
            raise VisibleCardDatasetError("exact_event_frame_file_missing")
        image_sha256 = _file_digest(image_path)
        declared_frame_digest = _digest_value(frame.get("sha256"), "frame.sha256")
        if declared_frame_digest is not None and declared_frame_digest != image_sha256:
            raise VisibleCardDatasetError("exact_event_frame_digest_mismatch")
        width = _positive_int(frame.get("width"), "frame.width")
        height = _positive_int(frame.get("height"), "frame.height")
        event_time_ms = _non_negative_int(package_event.get("event_time_ms"), "event.event_time_ms")
        session = package.get("session")
        session_id = _first_text(
            row.get("session_id"),
            session.get("session_id") if isinstance(session, dict) else None,
            default=f"session:{package_id}",
        )
        source_video_sha256 = _digest_value(row.get("source_video_sha256"), "source_video_sha256")
        source_asset_id = _first_text(
            row.get("source_asset_id"),
            package.get("source_asset_id"),
            f"source-video:{source_video_sha256}" if source_video_sha256 else None,
            default=f"source-package:{package_id}",
        )
        source_lineage_group = _first_text(
            row.get("source_lineage_group"),
            package.get("source_lineage_group"),
            f"source-video:{source_video_sha256}" if source_video_sha256 else None,
            source_asset_id,
            session_id,
            default=f"source-package:{package_id}",
        )
        if source_lineage_group in holdout_groups or source_asset_id in holdout_groups:
            raise VisibleCardDatasetError("system_holdout")
        source_video_id = (
            _first_text(row.get("video_id"), package.get("video_id"), default="") or None
        )
        annotation_event_index = row.get("annotation_event_index")
        if annotation_event_index is not None:
            annotation_event_index = _non_negative_int(
                annotation_event_index, "annotation_event_index"
            )
        event_id = _first_text(
            row.get("event_id"),
            row.get("annotation_event_id"),
            f"{package_id}:card_played",
            default=f"{package_id}:card_played",
        )
        result_key = (package_id, frame_part_name)
        results = result_index.get(result_key, [])
        invalid = invalid_results.get(result_key, [])
        if len(results) != 1:
            if len(results) > 1:
                reason = "duplicate_gemini_results"
                details: dict[str, Any] = {"package_id": package_id, "reason": reason}
            elif invalid:
                details = {
                    "package_id": package_id,
                    "reason": "malformed_gemini_result",
                    "gemini_result": invalid[0],
                }
            else:
                details = {"package_id": package_id, "reason": "missing_gemini_result"}
            return None, details
        result = results[0]
        if result.status != "ok":
            return None, {
                "package_id": package_id,
                "reason": "gemini_result_unavailable",
                "gemini_request_digest": result.request_digest,
                "gemini_result_digest": result.digest,
                "gemini_result": result.relative_path,
            }
        if result.target_offset_ms != DEFAULT_TARGET_OFFSET_MS:
            return None, {
                "package_id": package_id,
                "reason": "gemini_result_target_offset_mismatch",
                "gemini_result": result.relative_path,
            }
        if result.image_sha256 != image_sha256:
            return None, {
                "package_id": package_id,
                "reason": "gemini_result_frame_digest_mismatch",
                "gemini_result": result.relative_path,
            }
        targets = _targets(result.prediction, width, height)
        return (
            _Candidate(
                package_id=package_id,
                frame_part_name=frame_part_name,
                frame_path=_relative_path(image_path, evidence_root),
                frame_sha256=image_sha256,
                width=width,
                height=height,
                source_asset_id=source_asset_id,
                source_asset_sha256=source_video_sha256,
                source_lineage_group=source_lineage_group,
                session_id=session_id,
                table_setup=_first_text(row.get("table_setup"), default="unknown"),
                deck_design=_first_text(
                    row.get("deck_design"), row.get("card_deck"), default="unknown"
                ),
                event_id=event_id,
                source_video_id=source_video_id,
                annotation_event_index=annotation_event_index,
                event_time_ms=event_time_ms,
                event_type=event_type,
                request_digest=result.request_digest,
                result_digest=result.digest,
                result_path=result.relative_path,
                provider=result.provider,
                targets=targets,
            ),
            None,
        )
    except (OSError, TypeError, ValueError, VisibleCardError, VisibleCardDatasetError) as error:
        reason = str(error)
        return None, {"package_id": package_id, "reason": reason}


def _select(candidates: list[_Candidate], config: VisibleCardDatasetConfig) -> list[_Candidate]:
    ordered = sorted(candidates, key=lambda item: item.frame_id)
    if len(ordered) < config.target_frame_count:
        raise VisibleCardDatasetError(
            f"only {len(ordered)} usable complete frames are available; "
            f"{config.target_frame_count} are required"
        )
    selected = ordered[: config.target_frame_count]
    index = config.target_frame_count

    def requirements_met() -> bool:
        groups = {item.source_lineage_group for item in selected}
        non_empty_groups = {item.source_lineage_group for item in selected if item.targets}
        return len(groups) >= 3 and len(non_empty_groups) >= 2

    while not requirements_met() and index < len(ordered) and len(selected) < config.max_frames:
        selected.append(ordered[index])
        index += 1
    groups = {item.source_lineage_group for item in selected}
    non_empty_groups = {item.source_lineage_group for item in selected if item.targets}
    if len(groups) < 3 or len(non_empty_groups) < 2:
        raise VisibleCardDatasetError(
            "the bounded slice cannot represent at least three source-lineage groups and "
            "non-empty pseudo-label examples in both splits within the frame cap "
            f"({len(selected)} selected, {len(groups)} groups, "
            f"{len(non_empty_groups)} non-empty groups)"
        )
    return selected


def _split(selected: list[_Candidate], seed: int) -> tuple[dict[str, str], dict[str, Any]]:
    groups = sorted({item.source_lineage_group for item in selected})
    non_empty_groups = sorted({item.source_lineage_group for item in selected if item.targets})
    validation_group = non_empty_groups[0]
    assignments = {
        item.frame_id: ("validation" if item.source_lineage_group == validation_group else "train")
        for item in selected
    }
    split = {
        "schema_version": VISIBLE_CARD_SPLIT_SCHEMA,
        "strategy": "source_lineage_group_first_validation_v1",
        "seed": seed,
        "group_key": "source_lineage_group",
        "groups": groups,
        "train": sorted(frame_id for frame_id, value in assignments.items() if value == "train"),
        "validation": sorted(
            frame_id for frame_id, value in assignments.items() if value == "validation"
        ),
    }
    split["split_digest"] = _digest(
        {key: value for key, value in split.items() if key != "split_digest"}
    )
    return assignments, split


def _target_mapping(target: _Target) -> dict[str, Any]:
    x_min, y_min, x_max, y_max = target.pixel_bbox
    return {
        "category": DEFAULT_TARGET_CLASS,
        "target_state": "unreviewed_pseudo_label",
        "normalized_box": target.normalized_box,
        "pixel_bbox": [x_min, y_min, x_max, y_max],
        "side": target.side,
        "provider_label": target.provider_label,
    }


def _manifest_frame(candidate: _Candidate, split: str) -> dict[str, Any]:
    return {
        "frame_id": candidate.frame_id,
        "package_id": candidate.package_id,
        "frame_part_name": candidate.frame_part_name,
        "file_name": candidate.frame_path,
        "source_asset_id": candidate.source_asset_id,
        "source_asset_sha256": candidate.source_asset_sha256,
        "source_lineage_group": candidate.source_lineage_group,
        "session_id": candidate.session_id,
        "table_setup": candidate.table_setup,
        "deck_design": candidate.deck_design,
        "event_id": candidate.event_id,
        "source_video_id": candidate.source_video_id,
        "annotation_event_index": candidate.annotation_event_index,
        "event_type": candidate.event_type,
        "event_time_ms": candidate.event_time_ms,
        "target_offset_ms": DEFAULT_TARGET_OFFSET_MS,
        "frame_sha256": candidate.frame_sha256,
        "width": candidate.width,
        "height": candidate.height,
        "gemini_request_digest": candidate.request_digest,
        "gemini_result_digest": candidate.result_digest,
        "gemini_result": candidate.result_path,
        "gemini_provider": candidate.provider,
        "split": split,
        "allowed_use": [split],
        "target_state": "unreviewed_pseudo_label",
        "review_state": "unreviewed",
        "review_id": None,
        "targets": [_target_mapping(target) for target in candidate.targets],
    }


def _coco(selected: list[_Candidate], assignments: Mapping[str, str]) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    annotation_id = 0
    for image_id, candidate in enumerate(selected, start=1):
        images.append(
            {
                "id": image_id,
                "file_name": candidate.frame_path,
                "width": candidate.width,
                "height": candidate.height,
                "sha256": candidate.frame_sha256,
                "source_frame_id": candidate.frame_id,
                "source_asset_id": candidate.source_asset_id,
                "split": assignments[candidate.frame_id],
            }
        )
        for target in candidate.targets:
            annotation_id += 1
            x_min, y_min, x_max, y_max = target.pixel_bbox
            annotations.append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "bbox": [x_min, y_min, x_max - x_min, y_max - y_min],
                    "area": (x_max - x_min) * (y_max - y_min),
                    "segmentation": [list(target.segmentation)],
                    "iscrowd": 0,
                    "target_state": "unreviewed_pseudo_label",
                    "gemini_request_digest": candidate.request_digest,
                    "gemini_result_digest": candidate.result_digest,
                }
            )
    return {
        "info": {
            "description": "DokoDetector visible-card detector pseudo-label view",
            "version": "visible-card-poc-v1",
            "coco_version": COCO_VERSION,
        },
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": DEFAULT_TARGET_CLASS, "supercategory": "card"}],
    }


def _stable_manifest_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": VISIBLE_CARD_DATASET_SCHEMA,
        "task": manifest["task"],
        "source_kind": manifest["source_kind"],
        "target_schema": manifest["target_schema"],
        "selection": manifest["selection"],
        "split": manifest["split"],
        "frames": manifest["frames"],
        "excluded": manifest["excluded"],
        "coco_digest": manifest["coco_digest"],
    }


def _recipe(
    config: VisibleCardDatasetConfig, dataset_digest: str, split_digest: str
) -> dict[str, Any]:
    recipe: dict[str, Any] = {
        "schema_version": VISIBLE_CARD_RECIPE_SCHEMA,
        "component": "visible-card-detector",
        "model_variant": DEFAULT_MODEL_VARIANT,
        "package": {"name": "rfdetr", "version": DEFAULT_RFDETR_VERSION},
        "pretrained_checkpoint": {
            "name": DEFAULT_CHECKPOINT_NAME,
            "sha256": None,
            "digest_state": "resolved_at_training_run",
        },
        "class_map": {"1": DEFAULT_TARGET_CLASS},
        "input_size": [DEFAULT_INPUT_SIZE, DEFAULT_INPUT_SIZE],
        "preprocessing": "rfdetr_standard_704_v1",
        "device": "cuda:0",
        "seed": config.seed,
        "epochs": config.epochs,
        "confidence_threshold": config.confidence_threshold,
        "non_maximum_suppression": False,
        "augmentation": "rfdetr_default_v1",
        "dataset_digest": dataset_digest,
        "split_digest": split_digest,
        "target_schema": "visible-card-bbox/v1",
        "target_state": "unreviewed_pseudo_label",
    }
    recipe["recipe_digest"] = _digest(recipe)
    return recipe


def materialize_visible_card_dataset(config: VisibleCardDatasetConfig) -> dict[str, Any]:
    """Materialize one deterministic, bounded COCO pseudo-label view."""

    evidence_root = config.evidence_root.expanduser().resolve()
    if not evidence_root.is_dir():
        raise VisibleCardDatasetError(f"evidence root does not exist: {evidence_root}")
    extraction_path = evidence_root / "extraction-manifest.json"
    extraction = _read_json(extraction_path, "annotation evidence extraction manifest")
    if extraction.get("schema_version") != "annotation-evidence-extraction/v1":
        raise VisibleCardDatasetError("unsupported annotation evidence extraction schema")
    packages = extraction.get("packages")
    if not isinstance(packages, list) or not packages:
        raise VisibleCardDatasetError("extraction manifest packages must be a non-empty list")
    holdout_groups = _holdout_values(extraction.get("system_holdout_groups"))
    if config.system_holdout is not None:
        holdout_groups.update(
            _holdout_values(_read_json(config.system_holdout, "system holdout manifest"))
        )
    result_index, invalid_results = _load_result_index(config.results_root.expanduser().resolve())
    candidates: list[_Candidate] = []
    excluded: list[dict[str, Any]] = []
    for row in packages:
        if not isinstance(row, Mapping):
            excluded.append({"package_id": "<invalid-row>", "reason": "invalid_package_row"})
            continue
        candidate, exclusion = _package_candidate(
            row,
            evidence_root=evidence_root,
            result_index=result_index,
            invalid_results=invalid_results,
            holdout_groups=holdout_groups,
        )
        if candidate is not None:
            candidates.append(candidate)
        elif exclusion is not None:
            excluded.append(exclusion)
    selected = _select(candidates, config)
    assignments, split = _split(selected, config.seed)
    frames = [_manifest_frame(candidate, assignments[candidate.frame_id]) for candidate in selected]
    coco = _coco(selected, assignments)
    coco_digest = _digest(coco)
    stable = {
        "schema_version": VISIBLE_CARD_DATASET_SCHEMA,
        "task": "table_evidence_visible_card_detection",
        "source_kind": "exact_event_cached_gemini",
        "target_schema": "visible-card-bbox/v1",
        "selection": {
            "target_offset_ms": DEFAULT_TARGET_OFFSET_MS,
            "target_frame_count": config.target_frame_count,
            "selected_frame_count": len(selected),
            "hard_cap": config.max_frames,
            "selection_order": "frame_id_lexicographic_v1",
        },
        "split": split,
        "frames": frames,
        "excluded": sorted(excluded, key=lambda value: (str(value.get("package_id")), str(value))),
        "coco_digest": coco_digest,
    }
    manifest: dict[str, Any] = {
        **stable,
        "label_state": "unreviewed_pseudo_label",
        "review_state": "unreviewed",
        "reference_contract": "not_reviewed_reference",
        "review_id": None,
        "extraction_manifest_sha256": _file_digest(extraction_path),
        "result_artifact_count": sum(len(values) for values in result_index.values()),
        "dataset_digest": _digest(stable),
        "split_digest": split["split_digest"],
    }
    recipe = _recipe(config, manifest["dataset_digest"], manifest["split_digest"])
    manifest["recipe_digest"] = recipe["recipe_digest"]
    output_dir = config.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise VisibleCardDatasetError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.", dir=output_dir.parent
    ) as temporary:
        working = Path(temporary)
        _write_json(working / "dataset-manifest.json", manifest)
        _write_json(working / "annotations.json", coco)
        _write_json(working / "split.json", split)
        _write_json(working / "recipe.json", recipe)
        working.replace(output_dir)
    return {
        "status": "completed",
        "output_dir": str(output_dir),
        "dataset_manifest": str(output_dir / "dataset-manifest.json"),
        "coco_annotations": str(output_dir / "annotations.json"),
        "recipe": str(output_dir / "recipe.json"),
        "dataset_digest": manifest["dataset_digest"],
        "coco_digest": coco_digest,
        "split_digest": manifest["split_digest"],
        "recipe_digest": recipe["recipe_digest"],
        "selected_frame_count": len(selected),
        "annotation_count": len(coco["annotations"]),
        "empty_pseudo_label_frame_count": sum(not candidate.targets for candidate in selected),
        "excluded_count": len(excluded),
        "train_frame_count": len(split["train"]),
        "validation_frame_count": len(split["validation"]),
    }


def load_visible_card_dataset_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate a materialized pseudo-label manifest."""

    manifest_path = Path(path)
    manifest = _read_json(manifest_path, "visible-card dataset manifest")
    if manifest.get("schema_version") != VISIBLE_CARD_DATASET_SCHEMA:
        raise VisibleCardDatasetError("unsupported visible-card dataset schema")
    if (
        manifest.get("label_state") != "unreviewed_pseudo_label"
        or manifest.get("review_state") != "unreviewed"
    ):
        raise VisibleCardDatasetError(
            "visible-card dataset is not marked as unreviewed pseudo-label data"
        )
    if manifest.get("reference_contract") != "not_reviewed_reference":
        raise VisibleCardDatasetError(
            "pseudo-label dataset cannot use the reviewed reference contract"
        )
    expected = _digest(_stable_manifest_payload(manifest))
    if manifest.get("dataset_digest") != expected:
        raise VisibleCardDatasetError("visible-card dataset digest does not match its contents")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise VisibleCardDatasetError("visible-card dataset frames must be a non-empty list")
    frame_ids = [frame.get("frame_id") for frame in frames if isinstance(frame, dict)]
    if len(frame_ids) != len(frames) or len(frame_ids) != len(set(frame_ids)):
        raise VisibleCardDatasetError("visible-card dataset frame IDs must be unique")
    split = manifest.get("split")
    if not isinstance(split, dict) or manifest.get("split_digest") != split.get("split_digest"):
        raise VisibleCardDatasetError("visible-card dataset split digest is missing or stale")
    if split["split_digest"] != _digest(
        {key: value for key, value in split.items() if key != "split_digest"}
    ):
        raise VisibleCardDatasetError("visible-card dataset split digest does not match contents")
    train = split.get("train")
    validation = split.get("validation")
    if not isinstance(train, list) or not isinstance(validation, list):
        raise VisibleCardDatasetError("visible-card dataset split partitions must be lists")
    if set(train) & set(validation) or set(train) | set(validation) != set(frame_ids):
        raise VisibleCardDatasetError("visible-card dataset split does not cover its frames")
    frame_by_id = {frame["frame_id"]: frame for frame in frames}
    group_partitions: dict[str, str] = {}
    for frame_id, frame in frame_by_id.items():
        partition = frame.get("split")
        if partition not in {"train", "validation"}:
            raise VisibleCardDatasetError("visible-card dataset frame has an invalid split")
        if frame.get("allowed_use") != [partition]:
            raise VisibleCardDatasetError("visible-card dataset frame allowed_use is inconsistent")
        if frame.get("target_state") != "unreviewed_pseudo_label":
            raise VisibleCardDatasetError(
                "visible-card dataset target is not an unreviewed pseudo-label"
            )
        if frame.get("review_state") != "unreviewed" or frame.get("review_id") is not None:
            raise VisibleCardDatasetError("visible-card dataset frame has review state")
        group = frame.get("source_lineage_group")
        if not isinstance(group, str) or not group:
            raise VisibleCardDatasetError("visible-card dataset frame has no source-lineage group")
        previous = group_partitions.get(group)
        if previous is not None and previous != partition:
            raise VisibleCardDatasetError("a source-lineage group crosses dataset partitions")
        group_partitions[group] = partition
        if frame_id not in (train if partition == "train" else validation):
            raise VisibleCardDatasetError("visible-card dataset split disagrees with frame split")
    return manifest


def load_visible_card_recipe(path: str | Path) -> dict[str, Any]:
    """Load and validate the frozen detector recipe."""

    recipe = _read_json(Path(path), "visible-card detector recipe")
    if recipe.get("schema_version") != VISIBLE_CARD_RECIPE_SCHEMA:
        raise VisibleCardDatasetError("unsupported visible-card recipe schema")
    if recipe.get("recipe_digest") != _digest(
        {key: value for key, value in recipe.items() if key != "recipe_digest"}
    ):
        raise VisibleCardDatasetError("visible-card recipe digest does not match its contents")
    if recipe.get("model_variant") != DEFAULT_MODEL_VARIANT:
        raise VisibleCardDatasetError("recipe model variant is not RFDETRLarge")
    if recipe.get("package") != {"name": "rfdetr", "version": DEFAULT_RFDETR_VERSION}:
        raise VisibleCardDatasetError("recipe rfdetr package is not pinned to 1.9.4")
    checkpoint = recipe.get("pretrained_checkpoint")
    if not isinstance(checkpoint, dict) or checkpoint.get("name") != DEFAULT_CHECKPOINT_NAME:
        raise VisibleCardDatasetError("recipe checkpoint is not rf-detr-large.pth")
    return recipe


__all__ = [
    "COCO_VERSION",
    "DEFAULT_CHECKPOINT_NAME",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_EPOCHS",
    "DEFAULT_INPUT_SIZE",
    "DEFAULT_MAX_FRAMES",
    "DEFAULT_MODEL_VARIANT",
    "DEFAULT_RFDETR_VERSION",
    "DEFAULT_SEED",
    "DEFAULT_TARGET_FRAME_COUNT",
    "DEFAULT_TARGET_OFFSET_MS",
    "VISIBLE_CARD_DATASET_SCHEMA",
    "VISIBLE_CARD_RECIPE_SCHEMA",
    "VISIBLE_CARD_SPLIT_SCHEMA",
    "VisibleCardDatasetConfig",
    "VisibleCardDatasetError",
    "load_visible_card_dataset_manifest",
    "load_visible_card_recipe",
    "materialize_visible_card_dataset",
]
