#!/usr/bin/env python3
"""Build a deterministic, read-only inventory for epic 0086."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reviewed-virtual-card-corpus-work-manifest/v1"
PILOT_RECORDING_ID = "cardeventnet-IMG_0095"
DETECTOR_SEALED_RECORDINGS = {
    "cardeventnet-IMG_0646",
    "cardeventnet-IMG_0648",
    "cardeventnet-IMG_0649",
}
DETECTOR_LEGACY_EXCLUSIONS = {
    f"cardeventnet-IMG_{number}" for number in (2777, 2778, 2779, 2780, 2781)
}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _source_groups(recordings: list[dict[str, Any]]) -> dict[str, str]:
    """Group recordings linked by session, source asset, or table setup."""
    parents = {row["recording_id"]: row["recording_id"] for row in recordings}

    def find(recording_id: str) -> str:
        while parents[recording_id] != recording_id:
            parents[recording_id] = parents[parents[recording_id]]
            recording_id = parents[recording_id]
        return recording_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    values: dict[str, list[str]] = defaultdict(list)
    for row in recordings:
        for key in ("session_id", "source_asset_id", "source_sha256", "table_setup"):
            value = row.get(key)
            if value:
                values[f"{key}:{value}"].append(row["recording_id"])
    for members in values.values():
        for member in members[1:]:
            union(members[0], member)

    components: dict[str, list[str]] = defaultdict(list)
    for recording_id in parents:
        components[find(recording_id)].append(recording_id)
    result: dict[str, str] = {}
    for members in components.values():
        members.sort()
        group_id = f"source-group-{_canonical_digest(members)[:16]}"
        result.update({recording_id: group_id for recording_id in members})
    return result


def _cardevent_split(root: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    split_paths = sorted((root / "data/operations/cardevent-datasets").glob("*/split.json"))
    assignments: dict[str, str] = {}
    sources: list[dict[str, str]] = []
    for path in split_paths:
        split = _read_json(path)
        if split is None:
            continue
        sources.append(
            {
                "path": path.relative_to(root).as_posix(),
                "dataset_version_id": split["dataset_version_id"],
                "dataset_version_digest": split["dataset_version_digest"],
                "split_version_id": split["split_version_id"],
                "split_version_digest": split["split_version_digest"],
            }
        )
        for partition in ("train", "validation", "test", "unassigned"):
            for recording_id in split.get(partition, []):
                previous = assignments.setdefault(recording_id, partition)
                if previous != partition:
                    raise ValueError(f"CardEventNet split conflict for {recording_id}")
    return assignments, sources


def _latest_proposals(root: Path) -> dict[str, dict[str, Any]]:
    by_recording: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    runs_dir = root / "data/operations/pipeline/runs"
    for run_dir in sorted(runs_dir.glob("card-scene-proposal-*")):
        request = _read_json(run_dir / "request.json")
        state = _read_json(run_dir / "state.json")
        if not request or not state:
            continue
        source = request.get("source", {})
        recording_id = source.get("recording_id")
        if recording_id:
            by_recording[recording_id].append((run_dir.name, request, state))

    result: dict[str, dict[str, Any]] = {}
    for recording_id, runs in by_recording.items():
        runs.sort(
            key=lambda item: (
                item[2].get("completed_at") or item[2].get("updated_at") or "",
                item[0],
            )
        )
        run_id, request, state = runs[-1]
        output_ids = state.get("output_revision_ids", [])
        revision_id = output_ids[0] if output_ids else None
        revision = root / "data/operations/pipeline/revisions" / str(revision_id)
        revision_manifest = _read_json(revision / "manifest.json") if revision_id else None
        content = _read_json(revision / "content.json") if revision_id else None
        frames = content.get("frames", []) if content else []
        recipe_versions = sorted(
            {
                frame.get("proposal", {})
                .get("fit_diagnostics", {})
                .get("diagnostics", {})
                .get("recipe", {})
                .get("recipe_version")
                for frame in frames
                if frame.get("proposal", {})
                .get("fit_diagnostics", {})
                .get("diagnostics", {})
                .get("recipe", {})
                .get("recipe_version")
            }
        )
        result[recording_id] = {
            "run_id": run_id,
            "status": state.get("status", "unknown"),
            "updated_at": state.get("completed_at") or state.get("updated_at"),
            "processor_version": request.get("implementation", {}).get("version"),
            "input_revision_ids": request.get("input_revision_ids", []),
            "output_revision_id": revision_id,
            "output_content_sha256": (
                revision_manifest.get("content_sha256") if revision_manifest else None
            ),
            "recipe_versions": recipe_versions,
            "card_geometry_version": (
                content.get("calibration", {}).get("algorithm_version") if content else None
            ),
            "calibration_revision_id": (
                content.get("calibration_revision_id") if content else None
            ),
            "calibration_digest": content.get("calibration_digest") if content else None,
            "detector_revision_id": content.get("detector_revision_id") if content else None,
            "detector_revision_digest": (
                content.get("detector_revision_digest") if content else None
            ),
            "supported_frame_count": sum(frame.get("status") == "supported" for frame in frames),
            "unsupported_frame_count": sum(frame.get("status") != "supported" for frame in frames),
            "frame_ids": sorted(frame.get("frame_id") for frame in frames if frame.get("frame_id")),
        }
    return result


def _reference_state(root: Path, recording_id: str, content_type: str) -> dict[str, Any]:
    state = _read_json(
        root / "data/operations/pipeline-references" / recording_id / content_type / "state.json"
    )
    selection = _read_json(
        root / "data/operations/pipeline/selections" / recording_id / f"{content_type}.json"
    )
    completed_id = selection.get("selected_completed_reference_revision_id") if selection else None
    generated_id = selection.get("selected_generated_revision_id") if selection else None
    revisions_root = root / "data/operations/pipeline/revisions"
    completed_manifest = (
        _read_json(revisions_root / str(completed_id) / "manifest.json") if completed_id else None
    )
    generated_manifest = (
        _read_json(revisions_root / str(generated_id) / "manifest.json") if generated_id else None
    )
    return {
        "draft_state": state.get("draft_state") if state else None,
        "selected_completed_revision_id": completed_id,
        "selected_completed_content_sha256": (
            completed_manifest.get("content_sha256") if completed_manifest else None
        ),
        "selected_generated_revision_id": generated_id,
        "selected_generated_content_sha256": (
            generated_manifest.get("content_sha256") if generated_manifest else None
        ),
    }


def _event_frame_ids(root: Path, revision_id: str | None) -> list[str]:
    if not revision_id:
        return []
    content = _read_json(root / "data/operations/pipeline/revisions" / revision_id / "content.json")
    if not content:
        return []
    return sorted(event["event_id"] for event in content.get("events", []) if event.get("event_id"))


def build_manifest(root: Path) -> dict[str, Any]:
    recordings: list[dict[str, Any]] = []
    intake_root = root / "data/intake/recordings"
    for recording_dir in sorted(path for path in intake_root.iterdir() if path.is_dir()):
        bundle = _read_json(recording_dir / "manifest.json")
        source = _read_json(recording_dir / "source-record.json")
        enrollment = _read_json(recording_dir / "initial-task-enrollment.json")
        if not bundle or bundle.get("state") != "complete" or not source or not enrollment:
            continue
        recordings.append(
            {
                "recording_id": bundle["recording_id"],
                "session_id": source.get("session_id"),
                "source_asset_id": source.get("source_asset_id"),
                "source_sha256": source.get("sha256"),
                "table_setup": source.get("table_setup"),
                "allowed_uses": sorted(source.get("allowed_uses", [])),
                "source_permission": source.get("source_permission"),
                "task_enrollments": {
                    item["task"]: item["disposition"] for item in enrollment.get("enrollments", [])
                },
            }
        )

    groups = _source_groups(recordings)
    cardevent_assignments, cardevent_split_sources = _cardevent_split(root)
    proposals = _latest_proposals(root)
    for row in recordings:
        recording_id = row["recording_id"]
        row["source_group_id"] = groups[recording_id]
        row["cardeventnet_partition"] = cardevent_assignments.get(recording_id, "unassigned")
        row["rfdetr_sealed_test"] = recording_id in DETECTOR_SEALED_RECORDINGS
        row["rfdetr_development_exclusion"] = recording_id in DETECTOR_LEGACY_EXCLUSIONS
        row["dino_partition"] = "unavailable-in-checkout"
        row["reference_state"] = {
            kind: _reference_state(root, recording_id, kind)
            for kind in ("events", "visible_cards", "visual_identities", "table_observations")
        }
        selected_event_revision = row["reference_state"]["events"]["selected_completed_revision_id"]
        row["selected_event_revision_id"] = selected_event_revision
        row["event_frame_ids"] = _event_frame_ids(root, selected_event_revision)
        row["latest_proposal"] = proposals.get(recording_id)
        if row["cardeventnet_partition"] == "test":
            row["disposition"] = "excluded-system-holdout"
            row["disposition_reason"] = "CardEventNet split marks this source group as sealed test."
        elif row["rfdetr_sealed_test"]:
            row["disposition"] = "excluded-rfdetr-sealed-test"
            row["disposition_reason"] = (
                "The 0068 RF-DETR campaign marks this recording as sealed test."
            )
        elif row["cardeventnet_partition"] == "train":
            row["disposition"] = "candidate-development"
            row["disposition_reason"] = (
                "CardEventNet train assignment; cross-campaign reconciliation is pending."
            )
        else:
            row["disposition"] = "deferred-protected-or-unassigned"
            row["disposition_reason"] = (
                "A development assignment is not proven by the available split artifacts."
            )

    pilot = next((row for row in recordings if row["recording_id"] == PILOT_RECORDING_ID), None)
    if pilot is None:
        raise ValueError(
            f"Required pilot candidate is not an accepted recording: {PILOT_RECORDING_ID}"
        )
    pilot_frames = (
        pilot.get("latest_proposal", {}).get("frame_ids", [])
        if pilot.get("latest_proposal")
        else []
    )
    content = {
        "schema_version": SCHEMA_VERSION,
        "inventory_date": "2026-10-11",
        "source_roots": [
            "data/intake/recordings",
            "data/operations/pipeline",
            "data/operations/pipeline-references",
            "data/operations/cardevent-datasets",
        ],
        "cardeventnet_split_sources": cardevent_split_sources,
        "inventory_summary": {
            "accepted_recording_count": len(recordings),
            "proposal_run_count": sum(
                1
                for path in (root / "data/operations/pipeline/runs").glob("card-scene-proposal-*")
                if (path / "request.json").is_file() and (path / "state.json").is_file()
            ),
            "recordings_with_proposal_runs": len(proposals),
            "candidate_development_count": sum(
                row["disposition"] == "candidate-development" for row in recordings
            ),
            "excluded_system_holdout_count": sum(
                row["disposition"] == "excluded-system-holdout" for row in recordings
            ),
            "excluded_rfdetr_sealed_count": sum(
                row["disposition"] == "excluded-rfdetr-sealed-test" for row in recordings
            ),
            "rfdetr_development_exclusion_count": sum(
                row["rfdetr_development_exclusion"] for row in recordings
            ),
            "deferred_count": sum(
                row["disposition"] == "deferred-protected-or-unassigned" for row in recordings
            ),
            "completed_event_references": sum(
                bool(row["reference_state"]["events"]["selected_completed_revision_id"])
                for row in recordings
            ),
            "completed_visible_card_references": sum(
                bool(row["reference_state"]["visible_cards"]["selected_completed_revision_id"])
                for row in recordings
            ),
            "completed_identity_references": sum(
                bool(row["reference_state"]["visual_identities"]["selected_completed_revision_id"])
                for row in recordings
            ),
            "draft_visible_card_references": sum(
                row["reference_state"]["visible_cards"]["draft_state"] == "draft"
                for row in recordings
            ),
            "draft_identity_references": sum(
                row["reference_state"]["visual_identities"]["draft_state"] == "draft"
                for row in recordings
            ),
            "proposal_supported_frame_count": sum(
                (row.get("latest_proposal") or {}).get("supported_frame_count", 0)
                for row in recordings
            ),
            "proposal_unsupported_frame_count": sum(
                (row.get("latest_proposal") or {}).get("unsupported_frame_count", 0)
                for row in recordings
            ),
            "proposal_outputs_are_reviewed_targets": False,
        },
        "scope": {
            "candidate_recordings": [
                row["recording_id"]
                for row in recordings
                if row["disposition"] == "candidate-development"
            ],
            "frame_scope_source": (
                "Selected completed event revision. Event frame IDs are listed per recording. "
                "Proposal frame IDs are listed separately."
            ),
            "batch_size_recordings": 1,
            "exclusions": [
                {
                    "rule": "system-holdout",
                    "source": "CardEventNet split.json",
                    "recordings": sorted(
                        row["recording_id"]
                        for row in recordings
                        if row["disposition"] == "excluded-system-holdout"
                    ),
                },
                {
                    "rule": "RF-DETR sealed test",
                    "source": "0086/0068 documented sealed-test set",
                    "recordings": sorted(DETECTOR_SEALED_RECORDINGS),
                },
                {
                    "rule": "not proven development",
                    "source": "missing or non-train partition assignment",
                    "recordings": sorted(
                        row["recording_id"]
                        for row in recordings
                        if row["disposition"] == "deferred-protected-or-unassigned"
                    ),
                },
            ],
            "campaign_constraints": [
                {
                    "campaign": "0087 RF-DETR",
                    "reason": "0087 follows 0068's legacy-device exclusion.",
                    "recordings": sorted(DETECTOR_LEGACY_EXCLUSIONS),
                }
            ],
        },
        "pilot": {
            "recording_id": PILOT_RECORDING_ID,
            "candidate_frame_ids": pilot_frames,
            "selected_event_revision_id": pilot.get("selected_event_revision_id"),
            "event_frame_ids": pilot.get("event_frame_ids", []),
            "latest_proposal_run_id": pilot.get("latest_proposal", {}).get("run_id")
            if pilot.get("latest_proposal")
            else None,
            "proposal_status": pilot.get("latest_proposal", {}).get("status")
            if pilot.get("latest_proposal")
            else None,
            "candidate_only": True,
            "blocked_until": [
                "Recover the exact frozen 0043 DINO train, validation, and holdout membership.",
                "Recover and verify the complete 0068 train and validation membership.",
                "Confirm source-group separation before proposal refresh or review.",
            ],
        },
        "blockers": [
            {
                "id": "split-artifacts-not-present",
                "reason": (
                    "The checkout has CardEventNet splits and the 0068 sealed-test identities. "
                    "It lacks the exact 0043 split and full 0068 split manifest."
                ),
                "affected_recordings": [
                    row["recording_id"]
                    for row in recordings
                    if row["disposition"] == "candidate-development"
                ],
                "required_before": "M1 proposal generation and human review",
            },
            {
                "id": "event-scope-not-complete",
                "reason": (
                    "Some accepted recordings have no selected completed event revision. "
                    "Their review frame scope is not frozen."
                ),
                "affected_recordings": sorted(
                    row["recording_id"]
                    for row in recordings
                    if not row["reference_state"]["events"]["selected_completed_revision_id"]
                ),
                "required_before": "Adding those recordings to a proposal batch",
            },
        ],
        "recordings": recordings,
    }
    return {**content, "manifest_sha256": _canonical_digest(content)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.root.resolve())
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
