from uuid import UUID

from table_evidence_analyzer import AnalyzerEvidence, canonical_json_bytes

from dokodetector_backend.poc_analyzer import (
    LOCAL_POC_ANALYZER_NAME,
    LOCAL_POC_ANALYZER_VERSION,
    DeterministicLocalPoCAnalyzer,
    create_local_poc_analyzer,
)


def test_local_poc_analyzer_is_deterministic_and_reports_insufficient_evidence() -> None:
    evidence = AnalyzerEvidence(
        package_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
        event_time_ms=1234,
        frames=[],
    )
    analyzer = create_local_poc_analyzer()

    first = analyzer.analyze(evidence)
    second = DeterministicLocalPoCAnalyzer().analyze(evidence)

    assert analyzer.name == LOCAL_POC_ANALYZER_NAME == "deterministic-local"
    assert analyzer.version == LOCAL_POC_ANALYZER_VERSION == "v1"
    assert first.status == "insufficient_evidence"
    assert first.cards == []
    assert first.observed_at_ms == evidence.event_time_ms
    assert first.source.package_id == str(evidence.package_id)
    assert first.analyzer.name == analyzer.name
    assert first.analyzer.version == analyzer.version
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
