"""Deterministic source-video ingestion and dataset indexing.

The ingestion boundary keeps source videos read-only.  It accepts injected probe,
fingerprint, and preview implementations so tests do not need a video codec or a
display server.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

from .manifest import MANIFEST_SCHEMA_VERSION, DatasetRecord, ManifestError
from .video import SUPPORTED_VIDEO_EXTENSIONS, VideoError, read_video_metadata

INGESTION_INDEX_SCHEMA_VERSION = "cardevent-ingestion-index/v1"
DEFAULT_NEAR_DUPLICATE_DISTANCE = 0.08
_INDEX_FIELDS = {
    "video_id",
    "source_relative_path",
    "byte_size",
    "sha256",
    "probe",
    "visual_fingerprint",
    "generated_assets",
    "duplicate_status",
    "duplicate_findings",
    "session_id",
    "game_id",
    "content_type",
    "source_permission",
}
_DUPLICATE_KINDS = frozenset({"exact", "near"})
_DUPLICATE_STATUSES = frozenset(
    {"unique", "exact_duplicate", "near_duplicate", "exact_and_near_duplicate"}
)


class IngestionError(ValueError):
    """Raised when source registration or an ingestion artifact is invalid."""


@dataclass(frozen=True, slots=True)
class VideoProbe:
    """Technical information measured from one complete source video."""

    width: int
    height: int
    frame_rate: float
    frame_count: int
    duration_s: float
    orientation: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise IngestionError("Probe width and height must be positive.")
        if not math.isfinite(self.frame_rate) or self.frame_rate <= 0.0:
            raise IngestionError("Probe frame_rate must be positive and finite.")
        if self.frame_count <= 0:
            raise IngestionError("Probe frame_count must be positive.")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0.0:
            raise IngestionError("Probe duration_s must be positive and finite.")
        if self.orientation not in {"portrait", "landscape", "square", "other"}:
            raise IngestionError(f"Unsupported probe orientation: {self.orientation}.")

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "frame_count": self.frame_count,
            "duration_s": self.duration_s,
            "orientation": self.orientation,
        }
        for key in sorted(self.metadata):
            value = self.metadata[key]
            if value is not None and isinstance(value, (str, int, float, bool)):
                result[key] = value
        return result


class VideoProber(Protocol):
    def probe(self, video_path: Path) -> VideoProbe:
        """Measure the complete source video."""


class VisualFingerprinter(Protocol):
    def fingerprint(self, video_path: Path) -> str:
        """Return a deterministic visual fingerprint."""


class PreviewGenerator(Protocol):
    def generate(
        self, video_path: Path, output_dir: Path, video_id: str
    ) -> Mapping[str, str | Path]:
        """Write optional derived assets and return artifact-relative paths."""


class OpenCVVideoProber:
    """Probe technical video fields with OpenCV.

    OpenCV does not expose all container capture tags. When those tags are
    available through another probe, pass them through ``VideoProbe.metadata``.
    """

    def probe(self, video_path: Path) -> VideoProbe:
        try:
            metadata = read_video_metadata(video_path)
        except (RuntimeError, VideoError) as exc:
            raise IngestionError(str(exc)) from exc
        orientation = _orientation(metadata.width, metadata.height)
        return VideoProbe(
            width=metadata.width,
            height=metadata.height,
            frame_rate=metadata.fps,
            frame_count=metadata.frame_count,
            duration_s=metadata.duration_s,
            orientation=orientation,
        )


class OpenCVVisualFingerprinter:
    """Create a compact average-hash fingerprint from eight fixed frame positions."""

    sample_count = 8
    hash_width = 16
    hash_height = 16

    def fingerprint(self, video_path: Path) -> str:
        try:
            import cv2
            import numpy as np
        except ModuleNotFoundError as exc:
            raise IngestionError(
                "OpenCV and NumPy are required for visual duplicate detection."
            ) from exc

        capture = cv2.VideoCapture(str(video_path))
        try:
            if not capture.isOpened():
                raise IngestionError(f"OpenCV could not open source video: {video_path}")
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count <= 0:
                raise IngestionError(f"Source video has no frames: {video_path}")
            positions = _sample_positions(frame_count, self.sample_count)
            hashes: list[str] = []
            for position in positions:
                capture.set(cv2.CAP_PROP_POS_FRAMES, position)
                ok, frame = capture.read()
                if not ok or frame is None:
                    raise IngestionError(
                        f"Could not read fingerprint frame {position} from {video_path}."
                    )
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(
                    gray,
                    (self.hash_width, self.hash_height),
                    interpolation=cv2.INTER_AREA,
                )
                average = float(np.mean(small))
                bits = "".join("1" if value >= average else "0" for value in small.flat)
                hashes.append(f"{int(bits, 2):0{len(bits) // 4}x}")
            return ".".join(hashes)
        finally:
            capture.release()


class OpenCVPreviewGenerator:
    """Write a small source thumbnail and a contact sheet without a GUI."""

    def generate(self, video_path: Path, output_dir: Path, video_id: str) -> Mapping[str, str]:
        try:
            import cv2
            import numpy as np
        except ModuleNotFoundError as exc:
            raise IngestionError("OpenCV and NumPy are required for preview generation.") from exc

        capture = cv2.VideoCapture(str(video_path))
        frames: list[Any] = []
        try:
            if not capture.isOpened():
                raise IngestionError(f"OpenCV could not open source video: {video_path}")
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count <= 0:
                raise IngestionError(f"Source video has no frames: {video_path}")
            for position in _sample_positions(frame_count, 8):
                capture.set(cv2.CAP_PROP_POS_FRAMES, position)
                ok, frame = capture.read()
                if ok and frame is not None:
                    frames.append(frame)
        finally:
            capture.release()
        if not frames:
            raise IngestionError(f"Could not read preview frames from {video_path}.")

        thumbnail_dir = output_dir / "thumbnails"
        contact_sheet_dir = output_dir / "contact-sheets"
        thumbnail_path = thumbnail_dir / f"{video_id}.jpg"
        contact_sheet_path = contact_sheet_dir / f"{video_id}.jpg"
        thumbnail = _resize_preview(cv2, frames[0], width=320)
        columns = 4
        rows = (len(frames) + columns - 1) // columns
        tiles = [_resize_preview(cv2, frame, width=320) for frame in frames]
        tile_height = max(tile.shape[0] for tile in tiles)
        tile_width = max(tile.shape[1] for tile in tiles)
        sheet = np.zeros((rows * tile_height, columns * tile_width, 3), dtype=np.uint8)
        for index, tile in enumerate(tiles):
            row, column = divmod(index, columns)
            height, width = tile.shape[:2]
            sheet[
                row * tile_height : row * tile_height + height,
                column * tile_width : column * tile_width + width,
            ] = tile
        _write_image_atomic(cv2, thumbnail_path, thumbnail)
        _write_image_atomic(cv2, contact_sheet_path, sheet)
        return {
            "thumbnail": _relative_asset_path(output_dir, thumbnail_path),
            "contact_sheet": _relative_asset_path(output_dir, contact_sheet_path),
        }


@dataclass(frozen=True, slots=True)
class IngestionResult:
    manifest_path: Path
    index_path: Path
    dataset_version_digest: str
    records: tuple[DatasetRecord, ...]
    index: Mapping[str, Any]


def _orientation(width: int, height: int) -> str:
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def _sample_positions(frame_count: int, sample_count: int) -> tuple[int, ...]:
    if frame_count <= 1:
        return (0,)
    return tuple(
        min(frame_count - 1, round(index * (frame_count - 1) / (sample_count - 1)))
        for index in range(sample_count)
    )


def _resize_preview(cv2: Any, frame: Any, *, width: int) -> Any:
    height, source_width = frame.shape[:2]
    target_height = max(1, round(height * width / source_width))
    return cv2.resize(frame, (width, target_height), interpolation=cv2.INTER_AREA)


def _write_image_atomic(cv2: Any, path: Path, image: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=path.suffix, prefix=f".{path.name}.", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        if not cv2.imwrite(str(temporary_path), image):
            raise IngestionError(f"Could not write generated preview: {path}")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _relative_asset_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _call_probe(prober: VideoProber | Callable[[Path], VideoProbe], path: Path) -> VideoProbe:
    result = prober.probe(path) if hasattr(prober, "probe") else prober(path)
    if not isinstance(result, VideoProbe):
        raise IngestionError("The injected probe must return VideoProbe.")
    return result


def _call_fingerprint(
    fingerprinter: VisualFingerprinter | Callable[[Path], str], path: Path
) -> str:
    result = (
        fingerprinter.fingerprint(path)
        if hasattr(fingerprinter, "fingerprint")
        else fingerprinter(path)
    )
    if not isinstance(result, str) or not result:
        raise IngestionError("The injected fingerprinter must return a non-empty string.")
    return result


def _call_preview(
    generator: PreviewGenerator | Callable[[Path, Path, str], Mapping[str, str | Path]],
    source_path: Path,
    output_dir: Path,
    video_id: str,
) -> Mapping[str, str]:
    result = (
        generator.generate(source_path, output_dir, video_id)
        if hasattr(generator, "generate")
        else generator(source_path, output_dir, video_id)
    )
    if not isinstance(result, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, (str, Path))
        for key, value in result.items()
    ):
        raise IngestionError("The injected preview generator must return string paths.")
    return {key: str(value) for key, value in sorted(result.items())}


def discover_videos(source_dir: str | Path) -> tuple[Path, ...]:
    """Discover supported videos in stable relative-path order."""

    root = Path(source_dir).expanduser()
    if not root.is_dir():
        raise IngestionError(f"Source directory does not exist: {root}")
    paths = tuple(
        sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.casefold() in SUPPORTED_VIDEO_EXTENSIONS
            ),
            key=lambda path: (
                path.relative_to(root).as_posix().casefold(),
                path.relative_to(root).as_posix(),
            ),
        )
    )
    stems: dict[str, Path] = {}
    for path in paths:
        key = path.stem.casefold()
        if key in stems:
            raise IngestionError(
                "Video files have a case-insensitive stem collision: "
                f"{stems[key].name} and {path.name}."
            )
        stems[key] = path
    return paths


def _load_operator_metadata(
    source: str | Path | Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if isinstance(source, (str, Path)):
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise IngestionError("PyYAML is required to read operator metadata.") from exc
        try:
            data = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
        except (OSError, TypeError, yaml.YAMLError) as exc:
            raise IngestionError(f"Could not read operator metadata: {exc}") from exc
    else:
        data = source

    defaults: dict[str, Any] = {}
    rows: list[Mapping[str, Any]] = []
    if isinstance(data, Mapping):
        raw_defaults = data.get("defaults", {})
        if not isinstance(raw_defaults, Mapping):
            raise IngestionError("Operator metadata defaults must be a mapping.")
        defaults = dict(raw_defaults)
        raw_videos = data.get("videos", data.get("records", []))
        if isinstance(raw_videos, Mapping):
            for key, value in raw_videos.items():
                if not isinstance(value, Mapping):
                    raise IngestionError("Each operator video record must be a mapping.")
                record = dict(value)
                record.setdefault("video_id", str(key))
                rows.append(record)
        elif isinstance(raw_videos, list):
            rows = raw_videos
        elif raw_videos not in (None, []):
            raise IngestionError("Operator metadata videos must be a mapping or list.")
    elif isinstance(data, list):
        rows = data
    else:
        raise IngestionError("Operator metadata must be a mapping or list.")

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise IngestionError("Each operator video record must be a mapping.")
        record = dict(row)
        key = record.get("video_id") or record.get("file_name")
        if not isinstance(key, str) or not key:
            raise IngestionError("Each operator video record needs video_id or file_name.")
        lookup = Path(key).stem.casefold()
        if lookup in result:
            raise IngestionError(f"Duplicate operator metadata record: {key}.")
        result[lookup] = record
    return defaults, result


def _operator_record(
    path: Path,
    source_root: Path,
    defaults: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    video_id = path.stem
    relative = path.relative_to(source_root).as_posix()
    metadata = records.get(video_id.casefold())
    if metadata is None:
        metadata = records.get(relative.casefold()) or records.get(path.name.casefold())
    if metadata is None and not defaults:
        raise IngestionError(
            f"Operator metadata is missing for {relative}; add a record for {video_id}."
        )
    merged = dict(defaults)
    if metadata is not None:
        merged.update(metadata)
    merged["video_id"] = video_id
    merged["file_name"] = path.name
    for key in (
        "content_type",
        "session_id",
        "game_id",
        "recording_date",
        "device",
        "camera",
        "resolution",
        "frame_rate",
        "duration_s",
        "orientation",
        "camera_view",
        "camera_motion",
        "camera_framing",
        "table_setup",
        "background",
        "card_deck",
        "source",
        "annotation_version",
        "source_permission",
        "notes",
    ):
        merged.setdefault(key, None)
    for key in ("lighting", "scenario_tags", "known_limitations"):
        merged.setdefault(key, [])
    return merged


def _merge_probe(record: dict[str, Any], probe: VideoProbe) -> dict[str, Any]:
    technical = {
        "resolution": f"{probe.width}x{probe.height}",
        "frame_rate": probe.frame_rate,
        "duration_s": probe.duration_s,
        "orientation": probe.orientation,
    }
    for key, value in probe.metadata.items():
        if key in {"recording_date", "device", "camera"}:
            technical[key] = value
    record.update(technical)
    return record


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dataset_version_digest(
    records: Sequence[DatasetRecord], source_digests: Mapping[str, str]
) -> str:
    normalized = [
        {
            "record": record.to_mapping(),
            "sha256": source_digests[record.video_id],
        }
        for record in sorted(records, key=lambda item: item.video_id)
    ]
    payload = {"schema_version": MANIFEST_SCHEMA_VERSION, "videos": normalized}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise IngestionError(f"Could not read source video {path}: {exc}") from exc
    return digest.hexdigest()


def _visual_distance(first: str, second: str) -> float:
    if first == second:
        return 0.0
    hex_pattern = re.compile(r"^[0-9a-fA-F]+(?:\.[0-9a-fA-F]+)*$")
    if hex_pattern.fullmatch(first) and hex_pattern.fullmatch(second):
        first_bits = "".join(f"{int(part, 16):0{len(part) * 4}b}" for part in first.split("."))
        second_bits = "".join(f"{int(part, 16):0{len(part) * 4}b}" for part in second.split("."))
        if len(first_bits) == len(second_bits):
            return (int(first_bits, 2) ^ int(second_bits, 2)).bit_count() / len(first_bits)
    return 1.0 - SequenceMatcher(None, first, second, autojunk=False).ratio()


def _duplicate_status(findings: Sequence[Mapping[str, Any]]) -> str:
    kinds = {str(item["kind"]) for item in findings}
    if not kinds:
        return "unique"
    if kinds == {"exact"}:
        return "exact_duplicate"
    if kinds == {"near"}:
        return "near_duplicate"
    return "exact_and_near_duplicate"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _ensure_output_safe(
    path: str | Path,
    source_root: Path,
    source_paths: Sequence[Path],
    annotation_dir: str | Path | None,
) -> Path:
    output = Path(path).expanduser()
    resolved = output.resolve()
    source_resolved = source_root.resolve()
    if resolved == source_resolved or source_resolved in resolved.parents:
        raise IngestionError(f"Output path must not be inside the source directory: {output}")
    if resolved in {source.resolve() for source in source_paths}:
        raise IngestionError(f"Output path must not replace a source video: {output}")
    if annotation_dir is not None:
        annotations = Path(annotation_dir).expanduser().resolve()
        if resolved == annotations or annotations in resolved.parents:
            raise IngestionError(
                f"Output path must not be inside the annotation directory: {output}"
            )
    return output


def _asset_paths_safe(
    assets: Mapping[str, str],
    artifact_dir: Path,
    source_root: Path,
    annotation_dir: str | Path | None,
) -> None:
    annotation_root = Path(annotation_dir).expanduser().resolve() if annotation_dir else None
    artifact_root = artifact_dir.resolve()
    for label, value in assets.items():
        asset = Path(value)
        resolved = asset.resolve() if asset.is_absolute() else (artifact_dir / asset).resolve()
        if not asset.is_absolute() and (
            resolved == artifact_root or artifact_root not in resolved.parents
        ):
            raise IngestionError(f"Generated asset {label} escapes the artifact directory.")
        if resolved == source_root.resolve() or source_root.resolve() in resolved.parents:
            raise IngestionError(f"Generated asset {label} would overwrite a source path.")
        if annotation_root is not None and (
            resolved == annotation_root or annotation_root in resolved.parents
        ):
            raise IngestionError(f"Generated asset {label} would overwrite an annotation path.")


def _normalise_assets(assets: Mapping[str, str], artifact_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in sorted(assets.items()):
        asset = Path(value)
        if asset.is_absolute():
            try:
                asset = asset.resolve().relative_to(artifact_dir.resolve())
            except ValueError as exc:
                raise IngestionError(
                    f"Generated asset path must be inside the artifact directory: {value}"
                ) from exc
        result[key] = asset.as_posix()
    return result


def ingest_dataset(
    source_dir: str | Path,
    operator_metadata: str | Path | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    manifest_path: str | Path,
    index_path: str | Path,
    *,
    artifact_dir: str | Path | None = None,
    annotation_dir: str | Path | None = None,
    prober: VideoProber | Callable[[Path], VideoProbe] | None = None,
    fingerprinter: VisualFingerprinter | Callable[[Path], str] | None = None,
    preview_generator: PreviewGenerator
    | Callable[[Path, Path, str], Mapping[str, str | Path]]
    | None = None,
    near_duplicate_distance: float = DEFAULT_NEAR_DUPLICATE_DISTANCE,
) -> IngestionResult:
    """Register source videos and atomically write a V1 manifest and index."""

    if not math.isfinite(near_duplicate_distance) or not 0.0 <= near_duplicate_distance <= 1.0:
        raise IngestionError("near_duplicate_distance must be between 0 and 1.")
    source_root = Path(source_dir).expanduser()
    paths = discover_videos(source_root)
    if not paths:
        raise IngestionError(f"Source directory contains no supported videos: {source_root}")
    if annotation_dir is None:
        sibling_annotations = source_root.parent / "annotations"
        if sibling_annotations.is_dir():
            annotation_dir = sibling_annotations
    output_manifest = _ensure_output_safe(manifest_path, source_root, paths, annotation_dir)
    output_index = _ensure_output_safe(index_path, source_root, paths, annotation_dir)
    if output_manifest.resolve() == output_index.resolve():
        raise IngestionError("Manifest and ingestion index paths must be different.")
    output_artifact = None
    if artifact_dir is not None:
        output_artifact = Path(artifact_dir).expanduser()
        output_artifact = _ensure_output_safe(output_artifact, source_root, paths, annotation_dir)

    defaults, operator_records = _load_operator_metadata(operator_metadata)
    source_stems = {path.stem.casefold() for path in paths}
    unmatched = set(operator_records) - source_stems
    if unmatched:
        raise IngestionError(
            f"Operator metadata has no matching source video for: {', '.join(sorted(unmatched))}."
        )
    actual_prober = prober or OpenCVVideoProber()
    actual_fingerprinter = fingerprinter or OpenCVVisualFingerprinter()
    actual_preview_generator = preview_generator or OpenCVPreviewGenerator()
    records: list[DatasetRecord] = []
    source_digests: dict[str, str] = {}
    index_rows: list[dict[str, Any]] = []

    for path in paths:
        video_id = path.stem
        probe = _call_probe(actual_prober, path)
        merged = _merge_probe(
            _operator_record(path, source_root, defaults, operator_records), probe
        )
        try:
            record = DatasetRecord.from_mapping(merged, require_complete=True)
        except ManifestError as exc:
            raise IngestionError(f"Invalid metadata for {video_id}: {exc}") from exc
        source_digest = _sha256(path)
        fingerprint = _call_fingerprint(actual_fingerprinter, path)
        source_digests[video_id] = source_digest
        assets: Mapping[str, str] = {}
        if output_artifact is not None:
            assets = _call_preview(actual_preview_generator, path, output_artifact, video_id)
            _asset_paths_safe(assets, output_artifact, source_root, annotation_dir)
            assets = _normalise_assets(assets, output_artifact)
        index_rows.append(
            {
                "video_id": video_id,
                "source_relative_path": path.relative_to(source_root).as_posix(),
                "byte_size": path.stat().st_size,
                "sha256": source_digest,
                "probe": probe.to_mapping(),
                "visual_fingerprint": fingerprint,
                "generated_assets": dict(assets),
                "duplicate_status": "unique",
                "duplicate_findings": [],
                "session_id": record.session_id,
                "game_id": record.game_id,
                "content_type": record.content_type,
                "source_permission": record.source_permission,
            }
        )
        records.append(record)

    for index, row in enumerate(index_rows):
        findings: list[dict[str, Any]] = []
        for other_index, other in enumerate(index_rows):
            if index == other_index:
                continue
            if row["sha256"] == other["sha256"]:
                findings.append({"kind": "exact", "video_id": other["video_id"]})
            else:
                distance = _visual_distance(row["visual_fingerprint"], other["visual_fingerprint"])
                if distance <= near_duplicate_distance:
                    findings.append(
                        {
                            "kind": "near",
                            "video_id": other["video_id"],
                            "distance": round(distance, 12),
                        }
                    )
        row["duplicate_findings"] = sorted(
            findings,
            key=lambda item: (str(item["kind"]), str(item["video_id"]), item.get("distance", -1)),
        )
        row["duplicate_status"] = _duplicate_status(row["duplicate_findings"])

    records_tuple = tuple(sorted(records, key=lambda item: item.video_id))
    index_rows.sort(key=lambda item: item["video_id"])
    digest = dataset_version_digest(records_tuple, source_digests)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "videos": [record.to_mapping() for record in records_tuple],
    }
    index = {
        "schema_version": INGESTION_INDEX_SCHEMA_VERSION,
        "dataset_version_digest": digest,
        "videos": index_rows,
    }
    try:
        import yaml

        manifest_text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    except ModuleNotFoundError as exc:
        raise IngestionError("PyYAML is required to write the dataset manifest.") from exc
    _atomic_write(output_manifest, manifest_text)
    _atomic_write(output_index, json.dumps(index, indent=2, sort_keys=True) + "\n")
    return IngestionResult(output_manifest, output_index, digest, records_tuple, index)


def _validate_index_row(row: Any) -> None:
    if not isinstance(row, Mapping):
        raise IngestionError("Ingestion index videos must contain mappings.")
    unknown = set(row) - _INDEX_FIELDS
    if unknown:
        raise IngestionError(
            f"Ingestion index row has unknown fields: {', '.join(sorted(unknown))}."
        )
    required = _INDEX_FIELDS
    missing = required - set(row)
    if missing:
        raise IngestionError(
            f"Ingestion index row is missing fields: {', '.join(sorted(missing))}."
        )
    if not isinstance(row["video_id"], str) or not row["video_id"]:
        raise IngestionError("Ingestion index video_id must be a non-empty string.")
    for key in ("session_id", "content_type", "source_permission"):
        if not isinstance(row[key], str) or not row[key]:
            raise IngestionError(f"Ingestion index {key} must be a non-empty string.")
    if row.get("game_id") is not None and (
        not isinstance(row["game_id"], str) or not row["game_id"]
    ):
        raise IngestionError("Ingestion index game_id must be a non-empty string or null.")
    if not isinstance(row["source_relative_path"], str) or not row["source_relative_path"]:
        raise IngestionError("Ingestion index source_relative_path must be a non-empty string.")
    if not isinstance(row["byte_size"], int) or row["byte_size"] < 0:
        raise IngestionError("Ingestion index byte_size must be a non-negative integer.")
    if not isinstance(row["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None:
        raise IngestionError("Ingestion index sha256 must be a lowercase SHA-256 digest.")
    if not isinstance(row["probe"], Mapping):
        raise IngestionError("Ingestion index probe must be a mapping.")
    if not isinstance(row["visual_fingerprint"], str) or not row["visual_fingerprint"]:
        raise IngestionError("Ingestion index visual_fingerprint must be a non-empty string.")
    if not isinstance(row.get("generated_assets", {}), Mapping):
        raise IngestionError("Ingestion index generated_assets must be a mapping.")
    if row["duplicate_status"] not in _DUPLICATE_STATUSES:
        raise IngestionError(f"Unknown ingestion duplicate status: {row['duplicate_status']}.")
    findings = row.get("duplicate_findings", [])
    if not isinstance(findings, list):
        raise IngestionError("Ingestion index duplicate_findings must be a list.")
    for finding in findings:
        if not isinstance(finding, Mapping) or finding.get("kind") not in _DUPLICATE_KINDS:
            raise IngestionError("Ingestion duplicate findings must have kind exact or near.")
        if not isinstance(finding.get("video_id"), str) or not finding["video_id"]:
            raise IngestionError("Ingestion duplicate findings need a video_id.")


def load_ingestion_index(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionError(f"Could not read ingestion index: {exc}") from exc
    return validate_ingestion_index(data)


def validate_ingestion_index(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an ingestion-index object and return a shallow copy."""

    if not isinstance(data, Mapping):
        raise IngestionError("Ingestion index must contain a JSON object.")
    unknown = set(data) - {"schema_version", "dataset_version_digest", "videos"}
    if unknown:
        raise IngestionError(f"Ingestion index has unknown fields: {', '.join(sorted(unknown))}.")
    if data.get("schema_version") != INGESTION_INDEX_SCHEMA_VERSION:
        raise IngestionError(f"Unsupported ingestion index schema: {data.get('schema_version')}.")
    if (
        not isinstance(data.get("dataset_version_digest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", data["dataset_version_digest"]) is None
    ):
        raise IngestionError("Ingestion index needs dataset_version_digest.")
    videos = data.get("videos")
    if not isinstance(videos, list):
        raise IngestionError("Ingestion index videos must be a list.")
    for row in videos:
        _validate_index_row(row)
    if len({row["video_id"] for row in videos}) != len(videos):
        raise IngestionError("Ingestion index video_id values must be unique.")
    return dict(data)


def inspect_dataset(
    index_path: str | Path,
    *,
    video_id: str | Sequence[str] | None = None,
    session_id: str | Sequence[str] | None = None,
    game_id: str | Sequence[str] | None = None,
    content_type: str | Sequence[str] | None = None,
    source_permission: str | Sequence[str] | None = None,
    duplicate_status: str | Sequence[str] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return stable index rows matching the requested catalog filters."""

    index = load_ingestion_index(index_path)
    manifest_path = Path(index_path).with_name("manifest.yaml")
    manifest_by_id: dict[str, DatasetRecord] = {}
    if manifest_path.is_file():
        try:
            manifest_by_id = {record.video_id: record for record in _load_manifest(manifest_path)}
        except (IngestionError, ManifestError):
            manifest_by_id = {}

    def values(value: str | Sequence[str] | None) -> set[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return {value}
        return set(value)

    video_ids = values(video_id)
    sessions = values(session_id)
    games = values(game_id)
    content_types = values(content_type)
    permissions = values(source_permission)
    statuses = values(duplicate_status)
    if statuses is not None:
        statuses = {
            {"exact": "exact_duplicate", "near": "near_duplicate"}.get(status, status)
            for status in statuses
        }
    result: list[dict[str, Any]] = []
    for raw in index["videos"]:
        row = dict(raw)
        record = manifest_by_id.get(row["video_id"])
        if video_ids is not None and row["video_id"] not in video_ids:
            continue
        row_session = row.get("session_id") or (record.session_id if record else None)
        row_game = row.get("game_id") if "game_id" in row else (record.game_id if record else None)
        row_content_type = row.get("content_type") or (record.content_type if record else None)
        row_permission = row.get("source_permission") or (
            record.source_permission if record else None
        )
        if sessions is not None and row_session not in sessions:
            continue
        if games is not None and row_game not in games:
            continue
        if content_types is not None and row_content_type not in content_types:
            continue
        if permissions is not None and row_permission not in permissions:
            continue
        if statuses is not None:
            if "duplicate" in statuses:
                status_match = row["duplicate_status"] != "unique"
            else:
                status_match = row["duplicate_status"] in statuses
            if not status_match:
                continue
        result.append(row)
    return tuple(sorted(result, key=lambda row: row["video_id"]))


def _load_manifest(path: Path) -> tuple[DatasetRecord, ...]:
    from .manifest import load_dataset_manifest

    return load_dataset_manifest(path)


# Compatibility aliases for callers that prefer a verb-oriented name.
ingest_videos = ingest_dataset
