"""Export and compare the frozen DINOv3 identity model for Epic 0103 M2."""

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
BUNDLE = ROOT / ".runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle"
INPUTS = ROOT / ".runtime/0103-m0/inputs/identity-crops"
REFERENCES = ROOT / "docs/reports/0103-M0_Python_References.json"
OUTPUT = ROOT / ".runtime/0103-m2/dinov3-identity.mlpackage"
REPORT = ROOT / ".runtime/0103-m2/export-report.json"
EXPECTED_BUNDLE_SHA256 = (
    "a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79"
)
EXPECTED_ENCODER_SHA256 = (
    "6fc86f473ceec4c8612c1c7341d878e3ecf96b1d182dbae7d47b02cf83a5fa24"
)
EXPECTED_HEAD_SHA256 = (
    "baeae9d97b971cdfa60fa3f8c92e62c47cb5d7eb7074478322abda6ffca19979"
)
EXPECTED_INPUT_SHAPE = (1, 3, 224, 224)
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


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_report(report: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    sys.path.insert(0, str(ROOT / "table_evidence_analyzer/src"))
    versions = {
        name: package_version(name)
        for name in (
            "coremltools",
            "torch",
            "torchvision",
            "transformers",
            "safetensors",
        )
    }
    report: dict[str, Any] = {
        "schema_version": "epic-0103-m2-dinov3-export-attempt/v1",
        "status": "failed",
        "platform": platform.platform(),
        "python": sys.version,
        "packages": versions,
        "bundle": BUNDLE.relative_to(ROOT).as_posix(),
        "expected_bundle_sha256": EXPECTED_BUNDLE_SHA256,
        "encoder_sha256": EXPECTED_ENCODER_SHA256,
        "head_sha256": EXPECTED_HEAD_SHA256,
        "input_shape": list(EXPECTED_INPUT_SHAPE),
        "input_contract": "RGB float32, 224x224, aspect-ratio-preserving Lanczos letterbox, ImageNet normalization",
        "feature_layout": "CLS token concatenated with mean spatial patch tokens",
        "class_count": 25,
        "minimum_deployment_target": "iOS17",
        "compute_precision": "float32",
        "calibration_temperature": None,
        "output_package": OUTPUT.relative_to(ROOT).as_posix(),
        "package_digest": None,
        "parity": {},
    }
    return_code = 1
    try:
        if versions["coremltools"] != "9.0":
            raise RuntimeError(
                "install coremltools==9.0 before running the export attempt"
            )

        import coremltools as ct
        import numpy as np
        import torch
        from table_evidence_analyzer.dinov3_bundle import load_dinov3_identity_bundle
        from table_evidence_analyzer.dinov3_inference import (
            _feature_output,
            _load_encoder,
            _load_encoder_state,
            _load_head,
        )
        from table_evidence_analyzer.local_identity import transform_identity_crop
        from table_evidence_analyzer.model_parity import compare_score_vectors
        from torch import Tensor, nn

        bundle = load_dinov3_identity_bundle(BUNDLE)
        report["bundle_sha256"] = bundle.bundle_digest
        report["bundle_files"] = {
            "encoder_state": sha256(bundle.encoder_state_path),
            "head": sha256(bundle.head_path),
        }
        if bundle.bundle_digest != EXPECTED_BUNDLE_SHA256:
            raise RuntimeError("DINOv3 bundle digest differs from frozen M0 artifact")
        if report["bundle_files"]["encoder_state"] != EXPECTED_ENCODER_SHA256:
            raise RuntimeError("DINOv3 encoder state differs from frozen M0 artifact")
        if report["bundle_files"]["head"] != EXPECTED_HEAD_SHA256:
            raise RuntimeError("DINOv3 identity head differs from frozen M0 artifact")

        calibration = bundle.manifest["calibration"]
        report["calibration_temperature"] = calibration["temperature"]
        report["calibration_sha256"] = calibration["sha256"]
        target_map = json.loads(
            (BUNDLE / bundle.manifest["target_map_file"]).read_text()
        )
        targets = [target_map["class_map"][str(index)] for index in range(25)]
        report["target_map"] = targets
        references = json.loads(REFERENCES.read_text(encoding="utf-8"))["dinov3"][
            "crops"
        ]

        encoder = _load_encoder(bundle)
        encoder = _load_encoder_state(torch, bundle, encoder).eval()
        head = _load_head(torch, bundle).eval()

        class IdentityLogits(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.encoder = encoder
                self.head = head

            def forward(self, pixel_values: Tensor) -> Tensor:
                encoded = self.encoder(pixel_values=pixel_values)
                features = _feature_output(
                    encoded,
                    self.encoder,
                    bundle.identity.recipe["feature_layout"],
                    bundle.identity.input_size,
                )
                return self.head(features)

        model = IdentityLogits().eval()
        transformed_inputs: dict[str, Any] = {}
        for name, reference in references.items():
            crop_path = INPUTS / name
            crop = crop_path.read_bytes()
            transformed = transform_identity_crop(crop, input_size=224)
            if transformed.shape != (3, 224, 224):
                raise RuntimeError(
                    f"unexpected transformed crop shape: {transformed.shape}"
                )
            if (
                transformed.tensor_digest
                != reference["raw_response"]["input_tensor_digest"]
            ):
                raise RuntimeError(
                    f"transformed crop digest differs from M0 reference: {name}"
                )
            tensor = transformed.to_torch().unsqueeze(0)
            transformed_inputs[name] = tensor
            if tuple(tensor.shape) != EXPECTED_INPUT_SHAPE:
                raise RuntimeError(f"unexpected input tensor shape for {name}")

        example = next(iter(transformed_inputs.values()))
        with torch.inference_mode():
            torch_logits = {
                name: model(tensor).cpu().numpy()[0]
                for name, tensor in transformed_inputs.items()
            }
        report["python_output_shapes"] = [
            list(value.shape) for value in torch_logits.values()
        ]
        report["python_reference"] = {}
        for name, output in torch_logits.items():
            frozen_logits = references[name]["raw_response"]["logits"]
            report["python_reference"][name] = compare_score_vectors(
                frozen_logits,
                output.tolist(),
                atol=ATOL,
                rtol=RTOL,
            )
        traced = torch.jit.trace(model, example, strict=False, check_trace=False)
        coreml_model = ct.convert(
            traced,
            source="pytorch",
            inputs=[
                ct.TensorType(
                    name="pixel_values", shape=EXPECTED_INPUT_SHAPE, dtype=np.float32
                )
            ],
            outputs=[ct.TensorType(name="logits")],
            minimum_deployment_target=ct.target.iOS17,
            compute_precision=ct.precision.FLOAT32,
        )
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        coreml_model.save(str(OUTPUT))
        report["package_digest"] = package_sha256(OUTPUT)
        report["package_bytes"] = sum(
            path.stat().st_size for path in OUTPUT.rglob("*") if path.is_file()
        )

        coreml = ct.models.MLModel(str(OUTPUT), compute_units=ct.ComputeUnit.CPU_ONLY)
        for name, tensor in transformed_inputs.items():
            coreml_logits = np.asarray(
                coreml.predict({"pixel_values": tensor.numpy()})["logits"]
            ).reshape(-1)
            python_logits = torch_logits[name]
            python_probs = torch.softmax(torch.tensor(python_logits), dim=0).numpy()
            python_calibrated = torch.softmax(
                torch.tensor(python_logits) / float(calibration["temperature"]), dim=0
            ).numpy()
            coreml_probs = torch.softmax(torch.tensor(coreml_logits), dim=0).numpy()
            coreml_calibrated = torch.softmax(
                torch.tensor(coreml_logits) / float(calibration["temperature"]), dim=0
            ).numpy()
            raw_comparison = compare_score_vectors(
                python_probs.tolist(), coreml_probs.tolist(), atol=ATOL, rtol=RTOL
            )
            calibrated_comparison = compare_score_vectors(
                python_calibrated.tolist(),
                coreml_calibrated.tolist(),
                atol=ATOL,
                rtol=RTOL,
            )
            prior = references[name]["raw_response"]
            reference_calibrated = prior["probabilities"]
            frozen_comparison = compare_score_vectors(
                reference_calibrated,
                coreml_calibrated.tolist(),
                atol=ATOL,
                rtol=RTOL,
            )
            report["parity"][name] = {
                "input_tensor_digest": prior["input_tensor_digest"],
                "python_vs_coreml_logits_max_abs": float(
                    np.max(np.abs(python_logits - coreml_logits))
                ),
                "raw_probabilities": raw_comparison,
                "calibrated_probabilities": calibrated_comparison,
                "frozen_m0_calibrated_probabilities": frozen_comparison,
                "python_top_target": targets[int(np.argmax(python_calibrated))],
                "coreml_top_target": targets[int(np.argmax(coreml_calibrated))],
                "face_down_target_top": targets[int(np.argmax(coreml_calibrated))]
                == "FACE_DOWN",
            }
        report["status"] = "exported_and_compared"
        return_code = 0
    except Exception as error:  # noqa: BLE001 - Save a full bounded export failure for replay.
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
    write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
