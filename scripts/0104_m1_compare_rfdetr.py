"""Compare the exported RF-DETR package with frozen 0103 frame references."""

import base64
import hashlib
import json
import os
import zlib
from pathlib import Path

import coremltools as ct
import numpy as np
import torch
from PIL import Image, ImageDraw
from table_evidence_analyzer.rfdetr_segmentation_training import (
    load_rfdetr_segmentation_bundle,
)
from table_evidence_analyzer.visible_cards import (
    VisibleCardError,
    _load_local_rfdetr_segmentation,
    _normalised_polygon_from_mask,
)
from torchvision.transforms import functional as F

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime/0104-m1"
BUNDLE = ROOT / ".runtime/rfdetr-segmentation-0092-m4/bundle"
POPCOUNT = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)


def polygon_bits(mask, width, height):
    try:
        polygon, _ = _normalised_polygon_from_mask(mask, width=width, height=height)
    except VisibleCardError as error:
        if "must have positive area" not in str(error):
            raise
        return None
    if polygon is None:
        return None
    img = Image.new("1", (1000, 1000), 0)
    ImageDraw.Draw(img).polygon(
        [(round(p.x * 999 / 1000), round(p.y * 999 / 1000)) for p in polygon], fill=1
    )
    bits = np.packbits(np.asarray(img).ravel())
    return bits, int(POPCOUNT[bits].sum())


