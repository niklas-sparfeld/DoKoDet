"""Read-only M0 preflight for the first local DINOv3 identity campaign.

The preflight discovers the current maintained visual-card and visual-identity references.  It
does not select by recording-name order and it does not publish a dataset, crop, checkpoint, or
bundle.  M1 will freeze the exact revision IDs reported here immediately before training.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from table_evidence_analyzer.cards import CARD_IDENTITIES
from table_evidence_analyzer.local_identity import (
    DINOV3_ARCHITECTURE,
    DINOV3_AUGMENTATION_CONFIG,
    DINOV3_CONFIG_FILENAME,
    DINOV3_DEPENDENCY_VERSIONS,
    DINOV3_FEATURE,
    DINOV3_IMAGE_SIZE,
    DINOV3_MODEL_ID,
    DINOV3_PATCH_SIZE,
    DINOV3_PROCESSOR_CONFIG,
    DINOV3_PROCESSOR_FILENAME,
    DINOV3_TRANSFORM_VERSION,
    DinoV3LicenseRecord,
    LocalIdentityContractError,
    load_dinov3_identity_config,
)
from table_evidence_analyzer.pipeline_data import (
    VisibleCardData,
    VisualIdentityData,
)

from .holdout import load_system_holdout_registry, sealed_group_keys
from .intake import inspect_repository
from .source_exclusion import SourceExclusionError, ensure_source_allowed

DINOV3_PREFLIGHT_SCHEMA_VERSION = "dinov3-identity-preflight/v1"
DINOV3_CAMPAIGN_ID = "0043-m0-first-local-dinov3-card-identifier"
DINOV3_IDENTITY_CONFIG_SCHEMA = "dinov3-identity-config/v1"
DINOV3_REQUIRED_CROP_POLICY = "predicted_visible_region"
DINOV3_TRAINING_DEVICE = "mps"
DINOV3_SEED = 17
DINOV3_MAX_EPOCHS = 20
DINOV3_INITIAL_BATCH_SIZES = (8, 4, 2, 1)
DINOV3_FACE_UP_MIN_TRAIN = 20
DINOV3_FACE_UP_MIN_VALIDATION = 5
DINOV3_MIN_TRAIN_RECORDINGS = 5
DINOV3_MIN_VALIDATION_RECORDINGS = 2
DINOV3_MAX_TRAIN_RECORDING_FRACTION = 0.40
DINOV3_FACE_UP_IDENTITIES = tuple(
    identity for identity in CARD_IDENTITIES if not identity.endswith("_NINE")
)
DINOV3_UNSUPPORTED_IDENTITIES = tuple(
    identity for identity in CARD_IDENTITIES if identity not in DINOV3_FACE_UP_IDENTITIES
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DinoV3IdentityPreflightError(ValueError):
    """Raised when an M0 preflight input is malformed."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DinoV3IdentityPreflightError("preflight values must be finite JSON") from error


def sha256_json(value: Any) -> str:
    """Return the digest used by the read-only preflight manifest."""

    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DinoV3IdentityPreflightError(f"could not read {context}: {path}") from error
    if not isinstance(value, Mapping):
        raise DinoV3IdentityPreflightError(f"{context} must be a JSON object: {path}")
    return dict(value)


def _resolve(root: Path, value: str | Path | None, default: Path) -> Path:
    candidate = default if value is None else Path(value).expanduser()
    return candidate if candidate.is_absolute() else (root / candidate).resolve()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DinoV3IdentityPreflightError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value)
    ):
        raise DinoV3IdentityPreflightError(f"{field} must be a safe identifier")
    return value


def _empty_prerequisite_probe() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "torch_version": None,
        "mps_built": None,
        "mps_available": None,
        "batch_sizes": [],
        "selected_batch_size": None,
        "error": "PyTorch is not installed in the operations environment",
    }


def probe_dinov3_mps(*, batch_sizes: Sequence[int] = DINOV3_INITIAL_BATCH_SIZES) -> dict[str, Any]:
    """Probe MPS and allocate only input tensors; never load model weights."""

    try:
        import torch
    except ImportError:
        return _empty_prerequisite_probe()
    try:
        built = bool(torch.backends.mps.is_built())
        available = bool(torch.backends.mps.is_available())
    except (AttributeError, RuntimeError) as error:
        return {
            **_empty_prerequisite_probe(),
            "torch_version": getattr(torch, "__version__", None),
            "error": f"could not inspect MPS: {error}",
        }
    result: dict[str, Any] = {
        "status": "blocked",
        "torch_version": getattr(torch, "__version__", None),
        "mps_built": built,
        "mps_available": available,
        "batch_sizes": [],
        "selected_batch_size": None,
        "error": None,
    }
    if not built or not available:
        result["error"] = "MPS is not available"
        return result
    for value in batch_sizes:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            continue
        try:
            tensor = torch.empty(
                (value, 3, DINOV3_IMAGE_SIZE, DINOV3_IMAGE_SIZE),
                dtype=torch.float32,
                device="mps",
            )
            tensor.zero_()
            del tensor
            result["batch_sizes"].append(value)
            result["selected_batch_size"] = value
            result["status"] = "ready"
            break
        except (RuntimeError, MemoryError) as error:
            result["batch_sizes"].append({"batch_size": value, "error": str(error)})
    if result["selected_batch_size"] is None:
        result["error"] = "memory-only MPS batch probe failed for every candidate size"
    return result


