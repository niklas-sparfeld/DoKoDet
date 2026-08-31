from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from table_evidence_analyzer.visible_card_prompt_pilot import (
    VISIBLE_CARD_PROMPT_PILOT_INPUT_SCHEMA,
    PromptPilotFrame,
    VisibleCardPromptPilotError,
    load_prompt_pilot_frames,
    run_prompt_pilot,
)
from table_evidence_analyzer.visible_cards import (
    IMPROVED_REQUEST_SCHEMA_VERSION,
    FakeVisibleCardProvider,
)


def _image(path: Path, colour: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (16, 12), colour)
    output = BytesIO()
    image.save(output, format="JPEG")
    path.write_bytes(output.getvalue())


def _frames(tmp_path: Path, count: int = 2) -> tuple[PromptPilotFrame, ...]:
    frames = []
    for index in range(count):
        path = tmp_path / f"frame-{index}.jpg"
        _image(path, (index * 30, 80, 120))
        frames.append(
            PromptPilotFrame(
                package_id=f"package-{index}",
                frame_part_name="frame_00",
                image=path,
                source_lineage_group=f"session-{index}",
            )
        )
    return tuple(frames)


def test_prompt_pilot_records_paired_requests_and_development_only_selection(
    tmp_path: Path,
) -> None:
    output = tmp_path / "pilot.json"
    report = run_prompt_pilot(
        _frames(tmp_path),
        FakeVisibleCardProvider(),
        output=output,
        selected_request_version=IMPROVED_REQUEST_SCHEMA_VERSION,
        selection_reason=(
            "The improved instruction makes visible-region and box semantics explicit."
        ),
        expected_frame_count=2,
    )

    assert report["schema_version"] == "visible-card-prompt-pilot/v1"
    assert report["frame_count"] == 2
    assert report["selection"]["selected_request_version"] == IMPROVED_REQUEST_SCHEMA_VERSION
    assert report["selection"]["scope"] == "development"
    assert set(report["selection"]["excluded_partitions"]) == {
        "validation",
        "challenge",
        "test",
        "system_holdout",
    }
    for frame in report["frames"]:
        requests = frame["request_versions"]
        assert set(requests) == {"visible-card-request/v1", "visible-card-request/v2"}
        assert (
            requests["visible-card-request/v1"]["request"]["image_sha256"]
            == requests["visible-card-request/v2"]["request"]["image_sha256"]
        )
        assert (
            requests["visible-card-request/v1"]["request_key"]
            != requests["visible-card-request/v2"]["request_key"]
        )
        assert requests["visible-card-request/v1"]["result"]["result_sha256"]
        assert requests["visible-card-request/v2"]["result"]["result_sha256"]
    assert json.loads(output.read_text(encoding="utf-8"))["selection"] == report["selection"]


def test_prompt_pilot_manifest_resolves_paths_and_rejects_non_development_frames(
    tmp_path: Path,
) -> None:
    image = tmp_path / "frame.jpg"
    _image(image, (10, 20, 30))
    manifest = tmp_path / "frames.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": VISIBLE_CARD_PROMPT_PILOT_INPUT_SCHEMA,
                "frames": [
                    {
                        "package_id": "package-001",
                        "frame_part_name": "frame_00",
                        "image": image.name,
                        "source_lineage_group": "session-001",
                        "partition": "validation",
                        "target_offset_ms": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(VisibleCardPromptPilotError, match="development frames"):
        load_prompt_pilot_frames(manifest)


def test_prompt_pilot_does_not_overwrite_a_report(tmp_path: Path) -> None:
    output = tmp_path / "pilot.json"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(VisibleCardPromptPilotError, match="already exists"):
        run_prompt_pilot(
            _frames(tmp_path),
            FakeVisibleCardProvider(),
            output=output,
            selected_request_version=None,
            selection_reason="No request selected.",
            expected_frame_count=2,
        )
