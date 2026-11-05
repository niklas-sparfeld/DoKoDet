"""Project retained draft content without treating pending items as reviewed."""

from __future__ import annotations

import json
from typing import Any

from doko_operations.pipeline_reference import PipelineReferenceDraft

from dokodetector_backend.pipeline_reference_handlers import build_reference_handlers


def project_draft(draft: PipelineReferenceDraft) -> dict[str, Any]:
    """Separate current content from the original item decisions and coverage."""
    handlers = build_reference_handlers(
        source_for=lambda *_: None, selected_revision=lambda *_: None
    )
    handler = handlers[draft.content_type]
    ordered = handler.order_items(draft.items)
    if (
        draft.content_type == "visible_cards"
        and draft.proposal_revision_id is None
        and any(item.item.get("card_scene") is not None for item in ordered)
    ):
        raise ValueError("retained scenes have no exact proposal revision")
    retained = [item for item in ordered if item.review_state != "rejected"]
    content_items = []
    content_retained = []
    scene_only_items = []
    for item in retained:
        value = dict(item.item)
        if draft.content_type == "visible_cards":
            scene = value.pop("card_scene", None)
            if (
                scene is not None
                and value.get("status") == "detected"
                and not value.get("candidates")
                and not value.get("ignored_regions")
                and not value.get("pile_regions")
            ):
                scene_only_items.append(item.item_id)
                continue
        content_items.append(value)
        content_retained.append(item)
    content = {
        "schema_version": handler.content_schema,
        handler.content_key: content_items,
    }
    # Validate the projected content without changing classifier or provenance fields.
    content = json.loads(handler.canonical_content_bytes(content))
    return {
        "content": content,
        "pointers": {
            item.item_id: f"/{handler.content_key}/{index}"
            for index, item in enumerate(content_retained)
        },
        "legacy_items": [item.to_mapping() for item in ordered],
        "scene_only_items": scene_only_items,
        "coverage": draft.coverage,
        "impact": list(draft.impact),
    }


