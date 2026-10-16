"""Build an 0088 identity-crop pool from exact 0070 visible-region cutout joins."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from doko_operations.derived_view import (  # noqa: E402
    ResolvedFrame,
    ReviewedVisibleRegionGeometry,
    resolve_visible_region_crop,
)
from doko_operations.reviewed_rfdetr_detector_campaign import canonical_json_bytes  # noqa: E402
from doko_operations.synthetic_visible_region_rendering import (  # noqa: E402
    _alpha_composite,
    _apply_shadow,
    _mask_polygons,
    _photometric,
    _read_cutout,
    _remove_small_components,
    _scene_placements,
    _warp_cutout,
)

REPOSITORY = Path(__file__).resolve().parents[2]
M1_MANIFEST = Path("data/operations/synthetic-visible-region-0070-m1-calibrated-inputs.json")
DINO_ROOT = Path(".runtime/dinov3-identity-0088")
OUTPUT = Path(".runtime/dinov3-identity-0088/m8-synthetic-pool")
SEED = 88008
WIDTH = 960
HEIGHT = 1440
NEUTRAL = (128, 128, 128)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _join_cutout(
    cutout: dict[str, Any], entries: list[dict[str, Any]], crop_by_item: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    frame = cutout["source_frame"]
    source_group = cutout["source_group"]
    event_id = frame.get("event_id")
    frame_sha256 = frame.get("identity", {}).get("image_sha256")
    source_asset_id = f"source-{source_group['id']}"
    candidates = []
    for entry in entries:
        crop = crop_by_item.get(entry["dataset_item_id"])
        if (
            crop is not None
            and entry.get("source_asset_id") == source_asset_id
            and entry.get("source_sha256") == source_group.get("source_sha256")
            and crop.get("source_frame_sha256") == frame_sha256
            and event_id in entry.get("dataset_item_id", "")
            and crop.get("lineage", {}).get("source_frame_id") == entry.get("source_frame_id")
            and entry.get("review_id")
            and entry.get("visual_card_identity")
            and entry.get("eligibility", {}).get("state") == "eligible"
            and entry.get("eligibility", {}).get("intended_use") == "train"
            and entry.get("eligibility", {}).get("review_state") == "reviewed"
        ):
            candidates.append((entry, crop))
    if len(candidates) > 1:
        raise ValueError(f"ambiguous 0088 identity join for {cutout['cutout_id']}")
    return candidates[0] if candidates else None


def build_pool(
    repository_root: str | Path = REPOSITORY,
    *,
    m1_manifest_path: str | Path = M1_MANIFEST,
    dino_root: str | Path = DINO_ROOT,
    output_directory: str | Path = OUTPUT,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    m1_path = repository / m1_manifest_path
    campaign_root = repository / dino_root
    output_root = repository / output_directory
    m1 = _read_json(m1_path)
    dataset = _read_json(campaign_root / "data/dataset.json")
    split = _read_json(campaign_root / "data/split.json")
    crop_inventory = _read_json(campaign_root / "crop-inventory.json")
    training_ids = set(split["train"])
    entries = [entry for entry in dataset["entries"] if entry["dataset_item_id"] in training_ids]
    crop_by_item = {
        crop["dataset_item_id"]: crop
        for crop in crop_inventory["crops"]
        if crop.get("partition") == "train"
    }
    output_root.mkdir(parents=True, exist_ok=True)
    rows = []
    unmatched = []
    for cutout in sorted(m1["cutouts"], key=lambda item: item["cutout_id"]):
        joined = _join_cutout(cutout, entries, crop_by_item)
        if joined is None:
            unmatched.append(cutout["cutout_id"])
            continue
        identity, crop_record = joined
        source_group = cutout["source_group"]
        if source_group.get("split") != "train":
            raise ValueError(f"non-training 0070 source group: {cutout['cutout_id']}")
        image_path = repository / cutout["files"]["rgba"]["path"]
        alpha_path = repository / cutout["files"]["alpha"]["path"]
        for path, key in ((image_path, "rgba"), (alpha_path, "alpha")):
            expected = cutout["files"][key]["sha256"]
            if _sha256(path.read_bytes()) != expected:
                raise ValueError(f"0070 {key} digest mismatch: {path}")
        asset = {"rgba_path": image_path, "alpha_path": alpha_path}
        rgba, alpha = _read_cutout(asset)
        normalized_quad = np.asarray(
            [[0.30, 0.26], [0.70, 0.34], [0.63, 0.78], [0.22, 0.68]],
            dtype=np.float32,
        )
        rng_seed = SEED + len(rows)
        placements = _scene_placements(
            "fully_visible_card",
            base_quad=None,
            template_quads=[normalized_quad * np.asarray([WIDTH, HEIGHT], dtype=np.float32)],
            output_width=WIDTH,
            output_height=HEIGHT,
            rng=np.random.default_rng(rng_seed),
            card_count=1,
        )
        target_quad = placements[0]["target_quad"]
        warped_rgba, visible_mask = _warp_cutout(rgba, alpha, target_quad, WIDTH, HEIGHT)
        visible_mask = _remove_small_components(visible_mask, 64)
        if int(np.count_nonzero(visible_mask)) < 64:
            raise ValueError(f"rendered support is too small: {cutout['cutout_id']}")

        scene = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        scene[:] = (NEUTRAL[2], NEUTRAL[1], NEUTRAL[0])
        _apply_shadow(scene, visible_mask, 0.12)
        _alpha_composite(scene, warped_rgba, visible_mask)
        effects = _photometric(scene, np.random.default_rng(rng_seed + 1), True)
        ok, encoded_scene = cv2.imencode(
            ".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, int(effects["jpeg_quality"])]
        )
        if not ok:
            raise ValueError(f"could not encode synthetic appearance for {cutout['cutout_id']}")
        scene_bytes = encoded_scene.tobytes()
        scene_name = f"{cutout['cutout_id']}.jpg"
        scene_path = output_root / "appearances" / scene_name
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_bytes(scene_bytes)

        polygons = _mask_polygons(visible_mask)
        geometry = ReviewedVisibleRegionGeometry(
            polygons=tuple(
                tuple(
                    (
                        int(round(points[index] * 1000 / WIDTH)),
                        int(round(points[index + 1] * 1000 / HEIGHT)),
                    )
                    for index in range(0, len(points), 2)
                )
                for points in polygons
            )
        )
        frame = ResolvedFrame(
            requested_time_us=0,
            frame_index=0,
            presentation_timestamp_us=0,
            source_video_sha256=_sha256(canonical_json_bytes({"m8_scene": scene_name})),
            width=WIDTH,
            height=HEIGHT,
            decoder_version=f"opencv/{cv2.__version__}",
            transform_version="0088-m8-synthetic-frame/v1",
            output_encoding="jpeg",
            image_bytes=scene_bytes,
        )
        crop = resolve_visible_region_crop(
            frame,
            geometry,
            crop_policy="oracle_visible_region",
            output_encoding="ppm",
            identity_usable=True,
            transform_version="pillow/12.3.0/crop-conditions-v2",
        )
        if crop.status != "usable" or crop.image_bytes is None:
            raise ValueError(f"DINO crop is unusable for {cutout['cutout_id']}")
        crop_path = output_root / "crops" / f"{cutout['cutout_id']}.ppm"
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        crop_path.write_bytes(crop.image_bytes)
        real_crop_source = campaign_root / "crop-cache" / crop_record["relative_path"]
        real_crop_bytes = real_crop_source.read_bytes()
        if _sha256(real_crop_bytes) != crop_record["sha256"]:
            raise ValueError(f"0088 real crop digest mismatch: {real_crop_source}")
        real_crop_path = output_root / "real-crops" / f"{cutout['cutout_id']}.ppm"
        real_crop_path.parent.mkdir(parents=True, exist_ok=True)
        real_crop_path.write_bytes(real_crop_bytes)
        mask_ok, mask_png = cv2.imencode(".png", visible_mask)
        if not mask_ok:
            raise ValueError(f"could not encode visible mask for {cutout['cutout_id']}")
        mask_path = output_root / "masks" / f"{cutout['cutout_id']}.png"
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        mask_path.write_bytes(mask_png.tobytes())
        rows.append(
            {
                "synthetic_id": cutout["cutout_id"],
                "label": identity["visual_card_identity"],
                "side": cutout["reviewed_decision"]["card_side"],
                "source_group_id": source_group["id"],
                "source_group_keys": identity["group_keys"],
                "source_asset_id": identity["source_asset_id"],
                "source_sha256": identity["source_sha256"],
                "source_frame_id": identity["source_frame_id"],
                "source_frame_sha256": crop_record["source_frame_sha256"],
                "dataset_item_id": identity["dataset_item_id"],
                "review_id": identity["review_id"],
                "real_crop_sha256": crop_record["sha256"],
                "real_crop": {
                    "path": real_crop_path.relative_to(repository).as_posix(),
                    "sha256": _sha256(real_crop_bytes),
                    "byte_length": len(real_crop_bytes),
                },
                "cutout_id": cutout["cutout_id"],
                "cutout_digest": cutout["cutout_digest"],
                "seed": rng_seed,
                "placement": {
                    "target_quad": [
                        [round(float(point[0]), 4), round(float(point[1]), 4)]
                        for point in target_quad
                    ]
                },
                "effects": effects,
                "appearance": {
                    "path": scene_path.relative_to(repository).as_posix(),
                    "sha256": _sha256(scene_bytes),
                },
                "visible_mask": {
                    "path": mask_path.relative_to(repository).as_posix(),
                    "sha256": _sha256(mask_png.tobytes()),
                    "pixels": int(np.count_nonzero(visible_mask)),
                },
                "crop": {
                    "path": crop_path.relative_to(repository).as_posix(),
                    "sha256": _sha256(crop.image_bytes),
                    "byte_length": len(crop.image_bytes),
                    "width": crop.pixel_bounds.width,
                    "height": crop.pixel_bounds.height,
                },
            }
        )

    tiles = []
    for row in rows:
        real_crop_image = Image.open(repository / row["real_crop"]["path"]).convert("RGB")
        real_crop_image.thumbnail((200, 300))
        crop_image = Image.open(repository / row["crop"]["path"]).convert("RGB")
        crop_image.thumbnail((200, 300))
        appearance = Image.open(repository / row["appearance"]["path"]).convert("RGB")
        mask_image = Image.open(repository / row["visible_mask"]["path"]).convert("L")
        appearance.thumbnail((200, 300))
        mask_image = mask_image.resize(appearance.size, Image.Resampling.NEAREST)
        green = Image.new("RGB", appearance.size, (40, 235, 90))
        overlay = Image.composite(green, appearance, mask_image)
        tile = Image.new("RGB", (660, 360), "white")
        tile.paste(real_crop_image, (10 + (200 - real_crop_image.width) // 2, 44))
        tile.paste(crop_image, (230 + (200 - crop_image.width) // 2, 44))
        tile.paste(overlay, (450 + (200 - overlay.width) // 2, 44))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(tile)
        draw.text((10, 10), f"{row['label']} / real", fill="black")
        draw.text((230, 10), "synthetic DINO crop", fill="black")
        draw.text((450, 10), "0070 appearance + mask", fill="black")
        tiles.append(tile)
    sheet = Image.new("RGB", (660 * max(1, len(tiles)), 360), "#dddddd")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (660 * index, 0))
    sheet_path = output_root / "contact-sheet.jpg"
    sheet.save(sheet_path, quality=92)
    sheet_digest = _sha256(sheet_path.read_bytes())

    core = {
        "schema_version": "0088-m8-synthetic-identity-pool/v1",
        "campaign_id": "0088-m8-synthetic-identity-pool",
        "status": "complete" if rows else "skipped",
        "source_manifests": {
            "0070_m1": {
                "path": M1_MANIFEST.as_posix(),
                "manifest_digest": m1["manifest_digest"],
            },
            "0088_dataset_digest": dataset["dataset_version_digest"],
            "0088_split_digest": split["split_version_digest"],
            "0088_crop_cache_digest": crop_inventory["cache_digest"],
        },
        "recipe": {
            "seed": SEED,
            "one_render_per_exact_join": True,
            "renderer": "0070 deterministic planar cutout warp, shadow, and appearance effects",
            "background": "fixed neutral canvas; no source background pixels",
            "crop_policy": "oracle_visible_region",
            "crop_transform_version": "pillow/12.3.0/crop-conditions-v2",
            "identity_join": [
                "0088 training partition and reviewed eligibility",
                "same source recording digest",
                "same decoded source frame digest",
                "same event item id",
                "exactly one reviewed identity item",
            ],
        },
        "pool": rows,
        "unmatched_0070_cutouts": unmatched,
        "inventory": {
            "synthetic_crop_count": len(rows),
            "source_group_count": len({row["source_group_id"] for row in rows}),
            "source_group_ids": sorted({row["source_group_id"] for row in rows}),
            "class_counts": dict(
                sorted(
                    (label, sum(row["label"] == label for row in rows))
                    for label in {row["label"] for row in rows}
                )
            ),
            "side_counts": dict(
                sorted(
                    (side, sum(row["side"] == side for row in rows))
                    for side in {row["side"] for row in rows}
                )
            ),
            "face_down_synthetic_count": sum(row["label"] == "FACE_DOWN" for row in rows),
        },
        "review": {
            "contact_sheet": {
                "path": sheet_path.relative_to(repository).as_posix(),
                "sha256": sheet_digest,
            },
            "note": (
                "Contact sheet shows every DINO crop beside its 0070 appearance and visible mask."
            ),
        },
        "tool_versions": {
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "numpy": np.__version__,
        },
    }
    manifest = {**core, "manifest_digest": _sha256(canonical_json_bytes(core))}
    _write_json(output_root / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m1-manifest", type=Path, default=M1_MANIFEST)
    parser.add_argument("--dino-root", type=Path, default=DINO_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_pool(
        m1_manifest_path=args.m1_manifest,
        dino_root=args.dino_root,
        output_directory=args.output,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "inventory": result["inventory"],
                "manifest_digest": result["manifest_digest"],
            },
            indent=2,
        )
    )
