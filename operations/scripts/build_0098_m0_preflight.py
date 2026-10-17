#!/usr/bin/env python3
"""Freeze the read-only input manifest for epic 0098 M0."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import uuid
from pathlib import Path
from typing import Any

from doko_operations.card_plane_geometry import derive_pose_scene_visible_regions

REPOSITORY = Path(__file__).resolve().parents[2]
SCENE_REPORT = REPOSITORY / "docs/reports/0096-M2_Proposed_Scene_Results.json"
PREFLIGHT_REPORT = REPOSITORY / "docs/reports/0096-M0_Preflight.json"
IDENTITY_REPORT = REPOSITORY / "docs/reports/0088-M0_Campaign_Readiness.json"
PIN_REPORT = REPOSITORY / "docs/reports/0088-M15_Qualification_Decision.json"
M1_REPORT = REPOSITORY / "docs/reports/0096-M1_Run_Result.json"
OUTPUT_JSON = REPOSITORY / "docs/reports/0098-M0_Frozen_Inputs.json"
OUTPUT_MD = REPOSITORY / "docs/reports/0098-M0_Frozen_Inputs.md"
EXPECTED_BUNDLE = "a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79"
EXPECTED_CHECKPOINT = "ff560c5a4e2fff70f7e6ab0ff0cef6e7fa8cab8bbdfbcd25af4c569ee4bdfb1a"
EXPECTED_TEMPERATURE = 0.6487642659
PROTECTED_FIELDS = (
    "system_holdout_source_group_ids",
    "0068_sealed_test_source_group_ids",
    "0087_sealed_test_source_group_ids",
    "0092_sealed_test_source_group_ids",
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_manifest(store_root: Path, model_bundle: Path) -> dict[str, Any]:
    scene_report = read_json(SCENE_REPORT)
    preflight_report = read_json(PREFLIGHT_REPORT)
    identity_report = read_json(IDENTITY_REPORT)
    pin_report = read_json(PIN_REPORT)
    m1_report = read_json(M1_REPORT)
    m1_summary = m1_report["summary"]

    m2_recordings = {item["recording_id"]: item for item in scene_report["recordings"]}
    preflight_recordings = {item["recording_id"]: item for item in preflight_report["recordings"]}
    if len(m2_recordings) != 33 or len(preflight_recordings) < 34:
        raise ValueError("0096 M0/M2 do not contain the expected frozen recording set")

    protected_groups = {
        group_id
        for field in PROTECTED_FIELDS
        for group_id in identity_report["protected_source_groups"][field]
    }
    training_groups = {
        item["source_group_id"] for item in identity_report["frozen_partitions"]["training"]
    }
    model_manifest_path = model_bundle / "manifest.json"
    model_manifest = read_json(model_manifest_path)
    pinned_candidate = pin_report["candidates"]["m6-seed17-224-cls-mean-patch"]
    if (
        pinned_candidate["bundle_sha256"] != EXPECTED_BUNDLE
        or pinned_candidate["checkpoint_sha256"] != EXPECTED_CHECKPOINT
        or model_manifest.get("bundle_digest") != EXPECTED_BUNDLE
        or model_manifest.get("source_checkpoint_sha256") != EXPECTED_CHECKPOINT
    ):
        raise ValueError("local M6 bundle does not match the 0088 M15 pin")

    checked_model_files = {}
    for name, expected in sorted(model_manifest["files"].items()):
        path = model_bundle / name
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"M6 bundle file digest mismatch: {name}")
        checked_model_files[name] = actual

    geometry_source = REPOSITORY / "operations/src/doko_operations/card_plane_geometry.py"
    crop_source = REPOSITORY / "operations/src/doko_operations/derived_view.py"
    frozen_recordings = []
    excluded_recordings = []
    failed_recordings = []
    total_scene_frames = 0
    usable_geometry_count = 0
    unusable_geometry_count = 0
    zero_crop_frame_count = 0
    training_overlap_crop_count = 0
    non_training_crop_count = 0

    # Include the M1 dependency failure and all M2 outcomes in one accounted list.
    all_ids = set(m2_recordings)
    m1_failure_id = m1_report["terminal_failure"]["recording_id"]
    all_ids.add(m1_failure_id)

    for recording_id in sorted(all_ids):
        m2 = m2_recordings.get(recording_id)
        preflight = preflight_recordings.get(recording_id)
        if preflight is None:
            raise ValueError(f"0096 source ledger misses {recording_id}")
        if m2 is None:
            failed_recordings.append(
                {
                    "recording_id": recording_id,
                    "stage": "0096 M1",
                    "reason": m1_report["terminal_failure"]["reason"],
                    "unprocessed_frames": m1_report["terminal_failure"]["progress"]["total"],
                    "source_group_id": preflight.get("source_group", {}).get("source_group_id"),
                    "source_permission": preflight.get("source_permission"),
                }
            )
            continue
        if m2["status"] != "complete":
            failed_recordings.append(
                {
                    "recording_id": recording_id,
                    "stage": "0096 M2",
                    "reason": m2.get("failure_code"),
                    "unprocessed_frames": m2.get("unprocessed_frame_count"),
                    "source_group_id": preflight.get("source_group", {}).get("source_group_id"),
                    "source_permission": preflight.get("source_permission"),
                }
            )
            continue

        source_group_id = preflight.get("source_group", {}).get("source_group_id")
        protected = source_group_id in protected_groups
        if not preflight.get("execution_eligibility", {}).get("eligible"):
            raise ValueError(f"successful scene has no source permission: {recording_id}")
        if protected:
            excluded_recordings.append(
                {
                    "recording_id": recording_id,
                    "source_asset_id": preflight.get("source_asset_id"),
                    "source_group_id": source_group_id,
                    "source_permission": preflight.get("source_permission"),
                    "source_video_sha256": preflight.get("video_sha256"),
                    "scene_run_id": m2["m2_run_id"],
                    "scene_revision_id": m2["scene_revision_id"],
                    "scene_revision_sha256": m2["scene_revision_sha256"],
                    "frame_count": m2["input_frame_count"],
                    "disposition": "excluded_protected_source_group",
                    "exclusion_reason": (
                        "source group appears in a protected test or system holdout"
                    ),
                }
            )
            continue

        scene_id = m2["scene_revision_id"]
        revision_path = store_root / "data/operations/pipeline/revisions" / scene_id
        content_path = revision_path / "content.json"
        manifest_path = revision_path / "manifest.json"
        if not content_path.is_file() or not manifest_path.is_file():
            raise ValueError(f"primary pipeline store misses scene receipt {scene_id}")
        content = read_json(content_path)
        scene_manifest = read_json(manifest_path)
        if (
            scene_manifest.get("content_sha256") != m2["scene_revision_sha256"]
            or scene_manifest.get("revision_id") != scene_id
        ):
            raise ValueError(f"scene revision digest mismatch: {scene_id}")
        if content.get("detector_revision_id") != m2["m1_revision_id"]:
            raise ValueError(f"scene input does not match corrected M1 revision: {recording_id}")
        if content.get("detector_revision_digest") != m2["m1_revision_sha256"]:
            raise ValueError(
                f"scene input digest does not match corrected M1 revision: {recording_id}"
            )

        geometry_receipts = []
        scene_poses = 0
        crop_count = 0
        for frame in content["frames"]:
            frame_identity = frame.get("source_identity") or {}
            proposal = frame.get("proposal") or {}
            scene = proposal.get("initialized_scene")
            if not scene:
                zero_crop_frame_count += 1
                continue
            scene_poses += len(scene.get("poses", []))
            calibration = content["calibration"]
            projection = {
                "table_to_image_homography": calibration["table_to_image"],
                "card_short_size": calibration["card_short_size"],
                "card_long_size": calibration["card_long_size"],
            }
            derived = derive_pose_scene_visible_regions(scene, projection)
            geometry_receipts.append(
                {
                    "frame_id": frame["frame_id"],
                    "source_frame_digest": frame.get("source_frame_digest"),
                    "frame_identity": frame_identity,
                    "receipt": derived.receipt.to_mapping(),
                    "region_digests": derived.receipt.region_digests,
                    "hidden_card_ids": list(derived.hidden_card_ids),
                }
            )
            crop_count += len(derived.regions)
            usable_geometry_count += len(derived.regions)
            unusable_geometry_count += len(derived.hidden_card_ids)

        total_scene_frames += len(content["frames"])
        is_training_overlap = source_group_id in training_groups
        if is_training_overlap:
            training_overlap_crop_count += crop_count
        else:
            non_training_crop_count += crop_count

        identity_state = store_root / "data/operations/pipeline-references" / recording_id
        selection_path = (
            store_root
            / "data/operations/pipeline/selections"
            / recording_id
            / "visual_identities.json"
        )
        pointers = {}
        for name, path in (
            ("identity_state", identity_state / "visual_identities/state.json"),
            ("identity_draft", identity_state / "visual_identities/draft.json"),
            ("identity_selection", selection_path),
        ):
            pointer = read_json(path) if path.is_file() else {}
            pointers[name] = {
                "path": str(path.relative_to(store_root)),
                "sha256": sha256(path) if path.is_file() else None,
                "present": path.is_file(),
                "selected_completed_revision_id": pointer.get(
                    "selected_completed_reference_revision_id",
                    pointer.get("selected_completed_revision_id"),
                ),
                "selected_generated_revision_id": pointer.get("selected_generated_revision_id"),
                "draft_state": pointer.get("draft_state"),
                "draft_revision": pointer.get("draft_revision"),
            }
        selected_identity_reference = (
            pointers["identity_selection"]["selected_completed_revision_id"]
            or pointers["identity_state"]["selected_completed_revision_id"]
        )

        item = {
            "recording_id": recording_id,
            "source_asset_id": preflight.get("source_asset_id"),
            "source_group_id": source_group_id,
            "source_permission": preflight.get("source_permission"),
            "allowed_uses": preflight.get("allowed_uses", []),
            "source_video_sha256": preflight.get("video_sha256"),
            "scene_run_id": m2["m2_run_id"],
            "planned_identity_run_id": (
                "visual_identities-run-"
                + str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"doko-detector:0098:M1:{EXPECTED_BUNDLE}:{recording_id}",
                    )
                )
            ),
            "scene_revision_id": scene_id,
            "scene_revision_sha256": m2["scene_revision_sha256"],
            "m1_revision_id": m2["m1_revision_id"],
            "m1_revision_sha256": m2["m1_revision_sha256"],
            "calibration_revision_id": m2["calibration_revision_id"],
            "calibration_digest": m2["calibration_digest"],
            "frame_count": len(content["frames"]),
            "pose_count": scene_poses,
            "usable_crop_geometry_count": crop_count,
            "unusable_crop_geometry_count": sum(
                len(entry["hidden_card_ids"]) for entry in geometry_receipts
            ),
            "protected_source_group": protected,
            "m6_training_overlap": is_training_overlap,
            "source_group_quality_comparison_eligible": not is_training_overlap,
            "selected_identity_reference_revision_id": selected_identity_reference,
            "disposition": "included",
            "identity_selection_state_before_batch": pointers,
            "crop_geometry_receipts": geometry_receipts if not protected else [],
        }
        frozen_recordings.append(item)

    if len(frozen_recordings) + len(excluded_recordings) != 29 or len(failed_recordings) != 5:
        raise ValueError(
            "the frozen manifest must account for 29 successful scenes and five failures"
        )
    if len(frozen_recordings) > 29:
        raise ValueError("identity execution scope exceeds the 0098 recording cap")

    source_hashes = {
        path.name: sha256(path)
        for path in (SCENE_REPORT, PREFLIGHT_REPORT, IDENTITY_REPORT, PIN_REPORT, M1_REPORT)
    }
    return {
        "schema_version": "identity-proposal-batch-preflight/v1",
        "epic": "0098",
        "milestone": "M0",
        "status": "frozen",
        "created_on": "2026-10-17",
        "classifier_runs": 0,
        "deviations": [
            {
                "stage": "initial exploratory audit",
                "detail": (
                    "Before protected groups were identified, an exploratory count read stored "
                    "scene geometry for all 29 successful 0096 outputs, including the three "
                    "now excluded. No source image pixels or identity classifier outputs were read."
                ),
                "m1_disposition": "exclude the three protected source groups",
            }
        ],
        "source_report_sha256": source_hashes,
        "software": {
            "python": platform.python_version(),
            "preflight_script_sha256": sha256(Path(__file__).resolve()),
        },
        "upstream": {
            "successful_scene_recordings": 29,
            "scene_failures": 4,
            "m1_dependency_failures": 1,
            "scene_frames": scene_report["summary"]["completed_scene_frames"],
            "included_scene_frames": total_scene_frames,
            "corrected_detector_runs": m1_summary["corrective_run_ids"],
            "m2_output_manifest": "0096-M2_Proposed_Scene_Results.json",
        },
        "model": {
            "decision": "0088 M15 M6 seed 17",
            "bundle_sha256": EXPECTED_BUNDLE,
            "checkpoint_sha256": EXPECTED_CHECKPOINT,
            "temperature": EXPECTED_TEMPERATURE,
            "bundle_manifest_sha256": sha256(model_manifest_path),
            "target_map_sha256": model_manifest["target_map_sha256"],
            "target_class_count": model_manifest["head"]["class_count"],
            "verified_files": checked_model_files,
            "quality_state": "unqualified; every result requires human review",
            "prohibited_alternatives": ["M3", "Gemini"],
        },
        "crop_recipe": {
            "policy": "predicted_visible_region",
            "geometry_recipe": "card-plane-derived-regions/v2",
            "geometry_source_sha256": sha256(geometry_source),
            "crop_source_sha256": sha256(crop_source),
            "encoding": "P6 PPM",
            "model_input": (
                "224-pixel RGB; aspect-preserving Lanczos; centered (128,128,128) letterbox"
            ),
            "geometry_counts_are_not_pixel_crop_success_claims": True,
        },
        "budgets": {
            "maximum_recordings": 29,
            "maximum_source_frames": 1513,
            "maximum_parallel_runs": 1,
            "cloud_requests": 0,
            "active_processing_seconds": 28800,
            "process_rss_bytes": 34359738368,
            "rss_sample_interval_seconds": 10,
            "crop_cap": sum(item["usable_crop_geometry_count"] for item in frozen_recordings),
        },
        "coverage": {
            "included_recordings": len(frozen_recordings),
            "excluded_protected_recordings": len(excluded_recordings),
            "upstream_failed_recordings": len(failed_recordings),
            "eligible_source_frames": sum(item["frame_count"] for item in frozen_recordings),
            "usable_crop_geometry_count": usable_geometry_count,
            "unusable_crop_geometry_count": unusable_geometry_count,
            "frozen_crop_cap": sum(
                item["usable_crop_geometry_count"] for item in frozen_recordings
            ),
            "m6_training_overlap_crop_count": training_overlap_crop_count,
            "non_training_crop_count": non_training_crop_count,
            "zero_crop_frame_count": zero_crop_frame_count,
        },
        "protected_source_group_ids": sorted(protected_groups),
        "m6_training_source_group_ids": sorted(training_groups),
        "recordings": frozen_recordings,
        "excluded_recordings": excluded_recordings,
        "upstream_failures": failed_recordings,
    }


def write_report(manifest: dict[str, Any]) -> None:
    OUTPUT_JSON.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    coverage = manifest["coverage"]
    lines = [
        "# Epic 0098 M0 frozen inputs",
        "",
        "M0 checked the primary pipeline store, source permissions, protected groups, M6 files,",
        "scene lineage, crop geometry, and existing identity selections. It did not run a",
        "classifier.",
        "",
        "## Frozen scope",
        "",
        f"- Included recordings: {coverage['included_recordings']}",
        f"- Excluded protected recordings: {coverage['excluded_protected_recordings']}",
        f"- Upstream failures: {coverage['upstream_failed_recordings']}",
        f"- Included source frames: {coverage['eligible_source_frames']}",
        f"- Crop geometry candidates: {coverage['frozen_crop_cap']}",
        f"- Crop geometry with no visible pixels: {coverage['unusable_crop_geometry_count']}",
        f"- M6 training-overlap crop candidates: {coverage['m6_training_overlap_crop_count']}",
        "",
        "The crop counts describe deterministic visible-region geometry. M1 must still account for",
        "each materialized crop as classified, face-down, unusable, failed, or unprocessed.",
        "The three protected recording groups are excluded before identity inference. M6 training",
        "overlap can supply review proposals but cannot supply quality comparison pairs.",
        "",
        "## Deviation",
        "",
        "An initial exploratory count read stored scene geometry for all 29 successful 0096",
        "outputs before the protected groups were identified. This included the three now",
        "excluded recordings. No source image pixels or identity classifier outputs were read.",
        "The three recordings have",
        "no crop geometry receipts in this manifest and remain excluded from M1.",
        "",
        "## Pins",
        "",
        f"- M6 bundle: `{manifest['model']['bundle_sha256']}`",
        f"- M6 checkpoint: `{manifest['model']['checkpoint_sha256']}`",
        f"- Temperature: `{manifest['model']['temperature']}`",
        "- Crop: `predicted_visible_region`, RGB P6 PPM, 224-pixel Lanczos letterbox.",
        "",
        "## Reproduction",
        "",
        "Run from the repository root. The primary pipeline store and ignored M6 bundle remain in",
        "the `main` worktree, so pass that path explicitly:",
        "",
        "```sh",
        "mise exec -- uv run --project operations python \\",
        "  operations/scripts/build_0098_m0_preflight.py \\",
        "  --store-root /Users/niklas.sparfeld/Developer/doko_detector \\",
        (
            "  --model-bundle /Users/niklas.sparfeld/Developer/doko_detector/"
            ".runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle"
        ),
        "```",
        "",
        "The manifest stores each included frame and card geometry receipt, source digest, scene,",
        "detector revision, calibration digest, and identity selection pointer state. No upstream",
        "data or selection pointer was changed.",
        "",
        "See [the machine-readable manifest](0098-M0_Frozen_Inputs.json).",
    ]
    OUTPUT_MD.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--model-bundle", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_manifest(args.store_root.resolve(), args.model_bundle.resolve())
    write_report(manifest)
    print(json.dumps(manifest["coverage"], sort_keys=True))


if __name__ == "__main__":
    main()
