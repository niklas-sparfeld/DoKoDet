"""Resumable batch execution for exact-event visible-card provider runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .visible_cards import (
    DEFAULT_MODEL,
    CachedVisibleCardProvider,
    FakeVisibleCardProvider,
    GeminiVisibleCardProvider,
    ProviderResult,
    VisibleCardError,
    VisibleCardRequest,
    build_request_from_image,
    load_run_artifact,
    write_overlay_svg,
    write_run_artifact,
)

VISIBLE_CARD_BATCH_SCHEMA = "visible-card-batch/v1"


@dataclass(frozen=True, slots=True)
class VisibleCardBatchConfig:
    """Inputs for a resumable batch of exact-event frame requests."""

    evidence_root: Path
    output_dir: Path
    cache_dir: Path
    provider: Literal["fake", "gemini"] = "fake"
    model: str = DEFAULT_MODEL
    timeout_s: float = 120.0
    max_retries: int = 2
    target_offset_ms: int = 0
    fake_prediction: Path | None = None
    overlay_dir: Path | None = None
    resume: bool = False

    def __post_init__(self) -> None:
        if self.provider not in {"fake", "gemini"}:
            raise VisibleCardError("provider must be fake or gemini")
        if not self.model:
            raise VisibleCardError("model must be a non-empty string")
        if isinstance(self.target_offset_ms, bool) or not isinstance(self.target_offset_ms, int):
            raise VisibleCardError("target_offset_ms must be an integer")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_extraction_manifest(root: Path) -> dict[str, Any]:
    path = root / "extraction-manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardError(f"could not read extraction manifest: {path}") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "annotation-evidence-extraction/v1"
    ):
        raise VisibleCardError("unsupported annotation evidence extraction manifest")
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        raise VisibleCardError("extraction manifest packages must be a non-empty list")
    return payload


def _frame_for_target(package_root: Path, target_offset_ms: int) -> dict[str, Any] | None:
    try:
        manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardError(
            f"could not read evidence package manifest: {package_root}"
        ) from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "cardevent-evidence/v2":
        raise VisibleCardError(f"unsupported evidence package manifest: {package_root}")
    frames = manifest.get("frames")
    if not isinstance(frames, list):
        raise VisibleCardError(f"evidence package frames must be a list: {package_root}")
    matches = [
        frame
        for frame in frames
        if isinstance(frame, dict) and frame.get("target_offset_ms") == target_offset_ms
    ]
    if len(matches) > 1:
        raise VisibleCardError(f"evidence package has duplicate target frame: {package_root}")
    return matches[0] if matches else None


def _provider(config: VisibleCardBatchConfig) -> Any:
    if config.provider == "fake":
        predictions: dict[str, Any] = {}
        if config.fake_prediction:
            value = json.loads(config.fake_prediction.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise VisibleCardError("fake prediction must be an object keyed by image digest")
            predictions = value
        return FakeVisibleCardProvider(predictions)
    return GeminiVisibleCardProvider.from_environment(
        timeout_s=config.timeout_s,
        max_retries=config.max_retries,
    )


def _result_path(output_dir: Path, package_id: str, frame_part_name: str) -> Path:
    return output_dir / "results" / f"{package_id}-{frame_part_name}.json"


def _valid_existing_result(path: Path, request: VisibleCardRequest) -> bool:
    if not path.is_file():
        return False
    try:
        return load_run_artifact(path)["request_key"] == request.request_key
    except (OSError, ValueError, VisibleCardError, json.JSONDecodeError):
        return False


def run_visible_card_batch(config: VisibleCardBatchConfig) -> dict[str, Any]:
    """Run one exact-event frame per package and preserve resumable state."""

    if not config.evidence_root.is_dir():
        raise VisibleCardError(f"evidence root does not exist: {config.evidence_root}")
    if config.output_dir.exists() and not config.resume:
        raise VisibleCardError(
            f"batch output already exists; pass resume=True to continue: {config.output_dir}"
        )
    extraction_manifest = _load_extraction_manifest(config.evidence_root)
    extraction_manifest_path = config.evidence_root / "extraction-manifest.json"
    provider = CachedVisibleCardProvider(_provider(config), config.cache_dir)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    if config.overlay_dir:
        config.overlay_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    skipped_count = 0
    status_counts: dict[str, int] = {"ok": 0, "unavailable": 0}
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    total_retries = 0
    packages = sorted(
        extraction_manifest["packages"], key=lambda package: package.get("package_id", "")
    )
    for package in packages:
        package_id = package.get("package_id")
        relative_path = package.get("relative_path")
        if not isinstance(package_id, str) or not isinstance(relative_path, str):
            failures.append({"package_id": str(package_id), "error": "invalid package row"})
            continue
        package_root = (config.evidence_root / relative_path).resolve()
        if config.evidence_root.resolve() not in package_root.parents:
            failures.append(
                {"package_id": package_id, "error": "package path escapes evidence root"}
            )
            continue
        try:
            frame = _frame_for_target(package_root, config.target_offset_ms)
            if frame is None:
                failures.append(
                    {"package_id": package_id, "error": "requested target frame is missing"}
                )
                continue
            frame_part_name = frame["part_name"]
            image_path = package_root / "frames" / f"{frame_part_name}.jpg"
            if not image_path.is_file():
                raise VisibleCardError(f"frame artifact is missing: {image_path}")
            request = build_request_from_image(
                image_path,
                package_id=package_id,
                frame_part_name=frame_part_name,
                target_offset_ms=config.target_offset_ms,
                width=frame["width"],
                height=frame["height"],
                model=config.model,
                provider=config.provider,
            )
            result_path = _result_path(config.output_dir, package_id, frame_part_name)
            if config.resume and _valid_existing_result(result_path, request):
                run = load_run_artifact(result_path)
                result = ProviderResult.from_mapping(
                    {
                        field: run[field]
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
                skipped_count += 1
            else:
                result = provider.propose(request)
                overlay = None
                if config.overlay_dir:
                    overlay_path = config.overlay_dir / f"{package_id}-{frame_part_name}.svg"
                    write_overlay_svg(request, result.prediction, overlay_path)
                    overlay = str(overlay_path)
                write_run_artifact(
                    request,
                    result,
                    result_path,
                    image=str(image_path),
                    overlay=overlay,
                )
            status_counts[result.status] += 1
            total_input_tokens += result.usage.input_tokens
            total_output_tokens += result.usage.output_tokens
            total_cost += result.estimated_cost_usd
            total_retries += result.retry_count
            results.append(
                {
                    "package_id": package_id,
                    "frame_part_name": frame_part_name,
                    "target_offset_ms": config.target_offset_ms,
                    "request_key": request.request_key,
                    "status": result.status,
                    "result": str(result_path),
                }
            )
        except (OSError, ValueError, VisibleCardError, json.JSONDecodeError) as error:
            failures.append({"package_id": package_id, "error": str(error)})
        _atomic_write_json(
            config.output_dir / "batch-state.json",
            {
                "schema_version": VISIBLE_CARD_BATCH_SCHEMA,
                "status": "in_progress",
                "processed_count": len(results) + len(failures),
                "package_count": len(packages),
            },
        )
    report = {
        "schema_version": VISIBLE_CARD_BATCH_SCHEMA,
        "status": "completed" if not failures else "completed_with_failures",
        "evidence_root": str(config.evidence_root),
        "extraction_manifest_sha256": _sha256_file(extraction_manifest_path),
        "target_offset_ms": config.target_offset_ms,
        "provider": config.provider,
        "model": config.model,
        "package_count": len(packages),
        "result_count": len(results),
        "failure_count": len(failures),
        "resumed_result_count": skipped_count,
        "status_counts": status_counts,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "estimated_cost_usd": round(total_cost, 10),
        "retry_count": total_retries,
        "results": sorted(results, key=lambda result: result["package_id"]),
        "failures": sorted(failures, key=lambda failure: failure["package_id"]),
    }
    _atomic_write_json(config.output_dir / "batch-report.json", report)
    _atomic_write_json(
        config.output_dir / "batch-state.json",
        {
            "schema_version": VISIBLE_CARD_BATCH_SCHEMA,
            "status": report["status"],
            "processed_count": len(results) + len(failures),
            "package_count": len(packages),
        },
    )
    return report


__all__ = [
    "VISIBLE_CARD_BATCH_SCHEMA",
    "VisibleCardBatchConfig",
    "run_visible_card_batch",
]
