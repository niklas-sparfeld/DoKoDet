"""Compare all DINOv3 Core ML outputs to the frozen M0 references."""

import hashlib
import json
from pathlib import Path

import coremltools as ct
import numpy as np
import torch
from table_evidence_analyzer.dinov3_bundle import load_dinov3_identity_bundle
from table_evidence_analyzer.local_identity import transform_identity_crop
from table_evidence_analyzer.model_parity import compare_score_vectors

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / ".runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle"
PACKAGE = ROOT / ".runtime/0104-m2/dinov3-identity.mlpackage"


def main():
    bundle = load_dinov3_identity_bundle(BUNDLE)
    if (
        bundle.bundle_digest
        != "a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79"
    ):
        raise RuntimeError("Frozen bundle digest differs")
    target_map = json.loads((BUNDLE / bundle.manifest["target_map_file"]).read_text())[
        "class_map"
    ]
    targets = [target_map[str(i)] for i in range(25)]
    threshold = float(bundle.manifest["calibration"]["review_threshold"])
    temperature = float(bundle.manifest["calibration"]["temperature"])
    references = json.loads(
        (ROOT / "docs/reports/0103-M0_Python_References.json").read_text()
    )["dinov3"]["crops"]
    manifest = json.loads(
        (ROOT / "docs/reports/0103-M0_Input_Manifest.json").read_text()
    )
    crop_inputs = {Path(item["path"]).name: item for item in manifest["identity_crops"]}
    model = ct.models.MLModel(str(PACKAGE), compute_units=ct.ComputeUnit.CPU_ONLY)
    report = {
        "compute_units": "CPU_ONLY",
        "bundle_digest": bundle.bundle_digest,
        "targets": targets,
        "review_threshold": threshold,
        "temperature": temperature,
        "crops": {},
    }
    for name, reference in references.items():
        frame = crop_inputs[name]
        data = (ROOT / ".runtime/0103-m0" / frame["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != frame["sha256"]:
            raise RuntimeError(f"Frozen crop digest differs: {name}")
        transformed = transform_identity_crop(data, input_size=224)
        prior = reference["raw_response"]
        if transformed.tensor_digest != prior["input_tensor_digest"]:
            raise RuntimeError(f"Frozen transformed tensor differs: {name}")
        logits = np.asarray(
            model.predict(
                {"pixel_values": transformed.to_torch().unsqueeze(0).numpy()}
            )["logits"]
        ).reshape(-1)
        if logits.shape != (25,) or not np.isfinite(logits).all():
            raise RuntimeError(f"Invalid logits for {name}")
        scores = torch.softmax(torch.tensor(logits) / temperature, dim=0).numpy()
        raw_scores = torch.softmax(torch.tensor(logits), dim=0).numpy()
        logits_compare = compare_score_vectors(
            prior["logits"], logits.tolist(), atol=1e-4, rtol=1e-4
        )
        scores_compare = compare_score_vectors(
            prior["probabilities"], scores.tolist(), atol=1e-4, rtol=1e-4
        )
        raw_compare = compare_score_vectors(
            prior["raw_probabilities"], raw_scores.tolist(), atol=1e-4, rtol=1e-4
        )
        original_top = targets[scores_compare["reference_rank"][0]]
        candidate_top = targets[scores_compare["candidate_rank"][0]]
        report["crops"][name] = {
            "input_sha256": frame["sha256"],
            "input_tensor_digest": transformed.tensor_digest,
            "coreml_logits": logits.tolist(),
            "coreml_probabilities": scores.tolist(),
            "coreml_raw_probabilities": raw_scores.tolist(),
            "logits_comparison": logits_compare,
            "calibrated_comparison": scores_compare,
            "raw_probabilities_comparison": raw_compare,
            "reference_top_target": original_top,
            "coreml_top_target": candidate_top,
            "face_down_decision_changed": (original_top == "FACE_DOWN")
            != (candidate_top == "FACE_DOWN"),
            "review_threshold_decision_changed": (
                max(prior["probabilities"]) >= threshold
            )
            != (float(max(scores)) >= threshold),
        }
        print(
            name,
            "logit mismatches",
            len(logits_compare["mismatched_indices"]),
            "score mismatches",
            len(scores_compare["mismatched_indices"]),
            "rank changed",
            scores_compare["rank_changed"],
            "top",
            candidate_top,
            flush=True,
        )
    output = ROOT / ".runtime/0104-m2/parity-report.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    failed = any(
        c["logits_comparison"]["mismatched_indices"]
        or c["calibrated_comparison"]["mismatched_indices"]
        or c["raw_probabilities_comparison"]["mismatched_indices"]
        or c["calibrated_comparison"]["rank_changed"]
        or c["face_down_decision_changed"]
        or c["review_threshold_decision_changed"]
        for c in report["crops"].values()
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
