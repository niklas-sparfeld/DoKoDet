"""Export and compare the frozen CardEventNet model for Epic 0103 M3."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = (
    ROOT
    / "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt"
)
INPUTS = ROOT / ".runtime/0103-m0"
MANIFEST = ROOT / "docs/reports/0103-M0_Input_Manifest.json"
REFERENCES = ROOT / "docs/reports/0103-M0_Python_References.json"
THRESHOLD_FILE = (
    ROOT
    / "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/threshold.json"
)
OUTPUT = ROOT / ".runtime/0103-m3/cardeventnet.mlpackage"
REPORT = ROOT / ".runtime/0103-m3/export-report.json"
EXPECTED_CHECKPOINT_SHA256 = (
    "258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4"
)
EXPECTED_MANIFEST_SHA256 = (
    "dbcba9d8ff7aa32b438c70572eec76047b154b8796db030acad2a950414355e5"
)
EXPECTED_REFERENCES_SHA256 = (
    "8a9b48dce3a1e108a75a496008cdede140a11a339fa9114279d47819a0375423"
)
ATOL = 1e-4
RTOL = 1e-4


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(
        candidate for candidate in path.rglob("*") if candidate.is_file()
    ):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def write_report(report: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    sys.path.insert(0, str(ROOT / "card_event_net/src"))
    versions = {}
    for name in ("coremltools", "torch", "torchvision", "numpy", "opencv-python"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None

    report: dict[str, Any] = {
        "schema_version": "epic-0103-m3-cardeventnet-export-attempt/v1",
        "status": "failed",
        "platform": platform.platform(),
        "python": sys.version,
        "packages": versions,
        "checkpoint": CHECKPOINT.relative_to(ROOT).as_posix(),
        "expected_checkpoint_sha256": EXPECTED_CHECKPOINT_SHA256,
        "input_manifest": MANIFEST.relative_to(ROOT).as_posix(),
        "expected_input_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "python_references": REFERENCES.relative_to(ROOT).as_posix(),
        "expected_python_references_sha256": EXPECTED_REFERENCES_SHA256,
        "output_package": OUTPUT.relative_to(ROOT).as_posix(),
        "package_digest": None,
        "package_size_bytes": None,
        "minimum_deployment_target": "iOS15",
        "compute_precision": "float32",
        "input_shape": [1, 8, 3, 224, 224],
        "input_contract": "8 causal RGB cache frames, 224x224, full_frame_letterbox_v1, ImageNet normalization",
        "atol": ATOL,
        "rtol": RTOL,
        "parity": {},
    }
    try:
        if versions["coremltools"] != "9.0":
            raise RuntimeError(
                "install coremltools==9.0 in the frozen M0 Python environment"
            )
        if sha256(CHECKPOINT) != EXPECTED_CHECKPOINT_SHA256:
            raise RuntimeError(
                "CardEventNet checkpoint differs from frozen M0 artifact"
            )
        if sha256(MANIFEST) != EXPECTED_MANIFEST_SHA256:
            raise RuntimeError("M0 input manifest differs from the frozen report")
        if sha256(REFERENCES) != EXPECTED_REFERENCES_SHA256:
            raise RuntimeError("M0 Python references differ from the frozen report")

        import coremltools as ct
        import numpy as np
        import torch
        from cardevent.cache import require_cache_preprocessing
        from cardevent.dataset import (
            CausalClipDataset,
            DatasetSample,
            select_frame_indices,
        )
        from cardevent.events import ProbabilitySample, probabilities_to_events
        from cardevent.export_coreml import export_checkpoint_to_coreml
        from cardevent.infer import load_checkpoint
        from cardevent.transforms import ClipTransform
        from table_evidence_analyzer.model_parity import compare_score_vectors

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        event_input = manifest["event_window"]
        references = json.loads(REFERENCES.read_text(encoding="utf-8"))
        frozen_reference = references["cardeventnet"]
        threshold_config = json.loads(THRESHOLD_FILE.read_text(encoding="utf-8"))
        threshold = float(threshold_config["threshold"])
        merge_window_s = float(threshold_config["merge_window_s"])
        peak_confirmation_s = float(
            threshold_config["validation_metrics"]["peak_confirmation_s"]
        )

        loaded = load_checkpoint(CHECKPOINT, device_override="cpu")
        offsets = list(loaded.config.input.clip_offsets_s)
        if offsets != event_input["offsets_s"]:
            raise RuntimeError(
                "checkpoint temporal offsets differ from the frozen M0 window"
            )
        if loaded.config.input.preprocessing != event_input["preprocessing"]:
            raise RuntimeError(
                "checkpoint preprocessing differs from the frozen M0 contract"
            )
        cache_dir = INPUTS / "event-cache/video-cardeventnet-IMG_0657"
        cache_metadata = require_cache_preprocessing(
            cache_dir, loaded.config.input.preprocessing
        )
        indices = select_frame_indices(
            cache_metadata.frame_timestamps_s,
            float(event_input["decision_time_s"]),
            offsets_s=offsets,
        )
        expected_indices = [frame["cache_index"] for frame in event_input["frames"]]
        if list(indices) != expected_indices:
            raise RuntimeError(
                "selected cache frame indices differ from frozen M0 window"
            )
        for frame in event_input["frames"]:
            frame_path = INPUTS / frame["path"]
            if sha256(frame_path) != frame["sha256"]:
                raise RuntimeError(
                    f"frozen event input digest mismatch: {frame_path.name}"
                )

        sample = DatasetSample(
            source_video=cache_metadata.source_video,
            cache_dir=cache_dir,
            decision_time_s=float(event_input["decision_time_s"]),
            label=-1.0,
            label_state="ignore",
        )
        raw_clip, _label = CausalClipDataset([sample], offsets_s=offsets)[0]
        clip = ClipTransform(training=False)(raw_clip).unsqueeze(0).contiguous()
        if tuple(clip.shape) != (1, 8, 3, 224, 224):
            raise RuntimeError(f"unexpected model input shape: {tuple(clip.shape)}")
        expected_frame_tensor_digest = hashlib.sha256(
            np.ascontiguousarray(raw_clip.numpy()).tobytes()
        ).hexdigest()
        report.update(
            {
                "checkpoint_sha256": sha256(CHECKPOINT),
                "checkpoint_temporal_head": loaded.config.model.temporal_head,
                "checkpoint_offsets_s": offsets,
                "checkpoint_preprocessing": loaded.config.input.preprocessing,
                "decision_time_s": sample.decision_time_s,
                "frame_indices": indices,
                "frame_timestamps_s": [
                    frame["timestamp_s"] for frame in event_input["frames"]
                ],
                "frame_sha256": [frame["sha256"] for frame in event_input["frames"]],
                "raw_rgb_tensor_sha256": expected_frame_tensor_digest,
                "normalization": "float32 RGB divided by 255, then ImageNet mean/std",
                "threshold": threshold,
                "peak_confirmation_s": peak_confirmation_s,
                "min_event_gap_s": merge_window_s,
            }
        )

        with torch.inference_mode():
            python_logit = float(loaded.model(clip).reshape(-1)[0].cpu())
        python_probability = float(torch.sigmoid(torch.tensor(python_logit)))
        report["python_output"] = {
            "logit": python_logit,
            "probability": python_probability,
            "over_threshold": python_probability >= threshold,
        }
        reference_logit = float(frozen_reference["logit"])
        reference_probability = float(frozen_reference["probability"])
        report["python_reference_parity"] = {
            "logit": compare_score_vectors(
                [reference_logit], [python_logit], atol=ATOL, rtol=RTOL
            ),
            "probability": compare_score_vectors(
                [reference_probability], [python_probability], atol=ATOL, rtol=RTOL
            ),
        }

        # The exporter's built-in random-input check is not the frozen temporal sequence.
        # Compare the produced package against the actual M0 clip below.
        export_result = export_checkpoint_to_coreml(
            CHECKPOINT, OUTPUT, verify_parity=False
        )
        report["exporter_random_parity"] = (
            "skipped; frozen M0 temporal clip is used below"
        )
        coreml_model = ct.models.MLModel(str(export_result.output_path))
        coreml_output = coreml_model.predict({"clips": clip.numpy()})
        coreml_logit = float(np.asarray(coreml_output["logit"]).reshape(-1)[0])
        coreml_probability = float(1.0 / (1.0 + np.exp(-coreml_logit)))
        report["coreml_output"] = {
            "logit": coreml_logit,
            "probability": coreml_probability,
            "over_threshold": coreml_probability >= threshold,
        }
        report["parity"] = {
            "logit": compare_score_vectors(
                [python_logit], [coreml_logit], atol=ATOL, rtol=RTOL
            ),
            "probability": compare_score_vectors(
                [python_probability], [coreml_probability], atol=ATOL, rtol=RTOL
            ),
            "threshold_changed": (python_probability >= threshold)
            != (coreml_probability >= threshold),
        }
        python_events = probabilities_to_events(
            [
                ProbabilitySample(
                    sample.decision_time_s, python_probability, python_logit
                )
            ],
            threshold,
            peak_confirmation_s=peak_confirmation_s,
            min_event_gap_s=merge_window_s,
        )
        coreml_events = probabilities_to_events(
            [
                ProbabilitySample(
                    sample.decision_time_s, coreml_probability, coreml_logit
                )
            ],
            threshold,
            peak_confirmation_s=peak_confirmation_s,
            min_event_gap_s=merge_window_s,
        )
        report["decoded_events"] = {
            "python": [event.to_mapping() for event in python_events],
            "coreml": [event.to_mapping() for event in coreml_events],
            "changed": [event.to_mapping() for event in python_events]
            != [event.to_mapping() for event in coreml_events],
            "timing_offset_s": None,
            "timing_offset_note": "No event is emitted by either model for this frozen decision point.",
        }
        report["package_digest"] = package_sha256(OUTPUT)
        report["package_size_bytes"] = sum(
            item.stat().st_size for item in OUTPUT.rglob("*") if item.is_file()
        )
        report["status"] = "complete"
        write_report(report)
        return 0
    except Exception as exc:  # noqa: BLE001  # Keep a report for every bounded-attempt failure.
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        if OUTPUT.exists():
            report["package_digest"] = package_sha256(OUTPUT)
            report["package_size_bytes"] = sum(
                item.stat().st_size for item in OUTPUT.rglob("*") if item.is_file()
            )
        write_report(report)
        print(report["error"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