def _package_lock_check(repository: Path) -> tuple[dict[str, Any], list[str]]:
    """Check the checked-in package declarations without running a resolver."""

    gaps: list[str] = []
    files = {
        "pyproject": repository / "table_evidence_analyzer" / "pyproject.toml",
        "lock": repository / "table_evidence_analyzer" / "uv.lock",
    }
    result: dict[str, Any] = {
        "status": "ready",
        "paths": {name: _relative(path, repository) for name, path in files.items()},
        "required_versions": dict(DINOV3_DEPENDENCY_VERSIONS),
        "observed_versions": {},
    }
    for name, path in files.items():
        if not path.is_file():
            gaps.append(f"DINOv3 package {name} is missing: {_relative(path, repository)}")
    if gaps:
        result["status"] = "blocked"
        return result, gaps
    pyproject = files["pyproject"].read_text(encoding="utf-8")
    lock = files["lock"].read_text(encoding="utf-8")
    for package, version in DINOV3_DEPENDENCY_VERSIONS.items():
        declaration = f'"{package}=={version}"'
        if declaration not in pyproject:
            gaps.append(f"table_evidence_analyzer/pyproject.toml does not pin {declaration}")
        match = re.search(
            rf'(?ms)^\[\[package\]\]\s*\nname = "{re.escape(package)}"\s*\nversion = "([^"]+)"',
            lock,
        )
        observed = match.group(1) if match else None
        result["observed_versions"][package] = observed
        if observed != version:
            gaps.append(f"table_evidence_analyzer/uv.lock does not pin {package}=={version}")
    if gaps:
        result["status"] = "blocked"
    return result, gaps


def _license_and_weights(
    repository: Path,
    *,
    identity_config_path: str | Path | None,
    license_record_path: str | Path | None,
    weights_root: str | Path | None,
) -> tuple[dict[str, Any], list[str]]:
    gaps: list[str] = []
    default_config = repository / "data" / "operations" / "dinov3-identity-config.json"
    config_path = _resolve(repository, identity_config_path, default_config)
    record_path = _resolve(
        repository,
        license_record_path,
        (
            config_path
            if identity_config_path is not None or config_path.is_file()
            else default_config
        ),
    )
    root = _resolve(
        repository,
        weights_root,
        repository / "data" / "models" / "dinov3-vits16-pretrain-lvd1689m",
    )
    result: dict[str, Any] = {
        "license": {
            "status": "blocked",
            "path": _relative(record_path, repository),
            "record": None,
        },
        "pretrained": {
            "status": "blocked",
            "root": _relative(root, repository),
            "model_id": DINOV3_MODEL_ID,
            "revision": None,
            "files": {},
        },
        "identity_config": {
            "status": "missing",
            "path": _relative(config_path, repository),
            "digest": None,
        },
    }
    raw_config: dict[str, Any] | None = None
    if config_path.is_file():
        try:
            raw_config = _read_json(config_path, "DINOv3 identity config")
            result["identity_config"].update(
                {"status": "read", "digest": _file_sha256(config_path)}
            )
            if raw_config.get("schema_version") != DINOV3_IDENTITY_CONFIG_SCHEMA:
                gaps.append("DINOv3 identity config schema is not pinned")
        except DinoV3IdentityPreflightError as error:
            result["identity_config"]["status"] = "invalid"
            gaps.append(str(error))
    else:
        gaps.append(f"DINOv3 identity config is missing: {_relative(config_path, repository)}")

    raw_license = raw_config.get("license") if raw_config is not None else None
    if record_path.is_file() and record_path != config_path:
        try:
            raw_license = _read_json(record_path, "DINOv3 license record")
        except DinoV3IdentityPreflightError as error:
            gaps.append(str(error))
    if isinstance(raw_license, Mapping):
        try:
            license_record = DinoV3LicenseRecord.from_mapping(raw_license)
            result["license"]["record"] = license_record.to_mapping()
            result["license"]["status"] = "ready" if license_record.accepted else "blocked"
            if not license_record.accepted:
                gaps.append("DINOv3 license acceptance is required before model use")
        except LocalIdentityContractError as error:
            gaps.append(f"DINOv3 license record is invalid: {error}")
    else:
        gaps.append(f"DINOv3 license record is missing: {_relative(record_path, repository)}")

    if raw_config is not None and isinstance(raw_config.get("model"), Mapping):
        model = raw_config["model"]
        result["pretrained"]["revision"] = model.get("revision")
        root_from_config = root
        if isinstance(model.get("weights"), Mapping):
            declared_files = {
                "weights": model["weights"].get("file"),
                "config": model.get("config_file", DINOV3_CONFIG_FILENAME),
                "processor": model.get("processor_file", DINOV3_PROCESSOR_FILENAME),
            }
            declared_digests = {
                "weights": model["weights"].get("sha256"),
                "config": model.get("config_sha256"),
                "processor": model.get("processor_sha256"),
            }
        else:
            declared_files = {}
            declared_digests = {}
        for name, filename in declared_files.items():
            if not isinstance(filename, str):
                gaps.append(f"DINOv3 identity config has no {name} file")
                continue
            path = root_from_config / filename
            item: dict[str, Any] = {
                "path": _relative(path, repository),
                "declared_sha256": declared_digests.get(name),
            }
            if not path.is_file():
                gaps.append(f"pretrained {name} file is missing: {_relative(path, repository)}")
            else:
                actual = _file_sha256(path)
                item["sha256"] = actual
                if declared_digests.get(name) != actual:
                    gaps.append(f"pretrained {name} bytes do not match the identity config")
            result["pretrained"]["files"][name] = item
        license_record_value = result["license"]["record"]
        if isinstance(license_record_value, Mapping) and license_record_value.get("accepted"):
            try:
                identity_config = load_dinov3_identity_config(
                    config_path,
                    weights_root=root_from_config,
                )
                if (
                    record_path != config_path
                    and identity_config.license_record.to_mapping() != license_record_value
                ):
                    gaps.append("DINOv3 license record does not match the identity config")
                result["pretrained"]["revision"] = identity_config.weights.model_revision
                result["pretrained"]["materialization_digest"] = (
                    identity_config.weights.materialization_digest
                )
                result["pretrained"]["status"] = "ready"
            except (LocalIdentityContractError, TypeError, ValueError) as error:
                gaps.append(f"DINOv3 identity config is invalid: {error}")
        else:
            gaps.append("pretrained DINOv3 files cannot be validated before license acceptance")
    else:
        gaps.append("DINOv3 identity config has no frozen model declaration")
    return result, gaps


def _discover_split_path(
    operations: Path, repository: Path, requested: str | Path | None
) -> Path | None:
    if requested is not None:
        return _resolve(
            repository,
            requested,
            operations / "visual-identity-split" / "active.json",
        )
    exact = (
        operations / "visual-identity-split" / "active.json",
        operations / "visual-identity-splits" / "active.json",
        operations / "visual-identity-split.json",
        operations / "visual-identity-splits.json",
    )
    for path in exact:
        if path.is_file():
            return path
    candidates = sorted(
        path
        for path in operations.rglob("*.json")
        if any(token in path.as_posix().lower() for token in ("visual-identity", "visual_identity"))
        and "split" in path.name.lower()
    )
    return candidates[0] if candidates else None


