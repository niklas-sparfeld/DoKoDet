"""Deterministic local analyzer used by the round-recording proof of concept."""

from __future__ import annotations

from table_evidence_analyzer import (
    AnalyzerEvidence,
    ObservationSession,
    ObservationSource,
    TableEvidenceAnalyzer,
    TableObservation,
)
from table_evidence_analyzer.table_observation import AnalyzerMetadata

LOCAL_POC_ANALYZER_NAME = "deterministic-local"
LOCAL_POC_ANALYZER_VERSION = "v1"


class DeterministicLocalPoCAnalyzer:
    """Return a valid, deterministic observation without claiming recognition capability."""

    name = LOCAL_POC_ANALYZER_NAME
    version = LOCAL_POC_ANALYZER_VERSION

    def analyze(self, evidence: AnalyzerEvidence) -> TableObservation:
        """Convert accepted evidence into an explicit insufficient-evidence observation."""

        return TableObservation(
            schema_version="table-observation/v1",
            observation_id=f"{evidence.package_id}-observation",
            source=ObservationSource(package_id=str(evidence.package_id)),
            session=ObservationSession(
                session_id=str(evidence.package_id),
                event_sequence=1,
            ),
            observed_at_ms=evidence.event_time_ms,
            status="insufficient_evidence",
            capabilities=["identity_candidates"],
            cards=[],
            calibration="fixture",
            analyzer=AnalyzerMetadata(name=self.name, version=self.version),
            diagnostics={"mode": "deterministic_insufficient_evidence"},
        )


def create_local_poc_analyzer() -> TableEvidenceAnalyzer:
    """Create the fixed analyzer configured for the local round-recording PoC."""

    return DeterministicLocalPoCAnalyzer()


__all__ = [
    "LOCAL_POC_ANALYZER_NAME",
    "LOCAL_POC_ANALYZER_VERSION",
    "DeterministicLocalPoCAnalyzer",
    "create_local_poc_analyzer",
]
