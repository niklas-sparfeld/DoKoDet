"""Report saved M4 decisions separately from detection-handoff eligibility."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from doko_operations.reviewed_visible_card_handoff import (
    build_reviewed_visible_card_handoff,
    sha256_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path("docs/reports/0086-M4_Geometry_Review_Audit.json")
    )
    args = parser.parse_args()
    repository = args.repository_root.resolve()
    handoff = build_reviewed_visible_card_handoff(repository)
    eligible_ids = {item["recording_id"] for item in handoff["eligible_recordings"]}
    excluded = {item["recording_id"]: item for item in handoff["excluded_recordings"]}
    rows = []
    for recording_id in handoff["source_inventory"]["candidate_recordings"]:
        reference = (
            repository / "data/operations/pipeline-references" / recording_id / "visible_cards"
        )
        state = json.loads((reference / "state.json").read_text())
        draft = json.loads((reference / "draft.json").read_text())
        items = draft["items"]
        missing_piles = [
            item["item_id"]
            for item in items
            if item["review_state"] in {"accepted", "corrected"}
            and "pile_regions" not in item["item"]
        ]
        unfinished = [
            item["item_id"]
            for item in items
            if item["review_state"] not in {"accepted", "corrected", "unusable", "rejected"}
        ]
        revision_id = state["selected_completed_revision_id"]
        manifest = (
            json.loads(
                (
                    repository
                    / "data/operations/pipeline/revisions"
                    / revision_id
                    / "manifest.json"
                ).read_text()
            )
            if revision_id
            else None
        )
        rows.append(
            {
                "recording_id": recording_id,
                "reference_state_sha256": sha256_json(state),
                "reference_draft_sha256": sha256_json(draft),
                "draft_state": state["draft_state"],
                "selected_completed_revision_id": revision_id,
                "selected_content_schema": manifest["content_schema"] if manifest else None,
                "draft_frame_count": len(items),
                "draft_review_states": dict(
                    sorted(Counter(x["review_state"] for x in items).items())
                ),
                "unfinished_item_ids": unfinished,
                "accepted_items_without_explicit_pile_coverage": missing_piles,
                "detection_handoff_eligible": recording_id in eligible_ids,
                "disposition": excluded.get(recording_id, {}).get("disposition", "active"),
                "handoff_exclusion_reasons": excluded.get(recording_id, {}).get("reasons", []),
            }
        )
    core = {
        "schema_version": "0086-geometry-review-audit/v1",
        "source_inventory": handoff["source_inventory"],
        "detection_handoff_sha256": handoff["handoff_sha256"],
        "detection_handoff_summary": handoff["summary"],
        "policy": {
            "read_only": True,
            "saved_decisions_do_not_imply_current_schema_eligibility": True,
            "missing_pile_coverage_is_not_a_reviewed_negative": True,
            "source_bytes_verified": False,
        },
        "summary": {
            "completed_reference_count": sum(row["draft_state"] == "completed" for row in rows),
            "draft_reference_count": sum(row["draft_state"] == "draft" for row in rows),
            "draft_frame_count": sum(row["draft_frame_count"] for row in rows),
            "unfinished_item_count": sum(len(row["unfinished_item_ids"]) for row in rows),
            "accepted_items_without_explicit_pile_coverage": sum(
                len(row["accepted_items_without_explicit_pile_coverage"]) for row in rows
            ),
            "active_accepted_items_without_explicit_pile_coverage": sum(
                len(row["accepted_items_without_explicit_pile_coverage"])
                for row in rows
                if row["disposition"] == "active"
            ),
            "active_recording_count": sum(row["disposition"] == "active" for row in rows),
        },
        "recordings": rows,
    }
    report = {**core, "report_sha256": sha256_json(core)}
    output = args.output if args.output.is_absolute() else repository / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{len(eligible_ids)} eligible; saved-decision audit written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