def _split_inventory(
    operations: Path, repository: Path, requested: str | Path | None
) -> tuple[dict[str, Any], list[str]]:
    gaps: list[str] = []
    active_path = _discover_split_path(operations, repository, requested)
    result: dict[str, Any] = {
        "status": "blocked",
        "active_path": None,
        "version_path": None,
        "split_version_id": None,
        "split_version_digest": None,
        "partitions": {"train": [], "validation": [], "test": [], "unassigned": []},
    }
    if active_path is None:
        gaps.append("selected visual-identity split version is missing")
        return result, gaps
    result["active_path"] = _relative(active_path, repository)
    try:
        active = _read_json(active_path, "visual-identity split")
    except DinoV3IdentityPreflightError as error:
        gaps.append(str(error))
        return result, gaps
    version = active
    version_path = active_path
    version_id = active.get("split_version_id")
    if active_path.name == "active.json" and isinstance(version_id, str):
        candidate = active_path.parent / "versions" / f"{version_id}.json"
        if candidate.is_file():
            try:
                version = _read_json(candidate, "selected visual-identity split version")
                version_path = candidate
            except DinoV3IdentityPreflightError as error:
                gaps.append(str(error))
                return result, gaps
        else:
            gaps.append(f"selected visual-identity split version is missing: {candidate}")
    result["version_path"] = _relative(version_path, repository)
    result["split_version_id"] = version.get("split_version_id", version.get("id"))
    result["split_version_digest"] = version.get("split_version_digest", version.get("digest"))
    if not isinstance(result["split_version_id"], str):
        gaps.append("selected visual-identity split has no split_version_id")
    if (
        not isinstance(result["split_version_digest"], str)
        or _SHA256.fullmatch(result["split_version_digest"]) is None
    ):
        gaps.append("selected visual-identity split has no valid split_version_digest")
    else:
        core = {
            key: value
            for key, value in version.items()
            if key not in {"split_version_id", "split_version_digest", "id", "digest"}
        }
        if sha256_json(core) != result["split_version_digest"]:
            gaps.append("selected visual-identity split digest does not match its contents")
    partitions = version.get("partitions")
    if not isinstance(partitions, Mapping):
        partitions = version
    for name in result["partitions"]:
        raw_items = partitions.get(name, [])
        if not isinstance(raw_items, list):
            gaps.append(f"selected visual-identity split {name} partition is not a list")
            continue
        normalized: list[str] = []
        for index, item in enumerate(raw_items):
            value: Any = item
            if isinstance(item, Mapping):
                value = item.get("recording_id", item.get("source_recording_id"))
            if not isinstance(value, str) or not value:
                gaps.append(f"selected visual-identity split {name}[{index}] has no recording_id")
                continue
            normalized.append(value)
        result["partitions"][name] = normalized
    assigned = [item for values in result["partitions"].values() for item in values]
    if len(assigned) != len(set(assigned)):
        gaps.append("selected visual-identity split assigns one recording more than once")
    if not result["partitions"]["train"] or not result["partitions"]["validation"]:
        gaps.append(
            "selected visual-identity split needs non-empty train and validation partitions"
        )
    result["status"] = "ready" if not gaps else "blocked"
    return result, gaps


