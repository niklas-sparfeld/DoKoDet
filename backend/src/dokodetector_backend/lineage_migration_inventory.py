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
    parse_data_revision_manifest_bytes,
    parse_pipeline_selection_bytes,
    parse_processor_run_request_bytes,
    parse_processor_run_state_bytes,
)
from doko_operations.pipeline_reference import (
    parse_reference_draft_bytes,
    parse_reference_state_bytes,
)
from table_evidence_analyzer.card_scene_contract import CalibrationDraft, CalibrationReflowReceipt

from dokodetector_backend.pipeline_lineage import _acyclic
from dokodetector_backend.pipeline_store import PipelineRevisionStore
from dokodetector_backend.round_analysis_contract import parse_round_analysis_create_request_bytes
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


def _resource(path: str) -> tuple[str, str, str] | None:
    p = path.split("/")
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
        and p[2] in {"runs", "idempotency"}
        and p[3].endswith(".json")
    ):
        return ("automated_run" if p[2] == "runs" else "automated_run_receipt", path, p[3][:-5])
    if len(p) >= 2 and p[0] == "round-analyses":
        return ("analysis_artifact", path, path)
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


def inventory(
    roots: Mapping[str, Path | str],
    *,
    sealed: Sequence[Mapping[str, str]] = (),
    source_locations: Mapping[str, Mapping[str, str]] | None = None,
    snapshot_is_immutable: bool = False,
    scope_complete: bool = False,
    consumer_root_ids: Sequence[str] = (),
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
        classified = _resource(file["path"])
        if classified is None:
            unmapped.append(file)
            continue
        kind, relative, old_id = classified
        groups[(file["root_id"], kind, relative, old_id)].append(file)
    conflicts: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    resources = []
    revision_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
            if item["kind"]
            in {"selection", "automated_run", "automated_run_receipt", "analysis_artifact"}
            else f"{item['relative_identity']}/{suffix}"
        )
        expected = first[item["root_id"]][path]
        size, digest, raw = _stable_file(normalized[item["root_id"]] / path, capture=True)
        if (size, digest) != expected:
            raise ValueError("source snapshot changed during inventory")
        assert raw is not None
        return raw

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
    for item in resources:
        if item["kind"] == "calibration_revision":
            calibration_ids[item["old_id"]].append(item)

    def calibration_reference(
        item: dict[str, Any], recording: str, role: str, old_id: str, digest: str
    ) -> None:
        matches = calibration_ids.get(f"{recording}/{old_id}", [])
        item["references"].append(
            {
                "role": role,
                "old_calibration_id": old_id,
                "sha256": digest,
                "target_id": matches[0]["new_id"] if len(matches) == 1 else None,
            }
        )
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
                manifest_raw, content = get(item, "manifest.json"), get(item, "content.json")
                parsed = parse_data_revision_manifest_bytes(manifest_raw)
                if parsed.revision_id != item["old_id"]:
                    raise ValueError("revision identity differs from path")
                PipelineRevisionStore._validate_payload_bytes(parsed, content, manifest_raw)
                item["content_sha256"] = parsed.content_sha256
                item["content_type"] = parsed.content_type
                item["recording_id"] = parsed.recording_id
                source_reference(item, parsed.source)
                for old in parsed.input_revision_ids:
                    reference(item, "input", old)
                producer = parsed.producer.to_mapping()
                reference(item, "copy_base", producer.get("base_revision_id"))
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
            elif kind == "processor_run":
                request = parse_processor_run_request_bytes(get(item, "request.json"))
                state = parse_processor_run_state_bytes(get(item, "state.json"))
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
            elif (
                kind == "analysis_artifact"
                and item["relative_identity"].endswith("/state.json")
                and len(item["relative_identity"].split("/")) == 3
            ):
                state = _parse_json(get(item, ""))
                request_raw = state.get("request_json")
                if not isinstance(request_raw, str):
                    raise ValueError("analysis request is not recorded")
                request = parse_round_analysis_create_request_bytes(request_raw.encode("utf-8"))
                if str(request.analysis_id) != item["relative_identity"].split("/")[1] or str(
                    request.analysis_id
                ) != state.get("analysis_id"):
                    raise ValueError("analysis identity differs from path")
                if hashlib.sha256(request_raw.encode("utf-8")).hexdigest() != state.get(
                    "request_sha256"
                ):
                    raise ValueError("analysis request digest differs")
                reference(item, "observations", request.table_observation_revision_id)
                for revision_id in request.correction_constraint_revision_ids:
                    reference(item, "correction_constraint", revision_id)
                item["analysis_context"] = {
                    "round_context": request.model_dump(mode="json")["round_context"],
                    "rules_version": request.rules_version,
                    "search": request.search.model_dump(mode="json"),
                    "round_setup": request.model_dump(mode="json")["round_setup"],
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
                if request.evidence_package_ids:
                    uncertainties.append(
                        {
                            "kind": "evidence_package_reference_validation_required",
                            "resource": item["new_id"],
                            "ids": [str(i) for i in request.evidence_package_ids],
                        }
                    )
                uncertainties.append(
                    {"resource": item["new_id"], "kind": "analysis_state_validation_required"}
                )
            elif kind == "calibration_revision":
                run = CalibrationRun.from_mapping(_parse_json(get(item, "manifest.json")))
                if (
                    run.calibration is None
                    or f"{run.recording_id}/{run.calibration.calibration_revision_id}"
                    != item["old_id"]
                ):
                    raise ValueError("calibration revision identity differs from path")
                item["calibration_digest"] = run.calibration.calibration_digest
                reference(item, "detector", run.source_revision)
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
    referenced_sources = {
        (ref["root_id"], ref["path"])
        for item in resources
        for ref in item["references"]
        if ref.get("role") == "source_video"
    }
    unmapped = [
        file for file in unmapped if (file["root_id"], file["path"]) not in referenced_sources
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
        "source_locations": locations,
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
    )
    atomic_write_json(output, plan)


if __name__ == "__main__":
    main()
