"""Run a paired development-only pilot for the visible-card request versions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .visible_cards import (
    DEFAULT_MODEL,
    IMPROVED_REQUEST_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
    CachedVisibleCardProvider,
    ProviderResult,
    VisibleCardError,
    VisibleCardProvider,
    build_request_from_image,
)

VISIBLE_CARD_PROMPT_PILOT_INPUT_SCHEMA = "visible-card-prompt-pilot-input/v1"
VISIBLE_CARD_PROMPT_PILOT_SCHEMA = "visible-card-prompt-pilot/v1"
DEVELOPMENT_PARTITION = "development"
EXCLUDED_SELECTION_PARTITIONS = (
    "validation",
    "challenge",
    "test",
    "system_holdout",
)
PILOT_REQUEST_VERSIONS = (REQUEST_SCHEMA_VERSION, IMPROVED_REQUEST_SCHEMA_VERSION)


class VisibleCardPromptPilotError(VisibleCardError, ValueError):
    """Raised when a paired prompt pilot is invalid or unsafe."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for character in value
        )
    ):
        raise VisibleCardPromptPilotError(f"{field} must be a simple non-empty identifier")
    return value


@dataclass(frozen=True, slots=True)
class PromptPilotFrame:
    """One development frame shared by both request versions."""

    package_id: str
    frame_part_name: str
    image: Path
    source_lineage_group: str
    partition: str = DEVELOPMENT_PARTITION
    target_offset_ms: int = 0
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.image, Path):
            raise VisibleCardPromptPilotError("image must be a filesystem path")
        _identifier(self.package_id, "package_id")
        _identifier(self.frame_part_name, "frame_part_name")
        _identifier(self.source_lineage_group, "source_lineage_group")
        if self.partition != DEVELOPMENT_PARTITION:
            raise VisibleCardPromptPilotError(
                "prompt selection is allowed only on development frames; "
                f"got partition {self.partition!r}"
            )
        if isinstance(self.target_offset_ms, bool) or not isinstance(self.target_offset_ms, int):
            raise VisibleCardPromptPilotError("target_offset_ms must be an integer")
        for value, field in ((self.width, "width"), (self.height, "height")):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise VisibleCardPromptPilotError(
                    f"{field} must be a positive integer when provided"
                )

    @property
    def frame_id(self) -> str:
        return f"{self.package_id}:{self.frame_part_name}:{self.target_offset_ms}"

    @classmethod
    def from_mapping(cls, value: Any, *, root: Path | None = None) -> "PromptPilotFrame":
        required = {
            "package_id",
            "frame_part_name",
            "image",
            "source_lineage_group",
            "partition",
            "target_offset_ms",
        }
        optional = {"width", "height"}
        if (
            not isinstance(value, dict)
            or set(value) - required - optional
            or not required <= set(value)
        ):
            raise VisibleCardPromptPilotError("prompt pilot frame has unexpected or missing fields")
        if not isinstance(value["image"], str) or not value["image"]:
            raise VisibleCardPromptPilotError("image must be a non-empty path")
        image = Path(value["image"])
        if root is not None and not image.is_absolute():
            image = root / image
        return cls(
            package_id=value["package_id"],
            frame_part_name=value["frame_part_name"],
            image=image,
            source_lineage_group=value["source_lineage_group"],
            partition=value["partition"],
            target_offset_ms=value["target_offset_ms"],
            width=value.get("width"),
            height=value.get("height"),
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "package_id": self.package_id,
            "frame_part_name": self.frame_part_name,
            "image": str(self.image),
            "source_lineage_group": self.source_lineage_group,
            "partition": self.partition,
            "target_offset_ms": self.target_offset_ms,
        }
        if self.width is not None:
            value["width"] = self.width
        if self.height is not None:
            value["height"] = self.height
        return value


def load_prompt_pilot_frames(path: str | Path) -> tuple[PromptPilotFrame, ...]:
    """Load the explicit development-frame manifest used by the pilot."""

    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardPromptPilotError(
            f"could not read prompt pilot manifest: {path}"
        ) from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "frames"}:
        raise VisibleCardPromptPilotError("prompt pilot manifest has unexpected fields")
    if payload["schema_version"] != VISIBLE_CARD_PROMPT_PILOT_INPUT_SCHEMA:
        raise VisibleCardPromptPilotError("unsupported prompt pilot manifest schema")
    frames = payload["frames"]
    if not isinstance(frames, list) or not frames:
        raise VisibleCardPromptPilotError("prompt pilot manifest needs at least one frame")
    parsed = tuple(
        PromptPilotFrame.from_mapping(value, root=manifest_path.parent) for value in frames
    )
    frame_ids = [frame.frame_id for frame in parsed]
    if len(frame_ids) != len(set(frame_ids)):
        raise VisibleCardPromptPilotError("prompt pilot frames must be unique")
    return parsed


def _provider_name(provider: VisibleCardProvider) -> str:
    current: Any = provider
    while isinstance(current, CachedVisibleCardProvider):
        current = current.provider
    name = getattr(current, "name", None)
    if not isinstance(name, str) or not name:
        raise VisibleCardPromptPilotError("provider must declare a name")
    return name