def _source_inventory(
    repository: Path,
    operations: Path,
    intake: Path,
    *,
    verify_source_bytes: bool,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    gaps: list[str] = []
    result: dict[str, dict[str, Any]] = {}
    try:
        inspection = inspect_repository(
            repository,
            bundle_root=intake,
            artifacts_root=operations,
        )
    except (OSError, ValueError) as error:
        return {}, [f"shared recording-bundle validation failed: {error}"]
    for bundle in inspection.bundles:
        if bundle.recording_id is None:
            continue
        bundle_path = repository / bundle.path
        item: dict[str, Any] = {
            "recording_id": bundle.recording_id,
            "bundle_path": bundle.path,
            "state": bundle.state,
            "bundle_errors": list(bundle.errors),
        }
        if bundle.errors:
            gaps.extend(f"{bundle.recording_id}: {error}" for error in bundle.errors)
        if bundle.state != "complete":
            continue
        try:
            manifest = _read_json(bundle_path / "manifest.json", "recording bundle manifest")
            source_path = bundle_path / "source-record.json"
            if not source_path.is_file():
                source_record_info = manifest.get("source_record")
                if isinstance(source_record_info, Mapping) and isinstance(
                    source_record_info.get("relative_path"), str
                ):
                    source_path = bundle_path / source_record_info["relative_path"]
            source = _read_json(source_path, "source record")
        except DinoV3IdentityPreflightError as error:
            gaps.append(f"{bundle.recording_id}: {error}")
            continue
        video = (
            manifest.get("files", {}).get("video")
            if isinstance(manifest.get("files"), Mapping)
            else None
        )
        video = video if isinstance(video, Mapping) else {}
        source_digest = source.get("sha256", source.get("source_sha256"))
        bundle_digest = manifest.get("source_sha256")
        video_digest = video.get("sha256")
        for label, value in (
            ("source record", source_digest),
            ("bundle", bundle_digest),
            ("video descriptor", video_digest),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                gaps.append(f"{bundle.recording_id}: {label} has no valid source digest")
        if (
            len(
                {
                    value
                    for value in (source_digest, bundle_digest, video_digest)
                    if isinstance(value, str)
                }
            )
            > 1
        ):
            gaps.append(f"{bundle.recording_id}: source and video digests differ")
        video_path = None
        if isinstance(video.get("relative_path"), str):
            video_path = bundle_path / video["relative_path"]
            if not video_path.is_file():
                gaps.append(f"{bundle.recording_id}: source video is missing")
            elif (
                verify_source_bytes
                and isinstance(bundle_digest, str)
                and (_file_sha256(video_path) != bundle_digest)
            ):
                gaps.append(f"{bundle.recording_id}: source video bytes differ from its digest")
        allowed_uses = source.get("allowed_uses")
        if not isinstance(allowed_uses, list) or any(
            not isinstance(value, str) for value in allowed_uses
        ):
            gaps.append(f"{bundle.recording_id}: source allowed_uses is invalid")
            allowed_uses = []
        task_selected = any(
            task.task == "table_evidence_analysis" and task.disposition == "selected"
            for task in bundle.tasks
        )
        item.update(
            {
                "session_id": source.get("session_id", manifest.get("session_id")),
                "table_setup": source.get("table_setup"),
                "source_asset_id": source.get("source_asset_id", manifest.get("source_asset_id")),
                "source_sha256": bundle_digest,
                "source_permission": source.get("source_permission"),
                "allowed_uses": sorted(set(allowed_uses)),
                "retention_state": source.get("retention_state"),
                "task_selected": task_selected,
                "manifest_path": _relative(bundle_path / "manifest.json", repository),
                "manifest_sha256": _file_sha256(bundle_path / "manifest.json"),
                "source_record_path": _relative(source_path, repository),
                "source_record_sha256": (
                    _file_sha256(source_path) if source_path.is_file() else None
                ),
                "source_video_path": (
                    _relative(video_path, repository) if video_path is not None else None
                ),
                "source_groups": {
                    "session_id": source.get("session_id", manifest.get("session_id")),
                    "source_lineage": source.get(
                        "source_asset_id", manifest.get("source_asset_id")
                    ),
                    "table_setup": source.get("table_setup"),
                },
            }
        )
        result[bundle.recording_id] = item
    return result, gaps


def _revision_inventory(
    repository: Path, operations: Path
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    root = operations / "pipeline" / "revisions"
    result: dict[str, dict[str, Any]] = {}
    gaps: list[str] = []
    if not root.is_dir():
        return result, [f"pipeline revision root is missing: {_relative(root, repository)}"]
    for directory in sorted(root.iterdir(), key=lambda path: path.name):
        if not directory.is_dir() or directory.is_symlink() or directory.name.startswith("."):
            continue
        manifest_path = directory / "manifest.json"
        content_path = directory / "content.json"
        if not manifest_path.is_file() or not content_path.is_file():
            gaps.append(
                f"incomplete pipeline revision directory: {_relative(directory, repository)}"
            )
            continue
        try:
            manifest = _read_json(manifest_path, "pipeline revision manifest")
            content = _read_json(content_path, "pipeline revision content")
        except DinoV3IdentityPreflightError as error:
            gaps.append(str(error))
            continue
        revision_id = manifest.get("revision_id", directory.name)
        if revision_id != directory.name:
            gaps.append(f"pipeline revision directory does not match revision_id: {directory.name}")
            continue
        actual_content_digest = sha256_json(content)
        if manifest.get("content_sha256") != actual_content_digest:
            gaps.append(f"pipeline revision content digest mismatch: {revision_id}")
            continue
        result[str(revision_id)] = {
            "manifest": manifest,
            "content": content,
            "manifest_path": _relative(manifest_path, repository),
            "manifest_sha256": _file_sha256(manifest_path),
            "content_path": _relative(content_path, repository),
            "content_sha256": actual_content_digest,
        }
    return result, gaps


def _reference_inventory(
    repository: Path, operations: Path
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    root = operations / "pipeline-references"
    result: dict[tuple[str, str], dict[str, Any]] = {}
    gaps: list[str] = []
    if not root.is_dir():
        return result, [f"maintained reference root is missing: {_relative(root, repository)}"]
    for recording_root in sorted(root.iterdir(), key=lambda path: path.name):
        if not recording_root.is_dir() or recording_root.is_symlink():
            continue
        for content_type in ("visible_cards", "visual_identities"):
            reference_root = recording_root / content_type
            state_path = reference_root / "state.json"
            draft_path = reference_root / "draft.json"
            if not state_path.exists() and not draft_path.exists():
                continue
            if not state_path.is_file() or not draft_path.is_file():
                gaps.append(
                    f"incomplete maintained reference: {_relative(reference_root, repository)}"
                )
                continue
            try:
                state = _read_json(state_path, "pipeline reference state")
                draft = _read_json(draft_path, "pipeline reference draft")
            except DinoV3IdentityPreflightError as error:
                gaps.append(str(error))
                continue
            if state.get("draft_state") != "completed":
                continue
            revision_id = state.get("selected_completed_revision_id")
            if not isinstance(revision_id, str) or not revision_id:
                gaps.append(
                    "completed maintained reference has no selected revision: "
                    f"{_relative(reference_root, repository)}"
                )
                continue
            if (
                state.get("recording_id", recording_root.name) != recording_root.name
                or state.get("content_type", content_type) != content_type
            ):
                gaps.append(
                    "maintained reference path and state disagree: "
                    f"{_relative(reference_root, repository)}"
                )
                continue
            result[(recording_root.name, content_type)] = {
                "recording_id": recording_root.name,
                "content_type": content_type,
                "selected_revision_id": revision_id,
                "state": state,
                "draft": draft,
                "state_path": _relative(state_path, repository),
                "draft_path": _relative(draft_path, repository),
                "state_sha256": _file_sha256(state_path),
                "draft_sha256": _file_sha256(draft_path),
            }
    return result, gaps


def _validate_reference(
    reference: Mapping[str, Any],
    revision: Mapping[str, Any] | None,
    *,
    recording: Mapping[str, Any],
    expected_type: str,
    repository: Path,
    revisions: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    gaps: list[str] = []
    if revision is None:
        return [], [f"{recording['recording_id']}: selected {expected_type} revision is missing"]
    manifest = revision["manifest"]
    content = revision["content"]
    if manifest.get("recording_id") != recording["recording_id"]:
        gaps.append(
            f"{recording['recording_id']}: {expected_type} revision belongs to another recording"
        )
    if manifest.get("content_type") not in {None, expected_type}:
        gaps.append(f"{recording['recording_id']}: selected revision is not {expected_type} data")
    if manifest.get("origin") not in {None, "manual", "corrected"}:
        gaps.append(
            f"{recording['recording_id']}: selected {expected_type} revision is "
            "not human-maintained"
        )
    producer = manifest.get("producer")
    if isinstance(producer, Mapping) and producer.get("kind") not in {"human", None}:
        gaps.append(
            f"{recording['recording_id']}: selected {expected_type} revision has no human lineage"
        )
    source = manifest.get("source")
    if isinstance(source, Mapping):
        source_digest = source.get("video_sha256", source.get("source_sha256"))
        if source_digest != recording.get("source_sha256"):
            gaps.append(
                f"{recording['recording_id']}: {expected_type} revision source "
                "digest differs from bundle"
            )
    try:
        if expected_type == "visible_cards":
            VisibleCardData.from_mapping(content)
        else:
            VisualIdentityData.from_mapping(content)
    except (TypeError, ValueError) as error:
        gaps.append(
            f"{recording['recording_id']}: {expected_type} revision content is invalid: {error}"
        )
    outcomes = content.get("outcomes")
    if not isinstance(outcomes, list):
        return [], [*gaps, f"{recording['recording_id']}: {expected_type} revision has no outcomes"]
    if expected_type == "visual_identities":
        input_ids = manifest.get("input_revision_ids")
        if isinstance(input_ids, list) and reference.get("selected_visible_revision_id"):
            if reference["selected_visible_revision_id"] not in input_ids:
                gaps.append(
                    f"{recording['recording_id']}: visual identity revision is not paired "
                    "to visible-card revision"
                )
        elif isinstance(input_ids, list):
            # The selected visible revision is attached by the caller after this function.
            pass
    return [dict(item) for item in outcomes if isinstance(item, Mapping)], gaps


def _recording_groups(recording: Mapping[str, Any]) -> dict[str, str]:
    return {
        name: value
        for name, value in recording.get("source_groups", {}).items()
        if isinstance(value, str) and value
    }


def _analyze_recording(
    recording: Mapping[str, Any],
    partition: str,
    visible_reference: Mapping[str, Any],
    identity_reference: Mapping[str, Any],
    revisions: Mapping[str, Mapping[str, Any]],
    repository: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    gaps: list[str] = []
    recording_id = recording["recording_id"]
    visible_id = visible_reference["selected_revision_id"]
    identity_id = identity_reference["selected_revision_id"]
    visible_revision = revisions.get(visible_id)
    identity_revision = revisions.get(identity_id)
    if visible_revision is None or identity_revision is None:
        missing = [
            value
            for value, revision in (
                (visible_id, visible_revision),
                (identity_id, identity_revision),
            )
            if revision is None
        ]
        return (
            {"recording_id": recording_id, "partition": partition, "included_count": 0},
            [],
            [f"{recording_id}: missing selected revision(s): {', '.join(missing)}"],
        )
    visible_outcomes, visible_gaps = _validate_reference(
        visible_reference,
        visible_revision,
        recording=recording,
        expected_type="visible_cards",
        repository=repository,
        revisions=revisions,
    )
    identity_reference_with_pair = dict(identity_reference)
    identity_reference_with_pair["selected_visible_revision_id"] = visible_id
    identity_outcomes, identity_gaps = _validate_reference(
        identity_reference_with_pair,
        identity_revision,
        recording=recording,
        expected_type="visual_identities",
        repository=repository,
        revisions=revisions,
    )
    gaps.extend([*visible_gaps, *identity_gaps])
    visible_cards: dict[str, dict[str, Any]] = {}
    for outcome in visible_outcomes:
        if outcome.get("status") != "detected":
            continue
        for candidate in outcome.get("candidates", []):
            if not isinstance(candidate, Mapping) or not isinstance(candidate.get("card_id"), str):
                gaps.append(f"{recording_id}: visible-card candidate has no card_id")
                continue
            card_id = candidate["card_id"]
            if card_id in visible_cards:
                gaps.append(f"{recording_id}: visible-card card_id is duplicated: {card_id}")
            visible_cards[card_id] = {
                "frame_identity": outcome.get("frame_identity"),
                "geometry": candidate.get("geometry"),
                "side": candidate.get("side", "unknown"),
                "event_id": outcome.get("event_id"),
            }
    identity_by_card = {
        item.get("card_id"): item
        for item in identity_outcomes
        if isinstance(item.get("card_id"), str)
    }
    rows: list[dict[str, Any]] = []
    statuses: Counter[str] = Counter()
    crop_policies: Counter[str] = Counter()
    excluded: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    for card_id, visible in visible_cards.items():
        identity = identity_by_card.get(card_id)
        if identity is None:
            excluded.append(
                {
                    "recording_id": recording_id,
                    "card_id": card_id,
                    "partition": partition,
                    "status": "missing_identity_reference",
                    "identity_revision_id": identity_id,
                }
            )
            continue
        status = identity.get("status")
        statuses[str(status)] += 1
        if identity.get("frame_identity") != visible.get("frame_identity"):
            gaps.append(f"{recording_id}: paired references use different frames for {card_id}")
        if identity.get("geometry") != visible.get("geometry"):
            gaps.append(f"{recording_id}: paired references use different geometry for {card_id}")
        crop = identity.get("crop_identity")
        crop_policy = crop.get("crop_policy") if isinstance(crop, Mapping) else None
        crop_policies[str(crop_policy)] += 1
        if status == "face_down":
            excluded.append(
                {
                    "recording_id": recording_id,
                    "card_id": card_id,
                    "partition": partition,
                    "status": "face_down",
                    "identity_revision_id": identity_id,
                    "crop_policy": crop_policy,
                }
            )
            continue
        if status in {"unusable", "failed"}:
            excluded.append(
                {
                    "recording_id": recording_id,
                    "card_id": card_id,
                    "partition": partition,
                    "status": status,
                    "identity_revision_id": identity_id,
                    "reason": identity.get("unusable_reason", identity.get("error")),
                    "crop_policy": crop_policy,
                }
            )
            continue
        if status != "classified":
            gaps.append(
                f"{recording_id}: identity outcome has unsupported status for {card_id}: {status}"
            )
            continue
        candidates = identity.get("candidates")
        target = (
            candidates[0].get("identity") if isinstance(candidates, list) and candidates else None
        )
        if target not in CARD_IDENTITIES:
            gaps.append(f"{recording_id}: classified identity is not canonical for {card_id}")
            continue
        if crop_policy != DINOV3_REQUIRED_CROP_POLICY:
            excluded.append(
                {
                    "recording_id": recording_id,
                    "card_id": card_id,
                    "partition": partition,
                    "status": "wrong_crop_policy",
                    "identity_revision_id": identity_id,
                    "crop_policy": crop_policy,
                }
            )
            gaps.append(
                f"{recording_id}: classified identity uses {crop_policy!r}; "
                f"M0 requires {DINOV3_REQUIRED_CROP_POLICY!r}"
            )
            continue
        if visible.get("side") == "face_down":
            gaps.append(
                f"{recording_id}: classified identity is attached to a face-down "
                f"visible card: {card_id}"
            )
            continue
        if not isinstance(crop, Mapping) or crop.get("status") != "usable":
            gaps.append(f"{recording_id}: classified identity has no usable crop: {card_id}")
            continue
        class_counts[target] += 1
        rows.append(
            {
                "sample_id": f"{recording_id}:{card_id}",
                "recording_id": recording_id,
                "partition": partition,
                "source_lineage_group": _recording_groups(recording),
                "card_id": card_id,
                "target": target,
                "card_side": visible.get("side", "unknown"),
                "visible_card_revision_id": visible_id,
                "visual_identity_revision_id": identity_id,
                "frame_identity_digest": sha256_json(identity.get("frame_identity")),
                "crop_policy": crop_policy,
                "crop_digest": crop.get("image_sha256"),
            }
        )
    return (
        {
            "recording_id": recording_id,
            "partition": partition,
            "visible_card_revision_id": visible_id,
            "visual_identity_revision_id": identity_id,
            "visible_card_outcome_count": len(visible_outcomes),
            "identity_outcome_count": len(identity_outcomes),
            "included_count": len(rows),
            "class_counts": dict(sorted(class_counts.items())),
            "outcome_counts": dict(sorted(statuses.items())),
            "crop_policy_counts": dict(sorted(crop_policies.items())),
            "excluded_count": len(excluded),
            "source_lineage_groups": _recording_groups(recording),
            "excluded": excluded,
        },
        rows,
        gaps,
    )


def _gate_report(
    rows: Sequence[Mapping[str, Any]],
    recordings: Mapping[str, Mapping[str, Any]],
    partitions: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {
        identity: {partition: 0 for partition in ("train", "validation", "unassigned")}
        for identity in CARD_IDENTITIES
    }
    per_recording: Counter[str] = Counter()
    for row in rows:
        target = row.get("target")
        partition = row.get("partition")
        if target in counts and partition in counts[target]:
            counts[target][partition] += 1
            per_recording[str(row.get("recording_id"))] += 1
    train_total = sum(counts[item]["train"] for item in counts)
    train_fractions = {
        recording_id: (count / train_total if train_total else 0.0)
        for recording_id, count in sorted(per_recording.items())
        if recordings.get(recording_id, {}).get("partition") == "train"
    }
    absent = [identity for identity in CARD_IDENTITIES if sum(counts[identity].values()) == 0]
    class_gate = all(
        counts[identity]["train"] >= DINOV3_FACE_UP_MIN_TRAIN
        and counts[identity]["validation"] >= DINOV3_FACE_UP_MIN_VALIDATION
        for identity in DINOV3_FACE_UP_IDENTITIES
    )
    result = {
        "target_identities": list(DINOV3_FACE_UP_IDENTITIES),
        "counts_by_identity": counts,
        "absent_identities": absent,
        "unsupported_identities": list(DINOV3_UNSUPPORTED_IDENTITIES),
        "train_recording_count": len(partitions.get("train", [])),
        "validation_recording_count": len(partitions.get("validation", [])),
        "train_total": train_total,
        "largest_train_recording_fraction": max(train_fractions.values(), default=0.0),
        "train_recording_fractions": train_fractions,
        "gates": {
            "face_up_examples": {
                "pass": class_gate,
                "minimum_train_per_identity": DINOV3_FACE_UP_MIN_TRAIN,
                "minimum_validation_per_identity": DINOV3_FACE_UP_MIN_VALIDATION,
            },
            "minimum_train_recordings": {
                "pass": len(partitions.get("train", [])) >= DINOV3_MIN_TRAIN_RECORDINGS,
                "required": DINOV3_MIN_TRAIN_RECORDINGS,
                "observed": len(partitions.get("train", [])),
            },
            "minimum_validation_recordings": {
                "pass": len(partitions.get("validation", [])) >= DINOV3_MIN_VALIDATION_RECORDINGS,
                "required": DINOV3_MIN_VALIDATION_RECORDINGS,
                "observed": len(partitions.get("validation", [])),
            },
            "largest_train_recording_fraction": {
                "pass": max(train_fractions.values(), default=0.0)
                <= DINOV3_MAX_TRAIN_RECORDING_FRACTION,
                "maximum": DINOV3_MAX_TRAIN_RECORDING_FRACTION,
                "observed": max(train_fractions.values(), default=0.0),
            },
            "unsupported_classes_reported": {
                "pass": True,
                "classes": list(DINOV3_UNSUPPORTED_IDENTITIES),
            },
        },
    }
    return result


def build_dinov3_identity_preflight(
    repository_root: str | Path,
    *,
    operations_root: str | Path | None = None,
    intake_root: str | Path | None = None,
    split_path: str | Path | None = None,
    holdout_registry_path: str | Path | None = None,
    identity_config_path: str | Path | None = None,
    license_record_path: str | Path | None = None,
    weights_root: str | Path | None = None,
    verify_source_bytes: bool = False,
    prerequisite_probe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the deterministic, read-only M0 preflight report."""

    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root, repository / "data" / "operations")
    intake = _resolve(repository, intake_root, repository / "data" / "intake" / "recordings")
    holdout_path = _resolve(
        repository, holdout_registry_path, operations / "system-holdout-registry.json"
    )
    split, split_gaps = _split_inventory(operations, repository, split_path)
    sources, source_gaps = _source_inventory(
        repository, operations, intake, verify_source_bytes=verify_source_bytes
    )
    revisions, revision_gaps = _revision_inventory(repository, operations)
    references, reference_gaps = _reference_inventory(repository, operations)
    try:
        holdout = load_system_holdout_registry(holdout_path)
        held_out = sealed_group_keys(holdout)
    except (OSError, ValueError) as error:
        holdout = {"registry_version": None, "registry_digest": None, "seals": []}
        held_out = frozenset()
        source_gaps.append(f"could not load system holdout registry: {error}")

    prerequisite_gaps: list[str] = []
    prerequisites, model_gaps = _license_and_weights(
        repository,
        identity_config_path=identity_config_path,
        license_record_path=license_record_path,
        weights_root=weights_root,
    )
    prerequisite_gaps.extend(model_gaps)
    package_lock, lock_gaps = _package_lock_check(repository)
    prerequisite_gaps.extend(lock_gaps)
    mps_probe = dict(prerequisite_probe) if prerequisite_probe is not None else probe_dinov3_mps()
    if mps_probe.get("status") != "ready":
        prerequisite_gaps.append(
            f"MPS batch preflight is not ready: {mps_probe.get('error') or 'unknown error'}"
        )
    prerequisites["package_lock"] = package_lock
    prerequisites["mps_batch_probe"] = mps_probe
    prerequisites["recipe"] = {
        "model": {
            "id": DINOV3_MODEL_ID,
            "architecture": DINOV3_ARCHITECTURE,
            "feature": DINOV3_FEATURE,
            "patch_size": DINOV3_PATCH_SIZE,
            "revision": prerequisites["pretrained"].get("revision"),
        },
        "processor": DINOV3_PROCESSOR_CONFIG,
        "augmentation": DINOV3_AUGMENTATION_CONFIG,
        "transform_version": DINOV3_TRANSFORM_VERSION,
        "target_map": {
            str(index): identity for index, identity in enumerate((*CARD_IDENTITIES, "FACE_DOWN"))
        },
        "seed": DINOV3_SEED,
        "device": DINOV3_TRAINING_DEVICE,
        "precision": "fp32",
        "optimizer": {"name": "AdamW", "learning_rate": 0.001, "weight_decay": 0.0},
        "max_epochs": DINOV3_MAX_EPOCHS,
        "batch_size": mps_probe.get("selected_batch_size"),
        "crop_policy": DINOV3_REQUIRED_CROP_POLICY,
    }

    partition_values = split["partitions"]
    partition_for: dict[str, str] = {
        recording_id: partition
        for partition, recording_ids in partition_values.items()
        for recording_id in recording_ids
    }
    for recording_id, partition in partition_for.items():
        if recording_id in sources:
            sources[recording_id]["partition"] = partition
    group_partitions: dict[tuple[str, str], set[str]] = defaultdict(set)
    for recording_id, partition in partition_for.items():
        recording = sources.get(recording_id)
        if recording is None:
            continue
        for name, value in _recording_groups(recording).items():
            group_partitions[(name, value)].add(partition)
    group_gaps = [
        "source lineage group crosses train and validation: " + f"{name}:{value}"
        for (name, value), parts in sorted(group_partitions.items())
        if {"train", "validation"}.issubset(parts)
    ]
    source_gaps.extend(group_gaps)

    selected_rows: list[dict[str, Any]] = []
    recording_reports: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    selected_revisions: list[dict[str, Any]] = []
    analysis_gaps: list[str] = []
    for recording_id in sorted(set(partition_for)):
        partition = partition_for[recording_id]
        if partition in {"test"}:
            exclusions.append(
                {
                    "recording_id": recording_id,
                    "partition": partition,
                    "reason": "test_partition",
                }
            )
            continue
        recording = sources.get(recording_id)
        if recording is None:
            analysis_gaps.append(f"split recording has no accepted bundle: {recording_id}")
            continue
        if partition in {"train", "validation"}:
            try:
                ensure_source_allowed(
                    source_asset_id=recording.get("source_asset_id"),
                    source_sha256=recording.get("source_sha256"),
                    recording_id=recording_id,
                    context=f"{recording_id} source",
                )
            except SourceExclusionError as error:
                analysis_gaps.append(str(error))
            if recording.get("retention_state") != "active":
                analysis_gaps.append(f"{recording_id}: source retention state is not active")
            if partition not in recording.get("allowed_uses", []):
                analysis_gaps.append(
                    f"{recording_id}: source permission does not allow {partition}"
                )
            if not recording.get("task_selected"):
                analysis_gaps.append(
                    f"{recording_id}: table_evidence_analysis task is not selected"
                )
        held = [
            f"{name}:{value}"
            for name, value in _recording_groups(recording).items()
            if (name, value) in held_out
        ]
        if held:
            analysis_gaps.append(
                f"{recording_id}: source is in the sealed system holdout ({', '.join(held)})"
            )
            exclusions.append(
                {
                    "recording_id": recording_id,
                    "partition": partition,
                    "reason": "system_holdout",
                    "groups": held,
                }
            )
            continue
        visible_reference = references.get((recording_id, "visible_cards"))
        identity_reference = references.get((recording_id, "visual_identities"))
        if visible_reference is None or identity_reference is None:
            missing = [
                name
                for name, item in (
                    ("visible_cards", visible_reference),
                    ("visual_identities", identity_reference),
                )
                if item is None
            ]
            analysis_gaps.append(
                f"{recording_id}: missing completed maintained reference(s): {', '.join(missing)}"
            )
            continue
        selected_revisions.append(
            {
                "recording_id": recording_id,
                "partition": partition,
                "visible_card_revision_id": visible_reference["selected_revision_id"],
                "visual_identity_revision_id": identity_reference["selected_revision_id"],
            }
        )
        report, rows, gaps = _analyze_recording(
            recording,
            partition,
            visible_reference,
            identity_reference,
            revisions,
            repository,
        )
        recording_reports.append(report)
        selected_rows.extend(rows)
        exclusions.extend(report.get("excluded", []))
        analysis_gaps.extend(gaps)

    # Completed references that are not named by the selected split are visible in the report but
    # never become validation samples by identifier ordering or accidental discovery.
    completed_recordings = {
        recording_id
        for recording_id, content_type in references
        if content_type == "visual_identities"
    }
    unassigned_references = sorted(completed_recordings - set(partition_for))
    analysis_gaps.extend(
        f"completed visual identity reference is not assigned by the selected split: {recording_id}"
        for recording_id in unassigned_references
    )
    gate_recordings = {
        recording_id: {**recording, "partition": partition_for.get(recording_id)}
        for recording_id, recording in sources.items()
    }
    gates = _gate_report(selected_rows, gate_recordings, partition_values)
    for gate_name, gate in gates["gates"].items():
        if gate.get("pass") is False:
            analysis_gaps.append(f"first-run gate failed: {gate_name}")
    all_gaps = sorted(
        set(
            [
                *split_gaps,
                *source_gaps,
                *revision_gaps,
                *reference_gaps,
                *prerequisite_gaps,
                *analysis_gaps,
            ]
        )
    )
    # FACE_DOWN rows are intentionally excluded and are not a blocker.  Their revision IDs remain
    # in exclusions so the later freeze cannot silently materialize them.
    non_exclusion_gaps = [
        gap for gap in all_gaps if not gap.startswith("excluded from identity sample matrix")
    ]
    report = {
        "schema_version": DINOV3_PREFLIGHT_SCHEMA_VERSION,
        "campaign_id": DINOV3_CAMPAIGN_ID,
        "milestone": "M0",
        "read_only": True,
        "preflight_state": "ready" if not non_exclusion_gaps else "blocked",
        "split": split,
        "prerequisites": prerequisites,
        "holdout_registry": {
            "path": _relative(holdout_path, repository) if holdout_path.exists() else None,
            "registry_version": holdout.get("registry_version"),
            "registry_digest": holdout.get("registry_digest"),
            "sealed_group_count": len(held_out),
        },
        "selection": {
            "strategy": "selected_completed_references_from_frozen_split/v1",
            "selected_recording_ids": sorted(partition_for),
            "selected_revisions": sorted(selected_revisions, key=lambda item: item["recording_id"]),
            "unassigned_completed_references": unassigned_references,
        },
        "inventory": {
            "recording_count": len(sources),
            "completed_visual_card_reference_count": sum(
                content_type == "visible_cards" for _, content_type in references
            ),
            "completed_visual_identity_reference_count": sum(
                content_type == "visual_identities" for _, content_type in references
            ),
            "selected_recording_count": len(selected_revisions),
            "included_face_up_item_count": len(selected_rows),
            "excluded_outcome_count": len(exclusions),
            "excluded_face_down_count": sum(
                item.get("status") == "face_down" for item in exclusions
            ),
            "excluded_unusable_count": sum(item.get("status") == "unusable" for item in exclusions),
            "excluded_failed_count": sum(item.get("status") == "failed" for item in exclusions),
        },
        "recordings": sorted(recording_reports, key=lambda item: item["recording_id"]),
        "items": sorted(selected_rows, key=lambda item: item["sample_id"]),
        "exclusions": sorted(
            exclusions,
            key=lambda item: (
                str(item.get("recording_id")),
                str(item.get("card_id")),
                str(item.get("status")),
            ),
        ),
        "coverage": {
            "class_counts": gates["counts_by_identity"],
            "outcome_counts": {
                partition: dict(
                    sum(
                        (
                            Counter(report.get("outcome_counts", {}))
                            for report in recording_reports
                            if report.get("partition") == partition
                        ),
                        Counter(),
                    )
                )
                for partition in ("train", "validation", "unassigned")
            },
            "crop_policy_counts": {
                policy: sum(
                    report.get("crop_policy_counts", {}).get(policy, 0)
                    for report in recording_reports
                )
                for policy in sorted(
                    {
                        policy
                        for report in recording_reports
                        for policy in report.get("crop_policy_counts", {})
                    }
                )
            },
            "source_lineage_groups": [
                {
                    "group": [name, value],
                    "partitions": sorted(parts),
                    "recording_ids": sorted(
                        recording_id
                        for recording_id, recording in sources.items()
                        if _recording_groups(recording).get(name) == value
                    ),
                }
                for (name, value), parts in sorted(group_partitions.items())
            ],
        },
        "first_run_gate": gates,
        "excluded_face_down_outcomes": [
            item for item in exclusions if item.get("status") == "face_down"
        ],
        "coverage_gaps": all_gaps,
    }
    report["manifest_digest"] = sha256_json(report)
    return json.loads(_canonical(report).decode("utf-8"))


def render_dinov3_identity_preflight_human(report: Mapping[str, Any]) -> str:
    """Render the operator-facing M0 summary without hiding blocked checks."""

    inventory = report.get("inventory", {})
    gate = report.get("first_run_gate", {})
    prerequisites = report.get("prerequisites", {})
    lines = [
        "DINOv3 identity M0 preflight",
        f"state: {report.get('preflight_state')}",
        f"recordings: {inventory.get('recording_count', 0)}",
        f"selected recordings: {inventory.get('selected_recording_count', 0)}",
        f"included face-up items: {inventory.get('included_face_up_item_count', 0)}",
        f"excluded FACE_DOWN outcomes: {inventory.get('excluded_face_down_count', 0)}",
        f"train recordings: {gate.get('train_recording_count', 0)}",
        f"validation recordings: {gate.get('validation_recording_count', 0)}",
        f"MPS batch: {prerequisites.get('mps_batch_probe', {}).get('selected_batch_size')}",
        "selected revisions:",
    ]
    for item in report.get("selection", {}).get("selected_revisions", []):
        lines.append(
            f"  {item['recording_id']} [{item['partition']}]: "
            f"visible={item['visible_card_revision_id']} "
            f"identity={item['visual_identity_revision_id']}"
        )
    gaps = report.get("coverage_gaps", [])
    if gaps:
        lines.append("coverage gaps:")
        lines.extend(f"  - {gap}" for gap in gaps)
    return "\n".join(lines) + "\n"


__all__ = [
    "DINOV3_CAMPAIGN_ID",
    "DINOV3_FACE_UP_IDENTITIES",
    "DINOV3_PREFLIGHT_SCHEMA_VERSION",
    "DINOV3_REQUIRED_CROP_POLICY",
    "DinoV3IdentityPreflightError",
    "build_dinov3_identity_preflight",
    "probe_dinov3_mps",
    "render_dinov3_identity_preflight_human",
    "sha256_json",
]
