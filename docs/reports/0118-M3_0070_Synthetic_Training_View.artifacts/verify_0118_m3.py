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
        "generated_files": checked_files,
        "source_videos": source_videos,
        "train_coco_sha256": sha256_file(train_coco),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--restored-view", type=Path, required=True)
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

    print(
        json.dumps(
            {
                "training_view_manifest_digest": training_manifest["manifest_digest"],
                "m0_digest": m0["manifest_digest"],
                "m1_digest": m1["manifest_digest"],
                "m2_digest": m2["manifest_digest"],
                "m1_source_and_review_files_checked": review_files,
                "m2_scene_receipts_and_images_checked": receipt_count,
                "real_materialization_digest": real_materialization["manifest"][
                    "materialization_digest"
                ],
                "real_generated_files_checked": real_materialization["generated_files"],
                "real_source_videos_checked": real_materialization["source_videos"],
                "real_train_coco_sha256": real_materialization["train_coco_sha256"],
                "comparison_manifest_digest": comparison_digest,
                "run_ids": run_ids,
                "bundle_files_checked": bundle_files_checked,
                "restored_train_coco_sha256": loaded["identity"]["train_coco_sha256"],
                "restored_synthetic_rows": len(loaded["rows"]),
                "restored_files_checked": restored_files,
                "restored_logical_bytes_checked": restored_bytes,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
