"""Import a verified lineage migration package into an isolated node store."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import canonical_json_bytes, parse_pipeline_selection_bytes
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    ProposedCardSceneFrame,
)

from dokodetector_backend.filesystem import atomic_write_json, contained_path
from dokodetector_backend.pipeline_lineage import PipelineLineage, _key, _reference
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore
from dokodetector_backend.pipeline_store import _canonical_timestamp, _safe_id


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _resource_file(package: Path, resource: dict[str, Any], suffix: str) -> Path:
    matches = [item for item in resource["files"] if item["path"].endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"resource must have one {suffix} file: {resource['old_id']}")
    path = package / "evidence" / resource["old_root_id"] / matches[0]["path"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != matches[0]["sha256"]:
        raise ValueError(f"resource file digest changed: {matches[0]['path']}")
    return path


def _normalize_content(
    content: dict[str, Any], content_type: str
) -> tuple[dict[str, Any], dict[str, str]]:
    """Move known v1 payloads to the current node-store content contract."""
    normalized = dict(content)
    provenance: dict[str, str] = {}
    if content_type == "events":
        for event in normalized.get("events", []):
            if event["event_type"] != "card_state_changed":
                provenance[event["event_id"]] = event["event_type"]
                event["event_type"] = "card_state_changed"
    elif content_type == "visual_identities" and normalized.get("schema_version") == (
        "visual-identity-data/v1"
    ):
        for outcome in normalized.get("outcomes", []):
            outcome.setdefault("crop_input_provenance", None)
            outcome.setdefault("annotation_provenance", None)
            crop_input = outcome.get("crop_input_provenance")
            if isinstance(crop_input, dict) and crop_input.get("schema_version") == (
                "visual-identity-crop-input-provenance/v1"
            ):
                crop_input["schema_version"] = "visual-identity-crop-input-provenance/v2"
    if content_type == "visual_identities" and normalized.get("schema_version") == (
        "visual-identity-data/v1"
    ):
        normalized["schema_version"] = "visual-identity-data/v2"
    elif content_type == "card_scene_proposals" and normalized.get("schema_version") == (
        "proposed-card-scene-data/v1"
    ):
        upgraded = ProposedCardSceneData.create(
            detector_revision_id=normalized["detector_revision_id"],
            detector_revision_digest=normalized["detector_revision_digest"],
            calibration_revision_id=normalized["calibration_revision_id"],
            calibration_digest=normalized["calibration_digest"],
            calibration=normalized["calibration"],
            calibration_diagnostics=normalized["calibration_diagnostics"],
            frames=tuple(
                ProposedCardSceneFrame.from_mapping(frame, f"frames[{index}]")
                for index, frame in enumerate(normalized["frames"])
            ),
        )
        normalized = upgraded.to_mapping()
    return normalized, provenance


def _pipeline_revisions(
    package: Path,
    resources: list[dict[str, Any]],
    store: PipelineNodeStore,
    snapshot_sha256: str,
) -> dict[str, tuple[str, str]]:
    """Create one immutable node for each retained legacy revision."""
    mapping: dict[str, tuple[str, str]] = {}
    revisions = [item for item in resources if item["kind"] == "pipeline_revision"]
    for item in revisions:
        manifest = _object(_resource_file(package, item, "/manifest.json"))
        revision_id = item["new_revision_id"]
        node_id = item["new_id"]
        source = manifest["source"]
        node_path = store.root / node_id
        revision_path = node_path / "revisions" / revision_id / "revision.json"
        if node_path.exists():
            node = store.get(node_id)
            revision_record = _object(revision_path)
            metadata = revision_record.get("metadata", {})
            if (
                node.content_type != manifest["content_type"]
                or node.source != source
                or revision_record.get("node_id") != node_id
                or revision_record.get("revision_id") != revision_id
                or metadata.get("legacy_revision_id") != item["old_id"]
                or metadata.get("legacy_content_sha256") != manifest["content_sha256"]
                or metadata.get("migration_snapshot_sha256") != snapshot_sha256
            ):
                raise ValueError(f"migration target has different revision data: {item['old_id']}")
            mapping[item["old_id"]] = (node_id, revision_id)
            continue
        content_path = _resource_file(package, item, "/content.json")
        original_content = _object(content_path)
        content, provenance = _normalize_content(original_content, manifest["content_type"])
        metadata: dict[str, Any] = {
            "origin": manifest["origin"],
            "legacy_revision_id": item["old_id"],
            "legacy_created_at": manifest["created_at"],
            "legacy_content_schema": manifest["content_schema"],
            "legacy_content_sha256": manifest["content_sha256"],
            "coverage": manifest["coverage"],
            "producer": manifest["producer"],
            "unknown_history": item["unknown_history"],
            "migration_snapshot_sha256": snapshot_sha256,
        }
        if provenance:
            metadata["legacy_event_types"] = provenance
        for reference in item["references"]:
            if reference.get("role") == "copy_base" and reference.get("target_id") is not None:
                metadata["copied_from"] = {
                    "node_id": reference["target_id"],
                    "revision_id": reference["target_revision_id"],
                }
                break
        name = f"{manifest['content_type'].replace('_', ' ').title()} {item['old_id'][:8]}"
        try:
            store.create(
                node_id,
                name,
                manifest["content_type"],
                source,
                content,
                metadata,
                revision_id=revision_id,
            )
        except NodeConflict:
            node = store.get(node_id)
            revision_record = _object(revision_path)
            expected_digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest()
            if (
                node.content_type != manifest["content_type"]
                or node.source != source
                or revision_record.get("node_id") != node_id
                or revision_record.get("revision_id") != revision_id
                or revision_record.get("content_sha256") != expected_digest
                or revision_record.get("metadata") != metadata
            ):
                raise ValueError(
                    f"migration target has different revision data: {item['old_id']}"
                ) from None
        mapping[item["old_id"]] = (node_id, revision_id)
    return mapping


def _run_refs(
    resource: dict[str, Any], role: str
) -> tuple[list[dict[str, str]], list[tuple[str, str]], list[str]]:
    refs: list[dict[str, str]] = []
    pairs: list[tuple[str, str]] = []
    lost: list[str] = []
    for reference in resource["references"]:
        if reference.get("role") != role:
            continue
        old_id = reference.get("old_revision_id")
        if reference.get("availability") == "lost":
            if old_id is not None:
                lost.append(old_id)
            continue
        target_id = reference.get("target_id")
        target_revision_id = reference.get("target_revision_id")
        if target_id is None or target_revision_id is None:
            continue
        ref = {
            "kind": "revision",
            "node_id": target_id,
            "revision_id": target_revision_id,
            "role": role,
        }
        refs.append(ref)
        pairs.append((target_id, target_revision_id))
    return refs, pairs, lost


def _import_runs(
    package: Path,
    resources: list[dict[str, Any]],
    mapping: dict[str, tuple[str, str]],
    store: PipelineNodeStore,
) -> int:
    lineage = PipelineLineage(store)
    resource_by_old = {item["old_id"]: item for item in resources}
    imported = 0
    for item in resources:
        if item["kind"] != "processor_run":
            continue
        request = _object(_resource_file(package, item, "/request.json"))
        state = _object(_resource_file(package, item, "/state.json"))
        run_id = item["new_id"]
        inputs, pairs, lost_inputs = _run_refs(item, "input")
        outputs, _, _ = _run_refs(item, "output")
        if not inputs:
            source = request.get("source", {})
            video_digest = source.get("video_sha256")
            if not isinstance(video_digest, str):
                raise ValueError(f"run has no usable inputs or recording digest: {item['old_id']}")
            inputs = [
                {
                    "kind": "artifact",
                    "artifact_id": f"recording-video/{source.get('recording_id', 'unknown')}",
                    "sha256": video_digest,
                    "role": "recording_video",
                }
            ]
        _safe_id(run_id, "run_id")
        accepted_inputs = [
            {"node_id": node_id, "revision_id": revision_id} for node_id, revision_id in pairs
        ]
        accepted_inputs.sort(key=lambda item: (item["node_id"], item["revision_id"]))
        accepted_record = {
            "schema_version": "pipeline-accepted-use/v1",
            "run_id": run_id,
            "inputs": accepted_inputs,
            "accepted_at": _canonical_timestamp(None),
        }
        _write_once(store.root / ".accepted-uses", run_id, accepted_record, "accepted_at")
        processor = {
            "implementation": request.get("implementation")
            or {"name": request["processor_type"], "version": "legacy"},
            "model": request.get("model"),
            "configuration": request.get("configuration", {}),
            "policies": {
                "extraction": request.get("extraction_policy"),
                "crop": request.get("crop_policy"),
            },
        }
        context = {
            "recording_id": request.get("source", {}).get("recording_id"),
            "legacy_run_id": item["old_id"],
            "attempt": state.get("attempt", 1),
            "legacy_status": state.get("status"),
            "lost_input_revision_ids": sorted(lost_inputs),
            "request_digest": hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
        }
        input_refs = sorted(
            (_reference(ref) for ref in inputs), key=lambda ref: (_key(ref), ref["role"])
        )
        request_record = {
            "schema_version": "pipeline-lineage-request/v1",
            "run_id": run_id,
            "inputs": input_refs,
            "run_kind": "processor",
            "processor": processor,
            "context": context,
            "started_at": _canonical_timestamp(None),
        }
        _write_once(lineage.requests, run_id, request_record, "started_at")
        status = state.get("status")
        if status in {"complete", "partial", "failed", "cancelled"}:
            status = {"complete": "succeeded"}.get(status, status)
            result = None
            failure = None
            if status in {"succeeded", "partial"}:
                if not outputs:
                    if status == "succeeded":
                        raise ValueError(f"successful run has no migrated output: {item['old_id']}")
                else:
                    output_resources = [
                        resource_by_old[reference["old_revision_id"]]
                        for reference in item["references"]
                        if reference.get("role") == "output"
                        and reference.get("old_revision_id") in resource_by_old
                    ]
                    result = (
                        "empty"
                        if output_resources
                        and all(
                            _resource_content_empty(package, resource)
                            for resource in output_resources
                        )
                        else "nonempty"
                    )
            elif status == "failed":
                failure = state.get("terminal_failure") or {"code": "legacy_processor_failed"}
            output_refs = sorted(
                (_reference(ref) for ref in outputs), key=lambda ref: (_key(ref), ref["role"])
            )
            run_record = {
                "schema_version": "pipeline-lineage-run/v1",
                "run_id": run_id,
                "inputs": input_refs,
                "outputs": output_refs,
                "status": status,
                "run_kind": "processor",
                "result": result,
                "processor": processor,
                "context": context,
                "failure": failure,
                "finished_at": _canonical_timestamp(None),
            }
            _write_once(lineage.root, run_id, run_record, "finished_at")
        imported += 1
    return imported


def _write_once(root: Path, record_id: str, record: dict[str, Any], timestamp_key: str) -> None:
    path = contained_path(root, f"{_safe_id(record_id, 'record_id')}.json")
    if path.exists():
        existing = _object(path)
        if {key: value for key, value in existing.items() if key != timestamp_key} != {
            key: value for key, value in record.items() if key != timestamp_key
        }:
            raise ValueError(f"migration target has conflicting lineage: {record_id}")
        return
    atomic_write_json(path, record)


def _resource_content_empty(package: Path, resource: dict[str, Any]) -> bool:
    content = _object(_resource_file(package, resource, "/content.json"))
    for key in ("events", "outcomes", "frames", "observations", "identities"):
        if key in content:
            return not content[key]
    return False


def _import_analyses(
    package: Path,
    resources: list[dict[str, Any]],
    mapping: dict[str, tuple[str, str]],
    store: PipelineNodeStore,
) -> int:
    """Publish retained round analyses as exact lineage runs."""
    lineage = PipelineLineage(store)
    imported = 0
    resource_by_new_id = {item["new_id"]: item for item in resources}
    for item in resources:
        if item["kind"] != "analysis_artifact":
            continue
        state = _object(_resource_file(package, item, "/state.json"))
        input_reference = next(
            (ref for ref in item["references"] if ref.get("role") == "input_artifact"), None
        )
        input_data = (
            {} if input_reference is None else _object(_resource_file(package, item, "/input.json"))
        )
        request = state.get("request_json", "{}")
        if isinstance(request, str):
            request = json.loads(request)
        if not isinstance(request, dict):
            raise ValueError(f"analysis request is invalid: {item['old_id']}")

        inputs: list[dict[str, str]] = []
        pairs: list[tuple[str, str]] = []
        for reference in item["references"]:
            if reference.get("role") == "observations":
                target_id = reference.get("target_id")
                target_revision_id = reference.get("target_revision_id")
                if target_id is None or target_revision_id is None:
                    continue
                old_revision_id = reference.get("old_revision_id")
                if old_revision_id not in mapping:
                    raise ValueError(f"analysis observation is not mapped: {old_revision_id}")
                mapped = mapping[old_revision_id]
                if mapped != (target_id, target_revision_id):
                    raise ValueError(f"analysis observation map differs: {old_revision_id}")
                inputs.append(
                    {
                        "kind": "revision",
                        "node_id": target_id,
                        "revision_id": target_revision_id,
                        "role": "table_observations",
                    }
                )
                pairs.append((target_id, target_revision_id))
            elif reference.get("role") == "evidence_package":
                package_resource = resource_by_new_id[reference["target_id"]]
                digest = package_resource.get("content_sha256")
                package_id = reference.get("old_package_id")
                if not isinstance(digest, str) or not isinstance(package_id, str):
                    raise ValueError(
                        f"analysis evidence package has no exact digest: {item['old_id']}"
                    )
                inputs.append(
                    {
                        "kind": "artifact",
                        "artifact_id": f"evidence-package/{package_id}",
                        "sha256": digest,
                        "role": "evidence_package",
                    }
                )
            elif reference.get("role") == "input_artifact":
                inputs.append(
                    {
                        "kind": "artifact",
                        "artifact_id": reference["artifact_id"],
                        "sha256": reference["sha256"],
                        "role": "input_artifact",
                    }
                )
        if not inputs:
            raise ValueError(f"analysis has no retained inputs: {item['old_id']}")

        context_value = request.get("round_context", request.get("round_setup"))
        if not isinstance(context_value, dict):
            context_value = {
                key: input_data[key]
                for key in (
                    "game_id",
                    "round_id",
                    "active_players",
                    "dealer",
                    "first_trick_leader",
                )
                if key in input_data
            }
        rules = input_data.get("ruleset", request.get("rules", {}))
        if not isinstance(rules, dict):
            rules = {"version": str(request.get("rules_version", "unknown"))}
        search_settings = request.get("search", request.get("search_settings", {}))
        if not isinstance(search_settings, dict):
            search_settings = {}
        context = {
            "round_context": context_value,
            "rules": rules,
            "search_settings": search_settings,
            "recording_id": state.get("recording_id"),
            "legacy_analysis_id": item["old_id"],
            "result_status": state.get("result_status"),
        }
        run_id = f"analysis-{state['analysis_id']}"
        accepted = {
            "schema_version": "pipeline-accepted-use/v1",
            "run_id": run_id,
            "inputs": [
                {"node_id": node_id, "revision_id": revision_id}
                for node_id, revision_id in sorted(pairs)
            ],
            "accepted_at": _canonical_timestamp(None),
        }
        _write_once(store.root / ".accepted-uses", run_id, accepted, "accepted_at")
        processor = {
            "implementation": {"name": "round-analysis", "version": "1"},
            "model": None,
            "configuration": {},
            "policies": {},
        }
        inputs = sorted(
            (_reference(reference) for reference in inputs),
            key=lambda reference: (_key(reference), reference["role"]),
        )
        request_record = {
            "schema_version": "pipeline-lineage-request/v1",
            "run_id": run_id,
            "inputs": inputs,
            "run_kind": "analysis",
            "processor": processor,
            "context": context,
            "started_at": _canonical_timestamp(None),
        }
        _write_once(lineage.requests, run_id, request_record, "started_at")
        outputs = [
            {
                "kind": "artifact",
                "artifact_id": reference["artifact_id"],
                "sha256": reference["sha256"],
                "role": "result_artifact",
            }
            for reference in item["references"]
            if reference.get("role") == "result_artifact"
        ]
        status = state.get("state")
        if status in {"complete", "failed", "cancelled"}:
            failure = None
            result = None
            if status == "complete":
                status = "succeeded"
                if not outputs:
                    raise ValueError(f"completed analysis has no result artifact: {item['old_id']}")
                result = "nonempty"
            elif status == "failed":
                failure = {
                    "code": "legacy_analysis_failed",
                    "message": state.get("error") or "analysis failed",
                }
            outputs = sorted(
                (_reference(reference) for reference in outputs),
                key=lambda reference: (_key(reference), reference["role"]),
            )
            record = {
                "schema_version": "pipeline-lineage-run/v1",
                "run_id": run_id,
                "inputs": inputs,
                "outputs": outputs,
                "status": status,
                "run_kind": "analysis",
                "result": result,
                "processor": processor,
                "context": context,
                "failure": failure,
                "finished_at": _canonical_timestamp(None),
            }
            _write_once(lineage.root, run_id, record, "finished_at")
        imported += 1
    return imported


def _import_selections(
    package: Path,
    resources: list[dict[str, Any]],
    mapping: dict[str, tuple[str, str]],
    store: PipelineNodeStore,
) -> int:
    """Store migrated selection pointers as exact node and revision identities."""
    root = store.root / ".migrated-selections"
    imported = 0
    for item in resources:
        if item["kind"] != "selection":
            continue
        source = _resource_file(package, item, ".json")
        selection = parse_pipeline_selection_bytes(source.read_bytes())
        references = {
            reference["role"]: reference
            for reference in item["references"]
            if reference.get("role") in {"generated", "completed_reference"}
        }
        mapped: dict[str, dict[str, str] | None] = {}
        for role, legacy_id in (
            ("generated", selection.selected_generated_revision_id),
            ("completed_reference", selection.selected_completed_reference_revision_id),
        ):
            if legacy_id is None:
                mapped[role] = None
                continue
            reference = references.get(role)
            target = mapping.get(legacy_id)
            if reference is None or target is None:
                raise ValueError(f"selection revision is not mapped: {legacy_id}")
            expected = (reference.get("target_id"), reference.get("target_revision_id"))
            if target != expected:
                raise ValueError(f"selection mapping differs from migration plan: {legacy_id}")
            mapped[role] = {"node_id": target[0], "revision_id": target[1]}
        record = {
            "schema_version": "pipeline-node-selection/v1",
            "recording_id": selection.recording_id,
            "content_type": selection.content_type,
            "revision": selection.revision,
            "selected_generated": mapped["generated"],
            "selected_completed_reference": mapped["completed_reference"],
            "updated_at": selection.updated_at,
            "legacy_selection_id": item["old_id"],
        }
        path = contained_path(
            root / selection.recording_id,
            f"{selection.content_type}.json",
        )
        if path.exists():
            existing = _object(path)
            if existing != record:
                raise ValueError(f"migration target has conflicting selection: {item['old_id']}")
        else:
            atomic_write_json(path, record)
        imported += 1
    return imported


def _import_retained_records(
    package: Path,
    resources: list[dict[str, Any]],
    mapping: dict[str, tuple[str, str]],
    store: PipelineNodeStore,
    *,
    kinds: set[str],
    snapshot_sha256: str,
) -> dict[str, int]:
    """Preserve editable drafts and independent reviews with mapped lineage references."""
    counts = {kind: 0 for kind in kinds}
    root = store.root / ".migrated-records"
    reader_root = store.root / ".migrated-readers"
    reader_prefixes = {
        "maintained_draft": "pipeline-references/",
        "independent_review": "pipeline-reviews/",
    }
    for item in resources:
        kind = item["kind"]
        if kind not in kinds:
            continue
        files: dict[str, dict[str, Any]] = {}
        for file_record in item["files"]:
            relative_path = file_record["path"]
            source = contained_path(package / "evidence" / item["old_root_id"], relative_path)
            payload = source.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != file_record["sha256"] or len(payload) != file_record["byte_length"]:
                raise ValueError(f"resource file digest changed: {relative_path}")
            files[relative_path] = {
                "sha256": digest,
                "byte_length": len(payload),
                "base64": base64.b64encode(payload).decode("ascii"),
            }
            prefix = reader_prefixes.get(kind)
            if prefix is not None and relative_path.startswith(prefix):
                reader_path = contained_path(reader_root, relative_path)
                if reader_path.exists():
                    if reader_path.read_bytes() != payload:
                        raise ValueError(f"migration reader target differs: {relative_path}")
                else:
                    atomic_write_json(reader_path, payload)
            elif kind == "calibration_draft":
                reader_path = contained_path(reader_root / "calibration-drafts", relative_path)
                if reader_path.exists():
                    if reader_path.read_bytes() != payload:
                        raise ValueError(f"migration reader target differs: {relative_path}")
                else:
                    atomic_write_json(reader_path, payload)
        references = []
        for reference in item["references"]:
            copied = dict(reference)
            old_revision_id = reference.get("old_revision_id")
            if old_revision_id is not None and reference.get("availability") != "lost":
                target = mapping.get(old_revision_id)
                expected = (reference.get("target_id"), reference.get("target_revision_id"))
                if target is None or target != expected:
                    raise ValueError(f"retained record reference is not mapped: {old_revision_id}")
                copied["mapped_revision"] = {"node_id": target[0], "revision_id": target[1]}
            references.append(copied)
        record = {
            "schema_version": "pipeline-migrated-record/v1",
            "kind": kind,
            "old_id": item["old_id"],
            "snapshot_sha256": snapshot_sha256,
            "files": files,
            "references": references,
        }
        key = hashlib.sha256(f"{kind}/{item['old_id']}".encode("utf-8")).hexdigest()
        path = contained_path(root / kind, f"{key}.json")
        if path.exists():
            if _object(path) != record:
                raise ValueError(f"migration target has conflicting record: {item['old_id']}")
        else:
            atomic_write_json(path, record)
        counts[kind] += 1
    return counts


def import_package(package_root: Path | str, store_root: Path | str) -> dict[str, int]:
    """Load retained processor revisions and runs into an isolated node-store root."""
    package = Path(package_root).expanduser().resolve()
    manifest = _object(package / "migration.json")
    if manifest.get("schema_version") != "lineage-migration-stage/v1" or not manifest.get(
        "activation_ready"
    ):
        raise ValueError("migration package is not activation-ready")
    store = PipelineNodeStore(store_root)
    mapping = _pipeline_revisions(
        package, manifest["resources"], store, manifest["snapshot_sha256"]
    )
    run_count = _import_runs(package, manifest["resources"], mapping, store)
    analysis_count = _import_analyses(package, manifest["resources"], mapping, store)
    selection_count = _import_selections(package, manifest["resources"], mapping, store)
    retained_counts = _import_retained_records(
        package,
        manifest["resources"],
        mapping,
        store,
        kinds={"maintained_draft", "independent_review", "calibration_draft"},
        snapshot_sha256=manifest["snapshot_sha256"],
    )
    nodes = store.list_nodes()
    if len(nodes) != len(mapping):
        raise ValueError("imported node count does not match the migration plan")
    expected_heads = {node_id: revision_id for node_id, revision_id in mapping.values()}
    for node in nodes:
        if expected_heads.get(node.node_id) != node.head_revision_id:
            raise ValueError("imported node head does not match the migration plan")
    lineage = PipelineLineage(store)
    request_count = len(tuple(lineage.requests.glob("*.json")))
    terminal_count = len(tuple(lineage.root.glob("*.json")))
    if request_count != run_count + analysis_count or terminal_count > request_count:
        raise ValueError("imported processor run counts do not match the migration plan")
    summary = {
        "schema_version": "lineage-migration-import/v1",
        "snapshot_sha256": manifest["snapshot_sha256"],
        "resource_count": len(manifest["resources"]),
        "pipeline_revisions": len(mapping),
        "processor_runs": run_count,
        "analysis_runs": analysis_count,
        "selections": selection_count,
        **retained_counts,
        "terminal_runs": terminal_count,
    }
    atomic_write_json(
        store.root / ".legacy-revision-map.json",
        {
            "schema_version": "legacy-revision-map/v1",
            "snapshot_sha256": manifest["snapshot_sha256"],
            "revisions": {
                old_id: {"node_id": node_id, "revision_id": revision_id}
                for old_id, (node_id, revision_id) in sorted(mapping.items())
            },
        },
    )
    atomic_write_json(store.root / ".migration-import.json", summary)
    return {
        "pipeline_revisions": len(mapping),
        "processor_runs": run_count,
        "analysis_runs": analysis_count,
        "selections": selection_count,
        **retained_counts,
        "nodes": len(nodes),
        "lineage_runs": terminal_count,
    }


__all__ = ["import_package"]
