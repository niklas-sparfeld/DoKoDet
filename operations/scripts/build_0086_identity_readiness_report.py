from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from table_evidence_analyzer.cards import CARD_IDENTITIES
from table_evidence_analyzer.local_identity import FACE_DOWN_TARGET

from doko_operations.derived_view import ExactEventRequest, FFmpegFrameResolver
from doko_operations.pipeline_data import RecordingVideoSource
from doko_operations.visual_identity_materialization import (
    materialize_reviewed_visual_identity_crops,
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _selected_revision(
    repository: Path, recording_id: str, kind: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    state_path = (
        repository / "data/operations/pipeline-references" / recording_id / kind / "state.json"
    )
    if not state_path.is_file():
        return None, {"reason": "missing_reference_state"}
    state_bytes = state_path.read_bytes()
    state = json.loads(state_bytes)
    revision_id = state.get("selected_completed_revision_id")
    if not isinstance(revision_id, str) or not revision_id:
        return None, {
            "reason": "no_selected_completed_revision",
            "state_sha256": _sha256(state_bytes),
            "draft_state": state.get("draft_state"),
        }
    revision_root = repository / "data/operations/pipeline/revisions" / revision_id
    content_path = revision_root / "content.json"
    manifest_path = revision_root / "manifest.json"
    if not content_path.is_file() or not manifest_path.is_file():
        return None, {"reason": "missing_selected_revision_data", "revision_id": revision_id}
    content_bytes, manifest_bytes = content_path.read_bytes(), manifest_path.read_bytes()
    content, manifest = json.loads(content_bytes), json.loads(manifest_bytes)
    digest = _sha256(_canonical(content))
    details = {
        "revision_id": revision_id,
        "content_sha256": digest,
        "manifest_sha256": _sha256(_canonical(manifest)),
        "state_sha256": _sha256(state_bytes),
        "draft_state": state.get("draft_state"),
    }
    if manifest.get("revision_id") != revision_id or manifest.get("content_sha256") != digest:
        return None, {**details, "reason": "selected_revision_digest_mismatch"}
    return {
        "revision_id": revision_id,
        "content_digest": digest,
        "content": content,
        "manifest": manifest,
    }, details


def _draft_pending_card_ids(
    repository: Path,
    recording_id: str,
    already_decided_card_ids: set[str],
    current_visible_card_ids: set[str],
) -> list[str]:
    path = (
        repository
        / "data/operations/pipeline-references"
        / recording_id
        / "visual_identities/draft.json"
    )
    if not path.is_file():
        return []
    draft = _read(path)
    pending = []
    terminal = {
        "accepted",
        "corrected",
        "unusable",
        "rejected",
        "face_down",
        "identity_unusable",
    }
    for row in draft.get("items", []):
        if not isinstance(row, dict):
            continue
        item = row.get("item")
        card_id = item.get("card_id") if isinstance(item, dict) else row.get("item_id")
        if (
            not isinstance(card_id, str)
            or card_id not in current_visible_card_ids
            or card_id in already_decided_card_ids
        ):
            continue
        classifier = item.get("classifier") if isinstance(item, dict) else None
        candidates = item.get("candidates", []) if isinstance(item, dict) else []
        human_candidate = (
            isinstance(candidates, list)
            and len(candidates) == 1
            and isinstance(candidates[0], dict)
            and candidates[0].get("producer_id") == "human-reference.v1"
        )
        human_special_decision = (
            isinstance(classifier, dict)
            and classifier.get("provider") == "human-reference"
            and item.get("status") in {"face_down", "unusable"}
        )
        saved_human_decision = (
            isinstance(classifier, dict)
            and classifier.get("provider") == "human-reference"
            and (human_candidate or human_special_decision)
        )
        if row.get("review_state") not in terminal or not saved_human_decision:
            pending.append(card_id)
    return sorted(set(pending))


def _saved_human_decision_card_ids(
    visible_revision: dict[str, Any] | None, identity_revision: dict[str, Any] | None
) -> set[str]:
    if visible_revision is None or identity_revision is None:
        return set()
    visible_by_id: dict[str, dict[str, Any]] = {}
    for outcome in visible_revision["content"].get("outcomes", []):
        if not isinstance(outcome, dict) or outcome.get("status") != "detected":
            continue
        for candidate in outcome.get("candidates", []):
            if isinstance(candidate, dict) and isinstance(candidate.get("card_id"), str):
                visible_by_id[candidate["card_id"]] = {
                    "frame_identity": outcome.get("frame_identity"),
                    "geometry": candidate.get("geometry"),
                }
    decided: set[str] = set()
    for outcome in identity_revision["content"].get("outcomes", []):
        if not isinstance(outcome, dict):
            continue
        card_id = outcome.get("card_id")
        visible = visible_by_id.get(card_id)
        if (
            visible is None
            or outcome.get("frame_identity") != visible["frame_identity"]
            or outcome.get("geometry") != visible["geometry"]
        ):
            continue
        classifier = outcome.get("classifier")
        candidates = outcome.get("candidates", [])
        human_candidate = (
            isinstance(candidates, list)
            and len(candidates) == 1
            and isinstance(candidates[0], dict)
            and candidates[0].get("producer_id") == "human-reference.v1"
        )
        human_special = outcome.get("status") in {"face_down", "unusable"}
        receipt = identity_revision.get("manifest", {})
        producer = receipt.get("producer", {}) if isinstance(receipt, dict) else {}
        saved_human = (
            receipt.get("origin") in {"human", "corrected"}
            and isinstance(producer, dict)
            and producer.get("kind") == "human"
            and isinstance(classifier, dict)
            and classifier.get("provider") == "human-reference"
            and (human_candidate or human_special)
        )
        provenance = outcome.get("annotation_provenance")
        saved_annotation = (
            isinstance(provenance, dict)
            and classifier is None
            and provenance.get("visible_card_revision_id") == visible_revision["revision_id"]
            and provenance.get("visible_card_revision_digest") == visible_revision["content_digest"]
            and provenance.get("card_id") == card_id
            and provenance.get("frame_identity") == visible["frame_identity"]
            and provenance.get("geometry_digest") == _sha256(_canonical(visible["geometry"]))
        )
        if saved_human or saved_annotation:
            decided.add(card_id)
    return decided


def _visible_card_ids(visible_revision: dict[str, Any] | None) -> set[str]:
    if visible_revision is None:
        return set()
    return {
        candidate["card_id"]
        for outcome in visible_revision["content"].get("outcomes", [])
        if isinstance(outcome, dict) and outcome.get("status") == "detected"
        for candidate in outcome.get("candidates", [])
        if isinstance(candidate, dict) and isinstance(candidate.get("card_id"), str)
    }


def build_0086_identity_readiness_report(repository: Path, crop_output: Path) -> dict[str, Any]:
    inventory = _read(
        repository / "docs/reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json"
    )
    expected_classes = sorted(
        identity for identity in CARD_IDENTITIES if not identity.endswith("_NINE")
    ) + [FACE_DOWN_TARGET]
    recordings = [
        item
        for item in inventory["recordings"]
        if item.get("disposition") == "candidate-development"
        and item.get("source_permission") == "project_use"
    ]
    inputs: list[dict[str, Any]] = []
    initial_exclusions: list[dict[str, Any]] = []
    input_details: dict[str, dict[str, Any]] = {}
    visible_for_decisions: dict[str, dict[str, Any] | None] = {}
    identity_for_decisions: dict[str, dict[str, Any] | None] = {}
    for item in recordings:
        recording_id = item["recording_id"]
        visible_revision, visible_details = _selected_revision(
            repository, recording_id, "visible_cards"
        )
        identity_revision, identity_details = _selected_revision(
            repository, recording_id, "visual_identities"
        )
        visible_for_decisions[recording_id] = visible_revision
        identity_for_decisions[recording_id] = identity_revision
        input_details[recording_id] = {
            "visible_card_revision": visible_details,
            "visual_identity_revision": identity_details,
            "source_group": {
                "source_group_id": item.get("source_group_id"),
                "session_id": item.get("session_id"),
                "table_setup": item.get("table_setup"),
                "source_sha256": item.get("source_sha256"),
            },
        }
        if visible_revision is None or identity_revision is None:
            for kind, details in (
                ("visible_cards", visible_details),
                ("visual_identities", identity_details),
            ):
                if "reason" in details:
                    initial_exclusions.append(
                        {"recording_id": recording_id, "reference": kind, **details}
                    )
            continue
        if (
            visible_revision["manifest"].get("recording_id") != recording_id
            or identity_revision["manifest"].get("recording_id") != recording_id
        ):
            initial_exclusions.append(
                {"recording_id": recording_id, "reason": "revision_recording_mismatch"}
            )
            continue
        source = identity_revision["manifest"].get("source")
        if not isinstance(source, dict) or source.get("video_sha256") != item.get("source_sha256"):
            initial_exclusions.append(
                {"recording_id": recording_id, "reason": "source_lineage_mismatch"}
            )
            continue
        inputs.append(
            {
                "recording_id": recording_id,
                "source_lineage_group": input_details[recording_id]["source_group"],
                "source": source,
                "visible_card_revision": visible_revision,
                "visual_identity_revision": identity_revision,
            }
        )

    resolver = FFmpegFrameResolver()

    def resolve(frame_identity: dict[str, Any]):
        source_digest = frame_identity["source_video_sha256"]
        source_record = next(
            item["source"] for item in inputs if item["source"].get("video_sha256") == source_digest
        )
        source = RecordingVideoSource.from_mapping(source_record)
        request = ExactEventRequest(
            source=source,
            requested_time_us=frame_identity["requested_time_us"],
            output_encoding=frame_identity["output_encoding"],
        )
        return resolver.resolve(request, repository / source.relative_path)

    materialized = materialize_reviewed_visual_identity_crops(inputs, crop_output, resolve)
    samples_by_recording: dict[str, list[dict[str, Any]]] = {
        item["recording_id"]: [] for item in recordings
    }
    exclusions_by_recording: dict[str, list[dict[str, Any]]] = {
        item["recording_id"]: [] for item in recordings
    }
    for sample in materialized["samples"]:
        samples_by_recording[sample["recording_id"]].append(sample)
    for exclusion in [*initial_exclusions, *materialized["exclusions"]]:
        rid = exclusion.get("recording_id")
        if rid in exclusions_by_recording:
            exclusions_by_recording[rid].append(exclusion)

    for item in recordings:
        rid = item["recording_id"]
        decided = _saved_human_decision_card_ids(
            visible_for_decisions[rid],
            identity_for_decisions[rid],
        )
        input_details[rid]["human_decision_draft_pending_card_ids"] = _draft_pending_card_ids(
            repository,
            rid,
            decided,
            _visible_card_ids(visible_for_decisions[rid]),
        )

    class_counts = Counter(
        sample["target"]
        for sample in materialized["samples"]
        if sample["target"] in expected_classes
    )
    class_support = {
        name: {
            "sample_count": class_counts[name],
            "recording_count": len(
                {row["recording_id"] for row in materialized["samples"] if row["target"] == name}
            ),
            "source_group_count": len(
                {
                    row["source_lineage_group"].get("source_group_id")
                    for row in materialized["samples"]
                    if row["target"] == name
                }
            ),
        }
        for name in expected_classes
    }
    per_recording = []
    for item in recordings:
        rid = item["recording_id"]
        support = Counter(
            row["target"] for row in samples_by_recording[rid] if row["target"] in expected_classes
        )
        per_recording.append(
            {
                "recording_id": rid,
                "disposition": item["disposition"],
                **input_details[rid],
                "positive_crop_count": len(samples_by_recording[rid]),
                "class_support": {name: support[name] for name in expected_classes},
                "exclusions": sorted(
                    exclusions_by_recording[rid],
                    key=lambda row: (str(row.get("card_id", "")), str(row.get("reason", ""))),
                ),
            }
        )

    core = {
        "schema_version": "0086-m5-visual-identity-readiness/v1",
        "handoff_status": "incomplete",
        "handoff_complete": False,
        "status_reason": "human_review_gaps_and_campaign_handoff_gates_remain",
        "target_classes": expected_classes,
        "target_class_count": len(expected_classes),
        "nines_in_game_vocabulary_but_out_of_this_pool": True,
        "reference_inputs_read_only": True,
        "inventory_manifest_sha256": inventory.get("manifest_sha256"),
        "materialization_schema": materialized["schema_version"],
        "materialization_manifest_sha256": materialized["manifest_digest"],
        "summary": {
            "candidate_recording_count": len(recordings),
            "recordings_with_positive_crops": sum(
                bool(rows) for rows in samples_by_recording.values()
            ),
            "positive_crop_count": len(materialized["samples"]),
            "classes_with_support": sum(
                value["sample_count"] > 0 for value in class_support.values()
            ),
            "classes_without_support": [
                name for name, value in class_support.items() if value["sample_count"] == 0
            ],
        },
        "class_support": class_support,
        "back_design_support": materialized["back_design_support"],
        "back_design_unspecified_recordings": materialized["back_design_unspecified_recordings"],
        "duplicate_crop_groups": materialized["duplicate_crop_groups"],
        "recordings_still_needing_human_decisions": [
            {
                "recording_id": item["recording_id"],
                "pending_card_ids": input_details[item["recording_id"]][
                    "human_decision_draft_pending_card_ids"
                ],
                "reason": "visual_identity_draft_has_unresolved_items",
            }
            for item in recordings
            if input_details[item["recording_id"]]["human_decision_draft_pending_card_ids"]
        ],
        "recordings": per_recording,
        "samples": materialized["samples"],
        "exclusions": sorted(
            [*initial_exclusions, *materialized["exclusions"]],
            key=lambda row: (
                str(row.get("recording_id", "")),
                str(row.get("card_id", "")),
                str(row.get("reason", "")),
            ),
        ),
    }
    return {**core, "report_sha256": _sha256(_canonical(core))}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the read-only Epic 0086 M5 identity readiness report."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path("docs/reports/0086-M5_Visual_Identity_Readiness.json")
    )
    parser.add_argument("--crops", type=Path, default=Path(".runtime/0086-m5/identity-crops"))
    args = parser.parse_args()
    repository = args.repository_root.resolve()
    crops = args.crops if args.crops.is_absolute() else repository / args.crops
    report = build_0086_identity_readiness_report(repository, crops)
    output = args.output if args.output.is_absolute() else repository / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = report["summary"]
    print(
        f"{summary['positive_crop_count']} positive crops; "
        f"{summary['classes_with_support']}/21 classes supported; report written to {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
