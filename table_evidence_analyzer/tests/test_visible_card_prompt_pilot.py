from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from table_evidence_analyzer.visible_card_prompt_pilot import (
    VISIBLE_CARD_PROMPT_PILOT_INPUT_SCHEMA,
    VISIBLE_CARD_PROMPT_PILOT_RENDER_SCHEMA,
    PromptPilotFrame,
    VisibleCardPromptPilotError,
    load_prompt_pilot_frames,
    render_prompt_pilot,
    run_prompt_pilot,
)
from table_evidence_analyzer.visible_cards import (
    IMPROVED_REQUEST_SCHEMA_VERSION,
    FakeVisibleCardProvider,
    NormalizedBox,
    NormalizedPoint,
    ProviderResult,
    VisibleCardProposal,
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


class _RenderProvider:
    name = "fixture"
    version = "fixture-v1"

    def propose(self, request: object) -> ProviderResult:
        package_id = request.package_id
        if package_id == "package-0":
            proposal = VisibleCardProposal(
                box_2d=NormalizedBox(y_min=200, x_min=100, y_max=700, x_max=500),
                polygon=(
                    NormalizedPoint(x=100, y=200),
                    NormalizedPoint(x=500, y=200),
                    NormalizedPoint(x=500, y=700),
                    NormalizedPoint(x=100, y=700),
                ),
                side="face_up",
                label="fixture card",
            )
            return ProviderResult(status="ok", proposals=(proposal,))
        if package_id == "package-1":
            return ProviderResult(status="ok")
        return ProviderResult(status="unavailable", error="fixture provider unavailable")


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


def test_prompt_pilot_renderer_writes_deterministic_paired_index_and_distinct_states(
    tmp_path: Path,
) -> None:
    pilot_path = tmp_path / "pilot.json"
    run_prompt_pilot(
        _frames(tmp_path, count=3),
        _RenderProvider(),
        output=pilot_path,
        selected_request_version=None,
        selection_reason="Fixture render only.",
        expected_frame_count=3,
    )

    output_dir = tmp_path / "rendered"
    index = render_prompt_pilot(pilot_path, output_dir)

    assert index["schema_version"] == VISIBLE_CARD_PROMPT_PILOT_RENDER_SCHEMA
    assert index["quality_claim"] is None
    assert index["creates_reviewed_reference_data"] is False
    assert index["frame_count"] == 3
    assert [frame["frame_id"] for frame in index["frames"]] == [
        "package-0:frame_00:0",
        "package-1:frame_00:0",
        "package-2:frame_00:0",
    ]

    states = {}
    for frame in index["frames"]:
        rendered_path = output_dir / frame["rendered_file"]["path"]
        assert rendered_path.is_file()
        assert frame["rendered_file"]["sha256"]
        assert frame["source"]["frame_sha256"]
        assert {
            version: frame["request_versions"][version]["result_sha256"]
            for version in ("visible-card-request/v1", "visible-card-request/v2")
        }
        states[frame["frame_id"]] = {
            version: frame["request_versions"][version]["status"]
            for version in ("visible-card-request/v1", "visible-card-request/v2")
        }

    assert states["package-0:frame_00:0"] == {
        "visible-card-request/v1": "ok",
        "visible-card-request/v2": "ok",
    }
    assert states["package-1:frame_00:0"] == {
        "visible-card-request/v1": "ok",
        "visible-card-request/v2": "ok",
    }
    assert states["package-2:frame_00:0"] == {
        "visible-card-request/v1": "unavailable",
        "visible-card-request/v2": "unavailable",
    }

    empty_path = output_dir / index["frames"][1]["rendered_file"]["path"]
    unavailable_path = output_dir / index["frames"][2]["rendered_file"]["path"]
    assert empty_path.read_bytes() != unavailable_path.read_bytes()
    with Image.open(output_dir / index["frames"][0]["rendered_file"]["path"]) as rendered:
        assert rendered.width > rendered.height
