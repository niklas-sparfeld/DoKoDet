#!/usr/bin/env python3
"""One-off OpenCV reviewer for mined CardEventNet hard-negative candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import cv2

DECISIONS = ("no_event", "missed_event", "uncertain")
LEFT_KEYS = {81, 2424832, 63234}
RIGHT_KEYS = {83, 2555904, 63235}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--videos-dir", type=Path, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        help="Decision file (default: beside the manifest as hard-negative-review.json).",
    )
    parser.add_argument(
        "--only-decision",
        choices=(*DECISIONS, "unreviewed"),
        help="Show only candidates with this existing decision.",
    )
    parser.add_argument("--width", type=int, default=640, help="Width of each evidence panel.")
    return parser.parse_args()


def candidate_id(video: str, time_s: float) -> str:
    return f"{video}@{time_s:.6f}"


def load_candidates(path: Path) -> tuple[list[dict[str, Any]], str]:
    source = path.read_bytes()
    payload = json.loads(source)
    if payload.get("format") != "cardevent-hard-negatives-v1":
        raise ValueError("--manifest must be a cardevent-hard-negatives-v1 file")
    if payload.get("partition") != "train":
        raise ValueError("--manifest must contain train-partition candidates")

    candidates: list[dict[str, Any]] = []
    for video_entry in payload.get("videos", []):
        video = video_entry.get("video")
        if not isinstance(video, str):
            raise ValueError("manifest has a candidate without a video name")
        for sample in video_entry.get("hard_negatives", []):
            time_s = sample.get("time_s")
            probability = sample.get("probability")
            if not isinstance(time_s, (int, float)) or not isinstance(probability, (int, float)):
                raise ValueError(f"manifest has an invalid candidate for {video}")
            candidates.append(
                {
                    "id": candidate_id(video, float(time_s)),
                    "video": video,
                    "time_s": float(time_s),
                    "probability": float(probability),
                    "decision": None,
                }
            )
    if not candidates:
        raise ValueError("manifest has no hard-negative candidates")
    return candidates, hashlib.sha256(source).hexdigest()


def load_existing_decisions(path: Path, source_digest: str) -> dict[str, str | None]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "cardevent-hard-negative-review-v1":
        raise ValueError(f"{path} is not a review decision file")
    if payload.get("source_manifest_sha256") != source_digest:
        raise ValueError(f"{path} was created from a different manifest")
    decisions: dict[str, str | None] = {}
    for item in payload.get("items", []):
        item_id = item.get("id")
        decision = item.get("decision")
        if not isinstance(item_id, str) or decision not in (*DECISIONS, None):
            raise ValueError(f"{path} contains an invalid review item")
        decisions[item_id] = decision
    return decisions


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def save_review(
    path: Path,
    source_manifest: Path,
    source_digest: str,
    items: list[dict[str, Any]],
) -> None:
    atomic_write_json(
        path,
        {
            "format": "cardevent-hard-negative-review-v1",
            "source_manifest": str(source_manifest),
            "source_manifest_sha256": source_digest,
            "items": items,
        },
    )


def source_videos(videos_dir: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for path in videos_dir.iterdir():
        if path.is_file():
            resolved[path.stem.casefold()] = path
    return resolved


def resolve_video(video_name: str, videos: dict[str, Path]) -> Path:
    key = video_name.removeprefix("cardeventnet-").casefold()
    try:
        return videos[key]
    except KeyError as exc:
        raise ValueError(f"Could not find a source video for {video_name}") from exc


def read_frame(capture: cv2.VideoCapture, time_s: float) -> Any:
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_s) * 1000.0)
    ok, frame = capture.read()
    if not ok or frame is None:
        raise ValueError(f"Could not decode video frame at {time_s:.3f}s")
    return frame


def resize(frame: Any, width: int) -> Any:
    height, current_width = frame.shape[:2]
    scaled_height = round(height * width / current_width)
    return cv2.resize(frame, (width, scaled_height), interpolation=cv2.INTER_AREA)


def label(frame: Any, text: str) -> None:
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 38), (0, 0, 0), -1)
    cv2.putText(frame, text, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


def review_frame(video_path: Path, item: dict[str, Any], width: int, index: int, total: int) -> Any:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Could not open {video_path}")
    try:
        time_s = float(item["time_s"])
        frames = [
            resize(read_frame(capture, time_s - 0.5), width),
            resize(read_frame(capture, time_s), width),
            resize(read_frame(capture, time_s + 0.5), width),
        ]
    finally:
        capture.release()
    for frame, title in zip(frames, ("-0.5 s", "candidate", "+0.5 s"), strict=True):
        label(frame, title)
    evidence = cv2.hconcat(frames)
    lines = (
        f"{index + 1}/{total}  {item['video']}  {time_s:.3f}s  score={item['probability']:.3f}",
        "left/right: previous/next    a: no event    s: missed event    d: uncertain",
        "x: clear decision    q/esc: save and quit",
        f"decision: {item['decision'] or 'unreviewed'}",
    )
    overlay_height = 118
    canvas = cv2.copyMakeBorder(evidence, overlay_height, 0, 0, 0, cv2.BORDER_CONSTANT)
    for line_index, line in enumerate(lines):
        cv2.putText(
            canvas,
            line,
            (16, 28 + line_index * 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
        )
    return canvas


def main() -> int:
    args = parse_args()
    if args.width < 160:
        raise ValueError("--width must be at least 160")
    output_path = args.out or args.manifest.with_name("hard-negative-review.json")
    items, source_digest = load_candidates(args.manifest)
    existing = load_existing_decisions(output_path, source_digest)
    for item in items:
        item["decision"] = existing.get(item["id"])
    review_items = items
    if args.only_decision is not None:
        selected_decision = None if args.only_decision == "unreviewed" else args.only_decision
        review_items = [item for item in items if item["decision"] == selected_decision]
    if not review_items:
        raise ValueError("No candidates match --only-decision")
    videos = source_videos(args.videos_dir)

    index = 0
    window_name = "CardEventNet hard-negative review"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    try:
        while True:
            item = review_items[index]
            canvas = review_frame(
                resolve_video(item["video"], videos), item, args.width, index, len(review_items)
            )
            cv2.imshow(window_name, canvas)
            key = cv2.waitKeyEx(0)
            if key in (27, ord("q"), ord("Q")):
                break
            if key in LEFT_KEYS:
                index = max(0, index - 1)
                continue
            if key in RIGHT_KEYS:
                index = min(len(review_items) - 1, index + 1)
                continue
            decision = {ord("a"): "no_event", ord("s"): "missed_event", ord("d"): "uncertain"}.get(
                key
            )
            if decision is not None:
                item["decision"] = decision
                save_review(output_path, args.manifest, source_digest, items)
                index = min(len(review_items) - 1, index + 1)
            elif key in (ord("x"), ord("X")):
                item["decision"] = None
                save_review(output_path, args.manifest, source_digest, items)
    finally:
        save_review(output_path, args.manifest, source_digest, items)
        cv2.destroyAllWindows()

    counts = {
        decision: sum(item["decision"] == decision for item in items) for decision in DECISIONS
    }
    remaining = sum(item["decision"] is None for item in items)
    print(f"Saved review: {output_path}")
    print(
        f"no_event={counts['no_event']} missed_event={counts['missed_event']} "
        f"uncertain={counts['uncertain']} remaining={remaining}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
