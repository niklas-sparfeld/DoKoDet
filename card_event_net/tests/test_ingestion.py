from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cardevent.ingestion import (
    INGESTION_INDEX_SCHEMA_VERSION,
    IngestionError,
    VideoProbe,
    ingest_dataset,
    inspect_dataset,
    load_ingestion_index,
)
from cardevent.manifest import load_dataset_manifest


def _operator_metadata(path: Path, *, game_id: str | None = None) -> None:
    game_line = f"  game_id: {game_id}\n" if game_id else "  game_id: null\n"
    path.write_text(
        "defaults:\n"
        "  content_type: staged_trick_sequence\n"
        "  session_id: capture-one\n"
        f"{game_line}"
        "  camera_view: high_oblique\n"
        "  camera_motion: fixed\n"
        "  camera_framing: table_fills_frame\n"
        "  table_setup: setup-one\n"
        "  lighting: [room_light]\n"
        "  source: self_recorded\n"
        "  source_permission: training_and_evaluation\n"
        "videos:\n"
        "  one:\n"
        "    notes: operator supplied\n",
        encoding="utf-8",
    )


class _Probe:
    def probe(self, path: Path) -> VideoProbe:
        return VideoProbe(
            width=1920,
            height=1080,
            frame_rate=30.0,
            frame_count=60,
            duration_s=2.0,
            orientation="landscape",
            metadata={"device": "Test Phone"},
        )


class _Fingerprinter:
    def fingerprint(self, path: Path) -> str:
        return "same" if path.stem.casefold() in {"one", "two"} else path.stem


class _EscapingPreview:
    def generate(self, video_path: Path, output_dir: Path, video_id: str) -> dict[str, str]:
        return {"thumbnail": "../outside.jpg"}


def test_ingest_writes_manifest_and_index_deterministically(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "two.mov").write_bytes(b"two")
    (source_dir / "one.MP4").write_bytes(b"one")
    metadata_path = tmp_path / "operator.yaml"
    _operator_metadata(metadata_path)
    manifest_path = tmp_path / "out" / "manifest.yaml"
    index_path = tmp_path / "out" / "index.json"

    first = ingest_dataset(
        source_dir,
        metadata_path,
        manifest_path,
        index_path,
        prober=_Probe(),
        fingerprinter=_Fingerprinter(),
    )
    first_manifest = manifest_path.read_bytes()
    first_index = index_path.read_bytes()
    second = ingest_dataset(
        source_dir,
        metadata_path,
        manifest_path,
        index_path,
        prober=_Probe(),
        fingerprinter=_Fingerprinter(),
    )

    assert first.dataset_version_digest == second.dataset_version_digest
    assert first_manifest == manifest_path.read_bytes()
    assert first_index == index_path.read_bytes()
    assert load_dataset_manifest(manifest_path)[0].video_id == "one"
    index = load_ingestion_index(index_path)
    assert index["schema_version"] == INGESTION_INDEX_SCHEMA_VERSION
    assert index["videos"][0]["source_relative_path"] == "one.MP4"
    assert index["videos"][0]["byte_size"] == 3
    assert index["videos"][0]["sha256"] == hashlib.sha256(b"one").hexdigest()
    assert index["videos"][0]["duplicate_status"] == "near_duplicate"
    assert index["videos"][0]["duplicate_findings"] == [
        {"kind": "near", "video_id": "two", "distance": 0.0}
    ]
    assert json.loads(first_index) == json.loads(index_path.read_bytes())


def test_ingest_rejects_case_insensitive_stem_collision(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "One.mov").write_bytes(b"one")
    (source_dir / "one.mp4").write_bytes(b"one")
    metadata_path = tmp_path / "operator.yaml"
    _operator_metadata(metadata_path)

    with pytest.raises(IngestionError, match="case-insensitive stem"):
        ingest_dataset(
            source_dir,
            metadata_path,
            tmp_path / "manifest.yaml",
            tmp_path / "index.json",
            prober=_Probe(),
        )


def test_ingest_rejects_empty_source_and_unmatched_metadata(tmp_path: Path) -> None:
    source_dir = tmp_path / "empty-source"
    source_dir.mkdir()
    metadata_path = tmp_path / "operator.yaml"
    _operator_metadata(metadata_path)
    with pytest.raises(IngestionError, match="no supported videos"):
        ingest_dataset(
            source_dir,
            metadata_path,
            tmp_path / "manifest.yaml",
            tmp_path / "index.json",
            prober=_Probe(),
            fingerprinter=_Fingerprinter(),
        )

    (source_dir / "one.mov").write_bytes(b"one")
    metadata_path.write_text("videos:\n  typo:\n    session_id: capture-one\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="no matching source video"):
        ingest_dataset(
            source_dir,
            metadata_path,
            tmp_path / "manifest.yaml",
            tmp_path / "index.json",
            prober=_Probe(),
            fingerprinter=_Fingerprinter(),
        )


def test_ingest_refuses_outputs_inside_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "one.mov").write_bytes(b"one")
    metadata_path = tmp_path / "operator.yaml"
    _operator_metadata(metadata_path)

    with pytest.raises(IngestionError, match="source directory"):
        ingest_dataset(
            source_dir,
            metadata_path,
            source_dir / "manifest.yaml",
            tmp_path / "index.json",
            prober=_Probe(),
        )


def test_ingest_rejects_generated_asset_escape(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "one.mov").write_bytes(b"one")
    metadata_path = tmp_path / "operator.yaml"
    _operator_metadata(metadata_path)

    with pytest.raises(IngestionError, match="escapes the artifact directory"):
        ingest_dataset(
            source_dir,
            metadata_path,
            tmp_path / "manifest.yaml",
            tmp_path / "index.json",
            artifact_dir=tmp_path / "artifacts",
            prober=_Probe(),
            fingerprinter=_Fingerprinter(),
            preview_generator=_EscapingPreview(),
        )


def test_ingest_requires_operator_session_and_semantic_fields(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "one.mov").write_bytes(b"one")
    metadata_path = tmp_path / "operator.yaml"
    metadata_path.write_text("videos:\n  one: {}\n", encoding="utf-8")

    with pytest.raises(IngestionError, match="session_id"):
        ingest_dataset(
            source_dir,
            metadata_path,
            tmp_path / "manifest.yaml",
            tmp_path / "index.json",
            prober=_Probe(),
        )


def test_inspect_dataset_applies_stable_filters(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "one.mov").write_bytes(b"one")
    metadata_path = tmp_path / "operator.yaml"
    _operator_metadata(metadata_path)
    index_path = tmp_path / "index.json"
    ingest_dataset(
        source_dir,
        metadata_path,
        tmp_path / "manifest.yaml",
        index_path,
        prober=_Probe(),
        fingerprinter=_Fingerprinter(),
    )

    records = inspect_dataset(index_path, session_id="capture-one")

    assert [record["video_id"] for record in records] == ["one"]
    assert inspect_dataset(index_path, session_id="missing") == ()


def test_ingestion_index_rejects_unknown_top_level_fields(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text(
        '{"schema_version":"cardevent-ingestion-index/v1","videos":[],"x":1}',
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="unknown"):
        load_ingestion_index(path)


def test_ingestion_index_loader_requires_schema_fields(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "cardevent-ingestion-index/v1",
                "dataset_version_digest": "0" * 64,
                "videos": [{"video_id": "one"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="missing fields"):
        load_ingestion_index(path)
