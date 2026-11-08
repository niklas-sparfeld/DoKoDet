from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from doko_operations.derived_view import DerivedViewCache

SCRIPT = Path(__file__).parents[1] / "scripts" / "convert_0115_crop_cache.py"
SPEC = importlib.util.spec_from_file_location("convert_0115_crop_cache", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONVERTER)


def _legacy_ppm_entry(root: Path, key: str, content: bytes) -> None:
    digest = hashlib.sha256(content).hexdigest()
    entry = root / key
    entry.mkdir(parents=True)
    manifest = {
        "schema_version": "derived-view-cache/v1",
        "cache_key": key,
        "view_kind": "visible-region-crop/v1",
        "identity": {"output_encoding": "ppm", "image_sha256": digest, "points": [1.0, 2.0]},
        "content_sha256": digest,
        "byte_length": len(content),
    }
    (entry / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (entry / "content.bin").write_bytes(content)


def test_converter_preserves_snapshot_and_recovers_from_interruption(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    key = "a" * 64
    second_key = "b" * 64
    content = b"P6\n2 2\n255\n" + bytes(range(12))
    _legacy_ppm_entry(source, key, content)
    _legacy_ppm_entry(source, second_key, content + b"\0")
    frozen = CONVERTER.source_snapshot(source)
    assert DerivedViewCache(source).read(key) is None

    interrupted = tmp_path / "interrupted"
    try:
        CONVERTER.convert(
            source,
            interrupted,
            stop_after=1,
            expected_entries=2,
            expected_digest=frozen["source_digest"],
        )
    except InterruptedError:
        pass
    else:
        raise AssertionError("injected interruption did not stop conversion")
    assert (source / key / "content.bin").read_bytes() == content
    assert DerivedViewCache(interrupted).read(key) is not None
    assert DerivedViewCache(interrupted).read(second_key) is None

    converted = tmp_path / "converted"
    receipt = CONVERTER.convert(
        source,
        converted,
        expected_entries=2,
        expected_digest=frozen["source_digest"],
    )
    assert receipt["source_snapshot"]["source_digest"] == frozen["source_digest"]
    assert receipt["converted_entries"] == 2
    assert receipt["files"] == 4
    cache = DerivedViewCache(converted)
    entry = cache.read(key)
    assert entry is not None
    assert entry.content == content
    assert (
        entry.manifest["identity"]
        == json.loads((source / key / "manifest.json").read_text(encoding="utf-8"))["identity"]
    )

    (converted / key / "content.bin.gz").write_bytes(b"damaged")
    assert cache.read(key) is None
