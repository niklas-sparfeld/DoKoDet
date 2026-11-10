"""Offline rehearsal for the bounded 0124 retained event conversion."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.recording_folder_store import RecordingFolderStore

RECORDINGS = (
    "cardeventnet-IMG_0662",
    "cardeventnet-IMG_0648",
    "game-2026-08-20-01-001",
)


class RehearsalError(ValueError):
    """Frozen retained inputs cannot be converted without guessing or loss."""


def rehearse(
    *,
    recordings_root: Path,
    pipeline_nodes_root: Path,
    legacy_pipeline_root: Path,
    retained_output_runs_root: Path | None = None,
    retained_output_run_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Convert only the three named recordings into a caller-provided disposable root."""
    recordings = RecordingFolderStore(recordings_root)
    event_sets = EventSetStore(recordings)
    nodes = PipelineNodeStore(pipeline_nodes_root)
    reviews = PipelineNodeReviews(nodes)
    receipt: dict[str, Any] = {"schema_version": "0124-event-rehearsal/v1", "recordings": []}

    for recording_id in RECORDINGS:
        if recordings.get(recording_id) is None:
            raise RehearsalError(f"disposable recording root is missing: {recording_id}")
        legacy_selection = _read_json(
            legacy_pipeline_root / "selections" / recording_id / "events.json"
        )
        node_selection = _read_json(
            pipeline_nodes_root / ".pipeline-node-selections" / recording_id / "events.json"
        )
        if (
            legacy_selection.get("schema_version") != "pipeline-selection/v1"
            or legacy_selection.get("recording_id") != recording_id
            or node_selection.get("schema_version") != "pipeline-node-selection/v1"
            or node_selection.get("recording_id") != recording_id
        ):
            raise RehearsalError(f"event selector identity or schema is invalid: {recording_id}")

        candidates = [
            node
            for node in nodes.list_nodes()
            if node.content_type == "events" and node.source.get("recording_id") == recording_id
        ]
        if not candidates:
            raise RehearsalError(f"no event nodes found for {recording_id}")
        converted: dict[tuple[str, str], dict[str, str]] = {}
        version_rows = []
        review_total = 0
        for node in candidates:
            for revision in nodes.history(node.node_id):
                provenance = {
                    "source_schema": "pipeline-node-revision/v1",
                    "source_node_id": node.node_id,
                    "source_revision_id": revision.revision_id,
                    "source_content_sha256": revision.content_sha256,
                    "source_metadata": revision.metadata,
                    "source_parent_revision_id": revision.parent_revision_id,
                }
                saved = event_sets.get(recording_id, node.node_id, revision.revision_id)
                if saved is None:
                    event_sets.save(
                        recording_id,
                        set_id=node.node_id,
                        version=revision.revision_id,
                        content=revision.content,
                        origin=_origin(revision.metadata),
                        provenance=provenance,
                    )
                    saved = event_sets.get(recording_id, node.node_id, revision.revision_id)
                if (
                    saved is None
                    or saved["content_sha256"] != revision.content_sha256
                    or saved["provenance"] != provenance
                    or saved["origin"] != _origin(revision.metadata)
                ):
                    raise RehearsalError(
                        f"event content digest changed: {node.node_id}@{revision.revision_id}"
                    )
                converted[(node.node_id, revision.revision_id)] = {
                    "set_id": node.node_id,
                    "version": revision.revision_id,
                }
                # Retained reviews can exist on revisions that the old selection authority did
                # not publish. Read those exact records as offline migration input; calling the
                # normal user-facing list method would hide them behind publication authority.
                revision_reviews = reviews._records_for_revisions(
                    {(node.node_id, revision.revision_id)}
                )
                for record in revision_reviews:
                    if record.get("content_sha256") != revision.content_sha256:
                        raise RehearsalError(
                            f"review content digest differs from its source revision: "
                            f"{record.get('review_id')}"
                        )
                    details = {}
                    if record["kind"] == "item":
                        details["item_id"] = record["item_id"]
                    elif record["kind"] == "coverage":
                        details["coverage"] = record["coverage"]
                    event_sets.save_review(
                        recording_id,
                        node.node_id,
                        revision.revision_id,
                        review_id=record["review_id"],
                        kind=record["kind"],
                        question=record["question"],
                        decision=record["decision"],
                        reviewer=record["reviewer"],
                        reviewed_at=record["reviewed_at"],
                        evidence={
                            **record["evidence"],
                            "source_provenance": {
                                "source_schema": "pipeline-review/v1",
                                "source_node_id": node.node_id,
                                "source_revision_id": revision.revision_id,
                                "source_content_sha256": record["content_sha256"],
                            },
                        },
                        **details,
                    )
                converted_reviews = event_sets.list_reviews(
                    recording_id, node.node_id, revision.revision_id
                )
                _compare_reviews(
                    recording_id, node.node_id, revision, revision_reviews, converted_reviews
                )
                review_total += len(revision_reviews)
                review_kinds = Counter(row["kind"] for row in revision_reviews)
                reviewed_item_ids = {
                    row["item_id"] for row in revision_reviews if row["kind"] == "item"
                }
                version_rows.append(
                    {
                        "node_id": node.node_id,
                        "revision_id": revision.revision_id,
                        "content_sha256": revision.content_sha256,
                        "event_count": len(revision.content["events"]),
                        "review_count": len(revision_reviews),
                        "review_kinds": dict(sorted(review_kinds.items())),
                        "reviewed_item_ids": sorted(reviewed_item_ids),
                        "pending_item_event_ids": sorted(
                            event["event_id"]
                            for event in revision.content["events"]
                            if event["event_id"] not in reviewed_item_ids
                        ),
                    }
                )

        selectors = {
            "generated": (
                legacy_selection.get("selected_generated_revision_id"),
                node_selection.get("selected_generated"),
            ),
            "reference": (
                legacy_selection.get("selected_completed_reference_revision_id"),
                node_selection.get("selected_completed_reference"),
            ),
        }
        selected = {}
        for choice, (legacy_revision_id, node_ref) in selectors.items():
            if (legacy_revision_id is None) != (node_ref is None):
                raise RehearsalError(
                    f"legacy and node selectors disagree for {recording_id}:{choice}"
                )
            if node_ref is None:
                selected[choice] = None
                continue
            identity = (node_ref.get("node_id"), node_ref.get("revision_id"))
            if identity not in converted:
                raise RehearsalError(f"selected event version is unavailable: {identity}")
            revision = nodes.read_authorized_revision(*identity)
            if revision.metadata.get("legacy_revision_id") != legacy_revision_id:
                raise RehearsalError(
                    f"selector lineage mismatch for {recording_id}:{choice}: "
                    f"{legacy_revision_id} != {revision.metadata.get('legacy_revision_id')}"
                )
            selected[choice] = converted[identity]

        # Preserve a rehearsed pilot's existing event HEAD; initialize only empty test roots.
        root = recordings.get(recording_id)
        if not root.head.get("events"):
            for choice, reference in selected.items():
                event_sets.select(
                    recording_id,
                    choice=choice,
                    reference=reference,
                    expected_version=recordings.get(recording_id).version,
                )
        final_selection = event_sets.get_selection(recording_id)
        if final_selection is None:
            raise RehearsalError(
                f"recording selection is unavailable after conversion: {recording_id}"
            )

        receipt["recordings"].append(
            {
                "recording_id": recording_id,
                "converted_versions": version_rows,
                "review_count": review_total,
                "selected": selected,
                "current_head_preserved": bool(root.head.get("events")),
                "head_after_conversion": {
                    "generated": final_selection["generated"],
                    "reference": final_selection["reference"],
                },
            }
        )
    if retained_output_run_ids:
        if retained_output_runs_root is None:
            raise RehearsalError("retained output runs root is required for output lineage")
        receipt["retained_output_parent_mappings"] = _map_retained_output_parents(
            nodes=nodes,
            runs_root=retained_output_runs_root,
            run_ids=retained_output_run_ids,
            converted_by_recording={
                row["recording_id"]: {
                    (version["node_id"], version["revision_id"]): version
                    for version in row["converted_versions"]
                }
                for row in receipt["recordings"]
            },
        )
    return receipt


