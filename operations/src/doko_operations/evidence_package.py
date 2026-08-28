"""Read and validate canonical evidence-package intake bundles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .intake_contract import (
    EvidencePackageBundle,
    EvidencePackageLineage,
    EvidencePackageRecord,
    IntakeContractError,
    parse_evidence_package_bundle,
    parse_evidence_package_lineage,
    parse_evidence_package_record,
    parse_json_bytes,
)


@dataclass(frozen=True, slots=True)
class EvidencePackageData:
    """Validated canonical package documents used by task adapters."""

    path: Path
    bundle: EvidencePackageBundle
    record: EvidencePackageRecord
    enrollment: Mapping[str, Any]
    lineage: EvidencePackageLineage
    evidence_manifest: Mapping[str, Any]

    @property
    def selected_tasks(self) -> frozenset[str]:
        return frozenset(
            item["task"]
            for item in self.enrollment["enrollments"]
            if item["disposition"] == "selected"
        )


def discover_evidence_package_paths(root: str | Path) -> tuple[Path, ...]:
    """Find canonical package directories below one read-only root."""

    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        return ()
    if root_path.is_file():
        return (root_path.parent,) if root_path.name == "manifest.json" else ()
    paths: set[Path] = set()
    for manifest_path in sorted(
        root_path.rglob("manifest.json"), key=lambda value: value.as_posix()
    ):
        if not manifest_path.is_file():
            continue
        paths.add(manifest_path.parent)
    return tuple(sorted(paths, key=lambda value: value.as_posix()))


def load_evidence_package(path: str | Path) -> EvidencePackageData:
    """Load one canonical package and verify every declared member."""

    package_path = Path(path).expanduser().resolve()
    bundle_bytes = (package_path / "manifest.json").read_bytes()
    bundle = parse_evidence_package_bundle(bundle_bytes)
    record_bytes = (package_path / "package-record.json").read_bytes()
    enrollment_bytes = (package_path / "initial-task-enrollment.json").read_bytes()
    lineage_bytes = (package_path / "lineage.json").read_bytes()
    evidence_manifest_bytes = (package_path / "evidence-manifest.json").read_bytes()
    record = parse_evidence_package_record(record_bytes)
    enrollment = _parse_task_enrollment(enrollment_bytes)
    lineage = parse_evidence_package_lineage(lineage_bytes)
    evidence_manifest = parse_json_bytes(evidence_manifest_bytes, "evidence manifest")

    if record.package_id != bundle.package_id or record.source_asset_id != bundle.source_asset_id:
        raise IntakeContractError("evidence package record identity differs from bundle")
    if enrollment.get("source_asset_id") != bundle.source_asset_id:
        raise IntakeContractError("task enrollment source_asset_id differs from bundle")
    if lineage.package_id != bundle.package_id:
        raise IntakeContractError("evidence package lineage identity differs from bundle")
    if evidence_manifest.get("schema_version") != "cardevent-evidence/v2":
        raise IntakeContractError("evidence manifest schema is unsupported")
    if evidence_manifest.get("package_id") != bundle.package_id:
        raise IntakeContractError("evidence manifest package_id differs from bundle")

    descriptors = [
        bundle.files.evidence_manifest,
        bundle.files.package_record,
        bundle.files.task_enrollment,
        bundle.files.lineage,
        *bundle.files.frames,
    ]
    if bundle.files.video_snippet is not None:
        descriptors.append(bundle.files.video_snippet)
    expected_paths = {
        "manifest.json",
        *(descriptor.relative_path for descriptor in descriptors),
    }
    actual_paths = {
        file_path.relative_to(package_path).as_posix()
        for file_path in package_path.rglob("*")
        if file_path.is_file()
    }
    if actual_paths != expected_paths:
        raise IntakeContractError("evidence package members contain an unexpected or missing file")
    values = {
        "evidence-manifest.json": evidence_manifest_bytes,
        "package-record.json": record_bytes,
        "initial-task-enrollment.json": enrollment_bytes,
        "lineage.json": lineage_bytes,
    }
    for descriptor in descriptors:
        value = values.get(descriptor.relative_path)
        if value is None:
            value = (package_path / descriptor.relative_path).read_bytes()
        if len(value) != descriptor.byte_length or _sha256(value) != descriptor.sha256:
            raise IntakeContractError(f"{descriptor.relative_path} bytes do not match descriptor")

    _verify_evidence_members(package_path, evidence_manifest, bundle)
    return EvidencePackageData(package_path, bundle, record, enrollment, lineage, evidence_manifest)


def _parse_task_enrollment(raw: bytes) -> Mapping[str, Any]:
    """Validate the shared two-task enrollment document."""

    value = parse_json_bytes(raw, "task enrollment")
    _strict(value, {"schema_version", "source_asset_id", "enrollments"}, "task enrollment")
    if value.get("schema_version") != "task-enrollment/v1":
        raise IntakeContractError("task enrollment schema is unsupported")
    enrollments = value.get("enrollments")
    if not isinstance(enrollments, list) or len(enrollments) != 2:
        raise IntakeContractError("task enrollment must contain two enrollments")
    tasks: set[str] = set()
    enrollment_ids: set[str] = set()
    for index, item in enumerate(enrollments):
        if not isinstance(item, Mapping):
            raise IntakeContractError(f"task enrollment {index} must be an object")
        _strict(
            item,
            {
                "task_enrollment_id",
                "task",
                "disposition",
                "lifecycle_state",
                "operator",
                "created_at_utc",
                "reason",
            },
            f"task enrollment {index}",
        )
        task = item.get("task")
        enrollment_id = item.get("task_enrollment_id")
        if task not in {"cardevent_event_detection", "table_evidence_analysis"}:
            raise IntakeContractError(f"task enrollment {index} task is invalid")
        if task in tasks or not isinstance(enrollment_id, str) or not enrollment_id:
            raise IntakeContractError("task enrollment tasks and IDs must be unique")
        tasks.add(task)
        if enrollment_id in enrollment_ids:
            raise IntakeContractError("task enrollment IDs must be unique")
        enrollment_ids.add(enrollment_id)
        if item.get("disposition") not in {"selected", "deferred", "excluded"}:
            raise IntakeContractError(f"task enrollment {index} disposition is invalid")
        if item.get("lifecycle_state") not in {
            "intake",
            "annotating",
            "review_required",
            "reviewed",
            "eligible",
            "excluded",
            "retired",
        }:
            raise IntakeContractError(f"task enrollment {index} lifecycle state is invalid")
        if not isinstance(item.get("operator"), str) or not item["operator"]:
            raise IntakeContractError(f"task enrollment {index} operator is invalid")
        created_at = item.get("created_at_utc")
        if not isinstance(created_at, str) or not created_at.endswith("Z"):
            raise IntakeContractError(f"task enrollment {index} timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(created_at[:-1] + "+00:00")
        except ValueError as error:
            raise IntakeContractError(f"task enrollment {index} timestamp is invalid") from error
        if parsed.utcoffset() != timedelta(0):
            raise IntakeContractError(f"task enrollment {index} timestamp is invalid")
    if tasks != {"cardevent_event_detection", "table_evidence_analysis"}:
        raise IntakeContractError("task enrollment must contain both data tasks")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise IntakeContractError(f"{context} has invalid fields")


def _verify_evidence_members(
    package_path: Path,
    evidence_manifest: Mapping[str, Any],
    bundle: EvidencePackageBundle,
) -> None:
    frames = evidence_manifest.get("frames")
    if not isinstance(frames, list):
        raise IntakeContractError("evidence manifest frames must be a list")
    expected_frames = {
        f"frames/{frame.get('part_name')}.jpg" for frame in frames if isinstance(frame, Mapping)
    }
    declared_frames = {descriptor.relative_path for descriptor in bundle.files.frames}
    if expected_frames != declared_frames:
        raise IntakeContractError("evidence package frames differ from evidence manifest")
    for descriptor in bundle.files.frames:
        value = (package_path / descriptor.relative_path).read_bytes()
        if len(value) != descriptor.byte_length or _sha256(value) != descriptor.sha256:
            raise IntakeContractError(f"{descriptor.relative_path} bytes do not match descriptor")
        frame = next(
            (
                item
                for item in frames
                if isinstance(item, Mapping)
                and item.get("part_name") == Path(descriptor.relative_path).stem
            ),
            None,
        )
        if (
            not isinstance(frame, Mapping)
            or frame.get("byte_length") != descriptor.byte_length
            or frame.get("sha256") != descriptor.sha256
        ):
            raise IntakeContractError(f"{descriptor.relative_path} differs from evidence manifest")
    snippet = evidence_manifest.get("video_snippet")
    expected_snippet = None
    if isinstance(snippet, Mapping) and snippet.get("capture_complete"):
        part_name = snippet.get("part_name")
        expected_snippet = f"video/{part_name}.mp4"
    declared_snippet = (
        bundle.files.video_snippet.relative_path if bundle.files.video_snippet is not None else None
    )
    if expected_snippet != declared_snippet:
        raise IntakeContractError("evidence package video snippet differs from evidence manifest")
    if bundle.files.video_snippet is not None:
        value = (package_path / declared_snippet).read_bytes()
        if (
            len(value) != bundle.files.video_snippet.byte_length
            or _sha256(value) != bundle.files.video_snippet.sha256
        ):
            raise IntakeContractError("video snippet bytes do not match descriptor")
        if (
            not isinstance(snippet, Mapping)
            or snippet.get("byte_length") != bundle.files.video_snippet.byte_length
            or snippet.get("sha256") != bundle.files.video_snippet.sha256
        ):
            raise IntakeContractError("video snippet differs from evidence manifest")


def _sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


__all__ = [
    "EvidencePackageData",
    "discover_evidence_package_paths",
    "load_evidence_package",
]
