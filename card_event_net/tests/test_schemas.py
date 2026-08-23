from __future__ import annotations

import json
from pathlib import Path

from cardevent.annotation import EVENT_CONFIDENCES, EVENT_TYPES
from cardevent.manifest import (
    CAMERA_FRAMINGS,
    CAMERA_MOTIONS,
    CAMERA_VIEWS,
    CONTENT_TYPES,
    KNOWN_LIMITATIONS,
    LIGHTING_TAGS,
    MANIFEST_SCHEMA_VERSION,
    ORIENTATIONS,
    SCENARIO_TAGS,
    SOURCE_PERMISSIONS,
    SOURCES,
)

SCHEMAS_DIR = Path(__file__).parents[1] / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def test_annotation_schema_uses_runtime_event_values() -> None:
    schema = _load_schema("annotation-v1.schema.json")
    properties = schema["$defs"]["event"]["properties"]

    assert set(properties["type"]["enum"]) == EVENT_TYPES
    assert set(properties["confidence"]["enum"]) == EVENT_CONFIDENCES


def test_video_schema_uses_manifest_runtime_values() -> None:
    schema = _load_schema("video-metadata-v1.schema.json")
    assert schema["properties"]["schema_version"]["const"] == MANIFEST_SCHEMA_VERSION
    properties = schema["$defs"]["video"]["properties"]

    expected = {
        "content_type": CONTENT_TYPES,
        "orientation": ORIENTATIONS,
        "camera_view": CAMERA_VIEWS,
        "camera_motion": CAMERA_MOTIONS,
        "camera_framing": CAMERA_FRAMINGS,
        "lighting": LIGHTING_TAGS,
        "scenario_tags": SCENARIO_TAGS,
        "known_limitations": KNOWN_LIMITATIONS,
        "source": SOURCES,
        "source_permission": SOURCE_PERMISSIONS,
    }
    for key, values in expected.items():
        definition = properties[key]
        enum = definition["items"]["enum"] if "items" in definition else definition["enum"]
        assert set(enum) == values
