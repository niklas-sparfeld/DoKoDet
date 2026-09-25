"""Audit RF-DETR proposed card scenes for one frozen pose-derived campaign."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .rfdetr_segmentation_campaign import canonical_json_bytes, sha256_json

POSE_DERIVED_MANIFEST_SCHEMA_VERSION = "rfdetr-pose-derived-campaign-manifest/v1"
POSE_DERIVED_CAMPAIGN_ID = "0084-m0-rfdetr-pose-derived-visible-cards"
MINIMUM_CANDIDATE_FRAMES = 100
MINIMUM_CANDIDATE_GROUPS = 5
MINIMUM_CANDIDATE_POSES = 400
MINIMUM_MATERIALIZED_MASKS = 300
MINIMUM_VISIBLE_PIXELS = 256
MINIMUM_VISIBLE_BOX = [16, 16]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RfdetrPoseDerivedCampaignError(ValueError):
    """The proposed-scene campaign audit could not be completed safely."""


def _read_json(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RfdetrPoseDerivedCampaignError(f"could not read {name} {path}: {error}") from error
    if not isinstance(value, dict):
        raise RfdetrPoseDerivedCampaignError(f"{name} must be a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exclusion(
    *, run_id: str, recording_id: str, frame_id: str | None, reasons: Sequence[str]
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "recording_id": recording_id,
        "frame_id": frame_id,
        "reasons": sorted(set(reasons)),
    }


def _exclude_run_frames(
    run_dir: Path, *, run_id: str, recording_id: str, reason: str
) -> list[dict[str, Any]]:
    """Record an exclusion for each stored frame, or for the failed run if it has no frames."""

    item_paths = sorted((run_dir / "items").glob("*.json"))
    if not item_paths:
        return [
            _exclusion(
                run_id=run_id,
                recording_id=recording_id,
                frame_id=None,
                reasons=[reason],
            )
        ]
    results: list[dict[str, Any]] = []
    for item_path in item_paths:
        item = _read_json(item_path, f"proposal item {item_path.name}")
        frame_id = item.get("item_id")
        results.append(
            _exclusion(
                run_id=run_id,
                recording_id=recording_id,
                frame_id=frame_id if isinstance(frame_id, str) else item_path.stem,
                reasons=[reason],
            )
        )
    return results


def _recording_metadata(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    groups = manifest.get("source_groups")
    if not isinstance(groups, list):
        raise RfdetrPoseDerivedCampaignError("0068 manifest has no source-group list")
    result: dict[str, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, Mapping):
            raise RfdetrPoseDerivedCampaignError("0068 source groups must be objects")
        recording_id = group.get("recording_id")
        if not isinstance(recording_id, str) or not recording_id:
            raise RfdetrPoseDerivedCampaignError("0068 source group has no recording ID")
        if recording_id in result:
            raise RfdetrPoseDerivedCampaignError(
                f"0068 manifest repeats recording source group {recording_id}"
            )
        result[recording_id] = dict(group)
    return result


def _same_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _scene_quality_reasons(proposal: Mapping[str, Any], revision: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    scene = proposal.get("initialized_scene")
    if not isinstance(scene, Mapping):
        return ["missing_initialized_scene"]
    poses = scene.get("poses")
    if not isinstance(poses, list) or not poses:
        reasons.append("empty_pose_set")
        poses = []
    pose_ids = [pose.get("card_id") for pose in poses if isinstance(pose, Mapping)]
    if len(pose_ids) != len(poses) or len(set(pose_ids)) != len(pose_ids):
        reasons.append("invalid_or_duplicate_pose_ids")

    order = scene.get("stacking_order")
    if not isinstance(order, Mapping):
        reasons.append("missing_stacking_order")
    else:
        ordered_ids = order.get("card_ids")
        if not isinstance(ordered_ids, list) or set(ordered_ids) != set(pose_ids):
            reasons.append("stacking_order_does_not_cover_pose_set")
        if order.get("contradictions"):
            reasons.append("contradictory_stacking_order")
        if order.get("uncertain_edges"):
            reasons.append("unresolved_overlapping_card_order")

    diagnostics = proposal.get("fit_diagnostics")
    details = diagnostics.get("diagnostics") if isinstance(diagnostics, Mapping) else None
    fits = diagnostics.get("fit_diagnostics") if isinstance(diagnostics, Mapping) else None
    if not isinstance(details, Mapping) or not isinstance(fits, list):
        reasons.append("missing_pose_fit_diagnostics")
    else:
        if not _same_sha256(details.get("recipe_digest")):
            reasons.append("invalid_pose_recipe_digest")
        if details.get("initialized_count") != len(poses):
            reasons.append("incomplete_initialized_pose_set")
        if details.get("candidate_count") != len(poses):
            reasons.append("candidate_pose_set_incomplete")
        if details.get("failed_suggestion_ids"):
            reasons.append("failed_pose_suggestions")
        if details.get("low_confidence_suggestion_ids"):
            reasons.append("low_confidence_pose_suggestions")
        fit_by_id = {fit.get("card_id"): fit for fit in fits if isinstance(fit, Mapping)}
        if len(fit_by_id) != len(poses) or set(fit_by_id) != set(pose_ids):
            reasons.append("pose_fit_set_does_not_match_scene")
        for pose_id in pose_ids:
            fit = fit_by_id.get(pose_id)
            if not isinstance(fit, Mapping) or fit.get("accepted") is not True:
                reasons.append("pose_fit_not_accepted")
                break

    coverage = revision.get("coverage")
    if not isinstance(coverage, Mapping):
        reasons.append("missing_proposal_revision_coverage")
    else:
        if scene.get("calibration_revision_id") != coverage.get("calibration_revision_id"):
            reasons.append("calibration_revision_mismatch")
        if scene.get("calibration_digest") != coverage.get("calibration_digest"):
            reasons.append("calibration_digest_mismatch")
        if proposal.get("detector_revision_id") != coverage.get("detector_revision_id"):
            reasons.append("visible_card_revision_mismatch")
        if proposal.get("detector_revision_digest") != coverage.get("detector_revision_digest"):
            reasons.append("visible_card_digest_mismatch")
    if not _same_sha256(proposal.get("source_frame_digest")):
        reasons.append("invalid_source_frame_digest")
    return sorted(set(reasons))


def build_rfdetr_pose_derived_manifest(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path,
    proposal_run_ids: Sequence[str],
    operations_root: str | Path | None = None,
    verify_source_bytes: bool = True,
    minimum_frames: int = MINIMUM_CANDIDATE_FRAMES,
    minimum_groups: int = MINIMUM_CANDIDATE_GROUPS,
    minimum_poses: int = MINIMUM_CANDIDATE_POSES,
) -> dict[str, Any]:
    """Build a deterministic read-only audit from frozen 0068 and 0083 inputs."""

    repository = Path(repository_root).expanduser().resolve()
    operations = (
        Path(operations_root).expanduser().resolve()
        if operations_root is not None
        else repository / "data" / "operations"
    )
    source_path = Path(source_manifest_path).expanduser()
    if not source_path.is_absolute():
        source_path = (repository / source_path).resolve()
    source = _read_json(source_path, "0068 manifest")
    if source.get("freeze_state") != "frozen":
        raise RfdetrPoseDerivedCampaignError("0068 manifest is not frozen")
    source_digest = source.get("manifest_digest")
    if not _same_sha256(source_digest):
        raise RfdetrPoseDerivedCampaignError("0068 manifest has no valid digest")
    source_core = {key: value for key, value in source.items() if key != "manifest_digest"}
    if sha256_json(source_core) != source_digest:
        raise RfdetrPoseDerivedCampaignError("0068 manifest digest does not match its contents")
    if min(minimum_frames, minimum_groups, minimum_poses) < 1:
        raise RfdetrPoseDerivedCampaignError("minimum candidate counts must be positive")

    groups = _recording_metadata(source)
    train_groups = {
        key: value for key, value in groups.items() if value.get("partition") == "train"
    }
    source_recordings = {
        row.get("recording_id"): row
        for row in source.get("recordings", [])
        if isinstance(row, Mapping) and isinstance(row.get("recording_id"), str)
    }
    verified_sources: dict[str, dict[str, Any]] = {}
    reviewed_train_frames = {
        str(sample.get("event_id"))
        for sample in source.get("samples", [])
        if isinstance(sample, Mapping) and sample.get("split") == "train"
    }
    run_ids = tuple(sorted(set(proposal_run_ids)))
    if not run_ids or len(run_ids) != len(proposal_run_ids):
        raise RfdetrPoseDerivedCampaignError("proposal run IDs must be non-empty and unique")

    run_inventory: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    calibrations: dict[str, dict[str, Any]] = {}
    for run_id in run_ids:
        run_dir = operations / "pipeline" / "runs" / run_id
        state = _read_json(run_dir / "state.json", f"proposal run state {run_id}")
        request = _read_json(run_dir / "request.json", f"proposal run request {run_id}")
        source_record = request.get("source")
        recording_id = (
            source_record.get("recording_id") if isinstance(source_record, Mapping) else None
        )
        if not isinstance(recording_id, str) or not recording_id:
            raise RfdetrPoseDerivedCampaignError(f"proposal run {run_id} has no recording ID")
        if state.get("run_id") != run_id or request.get("run_id") != run_id:
            raise RfdetrPoseDerivedCampaignError(f"proposal run ID mismatch for {run_id}")
        if state.get("status") not in {"complete", "partial", "failed"}:
            raise RfdetrPoseDerivedCampaignError(f"proposal run {run_id} is not terminal")
        output_ids = state.get("output_revision_ids")
        if not isinstance(output_ids, list):
            output_ids = []
        proposal_revision_ids = [
            value
            for value in output_ids
            if isinstance(value, str) and value.startswith("card-scene-proposals-")
        ]
        if state.get("status") != "failed" and len(proposal_revision_ids) != 1:
            raise RfdetrPoseDerivedCampaignError(
                f"proposal run {run_id} must have one proposal output revision"
            )
        run_entry = {
            "run_id": run_id,
            "recording_id": recording_id,
            "status": state["status"],
            "created_at": state.get("created_at"),
            "completed_at": state.get("completed_at"),
            "request_sha256": _sha256_file(run_dir / "request.json"),
            "state_sha256": _sha256_file(run_dir / "state.json"),
            "input_revision_ids": request.get("input_revision_ids", []),
            "output_revision_ids": sorted(output_ids),
        }
        run_inventory.append(run_entry)

        if recording_id not in train_groups:
            exclusions.extend(
                _exclude_run_frames(
                    run_dir,
                    run_id=run_id,
                    recording_id=recording_id,
                    reason="source_group_not_in_0068_training_partition",
                )
            )
            continue
        permissions = source_recordings.get(recording_id, {})
        if (
            not isinstance(permissions, Mapping)
            or "train" not in permissions.get("allowed_uses", [])
            or permissions.get("retention_state") != "active"
        ):
            exclusions.extend(
                _exclude_run_frames(
                    run_dir,
                    run_id=run_id,
                    recording_id=recording_id,
                    reason="source_permission_does_not_allow_training",
                )
            )
            continue
        source_video_path = permissions.get("source_video_path")
        if not isinstance(source_video_path, str) or not source_video_path:
            raise RfdetrPoseDerivedCampaignError(
                f"0068 manifest has no source video path for {recording_id}"
            )
        source_path = (repository / source_video_path).resolve()
        try:
            source_path.relative_to(repository)
        except ValueError as error:
            raise RfdetrPoseDerivedCampaignError(
                f"source video path escapes repository for {recording_id}"
            ) from error
        source_sha256 = train_groups[recording_id].get("source_sha256")
        source_report = {
            "recording_id": recording_id,
            "relative_path": source_video_path,
            "sha256": source_sha256,
            "byte_length": permissions.get("source_byte_length"),
            "bytes_verified": False,
        }
        if verify_source_bytes and recording_id not in verified_sources:
            if not source_path.is_file():
                raise RfdetrPoseDerivedCampaignError(
                    f"source video is missing for {recording_id}: {source_path}"
                )
            actual_sha256 = _sha256_file(source_path)
            actual_byte_length = source_path.stat().st_size
            if actual_sha256 != source_sha256:
                raise RfdetrPoseDerivedCampaignError(
                    f"source video digest mismatch for {recording_id}"
                )
            if actual_byte_length != permissions.get("source_byte_length"):
                raise RfdetrPoseDerivedCampaignError(
                    f"source video byte length mismatch for {recording_id}"
                )
            source_report["bytes_verified"] = True
            verified_sources[recording_id] = source_report
        if request.get("source", {}).get("video_sha256") != train_groups[recording_id].get(
            "source_sha256"
        ):
            exclusions.extend(
                _exclude_run_frames(
                    run_dir,
                    run_id=run_id,
                    recording_id=recording_id,
                    reason="source_video_digest_mismatch",
                )
            )
            continue
        if request.get("source", {}).get("relative_path") != source_video_path:
            exclusions.extend(
                _exclude_run_frames(
                    run_dir,
                    run_id=run_id,
                    recording_id=recording_id,
                    reason="source_video_path_mismatch",
                )
            )
            continue
        if request.get("source", {}).get("byte_length") != permissions.get("source_byte_length"):
            exclusions.extend(
                _exclude_run_frames(
                    run_dir,
                    run_id=run_id,
                    recording_id=recording_id,
                    reason="source_video_byte_length_mismatch",
                )
            )
            continue
        if state["status"] == "failed":
            exclusions.extend(
                _exclude_run_frames(
                    run_dir,
                    run_id=run_id,
                    recording_id=recording_id,
                    reason="proposal_run_failed",
                )
            )
            continue

        revision_id = proposal_revision_ids[0]
        revision_dir = operations / "pipeline" / "revisions" / revision_id
        revision_path = revision_dir / "manifest.json"
        revision = _read_json(revision_path, f"proposal revision {revision_id}")
        if (
            revision.get("revision_id") != revision_id
            or revision.get("recording_id") != recording_id
        ):
            raise RfdetrPoseDerivedCampaignError(f"proposal revision lineage mismatch for {run_id}")
        producer = revision.get("producer")
        if not isinstance(producer, Mapping) or producer.get("run_id") != run_id:
            raise RfdetrPoseDerivedCampaignError(
                f"proposal revision producer mismatch for {run_id}"
            )
        if revision.get("source", {}).get("video_sha256") != train_groups[recording_id].get(
            "source_sha256"
        ):
            raise RfdetrPoseDerivedCampaignError(f"proposal revision source mismatch for {run_id}")
        revision_entry = {
            "revision_id": revision_id,
            "manifest_sha256": _sha256_file(revision_path),
            "content_sha256": revision.get("content_sha256"),
            "coverage": revision.get("coverage"),
        }
        proposal_content_path = revision_dir / "content.json"
        proposal_content = _read_json(proposal_content_path, f"proposal content {revision_id}")
        if sha256_json(proposal_content) != revision.get("content_sha256"):
            raise RfdetrPoseDerivedCampaignError(
                f"proposal content digest mismatch for {revision_id}"
            )
        calibration = proposal_content.get("calibration")
        if not isinstance(calibration, Mapping):
            raise RfdetrPoseDerivedCampaignError(
                f"proposal content has no calibration for {revision_id}"
            )
        coverage = revision.get("coverage")
        if not isinstance(coverage, Mapping):
            raise RfdetrPoseDerivedCampaignError(
                f"proposal revision has no coverage for {revision_id}"
            )
        if (
            calibration.get("calibration_revision_id") != coverage.get("calibration_revision_id")
            or calibration.get("calibration_digest") != coverage.get("calibration_digest")
            or calibration.get("recording_id") != recording_id
        ):
            raise RfdetrPoseDerivedCampaignError(
                f"calibration content lineage mismatch for {revision_id}"
            )
        calibration_key = f"{recording_id}:{calibration['calibration_digest']}"
        calibrations[calibration_key] = dict(calibration)
        content_frames = proposal_content.get("frames")
        if not isinstance(content_frames, list):
            raise RfdetrPoseDerivedCampaignError(
                f"proposal content has no frame list for {revision_id}"
            )
        frame_content_by_id = {
            row.get("frame_id"): row for row in content_frames if isinstance(row, Mapping)
        }
        if len(frame_content_by_id) != len(content_frames):
            raise RfdetrPoseDerivedCampaignError(
                f"proposal content has duplicate or invalid frame IDs for {revision_id}"
            )
        if (
            proposal_content.get("detector_revision_id")
            != revision.get("coverage", {}).get("detector_revision_id")
            or proposal_content.get("detector_revision_digest")
            != revision.get("coverage", {}).get("detector_revision_digest")
            or proposal_content.get("calibration_revision_id")
            != revision.get("coverage", {}).get("calibration_revision_id")
            or proposal_content.get("calibration_digest")
            != revision.get("coverage", {}).get("calibration_digest")
        ):
            raise RfdetrPoseDerivedCampaignError(
                f"proposal content coverage differs from its manifest for {revision_id}"
            )
        detector_revision_id = revision.get("coverage", {}).get("detector_revision_id")
        detector_manifest_path = (
            operations / "pipeline" / "revisions" / str(detector_revision_id) / "manifest.json"
        )
        detector_manifest = _read_json(
            detector_manifest_path, f"visible-card revision {detector_revision_id}"
        )
        detector_producer = detector_manifest.get("producer")
        if not isinstance(detector_producer, Mapping):
            raise RfdetrPoseDerivedCampaignError(
                f"visible-card revision has no model lineage: {detector_revision_id}"
            )
        detector_model_id = detector_producer.get("model_id")
        if not isinstance(detector_model_id, str) or not detector_model_id.startswith(
            "local-rfdetr-segmentation."
        ):
            raise RfdetrPoseDerivedCampaignError(
                "visible-card revision is not from the local RF-DETR provider: "
                f"{detector_revision_id}"
            )
        if detector_manifest.get("content_sha256") != revision.get("coverage", {}).get(
            "detector_revision_digest"
        ):
            raise RfdetrPoseDerivedCampaignError(
                f"visible-card content digest mismatch: {detector_revision_id}"
            )
        if detector_manifest.get("recording_id") != recording_id:
            raise RfdetrPoseDerivedCampaignError(
                f"visible-card recording mismatch: {detector_revision_id}"
            )
        if request.get("input_revision_ids") != [detector_revision_id]:
            raise RfdetrPoseDerivedCampaignError(
                f"proposal run input does not match detector revision: {run_id}"
            )
        items_dir = run_dir / "items"
        item_paths = sorted(items_dir.glob("*.json")) if items_dir.exists() else []
        if {path.stem for path in item_paths} != set(frame_content_by_id):
            raise RfdetrPoseDerivedCampaignError(
                f"proposal run items differ from revision frames for {run_id}"
            )
        for item_path in item_paths:
            raw_item = _read_json(item_path, f"proposal item {item_path.name}")
            frame_id = raw_item.get("item_id")
            result = raw_item.get("result")
            proposal = result.get("proposal") if isinstance(result, Mapping) else None
            if not isinstance(frame_id, str) or not isinstance(proposal, Mapping):
                exclusions.append(
                    _exclusion(
                        run_id=run_id,
                        recording_id=recording_id,
                        frame_id=frame_id if isinstance(frame_id, str) else None,
                        reasons=["invalid_proposal_item"],
                    )
                )
                continue
            reasons: list[str] = []
            if not isinstance(proposal.get("initializer_recipe_version"), str):
                reasons.append("missing_pose_recipe_version")
            content_frame = frame_content_by_id.get(frame_id)
            if raw_item.get("status") != "succeeded" or proposal.get("status") != "supported":
                reasons.append("proposal_frame_unsupported")
            if proposal.get("source_frame_id") != frame_id:
                reasons.append("source_frame_identity_mismatch")
            if (
                not isinstance(content_frame, Mapping)
                or content_frame.get("source_frame_digest") != proposal.get("source_frame_digest")
                or content_frame.get("status") != proposal.get("status")
            ):
                reasons.append("proposal_revision_frame_mismatch")
            if frame_id in reviewed_train_frames:
                reasons.append("duplicate_of_0068_reviewed_training_frame")
            reasons.extend(_scene_quality_reasons(proposal, revision))
            if reasons:
                exclusions.append(
                    _exclusion(
                        run_id=run_id,
                        recording_id=recording_id,
                        frame_id=frame_id,
                        reasons=reasons,
                    )
                )
                continue
            scene = proposal["initialized_scene"]
            poses = scene["poses"]
            accepted.append(
                {
                    "recording_id": recording_id,
                    "source_group": train_groups[recording_id],
                    "source_permission": permissions.get("source_permission"),
                    "allowed_uses": sorted(permissions.get("allowed_uses", [])),
                    "run_id": run_id,
                    "proposal_revision_id": revision_id,
                    "proposal_revision_sha256": revision_entry["manifest_sha256"],
                    "proposal_content_sha256": revision.get("content_sha256"),
                    "visible_card_revision_id": proposal.get("detector_revision_id"),
                    "visible_card_revision_digest": proposal.get("detector_revision_digest"),
                    "visible_card_model_id": detector_producer.get("model_id"),
                    "visible_card_model_run_id": detector_producer.get("run_id"),
                    "calibration_revision_id": proposal.get("calibration_revision_id"),
                    "calibration_digest": proposal.get("calibration_digest"),
                    "pose_recipe_version": proposal.get("initializer_recipe_version"),
                    "pose_recipe_digest": (
                        proposal.get("fit_diagnostics", {})
                        .get("diagnostics", {})
                        .get("recipe_digest")
                    ),
                    "frame_id": frame_id,
                    "source_frame_digest": proposal.get("source_frame_digest"),
                    "scene_digest": scene.get("scene_digest"),
                    "pose_count": len(poses),
                    "pose_ids": sorted(pose["card_id"] for pose in poses),
                    "calibration_key": calibration_key,
                    "hand_occlusion_review": "required_before_training",
                }
            )

    accepted.sort(key=lambda row: (row["recording_id"], row["frame_id"]))
    exclusions.sort(
        key=lambda row: (row["recording_id"], row["run_id"], row["frame_id"] or "", row["reasons"])
    )
    group_keys = {row["source_group"]["group_key"] for row in accepted}
    pose_count = sum(row["pose_count"] for row in accepted)
    minimum_gaps = []
    if len(accepted) < minimum_frames:
        minimum_gaps.append(f"eligible frame count {len(accepted)} is below {minimum_frames}")
    if len(group_keys) < minimum_groups:
        minimum_gaps.append(
            f"eligible source-group count {len(group_keys)} is below {minimum_groups}"
        )
    if pose_count < minimum_poses:
        minimum_gaps.append(f"eligible pose count {pose_count} is below {minimum_poses}")

    real_sample_count = source.get("split", {}).get("train", {}).get("retained_frames")
    if not isinstance(real_sample_count, int) or real_sample_count < 1:
        raise RfdetrPoseDerivedCampaignError("0068 manifest has no frozen training sample count")
    recipe = source.get("recipe")
    if not isinstance(recipe, Mapping):
        raise RfdetrPoseDerivedCampaignError("0068 manifest has no frozen RF-DETR recipe")
    if sha256_json(recipe) != source.get("recipe_sha256"):
        raise RfdetrPoseDerivedCampaignError("0068 RF-DETR recipe digest does not match")
    core = {
        "schema_version": POSE_DERIVED_MANIFEST_SCHEMA_VERSION,
        "campaign_id": POSE_DERIVED_CAMPAIGN_ID,
        "milestone": "M0",
        "freeze_state": "frozen" if not minimum_gaps else "blocked",
        "source_manifest": {
            "path": source_path.as_posix(),
            "manifest_digest": source_digest,
            "file_sha256": _sha256_file(source_path),
        },
        "proposal_runs": run_inventory,
        "verified_source_videos": [verified_sources[key] for key in sorted(verified_sources)],
        "calibrations": {key: calibrations[key] for key in sorted(calibrations)},
        "source_groups": [train_groups[key] for key in sorted(train_groups)],
        "selection_policy": {
            "partition": "0068 train only",
            "minimum_frames": minimum_frames,
            "minimum_source_groups": minimum_groups,
            "minimum_card_poses": minimum_poses,
            "post_materialization_minimum": {
                "visible_frames": minimum_frames,
                "source_groups": minimum_groups,
                "visible_card_masks": MINIMUM_MATERIALIZED_MASKS,
            },
            "minimum_basis": (
                "At least 100 frames, 5 training source groups, and 400 candidate poses before "
                "mask construction; retain at least 300 visible masks after occlusion and size "
                "filters. The final mask count is about 20 percent of the 0068 training target "
                "count and gives a material addition to the real-only corpus."
            ),
            "exclude_exact_reviewed_frame_duplicates": True,
            "exclude_failed_pose_fits": True,
            "exclude_low_confidence_poses": True,
            "exclude_contradictory_or_uncertain_overlap_order": True,
            "hand_occlusion_gate": "review_required_before_training",
        },
        "mask_policy": {
            "outline": "rounded_physical_card_outline/v1",
            "occlusion": "front_to_back_card_stacking_order/v1",
            "clip_to_source_frame": True,
            "preserve_disconnected_components": True,
            "encoding": "COCO_RLE",
            "minimum_visible_pixels": MINIMUM_VISIBLE_PIXELS,
            "minimum_tight_box_width_pixels": MINIMUM_VISIBLE_BOX[0],
            "minimum_tight_box_height_pixels": MINIMUM_VISIBLE_BOX[1],
            "mask_minimum_gate": {
                "minimum_frames": minimum_frames,
                "minimum_source_groups": minimum_groups,
                "minimum_masks": MINIMUM_MATERIALIZED_MASKS,
            },
        },
        "paired_campaign": {
            "control": "0068 reviewed training samples only",
            "candidate": "same 0068 training samples plus pose-derived frames",
            "source_recipe": dict(recipe),
            "source_recipe_sha256": sha256_json(recipe),
            "candidate_count": 2,
            "optimizer": "rfdetr-1.9.4-library-default-no-override",
            "per_candidate_wall_clock_seconds": recipe.get("budget", {}).get("wall_clock_seconds"),
            "total_wall_clock_seconds": 2
            * int(recipe.get("budget", {}).get("wall_clock_seconds", 0)),
            "real_sample_presentations_per_epoch": real_sample_count,
            "derived_sample_presentations_per_epoch": real_sample_count,
            "report_extra_derived_compute_separately": True,
            "derived_to_real_sample_ratio": [1, 1],
            "derived_sampling": {
                "policy": "uniform_with_replacement_seeded_per_epoch/v1",
                "seed": 8404,
            },
            "validation_partition": "0068 validation, unchanged",
            "sealed_test_policy": "run_once_only_if_validation_gate_passes",
            "validation_gate": {
                "candidate_mask_ap_50_95_strictly_greater_than_control": True,
                "candidate_recall_strictly_greater_than_control": True,
            },
            "metrics": recipe.get("validation", {}).get("metrics", []),
        },
        "eligible_scenes": accepted,
        "excluded_scenes": exclusions,
        "inventory": {
            "eligible_frame_count": len(accepted),
            "eligible_source_group_count": len(group_keys),
            "eligible_pose_count": pose_count,
            "excluded_scene_count": sum(row["frame_id"] is not None for row in exclusions),
            "excluded_run_count": sum(row["frame_id"] is None for row in exclusions),
            "excluded_receipt_count": len(exclusions),
            "real_training_frame_count": real_sample_count,
        },
        "minimum_gaps": minimum_gaps,
    }
    return json.loads(
        canonical_json_bytes({**core, "manifest_digest": sha256_json(core)}).decode("utf-8")
    )


def write_rfdetr_pose_derived_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    """Write an immutable M0 manifest without replacing a different frozen result."""

    target = Path(path)
    payload = canonical_json_bytes(manifest) + b"\n"
    if target.exists():
        if target.read_bytes() != payload:
            raise RfdetrPoseDerivedCampaignError(
                f"refusing to replace existing M0 manifest with different bytes: {target}"
            )
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def render_rfdetr_pose_derived_manifest(manifest: Mapping[str, Any]) -> str:
    """Render the campaign freeze state and scene counts."""

    inventory = manifest.get("inventory", {})
    lines = [
        f"RF-DETR pose-derived campaign: {manifest.get('freeze_state', 'unknown')}",
        f"Manifest digest: {manifest.get('manifest_digest', 'unknown')}",
        f"Eligible frames: {inventory.get('eligible_frame_count', 0)}",
        f"Eligible source groups: {inventory.get('eligible_source_group_count', 0)}",
        f"Eligible card poses: {inventory.get('eligible_pose_count', 0)}",
        f"Excluded scenes: {inventory.get('excluded_scene_count', 0)}",
    ]
    lines.extend(f"Minimum gate: {gap}" for gap in manifest.get("minimum_gaps", []))
    return "\n".join(lines)


__all__ = [
    "MINIMUM_CANDIDATE_FRAMES",
    "MINIMUM_CANDIDATE_GROUPS",
    "MINIMUM_CANDIDATE_POSES",
    "POSE_DERIVED_CAMPAIGN_ID",
    "POSE_DERIVED_MANIFEST_SCHEMA_VERSION",
    "RfdetrPoseDerivedCampaignError",
    "build_rfdetr_pose_derived_manifest",
    "render_rfdetr_pose_derived_manifest",
    "write_rfdetr_pose_derived_manifest",
]
