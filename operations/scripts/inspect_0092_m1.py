from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
from pycocotools import mask as mask_utils
from rfdetr.datasets.coco import build_roboflow_from_coco

from doko_operations.rfdetr_segmentation_materialization import (
    load_rfdetr_segmentation_materialization,
)

COLORS = {1: (25, 230, 255), 2: (255, 170, 30)}


def _decode_mask(segmentation: object, height: int, width: int):
    if isinstance(segmentation, list):
        rles = mask_utils.frPyObjects(segmentation, height, width)
        rle = mask_utils.merge(rles) if isinstance(rles, list) else rles
    elif isinstance(segmentation, dict):
        rle = dict(segmentation)
        if isinstance(rle.get("counts"), list):
            rle = mask_utils.frPyObjects(rle, height, width)
    else:
        raise ValueError("unsupported COCO segmentation encoding")
    decoded = mask_utils.decode(rle)
    if decoded.ndim == 3:
        decoded = decoded.any(axis=2)
    return decoded


def _draw_overlay(image_path: Path, image_record: dict, annotations: list[dict]) -> Image.Image:
    source = Image.open(image_path).convert("RGB")
    width, height = source.size
    if (width, height) != (image_record["width"], image_record["height"]):
        raise ValueError(f"image dimensions differ for {image_record['event_id']}")
    composed = source
    for annotation in annotations:
        binary = _decode_mask(annotation["segmentation"], height, width)
        if binary.shape != (height, width) or not binary.any():
            raise ValueError(f"empty or wrong-size mask in {image_record['event_id']}")
        mask_image = Image.fromarray(binary.astype("uint8") * 255, mode="L")
        color_image = Image.new("RGB", source.size, COLORS[int(annotation["category_id"])])
        blended = Image.blend(composed, color_image, 0.376)
        composed = Image.composite(blended, composed, mask_image)
    draw = ImageDraw.Draw(composed)
    for annotation in annotations:
        x, y, box_width, box_height = annotation["bbox"]
        color = COLORS[int(annotation["category_id"])]
        draw.rectangle((x, y, x + box_width, y + box_height), outline=color, width=5)
    return composed