def _map_retained_output_parents(
    *,
    nodes: PipelineNodeStore,
    runs_root: Path,
    run_ids: tuple[str, ...],
    converted_by_recording: dict[str, dict[tuple[str, str], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Map named saved outputs through their exact legacy event revision metadata."""
    mappings = []
    all_nodes = nodes.list_nodes()
    for run_id in run_ids:
        run_root = runs_root / run_id
        request = _read_json(run_root / "request.json")
        state = _read_json(run_root / "state.json")
        output_revision_ids = state.get("output_revision_ids")
        outputs = [
            (node, revision)
            for node in all_nodes
            if node.content_type == "visible_cards"
            for revision in nodes.history(node.node_id)
            if revision.metadata.get("producer", {}).get("run_id") == run_id
        ]
        if len(outputs) != 1 or len(output_revision_ids or []) != 1:
            raise RehearsalError(f"named retained output is ambiguous or missing: {run_id}")
        output_node, output_revision = outputs[0]
        if output_revision.metadata.get("legacy_revision_id") != output_revision_ids[0]:
            raise RehearsalError(f"retained output revision differs from run state: {run_id}")
        recording_id = output_node.source.get("recording_id")
        coverage = output_revision.metadata.get("coverage", {})
        parent_legacy_id = coverage.get("event_revision_id")
        if not parent_legacy_id or request.get("input_revision_ids") != [parent_legacy_id]:
            raise RehearsalError(
                f"retained output parent differs from its frozen request: {run_id}"
            )
        parents = [
            (node, revision)
            for node in all_nodes
            if node.content_type == "events" and node.source.get("recording_id") == recording_id
            for revision in nodes.history(node.node_id)
            if revision.metadata.get("legacy_revision_id") == parent_legacy_id
        ]
        if len(parents) != 1:
            raise RehearsalError(f"retained output event parent is ambiguous or missing: {run_id}")
        parent_node, parent_revision = parents[0]
        target = converted_by_recording.get(recording_id, {}).get(
            (parent_node.node_id, parent_revision.revision_id)
        )
        if target is None or target["content_sha256"] != parent_revision.content_sha256:
            raise RehearsalError(f"converted exact parent is missing or changed: {run_id}")
        mappings.append(
            {
                "run_id": run_id,
                "recording_id": recording_id,
                "output_node_id": output_node.node_id,
                "output_revision_id": output_revision.revision_id,
                "output_content_sha256": output_revision.content_sha256,
                "source_event_revision_id": parent_legacy_id,
                "source_event_node_id": parent_node.node_id,
                "source_event_node_revision_id": parent_revision.revision_id,
                "source_event_content_sha256": parent_revision.content_sha256,
                "converted_parent": {
                    "set_id": target["node_id"],
                    "version": target["revision_id"],
                    "content_sha256": target["content_sha256"],
                },
            }
        )
    return mappings


def _origin(metadata: dict[str, Any]) -> str:
    value = metadata.get("origin")
    return value if value in {"processor", "manual", "corrected"} else "corrected"


def _compare_reviews(
    recording_id: str,
    node_id: str,
    revision: Any,
    source: list[dict[str, Any]],
    converted: list[dict[str, Any]],
) -> None:
    by_id = {row["review_id"]: row for row in converted}
    if len(by_id) != len(converted) or set(by_id) != {row["review_id"] for row in source}:
        raise RehearsalError(f"review IDs changed: {recording_id} {node_id}@{revision.revision_id}")
    for row in source:
        target = by_id[row["review_id"]]
        expected = {
            "kind": row["kind"],
            "question": row["question"],
            "decision": row["decision"],
            "reviewer": row["reviewer"],
            "reviewed_at": row["reviewed_at"],
            "content_sha256": row["content_sha256"],
        }
        actual = {key: target.get(key) for key in expected if key != "source_evidence"}
        actual_evidence = dict(target.get("evidence", {}))
        actual_evidence.pop("source_provenance", None)
        expected["evidence"] = row["evidence"]
        actual["evidence"] = actual_evidence
        if row["kind"] == "item":
            expected["item_id"] = row["item_id"]
            expected["item_sha256"] = row["item_sha256"]
            actual["item_id"] = target.get("item_id")
            actual["item_sha256"] = target.get("item_sha256")
        elif row["kind"] == "coverage":
            expected["coverage"] = row["coverage"]
            actual["coverage"] = target.get("coverage")
        if actual != expected:
            raise RehearsalError(
                f"review facts changed: {recording_id} {node_id}@{revision.revision_id} "
                f"{row['review_id']}"
            )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RehearsalError(f"expected a JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recordings-root", type=Path, required=True)
    parser.add_argument("--pipeline-nodes-root", type=Path, required=True)
    parser.add_argument("--legacy-pipeline-root", type=Path, required=True)
    parser.add_argument("--retained-output-runs-root", type=Path)
    parser.add_argument("--retained-output-run-id", action="append", default=[])
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = rehearse(
        recordings_root=args.recordings_root,
        pipeline_nodes_root=args.pipeline_nodes_root,
        legacy_pipeline_root=args.legacy_pipeline_root,
        retained_output_runs_root=args.retained_output_runs_root,
        retained_output_run_ids=tuple(args.retained_output_run_id),
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
