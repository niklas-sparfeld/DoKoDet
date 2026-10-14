"""Build the Epic 0086 detection-only handoff from current reviewed references."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .rfdetr_segmentation_campaign import (
    _bundle_audit,
    _read_json,
    _reference_audit,
    _relative,
    sha256_json,
)

HANDOFF_SCHEMA_VERSION = "reviewed-visible-card-detection-handoff/v1"
DEFAULT_INVENTORY = Path("docs/reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json")
DEFAULT_DISPOSITIONS = Path("docs/reports/0086-M4_Recording_Dispositions.json")


def build_reviewed_visible_card_handoff(
    repository_root: str | Path,
    *,
    inventory_path: str | Path = DEFAULT_INVENTORY,
    verify_source_bytes: bool = False,
) -> dict[str, Any]:
    """Audit the frozen development candidates and return a digest-backed handoff."""

    repository = Path(repository_root).expanduser().resolve()
    inventory_file = inventory_path
    if not inventory_file.is_absolute():
        inventory_file = repository / inventory_file
    inventory = _read_json(inventory_file, "0086 M0 inventory")
    if inventory.get("schema_version") != "reviewed-virtual-card-corpus-work-manifest/v1":
        raise ValueError("0086 M0 inventory has an unsupported schema")
    inventory_digest = inventory.get("manifest_sha256")
    inventory_core = {key: value for key, value in inventory.items() if key != "manifest_sha256"}
    if inventory_digest != sha256_json(inventory_core):
        raise ValueError("0086 M0 inventory digest does not match its contents")
    candidate_ids = inventory.get("scope", {}).get("candidate_recordings")
    recordings = inventory.get("recordings")
    if not isinstance(candidate_ids, list) or not isinstance(recordings, list):
        raise ValueError("0086 M0 inventory has no frozen candidate list")
    records_by_id = {
        item.get("recording_id"): item for item in recordings if isinstance(item, dict)
    }
    if len(records_by_id) != len(recordings) or set(candidate_ids) - set(records_by_id):
        raise ValueError("0086 M0 candidate recordings do not match its inventory")

    disposition_path = repository / DEFAULT_DISPOSITIONS
    dispositions = (
        _read_json(disposition_path, "0086 M4 dispositions") if disposition_path.exists() else None
    )
    if dispositions is not None:
        core = {key: value for key, value in dispositions.items() if key != "receipt_sha256"}
        if dispositions.get(
            "schema_version"
        ) != "0086-recording-dispositions/v1" or dispositions.get("receipt_sha256") != sha256_json(
            core
        ):
            raise ValueError("0086 M4 dispositions schema or digest is invalid")
    decisions = {} if dispositions is None else dispositions["recordings"]

    operations = repository / "data" / "operations"
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for recording_id in candidate_ids:
        if recording_id in decisions:
            decision = decisions[recording_id]
            if decision["disposition"] not in {"permanently_excluded", "deferred"}:
                raise ValueError("0086 M4 disposition is invalid")
            excluded.append(
                {
                    "recording_id": recording_id,
                    "disposition": decision["disposition"],
                    "reasons": [decision["reason"]],
                }
            )
            continue
        inventory_record = records_by_id[recording_id]
        source_group_id = inventory_record.get("source_group_id")
        if not isinstance(source_group_id, str) or not source_group_id:
            excluded.append({"recording_id": recording_id, "reasons": ["source group is missing"]})
            continue
        bundle, bundle_gaps = _bundle_audit(
            recording_id,
            "train",
            intake_root=repository / "data" / "intake" / "recordings",
            repository_root=repository,
            verify_source_bytes=verify_source_bytes,
        )
        if bundle is None or bundle_gaps:
            excluded.append(
                {
                    "recording_id": recording_id,
                    "reasons": bundle_gaps or ["source bundle is unavailable"],
                }
            )
            continue
        audit, audit_gaps = _reference_audit(
            bundle,
            operations_root=operations,
            repository_root=repository,
            include_piles=True,
        )
        if audit_gaps:
            excluded.append(
                {
                    "recording_id": recording_id,
                    "reference_revision_id": audit["reference_revision_id"],
                    "reasons": audit_gaps,
                }
            )
            continue
        for sample in audit["samples"]:
            sample.pop("split", None)
        event_revision_id = inventory_record.get("selected_event_revision_id")
        event_manifest_path = (
            operations / "pipeline" / "revisions" / str(event_revision_id) / "manifest.json"
        )
        event_content_path = event_manifest_path.parent / "content.json"
        if (
            not isinstance(event_revision_id, str)
            or not event_manifest_path.is_file()
            or not event_content_path.is_file()
        ):
            excluded.append(
                {
                    "recording_id": recording_id,
                    "reference_revision_id": audit["reference_revision_id"],
                    "reasons": ["selected event revision is incomplete"],
                }
            )
            continue
        event_manifest = _read_json(
            event_manifest_path, f"event revision manifest for {recording_id}"
        )
        event_content = _read_json(event_content_path, f"event revision content for {recording_id}")
        reference_content_path = (
            operations
            / "pipeline"
            / "revisions"
            / str(audit["reference_revision_id"])
            / "content.json"
        )
        reference_content = _read_json(
            reference_content_path, f"visible-card reference content for {recording_id}"
        )
        event_ids = {
            event.get("event_id")
            for event in event_content.get("events", [])
            if isinstance(event, dict)
        }
        outcome_ids = {
            outcome.get("event_id")
            for outcome in reference_content.get("outcomes", [])
            if isinstance(outcome, dict)
        }
        event_source = event_manifest.get("source")
        if (
            event_manifest.get("revision_id") != event_revision_id
            or event_manifest.get("recording_id") != recording_id
            or event_manifest.get("content_type") != "events"
            or event_manifest.get("content_schema") != "event-data/v1"
            or event_manifest.get("content_sha256") != sha256_json(event_content)
            or not isinstance(event_source, dict)
            or event_source.get("video_sha256") != bundle["source_sha256"]
            or event_ids != outcome_ids
        ):
            excluded.append(
                {
                    "recording_id": recording_id,
                    "reference_revision_id": audit["reference_revision_id"],
                    "reasons": [
                        "selected event and visible-card lineage or frame scope does not match"
                    ],
                }
            )
            continue
        if audit["reference_revision_id"] is None or not audit["samples"]:
            excluded.append(
                {
                    "recording_id": recording_id,
                    "reference_revision_id": audit["reference_revision_id"],
                    "reasons": ["reference has no eligible retained detection samples"],
                }
            )
            continue
        group_lineage = {
            "source_group_id": source_group_id,
            "session_id": bundle["session_id"],
            "table_setup": bundle["table_setup"],
            "source_asset_id": bundle["source_asset_id"],
            "source_video_sha256": bundle["source_sha256"],
        }
        eligible.append(
            {
                "recording_id": recording_id,
                "source_permission": bundle["source_permission"],
                "allowed_uses": bundle["allowed_uses"],
                "source_group": group_lineage,
                "prior_partitions": {
                    "cardeventnet": inventory_record.get("cardeventnet_partition"),
                    "rfdetr": inventory_record.get("rfdetr_partition"),
                    "dino": inventory_record.get("dino_partition"),
                },
                "source": {
                    "bundle_manifest_path": bundle["manifest_path"],
                    "bundle_manifest_sha256": bundle["manifest_sha256"],
                    "source_record_path": bundle["source_record_path"],
                    "source_record_sha256": bundle["source_record_sha256"],
                    "source_bytes_verified": bundle["source_bytes_verified"],
                },
                "reference": {
                    "revision_id": audit["reference_revision_id"],
                    "content_schema": "visible-card-data/v2",
                    "manifest_path": audit["reference_revision_manifest_path"],
                    "manifest_sha256": audit["reference_revision_manifest_sha256"],
                    "content_sha256": audit["reference_content_sha256"],
                    "reviewed_frame_count": audit["reviewed_frame_count"],
                    "retained_frame_count": audit["retained_frame_count"],
                    "excluded_frame_count": audit["excluded_frame_count"],
                    "ignored_region_count": audit["ignored_region_count"],
                    "visible_card_target_count": audit["target_count"],
                    "pile_target_count": audit["pile_target_count"],
                    "pile_reviewed_frame_count": audit["pile_reviewed_frame_count"],
                    "samples": audit["samples"],
                    "excluded_frames": audit["excluded_frames"],
                    "ineligible_outcomes": audit["ineligible_outcomes"],
                },
                "event_reference": {
                    "revision_id": event_revision_id,
                    "manifest_path": _relative(event_manifest_path, repository),
                    "manifest_sha256": sha256_json(event_manifest),
                    "content_sha256": sha256_json(event_content),
                    "event_frame_ids": sorted(event_ids),
                },
            }
        )

    core: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "status": "ready" if eligible else "blocked",
        "purpose": "detection_only",
        "recording_dispositions": dispositions,
        "identity_labels_included": False,
        "source_inventory": {
            "path": _relative(inventory_file, repository),
            "manifest_sha256": inventory_digest,
            "candidate_recordings": list(candidate_ids),
        },
        "policy": {
            "required_content_schema": "visible-card-data/v2",
            "pile_coverage_required": True,
            "reviewed_ignore_policy": "exclude_frame_on_any_reviewed_ignore_region",
            "background_policy": "reviewed_empty_frames_are_not_background_negatives",
            "prior_evaluation_uses": [
                {
                    "campaign": "0067",
                    "purpose": "validation",
                    "recording_ids": [
                        "cardeventnet-IMG_0090",
                        "cardeventnet-IMG_0091",
                        "cardeventnet-IMG_0661",
                    ],
                },
                {
                    "campaign": "0068",
                    "purpose": "sealed_test_evaluation",
                    "recording_ids": [
                        "cardeventnet-IMG_0646",
                        "cardeventnet-IMG_0648",
                        "cardeventnet-IMG_0649",
                    ],
                },
                {
                    "campaign": "0087",
                    "purpose": "validation",
                    "recording_ids": ["cardeventnet-IMG_0097"],
                },
                {
                    "campaign": "0087",
                    "purpose": "sealed_test_evaluation",
                    "recording_ids": ["cardeventnet-IMG_0654"],
                },
            ],
            "partition_policy": "handoff does not assign train, validation, or test partitions",
        },
        "summary": {
            "candidate_recording_count": len(candidate_ids),
            "eligible_recording_count": len(eligible),
            "excluded_recording_count": len(excluded),
            "reviewed_frame_count": sum(
                item["reference"]["reviewed_frame_count"] for item in eligible
            ),
            "retained_frame_count": sum(
                item["reference"]["retained_frame_count"] for item in eligible
            ),
            "visible_card_target_count": sum(
                item["reference"]["visible_card_target_count"] for item in eligible
            ),
            "pile_target_count": sum(item["reference"]["pile_target_count"] for item in eligible),
        },
        "eligible_recordings": eligible,
        "excluded_recordings": excluded,
        "protected_exclusions": inventory.get("scope", {}).get("exclusions", []),
    }
    core["handoff_sha256"] = sha256_json(core)
    return core


def write_reviewed_visible_card_handoff(path: str | Path, handoff: dict[str, Any]) -> Path:
    """Write the exact handoff as canonical, digest-backed JSON."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(handoff, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def validate_reviewed_visible_card_handoff(handoff: dict[str, Any]) -> None:
    """Reject edited or incomplete handoff payloads."""

    digest = handoff.get("handoff_sha256")
    core = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    if digest != sha256_json(core):
        raise ValueError("0086 detection handoff digest does not match its contents")
    if handoff.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        raise ValueError("0086 detection handoff has an unsupported schema")
    if handoff.get("status") not in {"ready", "blocked"}:
        raise ValueError("0086 detection handoff has an invalid status")
    eligible = handoff.get("eligible_recordings")
    if not isinstance(eligible, list):
        raise ValueError("0086 detection handoff has no eligible recording list")
    for item in eligible:
        if (
            not isinstance(item, dict)
            or item.get("reference", {}).get("content_schema") != "visible-card-data/v2"
        ):
            raise ValueError("0086 detection handoff contains a non-v2 reference")


__all__ = [
    "build_reviewed_visible_card_handoff",
    "validate_reviewed_visible_card_handoff",
    "write_reviewed_visible_card_handoff",
]