def _write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise VisibleCardPromptPilotError(f"prompt pilot report already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _result_mapping(result: ProviderResult) -> dict[str, Any]:
    mapping = result.to_mapping(include_raw_response=True)
    mapping["result_sha256"] = _digest(mapping)
    return mapping


def run_prompt_pilot(
    frames: tuple[PromptPilotFrame, ...] | list[PromptPilotFrame],
    provider: VisibleCardProvider,
    *,
    output: str | Path,
    selected_request_version: Literal["visible-card-request/v1", "visible-card-request/v2"]
    | None = None,
    selection_reason: str | None = None,
    run_id: str = "visible-card-prompt-pilot-v1",
    model: str = DEFAULT_MODEL,
    cache_dir: str | Path | None = None,
    expected_frame_count: int | None = None,
) -> dict[str, Any]:
    """Run both request versions on the same development frames and record a bounded selection."""

    _identifier(run_id, "run_id")
    if not frames:
        raise VisibleCardPromptPilotError("prompt pilot needs at least one frame")
    if expected_frame_count is not None and len(frames) != expected_frame_count:
        raise VisibleCardPromptPilotError(
            f"prompt pilot needs exactly {expected_frame_count} frames; got {len(frames)}"
        )
    if any(not isinstance(frame, PromptPilotFrame) for frame in frames):
        raise VisibleCardPromptPilotError("prompt pilot frames must use PromptPilotFrame")
    frame_ids = [frame.frame_id for frame in frames]
    if len(frame_ids) != len(set(frame_ids)):
        raise VisibleCardPromptPilotError("prompt pilot frames must be unique")
    for frame in frames:
        if frame.partition != DEVELOPMENT_PARTITION:
            raise VisibleCardPromptPilotError(
                "validation, challenge, test, and system-holdout frames cannot select a request"
            )
        if not frame.image.is_file():
            raise VisibleCardPromptPilotError(f"prompt pilot image does not exist: {frame.image}")
    if selected_request_version not in (*PILOT_REQUEST_VERSIONS, None):
        raise VisibleCardPromptPilotError(
            "selected_request_version is not one of the pilot versions"
        )
    if selection_reason is None or not selection_reason.strip():
        raise VisibleCardPromptPilotError(
            "selection_reason is required, including when no version is selected"
        )

    pilot_provider: VisibleCardProvider = provider
    if cache_dir is not None and not isinstance(provider, CachedVisibleCardProvider):
        pilot_provider = CachedVisibleCardProvider(provider, cache_dir)
    provider_name = _provider_name(provider)
    reports: list[dict[str, Any]] = []
    for frame in sorted(frames, key=lambda item: item.frame_id):
        version_reports: dict[str, Any] = {}
        for request_version in PILOT_REQUEST_VERSIONS:
            request = build_request_from_image(
                frame.image,
                package_id=frame.package_id,
                frame_part_name=frame.frame_part_name,
                target_offset_ms=frame.target_offset_ms,
                width=frame.width,
                height=frame.height,
                model=model,
                provider=provider_name,
                request_version=request_version,
            )
            result = pilot_provider.propose(request)
            version_reports[request_version] = {
                "request_key": request.request_key,
                "request": request.to_mapping(),
                "result": _result_mapping(result),
            }
        reports.append(
            {
                "frame_id": frame.frame_id,
                "package_id": frame.package_id,
                "frame_part_name": frame.frame_part_name,
                "target_offset_ms": frame.target_offset_ms,
                "image": str(frame.image),
                "source_lineage_group": frame.source_lineage_group,
                "partition": frame.partition,
                "request_versions": version_reports,
            }
        )
    report = {
        "schema_version": VISIBLE_CARD_PROMPT_PILOT_SCHEMA,
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "frame_count": len(reports),
        "request_versions": [
            {
                "schema_version": version,
                "prompt_sha256": reports[0]["request_versions"][version]["request"][
                    "prompt_sha256"
                ],
                "response_schema_sha256": reports[0]["request_versions"][version]["request"][
                    "response_schema_sha256"
                ],
                "prompt": reports[0]["request_versions"][version]["request"]["prompt"],
            }
            for version in PILOT_REQUEST_VERSIONS
        ],
        "frames": reports,
        "selection": {
            "selected_request_version": selected_request_version,
            "reason": selection_reason,
            "scope": DEVELOPMENT_PARTITION,
            "excluded_partitions": list(EXCLUDED_SELECTION_PARTITIONS),
        },
    }
    _write_json(Path(output), report)
    return report


__all__ = [
    "DEVELOPMENT_PARTITION",
    "EXCLUDED_SELECTION_PARTITIONS",
    "PILOT_REQUEST_VERSIONS",
    "PromptPilotFrame",
    "VISIBLE_CARD_PROMPT_PILOT_INPUT_SCHEMA",
    "VISIBLE_CARD_PROMPT_PILOT_SCHEMA",
    "VisibleCardPromptPilotError",
    "load_prompt_pilot_frames",
    "run_prompt_pilot",
]
