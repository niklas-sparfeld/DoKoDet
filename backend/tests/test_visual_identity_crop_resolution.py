from __future__ import annotations

import hashlib
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
