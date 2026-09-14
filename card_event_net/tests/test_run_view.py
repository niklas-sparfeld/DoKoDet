from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cardevent.run_view import RunViewError, load_materialized_run_view


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_view(root: Path) -> None:
    (root / "videos").mkdir(parents=True)
    (root / "annotations").mkdir()
    (root / "cache").mkdir()
    (root / "videos" / "recording.mov").write_bytes(b"video")
    (root / "annotations" / "recording.json").write_text("{}\n", encoding="utf-8")
    (root / "split.yaml").write_text("train: [recording]\nval: []\ntest: []\n", encoding="utf-8")
    generated_files = [
        {
            "kind": "source_link",
            "path": "videos/recording.mov",
            "sha256": _sha256(root / "videos" / "recording.mov"),
        },
        {
            "kind": "event_annotation",
            "path": "annotations/recording.json",
            "sha256": _sha256(root / "annotations" / "recording.json"),
        },
        {
            "kind": "trainer_split",
            "path": "split.yaml",
            "sha256": _sha256(root / "split.yaml"),
        },
    ]
    manifest_core = {
        "schema_version": "cardeventnet-materialization/v1",
        "materializer_version": "cardeventnet-materializer/v1",
        "dataset": {"id": "dataset-fixture", "digest": "a" * 64},
        "split": {"id": "split-fixture", "digest": "b" * 64},
        "inputs": [
            {
                "kind": "source_video",
                "recording_id": "recording",
                "path": "source.mov",
                "sha256": "c" * 64,
            }
        ],
        "generated_files": generated_files,
    }
    manifest = {**manifest_core, "manifest_digest": _digest(manifest_core)}
    (root / "materialization.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_materialized_run_view_validates_manifest_and_exposes_identity(tmp_path: Path) -> None:
    _write_view(tmp_path)

    view = load_materialized_run_view(tmp_path)
    identity = view.data_identity(preprocessing="full_frame_letterbox_v1")

    assert view.video_paths() == (tmp_path / "videos" / "recording.mov",)
    assert view.video_paths(("train",)) == (tmp_path / "videos" / "recording.mov",)
    assert identity["dataset"]["id"] == "dataset-fixture"
    assert identity["materializer"]["version"] == "cardeventnet-materializer/v1"
    assert identity["preprocessing"] == "full_frame_letterbox_v1"


def test_materialized_run_view_rejects_changed_generated_file(tmp_path: Path) -> None:
    _write_view(tmp_path)
    (tmp_path / "split.yaml").write_text("train: []\nval: []\ntest: []\n", encoding="utf-8")

    with pytest.raises(RunViewError, match="materialized file digest is invalid"):
        load_materialized_run_view(tmp_path)