def main():
    manifest = json.loads(
        (ROOT / "docs/reports/0103-M0_Input_Manifest.json").read_text()
    )
    references = json.loads(
        (ROOT / "docs/reports/0103-M0_Python_References.json").read_text()
    )["rfdetr"]["frames"]
    bundle = load_rfdetr_segmentation_bundle(BUNDLE)
    assert (
        bundle.manifest["bundle_digest"]
        == "05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c"
    )
    detector = _load_local_rfdetr_segmentation(bundle, "cpu")
    compute_unit = os.environ.get("RFDETR_COREML_COMPUTE", "CPU_ONLY")
    model = ct.models.MLModel(
        str(RUNTIME / "rfdetr-seg-medium.mlpackage"),
        compute_units=getattr(ct.ComputeUnit, compute_unit),
    )
    report = {
        "frames": {},
        "compute_units": compute_unit,
        "input_contract": "RGB, torchvision to_tensor, resize 432x432 bilinear antialias false, ImageNet normalize",
        "notes": "Compares all threshold-free candidates. Polygon mask matching uses frozen 1000x1000 raster, class and greedy descending IoU >= 0.5. Empty polygons remain unmatched.",
    }
    for frame in manifest["frames"]:
        path = ROOT / ".runtime/0103-m0" / frame["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frame["sha256"]
        with Image.open(path) as image:
            assert image.size == (frame["width"], frame["height"])
            rgb = image.convert("RGB")
            image_tensor = F.to_tensor(rgb)
        tensor = F.normalize(
            F.resize(image_tensor, [432, 432], antialias=False),
            detector.means,
            detector.stds,
        ).unsqueeze(0)
        with torch.inference_mode():
            python_out = detector.model.inference_model(tensor)
            out = model.predict({"image": tensor.numpy()})
            raw_differences = {
                name: float(
                    np.max(np.abs(np.asarray(value.detach().cpu()) - out[name]))
                )
                for name, value in zip(
                    ("boxes", "class_logits", "mask_logits"), python_out, strict=True
                )
            }
            python_prediction = dict(
                zip(
                    ("pred_boxes", "pred_logits", "pred_masks"), python_out, strict=True
                )
            )
            python_res = detector.model.postprocess(
                python_prediction,
                target_sizes=torch.tensor([[frame["height"], frame["width"]]]),
                score_threshold=0.5,
            )[0]
            prediction = {
                "pred_boxes": torch.from_numpy(out["boxes"]),
                "pred_logits": torch.from_numpy(out["class_logits"]),
                "pred_masks": torch.from_numpy(out["mask_logits"]),
            }
            post = detector.model.postprocess
            target_sizes = torch.tensor([[frame["height"], frame["width"]]])
            score_tensor, label_tensor, topk = post._select_topk(
                prediction["pred_logits"]
            )
            box_tensor = post._gather_and_scale_boxes(
                prediction["pred_boxes"], topk, target_sizes
            )
        scores = score_tensor[0].cpu().numpy()
        labels = label_tensor[0].cpu().numpy()
        boxes = box_tensor[0].cpu().numpy()
        refs = references[path.name]["threshold_free_candidates"]
        cand_bits = []
        for start in range(0, len(scores), 8):
            with torch.inference_mode():
                chunk = post._postprocess_masks(
                    prediction["pred_masks"],
                    score_tensor[:, start : start + 8],
                    label_tensor[:, start : start + 8],
                    box_tensor[:, start : start + 8],
                    topk[:, start : start + 8],
                    target_sizes,
                )[0]
            for mask in chunk["masks"].squeeze(1).cpu().numpy():
                cand_bits.append(polygon_bits(mask, frame["width"], frame["height"]))
        refs_bits = []
        for item in refs:
            packed = zlib.decompress(
                base64.b64decode(item["mask_packbits_little_zlib_base64"])
            )
            mask = (
                np.unpackbits(
                    np.frombuffer(packed, dtype=np.uint8),
                    bitorder="little",
                    count=frame["height"] * frame["width"],
                )
                .reshape(frame["height"], frame["width"])
                .astype(bool)
            )
            refs_bits.append(polygon_bits(mask, frame["width"], frame["height"]))
        pairs = []
        for i, a in enumerate(refs_bits):
            if a is None:
                continue
            for j, b in enumerate(cand_bits):
                if b is None or refs[i]["class_id"] != int(labels[j]):
                    continue
                if min(a[1], b[1]) < 0.5 * max(a[1], b[1]):
                    continue
                intersection = int(POPCOUNT[np.bitwise_and(a[0], b[0])].sum())
                union = a[1] + b[1] - intersection
                iou = intersection / union if union else 1.0
                if iou >= 0.5:
                    pairs.append((iou, i, j))
        used_r = set()
        used_c = set()
        matches = []
        for iou, i, j in sorted(pairs, key=lambda t: (-t[0], t[1], t[2])):
            if i in used_r or j in used_c:
                continue
            used_r.add(i)
            used_c.add(j)
            ref = refs[i]
            score = float(scores[j])
            score_diff = abs(score - ref["score"])
            normalizer = np.array(
                [frame["width"], frame["height"], frame["width"], frame["height"]]
            )
            box_delta = (boxes[j] - np.array(ref["box_xyxy"])) / normalizer
            matches.append(
                {
                    "reference_index": i,
                    "candidate_index": j,
                    "class_id": int(labels[j]),
                    "mask_iou": iou,
                    "reference_score": ref["score"],
                    "candidate_score": score,
                    "score_difference": score_diff,
                    "score_outside_tolerance": score_diff
                    > 1e-4 + 1e-4 * abs(ref["score"]),
                    "normalized_box_differences": box_delta.tolist(),
                    "box_outside_tolerance": bool(np.any(np.abs(box_delta) > 1e-4)),
                    "decision_changed": (ref["score"] >= 0.5) != (score >= 0.5),
                }
            )
        result = {
            "input_sha256": frame["sha256"],
            "python_coreml_raw_max_absolute_difference": raw_differences,
            "python_scores": python_res["scores"].cpu().tolist(),
            "preprocessed_tensor_sha256": hashlib.sha256(
                tensor.numpy().tobytes()
            ).hexdigest(),
            "reference_count": len(refs),
            "candidate_count": len(scores),
            "matches": matches,
            "unmatched_reference": [i for i in range(len(refs)) if i not in used_r],
            "unmatched_candidate": [i for i in range(len(scores)) if i not in used_c],
        }
        report["frames"][path.name] = result
        (RUNTIME / f"parity-report-{compute_unit}.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(
            path.name,
            "matched",
            len(matches),
            "unmatched",
            len(result["unmatched_reference"]),
            len(result["unmatched_candidate"]),
            "score failures",
            sum(m["score_outside_tolerance"] for m in matches),
            "box failures",
            sum(m["box_outside_tolerance"] for m in matches),
            "decisions",
            sum(m["decision_changed"] for m in matches),
            flush=True,
        )


if __name__ == "__main__":
    main()