def import_draft(
    store: Any,
    draft: PipelineReferenceDraft,
    legacy_key: str,
    source_node_id: str,
    source_revision_id: str,
    legacy_state: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Publish one deterministic draft node and its recorded decisions.

    This function is for verified migration input. Replaying an unchanged input is safe.
    It never updates an existing node or infers a reviewer.
    """
    from uuid import NAMESPACE_URL, uuid5

    from doko_operations.pipeline_data import canonical_json_bytes, sha256_bytes

    from dokodetector_backend.pipeline_item_provenance import _items
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import NodeConflict

    source = store.get(source_node_id)
    source_revision = store.read_revision(source_node_id, source_revision_id)
    if (
        source.content_type != draft.content_type
        or source.source.get("recording_id") != draft.recording_id
    ):
        raise ValueError("draft source does not match recording or content type")
    if source_revision.metadata.get("legacy_revision_id") != draft.source_revision_id:
        raise ValueError("draft source does not match its retained revision ID")
    projection = project_draft(draft)
    digest = sha256_bytes(canonical_json_bytes(draft.to_mapping()))
    node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{legacy_key}"))
    revision_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-revision:{legacy_key}:{digest}"))
    metadata = {
        "copied_from": {"node_id": source_node_id, "revision_id": source_revision_id},
        "migration": {
            "legacy_key": legacy_key,
            "draft_sha256": digest,
            "updated_at": draft.updated_at,
        },
        "legacy_review": {
            "items": projection["legacy_items"],
            "coverage": projection["coverage"],
            "impact": projection["impact"],
            "scene_only_items": projection["scene_only_items"],
            "state": legacy_state,
        },
        "item_provenance": {
            "version": 1,
            "items": _items(projection["content"], projection["pointers"]),
            "changes": [],
        },
    }
    try:
        stored = store.create(
            node_id,
            f"Imported {draft.content_type.replace('_', ' ')} draft",
            draft.content_type,
            source.source,
            projection["content"],
            metadata,
            revision_id=revision_id,
        )
    except NodeConflict:
        try:
            stored = store.read_revision(node_id, revision_id)
        except FileNotFoundError:
            raise NodeConflict("imported draft key is already used by different input") from None
        if stored.content != projection["content"] or stored.metadata != metadata:
            raise NodeConflict("imported draft differs from the retained input") from None
    reviews = PipelineNodeReviews(store)
    reviewer = {"kind": "not_recorded", "id": None}
    evidence = {"policy": "legacy-draft-import/v1", "draft_sha256": digest}
    decisions = []
    for item in draft.items:
        if item.item_id not in projection["pointers"] or item.review_state not in {
            "accepted",
            "empty",
            "unusable",
            "face_down",
            "identity_unusable",
            "source_problem",
        }:
            continue
        review_id = str(
            uuid5(NAMESPACE_URL, f"lineage-draft-item:{legacy_key}:{digest}:{item.item_id}")
        )
        decisions.append(
            {"review_id": review_id, "item_id": item.item_id, "decision": item.review_state}
        )
    reviews.items(node_id, revision_id, decisions, "Retained item decision", reviewer, evidence)
    if draft.coverage and draft.proposal_revision_id is None:
        review_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-coverage:{legacy_key}:{digest}"))
        reviews.coverage(
            review_id, node_id, revision_id, "Retained coverage", draft.coverage, reviewer, evidence
        )
    if (
        legacy_state is not None
        and legacy_state["draft_state"] == "completed"
        and draft.proposal_revision_id is None
    ):
        review_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-overall:{legacy_key}:{digest}"))
        reviews.overall(
            review_id,
            node_id,
            revision_id,
            "Retained data-set completion",
            "complete",
            reviewer,
            evidence,
        )
    return {"node_id": node_id, "revision_id": stored.revision_id}


def project_scene_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """Keep exact scene geometry and the original review facts for one frame."""
    from table_evidence_analyzer.card_scene_contract import CardSceneDraft

    from dokodetector_backend.virtual_scene_data import from_draft, validate_virtual_scenes

    raw = frame["card_scene"]
    if raw.get("schema_version") == "card-scene-draft/v1":
        draft = CardSceneDraft.from_mapping(raw, "card_scene")
        if draft.proposal.status == "supported":
            try:
                return from_draft(
                    draft,
                    frame["frame_identity"],
                    pile_regions=frame.get("pile_regions", []),
                    ignore_regions=frame.get("ignored_regions", []),
                )
            except ValueError as error:
                if (
                    str(error) != "partial proposal requires an explicit complete scene"
                    or draft.completion.state != "unusable"
                ):
                    raise
        calibration_id = draft.proposal.calibration_revision_id
        calibration_digest = draft.proposal.calibration_digest
        geometry = None
        frame_id = draft.proposal.source_frame_id
        if frame["frame_identity"]["image_sha256"] != draft.proposal.source_frame_digest:
            raise ValueError("draft frame identity does not match proposal")
    elif raw.get("schema_version") == "reviewed-card-scene-editor/v1":
        geometry = raw.get("scene")
        calibration_source = geometry or raw.get("initialized_scene")
        if calibration_source is None:
            raise ValueError("legacy scene has no recorded calibration")
        calibration_id = calibration_source["calibration_revision_id"]
        calibration_digest = calibration_source["calibration_digest"]
        frame_id = calibration_source["source_frame_id"]
    else:
        raise ValueError("unsupported retained scene format")
    content = validate_virtual_scenes(
        {
            "schema_version": "virtual-scene-data/v1",
            "frames": [
                {
                    "frame_id": frame_id,
                    "frame_identity": frame["frame_identity"],
                    "calibration": {"revision_id": calibration_id, "digest": calibration_digest},
                    "scene": geometry,
                    "pile_regions": frame.get("pile_regions", []),
                    "ignore_regions": frame.get("ignored_regions", []),
                }
            ],
        }
    )
    return {
        "content": content,
        "source_draft": raw,
        "legacy_review": raw,
        "geometry_unavailable": raw.get("schema_version") == "card-scene-draft/v1",
    }


def import_draft_scenes(
    store: Any,
    draft: PipelineReferenceDraft,
    legacy_key: str,
    proposal_node_id: str,
    proposal_revision_id: str,
    legacy_state: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Publish retained scene frames separately from visible-region data."""
    from uuid import NAMESPACE_URL, uuid5

    from doko_operations.pipeline_data import canonical_json_bytes, sha256_bytes

    from dokodetector_backend.pipeline_item_provenance import _items
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import NodeConflict
    from dokodetector_backend.virtual_scene_data import validate_virtual_scenes

    source = store.get(proposal_node_id)
    proposal = store.read_revision(proposal_node_id, proposal_revision_id)
    if (
        source.content_type != "card_scene_proposals"
        or source.source.get("recording_id") != draft.recording_id
        or proposal.metadata.get("legacy_revision_id") != draft.proposal_revision_id
    ):
        raise ValueError("draft proposal does not match its retained source")
    projected = [
        (item, project_scene_frame(dict(item.item)))
        for item in draft.items
        if item.review_state != "rejected" and item.item.get("card_scene") is not None
    ]
    if not projected:
        return None
    content = validate_virtual_scenes(
        {
            "schema_version": "virtual-scene-data/v1",
            "frames": [item[1]["content"]["frames"][0] for item in projected],
        }
    )
    digest = sha256_bytes(canonical_json_bytes(draft.to_mapping()))
    node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-scenes:{legacy_key}"))
    revision_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-scenes-revision:{legacy_key}:{digest}"))
    metadata = {
        "copied_from": {"node_id": proposal_node_id, "revision_id": proposal_revision_id},
        "migration": {
            "legacy_key": legacy_key,
            "draft_sha256": digest,
            "updated_at": draft.updated_at,
        },
        "legacy_state": legacy_state,
        "legacy_scenes": {
            frame["frame_id"]: {
                "review": result["legacy_review"],
                "geometry_unavailable": result.get("geometry_unavailable", False),
            }
            for frame, (_, result) in zip(content["frames"], projected, strict=True)
        },
        "item_provenance": {
            "version": 1,
            "items": _items(
                content,
                {frame["frame_id"]: f"/frames/{i}" for i, frame in enumerate(content["frames"])},
            ),
            "changes": [],
        },
    }
    try:
        stored = store.create(
            node_id,
            "Imported virtual scenes",
            "virtual_scenes",
            source.source,
            content,
            metadata,
            revision_id=revision_id,
        )
    except NodeConflict:
        try:
            stored = store.read_revision(node_id, revision_id)
        except FileNotFoundError:
            raise NodeConflict("imported scene key is already used by different input") from None
        if stored.content != content or stored.metadata != metadata:
            raise NodeConflict("imported scenes differ from the retained input") from None
    reviews = PipelineNodeReviews(store)
    if legacy_state is not None and legacy_state["draft_state"] == "completed":
        review_id = str(uuid5(NAMESPACE_URL, f"lineage-scene-overall:{legacy_key}:{digest}"))
        reviews.overall(
            review_id,
            node_id,
            revision_id,
            "Retained data-set completion",
            "complete",
            {"kind": "not_recorded", "id": None},
            {"policy": "legacy-draft-import/v1", "draft_sha256": digest},
        )
    if draft.coverage:
        coverage_id = str(uuid5(NAMESPACE_URL, f"lineage-scene-coverage:{legacy_key}:{digest}"))
        reviews.coverage(
            coverage_id,
            node_id,
            revision_id,
            "Retained coverage",
            draft.coverage,
            {"kind": "not_recorded", "id": None},
            {"policy": "legacy-draft-import/v1", "draft_sha256": digest},
        )
    decisions = []
    for frame, (_, result) in zip(content["frames"], projected, strict=True):
        facts = result["legacy_review"]
        completion = facts.get("completion", {}).get("state", facts.get("completion_state"))
        if completion not in {"complete", "unusable"}:
            continue
        review_id = str(
            uuid5(
                NAMESPACE_URL,
                f"lineage-draft-scene-review:{legacy_key}:{digest}:{frame['frame_id']}",
            )
        )
        decisions.append(
            {"review_id": review_id, "item_id": frame["frame_id"], "decision": completion}
        )
    reviews.items(
        node_id,
        revision_id,
        decisions,
        "Retained frame decision",
        {"kind": "not_recorded", "id": None},
        {"policy": "legacy-draft-import/v1", "draft_sha256": digest},
    )
    return {"node_id": node_id, "revision_id": stored.revision_id}


def import_staged_drafts(package_root: Any, store_root: Any) -> dict[str, int]:
    """Import drafts from the matching verified migration package into a staged store."""
    import hashlib
    from pathlib import Path

    from doko_operations.pipeline_reference import (
        parse_reference_draft_bytes,
        parse_reference_state_bytes,
    )

    from dokodetector_backend.filesystem import contained_path
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    package = Path(package_root).expanduser().resolve()
    store = PipelineNodeStore(store_root)
    manifest = json.loads((package / "migration.json").read_bytes())
    mapping = json.loads((store.root / ".legacy-revision-map.json").read_bytes())
    if (
        manifest.get("schema_version") != "lineage-migration-stage/v1"
        or not manifest.get("activation_ready")
        or mapping.get("schema_version") != "legacy-revision-map/v1"
        or mapping.get("snapshot_sha256") != manifest.get("snapshot_sha256")
    ):
        raise ValueError("draft import snapshot does not match the staged node store")
    revisions = mapping["revisions"]
    prepared = []
    for resource in manifest["resources"]:
        if resource["kind"] not in {"maintained_draft", "independent_review"}:
            continue

        def read_file(name: str, resource: dict[str, Any] = resource) -> bytes:
            files = [item for item in resource["files"] if item["path"].endswith(f"/{name}")]
            if len(files) != 1:
                raise ValueError(f"retained draft must have exactly one {name} file")
            file = files[0]
            evidence_root = contained_path(package / "evidence", resource["old_root_id"])
            raw = contained_path(evidence_root, file["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != file["sha256"] or (
                "byte_length" in file and len(raw) != file["byte_length"]
            ):
                raise ValueError("retained draft file does not match the verified package")
            return raw

        draft = parse_reference_draft_bytes(read_file("draft.json"))
        state = parse_reference_state_bytes(read_file("state.json"))
        if (
            state.recording_id != draft.recording_id
            or state.content_type != draft.content_type
            or state.draft_revision != draft.revision
            or state.source_revision_id != draft.source_revision_id
        ):
            raise ValueError("retained draft state does not match its content")
        targets = []
        for old_id in (draft.source_revision_id, draft.proposal_revision_id):
            if old_id is None:
                targets.append(None)
                continue
            target = revisions.get(old_id)
            if target is None or not any(
                ref.get("old_revision_id") == old_id
                and ref.get("target_id") == target["node_id"]
                and ref.get("target_revision_id") == target["revision_id"]
                for ref in resource["references"]
            ):
                raise ValueError(f"retained draft revision is not mapped: {old_id}")
            targets.append(target)
        if targets[0] is None:
            raise ValueError("retained draft has no exact source revision")
        prepared.append((resource, draft, state.to_mapping(), targets))
    scene_count = 0
    for resource, draft, state, targets in prepared:
        key = f"{resource['kind']}/{resource['old_id']}"
        source, proposal = targets
        import_draft(store, draft, key, source["node_id"], source["revision_id"], state)
        if proposal is not None:
            scene_count += (
                import_draft_scenes(
                    store, draft, key, proposal["node_id"], proposal["revision_id"], state
                )
                is not None
            )
    return {"drafts": len(prepared), "scene_nodes": scene_count}