def _json_array(text: str, field: str) -> Iterator[dict]:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*\[', text)
    if match is None:
        raise ValueError(f"COCO JSON is missing the {field} array")
    decoder = json.JSONDecoder()
    position = match.end()
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if text[position] == "]":
            return
        if text[position] == ",":
            position += 1
            continue
        item, position = decoder.raw_decode(text, position)
        if not isinstance(item, dict):
            raise ValueError(f"COCO {field} entries must be objects")
        yield item


def _sample_indices(
    images: list[dict], annotation_counts: dict[int, int], pile_counts: dict[int, int]
) -> list[int]:
    if not images:
        return []
    candidates = {0, len(images) // 2, len(images) - 1}
    candidates.add(max(range(len(images)), key=lambda i: annotation_counts[images[i]["id"]]))
    candidates.add(max(range(len(images)), key=lambda i: pile_counts[images[i]["id"]]))
    return sorted(candidates)


def _render_recording_sheet(
    output: Path,
    recording_id: str,
    images: list[dict],
    annotations_by_image: dict[int, list[dict]],
    image_root: Path,
) -> list[str]:
    cell_width, image_height, label_height = 480, 854, 40
    rows = (len(images) + 1) // 2
    sheet = Image.new("RGB", (cell_width * 2, (image_height + label_height) * rows), "#17191d")
    draw = ImageDraw.Draw(sheet)
    event_ids: list[str] = []
    for position, image_record in enumerate(images):
        event_ids.append(str(image_record["event_id"]))
        overlay = _draw_overlay(
            image_root / image_record["file_name"],
            image_record,
            annotations_by_image[image_record["id"]],
        )
        overlay.thumbnail((cell_width, image_height), Image.Resampling.LANCZOS)
        x = (position % 2) * cell_width
        y = (position // 2) * (image_height + label_height)
        sheet.paste(overlay, (x, y + label_height))
        card_count = sum(
            item["category_id"] == 1 for item in annotations_by_image[image_record["id"]]
        )
        pile_count = sum(
            item["category_id"] == 2 for item in annotations_by_image[image_record["id"]]
        )
        draw.text(
            (x + 8, y + 8),
            f"{image_record['event_id']} | cards {card_count} | piles {pile_count}",
            fill="white",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return event_ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the frozen 0092 materialization and load it with RF-DETR 1.9.4."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--view-root", type=Path, default=Path(".runtime/rfdetr-segmentation-0092-m1")
    )
    parser.add_argument(
        "--overlay-root", type=Path, default=Path(".runtime/rfdetr-segmentation-0092-m1-overlays")
    )
    args = parser.parse_args()
    repository = args.repository_root.expanduser().resolve()
    view_root = (repository / args.view_root).resolve()
    overlay_root = (repository / args.overlay_root).resolve()
    materialization = load_rfdetr_segmentation_materialization(view_root)

    image_count = 0
    mask_count = 0
    recordings_qa = []
    for _split, relative in (
        ("train", "train"),
        ("validation", "valid"),
        ("sealed_test", "sealed_test"),
    ):
        coco_text = (view_root / relative / "_annotations.coco.json").read_text()
        images = list(_json_array(coco_text, "images"))
        for image in images:
            image["_split_directory"] = relative
        image_by_id = {image["id"]: image for image in images}
        annotation_counts: dict[int, int] = defaultdict(int)
        pile_counts: dict[int, int] = defaultdict(int)
        smallest_card_area: dict[int, float] = defaultdict(lambda: float("inf"))
        edge_card_images: set[int] = set()
        for annotation in _json_array(coco_text, "annotations"):
            # Decode every mask. The same pass checks non-empty masks and their exact frame shape.
            image = image_by_id.get(annotation["image_id"])
            if image is None:
                raise ValueError(f"mask points to unknown image id {annotation['image_id']}")
            decoded = _decode_mask(annotation["segmentation"], image["height"], image["width"])
            if decoded.shape != (image["height"], image["width"]) or not decoded.any():
                raise ValueError(f"mask decode failed for image {image['event_id']}")
            annotation_counts[image["id"]] += 1
            if annotation["category_id"] == 2:
                pile_counts[image["id"]] += 1
            elif annotation["category_id"] == 1:
                x, y, box_width, box_height = annotation["bbox"]
                smallest_card_area[image["id"]] = min(
                    smallest_card_area[image["id"]],
                    box_width * box_height / (image["width"] * image["height"]),
                )
                if (
                    x <= 2
                    or y <= 2
                    or x + box_width >= image["width"] - 2
                    or y + box_height >= image["height"] - 2
                ):
                    edge_card_images.add(image["id"])
            mask_count += 1
        by_recording: dict[str, list[dict]] = defaultdict(list)
        for image in images:
            by_recording[str(image["recording_id"])].append(image)
        selected_by_recording = {}
        risk_examples_by_recording = {}
        for recording_id, image_list in by_recording.items():
            selected_indices = set(_sample_indices(image_list, annotation_counts, pile_counts))
            risk_examples = {}
            card_images = [
                image for image in image_list if smallest_card_area[image["id"]] < float("inf")
            ]
            if card_images:
                smallest_image = min(card_images, key=lambda image: smallest_card_area[image["id"]])
                risk_examples["small_cards"] = smallest_image["event_id"]
                selected_indices.add(image_list.index(smallest_image))
            edge_images = [image for image in image_list if image["id"] in edge_card_images]
            if edge_images:
                edge_image = edge_images[0]
                risk_examples["frame_edge"] = edge_image["event_id"]
                selected_indices.add(image_list.index(edge_image))
            pile_image = max(image_list, key=lambda image: pile_counts[image["id"]])
            if pile_counts[pile_image["id"]]:
                risk_examples["pile_and_near_pile_cards"] = pile_image["event_id"]
            dense_image = max(image_list, key=lambda image: annotation_counts[image["id"]])
            risk_examples["dense_overlap_candidate"] = dense_image["event_id"]
            selected_by_recording[recording_id] = [
                image_list[index] for index in sorted(selected_indices)
            ]
            risk_examples_by_recording[recording_id] = risk_examples
        selected_image_ids = {
            image["id"] for image_list in selected_by_recording.values() for image in image_list
        }
        selected_annotations: dict[int, list[dict]] = defaultdict(list)
        for annotation in _json_array(coco_text, "annotations"):
            if annotation["image_id"] in selected_image_ids:
                selected_annotations[annotation["image_id"]].append(annotation)
        for recording_id, selected_images in sorted(selected_by_recording.items()):
            event_ids = _render_recording_sheet(
                overlay_root / f"{recording_id}.png",
                recording_id,
                selected_images,
                selected_annotations,
                view_root / relative,
            )
            recordings_qa.append(
                {
                    "recording_id": recording_id,
                    "split": selected_images[0]["split"],
                    "image_count": len(by_recording[recording_id]),
                    "overlay_path": (overlay_root / f"{recording_id}.png")
                    .relative_to(repository)
                    .as_posix(),
                    "sample_event_ids": event_ids,
                    "risk_examples": risk_examples_by_recording[recording_id],
                }
            )
        image_count += len(images)
        del coco_text, images, image_by_id, selected_annotations
    qa = {
        "schema_version": "0092-m1-overlay-inspection/v1",
        "materialization_digest": materialization["materialization_digest"],
        "image_count": image_count,
        "recording_count": len(recordings_qa),
        "mask_count": mask_count,
        "recordings": recordings_qa,
    }

    # Use the package's COCO readers and mask conversion, without training or inference.
    from importlib.metadata import version

    package_version = version("rfdetr")
    if package_version != "1.9.4":
        raise ValueError(f"expected pinned rfdetr 1.9.4, found {package_version}")
    with tempfile.TemporaryDirectory(prefix="rfdetr-0092-loader-") as temp_dir:
        loader_root = Path(temp_dir)
        for source, target in (("train", "train"), ("valid", "valid"), ("sealed_test", "test")):
            (loader_root / target).symlink_to(view_root / source, target_is_directory=True)
        loader_args = SimpleNamespace(
            dataset_dir=str(loader_root),
            segmentation_head=True,
            multi_scale=True,
            expanded_scales=True,
            augmentation_backend="cpu",
            scale_jitter=True,
        )
        loaded_partitions = {}
        for package_split, label in (
            ("train", "train"),
            ("val", "validation"),
            ("test", "sealed_test"),
        ):
            dataset = build_roboflow_from_coco(package_split, loader_args, 432)
            if len(dataset) == 0:
                raise ValueError(f"RF-DETR package loaded an empty {label} dataset")
            _sample_image, sample_target = dataset[0]
            masks = sample_target.get("masks")
            if masks is None or masks.ndim != 3:
                raise ValueError(f"RF-DETR package did not decode segmentation masks for {label}")
            loaded_partitions[label] = {
                "images": len(dataset),
                "first_sample_masks": int(masks.shape[0]),
            }

    qa["rfdetr_package"] = {"version": package_version, "loaded_partitions": loaded_partitions}
    qa_path = overlay_root / "inspection.json"
    qa_path.write_text(json.dumps(qa, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {**qa, "inspection_report": qa_path.relative_to(repository).as_posix()}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
