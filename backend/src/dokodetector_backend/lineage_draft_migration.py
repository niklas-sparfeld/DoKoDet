"""Offline import and verification for retained lineage migration inputs."""

from __future__ import annotations

import json
from typing import Any

from doko_operations.pipeline_reference import PipelineReferenceDraft

from dokodetector_backend.lineage_draft_projection import project_draft, project_scene_frame


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

    from dokodetector_backend.calibration_reflow_context import build_calibration_reflow_context
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
        "scene_only_frame_ids": projection["scene_only_items"],
        "excluded_items": [
            {"item_id": item.item_id, "decision": "rejected"}
            for item in draft.items
            if item.review_state == "rejected"
        ],
        "item_provenance": {
            "version": 1,
            "items": _items(projection["content"], projection["pointers"]),
            "changes": [],
        },
    }
    if draft.content_type == "visible_cards":
        legacy_revision_map = json.loads((store.root / ".legacy-revision-map.json").read_bytes())
        proposal_pointer = (
            None
            if draft.proposal_revision_id is None
            else legacy_revision_map["revisions"][draft.proposal_revision_id]
        )
        metadata["calibration_reflow_context"] = build_calibration_reflow_context(
            draft,
            source_revision_id=source_revision_id,
            proposal_revision_id=(
                None if proposal_pointer is None else proposal_pointer["revision_id"]
            ),
        )
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
            "corrected",
            "added",
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


