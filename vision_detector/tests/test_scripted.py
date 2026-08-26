import json
from pathlib import Path
from uuid import UUID

import pytest

from vision_detector.contract import (
    VisionDiagnostics,
    VisionEvidence,
    VisionFrame,
    canonical_json_bytes,
)
from vision_detector.detector import VisionDetector
from vision_detector.scripted import (
    SCRIPTED_DETECTOR_NAME,
    SCRIPTED_DETECTOR_VERSION,
    ScriptedDetectorConfigurationError,
    ScriptedVisionDetector,
)

MAPPING_FIXTURE = Path(__file__).parents[2] / "fixtures" / "vision" / "v1" / "scripted-results.json"


def make_evidence(package_id: str, *, frame_count: int = 2) -> VisionEvidence:
    return VisionEvidence(
        package_id=UUID(package_id),
        event_time_ms=12000,
        frames=[
            VisionFrame(
                part_name=f"frame_{index:02d}",
                actual_offset_ms=index * 100 - 100,
                width=1920,
                height=1080,
                jpeg_bytes=f"fixture-jpeg-{index}".encode(),
            )
            for index in range(frame_count)
        ],
    )


@pytest.mark.parametrize(
    ("package_id", "status", "selected_card", "candidate_cards"),
    [
        (
            "550e8400-e29b-41d4-a716-446655440000",
            "uncertain",
            None,
            ["HEARTS_QUEEN", "DIAMONDS_QUEEN"],
        ),
        ("550e8400-e29b-41d4-a716-446655440010", "confident", "SPADES_ACE", ["SPADES_ACE"]),
        ("550e8400-e29b-41d4-a716-446655440011", "no_card_found", None, []),
        ("550e8400-e29b-41d4-a716-446655440001", "insufficient_evidence", None, []),
    ],
)
def test_scripted_detector_returns_each_configured_status(
    package_id: str,
    status: str,
    selected_card: str | None,
    candidate_cards: list[str],
) -> None:
    detector = ScriptedVisionDetector(MAPPING_FIXTURE)
    evidence = make_evidence(package_id)

    first = detector.detect(evidence)
    second = detector.detect(evidence)

    assert isinstance(detector, VisionDetector)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first.package_id == evidence.package_id
    assert first.status == status
    assert first.selected_card == selected_card
    assert [candidate.card for candidate in first.candidates] == candidate_cards
    assert first.detector.name == SCRIPTED_DETECTOR_NAME
    assert first.detector.version == SCRIPTED_DETECTOR_VERSION
    assert first.calibration == "fixture"
    assert first.diagnostics == VisionDiagnostics(frames_received=2, frames_decoded=0)


@pytest.mark.parametrize("frame_count", [0, 2])
def test_unmapped_package_returns_deterministic_insufficient_evidence(frame_count: int) -> None:
    detector = ScriptedVisionDetector(MAPPING_FIXTURE)
    evidence = make_evidence("550e8400-e29b-41d4-a716-446655440099", frame_count=frame_count)

    result = detector.detect(evidence)

    assert result.status == "insufficient_evidence"
    assert result.candidates == []
    assert result.selected_card is None
    assert result.calibration == "fixture"
    assert result.detector.name == "scripted"
    assert result.diagnostics.frames_received == frame_count
    assert result.diagnostics.frames_decoded == 0
    assert canonical_json_bytes(result) == canonical_json_bytes(detector.detect(evidence))


def test_scripted_detector_does_not_expose_or_mutate_excluded_context() -> None:
    detector = ScriptedVisionDetector(MAPPING_FIXTURE)
    evidence = make_evidence("550e8400-e29b-41d4-a716-446655440099", frame_count=1)
    original_bytes = evidence.frames[0].jpeg_bytes

    detector.detect(evidence)

    assert set(VisionEvidence.model_fields) == {"package_id", "event_time_ms", "frames"}
    assert not hasattr(evidence, "session_id")
    assert not hasattr(evidence, "event_sequence")
    assert not hasattr(evidence, "player_id")
    assert evidence.frames[0].jpeg_bytes == original_bytes
    assert isinstance(evidence.frames[0].jpeg_bytes, bytes)


def test_scripted_detector_version_is_deterministic_and_recorded() -> None:
    detector = ScriptedVisionDetector(MAPPING_FIXTURE, version="scripted-v2")
    evidence = make_evidence("550e8400-e29b-41d4-a716-446655440010")

    first = detector.detect(evidence)
    second = detector.detect(evidence)

    assert first.detector.version == "scripted-v2"
    v1_result = ScriptedVisionDetector(MAPPING_FIXTURE).detect(evidence)
    assert first.result_id != v1_result.result_id
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_invalid_scripted_mapping_is_rejected(tmp_path: Path) -> None:
    mapping_path = tmp_path / "scripted-results.json"
    mapping_path.write_text(json.dumps({"not-a-uuid": {}}), encoding="utf-8")

    with pytest.raises(ScriptedDetectorConfigurationError):
        ScriptedVisionDetector(mapping_path)
