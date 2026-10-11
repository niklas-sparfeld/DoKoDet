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
RFDETR_MANIFEST = Path("data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json")
DINO_CAMPAIGN = Path(
    "data/operations/dinov3-identity-campaigns/0043-m1-dinov3-identity-75000a5eec53a52f088f9e6e"
)
LEGACY_EXCLUSION = Path("data/operations/source-exclusions/legacy-device-diagnostic.json")


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


def _cardevent_split(root: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
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
                "task": split.get("task"),
                "test_sealed": split.get("test_sealed", False),
            }
        )
        for partition in ("train", "validation", "test", "unassigned"):
            for recording_id in split.get(partition, []):
                previous = assignments.setdefault(recording_id, partition)
                if previous != partition:
                    raise ValueError(f"CardEventNet split conflict for {recording_id}")
    return assignments, sources


def _rfdetr_partitions(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    path = root / RFDETR_MANIFEST
    manifest = _read_json(path)
    if not manifest:
        return {}, {"available": False, "path": RFDETR_MANIFEST.as_posix()}
    partitions: dict[str, str] = {}
    groups: dict[str, str] = {}
    for item in manifest.get("source_groups", []):
        recording_id = item["recording_id"]
        partition = item["partition"]
        previous = partitions.setdefault(recording_id, partition)
        if previous != partition:
            raise ValueError(f"RF-DETR partition conflict for {recording_id}")
        groups[recording_id] = item["group_key"]
    source = {
        "available": True,
        "path": RFDETR_MANIFEST.as_posix(),
        "campaign_id": manifest.get("campaign_id"),
        "manifest_digest": manifest.get("manifest_digest"),
        "freeze_state": manifest.get("freeze_state"),
        "partition_recordings": {
            name: value.get("recording_ids", [])
            for name, value in manifest.get("split", {}).items()
        },
        "source_group_keys": groups,
    }
    return partitions, source


def _dino_partitions(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    campaign_root = root / DINO_CAMPAIGN
    manifest = _read_json(campaign_root / "manifest.json")
    if not manifest:
        return {}, {"available": False, "path": DINO_CAMPAIGN.as_posix()}
    split_path = campaign_root / manifest["split"]["path"]
    split = _read_json(split_path)
    if not split:
        return {}, {"available": False, "path": split_path.relative_to(root).as_posix()}
    partitions: dict[str, str] = {}
    for item in manifest.get("selection", {}).get("selected_revisions", []):
        recording_id = item["recording_id"]
        partition = item["partition"]
        previous = partitions.setdefault(recording_id, partition)
        if previous != partition:
            raise ValueError(f"DINO partition conflict for {recording_id}")
    source = {
        "available": True,
        "path": DINO_CAMPAIGN.as_posix(),
        "campaign_id": manifest.get("campaign_id"),
        "manifest_digest": manifest.get("manifest_digest"),
        "freeze_digest": manifest.get("freeze_digest"),
        "split_path": split_path.relative_to(root).as_posix(),
        "split_version_id": split.get("split_version_id"),
        "split_version_digest": split.get("split_version_digest"),
        "selected_recordings": manifest.get("selection", {}).get("selected_recording_ids", []),
    }
    return partitions, source


def _legacy_exclusions(root: Path) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    path = root / LEGACY_EXCLUSION
    receipt = _read_json(path)
    if not receipt:
        return {}, {"available": False, "path": LEGACY_EXCLUSION.as_posix()}
    exclusions = {
        item["recording_id"]: {
            "source_asset_id": item["source_asset_id"],
            "source_sha256": item["source_sha256"],
            "role": item["role"],
        }
        for item in receipt.get("sources", [])
    }
    source = {
        "available": True,
        "path": LEGACY_EXCLUSION.as_posix(),
        "receipt_digest": receipt.get("receipt_digest"),
        "decision": receipt.get("decision"),
        "role": receipt.get("role"),
    }
    return exclusions, source


def _validate_source_group_partitions(
    recordings: list[dict[str, Any]], partition_field: str
) -> None:
    by_group: dict[str, set[str]] = defaultdict(set)
    for row in recordings:
        partition = row.get(partition_field)
        if partition and partition not in {"not-in-frozen-campaign", "unassigned"}:
            by_group[row["source_group_id"]].add(partition)
    conflicts = {group: partitions for group, partitions in by_group.items() if len(partitions) > 1}
    if conflicts:
        raise ValueError(f"Source groups cross {partition_field} partitions: {conflicts}")


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
    rfdetr_assignments, rfdetr_source = _rfdetr_partitions(root)
    dino_assignments, dino_source = _dino_partitions(root)
    legacy_exclusions, legacy_source = _legacy_exclusions(root)
    proposals = _latest_proposals(root)
    for row in recordings:
        recording_id = row["recording_id"]
        row["source_group_id"] = groups[recording_id]
        row["cardeventnet_partition"] = cardevent_assignments.get(recording_id, "unassigned")
        row["rfdetr_partition"] = rfdetr_assignments.get(recording_id, "not-in-frozen-campaign")
        row["rfdetr_source_group_key"] = rfdetr_source.get("source_group_keys", {}).get(
            recording_id
        )
        row["rfdetr_sealed_test"] = row["rfdetr_partition"] == "sealed_test"
        row["legacy_device_exclusion"] = legacy_exclusions.get(recording_id)
        row["dino_partition"] = dino_assignments.get(recording_id, "not-in-frozen-campaign")
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
        elif row["legacy_device_exclusion"]:
            row["disposition"] = "excluded-legacy-device-diagnostic"
            row["disposition_reason"] = row["legacy_device_exclusion"]["role"]
        elif any(
            partition == "validation"
            for partition in (
                row["cardeventnet_partition"],
                row["rfdetr_partition"],
                row["dino_partition"],
            )
        ):
            row["disposition"] = "deferred-protected-evaluation"
            row["disposition_reason"] = (
                "A frozen validation partition needs a separate blind review decision."
            )
        elif "train" not in row["allowed_uses"]:
            row["disposition"] = "deferred-source-permission"
            row["disposition_reason"] = "Source permission does not allow training use."
        elif row["cardeventnet_partition"] == "train":
            row["disposition"] = "candidate-development"
            row["disposition_reason"] = (
                "Train eligible across current assignments; new campaign splits stay independent."
            )
        else:
            row["disposition"] = "deferred-protected-or-unassigned"
            row["disposition_reason"] = (
                "No development assignment or completed event scope is available."
            )

    for field in ("cardeventnet_partition", "rfdetr_partition", "dino_partition"):
        _validate_source_group_partitions(recordings, field)

    pilot = next((row for row in recordings if row["recording_id"] == PILOT_RECORDING_ID), None)
    if pilot is None:
        raise ValueError(
            f"Required pilot candidate is not an accepted recording: {PILOT_RECORDING_ID}"
        )
    if (
        pilot["disposition"] != "candidate-development"
        or pilot["cardeventnet_partition"] != "train"
        or pilot["rfdetr_partition"] != "train"
        or pilot["dino_partition"] == "validation"
        or "train" not in pilot["allowed_uses"]
    ):
        raise ValueError(
            f"Pilot candidate is not eligible under frozen assignments: {PILOT_RECORDING_ID}"
        )
    pilot_frames = (
        pilot.get("latest_proposal", {}).get("frame_ids", [])
        if pilot.get("latest_proposal")
        else []
    )
    content = {
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "inventory_date": "2026-10-11",
        "source_roots": [
            "data/intake/recordings",
            "data/operations/pipeline",
            "data/operations/pipeline-references",
            "data/operations/cardevent-datasets",
            RFDETR_MANIFEST.as_posix(),
            DINO_CAMPAIGN.as_posix(),
            LEGACY_EXCLUSION.as_posix(),
        ],
        "cardeventnet_split_sources": cardevent_split_sources,
        "rfdetr_source": rfdetr_source,
        "dino_source": dino_source,
        "legacy_exclusion_source": legacy_source,
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
            "excluded_legacy_device_count": sum(
                row["disposition"] == "excluded-legacy-device-diagnostic" for row in recordings
            ),
            "deferred_count": sum(row["disposition"].startswith("deferred-") for row in recordings),
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
            "source_group_partition_conflicts": 0,
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
                    "source": RFDETR_MANIFEST.as_posix(),
                    "recordings": sorted(
                        row["recording_id"]
                        for row in recordings
                        if row["disposition"] == "excluded-rfdetr-sealed-test"
                    ),
                },
                {
                    "rule": "legacy device diagnostic only",
                    "source": LEGACY_EXCLUSION.as_posix(),
                    "recordings": sorted(
                        row["recording_id"]
                        for row in recordings
                        if row["disposition"] == "excluded-legacy-device-diagnostic"
                    ),
                },
                {
                    "rule": "protected validation",
                    "source": "CardEventNet, 0068 RF-DETR, and 0043 DINO frozen splits",
                    "recordings": sorted(
                        row["recording_id"]
                        for row in recordings
                        if row["disposition"] == "deferred-protected-evaluation"
                    ),
                },
                {
                    "rule": "not proven development",
                    "source": "missing or non-train partition assignment",
                    "recordings": sorted(
                        row["recording_id"]
                        for row in recordings
                        if row["disposition"]
                        in {
                            "deferred-protected-or-unassigned",
                            "deferred-source-permission",
                        }
                    ),
                },
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
            "selected": True,
            "proposal_refresh_required": True,
            "proposal_refresh_reason": "The stored proposal uses recipe v3 and geometry v4.",
            "blocked_until": [],
        },
        "follow_up_constraints": [
            {
                "id": "missing-event-scope",
                "reason": "Do not batch a recording without a selected completed event revision.",
                "recordings": sorted(
                    row["recording_id"]
                    for row in recordings
                    if not row["reference_state"]["events"]["selected_completed_revision_id"]
                ),
            },
            {
                "id": "blind-validation-review",
                "reason": ("Validation groups need a blind reference process before annotation."),
                "recordings": sorted(
                    row["recording_id"]
                    for row in recordings
                    if row["disposition"] == "deferred-protected-evaluation"
                ),
            },
        ],
        "blockers": [],
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
