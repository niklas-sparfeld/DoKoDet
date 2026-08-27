"""Shared domain types for the DokoDetector table-evidence boundary."""

from vision_detector.analyzer import AnalyzerEvidence, AnalyzerFrame, TableEvidenceAnalyzer
from vision_detector.cards import (
    CARD_IDENTITIES,
    CARD_SET_ID,
    CardIdentity,
    CardSetManifest,
    DeckCard,
    DeckManifest,
    load_card_set,
    load_deck_manifest,
)
from vision_detector.table_observation import (
    ANALYZER_CAPABILITIES,
    CALIBRATION_STATES,
    OBSERVATION_SCHEMA_VERSION,
    ContractError,
    IdentityCandidate,
    ObservationSession,
    ObservationSource,
    ObservedCard,
    TableObservation,
    canonical_json_bytes,
    parse_observation_bytes,
    validate_observation,
)

__all__ = [
    "CALIBRATION_STATES",
    "ANALYZER_CAPABILITIES",
    "CARD_IDENTITIES",
    "CARD_SET_ID",
    "CardIdentity",
    "CardSetManifest",
    "DeckCard",
    "DeckManifest",
    "AnalyzerEvidence",
    "AnalyzerFrame",
    "ContractError",
    "IdentityCandidate",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationSession",
    "ObservationSource",
    "ObservedCard",
    "TableObservation",
    "TableEvidenceAnalyzer",
    "canonical_json_bytes",
    "load_card_set",
    "load_deck_manifest",
    "parse_observation_bytes",
    "validate_observation",
]