def project_scene_review_facts(raw: dict[str, Any]) -> dict[str, Any]:
    """Read review facts from retained migration input without storing a legacy adapter."""
    from table_evidence_analyzer.card_scene_contract import CardSceneDraft

    if raw.get("schema_version") == "card-scene-draft/v1":
        draft = CardSceneDraft.from_mapping(raw, "card_scene")
        return {
            "card_states": [state.to_mapping() for state in draft.card_states],
            "completion": draft.completion.to_mapping(),
        }
    if raw.get("schema_version") == "reviewed-card-scene-editor/v1":
        return raw
    raise ValueError("unsupported retained scene review format")


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
            "geometry_unavailable_frame_ids": [
                frame["frame_id"]
                for frame, (_, result) in zip(content["frames"], projected, strict=True)
                if result.get("geometry_unavailable", False)
            ],
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
    for frame, (item, _result) in zip(content["frames"], projected, strict=True):
        facts = project_scene_review_facts(item.item["card_scene"])
        completion = facts.get("completion", {}).get("state", facts.get("completion_state"))
        decision = completion if completion in {"complete", "unusable"} else "pending"
        state_facts = facts.get("card_states", facts.get("card_review_states", []))
        state_summary = ", ".join(
            f"{entry['card_id']}: {entry['state']}"
            for entry in state_facts
            if isinstance(entry, dict)
            and isinstance(entry.get("card_id"), str)
            and isinstance(entry.get("state"), str)
        )
        reason = facts.get("completion", {}).get("reason", facts.get("completion_reason"))
        question = "Retained frame review"
        if state_summary:
            question += f". Card states: {state_summary}"
        if isinstance(reason, str) and reason:
            question += f". Completion reason: {reason}"
        review_id = str(
            uuid5(
                NAMESPACE_URL,
                f"lineage-draft-scene-review:{legacy_key}:{digest}:{frame['frame_id']}",
            )
        )
        decisions.append(
            (
                {"review_id": review_id, "item_id": frame["frame_id"], "decision": decision},
                question,
            )
        )
    for decision, question in decisions:
        reviews.item(
            decision["review_id"],
            node_id,
            revision_id,
            decision["item_id"],
            question,
            decision["decision"],
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


def verify_active_draft_snapshot(package_root: Any, store_root: Any) -> int:
    """Check retained draft files against the staged snapshot before activation.

    Call this while all writers to the active store are stopped. A changed or new file
    requires a new inventory instead of importing an outdated snapshot.
    """
    import hashlib
    from pathlib import Path
    from uuid import NAMESPACE_URL, uuid5

    from doko_operations.pipeline_data import canonical_json_bytes, sha256_bytes
    from doko_operations.pipeline_reference import parse_reference_draft_bytes

    from dokodetector_backend.filesystem import contained_path
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    package = Path(package_root).expanduser().resolve()
    root = Path(store_root).expanduser().resolve()
    manifest = json.loads((package / "migration.json").read_bytes())
    mapping = json.loads((root / ".legacy-revision-map.json").read_bytes())
    if (
        manifest.get("schema_version") != "lineage-migration-stage/v1"
        or not manifest.get("activation_ready")
        or mapping.get("schema_version") != "legacy-revision-map/v1"
        or mapping.get("snapshot_sha256") != manifest.get("snapshot_sha256")
    ):
        raise ValueError("active draft snapshot does not match the migration package")
    reader_root = root / ".migrated-readers"
    expected = set()
    for resource in manifest["resources"]:
        if resource["kind"] not in {"maintained_draft", "independent_review"}:
            continue
        for file in resource["files"]:
            path = file["path"]
            if not path.startswith(("pipeline-references/", "pipeline-reviews/")):
                raise ValueError("retained draft path is outside the reader store")
            expected.add(path)
            target = contained_path(reader_root, path)
            if target.is_symlink() or not target.is_file():
                raise ValueError(f"retained draft file is missing: {path}")
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() != file["sha256"] or (
                "byte_length" in file and len(raw) != file["byte_length"]
            ):
                raise ValueError(f"retained draft file changed: {path}")
    actual = {
        file.relative_to(reader_root).as_posix()
        for group in ("pipeline-references", "pipeline-reviews")
        for file in (reader_root / group).rglob("*")
        if (file.is_file() or file.is_symlink()) and not file.name.startswith(".")
    }
    if actual != expected:
        raise ValueError("retained draft files changed since the migration snapshot")
    store = PipelineNodeStore(root)
    for resource in manifest["resources"]:
        if resource["kind"] not in {"maintained_draft", "independent_review"}:
            continue
        key = f"{resource['kind']}/{resource['old_id']}"
        for prefix, revision_prefix in (
            ("lineage-draft:", "lineage-draft-revision:"),
            ("lineage-draft-scenes:", "lineage-draft-scenes-revision:"),
        ):
            node_id = str(uuid5(NAMESPACE_URL, prefix + key))
            if not (root / node_id).exists():
                continue
            draft_file = next(f for f in resource["files"] if f["path"].endswith("/draft.json"))
            draft = parse_reference_draft_bytes(
                contained_path(reader_root, draft_file["path"]).read_bytes()
            )
            digest = sha256_bytes(canonical_json_bytes(draft.to_mapping()))
            revision_id = str(uuid5(NAMESPACE_URL, f"{revision_prefix}{key}:{digest}"))
            try:
                revision = store.read_revision(node_id, revision_id)
            except (OSError, KeyError, ValueError) as error:
                raise ValueError(
                    "active draft import target conflicts with existing data"
                ) from error
            migration = revision.metadata.get("migration")
            if (
                not isinstance(migration, dict)
                or migration.get("legacy_key") != key
                or migration.get("draft_sha256") != digest
            ):
                raise ValueError("active draft import target conflicts with existing data")
    return len(expected)


def verify_staged_drafts(package_root: Any, store_root: Any) -> dict[str, int]:
    """Verify imported draft content, lineage, and decisions against the staged inputs."""
    import hashlib
    from pathlib import Path
    from uuid import NAMESPACE_URL, uuid5

    from doko_operations.pipeline_data import canonical_json_bytes, sha256_bytes
    from doko_operations.pipeline_reference import (
        parse_reference_draft_bytes,
        parse_reference_state_bytes,
    )

    from dokodetector_backend.calibration_reflow_context import build_calibration_reflow_context
    from dokodetector_backend.filesystem import contained_path
    from dokodetector_backend.pipeline_item_provenance import _items
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore
    from dokodetector_backend.virtual_scene_data import validate_virtual_scenes

    package = Path(package_root).expanduser().resolve()
    store = PipelineNodeStore(store_root)
    manifest = json.loads((package / "migration.json").read_bytes())
    mapping = json.loads((store.root / ".legacy-revision-map.json").read_bytes())
    if not manifest.get("activation_ready") or manifest.get("snapshot_sha256") != mapping.get(
        "snapshot_sha256"
    ):
        raise ValueError("staged draft snapshot does not match")
    revisions = mapping["revisions"]
    reviews = PipelineNodeReviews(store)
    counts = {"drafts": 0, "scene_nodes": 0, "reviews": 0}
    verified_sources = {}

    def verify_source(old_id: str, recording_id: str, content_type: str) -> dict[str, str]:
        target = revisions[old_id]
        pair = (target["node_id"], target["revision_id"])
        if pair not in verified_sources:
            source_node = store.get(pair[0])
            source_revision = store.read_revision(pair[0], pair[1])
            verified_sources[pair] = (source_node, source_revision)
        source_node, source_revision = verified_sources[pair]
        if (
            source_node.source.get("recording_id") != recording_id
            or source_node.content_type != content_type
            or source_revision.metadata.get("legacy_revision_id") != old_id
        ):
            raise ValueError("staged draft source identity differs from the migration plan")
        return target

    for resource in manifest["resources"]:
        if resource["kind"] not in {"maintained_draft", "independent_review"}:
            continue

        def read_file(name: str, resource: dict[str, Any] = resource) -> bytes:
            files = [f for f in resource["files"] if f["path"].endswith(f"/{name}")]
            if len(files) != 1:
                raise ValueError("retained draft file is missing")
            file = files[0]
            raw = contained_path(
                contained_path(package / "evidence", resource["old_root_id"]), file["path"]
            ).read_bytes()
            if hashlib.sha256(raw).hexdigest() != file["sha256"]:
                raise ValueError("retained draft input digest changed")
            return raw

        draft = parse_reference_draft_bytes(read_file("draft.json"))
        state = parse_reference_state_bytes(read_file("state.json")).to_mapping()
        key = f"{resource['kind']}/{resource['old_id']}"
        digest = sha256_bytes(canonical_json_bytes(draft.to_mapping()))
        node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{key}"))
        revision_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-revision:{key}:{digest}"))
        revision = store.read_revision(node_id, revision_id)
        projection = project_draft(draft)
        source = verify_source(draft.source_revision_id, draft.recording_id, draft.content_type)
        if (
            revision.content != projection["content"]
            or revision.metadata.get("copied_from") != source
            or revision.metadata.get("item_provenance", {}).get("items")
            != _items(revision.content, projection["pointers"])
            or revision.metadata.get("scene_only_frame_ids") != projection["scene_only_items"]
            or revision.metadata.get("excluded_items")
            != [
                {"item_id": item.item_id, "decision": "rejected"}
                for item in draft.items
                if item.review_state == "rejected"
            ]
        ):
            raise ValueError(f"staged draft differs from its source: {key}")
        if draft.content_type == "visible_cards":
            proposal = (
                None
                if draft.proposal_revision_id is None
                else verify_source(
                    draft.proposal_revision_id, draft.recording_id, "card_scene_proposals"
                )
            )
            if revision.metadata.get("calibration_reflow_context") != (
                build_calibration_reflow_context(
                    draft,
                    source_revision_id=source["revision_id"],
                    proposal_revision_id=(None if proposal is None else proposal["revision_id"]),
                )
            ):
                raise ValueError(f"staged calibration context differs from its source: {key}")
        counts["drafts"] += 1
        expected = []
        for item in draft.items:
            if item.item_id in projection["pointers"] and item.review_state in {
                "accepted",
                "corrected",
                "added",
                "empty",
                "unusable",
                "face_down",
                "identity_unusable",
                "source_problem",
            }:
                expected.append(
                    (
                        str(
                            uuid5(
                                NAMESPACE_URL, f"lineage-draft-item:{key}:{digest}:{item.item_id}"
                            )
                        ),
                        "item",
                        item.item_id,
                        item.review_state,
                    )
                )
        if draft.coverage and draft.proposal_revision_id is None:
            expected.append(
                (
                    str(uuid5(NAMESPACE_URL, f"lineage-draft-coverage:{key}:{digest}")),
                    "coverage",
                    None,
                    None,
                )
            )
        if state["draft_state"] == "completed" and draft.proposal_revision_id is None:
            expected.append(
                (
                    str(uuid5(NAMESPACE_URL, f"lineage-draft-overall:{key}:{digest}")),
                    "overall",
                    None,
                    "complete",
                )
            )
        draft_review_ids = {entry[0] for entry in expected}
        scene_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-scenes:{key}"))
        if draft.proposal_revision_id is not None:
            projected = [
                (item, project_scene_frame(dict(item.item)))
                for item in draft.items
                if item.review_state != "rejected" and item.item.get("card_scene") is not None
            ]
            if projected:
                scene_revision_id = str(
                    uuid5(NAMESPACE_URL, f"lineage-draft-scenes-revision:{key}:{digest}")
                )
                scene_revision = store.read_revision(scene_id, scene_revision_id)
                scene_content = validate_virtual_scenes(
                    {
                        "schema_version": "virtual-scene-data/v1",
                        "frames": [result["content"]["frames"][0] for _, result in projected],
                    }
                )
                if (
                    scene_revision.content != scene_content
                    or scene_revision.metadata.get("copied_from")
                    != verify_source(
                        draft.proposal_revision_id, draft.recording_id, "card_scene_proposals"
                    )
                    or scene_revision.metadata.get("migration", {}).get(
                        "geometry_unavailable_frame_ids"
                    )
                    != [
                        frame["frame_id"]
                        for frame, (_, result) in zip(
                            scene_content["frames"], projected, strict=True
                        )
                        if result.get("geometry_unavailable", False)
                    ]
                    or scene_revision.metadata.get("item_provenance", {}).get("items")
                    != _items(
                        scene_content,
                        {
                            frame["frame_id"]: f"/frames/{index}"
                            for index, frame in enumerate(scene_content["frames"])
                        },
                    )
                ):
                    raise ValueError(f"staged scenes differ from their source: {key}")
                counts["scene_nodes"] += 1
                if state["draft_state"] == "completed":
                    expected.append(
                        (
                            str(uuid5(NAMESPACE_URL, f"lineage-scene-overall:{key}:{digest}")),
                            "overall",
                            None,
                            "complete",
                        )
                    )
                if draft.coverage:
                    expected.append(
                        (
                            str(uuid5(NAMESPACE_URL, f"lineage-scene-coverage:{key}:{digest}")),
                            "coverage",
                            None,
                            None,
                        )
                    )
                for frame, (item, _) in zip(scene_content["frames"], projected, strict=True):
                    facts = project_scene_review_facts(item.item["card_scene"])
                    completion = facts.get("completion", {}).get(
                        "state", facts.get("completion_state")
                    )
                    expected.append(
                        (
                            str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"lineage-draft-scene-review:{key}:{digest}:{frame['frame_id']}",
                                )
                            ),
                            "item",
                            frame["frame_id"],
                            completion if completion in {"complete", "unusable"} else "pending",
                        )
                    )
        for review_id, kind, item_id, decision in expected:
            record = reviews.get(review_id)
            expected_node = node_id if review_id in draft_review_ids else scene_id
            expected_revision = revision_id if expected_node == node_id else scene_revision_id
            revision_data = revision if expected_node == node_id else scene_revision
            if (
                record["node_id"] != expected_node
                or record["revision_id"] != expected_revision
                or record.get("content_sha256") != revision_data.content_sha256
                or record["kind"] != kind
                or record.get("decision") != decision
                or (item_id is not None and record.get("item_id") != item_id)
                or (
                    item_id is not None
                    and record.get("item_sha256")
                    != revision_data.metadata["item_provenance"]["items"][item_id]["sha256"]
                )
                or record.get("reviewer") != {"kind": "not_recorded", "id": None}
                or record.get("evidence", {}).get("draft_sha256") != digest
                or (kind == "coverage" and record.get("coverage") != draft.coverage)
            ):
                raise ValueError(f"staged review differs from its source: {key}")
            counts["reviews"] += 1
    return counts


def activate_staged_drafts(package_root: Any, staged_root: Any, active_root: Any) -> dict[str, int]:
    """Activate a verified import while all active-store writers are stopped.

    Each publication is replay-safe. A failure leaves the original files intact and a retry
    checks any already-published node before continuing.
    """
    from pathlib import Path

    staged = Path(staged_root).expanduser().resolve()
    active = Path(active_root).expanduser().resolve()
    if staged == active:
        raise ValueError("staged and active node stores must be different")
    expected = verify_staged_drafts(package_root, staged)
    verify_active_draft_snapshot(package_root, active)
    imported = import_staged_drafts(package_root, active)
    if imported != {key: expected[key] for key in ("drafts", "scene_nodes")}:
        raise ValueError("activated draft counts do not match the verified stage")
    actual = verify_staged_drafts(package_root, active)
    if actual != expected:
        raise ValueError("activated draft verification does not match the stage")
    verify_active_draft_snapshot(package_root, active)
    return actual
