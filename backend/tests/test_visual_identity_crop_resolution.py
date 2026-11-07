from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import pytest
from doko_operations.derived_view import DerivedViewError

from dokodetector_backend import visual_identity_crop_resolution as resolution
from dokodetector_backend.visual_identity_crop_provenance import (
    crop_input_provenance,
    validate_crop_outcome,
)
from dokodetector_backend.visual_identity_pipeline_service import VisualIdentityPipelineService


def test_resolution_uses_exact_geometry_and_preserves_crop_fixture(monkeypatch, tmp_path: Path):
    frame_identity = {
        "requested_time_us": 1234,
        "output_encoding": "jpeg",
        "frame_index": 7,
    }
    geometry = {"kind": "fixture-geometry", "points": [[1, 2], [3, 4]]}
    fixture_bytes = b"fixture-crop-bytes"
    fixture_crop = SimpleNamespace(
        image_bytes=fixture_bytes,
        image_sha256=hashlib.sha256(fixture_bytes).hexdigest(),
        identity_mapping=lambda: {
            "status": "usable",
            "image_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
            "exclusion_inputs": [],
        },
    )
    frame = SimpleNamespace(identity_mapping=lambda: frame_identity)
    calls = {}
    monkeypatch.setattr(resolution, "parse_geometry", lambda value: value)
    monkeypatch.setattr(resolution, "resolve_exact_event", lambda *a, **kw: frame)

    def resolve_crop(_frame, actual_geometry, **kwargs):
        calls["geometry"] = actual_geometry
        calls["kwargs"] = kwargs
        return fixture_crop

    monkeypatch.setattr(resolution, "resolve_visible_region_crop", resolve_crop)
    crop = resolution.resolve_geometry_crop(
        video_path=tmp_path / "video.mp4",
        source=SimpleNamespace(),
        frame_identity=frame_identity,
        geometry=geometry,
        crop_policy="oracle_visible_region",
        output_encoding="ppm",
        resolver=SimpleNamespace(),
        cache=tmp_path / "cache",
        lock=RLock(),
    )

    assert crop.image_bytes == fixture_bytes
    assert resolution.crop_identity_mapping(crop) == {
        "status": "usable",
        "image_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
    }
    assert calls["geometry"] == geometry
    assert calls["kwargs"]["crop_policy"] == "oracle_visible_region"


def test_provenance_rejects_stale_input_and_geometry():
    expected = SimpleNamespace(
        input_kind="reviewed_visible_card",
        computed_manifest_digest="a" * 64,
        source_revision_id="revision-1",
        source_revision_digest="b" * 64,
        source_view_digest=None,
        source_node_id="node-1",
        source_node_revision_id="revision-1",
        schema_version="visual-identity-crop-input/v4",
    )
    geometry = {"kind": "fixture", "points": [[1, 2], [3, 4]]}
    item = SimpleNamespace(geometry=SimpleNamespace(to_mapping=lambda: geometry))
    outcome = SimpleNamespace(
        crop_input_provenance=SimpleNamespace(
            input_kind="reviewed_visible_card",
            manifest_digest="stale",
            source_revision_id="revision-1",
            source_revision_digest="b" * 64,
            source_view_digest=None,
            source_node_id="node-1",
            source_node_revision_id="revision-1",
            schema_version="visual-identity-crop-input-provenance/v3",
        ),
        geometry=SimpleNamespace(to_mapping=lambda: geometry),
    )

    with pytest.raises(DerivedViewError, match="lineage changed"):
        validate_crop_outcome(expected, item, outcome)

    outcome.crop_input_provenance = crop_input_provenance(expected, item)
    outcome.geometry = SimpleNamespace(to_mapping=lambda: {"kind": "stale"})
    with pytest.raises(DerivedViewError, match="geometry changed"):
        validate_crop_outcome(expected, item, outcome)


def test_reviewed_annotation_lookup_uses_frozen_geometry(monkeypatch, tmp_path: Path):
    geometry = {"kind": "reviewed-geometry", "points": [[1, 2], [3, 4]]}
    frame_identity = {"frame_index": 4, "requested_time_us": 8000}
    item = SimpleNamespace(
        card_id="card-1",
        geometry=SimpleNamespace(to_mapping=lambda: geometry),
        frame_identity=SimpleNamespace(to_mapping=lambda: frame_identity),
    )
    crop_input = SimpleNamespace(items=(item,))
    crop_identity = {
        "status": "usable",
        "image_sha256": "a" * 64,
        "crop_policy": "oracle_visible_region",
        "output_encoding": "ppm",
    }
    crop = SimpleNamespace(
        identity_mapping=lambda: {
            **crop_identity,
            "exclusion_inputs": [],
        }
    )
    calls = []
    monkeypatch.setattr(
        resolution,
        "resolve_geometry_crop",
        lambda **kwargs: calls.append(kwargs) or crop,
    )
    resolved = resolution.resolve_reviewed_annotation_crop(
        crop_input=crop_input,
        item_id="card-1",
        outcome={
            "card_id": "card-1",
            "frame_identity": frame_identity,
            "geometry": geometry,
            "crop_identity": crop_identity,
        },
        source=SimpleNamespace(),
        video_path=tmp_path / "video.mp4",
        resolver=SimpleNamespace(),
        cache=tmp_path / "cache",
        lock=RLock(),
    )
    assert resolved is crop
    assert calls[0]["geometry"] == geometry
    assert calls[0]["frame_identity"] == frame_identity


def test_reviewed_crop_context_caches_numeric_fingerprint_timestamp(tmp_path: Path):
    from table_evidence_analyzer.pipeline_data import VisibleCardData

    recording_id = "recording-1"
    bundle = tmp_path / "recording"
    bundle.mkdir()
    node_root = tmp_path / "nodes"
    (node_root / "node-1").mkdir(parents=True)
    source = SimpleNamespace(recording_id=recording_id)
    revision = SimpleNamespace(
        manifest=SimpleNamespace(
            recording_id=recording_id,
            content_type="visible_cards",
            producer=None,
            source=source,
        ),
        content=VisibleCardData(outcomes=()),
    )
    crop_input = SimpleNamespace(input_kind="reviewed_visible_card")
    service = object.__new__(VisualIdentityPipelineService)
    service._crop_context_lock = RLock()
    service._crop_contexts = OrderedDict()
    service._accepted_source = lambda _recording_id: (None, source)
    service._canonical_input_node_ref = lambda *_args: {
        "node_id": "node-1",
        "revision_id": "revision-1",
    }
    service.selection_store = SimpleNamespace(read_node_revision=lambda *_args: revision)
    service._freeze_crop_input = lambda *_args, **_kwargs: crop_input
    service.repository_storage = SimpleNamespace(bundle_path=lambda _recording_id: bundle)
    service.node_store = SimpleNamespace(root=node_root)
    service.run_store = SimpleNamespace()

    assert service._reviewed_crop_input_context(recording_id, "revision-1") == (
        revision,
        crop_input,
    )
    assert service._reviewed_crop_input_context(recording_id, "revision-1") == (
        revision,
        crop_input,
    )
    assert "reviewed:recording-1:revision-1" in service._crop_contexts
