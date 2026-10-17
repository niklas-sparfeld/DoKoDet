#!/usr/bin/env python3
"""Build the frozen, file-based identity review queue for epic 0098 M3."""

# Report prose and Markdown tables contain long lines by design.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

REPOSITORY = Path(__file__).resolve().parents[2]
MAX_FRAMES_PER_RECORDING = 5
LOW_CONFIDENCE = 0.50
LOW_MARGIN = 0.10


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _frame_key(outcome: dict[str, Any]) -> str:
    frame = outcome.get("frame_identity")
    if not isinstance(frame, dict):
        raise ValueError(f"identity outcome has no frame identity: {outcome.get('card_id')}")
    return canonical_sha256(frame)


def _candidate_metrics(outcome: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    ranked = sorted(
        outcome.get("candidates") or [],
        key=lambda candidate: float(candidate.get("score", -1.0)),
        reverse=True,
    )
    if not ranked:
        return None, None, None
    confidence = float(ranked[0]["score"])
    margin = confidence - float(ranked[1]["score"]) if len(ranked) > 1 else None
    return confidence, margin, ranked[0].get("identity")


def _outcome_priority(outcome: dict[str, Any]) -> tuple[Any, ...]:
    status = outcome.get("status")
    confidence, margin, _ = _candidate_metrics(outcome)
    diagnostic = status in {"failed", "unusable"} or bool(outcome.get("error"))
    face_down = status == "face_down"
    margin_priority = margin if margin is not None else 1.0
    confidence_priority = confidence if confidence is not None else 1.0
    return (
        not diagnostic,
        not face_down,
        not (margin is not None and margin < LOW_MARGIN),
        not (confidence is not None and confidence < LOW_CONFIDENCE),
        margin_priority,
        confidence_priority,
        str(outcome.get("card_id", "")),
    )


def _reason_tags(outcome: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = outcome.get("status")
    confidence, margin, _ = _candidate_metrics(outcome)
    if status == "face_down":
        reasons.append("face_down_prediction")
    if status in {"failed", "unusable"} or outcome.get("error"):
        reasons.append("crop_or_classifier_diagnostic")
    if margin is not None and margin < LOW_MARGIN:
        reasons.append("low_top1_top2_margin")
    if confidence is not None and confidence < LOW_CONFIDENCE:
        reasons.append("low_top1_confidence")
    return reasons


def _selection_pointer(operations_root: Path, recording_id: str) -> dict[str, Any]:
    path = operations_root / "pipeline" / "selections" / recording_id / "visual_identities.json"
    if not path.is_file():
        return {"status": "unavailable", "reason": "selection_pointer_missing"}
    value = read_json(path)
    return {
        "status": "available",
        "path": str(path),
        "content_sha256": sha256(path),
        "selected_generated_revision_id": value.get("selected_generated_revision_id"),
        "selected_completed_reference_revision_id": value.get(
            "selected_completed_reference_revision_id"
        ),
    }


def _draft_status(
    operations_root: Path, recording_id: str, target_revision_id: str
) -> dict[str, Any]:
    root = operations_root / "pipeline-references" / recording_id / "visual_identities"
    state_path = root / "state.json"
    draft_path = root / "draft.json"
    if not state_path.is_file() and not draft_path.is_file():
        return {"status": "no_saved_reference_state"}
    if not state_path.is_file() or not draft_path.is_file():
        return {"status": "unavailable", "reason": "incomplete_reference_state"}
    state = read_json(state_path)
    draft = read_json(draft_path)
    source_revision_id = draft.get("source_revision_id")
    state_name = state.get("draft_state")
    conflict = state_name == "draft" and source_revision_id != target_revision_id
    return {
        "status": "conflict_preserved" if conflict else state_name or "unknown",
        "draft_revision": state.get("draft_revision"),
        "draft_source_revision_id": source_revision_id,
        "draft_content_sha256": sha256(draft_path),
        "conflicts_with_queue_target": conflict,
        "reason": "live_draft_targets_another_revision" if conflict else None,
    }


def _editor_url(recording_id: str, revision_id: str, card_id: str, time_us: int) -> str:
    query = urlencode(
        {
            "view": "generated",
            "revision": revision_id,
            "item": card_id,
            "t_us": str(time_us),
        }
    )
    return f"/recordings/{recording_id}/pipeline/visual_identities?{query}"


def build_report(
    repository: Path,
    pipeline_store: Path,
    operations_root: Path,
    live_backend_status: str = "not_probed",
    live_backend_reason: str | None = None,
) -> dict[str, Any]:
    m0_path = repository / "docs/reports/0098-M0_Frozen_Inputs.json"
    m1_path = repository / "docs/reports/0098-M1_Identity_Batch.json"
    m2_path = repository / "docs/reports/0098-M2_Identity_Diagnostics.json"
    m0, m1, m2 = (read_json(path) for path in (m0_path, m1_path, m2_path))
    if m2["inputs"]["m0_manifest_sha256"] != sha256(m0_path):
        raise ValueError("M2 report does not match the current M0 manifest")
    if m2["inputs"]["m1_report_sha256"] != sha256(m1_path):
        raise ValueError("M2 report does not match the current M1 report")
    if m2["inputs"]["pipeline_store"] != str(pipeline_store):
        raise ValueError("pipeline store differs from the store frozen by M2")

    frozen = {record["recording_id"]: record for record in m0["recordings"]}
    diagnostic = {record["recording_id"]: record for record in m2["recordings"]}
    queue: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    revisions = pipeline_store / "revisions"

    for recording_id in sorted(m1["recordings"]):
        run = m1["recordings"][recording_id]
        record_diagnostics = diagnostic[recording_id]
        frozen_record = frozen[recording_id]
        revision_id = run["output_revision_id"]
        revision_path = revisions / revision_id
        output_path = revision_path / "content.json"
        manifest_path = revision_path / "manifest.json"
        if not output_path.is_file() or not manifest_path.is_file():
            raise FileNotFoundError(f"M1 identity result is missing: {revision_id}")
        output = read_json(output_path)
        manifest = read_json(manifest_path)
        output_digest = canonical_sha256(output)
        if (
            manifest.get("revision_id") != revision_id
            or manifest.get("content_type") != "visual_identities"
            or manifest.get("content_sha256") != output_digest
            or output_digest != run["output_content_sha256"]
        ):
            raise ValueError(f"M1 output digest mismatch for {recording_id}")
        if output_digest != record_diagnostics["output_lineage"]["content_sha256"]:
            raise ValueError(f"M2 output digest mismatch for {recording_id}")

        outcomes = output.get("outcomes", [])
        by_frame: dict[str, list[dict[str, Any]]] = defaultdict(list)
        frame_ids = {
            canonical_sha256(receipt["frame_identity"]): receipt["frame_id"]
            for receipt in frozen_record.get("crop_geometry_receipts", [])
        }
        status_counts: Counter[str] = Counter()
        for outcome in outcomes:
            status = outcome.get("status", "missing")
            status_counts[status] += 1
            if status in {"classified", "face_down", "unusable", "failed"}:
                by_frame[_frame_key(outcome)].append(outcome)

        frame_candidates: list[dict[str, Any]] = []
        for frame_key, frame_outcomes in by_frame.items():
            selected = sorted(frame_outcomes, key=_outcome_priority)[0]
            identity = selected["frame_identity"]
            if selected.get("card_id") not in set(manifest.get("coverage", {}).get("card_ids", [])):
                raise ValueError(
                    f"selected card is absent from the M1 revision manifest: {recording_id}"
                )
            confidence, margin, predicted = _candidate_metrics(selected)
            frame_candidates.append(
                {
                    "frame_key": frame_key,
                    "frame_identity": identity,
                    "frame_id": frame_ids.get(frame_key),
                    "card_id": selected.get("card_id"),
                    "status": selected.get("status"),
                    "confidence": confidence,
                    "top1_top2_margin": margin,
                    "predicted_identity": predicted,
                    "reason_tags": _reason_tags(selected),
                    "outcome": selected,
                }
            )

        priority_candidates = [item for item in frame_candidates if item["reason_tags"]]
        priority_candidates.sort(
            key=lambda item: (
                "face_down_prediction" not in item["reason_tags"],
                "crop_or_classifier_diagnostic" not in item["reason_tags"],
                item["top1_top2_margin"] if item["top1_top2_margin"] is not None else 1.0,
                item["confidence"] if item["confidence"] is not None else 1.0,
                item["frame_key"],
            )
        )
        controls = [
            item
            for item in frame_candidates
            if item["status"] == "classified"
            and "low_top1_confidence" not in item["reason_tags"]
            and "low_top1_top2_margin" not in item["reason_tags"]
        ]
        controls.sort(
            key=lambda item: (
                -(item["top1_top2_margin"] if item["top1_top2_margin"] is not None else -1.0),
                -(item["confidence"] if item["confidence"] is not None else -1.0),
                item["frame_key"],
            )
        )
        selected_frames = priority_candidates[: MAX_FRAMES_PER_RECORDING - 1]
        if controls and controls[0] not in selected_frames:
            selected_frames.append(controls[0])
        elif len(selected_frames) < MAX_FRAMES_PER_RECORDING:
            remaining = [
                item
                for item in priority_candidates[MAX_FRAMES_PER_RECORDING - 1 :]
                if item not in selected_frames
            ]
            selected_frames.extend(remaining[: MAX_FRAMES_PER_RECORDING - len(selected_frames)])
        selected_frames = selected_frames[:MAX_FRAMES_PER_RECORDING]

        pointer = _selection_pointer(operations_root, recording_id)
        draft_status = _draft_status(operations_root, recording_id, revision_id)
        items_for_recording = 0
        for index, selected in enumerate(selected_frames, start=1):
            outcome = selected["outcome"]
            identity = selected["frame_identity"]
            frame_reason = list(selected["reason_tags"])
            if not frame_reason:
                frame_reason = ["deterministic_control"]
            item = {
                "recording_id": recording_id,
                "source_group_id": frozen_record.get("source_group_id"),
                "m6_training_overlap": bool(frozen_record.get("m6_training_overlap")),
                "frame_ordinal_in_recording": index,
                "frame_id": selected["frame_id"],
                "frame_identity": identity,
                "frame_identity_sha256": canonical_sha256(identity),
                "card_id": selected["card_id"],
                "outcome_status": selected["status"],
                "predicted_identity": selected["predicted_identity"],
                "top1_confidence": selected["confidence"],
                "top1_top2_margin": selected["top1_top2_margin"],
                "selection_reasons": frame_reason,
                "crop_lineage": {
                    "crop_identity_sha256": canonical_sha256(outcome.get("crop_identity")),
                    "crop_policy": (outcome.get("crop_identity") or {}).get("crop_policy"),
                    "crop_content_type": (outcome.get("crop_identity") or {}).get("content_type"),
                    "source_frame_identity_sha256": canonical_sha256(
                        (outcome.get("crop_identity") or {}).get("frame_identity")
                    ),
                    "geometry_sha256": canonical_sha256(
                        (outcome.get("crop_identity") or {}).get("geometry")
                    ),
                    "visible_polygon_count": len(
                        (
                            ((outcome.get("crop_identity") or {}).get("geometry") or {}).get(
                                "visible_region"
                            )
                            or {}
                        ).get("polygons", [])
                    ),
                },
                "identity_result": {
                    "run_id": run["run_id"],
                    "revision_id": revision_id,
                    "content_sha256": output_digest,
                    "input_revision_ids": run["input_revision_ids"],
                    "crop_input_manifest_digest": run["crop_input_manifest_digest"],
                },
                "editor_target": {
                    "url": _editor_url(
                        recording_id,
                        revision_id,
                        selected["card_id"],
                        int(identity["presentation_timestamp_us"]),
                    ),
                    "artifact_status": "available_in_frozen_pipeline_store",
                    "current_selection_pointer": pointer,
                    "live_draft": draft_status,
                    "live_backend_verified": False,
                    "live_backend_status": live_backend_status,
                    "live_backend_reason": live_backend_reason
                    or "backend_was_not_probed_by_the_read_only_builder",
                },
            }
            frozen_item = {key: value for key, value in item.items() if key != "editor_target"}
            item["queue_item_id"] = canonical_sha256(frozen_item)
            queue.append(item)
            items_for_recording += 1

        coverage.append(
            {
                "recording_id": recording_id,
                "source_group_id": frozen_record.get("source_group_id"),
                "m6_training_overlap": bool(frozen_record.get("m6_training_overlap")),
                "input_crops": run["crop_input_item_count"],
                "outcomes": dict(sorted(status_counts.items())),
                "identity_bearing_frames": len(frame_candidates),
                "review_queue_frames": items_for_recording,
                "no_reviewable_identities": items_for_recording == 0,
                "selected_generated_revision_id": pointer.get("selected_generated_revision_id"),
                "queue_target_revision_id": revision_id,
                "editor_draft_status": draft_status["status"],
                "editor_draft_conflicts_with_target": draft_status.get(
                    "conflicts_with_queue_target", False
                ),
                "selection_pointer_status": pointer["status"],
                "selection_pointer_matches_target": pointer.get("selected_generated_revision_id")
                == revision_id,
            }
        )

    queue_digest = canonical_sha256([item["queue_item_id"] for item in queue])
    for item in queue:
        item["queue_digest"] = queue_digest
    draft_states = Counter(item["editor_draft_status"] for item in coverage)
    reason_counts = Counter(reason for item in queue for reason in item["selection_reasons"])
    pointer_states = Counter(
        "same_as_queue_target"
        if item["selection_pointer_matches_target"]
        else "different_from_queue_target"
        for item in coverage
    )
    return {
        "schema_version": "epic-0098-m3-identity-review-queue/v1",
        "epic": "0098",
        "milestone": "M3",
        "status": "complete",
        "queue_id": "epic-0098-identity-review-v1",
        "queue_digest": queue_digest,
        "inputs": {
            "m0_manifest_sha256": sha256(m0_path),
            "m1_report_sha256": sha256(m1_path),
            "m2_report_sha256": sha256(m2_path),
            "pipeline_store": str(pipeline_store),
            "operations_root": str(operations_root),
            "selection_policy": {
                "maximum_frames_per_recording": MAX_FRAMES_PER_RECORDING,
                "maximum_frames_total": 145,
                "low_confidence_below": LOW_CONFIDENCE,
                "low_top1_top2_margin_below": LOW_MARGIN,
                "ordering": [
                    "face_down_prediction",
                    "crop_or_classifier_diagnostic",
                    "lowest_top1_top2_margin",
                    "lowest_top1_confidence",
                    "one_high_margin_high_confidence_control_when_available",
                    "canonical_frame_identity_sha256_tiebreak",
                ],
                "one_card_item_per_selected_frame": True,
            },
            "editor_adapter": "relative URL with pinned generated revision and card item",
            "queue_builder": "operations/scripts/build_0098_m3_identity_review_queue.py",
        },
        "coverage": {
            "recordings": len(coverage),
            "review_queue_frames": len(queue),
            "maximum_frames_total": 145,
            "recordings_with_reviewable_identities": sum(
                not item["no_reviewable_identities"] for item in coverage
            ),
            "recordings_with_no_reviewable_identities": [
                item["recording_id"] for item in coverage if item["no_reviewable_identities"]
            ],
            "editor_draft_states": dict(sorted(draft_states.items())),
            "selection_reason_counts": dict(sorted(reason_counts.items())),
            "selection_pointer_states": dict(sorted(pointer_states.items())),
            "recordings_with_conflicting_drafts": [
                item["recording_id"]
                for item in coverage
                if item["editor_draft_conflicts_with_target"]
            ],
            "live_backend_status": live_backend_status,
            "live_backend_reason": live_backend_reason,
            "human_review_decisions_created": 0,
        },
        "recordings": coverage,
        "queue": queue,
        "handoff": {
            "adapter_file": "docs/reports/0098-M3_Identity_Review_Queue.json",
            "entry_report": "docs/reports/0098-M3_Identity_Review_Queue.md",
            "open_item": "open editor_target.url; it pins view=generated, revision, item, and source time",
            "draft_rule": "inspect live_draft before editing; preserve a draft that targets another revision",
            "review_state": "pending; queue membership and proposals are not human decisions",
            "reproduction": (
                "mise exec -- uv run --project operations python "
                "operations/scripts/build_0098_m3_identity_review_queue.py "
                "--pipeline-store /Users/niklas.sparfeld/Developer/doko_detector/data/operations/pipeline "
                "--operations-root /Users/niklas.sparfeld/Developer/doko_detector/data/operations "
                "--live-backend-status unavailable "
                "--live-backend-reason 'connection refused at http://127.0.0.1:8001'"
            ),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# Epic 0098 M3 identity review queue",
        "",
        "Status: complete. Human identity review remains pending.",
        "",
        "## Frozen queue",
        "",
        f"- Queue ID: `{report['queue_id']}`",
        f"- Queue digest: `{report['queue_digest']}`",
        f"- Selected frames: {coverage['review_queue_frames']} of at most 145.",
        f"- Recordings with reviewable identity outcomes: {coverage['recordings_with_reviewable_identities']} of {coverage['recordings']}.",
        f"- Recordings with no reviewable identity outcomes: {len(coverage['recordings_with_no_reviewable_identities'])}.",
        f"- Human review decisions created: {coverage['human_review_decisions_created']}.",
        f"- Selection reasons: `{json.dumps(coverage['selection_reason_counts'], sort_keys=True)}`.",
        "",
        "Each queue item selects one card result from one frame. The URL pins the exact generated revision, card item, and source time in the maintained-reference editor. Selection reasons include low confidence, low top-1/top-2 margin, face-down predictions, diagnostics when present, and one deterministic control when available. The proposal only routes review. It does not establish identity correctness.",
        "",
        "## Coverage",
        "",
        "| Recording | M6 training overlap | Identity-bearing frames | Queue frames | No reviewable identities |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for item in report["recordings"]:
        lines.append(
            f"| `{item['recording_id']}` | {'yes' if item['m6_training_overlap'] else 'no'} | {item['identity_bearing_frames']} | {item['review_queue_frames']} | {'yes' if item['no_reviewable_identities'] else 'no'} |"
        )
    lines += [
        "",
        "## Target and draft status",
        "",
        f"- Current selection pointers: `{json.dumps(coverage['selection_pointer_states'], sort_keys=True)}`. The queue URL pins its frozen result revision even when the current pointer names another run.",
        f"- Saved draft states: `{json.dumps(coverage['editor_draft_states'], sort_keys=True)}`. A draft with a different source revision is marked `conflict_preserved`; inspect it before any edit.",
        f"- Live editor backend status: `{coverage['live_backend_status']}` ({coverage['live_backend_reason'] or 'not probed'}). The builder verified local immutable result artifacts and recorded saved selection and draft state. Confirm editor access before review starts.",
        "- The 0097 queue API is unavailable in this checkout. This report is the documented file-based adapter input. It does not add queue UI.",
        "",
        "## Reproduction",
        "",
        "```sh",
        report["handoff"]["reproduction"],
        "```",
        "",
        "## Frozen inputs",
        "",
        f"- M0 manifest SHA-256: `{report['inputs']['m0_manifest_sha256']}`",
        f"- M1 report SHA-256: `{report['inputs']['m1_report_sha256']}`",
        f"- M2 report SHA-256: `{report['inputs']['m2_report_sha256']}`",
        "- Each `queue_item_id` covers frozen frame selection and result lineage. The `queue_digest` covers the ordered item IDs. Runtime editor and draft status is a separate snapshot.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=REPOSITORY)
    parser.add_argument("--pipeline-store", type=Path)
    parser.add_argument("--operations-root", type=Path)
    parser.add_argument(
        "--live-backend-status",
        choices=("not_probed", "available", "unavailable"),
        default="not_probed",
    )
    parser.add_argument("--live-backend-reason")
    args = parser.parse_args()
    repository = args.repository.resolve()
    m2 = read_json(repository / "docs/reports/0098-M2_Identity_Diagnostics.json")
    pipeline_store = (args.pipeline_store or Path(m2["inputs"]["pipeline_store"])).resolve()
    operations_root = (args.operations_root or pipeline_store.parent).resolve()
    report = build_report(
        repository,
        pipeline_store,
        operations_root,
        live_backend_status=args.live_backend_status,
        live_backend_reason=args.live_backend_reason,
    )
    json_path = repository / "docs/reports/0098-M3_Identity_Review_Queue.json"
    markdown_path = repository / "docs/reports/0098-M3_Identity_Review_Queue.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(render_markdown(report))
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Queue digest: {report['queue_digest']}")
    print(f"Queue frames: {report['coverage']['review_queue_frames']}")


if __name__ == "__main__":
    main()
