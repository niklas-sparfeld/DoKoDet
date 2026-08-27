"""Deterministic derived intake files for accepted training recordings."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from dokodetector_backend.recording_contract import (
    DevicePredictions,
    RecordingManifest,
)

DATASET_MANIFEST_SCHEMA_VERSION = "cardevent-video-metadata/v1"
REVIEW_QUEUE_FORMAT = "cardevent-review-queue-v1"


def build_dataset_record_yaml(manifest: RecordingManifest) -> bytes:
    """Build an intentionally incomplete, operator-facing dataset record."""

    values: dict[str, Any] = {
        "video_id": manifest.video_id,
        "file_name": manifest.video.name,
        "content_type": None,
        "session_id": manifest.session_id,
        "game_id": None,
        "recording_date": manifest.started_at_utc,
        "device": manifest.client.device_model,
        "camera": manifest.camera.position,
        "resolution": f"{manifest.video.width}x{manifest.video.height}",
        "frame_rate": manifest.video.frame_rate,
        "duration_s": manifest.duration_s,
        "orientation": manifest.camera.orientation,
        "camera_view": None,
        "camera_motion": None,
        "camera_framing": None,
        "table_setup": None,
        "lighting": [],
        "background": None,
        "card_deck": None,
        "scenario_tags": [],
        "known_limitations": [],
        "source": manifest.source,
        "annotation_version": None,
        "source_permission": manifest.source_permission,
        "notes": (
            "Draft generated from cardevent-recording/v1. Complete the video-wide annotation "
            "metadata before dataset import."
        ),
    }
    lines = [f"schema_version: {DATASET_MANIFEST_SCHEMA_VERSION}", "videos:", "  -"]
    for key, value in values.items():
        lines[-1] += f" {key}: {_yaml_scalar(value)}" if key == "video_id" else ""
        if key != "video_id":
            lines.append(f"    {key}: {_yaml_scalar(value)}")
    lines[2] = f"  - video_id: {_yaml_scalar(values['video_id'])}"
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_candidate_review_queue(
    manifest: RecordingManifest,
    predictions: DevicePredictions,
    *,
    predictions_sha256: str,
) -> bytes:
    """Build a deterministic candidate-only queue from device event proposals."""

    duration = manifest.duration_s
    proposals = [
        {
            "id": _proposal_id(manifest.recording_id, manifest.video.name, index, proposal),
            "video": manifest.video.name,
            "timestamp_s": proposal.time_s,
            "category": "unmatched_model_candidate",
            "score": proposal.probability,
            "nearest_annotation": None,
            "distance_s": None,
            "event_type": None,
            "preview": {
                "kind": "timestamp_window",
                "source_video": manifest.video.name,
                "start_s": max(0.0, proposal.time_s - 1.0),
                "end_s": min(duration, proposal.time_s + 1.0),
            },
            "status": "unreviewed",
            "outcome": "unreviewed",
        }
        for index, proposal in enumerate(predictions.event_proposals)
    ]
    probability_stream = {
        "duration_s": duration,
        "probability_times_s": [sample.time_s for sample in predictions.probabilities],
        "probabilities": [sample.probability for sample in predictions.probabilities],
        "ground_truth_events": [],
        "predicted_events": [
            proposal.model_dump(mode="json") for proposal in predictions.event_proposals
        ],
        "threshold": predictions.decoder.threshold,
    }
    payload: dict[str, Any] = {
        "format": REVIEW_QUEUE_FORMAT,
        "checkpoint": f"recording:{manifest.recording_id}",
        "split": "",
        "partition": "unassigned",
        "model_version": f"{predictions.model.name}:{predictions.model.version}",
        "comparison_model_version": None,
        "threshold": predictions.decoder.threshold,
        "merge_window_s": predictions.decoder.minimum_event_gap_s,
        "event_match_tolerance_s": 0.0,
        "peak_confirmation_s": predictions.decoder.peak_confirmation_s,
        "low_confidence_margin": 0.0,
        "empty_count_per_video": 0,
        "empty_exclusion_s": predictions.decoder.minimum_event_gap_s,
        "preview_half_window_s": 1.0,
        "selection_seed": 0,
        "probability_streams": {manifest.video.name: probability_stream},
        "items": proposals,
        "reviewer": None,
        "provenance": "candidate_only",
        "recording_id": manifest.recording_id,
        "source_predictions_sha256": predictions_sha256,
    }
    return (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _proposal_id(recording_id: str, video_name: str, index: int, proposal: Any) -> str:
    seed = {
        "recording_id": recording_id,
        "video": video_name,
        "index": index,
        "time_s": proposal.time_s,
        "emitted_at_s": proposal.emitted_at_s,
        "probability": proposal.probability,
    }
    return hashlib.sha256(
        json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "[]" if not value else json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


__all__ = [
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "REVIEW_QUEUE_FORMAT",
    "build_candidate_review_queue",
    "build_dataset_record_yaml",
]
