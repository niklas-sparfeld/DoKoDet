"""Read-only snapshot and deterministic dry-run inventory for lineage migration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid5

from doko_operations.card_plane_calibration import CalibrationRun
from doko_operations.pipeline_data import (
    RecordingVideoSource,
    canonical_json_bytes,
    parse_pipeline_selection_bytes,
)
from doko_operations.pipeline_reference import (
    parse_reference_draft_bytes,
    parse_reference_state_bytes,
)
from table_evidence_analyzer.card_scene_contract import CalibrationDraft, CalibrationReflowReceipt
from table_evidence_analyzer.pipeline_data import parse_observation_bytes

from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.evidence_package_store import EvidencePackageStore
from dokodetector_backend.pipeline_lineage import _acyclic
from dokodetector_backend.pipeline_store import PipelineRevisionStore, ProcessorRunStore
from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage
from dokodetector_backend.round_analysis_store import RoundAnalysisStore
from dokodetector_backend.visible_card_review_store import VisibleCardReviewStore

NAMESPACE = UUID("d1154376-3ab4-5d84-93e1-092dd4ea62d8")


def _json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("invalid relative identity")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(value).is_absolute():
        raise ValueError("invalid relative identity")
    return value


def _stable_file(path: Path, *, capture: bool = False) -> tuple[int, str, bytes | None]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("source is not a regular file")
    digest = hashlib.sha256()
    chunks = [] if capture else None
    size = 0
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            if chunks is not None:
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
    end = path.lstat()

    def key(s: os.stat_result) -> tuple[int, int, int, int, int]:
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    if (
        key(before) != key(opened)
        or key(opened) != key(after)
        or key(after) != key(end)
        or size != before.st_size
    ):
        raise ValueError("source changed while reading")
    return size, digest.hexdigest(), None if chunks is None else b"".join(chunks)


def _files(root: Path, sealed: set[str]) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}

    def walk(directory: Path) -> None:
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            relative = _relative(path.relative_to(root).as_posix())
            if path.is_symlink():
                raise ValueError(f"symlink is not allowed: {relative}")
            if relative in sealed:
                continue
            if path.name.lower() in {"sealed", "sealed-evaluation", "final-test"}:
                raise ValueError(f"sealed path must be explicitly declared: {relative}")
            if path.is_dir():
                walk(path)
            elif path.is_file():
                size, digest, _ = _stable_file(path)
                result[relative] = (size, digest)
            else:
                raise ValueError(f"unsupported source file: {relative}")

    walk(root)
    return result


def _resource(path: str, *, root_id: str) -> tuple[str, str, str] | None:
    p = path.split("/")
    if root_id == "evidence_packages" and len(p) >= 2:
        try:
            package_id = str(UUID(p[0]))
        except ValueError:
            pass
        else:
            if package_id == p[0]:
                return ("evidence_package", p[0], p[0])
    if len(p) >= 4 and p[:2] == ["pipeline", "revisions"]:
        return ("pipeline_revision", "/".join(p[:3]), p[2])
    if len(p) >= 4 and p[:2] == ["pipeline", "runs"]:
        return ("processor_run", "/".join(p[:3]), p[2])
    if len(p) == 4 and p[:2] == ["pipeline", "selections"] and p[3].endswith(".json"):
        return ("selection", path, f"{p[2]}/{p[3][:-5]}")
    if len(p) >= 4 and p[0] == "pipeline-references":
        return ("maintained_draft", "/".join(p[:3]), f"{p[1]}/{p[2]}")
    if len(p) >= 5 and p[0] == "pipeline-reviews" and p[2] == "visible_cards":
        return ("independent_review", "/".join(p[:4]), f"{p[1]}/{p[3]}")
    if len(p) >= 4 and p[1] in {
        "table-plane-calibrations",
        "table-plane-calibration-drafts",
        "table-plane-calibration-reflows",
    }:
        kind = {
            "table-plane-calibrations": "calibration_revision",
            "table-plane-calibration-drafts": "calibration_draft",
            "table-plane-calibration-reflows": "calibration_reflow",
        }[p[1]]
        return (kind, "/".join(p[:3]), f"{p[0]}/{p[2]}")
    if (
        len(p) == 4
        and p[:2] == ["pipeline", "automated-runs"]
        and p[2] in {"runs", "idempotency", "coordinator-runs"}
        and p[3].endswith(".json")
    ):
        kind = "automated_run_receipt" if p[2] == "idempotency" else "automated_run"
        return (kind, path, p[3][:-5])
    if len(p) >= 3 and p[0] == "table-observations" and p[2] == "observation.json":
        return ("table_observation_artifact", "/".join(p[:2]), p[1])
    if len(p) >= 3 and p[0] == "round-analyses":
        if p[2] == "counterfactuals" and len(p) >= 5:
            return (
                "counterfactual_artifact",
                "/".join(p[:4]),
                f"{p[1]}/{p[3]}",
            )
        return ("analysis_artifact", "/".join(p[:2]), p[1])
    if len(p) >= 3 and p[0] == "legacy-round-analysis-artifacts":
        return ("legacy_analysis_artifact", "/".join(p[:2]), p[1])
    return None


def _parse_json(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    result = json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON value")),
    )
    if not isinstance(result, dict):
        raise ValueError("expected JSON object")
    return result


def _legacy_pipeline_manifest(manifest_raw: bytes, content_raw: bytes):
    """Read known v1 revision envelopes for migration without rewriting their content."""
    from doko_operations.pipeline_data import DataRevision

    manifest = _parse_json(manifest_raw)
    content = _parse_json(content_raw)
    if canonical_json_bytes(manifest) != manifest_raw:
        raise ValueError("legacy pipeline manifest is not canonical JSON")
    legacy_schemas = {
        ("card_scene_proposals", "proposed-card-scene-data/v1"): "proposed-card-scene-data/v2",
        ("visual_identities", "visual-identity-data/v1"): "visual-identity-data/v2",
    }
    old_schema = (manifest.get("content_type"), manifest.get("content_schema"))
    current_schema = legacy_schemas.get(old_schema)
    if current_schema is None or content.get("schema_version") != old_schema[1]:
        raise ValueError("legacy pipeline revision schema is unsupported")
    if hashlib.sha256(content_raw).hexdigest() != manifest.get("content_sha256"):
        raise ValueError("pipeline content digest does not match its manifest")
    if canonical_json_bytes(content) != content_raw:
        raise ValueError("legacy pipeline content is not canonical JSON")
    if "data_digest" in content:
        core = {key: value for key, value in content.items() if key != "data_digest"}
        if hashlib.sha256(canonical_json_bytes(core)).hexdigest() != content["data_digest"]:
            raise ValueError("legacy pipeline content digest does not match its contents")

    normalized_manifest = dict(manifest)
    normalized_manifest["content_schema"] = current_schema
    parsed = DataRevision.from_mapping(normalized_manifest)
    return parsed


def _legacy_calibration_summary(raw: Mapping[str, Any]) -> tuple[str, str, str]:
    """Validate historical calibration hashes and return its stable identities."""
    schema = raw.get("schema_version")
    expected = {
        "card-plane-calibration-run/v1": {
            "schema_version",
            "recording_id",
            "source_revision",
            "status",
            "candidate_receipts",
            "diagnostics",
            "calibration",
            "failure",
            "run_digest",
        },
        "card-plane-calibration-run/v2": {
            "schema_version",
            "recording_id",
            "source_revision",
            "status",
            "candidate_receipts",
            "diagnostics",
            "calibration",
            "failure",
            "run_digest",
        },
        "card-plane-calibration-run/v3": {
            "schema_version",
            "recording_id",
            "source_revision",
            "status",
            "candidate_receipts",
            "diagnostics",
            "calibration",
            "failure",
            "calibration_fit_candidate",
            "run_digest",
        },
    }.get(schema)
    if expected is None or set(raw) != expected:
        raise ValueError("calibration run schema is unsupported")
    if raw.get("status") != "published":
        raise ValueError("calibration revision is not a published run")
    core = {key: value for key, value in raw.items() if key != "run_digest"}
    if hashlib.sha256(canonical_json_bytes(core)).hexdigest() != raw["run_digest"]:
        raise ValueError("calibration run digest does not match its contents")
    calibration = raw["calibration"]
    if not isinstance(calibration, dict):
        raise ValueError("published calibration run has no calibration")
    if calibration.get("recording_id") != raw.get("recording_id"):
        raise ValueError("calibration recording identity differs from its run")
    if calibration.get("schema_version") not in {
        "table-plane-calibration/v1",
        "table-plane-calibration/v2",
    }:
        raise ValueError("table-plane calibration schema is unsupported")
    calibration_core = {
        key: value for key, value in calibration.items() if key != "calibration_digest"
    }
    if hashlib.sha256(canonical_json_bytes(calibration_core)).hexdigest() != calibration.get(
        "calibration_digest"
    ):
        raise ValueError("table-plane calibration digest does not match its contents")
    return (
        raw["recording_id"],
        raw["source_revision"],
        calibration["calibration_digest"],
    )


def _validate_automated_record(data: Mapping[str, Any], expected_id: str, *, coordinator: bool):
    """Validate immutable automated-run identity, state, stage rows, and request digests."""
    from dokodetector_backend.automated_pipeline_run import PIPELINE_STAGE_NAMES

    if coordinator:
        expected = {
            "coordinator_id",
            "failure",
            "recording_id",
            "schema_version",
            "stages",
            "status",
        }
        identity_field = "coordinator_id"
        supported_schema = "pipeline-coordinator-run/v1"
        statuses = {"running", "complete", "failed", "cancelled"}
    else:
        expected = {
            "client_request_sha256",
            "created_at",
            "failure",
            "recording_id",
            "request",
            "request_sha256",
            "resolved_providers",
            "run_id",
            "schema_version",
            "source",
            "stages",
            "status",
            "updated_at",
        }
        identity_field = "run_id"
        supported_schema = "automated-pipeline-run/v1"
        statuses = {"accepted", "queued", "running", "complete", "failed", "cancelled"}
    if (
        set(data) != expected
        or data.get("schema_version") != supported_schema
        or data.get(identity_field) != expected_id
        or data.get("status") not in statuses
        or not isinstance(data.get("recording_id"), str)
        or not isinstance(data.get("stages"), list)
    ):
        raise ValueError("automated run record has an unsupported contract")
    stages = data["stages"]
    if len(stages) != len(PIPELINE_STAGE_NAMES) or [
        stage.get("name") if isinstance(stage, dict) else None for stage in stages
    ] != list(PIPELINE_STAGE_NAMES):
        raise ValueError("automated run stages do not match the declared order")
    if coordinator:
        for stage in stages:
            if (
                not isinstance(stage, dict)
                or not {"name", "status", "run_id", "request", "request_sha256"} <= stage.keys()
                or not isinstance(stage["request"], dict)
                or hashlib.sha256(canonical_json_bytes(stage["request"])).hexdigest()
                != stage["request_sha256"]
            ):
                raise ValueError("coordinator stage request or digest is invalid")
    else:
        request = data.get("request")
        if (
            not isinstance(request, dict)
            or hashlib.sha256(canonical_json_bytes(request)).hexdigest()
            != data.get("request_sha256")
            or request.get("source") != data.get("source")
        ):
            raise ValueError("automated run request or digest is invalid")
    return data["recording_id"]


def inventory(
    roots: Mapping[str, Path | str],
    *,
    sealed: Sequence[Mapping[str, str]] = (),
    source_locations: Mapping[str, Mapping[str, str]] | None = None,
    snapshot_is_immutable: bool = False,
    scope_complete: bool = False,
    consumer_root_ids: Sequence[str] = (),
    reference_only_root_ids: Sequence[str] = (),
    lost_revision_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Inventory explicitly declared roots without changing them or reading sealed artifacts.

    A sealed entry gives root_id, relative_path, artifact_id and declared sha256. Callers must
    declare all relevant roots and sealed paths. Missing declarations cannot be discovered safely.
    """
    if snapshot_is_immutable is not True:
        raise ValueError("inventory requires a consistent immutable source snapshot")
    if not isinstance(scope_complete, bool):
        raise ValueError("scope_complete must be a boolean")
    if not roots:
        raise ValueError("at least one source root is required")
    normalized: dict[str, Path] = {}
    for root_id, raw in roots.items():
        if not isinstance(root_id, str) or not root_id.strip() or "/" in root_id:
            raise ValueError("invalid root ID")
        root = Path(raw).absolute()
        if root.is_symlink() or not root.is_dir() or root.resolve() != root:
            raise ValueError("source root must be an existing non-symlink directory")
        normalized[root_id] = root
    if len(set(consumer_root_ids)) != len(consumer_root_ids) or any(
        root_id not in normalized for root_id in consumer_root_ids
    ):
        raise ValueError("consumer roots must identify declared roots")
    if len(set(reference_only_root_ids)) != len(reference_only_root_ids) or any(
        root_id not in normalized for root_id in reference_only_root_ids
    ):
        raise ValueError("reference-only roots must identify declared roots")
    safe_revision_characters = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    )
    if (
        not isinstance(lost_revision_ids, Sequence)
        or isinstance(lost_revision_ids, (str, bytes))
        or any(
            not isinstance(revision_id, str)
            or not revision_id
            or any(character not in safe_revision_characters for character in revision_id)
            for revision_id in lost_revision_ids
        )
        or len(set(lost_revision_ids)) != len(lost_revision_ids)
    ):
        raise ValueError("lost revision IDs must be unique safe IDs")
    lost_revisions = set(lost_revision_ids)
    values = list(normalized.values())
    if any(
        a == b or a in b.parents or b in a.parents
        for i, a in enumerate(values)
        for b in values[i + 1 :]
    ):
        raise ValueError("source roots must not overlap")
    excluded: dict[str, set[str]] = defaultdict(set)
    sealed_values = []
    for item in sealed:
        if (
            set(item) != {"root_id", "relative_path", "artifact_id", "sha256"}
            or item["root_id"] not in normalized
        ):
            raise ValueError("invalid sealed artifact declaration")
        path = _relative(item["relative_path"])
        digest = item["sha256"]
        if (
            not item["artifact_id"]
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("sealed artifact needs an identity and declared digest")
        if path in excluded[item["root_id"]]:
            raise ValueError("duplicate sealed artifact")
        excluded[item["root_id"]].add(path)
        sealed_values.append(dict(item))
    locations: dict[str, dict[str, str]] = {}
    for source_path, location in (source_locations or {}).items():
        _relative(source_path)
        if set(location) != {"root_id", "path"} or location["root_id"] not in normalized:
            raise ValueError("invalid source location")
        locations[source_path] = {
            "root_id": location["root_id"],
            "path": _relative(location["path"]),
        }
    first = {
        root_id: _files(root, excluded[root_id]) for root_id, root in sorted(normalized.items())
    }
    manifest = [
        {
            "root_id": root_id,
            "path": path,
            "byte_length": details[0],
            "sha256": details[1],
        }
        for root_id, files in first.items()
        for path, details in sorted(files.items())
    ]
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    unmapped = []
    for file in manifest:
        classified = _resource(file["path"], root_id=file["root_id"])
        if classified is None:
            unmapped.append(file)
            continue
        kind, relative, old_id = classified
        groups[(file["root_id"], kind, relative, old_id)].append(file)
    conflicts: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    resources = []
    revision_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    revision_stores = {root_id: PipelineRevisionStore(root) for root_id, root in normalized.items()}
    run_stores = {
        root_id: ProcessorRunStore(root, revision_store=revision_stores[root_id])
        for root_id, root in normalized.items()
    }
    for (root_id, kind, relative, old_id), files in sorted(groups.items()):
        key = ["0107-migration/v1", kind, root_id, relative]
        item = {
            "kind": kind,
            "root_id": root_id,
            "relative_identity": relative,
            "old_id": old_id,
            "mapping_key": key,
            "new_id": str(uuid5(NAMESPACE, _json(key).decode("utf-8"))),
            "files": files,
            "references": [],
            "unknown_history": "not_recorded",
        }
        if kind in {
            "pipeline_revision",
            "maintained_draft",
            "independent_review",
            "calibration_revision",
            "calibration_draft",
        }:
            revision_key = ["0107-migration/v1", f"{kind}_content", root_id, relative]
            item["revision_mapping_key"] = revision_key
            item["new_revision_id"] = str(uuid5(NAMESPACE, _json(revision_key).decode("utf-8")))
        resources.append(item)
        if kind == "pipeline_revision":
            revision_ids[old_id].append(item)
    if len({item["new_id"] for item in resources}) != len(resources):
        conflicts.append({"kind": "mapping_collision"})
    for old_id, candidates in sorted(revision_ids.items()):
        if len(candidates) > 1:
            conflicts.append(
                {
                    "kind": "ambiguous_revision",
                    "revision_id": old_id,
                    "paths": [x["relative_identity"] for x in candidates],
                }
            )

    def issue(item: dict[str, Any], message: str) -> None:
        conflicts.append(
            {"kind": "invalid_resource", "resource": item["new_id"], "message": message}
        )

    def get(item: dict[str, Any], suffix: str) -> bytes:
        path = (
            item["relative_identity"]
            if item["kind"] in {"selection", "automated_run", "automated_run_receipt"}
            else f"{item['relative_identity']}/{suffix}"
        )
        expected = first[item["root_id"]][path]
        size, digest, raw = _stable_file(normalized[item["root_id"]] / path, capture=True)
        if (size, digest) != expected:
            raise ValueError("source snapshot changed during inventory")
        assert raw is not None
        return raw

    embedded_calibrations: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in resources:
        if candidate["kind"] != "pipeline_revision":
            continue
        try:
            raw_manifest = get(candidate, "manifest.json")
            raw_content = get(candidate, "content.json")
            revision_manifest = _parse_json(raw_manifest)
            content = _parse_json(raw_content)
            calibration = content.get("calibration")
            if (
                revision_manifest.get("content_type") != "card_scene_proposals"
                or not isinstance(calibration, dict)
                or not isinstance(content.get("calibration_revision_id"), str)
                or not isinstance(content.get("calibration_digest"), str)
                or hashlib.sha256(raw_content).hexdigest()
                != revision_manifest.get("content_sha256")
            ):
                continue
            core = {key: value for key, value in calibration.items() if key != "calibration_digest"}
            digest = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
            if (
                calibration.get("calibration_digest") != digest
                or content["calibration_digest"] != digest
                or calibration.get("calibration_revision_id") != content["calibration_revision_id"]
            ):
                continue
            embedded_calibrations[
                (revision_manifest.get("recording_id"), content["calibration_revision_id"], digest)
            ].append(candidate)
        except (KeyError, OSError, TypeError, ValueError):
            continue
    for evidence in embedded_calibrations.values():
        evidence.sort(key=lambda item: (item["root_id"], item["relative_identity"]))

    def source_reference(item: dict[str, Any], source: Any) -> None:
        if not isinstance(source, RecordingVideoSource):
            uncertainties.append(
                {"kind": "external_fixture_unverified", "resource": item["new_id"]}
            )
            return
        location = locations.get(source.relative_path)
        matches = [
            f
            for f in manifest
            if (
                f["path"] == source.relative_path
                if location is None
                else (f["root_id"], f["path"]) == (location["root_id"], location["path"])
            )
        ]
        declared = [
            s
            for s in sealed_values
            if (
                s["relative_path"] == source.relative_path
                if location is None
                else (s["root_id"], s["relative_path"]) == (location["root_id"], location["path"])
            )
        ]
        if len(matches) + len(declared) != 1:
            conflicts.append(
                {
                    "kind": "missing_or_ambiguous_source",
                    "resource": item["new_id"],
                    "path": source.relative_path,
                }
            )
            return
        if matches:
            found = matches[0]
            if found["sha256"] != source.video_sha256 or found["byte_length"] != source.byte_length:
                conflicts.append(
                    {
                        "kind": "source_digest_mismatch",
                        "resource": item["new_id"],
                        "path": source.relative_path,
                    }
                )
            item["references"].append(
                {
                    "role": "source_video",
                    "root_id": found["root_id"],
                    "path": found["path"],
                    "sha256": found["sha256"],
                }
            )
        else:
            found = declared[0]
            if found["sha256"] != source.video_sha256:
                conflicts.append(
                    {
                        "kind": "source_digest_mismatch",
                        "resource": item["new_id"],
                        "path": source.relative_path,
                    }
                )
            item["references"].append(
                {
                    "role": "source_video",
                    "root_id": found["root_id"],
                    "path": found["relative_path"],
                    "sha256": found["sha256"],
                    "verification": "not_recorded",
                }
            )

    def reference(item: dict[str, Any], role: str, old_id: Any) -> None:
        if old_id is None:
            return
        if not isinstance(old_id, str) or not old_id:
            issue(item, f"invalid {role} reference")
            return
        matches = revision_ids.get(old_id, [])
        ref = {
            "role": role,
            "old_revision_id": old_id,
            "target_id": matches[0]["new_id"] if len(matches) == 1 else None,
            "target_revision_id": matches[0]["new_revision_id"] if len(matches) == 1 else None,
        }
        if not matches and old_id in lost_revisions:
            ref["availability"] = "lost"
            item["references"].append(ref)
            uncertainties.append(
                {
                    "kind": "declared_lost_input",
                    "resource": item["new_id"],
                    "revision_id": old_id,
                    "resolution": "user_declared_lost",
                }
            )
            return
        item["references"].append(ref)
        if len(matches) != 1:
            conflicts.append(
                {
                    "kind": "dangling_revision" if not matches else "ambiguous_reference",
                    "resource": item["new_id"],
                    "role": role,
                    "revision_id": old_id,
                }
            )

    calibration_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    evidence_package_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    automated_run_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in resources:
        if item["kind"] == "calibration_revision":
            calibration_ids[item["old_id"]].append(item)
        elif item["kind"] == "evidence_package":
            evidence_package_ids[item["old_id"]].append(item)
        elif item["kind"] == "automated_run":
            automated_record = _parse_json(get(item, ""))
            is_coordinator = "/coordinator-runs/" in f"/{item['relative_identity']}"
            record_id = automated_record.get("coordinator_id" if is_coordinator else "run_id")
            if isinstance(record_id, str):
                if is_coordinator:
                    continue
                automated_run_ids[record_id].append(item)

    def calibration_reference(
        item: dict[str, Any], recording: str, role: str, old_id: str, digest: str
    ) -> None:
        matches = calibration_ids.get(f"{recording}/{old_id}", [])
        ref = {
            "role": role,
            "old_calibration_id": old_id,
            "sha256": digest,
            "target_id": matches[0]["new_id"] if len(matches) == 1 else None,
        }
        if not matches:
            evidence = embedded_calibrations.get((recording, old_id, digest), [])
            if evidence:
                ref["embedded_evidence_id"] = evidence[0]["new_id"]
                item["references"].append(ref)
                return
        item["references"].append(ref)
        if len(matches) != 1:
            conflicts.append(
                {
                    "kind": "dangling_calibration" if not matches else "ambiguous_calibration",
                    "resource": item["new_id"],
                    "revision_id": old_id,
                }
            )

    for item in resources:
        try:
            kind = item["kind"]
            if kind == "pipeline_revision":
                raw_manifest = _parse_json(get(item, "manifest.json"))
                try:
                    stored = revision_stores[root_id]._read_path(
                        normalized[root_id] / item["relative_identity"], validate_lineage=False
                    )
                    parsed = stored.manifest
                except ValueError as error:
                    if str(error) != "content_type and content_schema do not match":
                        raise
                    parsed = _legacy_pipeline_manifest(
                        canonical_json_bytes(raw_manifest), get(item, "content.json")
                    )
                if parsed.revision_id != item["old_id"]:
                    raise ValueError("revision identity differs from path")
                item["content_sha256"] = parsed.content_sha256
                item["content_type"] = parsed.content_type
                item["content_schema"] = raw_manifest["content_schema"]
                item["recording_id"] = parsed.recording_id
                source_reference(item, parsed.source)
                for old in parsed.input_revision_ids:
                    reference(item, "input", old)
                producer = parsed.producer.to_mapping()
                reference(item, "copy_base", producer.get("base_revision_id"))
            elif kind == "table_observation_artifact":
                observation = parse_observation_bytes(get(item, "observation.json"))
                if observation.observation_id != item["old_id"]:
                    raise ValueError("observation identity differs from path")
                item["recording_id"] = observation.source.recording_id
                item["content_sha256"] = hashlib.sha256(get(item, "observation.json")).hexdigest()
                for old in observation.source.input_revision_ids or ():
                    reference(item, "input", old)
            elif kind == "legacy_analysis_artifact":
                item["recording_id"] = None
                item["content_sha256"] = hashlib.sha256(
                    _json([file["sha256"] for file in item["files"]])
                ).hexdigest()
            elif kind == "selection":
                selected = parse_pipeline_selection_bytes(get(item, ""))
                if f"{selected.recording_id}/{selected.content_type}" != item["old_id"]:
                    raise ValueError("selection identity differs from path")
                item["content_type"] = selected.content_type
                item["recording_id"] = selected.recording_id
                reference(item, "generated", selected.selected_generated_revision_id)
                reference(
                    item, "completed_reference", selected.selected_completed_reference_revision_id
                )
            elif kind == "automated_run":
                coordinator = "/coordinator-runs/" in f"/{item['relative_identity']}"
                record = _parse_json(get(item, ""))
                record_id = record.get("coordinator_id" if coordinator else "run_id")
                if not isinstance(record_id, str):
                    raise ValueError("automated run identity is invalid")
                item["old_id"] = record_id
                item["recording_id"] = _validate_automated_record(
                    record, record_id, coordinator=coordinator
                )
                if coordinator:
                    for stage in record["stages"]:
                        processor_run_id = stage.get("processor_run_id")
                        if processor_run_id is not None:
                            run_matches = [
                                candidate
                                for candidate in resources
                                if candidate["kind"] == "processor_run"
                                and candidate["old_id"] == processor_run_id
                            ]
                            stage_reference = {
                                "role": "processor_stage_run",
                                "old_run_id": processor_run_id,
                                "target_id": run_matches[0]["new_id"]
                                if len(run_matches) == 1
                                else None,
                            }
                            if not run_matches:
                                # The coordinator record contains the full stage row. Keep its
                                # opaque run ID and stage data when no separate processor record
                                # exists in the snapshot.
                                stage_reference["availability"] = "embedded_in_coordinator"
                                uncertainties.append(
                                    {
                                        "kind": "processor_run_record_not_separate",
                                        "resource": item["new_id"],
                                        "run_id": processor_run_id,
                                    }
                                )
                            elif len(run_matches) > 1:
                                conflicts.append(
                                    {
                                        "kind": "ambiguous_processor_run",
                                        "resource": item["new_id"],
                                        "run_id": processor_run_id,
                                    }
                                )
                            item["references"].append(stage_reference)
                else:
                    for stage in record["stages"]:
                        stage_run_id = stage.get("run_id")
                        if stage_run_id is None:
                            continue
                        # The stage execution ID belongs to this immutable automated-run row.
                        # Keep it as an embedded reference; it is not a coordinator record ID.
                        item["references"].append(
                            {
                                "role": "embedded_stage_run",
                                "old_run_id": stage_run_id,
                                "target_id": None,
                                "availability": "embedded_in_automated_run",
                            }
                        )
            elif kind == "automated_run_receipt":
                receipt = _parse_json(get(item, ""))
                if set(receipt) != {"run_id"} or not isinstance(receipt["run_id"], str):
                    raise ValueError("automated run receipt is invalid")
                run_matches = automated_run_ids.get(receipt["run_id"], [])
                item["references"].append(
                    {
                        "role": "idempotent_run",
                        "old_run_id": receipt["run_id"],
                        "target_id": run_matches[0]["new_id"] if len(run_matches) == 1 else None,
                    }
                )
                if len(run_matches) != 1:
                    conflicts.append(
                        {
                            "kind": "missing_or_ambiguous_idempotent_run",
                            "resource": item["new_id"],
                            "run_id": receipt["run_id"],
                        }
                    )
            elif kind == "processor_run":
                stored = run_stores[root_id]._read_path(
                    normalized[root_id] / item["relative_identity"],
                    validate_output_revisions=False,
                    validate_output_lineage=False,
                    include_items=True,
                )
                request, state = stored.request, stored.state
                if request.run_id != item["old_id"] or state.run_id != item["old_id"]:
                    raise ValueError("run identity differs from path")
                source_reference(item, request.source)
                for old in request.input_revision_ids:
                    reference(item, "input", old)
                for old in state.output_revision_ids:
                    reference(item, "output", old)
            elif kind in {"maintained_draft", "independent_review"}:
                state = parse_reference_state_bytes(get(item, "state.json"))
                draft = parse_reference_draft_bytes(get(item, "draft.json"))
                if (
                    state.recording_id != draft.recording_id
                    or state.content_type != draft.content_type
                    or state.draft_revision != draft.revision
                    or state.source_revision_id != draft.source_revision_id
                ):
                    raise ValueError("draft and state do not match")
                item["content_type"] = state.content_type
                item["recording_id"] = state.recording_id
                if kind == "independent_review":
                    if state.content_type != "visible_cards":
                        raise ValueError("independent review must contain visible cards")
                    get(item, "commands.json")
                    recording, review_id = item["old_id"].split("/", 1)
                    VisibleCardReviewStore(
                        normalized[item["root_id"]] / "pipeline-reviews"
                    )._read_directory(
                        normalized[item["root_id"]] / item["relative_identity"],
                        recording,
                        review_id,
                    )
                    review = _parse_json(get(item, "review.json"))
                    if f"{review.get('recording_id')}/{review.get('review_id')}" != item["old_id"]:
                        raise ValueError("review identity differs from path")
                elif f"{state.recording_id}/{state.content_type}" != item["old_id"]:
                    raise ValueError("draft identity differs from path")
                reference(item, "proposal", draft.proposal_revision_id)
                if kind == "independent_review":
                    lineage = review.get("lineage", {})
                    if isinstance(lineage, dict):
                        reference(item, "detector", lineage.get("detector_revision_id"))
                        if lineage.get("calibration_revision_id") is not None:
                            calibration_reference(
                                item,
                                state.recording_id,
                                "calibration",
                                lineage["calibration_revision_id"],
                                lineage.get("calibration_digest"),
                            )
                reference(item, "base", state.source_revision_id)
                reference(item, "published", state.selected_completed_revision_id)
                uncertainties.append(
                    {"resource": item["new_id"], "kind": "item_history_not_recorded"}
                )
            elif kind == "analysis_artifact":
                state = _parse_json(get(item, "state.json"))
                request_raw = state.get("request_json")
                if not isinstance(request_raw, str):
                    raise ValueError("analysis request is not recorded")
                request_mapping = json.loads(request_raw)
                if not isinstance(request_mapping, dict):
                    raise ValueError("analysis request is not an object")
                analysis_id = request_mapping.get("analysis_id")
                if not isinstance(analysis_id, str):
                    raise ValueError("analysis request has no analysis ID")
                if analysis_id != item["relative_identity"].split("/")[
                    1
                ] or analysis_id != state.get("analysis_id"):
                    raise ValueError("analysis identity differs from path")
                if hashlib.sha256(request_raw.encode("utf-8")).hexdigest() != state.get(
                    "request_sha256"
                ):
                    raise ValueError("analysis request digest differs")
                legacy_revision_id = request_mapping.get("table_observation_revision_id")
                if legacy_revision_id is not None:
                    reference(item, "observations", legacy_revision_id)
                elif request_mapping.get("table_observation_node_ref") is None:
                    raise ValueError("analysis request has no observation input")
                correction_ids = request_mapping.get("correction_constraint_revision_ids", [])
                if not isinstance(correction_ids, list):
                    raise ValueError("analysis correction references are invalid")
                for revision_id in correction_ids:
                    reference(item, "correction_constraint", revision_id)
                item["analysis_context"] = {
                    key: request_mapping[key]
                    for key in (
                        "round_context",
                        "rules_version",
                        "search",
                        "round_setup",
                        "evidence_package_ids",
                    )
                    if key in request_mapping
                }
                for role in ("input", "result"):
                    artifact_id, digest = (
                        state.get(f"{role}_artifact_id"),
                        state.get(f"{role}_artifact_sha256"),
                    )
                    if artifact_id is None and digest is None:
                        continue
                    matching = [
                        f
                        for f in manifest
                        if f["path"] == artifact_id and f["root_id"] == item["root_id"]
                    ]
                    item["references"].append(
                        {"role": f"{role}_artifact", "artifact_id": artifact_id, "sha256": digest}
                    )
                    if len(matching) != 1 or matching[0]["sha256"] != digest:
                        conflicts.append(
                            {
                                "kind": "missing_or_changed_analysis_artifact",
                                "resource": item["new_id"],
                                "artifact_id": artifact_id,
                            }
                        )
                analysis = RoundAnalysisStore(
                    RoundAnalysisArtifactStorage(normalized[root_id])
                ).get(request.analysis_id)
                if analysis is None:
                    raise ValueError("round analysis state or artifact bytes are invalid")
                item["analysis_status"] = analysis.state
                for package_id in request.evidence_package_ids:
                    package_matches = evidence_package_ids.get(str(package_id), [])
                    item["references"].append(
                        {
                            "role": "evidence_package",
                            "old_package_id": str(package_id),
                            "target_id": (
                                package_matches[0]["new_id"] if len(package_matches) == 1 else None
                            ),
                        }
                    )
                    if len(package_matches) != 1:
                        conflicts.append(
                            {
                                "kind": "missing_or_ambiguous_evidence_package",
                                "resource": item["new_id"],
                                "package_id": str(package_id),
                            }
                        )
            elif kind == "calibration_revision":
                raw_run = _parse_json(get(item, "manifest.json"))
                try:
                    run = CalibrationRun.from_mapping(raw_run)
                    recording_id = run.recording_id
                    source_revision = run.source_revision
                    calibration = run.calibration
                    if calibration is None:
                        raise ValueError("published calibration run has no calibration")
                    calibration_id = calibration.calibration_revision_id
                    calibration_digest = calibration.calibration_digest
                except ValueError:
                    recording_id, source_revision, calibration_digest = _legacy_calibration_summary(
                        raw_run
                    )
                    calibration = raw_run["calibration"]
                    calibration_id = calibration["calibration_revision_id"]
                if f"{recording_id}/{calibration_id}" != item["old_id"]:
                    raise ValueError("calibration revision identity differs from path")
                item["calibration_digest"] = calibration_digest
                item["source_revision"] = source_revision
                reference(item, "detector", source_revision)
            elif kind == "evidence_package":
                package = EvidencePackageStore(
                    EvidencePackageStorage(normalized[item["root_id"]])
                ).get(item["old_id"])
                if package is None or str(package.package_id) != item["old_id"]:
                    raise ValueError("evidence package is invalid or differs from its path")
                item["session_id"] = str(package.session_id)
                item["event_sequence"] = package.event_sequence
                item["content_sha256"] = package.manifest_sha256
            elif kind == "calibration_draft":
                initial_raw, current_raw = get(item, "initial.json"), get(item, "draft.json")
                initial = CalibrationDraft.from_mapping(_parse_json(initial_raw))
                current = CalibrationDraft.from_mapping(_parse_json(current_raw))
                if f"{current.recording_id}/{current.draft_id}" != item["old_id"] or (
                    initial.recording_id,
                    initial.draft_id,
                ) != (current.recording_id, current.draft_id):
                    raise ValueError("calibration draft identity differs from path")
                initial_key = [
                    "0107-migration/v1",
                    "calibration_draft_initial",
                    item["root_id"],
                    item["relative_identity"],
                ]
                item["initial_revision_mapping_key"] = initial_key
                item["initial_revision_id"] = (
                    item["new_revision_id"]
                    if initial.to_mapping() == current.to_mapping()
                    else str(uuid5(NAMESPACE, _json(initial_key).decode("utf-8")))
                )
                for value in (initial, current):
                    reference(item, "detector", value.detector_revision_id)
                    calibration_reference(
                        item,
                        value.recording_id,
                        "base_calibration",
                        value.base_calibration_revision_id,
                        value.base_calibration_digest,
                    )
                uncertainties.append(
                    {"resource": item["new_id"], "kind": "intermediate_draft_history_not_recorded"}
                )
            elif kind == "calibration_reflow":
                receipt = CalibrationReflowReceipt.from_mapping(
                    _parse_json(get(item, "receipt.json"))
                )
                recording, receipt_id = item["old_id"].split("/", 1)
                if receipt.receipt_id != receipt_id:
                    raise ValueError("calibration receipt identity differs from path")
                reference(item, "proposal", receipt.proposal_revision_id)
                calibration_reference(
                    item,
                    recording,
                    "source_calibration",
                    receipt.source_calibration_revision_id,
                    receipt.source_calibration_digest,
                )
                calibration_reference(
                    item,
                    recording,
                    "target_calibration",
                    receipt.target_calibration_revision_id,
                    receipt.target_calibration_digest,
                )
            else:
                uncertainties.append(
                    {"resource": item["new_id"], "kind": "semantic_validation_required"}
                )
        except (KeyError, OSError, TypeError, ValueError) as error:
            issue(item, str(error))
    for item in resources:
        for ref in item["references"]:
            matches = revision_ids.get(ref.get("old_revision_id"), [])
            if len(matches) != 1 or "content_type" not in matches[0]:
                continue
            target = matches[0]
            if (
                item["kind"] in {"selection", "maintained_draft", "independent_review"}
                and ref["role"] in {"generated", "completed_reference", "base", "published"}
                and (
                    item.get("content_type") != target["content_type"]
                    or item.get("recording_id") != target.get("recording_id")
                )
            ):
                conflicts.append(
                    {
                        "kind": "revision_type_mismatch",
                        "resource": item["new_id"],
                        "revision_id": ref["old_revision_id"],
                    }
                )
    for item in resources:
        for ref in item["references"]:
            if "old_calibration_id" not in ref or ref["target_id"] is None:
                continue
            target = next((r for r in resources if r["new_id"] == ref["target_id"]), None)
            if target is not None and target.get("calibration_digest") != ref["sha256"]:
                conflicts.append(
                    {
                        "kind": "calibration_digest_mismatch",
                        "resource": item["new_id"],
                        "revision_id": ref["old_calibration_id"],
                    }
                )
    graph_edges: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for item in resources:
        current = ("resource", item["new_id"])
        for ref in item["references"]:
            target_id = ref.get("target_id")
            if target_id is None:
                continue
            target = ("resource", target_id)
            if item["kind"] == "pipeline_revision" and ref["role"] in {"input", "copy_base"}:
                graph_edges.append((target, current))
            if item["kind"] == "processor_run":
                graph_edges.append(
                    (current, target) if ref["role"] == "output" else (target, current)
                )
    try:
        _acyclic(graph_edges)
    except ValueError:
        conflicts.append({"kind": "lineage_cycle"})
    consumers = []
    needles = (
        "pipeline-references",
        "pipeline-reviews",
        "pipeline/selections",
        "round-analyses",
        "table-plane-calibrations",
    )
    for root_id in sorted(consumer_root_ids):
        for path, expected in sorted(first[root_id].items()):
            if Path(path).suffix not in {".py", ".ts", ".tsx", ".md", ".json", ".yaml", ".yml"}:
                continue
            size, digest, content = _stable_file(normalized[root_id] / path, capture=True)
            if (size, digest) != expected:
                raise ValueError("source snapshot changed during inventory")
            try:
                lines = content.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                uncertainties.append(
                    {"kind": "consumer_file_not_utf8", "root_id": root_id, "path": path}
                )
                continue
            for line_number, line in enumerate(lines, start=1):
                hits = [needle for needle in needles if needle in line]
                if hits:
                    consumers.append(
                        {"root_id": root_id, "path": path, "line": line_number, "references": hits}
                    )
    if not scope_complete:
        uncertainties.append({"kind": "source_scope_not_confirmed"})
    if consumers:
        uncertainties.append(
            {"kind": "consumer_references_need_classification", "count": len(consumers)}
        )
    referenced_lost_ids = {
        ref.get("old_revision_id")
        for item in resources
        for ref in item["references"]
        if ref.get("availability") == "lost"
    }
    for revision_id in sorted(lost_revisions - referenced_lost_ids):
        conflicts.append({"kind": "unused_lost_revision_declaration", "revision_id": revision_id})
    referenced_sources = {
        (ref["root_id"], ref["path"])
        for item in resources
        for ref in item["references"]
        if ref.get("role") == "source_video"
    }
    ignored_artifacts = [file for file in unmapped if Path(file["path"]).name == ".DS_Store"]
    unmapped = [
        file
        for file in unmapped
        if (file["root_id"], file["path"]) not in referenced_sources
        and Path(file["path"]).name != ".DS_Store"
    ]
    for file in unmapped:
        uncertainties.append(
            {"kind": "unclassified_artifact", "root_id": file["root_id"], "path": file["path"]}
        )
    for item in sealed_values:
        uncertainties.append(
            {"kind": "sealed_artifact_unverified", "artifact_id": item["artifact_id"]}
        )
    second = {
        root_id: _files(root, excluded[root_id]) for root_id, root in sorted(normalized.items())
    }
    if first != second:
        raise ValueError("source snapshot changed during inventory")
    # Include logical root IDs to distinguish equal paths in different roots.
    sealed_values.sort(key=lambda x: (x["root_id"], x["relative_path"]))
    snapshot_id = hashlib.sha256(
        _json({"files": manifest, "sealed_artifacts": sealed_values})
    ).hexdigest()
    return {
        "schema_version": "lineage-migration-inventory/v1",
        "snapshot_sha256": snapshot_id,
        "files": manifest,
        "resources": resources,
        "unclassified_files": unmapped,
        "ignored_artifacts": ignored_artifacts,
        "source_locations": locations,
        "reference_only_root_ids": sorted(reference_only_root_ids),
        "lost_revision_ids": sorted(lost_revisions),
        "scope_complete": scope_complete,
        "consumer_references": consumers,
        "sealed_artifacts": sorted(sealed_values, key=lambda x: (x["root_id"], x["relative_path"])),
        "conflicts": conflicts,
        "uncertainties": uncertainties,
        "activation_ready": not conflicts
        and not any(
            u["kind"]
            not in {
                "item_history_not_recorded",
                "intermediate_draft_history_not_recorded",
                "sealed_artifact_unverified",
                "declared_lost_input",
                "processor_run_record_not_separate",
            }
            for u in uncertainties
        ),
    }


def main() -> None:
    """Read explicit snapshot configuration and write a dry-run plan outside source roots."""
    import argparse

    from dokodetector_backend.filesystem import atomic_write_json

    parser = argparse.ArgumentParser(description="Inventory a read-only lineage migration snapshot")
    parser.add_argument("config", type=Path, help="JSON with roots, sealed, and source_locations")
    parser.add_argument("output", type=Path, help="plan JSON outside every source root")
    args = parser.parse_args()
    config = _parse_json(args.config.read_bytes())
    if set(config) - {
        "roots",
        "sealed",
        "source_locations",
        "snapshot_is_immutable",
        "scope_complete",
        "consumer_root_ids",
        "reference_only_root_ids",
        "lost_revision_ids",
    } or not isinstance(config.get("roots"), dict):
        parser.error("config needs roots and optional sealed and source_locations")
    output = args.output.absolute().resolve()
    for source in config["roots"].values():
        root = Path(source).absolute().resolve()
        if output == root or root in output.parents:
            parser.error("output must be outside all source roots")
    plan = inventory(
        config["roots"],
        sealed=config.get("sealed", ()),
        source_locations=config.get("source_locations"),
        snapshot_is_immutable=config.get("snapshot_is_immutable", False),
        scope_complete=config.get("scope_complete", False),
        consumer_root_ids=config.get("consumer_root_ids", ()),
        reference_only_root_ids=config.get("reference_only_root_ids", ()),
        lost_revision_ids=config.get("lost_revision_ids", ()),
    )
    atomic_write_json(output, plan)


if __name__ == "__main__":
    main()
