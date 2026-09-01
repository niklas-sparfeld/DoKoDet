"""Run a paired development-only pilot for the visible-card request versions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .visible_cards import (
    DEFAULT_MODEL,
    IMPROVED_REQUEST_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
    CachedVisibleCardProvider,
    ProviderResult,
    VisibleCardError,
    VisibleCardProvider,
    build_request_from_image,
    normalize_prediction,
)

VISIBLE_CARD_PROMPT_PILOT_INPUT_SCHEMA = "visible-card-prompt-pilot-input/v1"
VISIBLE_CARD_PROMPT_PILOT_SCHEMA = "visible-card-prompt-pilot/v1"
VISIBLE_CARD_PROMPT_PILOT_RENDER_SCHEMA = "visible-card-prompt-pilot-render/v1"
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


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise VisibleCardPromptPilotError(f"could not read source image: {path}") from error


def _digest_mapping(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VisibleCardPromptPilotError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _read_prompt_pilot_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardPromptPilotError(f"could not read prompt pilot report: {path}") from error
    if not isinstance(report, dict):
        raise VisibleCardPromptPilotError("prompt pilot report must be a JSON object")
    if report.get("schema_version") != VISIBLE_CARD_PROMPT_PILOT_SCHEMA:
        raise VisibleCardPromptPilotError("unsupported prompt pilot report schema")
    frame_count = report.get("frame_count")
    frames = report.get("frames")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
        raise VisibleCardPromptPilotError("prompt pilot report frame_count must be positive")
    if not isinstance(frames, list) or len(frames) != frame_count:
        raise VisibleCardPromptPilotError("prompt pilot report frame records are incomplete")
    if not isinstance(report.get("run_id"), str):
        raise VisibleCardPromptPilotError("prompt pilot report run_id is missing")
    request_versions = report.get("request_versions")
    if not isinstance(request_versions, list) or {
        item.get("schema_version") for item in request_versions if isinstance(item, dict)
    } != set(PILOT_REQUEST_VERSIONS):
        raise VisibleCardPromptPilotError("prompt pilot report must contain both request versions")
    return report


def _source_path(report_path: Path, value: Any, *, source_root: Path | None = None) -> Path:
    if not isinstance(value, str) or not value:
        raise VisibleCardPromptPilotError("prompt pilot frame image must be a non-empty path")
    image = Path(value)
    if image.is_absolute():
        return image
    if source_root is not None:
        rooted = source_root / image
        if rooted.is_file():
            return rooted
    if image.is_file():
        return image
    return report_path.parent / image


def _validated_pilot_frame(
    report_path: Path,
    frame: Any,
    *,
    source_root: Path | None = None,
) -> tuple[dict[str, Any], Path, bytes, dict[str, ProviderResult], dict[str, str]]:
    if not isinstance(frame, dict):
        raise VisibleCardPromptPilotError("prompt pilot frame must be an object")
    required = {
        "frame_id",
        "package_id",
        "frame_part_name",
        "target_offset_ms",
        "image",
        "source_lineage_group",
        "partition",
        "request_versions",
    }
    if set(frame) != required:
        raise VisibleCardPromptPilotError("prompt pilot frame has unexpected fields")
    if frame["partition"] != DEVELOPMENT_PARTITION:
        raise VisibleCardPromptPilotError("prompt pilot renderer accepts development frames only")
    expected_frame_id = (
        f"{frame['package_id']}:{frame['frame_part_name']}:{frame['target_offset_ms']}"
    )
    if frame["frame_id"] != expected_frame_id:
        raise VisibleCardPromptPilotError("prompt pilot frame_id does not match its frame fields")
    image_path = _source_path(report_path, frame["image"], source_root=source_root)
    if not image_path.is_file():
        raise VisibleCardPromptPilotError(f"prompt pilot source image does not exist: {image_path}")
    source_bytes = image_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    versions = frame["request_versions"]
    if not isinstance(versions, dict) or set(versions) != set(PILOT_REQUEST_VERSIONS):
        raise VisibleCardPromptPilotError("prompt pilot frame must contain both request versions")

    results: dict[str, ProviderResult] = {}
    request_digests: dict[str, str] = {}
    image_digests: set[str] = set()
    for version in PILOT_REQUEST_VERSIONS:
        version_record = versions[version]
        if not isinstance(version_record, dict) or set(version_record) != {
            "request_key",
            "request",
            "result",
        }:
            raise VisibleCardPromptPilotError(
                f"prompt pilot {version} record has unexpected fields"
            )
        request = version_record["request"]
        if not isinstance(request, dict):
            raise VisibleCardPromptPilotError(f"prompt pilot {version} request is invalid")
        request_key = version_record["request_key"]
        if not isinstance(request_key, str) or request_key != _digest(request):
            raise VisibleCardPromptPilotError(f"prompt pilot {version} request key is invalid")
        if request.get("schema_version") != version:
            raise VisibleCardPromptPilotError(f"prompt pilot {version} request version is invalid")
        for field, expected in (
            ("package_id", frame["package_id"]),
            ("frame_part_name", frame["frame_part_name"]),
            ("target_offset_ms", frame["target_offset_ms"]),
        ):
            if request.get(field) != expected:
                raise VisibleCardPromptPilotError(
                    f"prompt pilot {version} request does not match frame {field}"
                )
        image_sha256 = _digest_mapping(request.get("image_sha256"), f"{version} image_sha256")
        image_digests.add(image_sha256)
        request_digests[version] = request_key
        result_record = version_record["result"]
        if not isinstance(result_record, dict) or set(result_record) != {
            "status",
            "prediction",
            "usage",
            "latency_ms",
            "retry_count",
            "estimated_cost_usd",
            "error",
            "raw_response",
            "result_sha256",
        }:
            raise VisibleCardPromptPilotError(f"prompt pilot {version} result is invalid")
        result_sha256 = _digest_mapping(result_record["result_sha256"], f"{version} result_sha256")
        result_without_digest = {
            key: value for key, value in result_record.items() if key != "result_sha256"
        }
        if result_sha256 != _digest(result_without_digest):
            raise VisibleCardPromptPilotError(f"prompt pilot {version} result digest is invalid")
        try:
            result = ProviderResult.from_mapping(result_without_digest)
            if version == IMPROVED_REQUEST_SCHEMA_VERSION:
                normalize_prediction(result.prediction.to_mapping(), require_tight_boxes=True)
        except (TypeError, ValueError, VisibleCardError) as error:
            raise VisibleCardPromptPilotError(
                f"prompt pilot {version} result is invalid"
            ) from error
        results[version] = result

    if len(image_digests) != 1 or source_sha256 not in image_digests:
        raise VisibleCardPromptPilotError(
            "prompt pilot requests do not reference the same source image bytes"
        )
    try:
        with Image.open(BytesIO(source_bytes)) as source:
            width, height = source.size
    except (UnidentifiedImageError, OSError) as error:
        raise VisibleCardPromptPilotError(
            f"prompt pilot source image is not readable: {image_path}"
        ) from error
    for version in PILOT_REQUEST_VERSIONS:
        request = versions[version]["request"]
        if request.get("width") != width or request.get("height") != height:
            raise VisibleCardPromptPilotError(
                f"prompt pilot {version} request dimensions do not match source image"
            )
    return frame, image_path, source_bytes, results, request_digests


def _render_status(result: ProviderResult) -> tuple[str, tuple[int, int, int]]:
    if result.status == "unavailable":
        return "UNAVAILABLE", (145, 45, 45)
    if not result.proposals:
        return "EMPTY", (90, 90, 90)
    return "OK", (39, 119, 73)


def _safe_render_name(frame_id: str, index: int) -> str:
    name = "".join(
        character if character.isalnum() or character in "._-" else "-" for character in frame_id
    )
    return f"{index:04d}-{name}.png"


def _render_panel(
    source_bytes: bytes,
    *,
    request_version: str,
    provider: str,
    result: ProviderResult,
    frame_id: str,
) -> Image.Image:
    with Image.open(BytesIO(source_bytes)) as opened:
        source = opened.convert("RGB")
    source_width, source_height = source.size
    display_width = min(960, max(320, source_width))
    display_height = max(1, round(source_height * display_width / source_width))
    source = source.resize((display_width, display_height), Image.Resampling.LANCZOS)
    status, status_colour = _render_status(result)
    footer_lines = [
        f"provider: {provider}   status: {status}   proposals: {len(result.proposals)}",
    ]
    if result.status == "unavailable":
        footer_lines.append(f"error: {result.error or 'provider unavailable'}")
    elif not result.proposals:
        footer_lines.append("No visible-card proposals returned.")
    else:
        for index, proposal in enumerate(result.proposals, start=1):
            box = proposal.box_2d
            footer_lines.append(
                f"{index}. {proposal.label} ({proposal.side})  "
                f"box=[{box.x_min},{box.y_min},{box.x_max},{box.y_max}]"
            )
    font = ImageFont.load_default()
    footer_height = max(76, 24 + 22 * len(footer_lines))
    header_height = 76
    panel = Image.new(
        "RGB", (display_width, header_height + display_height + footer_height), (245, 245, 245)
    )
    header = ImageDraw.Draw(panel)
    header.rectangle((0, 0, display_width, header_height), fill=status_colour)
    header.text((16, 12), request_version, fill="white", font=font)
    header.text((16, 32), f"frame: {frame_id}", fill="white", font=font)
    header.text((16, 52), f"provider: {provider}   status: {status}", fill="white", font=font)

    overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    colours = {
        "face_up": (60, 190, 70, 255),
        "face_down": (40, 140, 240, 255),
        "unknown": (210, 90, 180, 255),
    }
    for index, proposal in enumerate(result.proposals, start=1):
        colour = colours[proposal.side]
        points = [
            (
                round(point.x * display_width / 1000),
                round(point.y * display_height / 1000),
            )
            for point in proposal.polygon
        ]
        draw.polygon(points, fill=(*colour[:3], 72))
        draw.line(points + [points[0]], fill=colour, width=4, joint="curve")
        box = proposal.box_2d
        box_points = (
            round(box.x_min * display_width / 1000),
            round(box.y_min * display_height / 1000),
            round(box.x_max * display_width / 1000),
            round(box.y_max * display_height / 1000),
        )
        draw.rectangle(box_points, outline=(255, 255, 255, 255), width=2)
        label = f"{index} {proposal.label}"
        label_x = max(2, min(box_points[0], display_width - 120))
        label_y = max(2, box_points[1] - 18)
        text_box = draw.textbbox((label_x, label_y), label, font=font)
        draw.rectangle(text_box, fill=(0, 0, 0, 190))
        draw.text((label_x, label_y), label, fill="white", font=font)
    panel.paste(
        Image.alpha_composite(source.convert("RGBA"), overlay).convert("RGB"),
        (0, header_height),
    )
    footer = ImageDraw.Draw(panel)
    footer_y = header_height + display_height + 12
    for line in footer_lines:
        footer.text((16, footer_y), line[:180], fill=(25, 25, 25), font=font)
        footer_y += 22
    return panel


def render_prompt_pilot(
    pilot_report: str | Path,
    output_dir: str | Path,
    *,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    """Render an immutable paired box-level review for one prompt pilot report."""

    report_path = Path(pilot_report)
    report = _read_prompt_pilot_report(report_path)
    destination = Path(output_dir)
    index_path = destination / "index.json"
    if index_path.exists():
        raise VisibleCardPromptPilotError(f"prompt pilot render index already exists: {index_path}")
    destination.mkdir(parents=True, exist_ok=True)
    frames_dir = destination / "frames"
    frames_dir.mkdir(exist_ok=True)
    source_root_path = Path(source_root) if source_root is not None else None
    rendered_frames: list[dict[str, Any]] = []
    for index, frame_record in enumerate(
        sorted(report["frames"], key=lambda item: item["frame_id"]), start=1
    ):
        frame, image_path, source_bytes, results, request_digests = _validated_pilot_frame(
            report_path, frame_record, source_root=source_root_path
        )
        versions = frame["request_versions"]
        provider_names = {
            versions[version]["request"]["provider"] for version in PILOT_REQUEST_VERSIONS
        }
        if len(provider_names) != 1:
            raise VisibleCardPromptPilotError("prompt pilot request providers must match")
        provider = next(iter(provider_names))
        panels = [
            _render_panel(
                source_bytes,
                request_version=version,
                provider=provider,
                result=results[version],
                frame_id=frame["frame_id"],
            )
            for version in PILOT_REQUEST_VERSIONS
        ]
        panel_gap = 16
        title_height = 42
        width = panels[0].width + panel_gap + panels[1].width
        height = title_height + max(panel.height for panel in panels)
        rendered = Image.new("RGB", (width, height), "white")
        title = ImageDraw.Draw(rendered)
        title.text(
            (16, 14),
            f"Paired visible-card prompt review · {frame['frame_id']} · source "
            f"{hashlib.sha256(source_bytes).hexdigest()[:12]}",
            fill=(25, 25, 25),
            font=ImageFont.load_default(),
        )
        rendered.paste(panels[0], (0, title_height))
        rendered.paste(panels[1], (panels[0].width + panel_gap, title_height))
        rendered_path = frames_dir / _safe_render_name(frame["frame_id"], index)
        if rendered_path.exists():
            raise VisibleCardPromptPilotError(
                f"prompt pilot rendered file already exists: {rendered_path}"
            )
        rendered.save(rendered_path, format="PNG", optimize=False, compress_level=9)
        result_records = {
            version: {
                "request_key": request_digests[version],
                "request_sha256": _digest(versions[version]["request"]),
                "result_sha256": versions[version]["result"]["result_sha256"],
                "status": results[version].status,
                "proposal_count": len(results[version].proposals),
            }
            for version in PILOT_REQUEST_VERSIONS
        }
        rendered_frames.append(
            {
                "frame_id": frame["frame_id"],
                "source": {
                    "path": str(image_path),
                    "frame_sha256": hashlib.sha256(source_bytes).hexdigest(),
                },
                "request_versions": result_records,
                "rendered_file": {
                    "path": str(rendered_path.relative_to(destination)),
                    "sha256": _file_digest(rendered_path),
                },
            }
        )
    index = {
        "schema_version": VISIBLE_CARD_PROMPT_PILOT_RENDER_SCHEMA,
        "artifact_role": "paired_box_level_prompt_review",
        "quality_claim": None,
        "creates_reviewed_reference_data": False,
        "pilot_report": {
            "path": str(report_path),
            "sha256": _file_digest(report_path),
            "schema_version": report["schema_version"],
            "run_id": report["run_id"],
        },
        "frame_count": len(rendered_frames),
        "frames": rendered_frames,
    }
    _write_json(index_path, index)
    return index


render_visible_card_prompt_pilot = render_prompt_pilot


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
    "VISIBLE_CARD_PROMPT_PILOT_RENDER_SCHEMA",
    "VISIBLE_CARD_PROMPT_PILOT_SCHEMA",
    "VisibleCardPromptPilotError",
    "load_prompt_pilot_frames",
    "render_prompt_pilot",
    "render_visible_card_prompt_pilot",
    "run_prompt_pilot",
]
