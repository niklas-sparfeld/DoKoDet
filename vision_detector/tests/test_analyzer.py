from uuid import UUID

import pytest
from pydantic import ValidationError

from vision_detector import AnalyzerEvidence, AnalyzerFrame, TableEvidenceAnalyzer, TableObservation


def test_analyzer_input_is_visual_only_and_has_one_read_only_frame_source() -> None:
    evidence = AnalyzerEvidence(
        package_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
        event_time_ms=12000,
        frames=[
            AnalyzerFrame(
                part_name="frame_00",
                actual_offset_ms=-802,
                width=1920,
                height=1080,
                jpeg_bytes=b"fixture bytes",
            )
        ],
    )

    assert set(evidence.model_dump()) == {"package_id", "event_time_ms", "frames"}
    assert not hasattr(evidence, "session_id")
    with pytest.raises(ValidationError):
        AnalyzerEvidence.model_validate(
            {
                "package_id": str(evidence.package_id),
                "event_time_ms": evidence.event_time_ms,
                "frames": [],
                "session_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            }
        )
    with pytest.raises(ValidationError):
        AnalyzerFrame(
            part_name="frame_00",
            actual_offset_ms=0,
            width=1,
            height=1,
        )


def test_table_evidence_analyzer_protocol_accepts_analyzer_implementation() -> None:
    class FixtureAnalyzer:
        name = "fixture"
        version = "fixture-v1"

        def analyze(self, evidence: AnalyzerEvidence) -> TableObservation:
            del evidence
            return TableObservation.model_validate(
                {
                    "schema_version": "table-observation/v1",
                    "observation_id": "observation-001",
                    "source": {"package_id": "package-001"},
                    "session": {"session_id": "session-001", "event_sequence": 1},
                    "observed_at_ms": 1,
                    "status": "insufficient_evidence",
                    "capabilities": ["identity_candidates"],
                    "cards": [],
                    "calibration": "fixture",
                    "analyzer": {"name": "fixture", "version": "fixture-v1"},
                    "diagnostics": {},
                }
            )

    analyzer = FixtureAnalyzer()
    assert isinstance(analyzer, TableEvidenceAnalyzer)
    assert (
        analyzer.analyze(
            AnalyzerEvidence(package_id=UUID(int=0), event_time_ms=0, frames=[])
        ).schema_version
        == "table-observation/v1"
    )
