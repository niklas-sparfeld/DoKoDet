#!/usr/bin/env python3
"""Build the frozen 0088 M1 reviewed and automatic development views."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "operations/src"), str(ROOT / "table_evidence_analyzer/src")]

from table_evidence_analyzer.data import (  # noqa: E402
    TARGET_SCHEMA,
    ArtifactIndex,
    ArtifactRecord,
    CropArtifact,
    CropCache,
    DatasetEntry,
    DatasetManifest,
    Eligibility,
    SplitManifest,
)
from table_evidence_analyzer.local_identity import (  # noqa: E402
    MaterializedDinoV3Weights,
    build_dinov3_identity_config,
)
from table_evidence_analyzer.visible_card_evaluation import polygon_iou  # noqa: E402
from table_evidence_analyzer.visible_cards import (  # noqa: E402
    LocalVisibleCardSegmentationProvider,
    NormalizedPoint,
    VisibleCardRequest,
)

from doko_operations.derived_view import (  # noqa: E402
    DEFAULT_TRANSFORM_VERSION,
    ExactEventRequest,
    FFmpegFrameResolver,
    PredictedVisibleRegionGeometry,
    resolve_visible_region_crop,
)
from doko_operations.pipeline_data import RecordingVideoSource  # noqa: E402
from doko_operations.visual_identity_materialization import (  # noqa: E402
    materialize_reviewed_visual_identity_crops,
)

RUN = ROOT / ".runtime/dinov3-identity-0088"
HANDOFF = ROOT / "docs/reports/0086-M5_DINO_Campaign_Handoff.json"
M0 = ROOT / "docs/reports/0088-M0_Campaign_Readiness.json"
SOURCE_RECEIPT = ROOT / "docs/reports/0088-M1_Source_Verification.json"
PROVIDER_BUNDLE = ROOT / ".runtime/rfdetr-segmentation-0087-m3-training/bundle"
PROVIDER_DECISION = ROOT / "docs/reports/0087-M5_Pretest_Decision.json"
PROVIDER_SHA256 = "018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9"
TRANSFORM = DEFAULT_TRANSFORM_VERSION


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def selected_revision(recording_id: str, kind: str, expected: dict[str, Any]) -> dict[str, Any]:
    state_path = ROOT / "data/operations/pipeline-references" / recording_id / kind / "state.json"
    state = read(state_path)
    revision_id = state.get("selected_completed_revision_id")
    if revision_id != expected["revision_id"]:
        raise ValueError(f"{recording_id} {kind} selected revision changed")
    revision_root = ROOT / "data/operations/pipeline/revisions" / revision_id
    content = read(revision_root / "content.json")
    manifest = read(revision_root / "manifest.json")
    if manifest.get("recording_id") != recording_id:
        raise ValueError(f"{recording_id} {kind} revision belongs to another recording")
    if digest(canonical(content)) != expected["content_sha256"]:
        raise ValueError(f"{recording_id} {kind} content digest changed")
    if digest(canonical(manifest)) != expected["manifest_sha256"]:
        raise ValueError(f"{recording_id} {kind} manifest digest changed")
    if digest((state_path).read_bytes()) != expected["state_sha256"]:
        raise ValueError(f"{recording_id} {kind} state digest changed")
    return {
        "revision_id": revision_id,
        "content_digest": digest(canonical(content)),
        "content": content,
        "manifest": manifest,
    }


def source_for(
    recording_id: str, expected_sha: str, frozen_source: dict[str, Any]
) -> tuple[RecordingVideoSource, Path, dict[str, Any]]:
    intake = ROOT / "data/intake/recordings" / recording_id
    manifest = read(intake / "manifest.json")
    record = read(intake / "source-record.json")
    video = manifest["files"]["video"]
    video_path = (intake / video["relative_path"]).resolve()
    if not video_path.is_relative_to(intake.resolve()):
        raise ValueError(f"{recording_id} video path escapes its intake bundle")
    if (
        video["sha256"] != expected_sha
        or record["sha256"] != expected_sha
        or frozen_source.get("video_sha256") != expected_sha
        or frozen_source.get("relative_path") != video_path.relative_to(ROOT).as_posix()
    ):
        raise ValueError(f"{recording_id} intake source digest differs from frozen handoff")
    if video_path.stat().st_size != video["byte_length"] or digest_file(video_path) != expected_sha:
        raise ValueError(f"{recording_id} source bytes differ from frozen handoff")
    source_mapping = {
        "schema_version": "recording-video/v1",
        "recording_id": recording_id,
        "relative_path": frozen_source["relative_path"],
        "video_sha256": expected_sha,
        "byte_length": video_path.stat().st_size,
        "duration_us": frozen_source["duration_us"],
    }
    return RecordingVideoSource.from_mapping(source_mapping), video_path, record


def build_inputs(partitions: dict[str, list[dict[str, Any]]], handoff: dict[str, Any]):
    chosen = {
        item["recording_id"]: part
        for part, values in partitions.items()
        if part in {"training", "model_selection", "confidence_calibration"}
        for item in values
    }
    handoff_by_id = {row["recording_id"]: row for row in handoff["recordings"]}
    inputs, details, sources, frames = [], {}, {}, {}
    unavailable = {}
    resolver = FFmpegFrameResolver()
    for recording_id, partition in sorted(chosen.items()):
        row = handoff_by_id[recording_id]
        if not row["visual_identity_revision"].get("revision_id"):
            unavailable[recording_id] = "no_completed_visual_identity_revision"
            continue
        visible = selected_revision(recording_id, "visible_cards", row["visible_card_revision"])
        identity = selected_revision(
            recording_id, "visual_identities", row["visual_identity_revision"]
        )
        frozen_source = identity["manifest"].get("source")
        if not isinstance(frozen_source, dict):
            raise ValueError(f"{recording_id} identity revision has no frozen source")
        source, video_path, source_record = source_for(
            recording_id, row["source_group"]["source_sha256"], frozen_source
        )
        if identity["manifest"].get("source", {}).get("video_sha256") != source.video_sha256:
            raise ValueError(f"{recording_id} identity revision names a different source")
        group = dict(row["source_group"])
        inputs.append(
            {
                "recording_id": recording_id,
                "source_lineage_group": group,
                "source": source.to_mapping(),
                "visible_card_revision": visible,
                "visual_identity_revision": identity,
            }
        )
        details[recording_id] = {
            "partition": partition,
            "visible": visible,
            "identity": identity,
            "group": group,
            "source_record": source_record,
        }
        sources[recording_id] = (source, video_path)

    def resolve(frame_identity: dict[str, Any]):
        source_match = next(
            (source, path)
            for source, path in sources.values()
            if source.video_sha256 == frame_identity["source_video_sha256"]
        )
        source, video_path = source_match
        key = digest(canonical(frame_identity))
        if key not in frames:
            resolved = resolver.resolve(
                ExactEventRequest(
                    source,
                    frame_identity["requested_time_us"],
                    frame_identity["output_encoding"],
                ),
                video_path,
            )
            if resolved.identity_mapping() != frame_identity:
                raise ValueError("resolved frame identity differs from reviewed reference")
            frames[key] = resolved
        return frames[key]

    return inputs, details, resolve, frames, unavailable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--provider-bundle", type=Path, default=PROVIDER_BUNDLE)
    parser.add_argument("--run-dir", type=Path, default=RUN)
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    provider_bundle = args.provider_bundle.expanduser().resolve()
    if not provider_bundle.is_dir():
        raise ValueError(f"frozen provider bundle is missing: {provider_bundle}")
    provider_manifest = read(provider_bundle / "manifest.json")
    if provider_manifest.get("bundle_digest") != PROVIDER_SHA256:
        raise ValueError("RF-DETR provider bundle digest differs from the frozen M0 provider")
    checkpoint = provider_bundle / provider_manifest["checkpoint_file"]
    if digest(checkpoint.read_bytes()) != provider_manifest["checkpoint_sha256"]:
        raise ValueError("RF-DETR checkpoint digest differs from its bundle manifest")
    m0, handoff, receipt = read(M0), read(HANDOFF), read(SOURCE_RECEIPT)
    if receipt["failed_recordings"] or receipt["verified_recording_count"] != 20:
        raise ValueError("M1 exact-source verification is incomplete")
    if m0.get("authorized_work", {}).get("crop_materialization") is not True:
        raise ValueError("M0 does not authorize crop materialization")
    provider_decision = read(PROVIDER_DECISION)
    if provider_decision.get("candidate_decision") != "eligible_for_conditional_selection":
        raise ValueError("0087 M5 did not mark the local candidate eligible")
    if provider_manifest.get("bundle_digest") != provider_decision.get("candidate_bundle_digest"):
        raise ValueError("0087 provider bundle does not match its sealed decision")
    partitions = m0["frozen_partitions"]
    inputs, details, resolve, frames, unavailable = build_inputs(partitions, handoff)

    reviewed_root = run_dir / "reviewed-cold"
    warm_root = run_dir / "reviewed-warm"
    shutil.rmtree(reviewed_root, ignore_errors=True)
    shutil.rmtree(warm_root, ignore_errors=True)
    reviewed = materialize_reviewed_visual_identity_crops(inputs, reviewed_root, resolve)
    warm = materialize_reviewed_visual_identity_crops(inputs, warm_root, resolve)
    if reviewed["manifest_digest"] != warm["manifest_digest"]:
        raise ValueError("cold and warm reviewed crop digests differ")
    for item in reviewed["samples"]:
        cold = (reviewed_root / item["crop_path"]).read_bytes()
        warm_bytes = (warm_root / item["crop_path"]).read_bytes()
        if digest(cold) != digest(warm_bytes) or digest(cold) != item["crop_sha256"]:
            raise ValueError(f"cold and warm crop bytes differ: {item['sample_id']}")
    shutil.rmtree(warm_root)

    partition_by_recording = {
        item["recording_id"]: part for part, values in partitions.items() for item in values
    }
    samples = reviewed["samples"]
    target_classes = set(m0["source_pool"]["target_classes"])
    non_campaign_samples = [sample for sample in samples if sample["target"] not in target_classes]
    train_samples = [
        s
        for s in samples
        if partition_by_recording[s["recording_id"]] == "training" and s["target"] in target_classes
    ]
    val_samples = [
        s
        for s in samples
        if partition_by_recording[s["recording_id"]] == "model_selection"
        and s["target"] in target_classes
    ]
    cal_samples = [
        s
        for s in samples
        if partition_by_recording[s["recording_id"]] == "confidence_calibration"
        and s["target"] in target_classes
    ]
    # M1 training data contains only frozen training and model-selection groups.
    dataset_samples = train_samples + val_samples
    data_root = run_dir / "data"
    frames_root = data_root / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    frame_records, entries, crop_records = {}, [], []
    for sample in dataset_samples:
        group = details[sample["recording_id"]]["group"]
        source_record = details[sample["recording_id"]]["source_record"]
        frame_identity = sample["frame_identity"]
        frame_key = digest(canonical(frame_identity))
        frame = frames[frame_key]
        frame_path = f"frames/{frame_key}.jpg"
        path = data_root / frame_path
        if not path.exists():
            path.write_bytes(frame.image_bytes)
        frame_records[frame_key] = ArtifactRecord(
            source_asset_id=source_record["source_asset_id"],
            source_frame_id=f"frame-{frame_key}",
            relative_path=frame_path,
            media_type=frame.content_type,
            byte_length=len(frame.image_bytes),
            sha256=frame.image_sha256,
        )
        crop_bytes = (reviewed_root / sample["crop_path"]).read_bytes()
        crop_name = f"crops/{digest(sample['sample_id'].encode())[:40]}.ppm"
        crop_path = data_root / crop_name
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        crop_path.write_bytes(crop_bytes)
        reviewed_card = next(
            candidate
            for outcome in details[sample["recording_id"]]["visible"]["content"]["outcomes"]
            if outcome.get("frame_identity") == frame_identity
            for candidate in outcome.get("candidates", [])
            if candidate.get("card_id") == sample["card_id"]
        )
        geometry = reviewed_card["geometry"]
        crop_view = resolve_visible_region_crop(
            frame, geometry, crop_policy="oracle_visible_region", output_encoding="ppm"
        )
        bounds = crop_view.pixel_bounds
        assert bounds is not None
        recording = details[sample["recording_id"]]
        source_mapping = inputs[[i["recording_id"] for i in inputs].index(sample["recording_id"])][
            "source"
        ]
        partition = "train" if sample in train_samples else "validation"
        revision_id = sample["visual_identity_revision_id"]
        item_id = sample["sample_id"]
        entries.append(
            DatasetEntry(
                dataset_item_id=item_id,
                source_asset_id=source_mapping["recording_id"].replace(
                    "cardeventnet-", "source-cardeventnet-"
                ),
                source_sha256=frame_identity["source_video_sha256"],
                annotation_set_id=revision_id,
                review_id=revision_id,
                eligibility=Eligibility(
                    source_asset_id=source_mapping["recording_id"].replace(
                        "cardeventnet-", "source-cardeventnet-"
                    ),
                    state="eligible",
                    source_permission=recording["source_record"]["source_permission"],
                    allowed_uses=tuple(sorted(recording["source_record"]["allowed_uses"])),
                    review_state="reviewed",
                    annotation_set_id=revision_id,
                    review_id=revision_id,
                    intended_use=partition,
                ),
                target_schema=TARGET_SCHEMA,
                group_keys=tuple(
                    sorted(
                        (name, group[name])
                        for name in ("session_id", "source_group_id", "table_setup")
                    )
                ),
                inclusion_reason="completed human visual identity review",
                transform_version=TRANSFORM,
                source_frame_id=f"frame-{frame_key}",
                observed_card_id=sample["card_id"],
                bbox=(bounds.x_min, bounds.y_min, bounds.x_max, bounds.y_max),
                visual_card_identity=sample["target"],
                quality_tags=("reviewed", f"crop_policy:{sample['crop_policy']}"),
            )
        )
        crop_records.append(
            {
                "dataset_item_id": item_id,
                "partition": partition,
                "path": crop_name,
                "sha256": digest(crop_bytes),
                "byte_length": len(crop_bytes),
            }
        )

    group_names = ("session_id", "source_group_id", "table_setup")
    core = DatasetManifest(
        dataset_version_id="dinov3-0088-pending",
        task="visual_identity",
        target_schema=TARGET_SCHEMA,
        entries=tuple(sorted(entries, key=lambda e: e.dataset_item_id)),
        allowed_use_filter=("train", "validation"),
        group_key_names=group_names,
        derived_artifact_transform_version=TRANSFORM,
        creation_code_revision="0088-m1",
        dirty_state=False,
        deck_design_version=None,
        card_set_version="doko-40-v1",
        created_at=None,
    )
    dataset = DatasetManifest(
        dataset_version_id=f"dinov3-0088-{core.digest[:24]}",
        task=core.task,
        target_schema=core.target_schema,
        entries=core.entries,
        allowed_use_filter=core.allowed_use_filter,
        group_key_names=core.group_key_names,
        derived_artifact_transform_version=core.derived_artifact_transform_version,
        creation_code_revision=core.creation_code_revision,
        dirty_state=False,
        deck_design_version=None,
        card_set_version="doko-40-v1",
        created_at=None,
    )
    train_ids = tuple(
        sorted(e.dataset_item_id for e in dataset.entries if e.eligibility.intended_use == "train")
    )
    validation_ids = tuple(
        sorted(
            e.dataset_item_id for e in dataset.entries if e.eligibility.intended_use == "validation"
        )
    )
    split_core = SplitManifest(
        "dinov3-0088-pending",
        dataset.dataset_version_id,
        dataset.digest,
        group_names,
        17088,
        train_ids,
        validation_ids,
        (),
        (),
    )
    split = SplitManifest(
        f"dinov3-0088-{split_core.digest[:24]}",
        split_core.dataset_version_id,
        split_core.dataset_version_digest,
        group_names,
        split_core.seed,
        train_ids,
        validation_ids,
        (),
        (),
    )
    split.validate_against(dataset)
    artifact_core = ArtifactIndex(
        "dinov3-0088-pending",
        dataset.dataset_version_id,
        dataset.digest,
        tuple(frame_records.values()),
    )
    artifacts = ArtifactIndex(
        f"dinov3-0088-{artifact_core.digest[:24]}",
        dataset.dataset_version_id,
        dataset.digest,
        artifact_core.artifacts,
    )
    write_json(
        data_root / "dataset.json",
        {
            "schema_version": "dataset-version/v1",
            "dataset_version_id": dataset.dataset_version_id,
            "task": dataset.task,
            "target_schema": dataset.target_schema,
            "entries": [e.to_mapping() for e in dataset.entries],
            "allowed_use_filter": list(dataset.allowed_use_filter),
            "group_key_names": list(dataset.group_key_names),
            "derived_artifact_transform_version": dataset.derived_artifact_transform_version,
            "creation_code_revision": dataset.creation_code_revision,
            "dirty_state": False,
            "deck_design_version": None,
            "card_set_version": dataset.card_set_version,
            "created_at": None,
            "dataset_version_digest": dataset.digest,
        },
    )
    write_json(data_root / "split.json", split.to_mapping())
    write_json(
        data_root / "artifact-index.json",
        {
            "schema_version": "sample-artifact-index/v1",
            "artifact_index_id": artifacts.artifact_index_id,
            "dataset_version_id": artifacts.dataset_version_id,
            "dataset_version_digest": artifacts.dataset_version_digest,
            "artifacts": [
                {
                    "source_asset_id": artifact.source_asset_id,
                    "source_frame_id": artifact.source_frame_id,
                    "relative_path": artifact.relative_path,
                    "media_type": artifact.media_type,
                    "byte_length": artifact.byte_length,
                    "sha256": artifact.sha256,
                }
                for artifact in artifacts.artifacts
            ],
            "artifact_index_digest": artifacts.digest,
        },
    )

    # Freeze the exact reviewed PPM bytes in the cache consumed by the DINO trainer. The
    # trainer must not reconstruct them from rectangular frame bounds.
    cache_root = run_dir / "crop-cache"
    crop_cache_rows = []
    partition_by_item = {
        item: part
        for part, ids in (
            ("train", train_ids),
            ("validation", validation_ids),
        )
        for item in ids
    }
    entry_by_id = {entry.dataset_item_id: entry for entry in entries}
    sample_by_id = {sample["sample_id"]: sample for sample in dataset_samples}
    for item_id in sorted(entry_by_id):
        entry = entry_by_id[item_id]
        sample = sample_by_id[item_id]
        crop_bytes = (reviewed_root / sample["crop_path"]).read_bytes()
        relative_path = f"crops/{digest(item_id.encode())}.ppm"
        crop_path = cache_root / relative_path
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        crop_path.write_bytes(crop_bytes)
        crop_cache_rows.append(
            CropArtifact(
                dataset_item_id=item_id,
                source_asset_id=entry.source_asset_id,
                source_frame_id=entry.source_frame_id or "",
                source_frame_sha256=frame_records[
                    digest(canonical(sample["frame_identity"]))
                ].sha256,
                annotation_set_id=entry.annotation_set_id,
                review_id=entry.review_id,
                observed_card_id=entry.observed_card_id or "",
                visual_card_identity=entry.visual_card_identity or "",
                bbox=entry.bbox or (0, 0, 0, 0),
                transform_version=entry.transform_version,
                relative_path=relative_path,
                byte_length=len(crop_bytes),
                sha256=digest(crop_bytes),
                partition=partition_by_item[item_id],
            )
        )
    crop_cache = CropCache(
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        split_version_id=split.split_version_id,
        split_version_digest=split.digest,
        transform_version=dataset.derived_artifact_transform_version,
        crops=tuple(crop_cache_rows),
        root=cache_root,
    )
    crop_mapping = {
        "schema_version": "crop-cache/v1",
        "dataset_version_id": crop_cache.dataset_version_id,
        "dataset_version_digest": crop_cache.dataset_version_digest,
        "split_version_id": crop_cache.split_version_id,
        "split_version_digest": crop_cache.split_version_digest,
        "transform_version": crop_cache.transform_version,
        "crops": [row.to_mapping() for row in crop_cache.crops],
        "cache_digest": crop_cache.digest,
    }
    write_json(cache_root / "crop-manifest.json", crop_mapping)
    write_json(run_dir / "crop-inventory.json", crop_mapping)

    pretrained_root = (
        ROOT
        / "data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-75000a5eec53a52f088f9e6e"
    )
    pretrained_manifest = read(pretrained_root / "manifest.json")
    frozen_inputs = m0["inputs"]
    for key, path in (
        ("pretrained_bundle_manifest", pretrained_root / "manifest.json"),
        ("pretrained_weights", pretrained_root / "model.safetensors"),
    ):
        if digest(path.read_bytes()) != frozen_inputs[key]["sha256"]:
            raise ValueError(f"M0 frozen DINO asset digest changed: {key}")
    identity_data = pretrained_manifest["identity"]
    weights = MaterializedDinoV3Weights(
        root=pretrained_root,
        model_id=identity_data["model"]["id"],
        model_revision=identity_data["model"]["revision"],
        weight_file=identity_data["model"]["weights"]["file"],
        weight_sha256=identity_data["model"]["weights"]["sha256"],
        config_file=identity_data["model"]["config_file"],
        config_sha256=identity_data["model"]["config_sha256"],
        processor_file=identity_data["model"]["processor_file"],
        processor_sha256=identity_data["model"]["processor_sha256"],
    )
    identity_config = build_dinov3_identity_config(
        weights,
        license_record=identity_data["license"],
        input_size=224,
        feature_layout="cls",
    )
    campaign_id = "dinov3-identity-0088-m1"
    recipes_dir = run_dir / "recipes"
    identity_config_path = recipes_dir / "224-cls.json"
    write_json(identity_config_path, identity_config.to_mapping())
    identity_config_digest = digest(identity_config_path.read_bytes())
    recipe = {
        "schema_version": "0088-dinov3-campaign-recipe/v1",
        "campaign_id": campaign_id,
        "identity_config_path": "recipes/224-cls.json",
        "identity_config_digest": identity_config_digest,
        "input_size": 224,
        "feature_layout": "cls",
        "encoder_training": "frozen",
        "seed": 17,
        "max_epochs": 8,
        "batch_size": 1,
        "optimizer": {"name": "AdamW", "learning_rate": 0.001, "weight_decay": 0.0},
        "device": "mps",
        "precision": "fp32",
        "sampling": {
            "policy": "class_source_weighted_with_replacement",
            "samples_per_epoch": "train_split_size",
        },
        "augmentation": m0["fit_budget"]["augmentation"],
    }
    write_json(run_dir / "recipe.json", recipe)
    training_preflight = {
        "schema_version": "dinov3-identity-training-preflight/v1",
        "campaign_id": campaign_id,
        "state": "ready",
        "device": "mps",
        "precision": "fp32",
        "batch_size": 1,
        "max_epochs": 8,
        "checks": {
            "dataset": {"path": "data/dataset.json", "digest": dataset.digest},
            "split": {"path": "data/split.json", "digest": split.digest},
            "artifacts": {"path": "data/artifact-index.json", "digest": artifacts.digest},
            "crop_inventory": {
                "path": "crop-cache/crop-manifest.json",
                "digest": crop_cache.digest,
            },
            "identity_config": {
                "path": "recipes/224-cls.json",
                "digest": identity_config_digest,
            },
        },
    }
    write_json(run_dir / "training-preflight.json", training_preflight)
    coverage = {
        "schema_version": "0088-m1-training-coverage/v1",
        "target_classes": sorted(target_classes),
        "support": {},
        "train_items": len(train_ids),
        "validation_items": len(validation_ids),
        "calibration_items_outside_dataset": len(cal_samples),
        "recordings_without_references": unavailable,
    }
    # The top-level M1 summary below fills this class-support value from the same frozen crop rows.
    coverage["support"] = {
        name: {
            target: Counter(item["target"] for item in selected_samples)[target]
            for target in m0["source_pool"]["target_classes"]
        }
        for name, selected_samples in (
            ("training", train_samples),
            ("model_selection", val_samples),
            ("confidence_calibration", cal_samples),
        )
    }
    write_json(run_dir / "coverage.json", coverage)
    manifest_core = {
        "schema_version": "dinov3-identity-preparation/v1",
        "campaign_id": campaign_id,
        "milestone": "M1",
        "state": "frozen",
        "freeze_digest": digest(
            canonical(
                {
                    "m0_campaign_readiness": digest(M0.read_bytes()),
                    "source_verification": receipt["source_handoff_sha256"],
                    "reviewed_materialization": reviewed["manifest_digest"],
                    "provider_bundle": PROVIDER_SHA256,
                }
            )
        ),
        "preflight_manifest_digest": digest(M0.read_bytes()),
        "selection": partitions,
        "dataset": {
            "path": "data/dataset.json",
            "id": dataset.dataset_version_id,
            "digest": dataset.digest,
        },
        "split": {
            "path": "data/split.json",
            "id": split.split_version_id,
            "digest": split.digest,
        },
        "artifact_index": {
            "path": "data/artifact-index.json",
            "id": artifacts.artifact_index_id,
            "digest": artifacts.digest,
        },
        "crop_inventory": {"path": "crop-cache/crop-manifest.json", "digest": crop_cache.digest},
        "coverage": {"path": "coverage.json", "digest": digest(canonical(coverage))},
        "recipe": {"path": "recipe.json", "digest": digest(canonical(recipe))},
        "training_preflight": {
            "path": "training-preflight.json",
            "digest": digest(canonical(training_preflight)),
            "command": m0["command_templates"]["primary_fit"],
        },
        "revision_content_digests": [
            {
                "recording_id": recording_id,
                "visible_card_content_sha256": details[recording_id]["visible"]["content_digest"],
                "visual_identity_content_sha256": details[recording_id]["identity"][
                    "content_digest"
                ],
            }
            for recording_id in sorted(details)
        ],
        "unsupported_identities": [
            identity
            for identity in identity_config.target_map.values()
            if identity.endswith("_NINE")
        ],
    }
    campaign_manifest = {
        **manifest_core,
        "manifest_digest": digest(canonical(manifest_core)),
    }
    write_json(run_dir / "manifest.json", campaign_manifest)

    # Build development automatic crops. Provider inference runs before the code reads any
    # reviewed identity target for the same frame.
    provider = LocalVisibleCardSegmentationProvider(provider_bundle, device=args.device)
    automatic_root = run_dir / "automatic-development"
    shutil.rmtree(automatic_root, ignore_errors=True)
    automatic_root.mkdir(parents=True)
    automatic_rows, missing_inputs = [], []
    provider_frames = 0
    provider_proposals = 0
    provider_unavailable = []
    eval_samples = val_samples + cal_samples
    frame_samples: dict[str, list[dict[str, Any]]] = {}
    for sample in eval_samples:
        key = digest(canonical(sample["frame_identity"]))
        frame_samples.setdefault(key, []).append(sample)
    for frame_key, frame_rows in sorted(frame_samples.items()):
        reference_frame = frames[frame_key]
        recording_id = frame_rows[0]["recording_id"]
        request = VisibleCardRequest(
            package_id=recording_id,
            frame_part_name=f"frame-{frame_key[:16]}",
            target_offset_ms=reference_frame.requested_time_us // 1000,
            image_bytes=reference_frame.image_bytes,
            width=reference_frame.width,
            height=reference_frame.height,
            provider=provider.name,
            image_mime_type=reference_frame.content_type,
        )
        result = provider.propose(request)
        if result.status != "ok":
            provider_unavailable.append({"recording_id": recording_id, "frame_key": frame_key})
            missing_inputs.append(
                {
                    "recording_id": recording_id,
                    "frame_key": frame_key,
                    "reason": "provider_unavailable",
                    "detail": result.error,
                }
            )
            continue
        provider_frames += 1
        provider_proposals += len(result.proposals)
        # Predictions have already been generated. Reviewed geometry is used only to associate
        # predictions with reviewed examples and never changes a predicted crop or target.
        proposals = list(result.proposals)
        references = []
        for sample in frame_rows:
            geometry = next(
                candidate["geometry"]
                for outcome in details[recording_id]["visible"]["content"]["outcomes"]
                if outcome.get("frame_identity") == sample["frame_identity"]
                for candidate in outcome.get("candidates", [])
                if candidate.get("card_id") == sample["card_id"]
            )
            polygons = geometry["visible_region"]["polygons"]
            references.append(
                (
                    sample,
                    tuple(
                        tuple(NormalizedPoint(x=point["x"], y=point["y"]) for point in polygon)
                        for polygon in polygons
                    ),
                )
            )
        candidates = []
        best_reference_by_prediction = {}
        ambiguous_predictions = set()
        for proposal_index, proposal in enumerate(proposals):
            proposal_polygons = proposal.polygons or (proposal.polygon,)
            best_reference = None
            scored_references = []
            for sample, ref_polygons in references:
                iou = max(
                    polygon_iou(predicted, reviewed_polygon)
                    for predicted in proposal_polygons
                    for reviewed_polygon in ref_polygons
                )
                if best_reference is None or iou > best_reference[1]:
                    best_reference = (sample, iou)
                scored_references.append((sample, iou))
            if best_reference and best_reference[1] >= 0.5:
                winners = [
                    sample
                    for sample, iou in scored_references
                    if math.isclose(iou, best_reference[1], abs_tol=1e-9)
                ]
                if len(winners) > 1:
                    ambiguous_predictions.add(proposal_index)
                else:
                    candidates.extend(
                        (iou, proposal_index, sample)
                        for sample, iou in scored_references
                        if iou >= 0.5
                    )
            best_reference_by_prediction[proposal_index] = best_reference
        assignments, used_predictions, used_samples = [], set(), set()
        used_predictions.update(ambiguous_predictions)
        for iou, prediction_index, sample in sorted(
            candidates, key=lambda row: (-row[0], row[1], row[2]["sample_id"])
        ):
            if prediction_index in used_predictions or sample["sample_id"] in used_samples:
                continue
            assignments.append((prediction_index, sample, iou))
            used_predictions.add(prediction_index)
            used_samples.add(sample["sample_id"])
        for sample in frame_rows:
            if sample["sample_id"] not in used_samples:
                missing_inputs.append(
                    {
                        "recording_id": recording_id,
                        "sample_id": sample["sample_id"],
                        "reason": "no_matched_automatic_prediction",
                    }
                )
        assignment_by_prediction = {
            prediction_index: (sample, iou) for prediction_index, sample, iou in assignments
        }
        for prediction_index, proposal in enumerate(proposals):
            visible_components = proposal.polygons or (proposal.polygon,)
            geometry = PredictedVisibleRegionGeometry(
                polygons=tuple(
                    tuple((point.x, point.y) for point in polygon) for polygon in visible_components
                )
            )
            crop = resolve_visible_region_crop(
                reference_frame,
                geometry,
                crop_policy="predicted_visible_region",
                output_encoding="ppm",
                identity_usable=True,
            )
            if crop.status != "usable" or crop.image_bytes is None:
                missing_inputs.append(
                    {
                        "recording_id": recording_id,
                        "frame_key": frame_key,
                        "provider_proposal_index": prediction_index,
                        "reason": "automatic_crop_unusable",
                    }
                )
                continue
            assignment = assignment_by_prediction.get(prediction_index)
            sample = assignment[0] if assignment else None
            iou = assignment[1] if assignment else None
            best_reference = best_reference_by_prediction[prediction_index]
            stable_key = sample["sample_id"] if sample else f"{frame_key}:{prediction_index}"
            filename = f"{digest(stable_key.encode())}.ppm"
            (automatic_root / filename).write_bytes(crop.image_bytes)
            automatic_rows.append(
                {
                    "recording_id": recording_id,
                    "sample_id": sample["sample_id"] if sample else None,
                    "frame_key": frame_key,
                    "frame_identity": reference_frame.identity_mapping(),
                    "partition": partition_by_recording[recording_id],
                    "provider_proposal_index": prediction_index,
                    "association_iou": round(iou, 6) if iou is not None else None,
                    "best_reviewed_sample_id": (
                        best_reference[0]["sample_id"] if best_reference else None
                    ),
                    "best_reviewed_iou": (round(best_reference[1], 6) if best_reference else None),
                    "predicted_polygons": [
                        [point.to_mapping() for point in polygon] for polygon in visible_components
                    ],
                    "association_state": "matched" if sample else "unmatched",
                    "automatic_crop_path": filename,
                    "automatic_crop_sha256": digest(crop.image_bytes),
                    "reviewed_identity_target": sample["target"] if sample else None,
                    "reviewed_card_id": sample["card_id"] if sample else None,
                    "reviewed_identity_revision_id": (
                        sample["visual_identity_revision_id"] if sample else None
                    ),
                    "target_source": (
                        "completed_human_review_after_prediction_association" if sample else None
                    ),
                    "predicted_side": proposal.side,
                    "predicted_label": proposal.label,
                }
            )
    write_json(
        automatic_root / "manifest.json",
        {
            "schema_version": "0088-m1-automatic-development-view/v1",
            "provider_bundle_sha256": PROVIDER_SHA256,
            "association_policy": "greedy_one_to_one_polygon_iou_at_least_0.5",
            "provider_frame_count": provider_frames,
            "provider_unavailable_frames": provider_unavailable,
            "provider_proposal_count": provider_proposals,
            "prediction_count": len(automatic_rows),
            "missing_input_count": len(missing_inputs),
            "rows": automatic_rows,
            "missing_inputs": missing_inputs,
        },
    )

    # Record final-test identity only from frozen M0 membership. Do not load its references or
    # frames.
    final_membership = [
        {"recording_id": item["recording_id"], "source_group_id": item["source_group_id"]}
        for item in partitions["final_test"]
    ]
    result = {
        "schema_version": "0088-m1-campaign-views/v1",
        "reviewed_materialization_digest": reviewed["manifest_digest"],
        "cold_warm_digests_match": True,
        "provider": {
            "bundle": str(PROVIDER_BUNDLE.relative_to(ROOT)),
            "bundle_sha256": PROVIDER_SHA256,
            "device": args.device,
        },
        "dataset": {
            "id": dataset.dataset_version_id,
            "digest": dataset.digest,
            "entry_count": len(entries),
            "train_count": len(train_ids),
            "validation_count": len(validation_ids),
            "calibration_not_in_training_dataset": len(cal_samples),
        },
        "support": {
            partition_name: {
                target: counts[target] for target in m0["source_pool"]["target_classes"]
            }
            for partition_name, counts in (
                ("training", Counter(s["target"] for s in train_samples)),
                ("model_selection", Counter(s["target"] for s in val_samples)),
                ("confidence_calibration", Counter(s["target"] for s in cal_samples)),
            )
        },
        "reviewed_exclusions": reviewed["exclusions"],
        "non_campaign_target_exclusions": [
            {
                "sample_id": sample["sample_id"],
                "recording_id": sample["recording_id"],
                "target": sample["target"],
                "reason": "target_not_in_frozen_0088_campaign",
            }
            for sample in non_campaign_samples
        ],
        "recordings_without_complete_references": unavailable,
        "automatic_views": {
            "status": "materialized",
            "association_policy": "greedy_one_to_one_polygon_iou_at_least_0.5",
            "provider_frame_count": provider_frames,
            "provider_proposal_count": provider_proposals,
            "automatic_crop_count": len(automatic_rows),
            "matched_count": sum(row["sample_id"] is not None for row in automatic_rows),
            "missing_input_count": len(missing_inputs),
            "covered_recordings": sorted({row["recording_id"] for row in automatic_rows}),
            "missing_inputs": missing_inputs,
        },
        "final_test_membership": final_membership,
        "final_test_rendered_or_scored": False,
        "unreviewed_predictions_used_as_targets": False,
    }
    write_json(run_dir / "campaign-view-manifest.json", result)
    write_json(run_dir / "reviewed-manifest.json", reviewed)
    print(
        json.dumps(
            {
                "dataset": result["dataset"],
                "reviewed_digest": reviewed["manifest_digest"],
                "reviewed_samples": len(samples),
                "calibration_samples": len(cal_samples),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
