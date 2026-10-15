from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def build_0086_m5_campaign_handoff(repository: Path) -> dict[str, Any]:
    readiness_path = repository / "docs/reports/0086-M5_Visual_Identity_Readiness.json"
    audit_path = repository / "docs/reports/0086-M4_Geometry_Review_Audit.json"
    dispositions_path = repository / "docs/reports/0086-M4_Recording_Dispositions.json"
    readiness, audit = _read(readiness_path), _read(audit_path)
    dispositions = _read(dispositions_path)
    readiness_core = {key: value for key, value in readiness.items() if key != "report_sha256"}
    if _sha256(_canonical(readiness_core)) != readiness.get("report_sha256"):
        raise ValueError("M5 readiness report digest does not match its content")
    eligible_ids = {
        row["recording_id"]
        for row in audit["recordings"]
        if row.get("disposition") == "active" and row.get("detection_handoff_eligible")
    }
    readiness_rows = {row["recording_id"]: row for row in readiness["recordings"]}
    audit_rows = {row["recording_id"]: row for row in audit["recordings"]}
    if not eligible_ids.issubset(readiness_rows):
        raise ValueError("M5 readiness report is missing an M4 eligible recording")

    recording_rows = []
    pile_count = 0
    coverage_counts: Counter[str] = Counter()
    grouping_provenance = []
    pile_policy_by_id: Counter[str] = Counter()
    post_m4_geometry_checks = []
    for recording_id in sorted(eligible_ids):
        ready = readiness_rows[recording_id]
        audit_row = audit_rows[recording_id]
        visible_ref = ready["visible_card_revision"]
        state_path = (
            repository
            / "data/operations/pipeline-references"
            / recording_id
            / "visible_cards/state.json"
        )
        state_bytes = state_path.read_bytes()
        state = json.loads(state_bytes)
        if (
            state.get("selected_completed_revision_id") != visible_ref["revision_id"]
            or _sha256(state_bytes) != visible_ref["state_sha256"]
        ):
            raise ValueError(
                "M5 readiness report does not name the current visible-card reference "
                f"for {recording_id}"
            )
        revision_root = (
            repository / "data/operations/pipeline/revisions" / visible_ref["revision_id"]
        )
        content_path, manifest_path = (
            revision_root / "content.json",
            revision_root / "manifest.json",
        )
        content_bytes, manifest_bytes = content_path.read_bytes(), manifest_path.read_bytes()
        content, manifest = json.loads(content_bytes), json.loads(manifest_bytes)
        content_digest = _sha256(_canonical(content))
        manifest_digest = _sha256(_canonical(manifest))
        if content_digest != visible_ref["content_sha256"]:
            raise ValueError(f"selected visible-card content changed for {recording_id}")
        if manifest_digest != visible_ref["manifest_sha256"]:
            raise ValueError(f"selected visible-card manifest changed for {recording_id}")
        if manifest.get("revision_id") != visible_ref["revision_id"]:
            raise ValueError(f"visible-card manifest revision mismatch for {recording_id}")

        # M5 review can publish the same geometry with a corrected card ID. Prove the exact
        # frame and geometry set against the completed M4 source revision before carrying it on.
        old_revision_id = audit_row.get("selected_completed_revision_id")
        old_content_path = (
            repository
            / "data/operations/pipeline/revisions"
            / str(old_revision_id)
            / "content.json"
        )
        if old_revision_id != visible_ref["revision_id"]:
            old_content = _read(old_content_path)
            old_pairs = {
                (
                    json.dumps(outcome.get("frame_identity"), sort_keys=True),
                    _sha256(_canonical(candidate.get("geometry"))),
                )
                for outcome in old_content.get("outcomes", [])
                if outcome.get("status") == "detected"
                for candidate in outcome.get("candidates", [])
            }
            current_pairs = {
                (
                    json.dumps(outcome.get("frame_identity"), sort_keys=True),
                    _sha256(_canonical(candidate.get("geometry"))),
                )
                for outcome in content.get("outcomes", [])
                if outcome.get("status") == "detected"
                for candidate in outcome.get("candidates", [])
            }
            if old_pairs != current_pairs:
                raise ValueError(f"visible-card geometry changed after M4 for {recording_id}")
            post_m4_geometry_checks.append(
                {
                    "recording_id": recording_id,
                    "m4_revision_id": old_revision_id,
                    "m5_revision_id": visible_ref["revision_id"],
                    "geometry_match_by_exact_frame": True,
                    "card_ids_may_differ": True,
                }
            )

        piles = []
        for outcome in content.get("outcomes", []):
            for pile in outcome.get("pile_regions", []) or []:
                pile_count += 1
                pile_policy_by_id[
                    pile.get("normalization", {}).get("policy_id", "unspecified")
                ] += 1
                provenance = {
                    "recording_id": recording_id,
                    "frame_identity": outcome.get("frame_identity"),
                    "pile_id": pile.get("pile_id"),
                    "grouped_candidates": pile.get("grouped_candidates", []),
                    "grouped_card_states": pile.get("grouped_card_states", []),
                    "grouped_scene_decision": pile.get("grouped_scene_decision"),
                    "source_candidates": pile.get("source_candidates", []),
                }
                grouping_provenance.append(provenance)
                piles.append(provenance)

        draft_path = (
            repository
            / "data/operations/pipeline-references"
            / recording_id
            / "visible_cards/draft.json"
        )
        draft_bytes = draft_path.read_bytes()
        draft_digest = _sha256(draft_bytes)
        draft = json.loads(draft_bytes)
        missing_coverage = [
            item.get("item_id")
            for item in draft.get("items", [])
            if item.get("review_state") in {"accepted", "corrected"}
            and "pile_regions" not in item.get("item", {})
        ]
        if missing_coverage:
            raise ValueError(f"accepted geometry has no explicit pile coverage for {recording_id}")
        decisions = Counter(
            frame.get("decision", "unspecified")
            for frame in (draft.get("coverage") or {}).get("frames", [])
        )
        coverage_counts.update(decisions)
        recording_rows.append(
            {
                "recording_id": recording_id,
                "source_group": ready["source_group"],
                "visible_card_revision": visible_ref,
                "visual_identity_revision": ready["visual_identity_revision"],
                "positive_crop_count": ready["positive_crop_count"],
                "class_support": ready["class_support"],
                "pile_review": {
                    "coverage_decision_counts": dict(sorted(decisions.items())),
                    "coverage_frame_count": sum(decisions.values()),
                    "pile_target_count": len(piles),
                    "grouping_provenance": piles,
                    "draft_sha256": draft_digest,
                    "m4_audited_draft_sha256": audit_row.get("reference_draft_sha256"),
                    "m4_audit_draft_changed_after_m5_publication": draft_digest
                    != audit_row.get("reference_draft_sha256"),
                },
            }
        )

    class_support: dict[str, Any] = {}
    classes = readiness["target_classes"]
    for name in classes:
        samples = sum(row["class_support"].get(name, 0) for row in recording_rows)
        recordings = [row for row in recording_rows if row["class_support"].get(name, 0)]
        class_support[name] = {
            "sample_count": samples,
            "recording_count": len(recordings),
            "source_group_count": len(
                {row["source_group"].get("source_group_id") for row in recordings}
            ),
        }

    pending = readiness.get("recordings_still_needing_human_decisions", [])
    missing_classes = [name for name, row in class_support.items() if row["sample_count"] == 0]
    missing_pile_coverage = {
        row["recording_id"]: audit_rows[row["recording_id"]][
            "accepted_items_without_explicit_pile_coverage"
        ]
        for row in recording_rows
        if audit_rows[row["recording_id"]]["accepted_items_without_explicit_pile_coverage"]
    }
    complete = (
        len(eligible_ids) == audit["detection_handoff_summary"]["eligible_recording_count"]
        and len(classes) == 21
        and readiness.get("identity_review_complete") is True
        and not pending
        and not missing_classes
        and not missing_pile_coverage
        and all(row["visible_card_revision"].get("revision_id") for row in recording_rows)
        and all(
            row["visual_identity_revision"].get("revision_id")
            or row["visual_identity_revision"].get("reason")
            for row in recording_rows
        )
    )

    geometry_exclusions = [
        {
            "recording_id": row["recording_id"],
            "disposition": row["disposition"],
            "reason": dispositions.get("recordings", {})
            .get(row["recording_id"], {})
            .get("reason", "; ".join(row.get("handoff_exclusion_reasons", []))),
            "source_sha256": dispositions.get("recordings", {})
            .get(row["recording_id"], {})
            .get("source_sha256"),
            "unfinished_item_ids": row.get("unfinished_item_ids", []),
            "accepted_items_without_explicit_pile_coverage": row.get(
                "accepted_items_without_explicit_pile_coverage", []
            ),
        }
        for row in audit["recordings"]
        if row["recording_id"] not in eligible_ids
    ]
    identity_exclusions = readiness["exclusions"]
    exclusion_counts = Counter(row.get("reason", "unspecified") for row in identity_exclusions)
    core = {
        "schema_version": "0086-m5-dino-campaign-handoff/v1",
        "handoff_status": "complete" if complete else "incomplete",
        "handoff_complete": complete,
        "status_reason": "all_required_reviews_and_handoff_inputs_present"
        if complete
        else "handoff_gate_failed",
        "target": {
            "class_count": len(classes),
            "classes": classes,
            "pool_policy": (
                "20 face-up identities plus FACE_DOWN; NINE is not in this recording pool"
            ),
        },
        "inputs": {
            "readiness_report": {
                "path": "docs/reports/0086-M5_Visual_Identity_Readiness.json",
                "sha256": readiness["report_sha256"],
            },
            "m4_geometry_audit": {
                "path": "docs/reports/0086-M4_Geometry_Review_Audit.json",
                "sha256": audit["report_sha256"],
            },
            "m4_detection_handoff_sha256": audit["detection_handoff_sha256"],
            "m4_detection_handoff_summary": audit["detection_handoff_summary"],
            "recording_dispositions": {
                "path": "docs/reports/0086-M4_Recording_Dispositions.json",
                "sha256": dispositions["receipt_sha256"],
            },
            "annotation_crop_contract": {
                "epic": "0093 M5",
                "path": "docs/reports/0093-M5_Visual_Identity_Input_Handoff.md",
                "identity_schema": "visual-identity-data/v2",
                "visible_card_schema": "visible-card-data/v2",
                "materialization_schema": "reviewed-visual-identity-materialization/v1",
                "crop_policy": "oracle_visible_region",
            },
            "dino_recipe_contract": {
                "epic": "0094 M9",
                "path": "docs/reports/0094-M9_Local_Recipe_Handoff.md",
                "recipe_schema": "dinov3-identity-recipe/v1",
                "config_schema": "dinov3-identity-config/v2",
                "input_sizes_px": [224, 384, 448],
                "feature_layouts": ["cls", "cls_mean_patch"],
                "encoder_modes": ["frozen", "last_two_blocks"],
                "campaign_recipe_selection": (
                    "0088 M0 must freeze; this handoff does not select a recipe"
                ),
            },
        },
        "summary": {
            "eligible_recording_count": len(recording_rows),
            "recordings_with_positive_crops": sum(
                bool(row["positive_crop_count"]) for row in recording_rows
            ),
            "positive_crop_count": sum(row["positive_crop_count"] for row in recording_rows),
            "source_group_count": len(
                {row["source_group"].get("source_group_id") for row in recording_rows}
            ),
            "supported_class_count": sum(
                bool(row["sample_count"]) for row in class_support.values()
            ),
            "pile_target_count": pile_count,
            "pile_review_coverage_decision_counts": dict(sorted(coverage_counts.items())),
            "identity_exclusion_counts": dict(sorted(exclusion_counts.items())),
        },
        "class_support": class_support,
        "recordings": recording_rows,
        "post_m4_geometry_checks": post_m4_geometry_checks,
        "geometry_exclusions": geometry_exclusions,
        "identity_exclusions": identity_exclusions,
        "campaign_specific_gaps": {
            "recordings_still_needing_human_decisions": pending,
            "classes_without_positive_support": missing_classes,
            "face_down_support": class_support.get("FACE_DOWN"),
            "back_design_unspecified_recordings": readiness.get(
                "back_design_unspecified_recordings", []
            ),
            "recordings_without_positive_crops": [
                row["recording_id"] for row in recording_rows if not row["positive_crop_count"]
            ],
            "pile_coverage_missing_from_accepted_geometry": missing_pile_coverage,
            "m4_source_bytes_were_verified": audit.get("policy", {}).get(
                "source_bytes_verified", False
            ),
            "campaign_quality_floors_and_splits": (
                "must be frozen by 0088 M0 before materialization or training"
            ),
        },
        "pile_policy": {
            "schema": "pile-region/v1",
            "geometry": (
                "coarse source-frame envelope around one visible physical pile; "
                "internal gaps may be included"
            ),
            "normalization_policy_counts": dict(sorted(pile_policy_by_id.items())),
            "identity_targets": False,
            "grouping_provenance": grouping_provenance,
            "coverage_rule": (
                "every accepted geometry frame has explicit pile-review coverage; see "
                "per-recording draft digests and decision counts"
            ),
        },
        "reproduction": {
            "command": (
                "mise exec -- uv run --project operations python "
                "operations/scripts/build_0086_m5_campaign_handoff.py "
                "--repository-root . --output docs/reports/0086-M5_DINO_Campaign_Handoff.json"
            ),
            "read_only": True,
        },
    }
    return {**core, "handoff_sha256": _sha256(_canonical(core))}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the read-only 0086 M5 DINO campaign handoff."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path("docs/reports/0086-M5_DINO_Campaign_Handoff.json")
    )
    args = parser.parse_args()
    repository = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else repository / args.output
    report = build_0086_m5_campaign_handoff(repository)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        f"{report['handoff_status']}: {report['summary']['positive_crop_count']} crops; "
        f"{report['summary']['supported_class_count']}/21 classes; wrote {output}"
    )
    return 0 if report["handoff_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
