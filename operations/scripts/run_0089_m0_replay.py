#!/usr/bin/env python3
"""Replay the frozen 0088 development frames through the 0089 diagnostic stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "operations/src"), str(ROOT / "table_evidence_analyzer/src")]

from table_evidence_analyzer.dinov3_inference import DinoV3IdentityClassifier  # noqa: E402
from table_evidence_analyzer.visible_cards import (  # noqa: E402
    LocalVisibleCardSegmentationProvider,
    VisibleCardRequest,
)

from doko_operations.derived_view import (  # noqa: E402
    ExactEventRequest,
    FFmpegFrameResolver,
    PredictedVisibleRegionGeometry,
    resolve_visible_region_crop,
)
from doko_operations.pipeline_data import RecordingVideoSource  # noqa: E402
from doko_operations.proposed_card_scene_processor import (  # noqa: E402
    build_proposed_card_scenes,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def source_for(recording_id: str) -> tuple[RecordingVideoSource, Path]:
    intake = ROOT / "data/intake/recordings" / recording_id
    state = read_json(
        ROOT / "data/operations/pipeline-references" / recording_id / "visible_cards/state.json"
    )
    revision_id = state["selected_completed_revision_id"]
    revision = ROOT / "data/operations/pipeline/revisions" / revision_id
    source = read_json(revision / "manifest.json")["source"]
    path = (ROOT / source["relative_path"]).resolve()
    if not path.is_relative_to(intake.resolve()):
        raise ValueError(f"unsafe video path for {recording_id}")
    accepted_source = RecordingVideoSource.from_mapping(source)
    if (
        path.stat().st_size != accepted_source.byte_length
        or digest(path.read_bytes()) != accepted_source.video_sha256
    ):
        raise ValueError(f"source length differs for {recording_id}")
    return accepted_source, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root", type=Path, required=True, help="checkout with frozen .runtime bundles"
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".runtime/0089-m0-replay")
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    args = parser.parse_args()
    artifact_root = args.artifact_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    upstream = artifact_root / ".runtime/dinov3-identity-0088"
    detector_path = artifact_root / ".runtime/rfdetr-segmentation-0087-m3-training/bundle"
    primary_path = upstream / "m12-final-lock/m6-candidate-bundle"
    control_path = upstream / "m12-final-lock/candidate-bundle"
    detector = LocalVisibleCardSegmentationProvider(detector_path, device=args.device)
    primary = DinoV3IdentityClassifier(primary_path, device="cpu")
    control = DinoV3IdentityClassifier(control_path, device="cpu")
    detector_digest = detector.bundle.manifest["bundle_digest"]
    if detector_digest != "018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9":
        raise ValueError("detector bundle differs from the frozen 0087 decision")
    if (
        primary.bundle.manifest["bundle_digest"]
        != "a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79"
    ):
        raise ValueError("primary identity bundle differs from the frozen 0088 decision")
    if (
        control.bundle.manifest["bundle_digest"]
        != "e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87"
    ):
        raise ValueError("control identity bundle differs from the frozen 0088 decision")

    automatic = read_json(upstream / "automatic-development/manifest.json")
    if automatic.get("provider_bundle_sha256") != detector_digest:
        raise ValueError("0088 development view names another detector bundle")
    rows = automatic["rows"]
    identities: dict[str, dict[str, Any]] = {}
    reference_events: dict[tuple[str, str], str] = {}
    for recording_id in sorted({row["recording_id"] for row in rows}):
        state = read_json(
            ROOT / "data/operations/pipeline-references" / recording_id / "visible_cards/state.json"
        )
        revision_id = state["selected_completed_revision_id"]
        content = read_json(
            ROOT / "data/operations/pipeline/revisions" / revision_id / "content.json"
        )
        for outcome in content["outcomes"]:
            identity = outcome.get("frame_identity")
            event_id = outcome.get("event_id")
            if (
                isinstance(identity, dict)
                and isinstance(identity.get("image_sha256"), str)
                and isinstance(event_id, str)
            ):
                reference_events[(recording_id, identity["image_sha256"])] = event_id
    for row in rows:
        identity = row["frame_identity"]
        key = identity["image_sha256"]
        event_id = reference_events.get((row["recording_id"], key))
        if event_id is None:
            raise ValueError(f"no selected human event identity for {row['recording_id']} {key}")
        identities.setdefault(
            key,
            {
                "recording_id": row["recording_id"],
                "frame_identity": identity,
                "event_id": event_id,
                "partition": row["partition"],
            },
        )
    if len(identities) != 130 or "cardeventnet-IMG_0659" in {
        value["recording_id"] for value in identities.values()
    }:
        raise ValueError("development scope changed or includes the sealed final-test recording")

    # Resolve exact source frames. The frame index and presentation timestamp come from the
    # immutable 0088 M1 manifest; frame bytes are checked against its image digest.
    resolver = FFmpegFrameResolver()
    frames: dict[str, Any] = {}
    by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, item in sorted(identities.items()):
        source, video_path = source_for(item["recording_id"])
        identity = item["frame_identity"]
        frame = resolver.resolve(
            ExactEventRequest(source, identity["requested_time_us"], identity["output_encoding"]),
            video_path,
        )
        if frame.identity_mapping() != identity:
            raise ValueError(f"exact-event frame identity changed: {item['recording_id']} {key}")
        if digest(frame.image_bytes) != identity["image_sha256"]:
            raise ValueError(f"exact-event frame bytes changed: {item['recording_id']} {key}")
        item["frame"] = frame
        frames[key] = frame
        by_recording[item["recording_id"]].append(item)

    current_run_id = "0089-m0-" + detector_digest[:12]
    proposal_crops: list[dict[str, Any]] = []
    local_results: dict[str, dict[str, Any]] = {}
    provider_latencies: list[float] = []
    for recording_id, recording_frames in sorted(by_recording.items()):
        converted_frames = []
        for item in sorted(
            recording_frames, key=lambda x: x["frame_identity"]["requested_time_us"]
        ):
            frame = item["frame"]
            request = VisibleCardRequest(
                package_id=recording_id,
                frame_part_name=f"frame-{item['frame_identity']['image_sha256'][:16]}",
                target_offset_ms=item["frame_identity"]["requested_time_us"] // 1000,
                image_bytes=frame.image_bytes,
                width=frame.width,
                height=frame.height,
                provider=detector.name,
                image_mime_type=frame.content_type,
            )
            started = time.perf_counter()
            result = detector.propose(request)
            elapsed = (time.perf_counter() - started) * 1000
            provider_latencies.append(elapsed)
            if result.status != "ok":
                raise RuntimeError(f"detector unavailable for {recording_id}: {result.error}")
            frame_id = item["event_id"] or f"frame-{item['frame_identity']['requested_time_us']}"
            predictions = []
            for proposal_index, proposal in enumerate(result.proposals):
                polys = proposal.polygons or (proposal.polygon,)
                predictions.append(
                    {
                        "candidate_id": f"{current_run_id}-{frame_id}-card-{proposal_index:04d}",
                        "confidence": 1.0,
                        "provider": detector.name,
                        "polygons": [
                            [
                                [point.x / 1000 * frame.width, point.y / 1000 * frame.height]
                                for point in poly
                            ]
                            for poly in polys
                        ],
                    }
                )
                normalized_polygons = [[point.to_mapping() for point in poly] for poly in polys]
                crop_result = resolve_visible_region_crop(
                    frame,
                    PredictedVisibleRegionGeometry(
                        polygons=tuple(
                            tuple((point.x, point.y) for point in poly) for poly in polys
                        ),
                    ),
                    crop_policy="predicted_visible_region",
                    output_encoding="ppm",
                    identity_usable=True,
                )
                if crop_result.status != "usable" or crop_result.image_bytes is None:
                    proposal_crops.append(
                        {
                            "recording_id": recording_id,
                            "frame_id": frame_id,
                            "proposal_index": proposal_index,
                            "crop_status": crop_result.status,
                            "crop_failure_tags": list(crop_result.failure_tags),
                        }
                    )
                    continue
                crop_path = output_dir / "crops" / f"{digest(crop_result.image_bytes)}.ppm"
                crop_path.parent.mkdir(parents=True, exist_ok=True)
                crop_path.write_bytes(crop_result.image_bytes)
                m6_result = primary.classify_ppm(crop_result.image_bytes)
                m3_result = control.classify_ppm(crop_result.image_bytes)
                m6 = m6_result.raw_response
                m3 = m3_result.raw_response
                proposal_crops.append(
                    {
                        "recording_id": recording_id,
                        "frame_id": frame_id,
                        "frame_identity": item["frame_identity"],
                        "proposal_index": proposal_index,
                        "predicted_polygons": normalized_polygons,
                        "crop_policy": "predicted_visible_region",
                        "crop_sha256": digest(crop_result.image_bytes),
                        "crop_path": str(crop_path.relative_to(output_dir)),
                        "m6": {
                            "bundle_digest": m6["bundle_digest"],
                            "top1": m6["ranked_targets"][0],
                            "confidence": m6["ranked_probabilities"][0],
                            "latency_ms": m6_result.latency_ms,
                        },
                        "m3": {
                            "bundle_digest": m3["bundle_digest"],
                            "top1": m3["ranked_targets"][0],
                            "confidence": m3["ranked_probabilities"][0],
                            "latency_ms": m3_result.latency_ms,
                        },
                        "identity_requires_human_review": True,
                    }
                )
            converted_frames.append(
                {
                    "frame_id": frame_id,
                    "source_frame_digest": frame.image_sha256,
                    "frame_index": frame.frame_index,
                    "timestamp_us": frame.requested_time_us,
                    "width": frame.width,
                    "height": frame.height,
                    "source_transform": frame.transform_version,
                    "predictions": predictions,
                    "outcome_status": "detected" if predictions else "empty",
                }
            )
            source_frame_path = output_dir / "frames" / f"{frame.image_sha256}.jpg"
            source_frame_path.parent.mkdir(parents=True, exist_ok=True)
            source_frame_path.write_bytes(frame.image_bytes)
            print(f"inferred {recording_id} {frame_id}: {len(predictions)} proposals", flush=True)
        local_results[recording_id] = {
            "recording_id": recording_id,
            "source_revision": current_run_id,
            "frames": converted_frames,
            "unresolvable_frames": [],
        }

    # Run the current recording-wide calibration and pose fitter on each fresh detector output.
    proposals_by_recording = {}
    for recording_id, result in sorted(local_results.items()):
        detector_revision_digest = digest(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        )
        replay = build_proposed_card_scenes(
            result,
            detector_revision_id=current_run_id,
            detector_revision_digest=detector_revision_digest,
        )
        proposals_by_recording[recording_id] = replay.to_mapping()
        print(f"fit {recording_id}: {replay.status}", flush=True)

    output = {
        "schema_version": "0089-m0-replay/v1",
        "detector_bundle_digest": detector_digest,
        "primary_identity_bundle_digest": primary.bundle.manifest["bundle_digest"],
        "control_identity_bundle_digest": control.bundle.manifest["bundle_digest"],
        "detector": {
            "provider": detector.name,
            "version": detector.version,
            "device": args.device,
            "confidence_threshold": detector.confidence_threshold,
            "frame_count": len(identities),
            "proposal_count": sum(
                len(frame["predictions"]) for r in local_results.values() for frame in r["frames"]
            ),
            "latency_ms": {
                "median": sorted(provider_latencies)[len(provider_latencies) // 2],
                "p95": sorted(provider_latencies)[int((len(provider_latencies) - 1) * 0.95)],
                "total": round(sum(provider_latencies), 3),
            },
        },
        "scope": {
            "recordings": sorted(by_recording),
            "partition_counts": {
                partition: sum(item["partition"] == partition for item in identities.values())
                for partition in sorted({item["partition"] for item in identities.values()})
            },
            "sealed_final_test_used": False,
            "input_manifest_sha256": digest(
                (upstream / "automatic-development/manifest.json").read_bytes()
            ),
            "input_manifest_path": str(upstream / "automatic-development/manifest.json"),
        },
        "identity_policy": {
            "crop_policy": "predicted_visible_region",
            "output_encoding": "ppm",
            "preprocessing": (
                "0088 M15 224-pixel RGB P6 PPM, aspect-preserving Lanczos, "
                "centered (128,128,128) letterbox"
            ),
            "review_threshold": 0.9,
            "review_threshold_use": "diagnostic routing only",
            "auto_accept": False,
            "all_predictions_require_human_review": True,
        },
        "identity_crops": proposal_crops,
        "pose_replays": proposals_by_recording,
    }
    write_json(output_dir / "report.json", output)
    print(f"wrote {output_dir / 'report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
