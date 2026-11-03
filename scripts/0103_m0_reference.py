"""Freeze the 0103 M0 development inputs and run Python reference inference."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
import zlib
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from cardevent.cache import prepare_inference_cache
from cardevent.dataset import DatasetSample, select_frame_indices
from cardevent.infer import load_checkpoint, predict_cached_samples
from PIL import Image
from table_evidence_analyzer.dinov3_inference import DinoV3IdentityClassifier
from table_evidence_analyzer.visible_cards import (
    LocalVisibleCardSegmentationProvider,
    VisibleCardRequest,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "data/intake/recordings/cardeventnet-IMG_0657/videos/video-cardeventnet-IMG_0657.mov"
)
OUTPUT = ROOT / ".runtime/0103-m0"
FRAME_TIMES_S = (2, 8, 12, 20, 40, 70)
EVENT_DECISION_S = 8.0
CROP_SPECS = {
    "face-up-card-frame-08s.ppm": (8, (900, 740, 1420, 1070)),
    "face-down-card-frame-40s.ppm": (40, (1200, 560, 1660, 810)),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_source_frames() -> list[dict[str, object]]:
    frame_dir = OUTPUT / "inputs/frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(SOURCE))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV cannot open {SOURCE}")
    orientation = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
    if orientation is not None:
        capture.set(orientation, 1)
    result = []
    try:
        for time_s in FRAME_TIMES_S:
            capture.set(cv2.CAP_PROP_POS_MSEC, time_s * 1000)
            ok, bgr = capture.read()
            if not ok or bgr is None:
                raise RuntimeError(f"No decoded frame at {time_s}s")
            path = frame_dir / f"frame-{time_s:02d}s.png"
            if not cv2.imwrite(str(path), bgr):
                raise RuntimeError(f"Could not write {path}")
            result.append(
                {
                    "path": path.relative_to(OUTPUT).as_posix(),
                    "timestamp_s": time_s,
                    "width": int(bgr.shape[1]),
                    "height": int(bgr.shape[0]),
                    "sha256": sha256(path),
                }
            )
    finally:
        capture.release()
    return result


def extract_event_window() -> tuple[Path, list[dict[str, object]]]:
    cache = prepare_inference_cache(
        SOURCE,
        cache_root=OUTPUT / "event-cache",
        cache_fps=10.0,
        size=224,
    )
    from cardevent.cache import load_cache_metadata

    metadata = load_cache_metadata(cache)
    indices = select_frame_indices(
        metadata.frame_timestamps_s,
        EVENT_DECISION_S,
        offsets_s=(-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0),
    )
    out = OUTPUT / "inputs/event-window"
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for order, index in enumerate(indices):
        source = cache / "frames" / f"{index:06d}.jpg"
        target = out / f"frame-{order:02d}.jpg"
        target.write_bytes(source.read_bytes())
        frames.append(
            {
                "path": target.relative_to(OUTPUT).as_posix(),
                "cache_index": index,
                "timestamp_s": metadata.frame_timestamps_s[index],
                "width": 224,
                "height": 224,
                "sha256": sha256(target),
            }
        )
    return cache, frames


def extract_identity_crops() -> list[dict[str, object]]:
    crops_dir = OUTPUT / "inputs/identity-crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for name, (timestamp, box) in CROP_SPECS.items():
        source = OUTPUT / "inputs/frames" / f"frame-{timestamp:02d}s.png"
        with Image.open(source) as image:
            crop = image.convert("RGB").crop(box)
            path = crops_dir / name
            crop.save(path, format="PPM")
            result.append(
                {
                    "path": path.relative_to(OUTPUT).as_posix(),
                    "source_frame": source.relative_to(OUTPUT).as_posix(),
                    "crop_box_xyxy": list(box),
                    "width": crop.width,
                    "height": crop.height,
                    "sha256": sha256(path),
                }
            )
    return result


def package_versions() -> dict[str, str | None]:
    versions = {}
    for name in (
        "torch",
        "torchvision",
        "transformers",
        "rfdetr",
        "Pillow",
        "opencv-python",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def raw_rfdetr_detections(
    detector: LocalVisibleCardSegmentationProvider,
    image_bytes: bytes,
    *,
    width: int,
    height: int,
) -> list[dict[str, object]]:
    """Keep threshold-free RF-DETR candidates and compressed full-resolution masks."""

    from io import BytesIO

    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    output = detector._detector.predict(
        image,
        threshold=0.0,
        shape=(432, 432),
        include_source_image=False,
    )
    raw_masks = output.mask
    if raw_masks is None:
        raise RuntimeError("RF-DETR did not return segmentation masks")
    return [
        {
            "class_id": int(class_id),
            "score": float(score),
            "box_xyxy": [float(value) for value in box],
            "mask_shape": [height, width],
            "mask_packbits_little_zlib_base64": base64.b64encode(
                zlib.compress(
                    np.packbits(mask.reshape(-1), bitorder="little").tobytes()
                )
            ).decode("ascii"),
        }
        for class_id, score, box, mask in zip(
            output.class_id, output.confidence, output.xyxy, raw_masks, strict=True
        )
    ]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source_digest = sha256(SOURCE)
    full_frames = extract_source_frames()
    event_cache, event_frames = extract_event_window()
    crops = extract_identity_crops()
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": package_versions(),
    }
    references: dict[str, object] = {"environment": environment}

    event_checkpoint = (
        ROOT
        / "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt"
    )
    event_model = load_checkpoint(event_checkpoint, device_override="cpu")
    event_sample = DatasetSample(
        source_video=SOURCE.name,
        cache_dir=event_cache,
        decision_time_s=EVENT_DECISION_S,
        label=-1.0,
        label_state="ignore",
    )
    event_started = time.monotonic()
    event_prediction = predict_cached_samples(
        event_model.model,
        [event_sample],
        offsets_s=event_model.config.input.clip_offsets_s,
        batch_size=1,
        device=event_model.device,
    )[0]
    references["cardeventnet"] = {
        "status": "ok",
        "device": str(event_model.device),
        "checkpoint_sha256": sha256(event_checkpoint),
        "decision_time_s": event_prediction.time_s,
        "logit": event_prediction.logit,
        "probability": event_prediction.probability,
        "threshold": 0.4271905720233917,
        "over_threshold": event_prediction.probability >= 0.4271905720233917,
        "inference_ms": round((time.monotonic() - event_started) * 1000, 3),
    }

    detector = LocalVisibleCardSegmentationProvider(
        ROOT / ".runtime/rfdetr-segmentation-0092-m4/bundle", device="cpu"
    )
    references["rfdetr"] = {
        "bundle_digest": detector.bundle.manifest["bundle_digest"],
        "frames": {},
    }
    for frame in full_frames:
        path = OUTPUT / str(frame["path"])
        image_bytes = path.read_bytes()
        request = VisibleCardRequest(
            package_id="epic-0103-m0",
            frame_part_name=path.stem,
            target_offset_ms=0,
            image_bytes=image_bytes,
            width=int(frame["width"]),
            height=int(frame["height"]),
            image_mime_type="image/png",
            provider=detector.name,
        )
        frame_started = time.monotonic()
        raw_detections = raw_rfdetr_detections(
            detector,
            image_bytes,
            width=int(frame["width"]),
            height=int(frame["height"]),
        )
        result = detector.propose(request)
        references["rfdetr"]["frames"][path.name] = {
            **result.to_mapping(),
            "threshold_free_candidates": raw_detections,
            "inference_wall_ms": round((time.monotonic() - frame_started) * 1000, 3),
        }

    identity = DinoV3IdentityClassifier(
        ROOT / ".runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle",
        device="cpu",
    )
    references["dinov3"] = {"bundle_identity": identity.bundle_identity, "crops": {}}
    for crop in crops:
        path = OUTPUT / str(crop["path"])
        crop_started = time.monotonic()
        result = identity.classify_ppm(path.read_bytes())
        result_mapping = asdict(result)
        result_mapping["candidates"] = [
            candidate.model_dump(mode="json") for candidate in result.candidates
        ]
        references["dinov3"]["crops"][path.name] = {
            **result_mapping,
            "inference_wall_ms": round((time.monotonic() - crop_started) * 1000, 3),
        }

    manifest = {
        "schema_version": "epic-0103-m0-inputs/v1",
        "source": {
            "recording_id": "cardeventnet-IMG_0657",
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": source_digest,
            "permission": "project_use",
            "duration_s": 89.42,
            "input_decision": "unreviewed development execution input",
        },
        "frames": full_frames,
        "identity_crops": crops,
        "event_window": {
            "decision_time_s": EVENT_DECISION_S,
            "cache_fps": 10.0,
            "frame_size": 224,
            "preprocessing": "full_frame_letterbox_v1",
            "offsets_s": [-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0],
            "frames": event_frames,
        },
        "environment": environment,
    }
    (OUTPUT / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (OUTPUT / "python-references.json").write_text(
        json.dumps(references, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "inputs": str(OUTPUT / "inputs.json"),
                "references": str(OUTPUT / "python-references.json"),
                "elapsed_s": round(time.monotonic() - started, 3),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
