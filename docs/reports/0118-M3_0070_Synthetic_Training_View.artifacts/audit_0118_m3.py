from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from doko_operations.reviewed_rfdetr_detector_campaign import canonical_json_bytes
from doko_operations.rfdetr_cluster_crop_materialization import _load_synthetic_input
from doko_operations.synthetic_visible_region_training_view import (
    validate_synthetic_visible_region_training_view,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def verify_manifest_file(repository: Path, ref: dict[str, Any]) -> dict[str, Any]:
    path = repository / ref["path"]
    value = read_json(path)
    actual_file_sha = sha256_file(path)
    if actual_file_sha != ref["file_sha256"]:
        raise ValueError(f"manifest file SHA-256 mismatch: {path}")
    core = {key: item for key, item in value.items() if key != "manifest_digest"}
    actual_digest = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    if (
        actual_digest != ref["manifest_digest"]
        or value.get("manifest_digest") != actual_digest
    ):
        raise ValueError(f"manifest digest mismatch: {path}")
    return value


def verify_input_files(repository: Path, manifest: dict[str, Any]) -> int:
    checked = 0
    for item in manifest.get("sources", []):
        if item.get("reviewed_decision", {}).get("status") != "accepted":
            raise ValueError(
                f"source lacks accepted review: {item.get('source_asset_id')}"
            )
        path = repository / item["path"]
        if sha256_file(path) != item["source_file_sha256"]:
            raise ValueError(f"source file digest mismatch: {path}")
        checked += 1
    for item in [*manifest.get("backgrounds", []), *manifest.get("cutouts", [])]:
        if item.get("reviewed_decision", {}).get("status") != "accepted":
            raise ValueError(
                f"review input is not accepted: {item.get('background_id', item.get('cutout_id'))}"
            )
        for file_ref in item.get("files", {}).values():
            path = repository / file_ref["path"]
            if sha256_file(path) != file_ref["sha256"]:
                raise ValueError(f"review input digest mismatch: {path}")
            checked += 1
    return checked


def verify_restored_copy(source: Path, restored: Path) -> tuple[int, int]:
    source_files = {
        path.relative_to(source).as_posix(): path
        for path in source.rglob("*")
        if path.is_file()
    }
    restored_files = {
        path.relative_to(restored).as_posix(): path
        for path in restored.rglob("*")
        if path.is_file()
    }
    if source_files.keys() != restored_files.keys():
        raise ValueError("restored view file inventory differs from the source")
    total_bytes = 0
    for relative, source_path in source_files.items():
        restored_path = restored_files[relative]
        if source_path.stat().st_size != restored_path.stat().st_size:
            raise ValueError(f"restored file size differs: {relative}")
        if sha256_file(source_path) != sha256_file(restored_path):
            raise ValueError(f"restored file digest differs: {relative}")
        total_bytes += source_path.stat().st_size
    return len(source_files), total_bytes


def verify_m2_receipts(repository: Path, manifest: dict[str, Any]) -> int:
    scenes = manifest.get("scenes", [])
    calibration_digests = {
        item["calibration_digest"] for item in manifest.get("calibrations", [])
    }
    if len(calibration_digests) != len(manifest.get("calibrations", [])):
        raise ValueError("M2 calibration digest is duplicated")
    for scene in scenes:
        path = repository / scene["receipt_path"]
        receipt = read_json(path)
        core = {key: item for key, item in receipt.items() if key != "receipt_digest"}
        actual_digest = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
        if actual_digest != scene["receipt_digest"]:
            raise ValueError(f"scene receipt reference mismatch: {path}")
        if receipt.get("receipt_digest") != actual_digest:
            raise ValueError(f"scene receipt self-digest mismatch: {path}")
        if receipt.get("scene_id") != scene.get("scene_id"):
            raise ValueError(f"scene receipt identity mismatch: {path}")
        calibration_digest = scene.get("table_calibration_digest")
        if calibration_digest not in calibration_digests:
            raise ValueError(
                f"scene points to an unknown calibration: {scene['scene_id']}"
            )
        if (
            receipt.get("table_calibration", {}).get("calibration_digest")
            != calibration_digest
        ):
            raise ValueError(f"receipt calibration link mismatch: {scene['scene_id']}")
        if (
            scene.get("background", {}).get("reviewed_decision", {}).get("status")
            != "accepted"
        ):
            raise ValueError(
                f"scene background lacks accepted review: {scene['scene_id']}"
            )
        image = repository / scene["image_path"]
        if sha256_file(image) != scene["image_sha256"]:
            raise ValueError(f"scene image digest mismatch: {image}")
    return len(scenes)


def audit_campaign_review_references(
    repository: Path, campaign_manifest: dict[str, Any]
) -> dict[str, Any]:
    archive_root = repository / (
        "data/operations-recovery/0108-m10-20261105/"
        "migration-stage-accepted-loss/evidence/operations"
    )
    records = []
    for reference in campaign_manifest["references"]:
        reference_root = archive_root / Path(
            *Path(reference["reference_path"]).parts[2:]
        )
        revision_manifest_path = archive_root / Path(
            *Path(reference["reference_revision_manifest_path"]).parts[2:]
        )
        content_path = revision_manifest_path.parent / "content.json"
        state_path = reference_root / "state.json"
        draft_path = reference_root / "draft.json"
        revision_manifest = read_json(revision_manifest_path)
        content = read_json(content_path)
        state = read_json(state_path)
        draft = read_json(draft_path)
        values = {
            "revision_manifest_sha256": sha256_file(revision_manifest_path),
            "content_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
            "state_sha256": hashlib.sha256(canonical_json_bytes(state)).hexdigest(),
            "draft_sha256": hashlib.sha256(canonical_json_bytes(draft)).hexdigest(),
        }
        expected = {
            "revision_manifest_sha256": reference["reference_revision_manifest_sha256"],
            "content_sha256": reference["reference_content_sha256"],
            "state_sha256": reference["reference_state_sha256"],
            "draft_sha256": reference["reference_draft_sha256"],
        }
        records.append(
            {
                "recording_id": reference["recording_id"],
                "reference_revision_id": reference["reference_revision_id"],
                "reference_root": reference_root.relative_to(repository).as_posix(),
                "revision_manifest_path": revision_manifest_path.relative_to(
                    repository
                ).as_posix(),
                "content_path": content_path.relative_to(repository).as_posix(),
                "expected": expected,
                "observed": values,
                "matches": {key: values[key] == expected[key] for key in expected},
                "revision_manifest_identity_matches": (
                    revision_manifest.get("revision_id")
                    == reference["reference_revision_id"]
                    and revision_manifest.get("recording_id")
                    == reference["recording_id"]
                ),
            }
        )
    checks = tuple(records[0]["matches"])
    counts = {key: sum(record["matches"][key] for record in records) for key in checks}
    return {
        "archive_root": archive_root.relative_to(repository).as_posix(),
        "reference_count": len(records),
        "counts_matching": counts,
        "revision_manifest_identity_matches": sum(
            record["revision_manifest_identity_matches"] for record in records
        ),
        "records": records,
    }


def verify_real_materialization(
    repository: Path, reference: dict[str, Any]
) -> dict[str, Any]:
    root = repository / reference["path"]
    path = root / "materialization.json"
    manifest = read_json(path)
    core = {
        key: value for key, value in manifest.items() if key != "materialization_digest"
    }
    actual_digest = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    if actual_digest != reference["materialization_digest"]:
        raise ValueError("0068 materialization digest mismatch")
    campaign_ref = manifest["campaign_manifest"]
    campaign_manifest = verify_manifest_file(repository, campaign_ref)
    if campaign_manifest.get("manifest_digest") != campaign_ref["manifest_digest"]:
        raise ValueError("0068 source campaign manifest mismatch")
    checked_files = 0
    for item in manifest["generated_files"]:
        generated_path = root / item["path"]
        if sha256_file(generated_path) != item["sha256"]:
            raise ValueError(
                f"0068 materialized file digest mismatch: {generated_path}"
            )
        checked_files += 1
    train_coco = root / "train/_annotations.coco.json"
    if sha256_file(train_coco) != reference["train_coco_sha256"]:
        raise ValueError("0068 real train COCO digest mismatch")
    source_videos = 0
    for source in manifest["inputs"]:
        source_path = repository / source["path"]
        if source_path.stat().st_size != source["byte_length"]:
            raise ValueError(f"0068 source video byte length mismatch: {source_path}")
        if sha256_file(source_path) != source["sha256"]:
            raise ValueError(f"0068 source video digest mismatch: {source_path}")
        source_videos += 1
    return {
        "manifest": manifest,
        "campaign_manifest": campaign_manifest,
        "generated_files": checked_files,
        "source_videos": source_videos,
        "train_coco_sha256": sha256_file(train_coco),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--restored-view", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    repository = args.repository.expanduser().resolve()
    restored_view = args.restored_view.expanduser().resolve()
    source_view = repository / ".runtime/synthetic-visible-region-0070-m5-50-50-view"
    restored_files, restored_bytes = verify_restored_copy(source_view, restored_view)

    training_manifest_path = (
        repository
        / "data/operations/synthetic-visible-region-0070-m5-50-50-training-view.json"
    )
    training_manifest = read_json(training_manifest_path)
    validate_synthetic_visible_region_training_view(training_manifest)
    inputs = training_manifest["inputs"]
    m0 = verify_manifest_file(repository, inputs["m0"])
    m1 = verify_manifest_file(repository, inputs["m1"])
    m2 = verify_manifest_file(repository, inputs["m2"])
    review_files = verify_input_files(repository, m1)
    receipt_count = verify_m2_receipts(repository, m2)

    real_materialization = verify_real_materialization(
        repository, inputs["real_materialization"]
    )
    review_reference_audit = audit_campaign_review_references(
        repository, real_materialization["campaign_manifest"]
    )

    comparison_path = (
        repository
        / "data/operations/synthetic-visible-region-0070-m4-50-50-training-comparison.json"
    )
    comparison = read_json(comparison_path)
    comparison_core = {
        key: value for key, value in comparison.items() if key != "manifest_digest"
    }
    comparison_digest = hashlib.sha256(
        canonical_json_bytes(comparison_core)
    ).hexdigest()
    if comparison.get("manifest_digest") != comparison_digest:
        raise ValueError("0070 comparison manifest digest mismatch")
    run_ids: dict[str, str] = {}
    bundle_files_checked = 0
    for name, run in comparison["runs"].items():
        if run.get("status") != "completed":
            raise ValueError(f"0070 {name} run is not complete")
        bundle = run["bundle"]
        bundle_manifest_path = Path(bundle["path"]) / "manifest.json"
        bundle_manifest = read_json(bundle_manifest_path)
        if sha256_file(bundle_manifest_path) != bundle["manifest_sha256"]:
            raise ValueError(f"0070 {name} bundle manifest file digest mismatch")
        if bundle_manifest.get("bundle_digest") != bundle["bundle_digest"]:
            raise ValueError(f"0070 {name} bundle digest mismatch")
        for relative, expected_sha in bundle_manifest.get("files", {}).items():
            model_file = bundle_manifest_path.parent / relative
            if sha256_file(model_file) != expected_sha:
                raise ValueError(
                    f"0070 {name} model file digest mismatch: {model_file}"
                )
            bundle_files_checked += 1
        run_ids[name] = run["run_id"]

    loaded = _load_synthetic_input(
        repository,
        synthetic_view_root=restored_view,
        synthetic_manifest_path=training_manifest_path,
        include_synthetic=True,
    )
    if (
        loaded["identity"]["manifest"]["manifest_digest"]
        != training_manifest["manifest_digest"]
    ):
        raise ValueError("restored view points to a different training-view manifest")
    if len(loaded["rows"]) != 537:
        raise ValueError(f"expected 537 synthetic rows, received {len(loaded['rows'])}")

    result = {
        "training_view_manifest_digest": training_manifest["manifest_digest"],
        "m0_digest": m0["manifest_digest"],
        "m1_digest": m1["manifest_digest"],
        "m2_digest": m2["manifest_digest"],
        "m1_source_and_review_files_checked": review_files,
        "m2_scene_receipts_and_images_checked": receipt_count,
        "m2_calibration_references_checked": len(m2["calibrations"]),
        "m2_calibration_linked_scenes_checked": receipt_count,
        "real_materialization_digest": real_materialization["manifest"][
            "materialization_digest"
        ],
        "real_generated_files_checked": real_materialization["generated_files"],
        "real_source_videos_checked": real_materialization["source_videos"],
        "review_reference_audit": review_reference_audit,
        "real_train_coco_sha256": real_materialization["train_coco_sha256"],
        "comparison_manifest_digest": comparison_digest,
        "run_ids": run_ids,
        "bundle_files_checked": bundle_files_checked,
        "restored_train_coco_sha256": loaded["identity"]["train_coco_sha256"],
        "restored_synthetic_rows": len(loaded["rows"]),
        "restored_files_checked": restored_files,
        "restored_logical_bytes_checked": restored_bytes,
    }
    if args.evidence:
        evidence_path = args.evidence.expanduser()
        if not evidence_path.is_absolute():
            evidence_path = repository / evidence_path
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(review_reference_audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result["review_reference_evidence_path"] = evidence_path.as_posix()
    result["review_reference_audit"] = {
        "reference_count": review_reference_audit["reference_count"],
        "counts_matching": review_reference_audit["counts_matching"],
        "revision_manifest_identity_matches": review_reference_audit[
            "revision_manifest_identity_matches"
        ],
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
